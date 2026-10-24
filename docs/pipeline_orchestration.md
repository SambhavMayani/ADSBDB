# EcoSentinel — Orquestación y recuperación

**Responsabilidad:** ejecutar los scripts de las zonas en orden, detenerse ante fallos y producir evidencia auditable. **Entrada:** `python -m orchestration.pipeline`.

## 1. Integración del ZIP y cambios

El archivo original `ecosentinel_orchestration_v1.zip` tenía SHA-256 `43f9579a7fbc747a49bb94c1eb89bcd9b88b34c57e44d62314db4b73674bf141`. Sus cinco archivos eran nuevos y sus 47 pruebas iniciales pasaron en Windows. Se preservaron los puntos de entrada y las colecciones existentes.

La integración añade bloqueo independiente de la ruta de logs, UTF-8 Windows, timeout, terminación de procesos descendientes, redacción de secretos y conciliación final. El plan actual tiene **16 pasos**, o **19** con adquisición. También se corrigió un fallo previo: el generador del informe de imágenes no creaba el directorio de salida personalizado.

## 2. Plan de ejecución

| Etapa | Pasos |
|---|---|
| Storage | Comprobar conexión; crear solo los buckets que falten |
| Landing | Ingesta con Security Gate; promoción verificada a Persistent |
| Formatted | Imágenes, audio, texto |
| Trusted | Imágenes, audio, texto; manifiestos e informes |
| Exploitation | Cinco procesos secuenciales, uno por colección |
| Verification | Conciliar fuentes, hashes y cobertura de fragmentos |

La adquisición explícita ocurre antes de la ingesta. `--plan` no abre servicios, modelos ni informes; `--run` autoriza ejecutar el plan. No se arranca Docker ni se adquieren datos de fauna automáticamente.

```bash
python -m orchestration.pipeline --plan
python -m orchestration.pipeline --plan --with-acquisition
python -m orchestration.pipeline --plan --from-stage formatted --through-stage trusted
python -m orchestration.pipeline --run
python -m orchestration.pipeline --run --from-stage exploitation
```

Desde Exploitation se incluye la conciliación final. `--through-stage exploitation` la omite de manera explícita; `--from-stage verification` ejecuta solo la conciliación. Todos los hijos usan el mismo `sys.executable`, la raíz como `cwd` y argumentos en lista, sin shell. CPU es el dispositivo predeterminado.

**Después del pipeline:** `--run` termina al conciliar Trusted y el índice original; no arranca la web ni crea automáticamente la copia de consulta. Con el pipeline completado y los escritores detenidos, la primera instalación continúa con:

```bash
python -m orchestration.audit --source data/chromadb --snapshot data/search_index
python -m webapp.server
```

La instantánea copia y verifica la base vectorial existente; no recalcula embeddings ni duplica los medios originales. Search abre esa copia para proteger el índice original. El destino debe ser nuevo; una copia existente se reutiliza o se sustituye explícitamente por otra ruta nueva, sin sobrescribirla. Véase el [manual](user_guide.md) para el primer arranque completo y la actualización de la copia.

Antes del primer pipeline completo, preparar los modelos de embeddings con `python -m exploitation_zone.prepare_models --download` y comprobar la carga local con `python -m exploitation_zone.prepare_models`. Se descargan parámetros ya entrenados, no datos de fauna; no se entrenan modelos ni se calculan embeddings en ese paso. Los subprocesos del pipeline usan la caché con Hugging Face offline por defecto: `--with-acquisition` no habilita descargas de pesos. Qwen y BLIP se preparan aparte para Task 3 y no son necesarios para construir las zonas.

Sin `data/raw_dataset/`, configurar primero almacenamiento y proveedores (incluida `XENO_CANTO_API_KEY`) y ejecutar `python -m orchestration.pipeline --run --with-acquisition`. Con los archivos y sus `_metadata.json` locales, ejecutar `python -m orchestration.pipeline --run`; no se vuelven a adquirir datos de Internet. Si ya existe un estado S3/Chroma coherente, basta conciliar y preparar/reutilizar la copia de consulta. El [manual](user_guide.md) detalla requisitos, orden, resultados y recuperación de cada ruta.

## 3. Errores, retención y recuperación

- Un proceso con código distinto de cero detiene el plan; los pasos posteriores quedan `skipped`.
- Persistent devuelve fallo si algún objeto falla. Comprueba procedencia, tamaño y SHA-256 de ambas copias antes de marcar la promoción como completada.
- Un marcador existente no autoriza limpieza si falta o no coincide su destino Persistent.
- Trusted distingue un error operativo de un rechazo de calidad. Se conservan los activos históricos y se registra una propuesta de retirada, sin borrar automáticamente.
- Temporal se conserva por defecto. Solo `process_to_persistent.py --cleanup-temporal` solicita su limpieza tras verificar copia y marcador.
- Tras corregir la causa se reejecuta el plan. El estado de los objetos y registros decide qué trabajo falta, no el mero estado de un informe anterior.

