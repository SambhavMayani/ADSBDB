# EcoSentinel — Task 3: RAG con evidencias del corpus

Revisión: 24-10-2026. La Task 3 incorpora ahora recuperación **antes** de la generación. Se mantiene el comando antiguo de captioning como herramienta auxiliar y para compatibilidad; no debe confundirse con el nuevo RAG.

## 1. Correspondencia con el enunciado

La página 12 del enunciado (Constraint 14) pide tareas generativas con modelos externos usando los datos almacenados y anima a combinar las búsquedas previas. Las páginas 12–13 proponen recuperar referencias e incorporarlas al contexto del generador. El nuevo flujo implementa ese orden. Las imágenes se interpretan mediante BLIP y embeddings CLIP; el LLM recibe texto y metadatos, **no los píxeles directamente**. Es una adaptación multimodal con componentes separados para CPU, y no un VLM conversacional monolítico.

```text
Pregunta + imagen opcional (subida o seleccionada en Trusted)
    → validación de archivo y descripción visual BLIP, si hay imagen
    → comprobación conservadora de vocabulario del dominio
    → recuperación visual CLIP y textual E5 / CLIP
    → fusión RRF por activo y contexto limitado de fuentes
    → Qwen genera afirmaciones condicionadas por ese contexto
    → comprobación de JSON, fuentes y citas literales
    → respuesta con [S1], [S2]... o abstención explícita
```

Una pregunta de texto utiliza los documentos e imágenes del corpus sin requerir una imagen de entrada. Una imagen de Trusted se lee sin modificarla. La imagen externa de consulta permanece en memoria y no se indexa.

## 2. Arquitectura y modelos

| Módulo | Responsabilidad |
|---|---|
| `multimodal_tasks/rag.py` | Casos de uso, orden de etapas, exclusión de solicitudes concurrentes, CLI y trazas |
| `rag_policy.py`, `config/rag.yaml` | Configuración validada, presupuestos y fingerprint independiente del índice |
| `rag_evidence.py` | Selección de fuentes, contexto, mensajes e integridad de citas |
| `rag_query.py` | Consultas por aspectos, candidatas visuales y recuperación léxica acotada |
| `rag_model.py` | Preparación explícita y generación CPU offline con liberación del modelo |
| `generate.py` | Captioning BLIP auxiliar, conservado |
| `webapp/server.py` | HTTP local, selección de imágenes existentes y límites de petición |

El generador es `Qwen/Qwen2.5-3B-Instruct-GGUF`, archivo oficial `qwen2.5-3b-instruct-q4_k_m.gguf`, cuantización Q4_K_M y SHA-256 `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`, revisión `7dabda4d13d513e3e842b20f0d435c732f172cbe`. Se eligió por su soporte de instrucciones, salida estructurada y español, con un tamaño que permite una ejecución CPU acotada. Esta elección no procede de un benchmark comparativo ni implica superioridad frente a todos los modelos. No se exige una API externa: los pesos preentrenados se ejecutan localmente.

BLIP mantiene `Salesforce/blip-image-captioning-base` y la revisión `82a37760796d32b1411fe092ab5d4e227313294b`. CLIP y E5 reutilizan los contratos existentes. **No cambia ninguna de las cinco colecciones, sus fingerprints ni los 6.021 embeddings**. La nueva configuración RAG tiene su propio fingerprint.

## 3. Recuperación y construcción del contexto

Para imagen se consulta directamente su vector CLIP en el espacio compartido; la recuperación no depende solo de acertar la descripción BLIP. Las dos primeras coincidencias visuales aportan hasta dos especies candidatas. La descripción BLIP se conserva como observación no verificada y no se concatena a las consultas biológicas: un detalle espurio como «barbell» no debe desplazar su tema.

Se planifican consultas E5 por candidata y aspecto solicitado (hábitat, alimentación o comportamiento; perfil si no se reconoce uno), conservando una consulta global de respaldo. El filtro limita una búsqueda SOBRE una hipótesis; no identifica la fotografía. Se añade recuperación léxica sobre hasta 128 registros de texto ya indexados por candidata, sin leer vectores ni generar embeddings. Si el límite recorta la exploración se registra `lexical_scan_truncated`. Es una ayuda de recuperación, no una prueba de relevancia semántica.

