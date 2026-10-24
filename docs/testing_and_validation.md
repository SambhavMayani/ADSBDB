# EcoSentinel — Testing y evidencias de validación

Revisión inicial: 23-10-2026; cierre de entrega: 24-10-2026 (sección 9). Windows, Python 3.11.2, `.venv`, CPU, almacenamiento S3 compatible con MinIO. Los informes completos viven fuera de Git; [resúmenes seleccionados](evidence/README.md) quedan versionados. Los comandos se ejecutan desde la raíz del repositorio.

## 1. Resultados observados

Esta tabla conserva la evidencia del cierre inicial del 23-10. Las secciones 7 y 8 recogen la evolución del RAG; la sección 9 contiene los resultados actuales del cierre general.

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
| Documentación | Zonas, decisiones, Tasks, reproducción y matriz P1 | Memoria PDF maquetada y revisada; manual y evidencias actualizados (sección 9) |
| CI remota y entrega | Workflow verde en GitHub; memoria ≤8 páginas + instrucciones | Pendiente de evidencia remota y revisión académica |

Mejoras siguientes basadas en riesgo: mayor cobertura de adquisición/CLIs y errores HTTP, benchmark etiquetado, mediciones sistemáticas de RAM, validación desde un entorno limpio y revisión humana de licencias/taxonomía. No se declaran cerradas por haber pasado los tests actuales.

## 7. Ampliación Task 3 RAG — 24-10-2026

La Task 3 principal recupera contexto antes de generar, con Qwen2.5-3B-Instruct-GGUF Q4_K_M en llama.cpp CPU. BLIP es el adaptador para imágenes opcionales. La ejecución se realizó con pesos locales, revisión y SHA-256 fijados. No se regeneró ningún embedding ni se indexaron las consultas.

| Evidencia actual | Resultado observado | Informe local |
|---|---|---|
| Regresión offline | **295 passed, 1 deselected**, 25,32 s | `reports/validation/rag_offline.xml` |
| Integración S3 + Chroma | **1 passed, 295 deselected**, 15,17 s | `reports/validation/rag_integration.xml` |
| Cobertura offline | **62,31 %**, 3.186/5.113 sentencias | `reports/validation/rag_coverage.xml` |
| Cobertura combinada | **69,96 %**, 3.577/5.113 sentencias | `reports/validation/rag_coverage_combined.xml` |
| Casos RAG añadidos | **66 pruebas**, incluidas en las 295 | `tests/test_rag.py` |
| Aceptación con modelos reales | **4/4 casos**, 223,32 s en total | `reports/validation/rag_acceptance.json` |
| Navegador | Alimentación del lince: respuesta real con cita; navegación al extracto y abstención ante receta de pizza | `reports/validation/ui_rag.png` |
| Conservación | Original Chroma idéntico a ambas líneas base; MinIO con mismas claves/tamaños/ETag | `reports/validation/rag_preservation.json` |
| Comprobaciones estáticas | 71 archivos Python parseados; sin coincidencias de secretos de `.env` en textos versionables ni enlaces locales de documentación rotos | `reports/validation/rag_static_checks.json` |

La cobertura de los módulos RAG es 75 % en el caso de uso, 94 % en evidencias, 72 % en runtime y 89 % en política; el CLI de aceptación alcanza 84 %. Las inferencias reales se ejecutan fuera de pytest y no se suman a su cobertura. `pip check`, la resolución sin descarga del único requirements, la sintaxis JavaScript y `git diff --check` pasaron. Esto no equivale a haber instalado el proyecto desde cero en otra máquina ni a haber ejecutado CI remota.

| Caso real | Resultado | Tiempo total |
|---|---|---|
| Hábitat del lince ibérico, solo texto | Dos afirmaciones con referencias S1/S4; las citas describen matorral mediterráneo y mosaicos de bosque/arbustos | 89,28 s |
| Misma pregunta con imagen existente en Trusted | Descripción BLIP separada, recuperación visual/textual y respuesta con citas S2 | 71,17 s |
| Secuencia completa del genoma del lince | Abstención del modelo por falta de evidencia (`model_abstained`) | 61,96 s |
| Receta de pizza | Abstención antes de cargar el generador (`query_domain_unrecognized`) | 0,004 s |

