# Guion de demostración y reproducción

Ejecutar desde la raíz del repositorio con `.venv` de Python 3.11 activado. En PowerShell: `.\.venv\Scripts\Activate.ps1`; en Git Bash: `source .venv/Scripts/activate`. Ver el README para la instalación CPU y la configuración local. Nunca compartir `.env`.

## 1. Comprobar el estado sin alterar los datos

```bash
python -m pip check
python -m orchestration.audit
python -m orchestration.pipeline --plan
python -m orchestration.reconcile
```

Mostrar 198 activos aceptados y las cinco colecciones: 100 + 357 + 547 + 1.763 + 3.254 = 6.021. La auditoría y la conciliación leen SQLite sin arrancar Chroma sobre el original. `--plan` no ejecuta los pasos.

Si no existe una copia para consultas, crearla una sola vez, con otros escritores detenidos:

```bash
python -m orchestration.audit --snapshot data/search_index
```

Se rechaza sobrescribir una copia existente. Las consultas posteriores usan esa copia; una instantánea representa el momento de su creación y no se actualiza sola.

## 2. Interfaz y Tasks 1 y 2

```bash
python -m webapp.server
```

Abrir `http://127.0.0.1:8765`. Primera carga de cada modelo: esperar y evitar consultas simultáneas. La aplicación funciona en CPU, escucha únicamente en loopback y requiere los modelos en caché.

| Pestaña / acción | Qué demuestra |
|---|---|
| Texto → `Task 1 · texto a texto · E5` | Recuperación del mismo tipo |
| Archivo → `Task 1 · misma modalidad` | Una imagen recupera imágenes; un audio recupera audios |
| Tarjeta → `Similares del mismo tipo` | Task 1 desde un activo indexado, excluyendo todos sus fragmentos |
| Texto → `Imagen + texto · CLIP` | Task 2 en una colección compartida, con resultados de imagen y texto |
| Texto → `Audio + texto · CLAP` | Task 2 con audio y texto |
| Archivo → `Task 2 · modalidades combinadas` | Consulta externa en espacio compartido |
| Tarjeta → `Relacionar con otros tipos` | Task 2 desde un activo ya indexado |
| Texto → `Todas las modalidades` | Fusión de rankings entre espacios mediante RRF |

Ejemplo: `Iberian lynx in Mediterranean forest`, CLIP, sin filtro de modalidad. Abrir la procedencia de una imagen y un texto. Explicar que varios fragmentos del mismo activo se agrupan y que una política de diversidad reserva modalidades. El orden es un ranking de recuperación, no una clasificación biológica validada. RRF combina posiciones; no compara directamente distancias de encoders diferentes.

## 3. Task 3

En `Describir`, seleccionar una imagen de fauna. BLIP produce una descripción automática en inglés y CLIP busca referencias para contrastarla. Mostrar la descripción y las fuentes; explicar una posible imprecisión. No afirmar que es RAG ni que reconoce correctamente la especie.

Alternativa CLI, tras preparar el modelo según la guía de Task 3:

```bash
python -m multimodal_tasks.generate --help
python -m orchestration.validate_reference --models --task3
```

La aceptación usa un archivo del corpus en lectura y produce un informe local con modelo, revisión y referencias. No añadir `--allow-model-download` salvo que se quiera autorizar explícitamente la descarga de pesos.

## 4. Pipeline y pruebas con escritura aislada

```bash
python -m pytest -q
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
python -m pytest -m integration -q
python -m orchestration.smoke --run
python -m orchestration.smoke --run
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

Usar únicamente el compose de pruebas en este bloque. La prueba completa requiere los modelos en caché y procesa tres activos sintéticos, por lo que no sirve para evaluar calidad ecológica. Mostrar los 16 pasos, el informe de conciliación y cero embeddings nuevos en la segunda ejecución. Para detener el servidor web: `Ctrl+C` en su terminal.

## 5. Cierre de la exposición

Mostrar los informes locales y el workflow de GitHub, diferenciando resultados observados de configuración. Explicar los límites: sin benchmark biológico etiquetado, generación susceptible de errores, modelos históricos con revisión originalmente nula y consumo de memoria dependiente de los archivos. La memoria final debe ajustarse al formato y límite oficial.

Al recrear el servicio de pruebas se pierde su almacenamiento S3 efímero. Para una sesión nueva, utilizar `python -m orchestration.smoke --run --workdir data/smoke-session-02` (una carpeta aún no utilizada) y repetir con esa misma ruta. No reutilizar el índice de una sesión cuyo S3 fue retirado; conservarlo como evidencia.