Para texto se combinan E5 y CLIP mediante RRF con constante 60. Un nombre completo explícito de una única especie fija el tema; si compara varias no se fuerza una sola. La fusión cuenta una contribución por activo en cada lista, sin comparar valores de coseno y puntuaciones léxicas. Después se preservan hasta dos fragmentos distintos de un mismo activo: hábitat y dieta pueden estar en partes diferentes de un artículo. Cada referencia conserva su ID de registro, clave original y hash de extracto.

Se conservan hasta seis referencias, 1.400 caracteres por extracto y 4.800 en total, incluida una visual cuando existe. Para el prompt se seleccionan por separado hasta ocho unidades literales y 1.600 caracteres de evidencia, con hasta tres unidades por referencia. Se favorecen los aspectos preguntados y se reduce bibliografía ajena a la consulta; existe un respaldo cuando no se reconoce el vocabulario. Esto no demuestra entailment. Los extractos completos permanecen en las tarjetas. El generador comprueba además el presupuesto real de tokens.

Los mensajes separan instrucciones del sistema y fuentes serializadas como datos no confiables. No se proporcionan herramientas, acceso al sistema de archivos ni secretos al LLM. El aislamiento reduce el impacto de instrucciones maliciosas dentro de documentos; no constituye una garantía de obediencia perfecta del modelo.

## 4. Respuesta, citas y abstención

La salida solicitada al modelo es un objeto JSON con `answerable` y hasta dos afirmaciones breves. Cada afirmación contiene texto en español, ID de fuente y una cita literal. Antes de mostrarla se comprueba:

- estructura válida y límites de longitud;
- fuente existente dentro del contexto de esa solicitud;
- modalidad textual para afirmaciones factuales;
- cita de al menos 24 caracteres presente exactamente en el extracto indicado.

Además del validador posterior, llama.cpp recibe una gramática JSON construida para esa consulta. Los extractos se presentan como unidades literales de 24–240 caracteres, identificadas como S1Q1, S1Q2, etc. Los encabezados se separan para conservar, cuando cabe, la oración completa. El modelo elige primero un ID permitido y redacta su paráfrasis; el servidor resuelve ese ID a la fuente y a su cita original. No se pide al modelo que reconstruya las citas. La resolución conserva todas las afirmaciones y una referencia desconocida hace fallar la validación completa. La gramática y los IDs no comprueban que la paráfrasis esté semánticamente respaldada: esa limitación sigue siendo explícita.

Una respuesta inválida se descarta completa y devuelve `status=error`; una abstención por contenido devuelve `status=abstained`. Un JSON cortado por tiempo se indica como `generation_timeout`, y por tokens como `generation_token_limit`. El error no se presenta como ausencia de datos. Las candidatas y referencias recuperadas se muestran independientemente del generador. No se reparan JSON incompletos ni se convierten en éxitos aparentes. Las afirmaciones están limitadas a 240 caracteres tanto en la gramática como en el validador posterior.

Las preguntas multipartes utilizan una posición por aspecto en la gramática, en el orden indicado por el plan, con IDs de evidencia cuyo vocabulario corresponde a ese aspecto. Una posición sin respaldo puede ser `null`: se registra en `missing_aspects` y la salida es `status=partial`, sin presentarla como una respuesta completa. No se descartan silenciosamente afirmaciones inválidas. Los IDs por aspecto son una restricción léxica y estructural, no una comprobación semántica de la paráfrasis. Para una sola intención se permite una afirmación; se omiten unidades con paréntesis abiertos o finales claramente cortados.

**Alcance de la comprobación:** prueba que la cita existe y está asociada a una fuente entregada. No demuestra que la paráfrasis se deduzca de ella, que el documento sea verdadero ni que una especie esté correctamente identificada. Se requiere evaluación humana de esos aspectos.

