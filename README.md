# EcoSentinel

Plataforma multimodal de fauna ibérica para la P1 de ADSDB (UPC). Gestiona imágenes, audio y texto con una arquitectura por zonas, trazabilidad, controles de calidad y búsquedas con modelos preentrenados en CPU.

## Estado comprobado

- 198 activos aceptados en Trusted: 100 imágenes, 34 audios y 64 textos.
- Cinco colecciones persistentes y 6.021 embeddings en `data/chromadb/`.
- Orquestación secuencial con logs, bloqueo, límites de tiempo y conciliación final.
- Tasks 1 y 2: consultas monomodales, multimodales y combinación de resultados con procedencia.
- Task 3: descripción generativa con BLIP y recuperación de referencias.
- Interfaz local con tres recorridos para probar las Tasks.
- Pruebas aisladas, integración con S3 y Chroma reales y aceptación con modelos CPU.
- GitHub Actions configurado para Windows y Ubuntu. La ejecución remota se comprueba en GitHub tras publicar la rama; no se confunde con los resultados locales.

Los resultados y límites detallados están en [validación](docs/testing_and_validation.md). El proyecto prioriza calidad del sistema; la similitud no equivale a identificación biológica verificada.

## Arquitectura

```text
Adquisición opcional → raw_dataset → Security Gate
    → Temporal Landing → Persistent Landing
    → Formatted (JPEG / FLAC PCM16 / TXT UTF-8)
    → Trusted (calidad, duplicados y manifiestos)
    → Exploitation (CLIP / CLAP / E5, Chroma persistente)
    → Tasks 1, 2 y 3 → interfaz local
```

Persistent conserva los originales. Una revalidación de calidad no elimina automáticamente los activos previamente aceptados. Las consultas usan una **copia independiente del índice**; no abren la persistencia original mediante el cliente Chroma.

## Instalación: Windows / Git Bash

Requisitos: Python 3.11 de 64 bits, Docker Desktop para MinIO y un entorno virtual. Desde la raíz del repositorio:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m pip check
cp -n .env.example .env
```

En PowerShell, activar con `.\.venv\Scripts\Activate.ps1`. Configurar las credenciales **solo en `.env`**, sin subirlo a Git. El único fichero de dependencias es `requirements.txt`; contiene las versiones directas comprobadas. No se requieren CUDA ni Tesseract para el funcionamiento básico.

En Linux, se puede instalar primero la rueda CPU de la versión de PyTorch indicada en `requirements.txt` desde el índice oficial de PyTorch y después instalar el mismo requirements. La CI usa ese procedimiento para evitar dependencias CUDA innecesarias. La reproducción completa de versiones transitivas debe verificarse en el entorno nuevo; un pin directo no sustituye esa comprobación.

```bash
docker compose up -d
python orchestration/check_minio_connection.py
```

La imagen del servicio actual es SILO, compatible con la API S3 de MinIO. Se conserva la configuración y el volumen existentes. **No utilizar `docker compose down -v` sobre el proyecto de datos.**

## Primera ejecución segura sobre un repositorio con datos

```bash
# Plan puro: no abre servicios ni modifica datos
python -m orchestration.pipeline --plan

# Verificación de lectura, sin crear embeddings
python -m orchestration.reconcile

# Inventario SQLite de solo lectura
python -m orchestration.audit --source data/chromadb
```

No es necesario reindexar el corpus validado. Cambiar modelos o contratos v1 requiere una estrategia de versionado explícita.

## Probar las Tasks y la interfaz

Con los escritores del índice detenidos, crear una instantánea **una vez**:

```bash
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m multimodal_tasks.search --status
python -m webapp.server
```

Abrir `http://127.0.0.1:8765`. La herramienta rechaza sobrescribir una instantánea existente: para refrescarla, usar otra ruta y `--index RUTA` al iniciar el servidor. Los medios siguen leyéndose del MinIO local.

- **Explorar por texto:** texto a texto, espacios mixtos o todas las modalidades.
- **Buscar similares:** imagen/audio de consulta; misma modalidad o modalidades combinadas.
- **Describir una imagen:** BLIP genera una descripción y recupera referencias.
- Cada resultado permite consultar procedencia y buscar activos relacionados.

Los encoders de búsqueda requieren sus pesos en la caché local. Los commits observados están en `config/model_manifest.json` y se usan para resolver las revisiones nulas históricas sin cambiar fingerprints. La preparación no indexa datos:

```bash
python -m exploitation_zone.prepare_models --download
# Verificar después sin permitir descargas
python -m exploitation_zone.prepare_models
```

El flag `--download` autoriza Internet para preparar pesos; la operación habitual es offline. Para BLIP:

```bash
python -m multimodal_tasks.generate ruta/imagen.jpg --allow-model-download
```

No se necesitan claves de un proveedor generativo. Las consultas externas no se guardan ni se indexan.

## Pipeline automático

La siguiente operación **escribe** en las zonas e indexa entradas pendientes. Revisar primero el plan y preservar una copia coherente del índice:

```bash
python -m orchestration.pipeline --plan
python -m orchestration.pipeline --run
```

La adquisición de nuevos datos desde Internet solo se añade con `--with-acquisition`. La preparación de pesos es una decisión independiente. Para reanudar después de corregir un fallo:

```bash
python -m orchestration.pipeline --run --from-stage exploitation
```

La recuperación se apoya en objetos, marcadores y registros completos; no salta un paso solo porque un informe anterior lo marcó como correcto. El borrado de Temporal está desactivado por defecto; su limpieza explícita solo se permite tras verificar copia, procedencia y checksum. [Detalles](docs/pipeline_orchestration.md).

## Pruebas reproducibles

```bash
# Pruebas sin Internet ni MinIO de producción
python -m pytest -q

# Servicio de prueba separado: puerto 19000, sin volumen de producción
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
python -m pytest -m integration -q

# Aceptación CLI completa con modelos reales ya en caché y datos sintéticos
python -m orchestration.smoke --run
python -m orchestration.smoke --run

# Cerrar únicamente el servicio de prueba
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

La integración usa buckets efímeros con nombres controlados y nunca el puerto 9000. La aceptación de tu corpus existente utiliza lecturas y una copia del índice:

```bash
python -m orchestration.validate_reference --models --task3
```

Los informes de tests, logs y evidencias locales se guardan en `reports/validation/`; datos, pesos, secretos e índices se excluyen de Git. Los informes Trusted se conservan fechados y deben interpretarse según el dataset de cada ejecución.

## Documentación

El [índice de `docs/`](docs/README.md) organiza los documentos de Landing, Formatted, Trusted, Exploitation, Tasks, operación, pruebas, requisitos oficiales y demostración. `docs/decision_log.md` conserva las decisiones históricas y añade las nuevas sin renumerarlas.

## Límites conocidos

No existe benchmark anotado de precisión taxonómica, ni transacción distribuida entre todas las zonas. La lectura del corpus para comprobar idempotencia sigue teniendo coste. El audio se decodifica por archivo; el consumo no es constante para duraciones arbitrarias. Las consultas usan una instantánea que se refresca explícitamente. La web está destinada a ejecución local, sin publicación en Internet.

Al recrear el servicio de pruebas se pierde su almacenamiento S3 efímero. Para una sesión nueva, utilizar `python -m orchestration.smoke --run --workdir data/smoke-session-02` (una carpeta aún no utilizada) y repetir con esa misma ruta. No reutilizar el índice de una sesión cuyo S3 fue retirado; conservarlo como evidencia.
