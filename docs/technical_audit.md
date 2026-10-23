# Auditoría técnica e integración de EcoSentinel

Fecha: 23-10-2026. Repositorio local Windows, Python 3.11. Rama de trabajo `codex/ecosentinel-p1-quality`, creada conservando los cambios locales existentes. No se han publicado ni confirmado estos cambios en Git durante la revisión.

## 1. Punto de partida y contraste del paquete

Landing, Formatted y Trusted ya procesaban las tres modalidades. El corpus aceptado de 198 activos y las cinco colecciones de Exploitation, con 6.021 embeddings, existían antes de esta integración. Había modificaciones locales y archivos de Exploitation aún sin seguimiento en Git; no se sustituyeron por un checkout limpio.

Se inspeccionó el ZIP de orquestación antes de incorporarlo. SHA-256 del paquete recibido: `43f9579a7fbc747a49bb94c1eb89bcd9b88b34c57e44d62314db4b73674bf141`. Sus cinco entradas eran aditivas: `orchestration/__init__.py`, `orchestration/pipeline.py`, `tests/test_orchestration_pipeline.py`, `docs/pipeline_orchestration.md` y `README_ORCHESTRATION_PATCH.md`. No contenía un reemplazo de validadores, indexadores o datos. La incorporación comprobó que los destinos no existían antes de escribirlos; no se hizo una extracción ciega con sobrescritura.

Las 47 pruebas del paquete pasaron en este Windows al integrarlo. La primera suite combinada detectó además un fallo de creación del directorio de informes de imágenes; se corrigió con una regresión. El orquestador recibido era una base útil, pero esas pruebas por sí solas no demostraban ejecución de los modelos, conservación del corpus ni recuperación completa entre servicios.

## 2. Problemas priorizados y tratamiento

| Prioridad | Hallazgo | Tratamiento / evidencia |
|---|---|---|
| Alta | Abrir Chroma puede actualizar archivos internos, incluso durante consultas | Auditoría SQLite de lectura, snapshot verificado y protección de ruta original; hashes finales intactos |
| Alta | Rechazo o fallo operativo podía retirar un aceptado anterior | Retención, candidatos a retirada y error operativo separado; regresiones S3 y políticas |
| Alta | Promoción confiaba demasiado en existencia de objetos/marcadores | Verificación de bytes, tamaño, metadatos y puntero; corrupción/orfandad provocan error |
| Alta | Limpieza automática de Temporal incompatible con conservación solicitada | Retención por defecto, `--cleanup-temporal` explícito y comprobado |
| Alta | Pruebas con riesgo de usar configuración productiva | S3 de pruebas independiente, bloqueo de puertos productivos y Chroma temporal |
| Media | Fallos de adquisición o JSON corrupto podían ocultarse o perder trazabilidad | Errores propagados, escritura atómica, registro de adquisición completo para nuevas entradas |
| Media | Procesos podían quedar bloqueados, interferir o perder salida en Windows | Lock compartido, timeout y terminación de hijos propios, UTF-8 e informes únicos/atómicos |
| Media | Dependencias y revisiones de modelos insuficientemente fijadas | Único requirements con versiones directas; manifiesto de commits y preparación explícita offline/descarga |
| Media | Distancias de modelos distintos no comparables; fragmentos dominaban resultados | RRF, agrupación por activo y cuotas transparentes por modalidad |
| Media | Lector HNSW intermitente para segmentos diminutos durante repetición | Coseno exacto acotado a 64 candidatos; prueba real HNSW para colecciones mayores |
| Media | Documentos de zonas y parches presentaban estados/instrucciones antiguos | Índice común, documentos de Exploitation/Tasks/orquestación/validación y punteros desde guías históricas |

No se afirma que esta auditoría elimine cualquier defecto. Persisten límites importantes: falta la ejecución remota de CI y una validación de instalación desde cero; las versiones transitivas no están bloqueadas exhaustivamente; no hay benchmark etiquetado de recuperación ni evaluación experta de especies; el audio se decodifica por archivo y no se ha medido un máximo de RAM sistemático. El manifiesto fija cargas futuras a commits observados, pero no reescribe la evidencia de las revisiones nulas históricas.

## 3. Arquitectura resultante

Cada zona conserva su CLI y sus contratos. `storage.py` centraliza configuración S3 y creación perezosa; `contracts.py` mantiene identidades/fingerprints; `source.py` ofrece lectura de activos aceptados; encoders y VectorStore se inyectan en tests. La orquestación compone los scripts mediante subprocesos, sin incorporar reglas de calidad al coordinador.

El flujo separa adquisición, preservación, representación, calidad, embeddings y uso. La conciliación final contrasta activos, hashes y fragmentos sin autorizar borrados. Las Tasks dependen de Exploitation y no escriben las zonas previas. La interfaz se limita a presentar esas capacidades y servir medios locales validados. Task 3 emplea generación externa preentrenada en CPU, seguida de recuperación; no se declara RAG.

## 4. Secuencia y criterios de cierre

La integración se dividió en protección/inventarios, robustez de fronteras, orquestación, búsqueda, generación, interfaz, pruebas y documentación. Los criterios medibles y el resultado de cada fase están en [testing_and_validation.md](testing_and_validation.md); la correspondencia con el enunciado está en [p1_requirements.md](p1_requirements.md).

Antes de la entrega académica: revisar el diff con los autores, confirmar la ejecución remota de GitHub Actions, reproducir en un entorno limpio y maquetar la memoria dentro del límite oficial. Los cambios permanecen disponibles para esa revisión; pasar pruebas locales no equivale a aprobar automáticamente la entrega o garantizar una nota.