La consulta adicional del navegador sobre alimentación tardó 86,6 s y mostró el 80–90 % de conejos con enlace al documento que expresa esa proporción. Son latencias observadas, no una garantía de rendimiento. La revisión cualitativa de estos ejemplos concuerda con los extractos; se observan formulaciones mejorables en español. No constituyen un benchmark representativo ni una medida de accuracy.

Durante el desarrollo se descartaron prototipos BF16/INT8 y una estrategia que pedía al modelo copiar citas. Se conservaron informes de diagnóstico con sus fallos. El diseño final presenta unidades literales con ID; el LLM selecciona una y el servidor resuelve la cita. También se separan encabezados de sus oraciones para evitar referencias recortadas artificialmente. El validador posterior sigue siendo obligatorio y no prueba entailment semántico.

Las nuevas pruebas cubren orden de recuperación/generación, imagen directa CLIP, límites de contexto, unidades de evidencia, cita inexistente, fuente inventada, instrucciones no confiables, abstención, concurrencia, recuperación tras error, RAM insuficiente, peso ausente/alterado, cierre nativo incluso ante fallo, presupuesto real de tokens, protección de exportaciones, HTTP y Chroma temporal. Tres regresiones del informe de aceptación impiden declarar éxito con motivos de abstención incorrectos o con cambios en el índice original.

Para repetir en Git Bash, con `.venv` activo:

```bash
python -m pytest -q
python -m pytest tests/test_rag.py -q
python -m orchestration.validate_rag --run
python -m webapp.server
```

La integración usa el fixture de la sección 3, nunca el puerto 9000. En esta revisión se reutilizó el servicio efímero de pruebas que ya estaba disponible en 19000; solo se crearon y limpiaron los buckets UUID del fixture. No se detuvo ese servicio preexistente ni MinIO de producción. La previsualización propia en 8766 se cierra al terminar la revisión.

La configuración de GitHub Actions incluye las pruebas nuevas por descubrimiento de pytest. La ejecución remota sigue pendiente de la subida del usuario y su comprobación en GitHub. Los informes y capturas locales están ignorados por Git; se conserva aquí el resumen reproducible y se publican los informes como artefactos en CI.

## 8. Regresión de imagen de rana y salida incompleta — 24-10-2026

Esta revisión es posterior a la sección 7. Una prueba manual con imagen externa y «qué animal es», seguida de una pregunta sobre hábitat y alimentación, devolvía `invalid_json` con seis referencias. Ese estado era un fallo técnico y no demostraba falta de información. La reproducción utilizó una rana existente de Trusted y la descripción BLIP comunicada por el usuario (`a frog with a dumb barbell`); no se disponía de la fotografía externa original. El modelo recibió 2.293 tokens y produjo solo 35 antes del límite de 120 s: la salida estaba cortada. Se conserva el diagnóstico en `reports/validation/frog_rag_before.json`.

La corrección separa error técnico, abstención documental y respuesta parcial. Reduce el prompt a ocho unidades/1.600 caracteres, recupera por aspectos y candidatas, conserva fragmentos distintos del mismo activo y añade exploración léxica acotada de documentos existentes. No descarga modelos, no calcula nuevos embeddings del corpus y mantiene el límite temporal. El generador tiene una posición por aspecto en preguntas multipartes para evitar dos afirmaciones de hábitat sin dieta. Los `null` expresan ausencia explícita de respaldo; no se eliminan afirmaciones inválidas para aparentar éxito.

