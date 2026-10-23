# EcoSentinel — Tasks 1 y 2: búsqueda por similitud

**Responsabilidad:** consultar los datos de Exploitation sin alterar el dataset, mostrando resultados agrupados por activo y con procedencia. **Código:** `multimodal_tasks/search.py`. **Interfaz:** `webapp/`.

## 1. Diferencia entre las dos tareas

| Tarea | Entrada | Salida | Espacio |
|---|---|---|---|
| Task 1 | Imagen | Otras imágenes | CLIP visual |
| Task 1 | Audio | Otros audios | CLAP acústico |
| Task 1 | Texto | Otros textos | E5 |
| Task 2 | Texto o imagen | Imágenes y textos | CLIP alineado |
| Task 2 | Texto o audio | Audios y textos | CLAP |
| Extensión Task 2 | Texto | Imágenes, audios y textos | Fusión de E5, CLIP y CLAP |

Task 2 requiere demostrar una **mezcla de formatos recuperados**. Una consulta de texto que devuelve únicamente imágenes no basta para cubrir todo ese requisito. Las pruebas verifican explícitamente imagen + texto y audio + texto.

## 2. De la consulta al resultado

1. Validar consulta, filtros, tamaño y número de resultados.
2. Construir el embedding con el encoder compatible. En texto E5 se añade `query:`.
3. Consultar mediante `query_embeddings`, sin activar una función de embedding predeterminada de Chroma.
4. Filtrar por especie/modalidad cuando se solicite.
5. Agrupar ventanas o fragmentos por `asset_id`: un texto largo no ocupa toda la lista.
6. Devolver la fuente, modalidad, especie, snippet, puntuación y espacio utilizado.

Las referencias del propio índice reutilizan su vector persistido. Se excluye **todo el activo de referencia**, no solo el fragmento usado, para evitar que otro fragmento del mismo documento aparezca como supuesto descubrimiento.

Con hasta 64 candidatos se leen los vectores y se calcula coseno exacto en memoria; por encima se usa HNSW mediante `query_embeddings`. La lectura exacta está acotada y evita depender de un segmento HNSW aún sin materializar para colecciones muy pequeñas. No se captura ni oculta un error de almacenamiento, ni se reconstruye el índice. Hay pruebas independientes de ambas rutas.

Las consultas externas de imagen/audio se procesan en memoria y no se incorporan al índice. El audio de consulta admite hasta 30 segundos y ocho canales; la web limita archivos a 10 MB e imágenes a 20 MP. Los originales de MinIO permanecen intactos.

## 3. Qué significa «ranking»

Es la lista ordenada de resultados más parecidos a una consulta. En una sola colección se usa similitud coseno (`1 − distancia`). No es una probabilidad, una certeza de especie ni una nota de calidad del archivo.

Cuando se consultan modelos distintos, sus distancias no son directamente comparables. Para combinar las listas se utiliza **Reciprocal Rank Fusion**, con `k = 60`:

```text
puntuación de un activo = suma de 1 / (60 + posición en cada lista)
```

Solo se suma una contribución por activo y lista. Una posición alta en varias búsquedas puede elevar el resultado combinado. Se etiqueta la puntuación como `rrf`; no se presenta como coseno ni como porcentaje de acierto.

## 4. Diversidad de modalidades

Sin una política de presentación, los numerosos fragmentos textuales pueden dominar los primeros resultados de una colección mixta. Por eso, cuando no se solicita una modalidad concreta y hay suficientes plazas, la búsqueda reserva cuotas por modalidad disponible.

En imagen–texto, ocho resultados pueden contener cuatro imágenes y cuatro textos. En la vista federada se reparten plazas entre imagen, audio y texto; si una modalidad no aporta suficientes activos, se completan con otros resultados. Dentro de cada modalidad se conserva su orden de similitud y la lista final mantiene el orden de puntuación entre los candidatos elegidos.

Esta es una **decisión de diversificación**, no la afirmación de que la lista mostrada sea el top-k puro global. Con un resultado no se puede mostrar una mezcla. Si se activa un filtro de modalidad, no se impone mezcla.

## 5. Ejecución desde terminal

Preparar una instantánea como se explica en [Exploitation](exploitation_zone_documentation.md). Desde la raíz y el entorno virtual:

```bash
python -m multimodal_tasks.search --status

# Task 1: texto → texto
python -m multimodal_tasks.search --query "Hábitat del lince ibérico" --space text

# Task 2: texto → imágenes y textos
python -m multimodal_tasks.search --query "Iberian lynx in its natural habitat" --space image_text

# Task 2: texto → audios y textos
python -m multimodal_tasks.search --query "owl calling at night" --space audio_text

# Extensión: tres modalidades combinadas
python -m multimodal_tasks.search --query "birds near a river" --space multimodal

# Filtro de especie
python -m multimodal_tasks.search --query "lince" --space image_text --species lynx_pardinus

# Consultas externas: no se indexan
python -m multimodal_tasks.search --file ruta/imagen.jpg --modality images
python -m multimodal_tasks.search --file ruta/imagen.jpg --modality images --mixed
python -m multimodal_tasks.search --file ruta/audio.flac --modality audio --mixed

# Referencia del índice: copiar un id devuelto por otra consulta
python -m multimodal_tasks.search --record ID_DEL_REGISTRO --space images
```

`--space images` corresponde a IDs de la colección monomodal. Los IDs son diferentes entre espacios; la interfaz resuelve automáticamente el mismo `asset_id` cuando se pulsa «Similares del mismo tipo» o «Relacionar con otros tipos».

## 6. Pruebas desde la interfaz

```bash
python -m webapp.server
```

Abrir `http://127.0.0.1:8765`:

- **Explorar por texto:** elegir texto a texto para Task 1, un espacio mixto para Task 2 o todas las modalidades para la búsqueda federada.
- **Buscar similares:** seleccionar imagen o audio; elegir misma modalidad o modalidades combinadas.
- En una tarjeta, **Similares del mismo tipo** prueba Task 1 y **Relacionar con otros tipos** prueba Task 2.
- Desplegar **Fuente y trazabilidad** para comprobar clave, origen, espacio y puntuación.

La interfaz no permite modificar ni reindexar datos. Sirve solo en loopback, limita y serializa consultas CPU, valida origen HTTP y no muestra errores internos ni credenciales al navegador. Los medios se leen de Trusted bajo claves validadas. El modelo generativo se documenta [por separado](generative_tasks_documentation.md).

## 7. Cómo se han probado

```bash
python -m pytest tests/test_search_and_web.py -q
python -m orchestration.validate_reference --models
```

La suite de búsqueda usa Chroma real con vectores deterministas en una carpeta temporal: mezcla de modalidades, filtros, referencia excluida, agrupación, consultas vacías, límites, ausencia de resultados y API HTTP. No usa los datos de referencia ni descarga pesos.

La aceptación real utiliza una copia de los 6.021 embeddings y encoders reales en CPU. En la ejecución del 23-10-2026:

| Consulta | Resultado comprobado |
|---|---|
| Referencia de imagen, audio y texto | Cinco activos similares por modalidad, sin devolver el activo de entrada |
| Texto E5 sobre hábitat del lince | Ocho textos; el primer resultado correspondía a `lynx_pardinus` |
| `Iberian lynx in its natural habitat` | Ocho resultados, imágenes y textos de `lynx_pardinus` |
| `owl calling at night` | Ocho resultados de audio y texto |
| `birds near a river` | Ocho resultados con imagen, audio y texto |

La evidencia completa se guarda en `reports/validation/reference.json`, ignorado por Git. Contiene consultas, modalidades, especies, tiempos y comprobación de preservación del índice. Los tiempos incluyen carga de modelos y varían por caché y equipo; no son un benchmark estable.

## 8. Límites y decisiones

- La similitud no valida identificación biológica: algunas búsquedas devuelven especies distintas.
- CLAP está orientado principalmente a descripciones inglesas; se incluyen ejemplos en inglés sin traducir los documentos originales.
- La agrupación pierde la presentación simultánea de todas las ventanas coincidentes; se conserva el fragmento más relevante.
- Descargar pesos, indexar y consultar son operaciones distintas. Las consultas están configuradas para usar la caché local.
- La copia de búsqueda no se actualiza automáticamente al cambiar el índice. Crear una nueva instantánea con escritores detenidos y cambiarla de forma explícita.
- El servicio HTTP de la biblioteca estándar está pensado para la demostración local; exponerlo a Internet requeriría un despliegue y controles adicionales.

**Continuación:** [Exploitation](exploitation_zone_documentation.md) · [Task 3](generative_tasks_documentation.md) · [Validación](testing_and_validation.md).
