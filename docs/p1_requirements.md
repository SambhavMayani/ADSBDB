# Correspondencia con los requisitos de la P1

Fuente principal: las 16 restricciones del enunciado local `P1 - Multimodal Data Management.pdf`, revisadas de nuevo el **04-11-2026**. `Project Context.pdf` se consultó en la revisión inicial del 23-10-2026. Esta tabla relaciona requisitos, implementación y evidencia, sin sustituir la evaluación del profesorado. Los recuentos del conjunto de fauna son evidencia histórica de la instalación de referencia, no un recuento nuevo durante esta revisión.

| Requisito | Implementación | Evidencia / criterio de aceptación |
|---|---|---|
| C1. Contexto del proyecto | Fauna ibérica, fuentes de imagen, audio y texto; diez especies | README y documentos de las zonas justifican fuentes, objetivo y límites |
| C2. Dos o más modalidades | Tres modalidades | Inventario Trusted: 100 imágenes, 34 audios, 64 textos |
| C3. Landing temporal/persistente e incremental | Adquisición por API opcional, Security Gate, SHA-256 + nombre, marcadores y copia verificada | `tests/test_storage_boundaries.py` y `tests/test_safety_regressions.py` cubren identidad, copia, marcador y retención. La limpieza de Temporal es opcional, tras verificar Persistent |
| C4. Formatted por modalidad | JPEG RGB, FLAC PCM16, TXT UTF-8/LF/NFC | Conversiones verificadas con archivos reales y formatos límite |
| C5. Trusted y calidad genérica | Validadores independientes, YAML, deduplicación y procedencia | Tests de políticas, bytes preservados y error operativo separado de rechazo |
| C6. Perfiles e informes | HTML/PNG/CSV/JSON por modalidad y ejecución | Informes de Trusted y resúmenes de referencia en [evidence/](evidence/README.md); el CLI aislado genera sus propios informes |
| C7. Embeddings por modalidad | CLIP imagen, CLAP audio y E5 texto | Colecciones de 100, 357 y 547 registros, respectivamente |
| C8. Modularidad de zonas y tareas | Paquetes con contratos comunes y comandos independientes | Tests importan módulos sin conectar a S3; orquestador ejecuta pasos separados |
| C9. Nombres significativos | Zonas, módulos y colecciones con propósito explícito | Revisión de estructura, contratos y documentación |
| C10. Calidad del código y explicación | Validaciones, errores explícitos, comentarios y decisiones de diseño | El 04-11 pasan Ruff, formato de 79 archivos, `pip check` y 469 pruebas offline. Cobertura de sentencias del 72,37 %, sin equipararla a precisión o ausencia de errores |
| C11. Almacenamiento de objetos en Docker | Servicio SILO compatible con MinIO/S3, fijado en Docker Compose, y servicio independiente para integración | El enunciado admite alternativas justificadas. La integración S3/Chroma pasa en 19000 sin volumen ni credenciales de producción |
| C12. Task 1, misma modalidad | Consultas por registro, imagen/audio externo y texto E5 | `tests/test_search_and_web.py` verifica autoexclusión por activo, filtros, agrupación y búsqueda exacta/HNSW. La aceptación nativa anterior obtuvo cinco resultados por modalidad. Top-k configurable de 1 a 50, ocho por defecto |
| C13. Colecciones compartidas y resultados mixtos | Imagen-texto CLIP: 1.763; audio-texto CLAP: 3.254 | Tests y ejemplos nativos anteriores muestran ambas modalidades por espacio. La fusión usa rankings, sin comparar directamente vectores CLIP y CLAP |
| C14. Modelo generativo externo preentrenado | Qwen genera con contexto recuperado automáticamente por E5/CLIP; BLIP adapta imágenes | `tests/test_rag.py` y `tests/test_query_preparation.py` verifican orden, límites, citas y fallos. La evidencia nativa anterior sigue fechada aparte. Qwen recibe texto, no píxeles |
| C15. Orquestación completa | 16 pasos; adquisición opcional añade tres | Planes de 16/19 pasos comprobados. Integración S3/Chroma del 04-11 ejecuta los 16 pasos dos veces, sin nuevas llamadas al encoder en la segunda. El CLI con modelos reales tiene evidencia anterior separada |
| C16. Repositorio reproducible y CI | Un requirements, Python 3.11, Docker, workflow Linux/Windows | [Actions 40944329385](https://github.com/SambhavMayani/ADSBDB/actions/runs/40944329385) pasa para `2f91480` en sus tres jobs. README y manual cubren instalación, adquisición, datos locales y referencia preparada. Los cambios posteriores necesitan su propio push y resultado |

## Entrega y criterios de cierre

1. Mantener los tests y la conciliación en verde; conservar los informes completos fuera de Git y los resúmenes fechados en `docs/evidence/`.
2. Comprobar el workflow en GitHub tras publicar los cambios. No marcar CI remota como validada antes de ver su resultado.
3. Revisar licencias y atribuciones, así como la interpretación biológica de ejemplos de búsqueda y generación.
4. La [memoria final](ecosentinel_report.pdf) incluye ocho páginas de contenido, una portada, dos páginas iniciales de manual sin numeración y un anexo (doce páginas físicas). El PDF oficial fija ocho páginas y excluye las instrucciones, pero no excluye expresamente portada o anexos. Esta entrega ocupa **diez páginas sin el manual** y utiliza la ampliación a diez que los autores indicaron que permite el profesor. No se presenta el anexo como una exención automática. La [fuente LaTeX](report/main.tex) acompaña al PDF.
5. Demostrar instalación y ejecución con la guía adjunta. Los modelos deben prepararse de forma explícita antes de una demostración offline; el repositorio no incluye pesos ni datos privados. Las páginas iniciales de manual distinguen adquisición, datos locales y estado ya preparado, indican `python -m orchestration.pipeline --run`, explican la copia de consulta, el arranque de la web y las rutas de informes. La copia protege el índice original y no es un requisito de persistencia de Chroma.

## Estructura documental y alcance de la revisión final

Las instrucciones aparecen al principio, sin numeración. El contexto y los datos están en la página 1, las zonas en las páginas 1–4, las Tasks en las páginas 5–7 y las operaciones en la 8. El esquema general y el anexo complementan las justificaciones y sus límites. Se mantienen los cinco bloques de contenido pedidos en la sección 6 del enunciado, aunque la memoria desglosa las zonas y las búsquedas en páginas propias.

En C14, la obligación es utilizar modelos preentrenados externos con los datos almacenados. El RAG y LLaVA se presentan como propuesta y ejemplo, no como una implementación única obligatoria. Nuestra composición BLIP → recuperación CLIP/E5 → Qwen realiza una tarea entre imagen y texto, aunque Qwen no recibe los píxeles. Esa diferencia, sus pérdidas de información y la ausencia de identificación biológica garantizada están explicadas en la memoria. Los modelos se ejecutan localmente, sin que «externo» implique una API de pago.

La revisión final ejecuta las pruebas offline, la integración aislada, el análisis estático y las comprobaciones documentales. No vuelve a adquirir el conjunto de fauna ni a generar sus embeddings, y no repite la inferencia nativa de Qwen/BLIP. No se ha detectado una funcionalidad obligatoria pendiente en el alcance revisado. Publicar la última revisión, comprobar su CI y asegurar el acceso del profesor siguen siendo pasos de entrega. Para reproducir exactamente los 198 activos se necesita además la entrega de datos y metadatos descrita en [procedencia](data_sources.md).

La interfaz web es una mejora de usabilidad del proyecto. Las puntuaciones de similitud no son precisión medida, probabilidades de especie ni una evaluación etiquetada de recuperación.