La comprobación previa de dominio usa vocabulario y nombres del proyecto. Si la descripción no reconoce un concepto animal, se abstiene antes del LLM. Es una heurística conservadora, **no un detector OOD calibrado**: puede rechazar imágenes válidas o admitir entradas no pertinentes. Una pizza o coche descritos de forma inequívoca deben funcionar como ejemplos negativos; una descripción BLIP errónea puede cambiar la decisión.

## 5. Recursos y reproducibilidad

Se conserva un único `requirements.txt`; la recuperación y BLIP reutilizan Transformers/PyTorch, y la generación utiliza llama.cpp CPU con GGUF. No requiere CUDA, bitsandbytes, servicios de pago ni una base vectorial adicional. Se añade únicamente el runtime CPU `llama-cpp-python==0.3.36` y su dependencia ligera `diskcache==5.6.3` al mismo requirements. Se utilizan ruedas oficiales precompiladas para Windows/Linux x86_64; pip falla explícitamente si no existe una rueda, en lugar de iniciar una compilación C++ opaca.

Qwen se prepara en `data/model_cache/gguf/`, ignorado por Git, y se verifica su SHA-256 antes de cargarlo. El GGUF ocupa aproximadamente 2,1 GB y se abre mediante mmap, con cero capas GPU, cuatro hilos y contexto acotado. La cuantización es la oficial, no una conversión manual realizada al arrancar. Las pruebas exploratorias BF16 e INT8 con PyTorch se descartaron por lentitud y respuestas inválidas en este equipo; los informes fallidos se conservan como diagnóstico. La generación es sin muestreo, con hasta 320 tokens nuevos y 3.072 de entrada. El límite temporal de generación es 120 segundos; el criterio de parada nativo se comprueba entre tokens y **no equivale a un timeout duro de todo el proceso**, ni incluye descarga, recuperación o carga.

El control previo exige 2,5 GiB de RAM disponible antes de cargar el generador. Si falta memoria, devuelve un error recuperable indicando que se cierren otras aplicaciones; no inicia una carga que incumpla esa reserva. Este control no garantiza un máximo de RSS. Encoders de búsqueda y generador se cargan secuencialmente; el generador se libera al terminar. La latencia depende del hardware.

Se registran modelo/revisión, pregunta, hash de entrada, origen Trusted cuando corresponde, fuentes, IDs de registros, hash de extractos, fingerprint de política, hashes de prompt/contexto/salida y tiempos por etapa. La web no persiste consultas; un informe CLI se escribe solo mediante `--output`. Los logs de etapas no incluyen la pregunta ni el contenido de las fuentes.

## 6. Instalación y uso en Git Bash

Desde la raíz y con el entorno activo:

```bash
source .venv/Scripts/activate
python -m pip install -r requirements.txt

# Una vez: permite descargar solo los pesos del nuevo generador
python -m multimodal_tasks.rag_model --download

# Comprobación posterior sin Internet
python -m multimodal_tasks.rag_model

# Pregunta al corpus, sin imagen
python -m multimodal_tasks.rag --question "¿Cuál es el hábitat del lince ibérico?"

# Pregunta con una imagen externa, sin indexarla
python -m multimodal_tasks.rag --image ruta/imagen.jpg --question "¿Qué describen las fuentes sobre las especies candidatas?"

# Imagen ya almacenada: copiar una clave real de la interfaz
python -m multimodal_tasks.rag --trusted-key 'images/lynx_pardinus/CLAVE_REAL.jpg' --question "¿Qué hábitat describen las fuentes?"

# Exportación explícita del resultado
python -m multimodal_tasks.rag --question "Hábitat del lince ibérico" --output reports/validation/mi_rag.json

python -m webapp.server
```

