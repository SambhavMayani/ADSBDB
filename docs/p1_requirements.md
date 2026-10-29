# Correspondencia con los requisitos de la P1

Fuente: enunciado local `P1 - Multimodal Data Management.pdf` y `Project Context.pdf`, revisados el 23-10-2026. Esta tabla resume los requisitos para facilitar su revisión; el enunciado oficial prevalece. No sustituye la evaluación del profesorado.

| Requisito | Implementación | Evidencia / criterio de aceptación |
|---|---|---|
| C1. Contexto del proyecto | Fauna ibérica, fuentes de imagen, audio y texto; diez especies | README y documentos de las zonas justifican fuentes, objetivo y límites |
| C2. Dos o más modalidades | Tres modalidades | Inventario Trusted: 100 imágenes, 34 audios, 64 textos |
| C3. Landing temporal/persistente e incremental | Security Gate, claves por contenido, marcadores y copia verificada | Tests de fallos de copia/marcador, corrupción, reintentos y retención |
| C4. Formatted por modalidad | JPEG RGB, FLAC PCM16, TXT UTF-8/LF/NFC | Conversiones verificadas con archivos reales y formatos límite |
| C5. Trusted y calidad genérica | Validadores independientes, YAML, deduplicación y procedencia | Tests de políticas, bytes preservados y error operativo separado de rechazo |
| C6. Perfiles e informes | HTML/PNG/CSV/JSON por modalidad y ejecución | Informes de Trusted y resúmenes de referencia en [evidence/](evidence/README.md); el CLI aislado genera sus propios informes |
| C7. Embeddings por modalidad | CLIP imagen, CLAP audio y E5 texto | Colecciones de 100, 357 y 547 registros, respectivamente |
| C8. Modularidad de zonas y tareas | Paquetes con contratos comunes y comandos independientes | Tests importan módulos sin conectar a S3; orquestador ejecuta pasos separados |
| C9. Nombres significativos | Zonas, módulos y colecciones con propósito explícito | Revisión de estructura, contratos y documentación |
| C10. Calidad del código y explicación | Validaciones, errores explícitos, comentarios y decisiones de diseño | Ruff y formato verificados, 469 pruebas offline, regresiones, memoria y registro de decisiones; revisión humana sigue siendo necesaria |
| C11. Almacenamiento de objetos en Docker | MinIO local y servicio independiente para integración | Tests reales S3 en 19000 sin volumen ni credenciales de producción |
| C12. Task 1, misma modalidad | Consultas por registro, imagen/audio externo y texto E5 | Autoexclusión por activo, cinco resultados por modalidad en aceptación real |
| C13. Colecciones compartidas y resultados mixtos | Imagen-texto CLIP: 1.763; audio-texto CLAP: 3.254 | Consultas verificadas con ambas modalidades; políticas de diversidad documentadas |
| C14. Modelo generativo externo preentrenado | Qwen genera usando contexto recuperado con E5/CLIP; BLIP adapta imágenes | RAG implementado; ver evidencias actuales, citas literales y límites de RAM en la guía de Task 3 |
| C15. Orquestación completa | 16 pasos; adquisición opcional añade tres | Dos ejecuciones del CLI sobre fixture aislado; conciliación final y cero vectores nuevos en repetición |
| C16. Repositorio reproducible y CI | Un requirements, Python 3.11, Docker, workflow Linux/Windows | Instalación/comandos documentados y validación local; falta evidencia de ejecución del workflow en GitHub |

## Entrega y criterios de cierre

1. Mantener los tests y la conciliación en verde; conservar los informes completos fuera de Git y los resúmenes fechados en `docs/evidence/`.
2. Comprobar el workflow en GitHub tras publicar los cambios. No marcar CI remota como validada antes de ver su resultado.
3. Revisar licencias y atribuciones, así como la interpretación biológica de ejemplos de búsqueda y generación.
4. Revisar por los autores la [memoria final](ecosentinel_report.pdf): ocho páginas de contenido, una portada separada y dos páginas iniciales de manual de usuario sin numeración (once páginas físicas). El manual distingue instalación desde cero, datos locales y estado ya preparado. La memoria justifica las zonas, modelos, búsquedas, consultas, informes y validación. La [fuente LaTeX](report/main.tex) se mantiene junto al PDF.
5. Demostrar instalación y ejecución con la guía adjunta. Los modelos deben prepararse de forma explícita antes de una demostración offline; el repositorio no incluye pesos ni datos privados. La primera página distingue archivos fuente frente a instalación ya preparada, indica `python -m orchestration.pipeline --run`, explica la copia de consulta, el arranque de la web y las rutas de informes. La copia es una protección adicional del proyecto y no un requisito de persistencia de Chroma.

La interfaz web es una mejora de usabilidad del proyecto. Las puntuaciones de similitud no son precisión medida, probabilidades de especie ni una evaluación etiquetada de recuperación.
