# EcoSentinel — Testing y evidencias de validación

Revisión local: 23-10-2026, Windows, Python 3.11.2, `.venv`, CPU, almacenamiento S3 compatible con MinIO. Los informes generados viven fuera de Git. Los comandos se ejecutan desde la raíz del repositorio.

## 1. Resultados observados

| Nivel | Resultado | Evidencia local |
|---|---|---|
| Suite offline | **229 passed, 1 deselected**, 46,66 s con cobertura | `reports/validation/offline.xml`, `coverage.xml` |
| Integración real S3 + Chroma | **1 passed, 229 deselected**, 29,73 s; incluye dos ejecuciones | `reports/validation/integration.xml` |
| Cobertura offline | **60 %** del conjunto de módulos incluidos | `coverage.xml` |
| Cobertura offline + integración | **69 %**, 4.618 sentencias, 1.448 sin cubrir | `coverage_combined.xml` |
| Pipeline CLI con modelos CPU reales | **16/16 pasos**; tres activos sintéticos, siete vectores | `data/smoke/reports/orchestration/pipeline_20261023T174607_756172Z_1ded064b.json` |
| Segunda ejecución del mismo CLI | **16/16 pasos**, cero subidas Trusted y cero vectores nuevos | `data/smoke/reports/orchestration/pipeline_20261023T175638_718645Z_798fbd1b.json` |
| Aceptación del corpus | **198 activos, 6.021 vectores, sin discrepancias**; consultas E5/CLIP/CLAP y BLIP reales | `reports/validation/reference.json` |
| Conservación del original | **True** en comparación de archivos Chroma e inventario MinIO | `reports/validation/preservation.json` |
| Interfaz | Consulta CLIP mixta y navegación a Task 1 verificadas en navegador | `reports/validation/ui_task1.png` |
| CI GitHub Actions | Configurada, **ejecución remota pendiente de comprobar** | `.github/workflows/quality.yml` |

La primera ejecución del fixture y la aceptación se realizaron también con comandos reales fuera de pytest. Sus líneas no se suman artificialmente a la cobertura de pytest. La cobertura combinada incluye adquisición opcional, CLIs e inferencia; no se excluyen para elevar el porcentaje. Referencias útiles: orquestador 92 %, cliente S3 95 %, indexador 77 %, búsquedas 80 %, segmentación 94 %. El porcentaje no mide la calidad biológica del dataset ni sustituye una revisión del código.

## 2. Pruebas offline

```bash
python -m pytest -q
python -m pytest -q --cov=orchestration --cov=exploitation_zone --cov=trusted_zone --cov=formatted_zone --cov=landing_zone --cov=multimodal_tasks --cov=webapp --cov-report=xml:reports/validation/coverage.xml --junitxml=reports/validation/offline.xml
```

`pytest.ini` excluye `integration` y `models` por defecto. `conftest.py` bloquea tráfico externo y puertos de MinIO de producción (9000/9001); solo permite loopback para HTTP temporal. Se desactiva el webhook de pruebas y no se descargan modelos. Un test rápido no debe depender de datos privados, Internet ni `.env`.

| Área | Contratos y regresiones cubiertos |
|---|---|
| Orquestador | Orden, selección de etapas, adquisición opcional, plan puro, propagación de errores, bloqueo compartido, timeout de un hijo real, UTF-8 y redacción de secretos |
| Landing | Copia y marcador, huérfanos, metadatos incompatibles, bytes corruptos, fallos entre escrituras, retención, limpieza explícita y salida del CLI |
| Adquisición | JSON atómico, corrupción preservada, fallos de proveedor, nombres reservados Windows, idioma/licencia y procedencia completa |
| Formatted | Imagen multiformato/modos, entradas inválidas, audio WAV/FLAC y texto HTML/JSON/JSONL/Markdown/XML/UTF-16 |
| Trusted | Reglas por modalidad, duplicados, informes, retención de aceptados, separación de error S3 frente a rechazo |
| Exploitation | Fingerprints, configuración inválida, normalización, fragmentación, enrutamiento, idempotencia, lotes parciales y recuperación tras fallo de upsert |
| Tasks 1/2 | Chroma temporal real, coseno exacto en colecciones pequeñas, HNSW en una colección mayor, filtros, autoexclusión por activo, cuotas, RRF y ausencia de escrituras de consulta |
| Task 3 y modelos | Captioner controlado, hash/revisión, contrato de referencias, fallo de descripción vacía, commits inmutables y preparación CPU con descarga explícita |
| HTTP | Servidor real, recursos estáticos, búsqueda, errores, origen y referencias con traversal |

Durante la repetición con cobertura se detectó un fallo intermitente del lector HNSW de Chroma sobre colecciones diminutas. Se adoptó coseno exacto para hasta 64 candidatos, con memoria acotada, sin capturar errores ni reconstruir índices. Dos regresiones comprueban esa ruta y el uso real de HNSW por encima del umbral. La suite completa volvió a pasar después de la corrección.

