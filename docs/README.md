# EcoSentinel — Documentación del proyecto

Revisión final: 24-10-2026. Python 3.11, Windows y CPU. El corpus de referencia contiene 198 activos aceptados (100 imágenes, 34 audios y 64 textos) y 6.021 embeddings en cinco colecciones.

Para evaluar o utilizar el proyecto, empezar por la **[memoria en inglés](ecosentinel_report.pdf)** y el **[manual de usuario](user_guide.md)**. La memoria tiene ocho páginas, incluida la portada con los tres autores, más una página inicial de instrucciones sin numerar, excluida del límite oficial.

| Documento | Contenido |
|---|---|
| [Landing Zone](landing_zone_documentation.md) | Adquisición opcional, Security Gate, procedencia y persistencia incremental |
| [Formatted Zone](formatted_zone_documentation.md) | Conversión a JPEG, FLAC y TXT con trazabilidad |
| [Trusted Zone](trusted_zone_documentation.md) | Políticas de calidad, duplicados, aceptación e informes |
| [Exploitation Zone](exploitation_zone_documentation.md) | Colecciones, modelos, segmentación, indexación y conservación del índice |
| [Tasks 1 y 2](multimodal_tasks_documentation.md) | Búsqueda del mismo tipo y multimodal; rankings, comandos, interfaz y pruebas |
| [Task 3](generative_tasks_documentation.md) | RAG con Qwen, recuperación E5/CLIP, adaptación visual BLIP, citas y abstención |
| [Orquestación](pipeline_orchestration.md) | Pipeline de 16 pasos, bloqueo, recuperación, logs y ejecución aislada |
| [Testing y validación](testing_and_validation.md) | Capas de prueba, evidencias locales, cobertura y CI |
| [Requisitos P1](p1_requirements.md) | Correspondencia con el enunciado y criterios verificables |
| [Auditoría técnica](technical_audit.md) | Estado inicial, comparación del ZIP, problemas priorizados y decisiones de integración |
| [Guion de demostración](demo.md) | Instalación, búsquedas, generación y comprobaciones para la presentación |
| [Memoria final PDF](ecosentinel_report.pdf) · [fuente Markdown](final_report.md) | Contexto, valor del dominio, arquitectura, decisiones, Tasks 1–3, interfaz y operaciones, en inglés |
| [Manual de usuario](user_guide.md) | Instalación CPU, comandos Git Bash, casos de interfaz y resultados esperados, en inglés |
| [Datos y modelos](data_sources.md) | Procedencia, licencias, decisiones de modelos y reproducción sin el corpus privado |
| [Evidencias versionadas](evidence/README.md) | Resúmenes revisables de calidad, pruebas, modelos reales y conservación del corpus |
| [Presentación y guion](presentation/README.md) | Defensa de 15 minutos en inglés, PowerPoint, PDF y guion por persona y diapositiva |
| [Registro de decisiones](decision_log.md) | Decisiones históricas y compromisos de arquitectura |

## Estado y alcance de las evidencias

Landing, Formatted, Trusted, Exploitation, las tres tareas y la interfaz local están implementados. Las pruebas offline, la integración con almacenamiento aislado, el CLI completo con modelos reales y la aceptación del corpus se distinguen en la guía de validación. GitHub Actions está configurado; una ejecución local no demuestra que el workflow remoto haya pasado.

Los datos originales y los informes completos generados no se incorporan a Git; se incluyen resúmenes seleccionados en `docs/evidence/`. Las consultas usan `data/search_index/`, una instantánea separada de `data/chromadb/`. Los datos de prueba se guardan en un servicio S3 independiente, puerto 19000, y en directorios locales ignorados.

## Organización

```text
config/              contratos, políticas y manifiesto de modelos
landing_zone/        adquisición y persistencia
formatted_zone/      representación por modalidad
trusted_zone/        validación, perfiles e informes
exploitation_zone/   segmentación, encoders y almacenamiento vectorial
orchestration/       ejecución, auditoría, conciliación y aceptación
multimodal_tasks/    búsquedas y generación
webapp/              servidor local y frontend sin compilación
tests/               pruebas y fixtures aislados
.github/workflows/   CI Linux y Windows
docs/                documentación mantenida en Git
```

Los valores efectivos proceden de los YAML y del código. Actualizar el documento de la zona cuando cambie su comportamiento y el registro de decisiones cuando exista un compromiso arquitectónico nuevo. Los informes fechados son evidencia de una ejecución concreta, no una garantía de calidad biológica ni de futuros datasets.