| Comprobación final | Resultado | Evidencia local |
|---|---|---|
| Regresión offline | **318 passed, 1 deselected**, 53,58 s | `reports/validation/frog_offline.xml` |
| Integración aislada | **1 passed, 318 deselected**, 31,88 s | `reports/validation/frog_integration.xml` |
| Suite RAG | **89 casos**, incluidos en las 318 pruebas | `tests/test_rag.py` |
| Cobertura offline | **63,46 %**, 3.353/5.284 sentencias | `reports/validation/frog_coverage.xml` |
| Cobertura combinada | **70,86 %**, 3.744/5.284 sentencias | `reports/validation/frog_coverage_combined.xml` |
| Rana en navegador, todos los modelos reales | Candidata *Pelophylax perezi*, hábitat [S1] y dieta [S2], sin timeout | `reports/validation/frog_ui_validation.json`, `ui_frog_rag.png` |
| Entrada del generador en ese ensayo web | **984 tokens**, ocho unidades y 1.303 caracteres de evidencia | Diagnóstico del navegador y `ui_frog_rag.txt` |
| Generación en ese ensayo web | **76,139 s**, 133 tokens de salida, cierre `stop`, sin alcanzar el límite | `reports/validation/frog_ui_validation.json` |
| Tiempo total de la consulta web | **131,8 s**, incluida descripción, recuperación y cargas/liberaciones | `reports/validation/frog_ui_validation.json` |
| Estática | 72 archivos Python parseados; sin secretos de `.env` en textos versionables ni enlaces locales rotos; sintaxis JavaScript y diff comprobados | `reports/validation/frog_static_checks.json` |

En la revisión manual del navegador, [S1] describía medios lóticos/lénticos y [S2] presas terrestres/acuáticas. Se abrió la procedencia de [S2] y se comprobó esa frase en su extracto original. La candidata se mostraba como asociación por similitud, sin identificación confirmada. La descripción BLIP real fue `a frog sitting on the ground in the grass`. Esta prueba usó todos los modelos reales y una imagen de Trusted; no valida por sí sola la fotografía externa del usuario ni constituye un benchmark biológico.

Las regresiones añadidas comprueban timeout con JSON abierto, límite de tokens, conservación de referencias/candidatas en errores, frases cortadas, unidades bibliográficas, exploración léxica limitada y sin vectores, fragmentos complementarios de un activo, restricciones por aspecto de la gramática nativa y respuestas parciales explícitas. La aceptación real adicional se registra en `reports/validation/frog_acceptance_final.json`.

La aceptación CLI final superó **5/5 casos estructurales** en 292,49 s: hábitat textual del lince, consulta con imagen de lince, «qué animal es» con rana de Trusted, genoma completo y receta de pizza. La rana se describió como «La candidata del corpus es Pelophylax perezi…»; las negativas se abstuvieron por `model_abstained` y `query_domain_unrecognized`. El caso multipartes de rana se comprobó por separado en la web con todos los modelos reales. En la consulta de lince con imagen, la frase generada trataba medidas de conservación que mejoran el hábitat: estaba citada, pero era menos directa para la pregunta que la respuesta textual. Este límite cualitativo se registra; superar el contrato no equivale a precisión semántica perfecta.

`reports/validation/frog_preservation.json` confirmó los mismos archivos, tamaños y SHA-256 originales frente a las dos líneas base, las cinco colecciones con **6.021 vectores** y el mismo inventario de MinIO (396/198/396 objetos). La comparación S3 fue por clave, tamaño y ETag. `frog_delivery.json` reúne evidencias y hashes del código revisado. No se realizó commit ni push; la CI remota no se ha validado en esta revisión.

Para cargar cambios en una web que ya estaba ejecutándose: detener su proceso con **Ctrl+C**, ejecutar `python -m webapp.server` desde Git Bash con `.venv` activo y recargar el navegador con **Ctrl+F5**. Repetir primero «qué animal es» y después la pregunta de hábitat/alimentación con la misma foto. La apariencia de una cita sigue sin probar que toda paráfrasis sea correcta; los ejemplos requieren revisión cualitativa.

## 9. Revisión final de entrega — 24-10-2026

Esta sección es la referencia actual para el estado del código. Los apartados anteriores conservan la historia de validación. El resumen portable está en [evidence/final_validation.json](evidence/final_validation.json).