## 3. Integración con escritura aislada

```bash
docker compose -p ecosentinel-tests -f docker-compose.test.yml up -d
python -m pytest -m integration -q --junitxml=reports/validation/integration.xml
docker compose -p ecosentinel-tests -f docker-compose.test.yml down
```

Esperar a que `http://127.0.0.1:19000/minio/health/ready` responda 200 antes del test. Se usan credenciales desechables, buckets con prefijo/UUID controlado, ningún volumen de producción y Chroma temporal. La limpieza solo alcanza los buckets de ese fixture. El test recorre todas las zonas y concilia el resultado; usa encoders deterministas para no descargar pesos ni depender de GPU. La repetición comprueba que no vuelve a ejecutar inferencias ni añade vectores.

Para combinar cobertura, ejecutar la suite offline con los `--cov` del bloque anterior y después la integración con los mismos `--cov`, `--cov-append` y `--cov-report=xml:reports/validation/coverage_combined.xml`. Una medición sin integración es distinta de la combinada.

## 4. End-to-end del CLI y modelos reales

Con el servicio aislado disponible y los encoders preparados en caché:

```bash
python -m orchestration.smoke --run
python -m orchestration.smoke --run
```

Después de cerrar y volver a crear el servicio S3 efímero, usar una carpeta nueva, por ejemplo `--workdir data/smoke-session-02`, en ambas ejecuciones. No reutilizar un índice de una sesión cuyo S3 ya no existe: la conciliación detectaría registros huérfanos. No se borran automáticamente índices anteriores.

El fixture sintético produce una imagen PNG, un WAV y un HTML con procedencia explícita `synthetic_fixture`. El CLI convierte, valida, indexa cinco espacios y concilia: 3 aceptados, 7 vectores. La segunda ejecución conserva Temporal, reutiliza Formatted/Trusted y añade cero vectores. Se rechaza reutilizar una carpeta sin la marca `.ecosentinel-smoke`. Este ensayo demuestra integración operativa, no calidad semántica de ejemplos biológicos.

## 5. Corpus real y protección de datos

```bash
python -m orchestration.validate_reference --models --task3
```

La aceptación concilia Trusted con SQLite original en modo lectura, consulta una copia independiente y verifica otra vez los hashes originales al terminar. Repite la indexación compatible sobre la copia con un encoder que falla ante cualquier intento de inferencia: los 198 activos se mantienen sin regenerar embeddings. Las consultas reales cubren Task 1 en tres modalidades; Task 2 textual y por archivos de imagen/audio, con mezcla de formatos; y BLIP con recuperación CLIP para Task 3.

La comparación final con el inventario previo a la integración confirmó:

- Misma lista, tamaños y SHA-256 de los archivos de `data/chromadb/`; las cinco colecciones suman 6.021.
- Mismas claves, tamaños y ETag de MinIO: 396 objetos en Landing, 198 en Formatted y 396 en Trusted. Los JSON de control/calidad explican que objetos y activos no tengan el mismo total.

La comparación S3 de inventario no equivale a una descarga y hash independiente de cada objeto. Se comunica exactamente lo verificado. Los backups locales no sustituyen una política de copias externa.

## 6. CI y cierre por fases

El workflow instala desde el único requirements y comprueba `pip check`. La matriz offline usa Python 3.11 en Windows/Ubuntu y rueda CPU de PyTorch. La integración Linux levanta un S3 separado, espera su healthcheck con reintentos acotados y lo cierra incluso si falla un test. JUnit y cobertura se publican como artefactos.

| Fase | Criterio verificable | Estado local |
|---|---|---|
| Protección y auditoría | Inventarios, snapshot, ausencia de modificaciones originales | Comprobado |
| Robustez de las zonas | Casos de fallo y reintento sin borrar aceptados | Tests aprobados |
| Orquestación | Orden, lock, timeout, informes y dos ejecuciones del CLI | Comprobado con fixture real |
| Tasks 1/2 | Resultados por activo, autoexclusión, espacios compartidos y mezcla | Tests y modelos reales comprobados |
| Task 3 | Modelo generativo externo, contrato y ejecución CPU real | Comprobado; precisión semántica no evaluada |
| Interfaz | Rutas de las tres tareas, filtros y procedencia | HTTP probado; Task 1/2 revisadas visualmente |
| Documentación | Zonas, decisiones, Tasks, reproducción y matriz P1 | Documentos revisados; memoria aún requiere maquetación |
| CI remota y entrega | Workflow verde en GitHub; memoria ≤8 páginas + instrucciones | Pendiente de evidencia remota y revisión académica |

Mejoras siguientes basadas en riesgo: mayor cobertura de adquisición/CLIs y errores HTTP, benchmark etiquetado, mediciones sistemáticas de RAM, validación desde un entorno limpio y revisión humana de licencias/taxonomía. No se declaran cerradas por haber pasado los tests actuales.