No hay una transacción global entre zonas. La recuperación es por activo; la conciliación detecta fuentes sin vectores, referencias obsoletas, partes incompletas y checksums distintos, sin reconstruir ni borrar por su cuenta. La cantidad de embeddings no se equipara a la cantidad de archivos.

## 4. Concurrencia, timeout y RAM

El lock de sistema operativo está en `reports/orchestration/.pipeline.lock`, aunque se elija otro `--report-dir`. Cambiar la ruta de logs no permite eludirlo. Se libera al terminar el proceso: no se basa solo en la existencia de un archivo.

El alcance es local a esta copia del repositorio. Scripts manuales u otros equipos no adquieren automáticamente ese lock; no ejecutar escritores externos simultáneamente sobre los mismos almacenes.

`ECOSENTINEL_STEP_TIMEOUT` limita cada paso en segundos (3600 por defecto); debe ser positivo y finito. Un timeout termina el árbol de procesos y registra un fallo. Ctrl+C interrumpe el activo y omite los siguientes. Los procesos se aíslan con grupos/sesiones según Windows o POSIX. No es un supervisor externo durante una suspensión del equipo; los tiempos observados no deben interpretarse como una garantía de rendimiento.

Los modelos se cargan secuencialmente y el proceso termina entre colecciones. El indexador libera familias de encoders y limita los lotes textuales. El audio todavía se decodifica por archivo; no se promete RAM constante para cualquier duración.

## 5. Informes y secretos

Cada ejecución crea un JSON único y un log por paso. Se guardan estados, argumentos, códigos de salida, UTC y duración. El JSON se reemplaza atómicamente después de cada paso. Los estados son `pending`, `running`, `success`, `failed`, `interrupted` y `skipped`; el resultado final es `completed`, `failed` o `interrupted`.

Una terminación forzada puede dejar un informe `running`: se conserva como evidencia, no se convierte automáticamente en éxito. Los logs redactan credenciales configuradas; `.env`, datos e informes generados no se incorporan a Git. Los hijos producen UTF-8 sin buffering para evitar errores y pérdida de acentos en Windows.

## 6. Configuración y aislamiento

El cliente compartido se crea de forma perezosa, con timeout de conexión de 5 s, lectura de 60 s y hasta tres reintentos estándar. Landing, Formatted y Trusted comparten esta configuración; las fábricas públicas de las zonas se conservan como adaptadores. Se admite `S3_ENDPOINT_URL`, con respaldo `MINIO_ENDPOINT`. Las credenciales se cargan localmente y no se imprimen.

`ECOSENTINEL_LANDING_BUCKET`, `ECOSENTINEL_FORMATTED_BUCKET`, `ECOSENTINEL_TRUSTED_BUCKET`, `ECOSENTINEL_RAW_ROOT`, `ECOSENTINEL_CHROMA_PATH` y `ECOSENTINEL_REPORT_ROOT` permiten separar datos e informes. Por defecto se conserva la configuración histórica.

```bash
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
python -m pytest -m integration -q
python -m orchestration.smoke --run
python -m orchestration.smoke --run
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

El servicio de prueba usa el puerto 19000, credenciales desechables y ningún volumen de producción. `smoke` prepara tres activos sintéticos y ejecuta el CLI real con modelos ya en caché. Rechaza reutilizar una carpeta sin su marca de fixture. La segunda ejecución debe añadir cero vectores.

## 7. Evidencias y límites

Se ejecutó el CLI completo de 16 pasos con subprocesos, S3, Chroma y modelos CPU reales sobre datos sintéticos: tres activos generaron siete vectores y una conciliación correcta. La integración automatizada prueba también una segunda ejecución sin nuevas inferencias, con encoders deterministas.

La aceptación del corpus de referencia es distinta: lee MinIO y SQLite y consulta una copia. Confirma 198 activos, 6.021 vectores, cero inferencias necesarias en una repetición y los archivos originales intactos. Las pruebas rápidas, la integración de protocolos y la aceptación de modelos se documentan por separado en [validación](testing_and_validation.md).

Al recrear el servicio de pruebas se pierde su almacenamiento S3 efímero. Para una sesión nueva, utilizar `python -m orchestration.smoke --run --workdir data/smoke-session-02` (una carpeta aún no utilizada) y repetir con esa misma ruta. No reutilizar el índice de una sesión cuyo S3 fue retirado; conservarlo como evidencia.