| Comprobación | Resultado observado | Informe local |
|---|---|---|
| Suite offline completa | **344 passed, 1 deselected**; 0 errores/fallos | `reports/validation/delivery_offline.xml` |
| Integración real S3 y Chroma | **1 passed, 344 deselected**; ejecuta dos pasadas aisladas | `reports/validation/delivery_integration.xml` |
| Cobertura offline | **63,82 %**, 3.361/5.266 sentencias | `delivery_coverage.xml` |
| Cobertura combinada | **71,25 %**, 3.752/5.266 sentencias | `delivery_coverage_combined.xml` |
| Repetición focalizada de búsquedas/HTTP | **38 passed**, 9,41 s; no se suman como casos nuevos | `delivery_search_regression.xml` |
| CLI completo con modelos CPU | **16/16 pasos**, tres activos, siete vectores | `delivery_smoke_first.log` |
| Segunda ejecución del CLI | **16/16 pasos**, cero vectores nuevos en los cinco espacios | `delivery_smoke_repeat.log` |
| Estática y dependencias | Ruff correcto; 73 archivos con formato consistente; `pip check`, JavaScript y `git diff --check` correctos | Comandos reproducibles del manual |
| Chroma original | Mismos archivos, tamaños y SHA-256 frente a ambas líneas base; **6.021 vectores** | `delivery_preservation.json` |
| Compatibilidad del control reforzado | **460/460 comprobaciones**, 198 activos y 6.021 vectores reutilizables; cero inferencias/escrituras | `delivery_index_reuse.json` |
| MinIO original | Mismas claves, tamaños y ETags: **396/198/396 objetos** | `delivery_minio_preservation.json` |

Las 26 regresiones nuevas prueban partes duplicadas/ausentes/fuera de rango, identidades repetidas, hashes incompatibles, conteos booleanos, políticas con NaN/infinito y timeout inválido antes de arrancar un proceso. También comprueban que los cinco adaptadores de Formatted/Trusted usan el cliente S3 compartido con límites de conexión/lectura y reintentos.

El control reforzado se contrastó con los metadatos reales mediante SQLite `mode=ro` y el método de producción `VectorStore.is_complete`, sin arrancar Chroma sobre el original ni invocar encoders. Pasaron las 460 combinaciones activo/colección con los fingerprints actuales. La inspección estática final encontró 73 archivos Python válidos, cero enlaces Markdown locales rotos, ningún valor secreto de `.env` en textos versionables y ninguna ruta de datos/informes originales incorporada a Git.

La primera ejecución de la suite detectó un fallo intermitente de HNSW en el fixture de tres registros. Se corrigió **el fixture**: materializa su índice con umbrales pequeños y cierra sus propios recursos nativos al terminar. No se modificó ni reconstruyó un índice del usuario. La suite completa y la repetición focalizada pasaron después; los fallos anteriores no se ocultan mediante skips ni capturas de excepciones.

Las dos ejecuciones CLI usan `data/delivery-smoke-20261024/` y el servicio 19000. El primer informe registra un intervalo atípico de 11.932,701 s en `index-text`; este ensayo valida resultados y repetición, **no rendimiento**, y no se atribuye ese intervalo a una causa que no se ha medido. Los otros pasos y la repetición finalizaron correctamente. Los ensayos generativos reales de la sección 8 se conservan como evidencia separada: no se presentan como una nueva ejecución del modelo después del formateo del código.

CI incorpora Ruff, comprobación de formato y mínimo de **60 % de cobertura offline**, sin excluir los módulos de adquisición ni los CLI del denominador. El 71,25 % combinado es una medición local distinta. La ejecución remota permanece pendiente del push de los autores y de revisar los jobs correspondientes al commit entregado.

La memoria final tiene **nueve páginas físicas: instrucciones sin numerar + ocho páginas**, incluida la portada. Se revisó visualmente cada página renderizada. El manual en inglés diferencia clon limpio, validación sintética y acceso al corpus de referencia; todas sus órdenes están escritas para Git Bash. La publicación del repositorio no incorpora `.env`, medios originales, índices, modelos ni informes completos.