En `http://127.0.0.1:8765`, abrir **Preguntar al corpus · RAG**, introducir una pregunta y elegir opcionalmente una imagen de Trusted o subir otra. Los enlaces [S1] llevan a las tarjetas con extracto y procedencia. Las candidatas se muestran como hipótesis por similitud, incluso si falla la generación. «Qué animal es» permite describir una candidata condicionalmente si los textos respaldan su nombre; no confirma la especie de la foto. BLIP se muestra aparte. El diagnóstico incluye unidades/caracteres de contexto, tokens, tiempo y motivo de cierre.

Las cuatro familias de embeddings y BLIP deben estar preparadas según las guías anteriores. No hay descargas implícitas desde la web. `generate.py` sigue disponible para obtener únicamente una descripción con BLIP, pero la experiencia principal de Task 3 es ahora `rag.py`.

## 7. Validación y evaluación

```bash
python -m pytest tests/test_rag.py -q
python -m pytest -q

# Aceptación real con el corpus, modelos locales y una imagen de Trusted
python -m orchestration.validate_rag --run

# Regresiones específicas con una imagen real de rana de Trusted
python -m orchestration.validate_rag --run --case frog-image --case frog-identification
```

Las pruebas automatizadas utilizan generadores y captioners controlados, además de una integración con Chroma temporal real y HTTP de loopback. Verifican recuperación antes de generación, contexto limitado, citas inexistentes/inventadas, metadatos visuales no aptos para sustentar hechos, entrada inválida, abstención, concurrencia, recuperación tras fallo y protección de RAM. No descargan modelos ni acceden al MinIO de producción.

La aceptación real es independiente: incluye hábitat del lince, una imagen de lince de Trusted, descripción e identificación condicional con una imagen de rana, una pregunta no cubierta (genoma completo) y una consulta ajena al dominio. Compara hashes del índice original y contadores de la copia. El informe conserva la salida después de resolver los IDs de evidencia, solo para diagnóstico, y el hash de la salida nativa. Se escribe incrementalmente en `reports/validation/rag_acceptance.json`. Un fallo de memoria o de generación figura como fallo, no como validación superada. Las pocas muestras no constituyen un benchmark taxonómico.

Para una evaluación académica sólida, revisar manualmente relevancia de recuperación, correspondencia de cada afirmación con su cita y comportamiento ante preguntas sin respuesta. Los tests estructurales y el uso de RAG no demuestran por sí solos precisión factual. El estado observado de cada ejecución se recoge en [testing_and_validation.md](testing_and_validation.md).

| Dimensión | Criterio de revisión |
|---|---|
| Recuperación | Las fuentes tratan la especie y el aspecto preguntado; una puntuación de similitud no basta |
| Fundamentación | Cada afirmación se deduce de su cita completa, sin añadir localizaciones, cifras ni causalidad |
| Utilidad | Respuesta en español, pertinente, sin repetir la misma idea y con referencias navegables |
| Abstención | Una consulta ajena al dominio se detiene antes del LLM; una pregunta no cubierta permite abstención del modelo |
| Entrada visual | La descripción es provisional y las referencias no se presentan como identificación confirmada |
| Conservación | Hashes originales y contadores permanecen iguales; ninguna consulta se indexa |

La aceptación automática registra estructura y conservación; la revisión semántica de unos ejemplos es cualitativa. No se publica una cifra de accuracy ni una evaluación poblacional a partir de estos pocos casos.

## 8. Fuentes

- Enunciado local, páginas 2 y 12–13, Constraint 14 y ejemplo RAG.
- [Modelo Qwen2.5-3B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF).
- [Runtime llama-cpp-python y ruedas CPU](https://github.com/abetlen/llama-cpp-python#installation).
- [Commit fijo de Qwen](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/commit/7dabda4d13d513e3e842b20f0d435c732f172cbe).
- [BLIP y ejemplo CPU](https://huggingface.co/Salesforce/blip-image-captioning-base).

Continuación: [Tasks 1/2](multimodal_tasks_documentation.md) · [Exploitation](exploitation_zone_documentation.md) · [Índice](README.md).

El modelo GGUF oficial declara licencia Qwen Research; revisar su ficha al reutilizarlo fuera del contexto académico. No se publica el modelo ni el dataset en el repositorio.
