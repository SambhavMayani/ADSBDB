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

El flujo separa adquisición, preservación, representación, calidad, embeddings y uso. La conciliación final contrasta activos, hashes y fragmentos sin autorizar borrados. Las Tasks dependen de Exploitation y no escriben las zonas previas. La interfaz se limita a presentar esas capacidades y servir medios locales validados. En la revisión inicial del 23-10, Task 3 empleaba captioning CPU seguido de recuperación. La ampliación del 24-10 sustituye esa experiencia principal por RAG: recuperación E5/CLIP previa, contexto acotado, Qwen2.5-3B-Instruct-GGUF y validación de citas. El captioning BLIP se conserva como adaptador visual y herramienta auxiliar.

La prueba manual posterior con rana detectó un JSON truncado por el límite temporal que se mostraba erróneamente como falta de evidencia. Se corrigió la separación de estados, la selección de contexto, la recuperación por aspectos y la conservación de fragmentos complementarios. La gramática multipartes hace explícita la cobertura o ausencia de cada aspecto. Las candidatas permanecen visibles si falla el generador. La sección 8 de la guía de validación recoge la reproducción, 318 pruebas offline, integración y pruebas con modelos reales, junto con las limitaciones semánticas observadas.

## 4. Secuencia y criterios de cierre

La integración se dividió en protección/inventarios, robustez de fronteras, orquestación, búsqueda, generación, interfaz, pruebas y documentación. Los criterios medibles y el resultado de cada fase están en [testing_and_validation.md](testing_and_validation.md); la correspondencia con el enunciado está en [p1_requirements.md](p1_requirements.md).

Antes de la entrega académica: revisar el diff y la memoria final con los autores, confirmar la ejecución remota de GitHub Actions y verificar el acceso del evaluador al corpus de referencia si se pretende reproducir exactamente sus resultados. El manual incluye validación técnica sintética sin ese corpus. Los cambios permanecen disponibles para esa revisión; pasar pruebas locales no equivale a aprobar automáticamente la entrega o garantizar una nota.

## 5. Cierre de revisión general — 24-10-2026

Se contrastaron las zonas, scripts, configuración, dependencias, búsqueda, RAG, interfaz, tests y documentación con C1–C16 y las instrucciones de entrega. Los cambios funcionales finales refuerzan el conteo de partes del índice, los límites numéricos y el uso uniforme del cliente S3. Se añadieron 26 casos de regresión y controles Ruff/formato/cobertura en CI; se aplicó formato consistente al código Python.

Se retiraron cinco documentos que solo redirigían a las guías mantenidas, un fragmento de `.gitignore` ya incorporado y marcadores vacíos `.gitkeep` de carpetas pobladas. Se conservaron scripts operativos y documentación histórica útil; no se eliminó código por ser antiguo ni se limpiaron datos locales. El README, el índice de documentación y el manual muestran una ruta de entrada única para el evaluador.

Resultado: **344 pruebas offline + una integración real**, dos ejecuciones completas del CLI con modelos CPU y cero vectores nuevos en la segunda. La regresión focalizada de búsqueda/HTTP pasó 38 casos adicionales ya incluidos en la suite. La cobertura combinada es **71,25 %**. Los límites y el intervalo atípico de una etapa del smoke quedan registrados en la [guía de validación](testing_and_validation.md), sin presentar el ensayo como benchmark de rendimiento.

La verificación final de solo lectura confirmó los **6.021 embeddings** y todos los hashes de archivos originales, además del inventario MinIO por claves/tamaños/ETags. La memoria inglesa y el manual están terminados; se incluyen resúmenes seleccionados en `docs/evidence/`. Queda fuera de esta evidencia local la ejecución remota de GitHub Actions, el acceso del profesor a los datos de referencia y una evaluación biológica etiquetada. Ninguna de esas tareas se presenta como completada sin pruebas.
