# EcoSentinel — Registro de decisiones arquitectónicas

**Edición consolidada · 19-10-2026.** Este archivo conserva los identificadores **D01–D52** del registro previo y los actualiza a un estado coherente con la implementación validada. Las decisiones **D53–D62** recogen Security Gate y Trusted Images/Audio/Text. Se han reducido explicaciones repetidas: el *cómo se ejecuta* pertenece a los documentos de [Landing](landing_zone_documentation.md), [Formatted](formatted_zone_documentation.md) y [Trusted](trusted_zone_documentation.md).

**Cómo leerlo:** *decisión* = contrato adoptado; *por qué* = justificación; *coste/límite* = compromiso aceptado. Las decisiones históricas no implican que el comportamiento esté pendiente: el estado presente se resume en [el índice](README.md).

## A. Arquitectura y adquisición (D01–D07)

### D01 — MinIO como almacenamiento de objetos
**Decisión:** MinIO compatible con S3, desplegado mediante Docker; acceso con `boto3`. **Por qué:** admite binarios multimodales y metadatos S3 con interfaz de inspección. **Coste:** infraestructura Docker y convenciones de claves.

### D02 — Adquisición, Temporal y Persistent separados
**Decisión:** scripts de adquisición → `ingest_local_data.py` → `process_to_persistent.py`. **Por qué:** responsabilidades claras, testabilidad y reutilización entre modalidades. **Alternativa descartada:** un script monolítico.

### D03 — Originales intactos en Landing
**Decisión:** Landing conserva los bytes captados, sin convertir JPEG/PNG/WEBP, audio o documentos. **Por qué:** reproducibilidad. La conversión pertenece a Formatted y el análisis de calidad a Trusted.

### D04 — Jerarquía raw como contrato explícito
**Decisión:** `data/raw_dataset/<modality>/<species_id>/<file>`. **Por qué:** simplicidad, inspección manual y determinismo; aceptado para la escala universitaria. **Coste:** el ingestor depende de esta estructura. A gran escala usaríamos catálogo independiente.

### D05 — Metadatos de adquisición junto al activo
**Decisión:** `_metadata.json` en cada carpeta de especie; campos mínimos `local_filename`, `source_name`, `species_id`. **Por qué:** recuperar origen y procedencia incluso ante interrupciones.

### D06 — No ingerir origen desconocido
**Decisión:** rechazar `source_name` vacío o `unknown`. **Por qué:** no promocionar datos sin trazabilidad. **Antecedente:** objetos temporales antiguos de `bubo_bubo` se corrigieron reingresando los activos con metadatos válidos.

### D07 — SHA-256 para identidad técnica raw
**Decisión:** fingerprint sobre bytes captados. **Por qué:** checksum y trazabilidad; **no** implica igualdad visual/acústica/semántica ni reemplaza la deduplicación de calidad.

## B. Idempotencia y persistencia de Landing (D08–D20)

### D08 — Clave de Temporal abreviada
**Decisión:** `temporal_landing/<hash16>__<filename>`, con los 16 primeros hex de SHA-256 raw. **Por qué:** distinguir combinaciones de bytes y nombre. **Límite:** riesgo de colisión teórico, despreciable al tamaño actual.

### D09 — Diferenciar idempotencia de deduplicación
**Decisión:** Landing evita repetir una ingestión **idéntica**; Trusted evalúa duplicados exactos o similares. **Estado actualizado:** los tres validadores Trusted implementan las reglas que les corresponden; no es una función pendiente de Landing.

### D10 — No buscar en Persistent desde el ingestor
**Decisión:** no listar/escanear Persistent por cada archivo para decidir reingesta. **Por qué:** desacoplar capas, evitar coste por listados y dependencias del nombre Persistent.

### D11 — No usar JSON local como registro autoritativo
**Decisión:** evitar estado de ingestión exclusivo de un PC. **Por qué:** los miembros del equipo y procesos necesitan el mismo estado compartido.

### D12 — Registro de finalización en MinIO
**Decisión:** `_control/completed/<control_id>.json` por ingestión completada. **Por qué:** lookup determinista, compartido y tolerante a reintentos. **Regla:** verificar primero el objeto Persistent.

### D13 — Control ID usa SHA-256 completo
**Decisión:** `control_id = SHA256(clave_temporal_completa)` (64 hex). **Por qué:** identidad interna sin necesidad de abreviar.

### D14 — La identidad del control incluye nombre y bytes
**Decisión:** calcular el marcador sobre la clave Temporal entera. **Consecuencia:** mismos bytes con otro nombre pueden entrar y serán evaluados por Trusted; mismo nombre y bytes se omite en reejecución.

### D15 — Organización de Persistent
**Decisión:** `persistent_landing/<modality>/<species_id>/`. **Por qué:** particiones estables e interpretables por el resto del pipeline.

### D16 — Nombre Persistent trazable
**Decisión:** `<source>$<species>$<timestamp>$<hash>.<ext>`. **Por qué:** origen, especie, momento y hash visibles en la clave.

### D17 — Timestamp de ingestión original
**Decisión:** usar `LastModified` de Temporal, expresado en UTC, no la fecha posterior del copy. **Por qué:** evitar confundir copia con captación.

### D18 — Eliminar Temporal solo tras verificar Persistencia y marcador
**Decisión:** copiar → verificar Persistent → registrar completado → verificar marcador → borrar Temporal. **Por qué:** evitar pérdida de datos por fallos parciales.

### D19 — Backfill programático de objetos históricos
**Decisión:** `process_to_persistent.py --backfill-control`. **Por qué:** un activo preexistía al registro; se corrigió sin manipular objetos manualmente.

### D20 — UTC en metadatos y operaciones
**Decisión:** timestamps UTC. **Por qué:** evitar ambigüedades entre zonas horarias y cambios de horario.

## C. Calidad de adquisición y coordinación (D21–D28)

### D21 — Guardar metadatos tras cada adquisición Wikimedia
**Decisión:** actualizar `_metadata.json` después de cada imagen válida. **Por qué:** un corte a mitad del lote no deja fotografías sin procedencia.

### D22 — Retries y separación de peticiones Wikimedia
**Decisión:** manejar fallos HTTP/rate limits con reintentos y pausas. **Por qué:** robustez frente a errores transitorios de la API.

### D23 — Solo filtros técnicos en adquisición Wikimedia
**Decisión:** MIME, resolución mínima y tamaño máximo. **Por qué:** no adelantar Trusted a Landing. **Límite:** una categoría Wikimedia no prueba calidad semántica del contenido.

### D24 — Nombres locales compatibles con Windows
**Decisión:** sanear caracteres y limitar la longitud de nombre (aprox. 140 caracteres en adquisición de imágenes). **Por qué:** se observaron errores con rutas largas en Windows.

### D25 — No crear carpetas Temporal artificiales
**Decisión:** permitir que el prefijo `temporal_landing/` desaparezca en la UI cuando está vacío. **Por qué:** MinIO/S3 usa prefijos, no carpetas físicas.

### D26 — Temporal y Persistent son scripts comunes
**Decisión:** ambos manejan `images`, `audio` y `text` con metadatos mínimos genéricos; la adquisición/formato/calidad específicos son por modalidad. **Estado:** contrato común usado con las tres modalidades.

### D27 — Proteger la interfaz común de Landing
**Decisión:** no modificar scripts compartidos por necesidades exclusivas de una modalidad. **Excepción justificada e implementada:** Security Gate opera para **todas** las modalidades antes de la ingestión; se probó la regresión incremental.

### D28 — Repartir documentación por propósito
**Decisión:** docstrings para detalles de función; un documento por zona para diseño/operación; registro de decisiones para razones/pros y contras; memoria final para selección de evidencia. **Estado:** documentación consolidada con estas cuatro piezas e índice.

## D. Formatted Images (D29–D40)

### D29 — JPEG como representación canónica de imágenes
**Decisión:** `.jpg` para todas las imágenes formateadas. **Por qué:** amplia interoperabilidad y peso manejable. **Coste:** JPEG es con pérdida.

### D30 — Imagen RGB de tres canales
**Decisión:** convertir a RGB. **Por qué:** entrada uniforme para etapas posteriores. **Coste:** no se preservan canales alpha o paleta idénticos.

### D31 — Transparencia a fondo blanco
**Decisión:** componer pixels transparentes sobre blanco antes de JPEG. **Por qué:** JPEG carece de alpha. **Coste:** puede cambiar la apariencia de los píxeles originales.

### D32 — Codificación JPEG con `quality=95`
**Decisión:** fijar el parámetro de encoder a 95. **Por qué:** favorecer fidelidad en fotografías de fauna. **Advertencia:** no es una puntuación objetiva de calidad ni hace reversible la conversión.

### D33 — Preservar dimensiones y no corregir orientación de píxeles
**Decisión:** sin resize/crop, sin rotación EXIF materializada; conservar EXIF cuando existe. **Por qué:** Formatted homogeneiza encoding, no optimiza por modelo. **Límite:** distintos visores pueden interpretar EXIF de forma diferente.

### D34 — MPO: exportar primer frame
**Decisión:** frame 0 de archivos MPO aunque terminen en `.jpg`, uno por objeto Persistent. **Evidencia:** 4 MPO de `aquila_chrysaetos` con 2 frames y 2 de `canis_lupus` con 3, por lo que 8 frames secundarios no pasan a Formatted. **Mitigación:** originales completos en Persistent.

### D35 — Conservar identidad fuente en el nombre formateado
**Decisión:** `formatted-zone/images/<species>/<persistent_stem>.jpg`. **Nota:** el hash del nombre describe bytes raw, no JPEG recodificado.

### D36 — Propagar trazabilidad y versión de política
**Decisión:** mantener metadatos Persistent y añadir `source_persistent_key_encoded`, `original_format`, `formatted_format`, `color_mode`, `jpeg_quality`, `format_version`, `formatted_at`. **Coste:** metadatos de objeto S3 no sustituyen un catálogo completo.

### D37 — Persistent no se modifica al formatear
**Decisión:** convertir en un bucket distinto y preservar el original. **Por qué:** reproducibilidad y investigación de errores; **coste:** más almacenamiento.

### D38 — Claves deterministas y reejecución compatible
**Decisión:** omitir destino solo cuando sus metadatos y contrato son coherentes; conflictos → error sin overwrite silencioso. **Por qué:** preservar integridad y procedencia; una política nueva requiere regeneración deliberada.

### D39 — Un formateador por modalidad
**Decisión:** `format_images.py`, `format_audio.py` y `format_text.py` independientes. **Estado actualizado:** los tres están implementados, sus objetos reales están en Formatted y se han validado aguas abajo con Trusted (100/34/64).

### D40 — Validar todos los JPEG formateados
**Decisión:** comprobar extensión/encoding/mode RGB, metadatos y cuentas. **Evidencia:** 100/100 imágenes RGB JPEG finales y cero fallos tras resolver MPO; esto **no** demuestra calidad semántica.

## E. Formatted Audio y Text (D41–D52)

### D41 — FLAC/PCM16 para audio
**Decisión:** usar `.flac` con PCM16 incluso desde archivos FLAC previos. **Por qué:** representación homogénea con codec sin pérdidas sobre las muestras resultantes. **Coste:** cuantización de originales de mayor precisión y pérdidas ya presentes en formatos fuente con compresión con pérdida.

### D42 — No forzar canales ni sample rate
**Decisión:** mantener frecuencia/canales disponibles. **Por qué:** son transformaciones dependientes de las necesidades futuras de modelos. **Coste:** audio formateado conserva heterogeneidad técnica que Exploitation deberá gestionar.

### D43 — Tomar primer stream de audio
**Decisión:** exportar una pista por objeto raw; omitir carátulas, capítulos y etiquetas internas del contenedor. **Por qué:** correspondencia 1:1 predecible. **Coste:** extras solo disponibles en Persistent.

### D44 — Decodificación ffmpeg con fallback libsndfile
**Decisión:** usar ffmpeg cuando está disponible y `soundfile` para formatos compatibles. **Por qué:** amplitud de codecs; **límite:** extensión reconocida no garantiza decodificación exitosa.

### D45 — TXT canónico UTF-8/LF/NFC
**Decisión:** sin BOM, sin controles prohibidos, con un salto de línea final. **Por qué:** consistencia de consumo. **Coste:** cambian bytes y puede perderse estructura de origen; Persistent conserva raw.

### D46 — Extracción real de formatos textuales heterogéneos
**Decisión:** admitir texto, Markdown, HTML/XML, JSON/JSONL, PDF con capa textual, DOCX y ODT. **Por qué:** cubrir representaciones de origen diversas. **Coste:** formatos ricos se aplanan; PDFs escaneados no disponen de OCR en el formateador.

### D47 — JSON: claves prioritarias y fallback heurístico
**Decisión:** buscar campos textuales por BFS/prioridad y, si faltan, elegir cadena no vacía más larga; arrays/JSONL por registro. **Coste:** la cadena larga no siempre es contenido semántico correcto.

### D48 — Formatted incremental con conflictos explícitos
**Decisión:** verificar clave fuente, representación, versión, MIME y tamaño antes de omitir; reportar conflictos, `--force` solo para sustitución intencionada. **Por qué:** impedir sobrescrituras opacas.

### D49 — Límite `--max-items` por conversiones nuevas
**Decisión:** tanto en real como en dry-run cuenta cambios nuevos, no archivos ya compatibles. **Por qué:** vista previa representativa del trabajo pendiente.

### D50 — Alias de metadatos compartidos
**Decisión:** conservar nombres anteriores específicos de audio/texto y añadir `original_format`, `formatted_format`, `format_version`, `formatted_at`. **Por qué:** facilitar integración; **coste:** algunos campos duplicados y objetos históricos sin todos los alias.

### D51 — Rechazo de procedencia inválida en Formatted
**Decisión:** exigir modalidad, especie, `source_name`, `asset_hash` y coherencia de clave Persistent; cerrar streams S3. **Por qué:** evitar activos mal clasificados y liberar recursos.

### D52 — Distinguir tests offline de verificación end-to-end
**Decisión:** no inferir publicación completa a partir de pruebas con S3 simulado. **Antecedente:** 12 pruebas focalizadas offline durante revisión inicial de Audio/Text, y otras pruebas comunicadas por colaborador. **Estado actualizado:** las conversiones reales (34 FLAC y 64 TXT) se han utilizado y aceptado en Trusted; ya no está pendiente el procesamiento completo en MinIO para estos activos. Esta evidencia no permite asegurar calidad semántica o perfección de fuentes.

## F. Security Gate y Trusted (D53–D62) — nuevas decisiones

### D53 — Validación de seguridad antes de Temporal
**Decisión:** inspeccionar cada activo local con allowlist, magic bytes y límites preventivos por formato, antes de subirlo. **Por qué:** separar riesgos de entrada de criterios posteriores de calidad. **Coste:** trabajo extra incluso si la ingestión se completó; detección basada en firmas no equivale a antivirus. Incidentes JSONL y salida distinta de cero ante bloqueos.

### D54 — No modificar automáticamente imágenes aceptadas
**Decisión:** JPEG de Formatted se copia intacto a Trusted tras validaciones. **Por qué:** brillo, movimiento, noche y monocromo pueden ser características ecológicas válidas. **Coste:** se conservan imágenes imperfectas como material de estudio.

### D55 — Deduplicación de imágenes: SQLite temporal, pHash y confirmación visual
**Decisión:** SHA exacto; pHash indexado en SQLite **efímero** para candidatos; SSIM y diferencia RGB confirmatoria. Primera clave válida como representante. **Conflicto de especies en imágenes:** registrar y excluir la copia posterior. **Coste:** umbrales heurísticos y coste de recomputación por ejecución.

### D56 — Watermarks como señal no excluyente
**Decisión:** OCR avanzado con Tesseract si está disponible o heurística ligera; **sin rechazo automático**. **Por qué:** falsos positivos y ausencia de conjunto etiquetado. **Evidencia de referencia:** 32 señales posibles, sin validación humana de precisión.

### D57 — Trusted Audio conservador y sin variantes extra
**Decisión:** FLAC aceptado idéntico en bytes al Formatted; no cortar, eliminar ruido, mezclar canales, remuestrear ni normalizar. **Por qué:** proteger vocalizaciones débiles y contexto acústico. **Alternativa descartada:** dos copias dentro de Trusted; raw ya existe en Persistent y el FLAC canónico en Formatted. Derivados de escucha corresponderían a presentación.

### D58 — Duplicados de audio exactos, conflictos de especie sin eliminación
**Decisión:** SHA de bytes y huella del PCM decodificado con sample rate/canales; deduplicación estricta **intra-especie**. **Entre especies:** marcar y conservar. **Por qué:** no descartar señales potencialmente mal etiquetadas sin investigación. Clipping y silencio son avisos, no expulsiones.

### D59 — Trusted Text conservador
**Decisión:** UTF-8/LF/NFC y caracteres válidos; sin lowercasing, stopwords, stemming, traducción ni redacción PII automática. **Por qué:** proteger semántica, negaciones, taxonomía y estructura documental. **Coste:** requiere revisión posterior de problemas semánticos o PII compleja.

### D60 — Deduplicación textual exacta y similitud para revisión
**Decisión:** hash del texto normalizado para dedup intra-especie; Jaccard de shingles de 5 palabras ≥0,90 solo identifica candidatos. Igualdad entre especies se marca, no se elimina. **Coste:** búsqueda aproximada O(N²) adecuada para 64 textos pero no para millones.

### D61 — Manifiestos de calidad e idempotencia verificable
**Decisión:** JSON en `trusted-zone/_quality/<modality>/<species>/`; datos aceptados bajo prefijo de la modalidad; evitar resubida sin cambio relevante. Audio/Text incluyen fingerprint del YAML en comprobaciones. **Por qué:** auditabilidad, reproducibilidad y seguridad de reejecución. **Coste:** los archivos vuelven a leerse/analizarse; la eliminación upstream aún puede dejar manifiestos obsoletos.

### D62 — Informe local por modalidad y por ejecución
**Decisión:** `reports/trusted_quality/{images,audio,text}/<UTC-run-id>/` con HTML, PNG, CSV, JSON; informes generados ignorados en Git. **Por qué:** Constraint 6, comparación de cobertura/alertas y evidencia histórica sin sobrescribir. **Evidencia:** los 198 activos del corpus actual se aceptaron, todos con procedencia presente, y una segunda ejecución no generó subidas redundantes. **Límite:** Before/After aquí refleja activos evaluados frente a aceptados; no implica una transformación física o semántica del dato.

## Estado de entrega y trabajos futuros

**Revisión 23-10-2026:** implementadas las cuatro zonas, Tasks 1–3, interfaz y orquestación. Las evidencias y límites se mantienen en [validación](testing_and_validation.md). La memoria dispone de borrador y requiere revisión/maquetación académica; el workflow remoto necesita su ejecución en GitHub. Las decisiones históricas anteriores describen el diseño en su fecha; D63–D70 recogen las sustituciones actuales.

**Enlaces:** [Índice](README.md) · [Landing](landing_zone_documentation.md) · [Formatted](formatted_zone_documentation.md) · [Trusted](trusted_zone_documentation.md).

## G. Orquestación y explotación (D63–D70)

### D63 — Retención y verificación antes de limpiar
Temporal se conserva por defecto; la limpieza requiere `--cleanup-temporal` y verificación de SHA-256, tamaño, metadatos y marcador. Sustituye la política histórica de limpieza automática. Una reevaluación Trusted propone una retirada y conserva bytes previos. Coste: espacio adicional y necesidad de revisión de bajas.

### D64 — Recuperación mediante reejecución idempotente
Subprocesos con el intérprete activo, sin shell, con timeout y bloqueo global independiente del directorio de informes. El primer error detiene la cadena. Informes atómicos y logs UTF-8 redactados conservan evidencia. No se promete una transacción distribuida entre S3, JSON y Chroma: el reintento verifica y repara cada frontera.

### D65 — Índice original protegido y consultas sobre copia
La auditoría usa hashes y SQLite `mode=ro`; no arranca Chroma sobre el original. La instantánea se crea solo en un destino nuevo y se verifica antes/después. Las consultas rechazan la ruta original. Coste: copia adicional y necesidad de renovar explícitamente una instantánea cuando cambien los datos.

### D66 — Mantener el contrato histórico de las cinco colecciones
Se preservan nombres, fingerprints, modelos y segmentación v1 para evitar regenerar los 6.021 vectores. El manifiesto registra los commits observados en caché, sin atribuir revisiones que el contrato histórico dejó nulas. En ejecución, los adapters resuelven esas revisiones nulas con el manifiesto y rechazan revisiones mutables o desconocidas: se fija la carga futura sin reescribir la historia. `prepare_models` separa preparación de pesos e indexación y requiere `--download` para Internet. Cambiar el encoder requiere una colección versionada y validación, no mezclar representaciones.

### D67 — Agrupar por activo y fusionar posiciones
Task 1 excluye todo el activo de referencia. Task 2 consulta espacios compartidos; la federación usa RRF con k=60. Cuotas explícitas reservan modalidades disponibles para evitar dominancia de fragmentos textuales. No es un top-k global puro ni una comparación entre distancias CLIP/CLAP/E5. Para hasta 64 candidatos se calcula coseno exacto con lectura acotada; conjuntos mayores usan HNSW. Esta decisión evita depender de segmentos HNSW aún sin materializar en colecciones diminutas, sin ocultar errores de almacenamiento.

### D68 — Generación externa en CPU
BLIP con revisión fijada genera una descripción; después CLIP recupera referencias. Se separan responsabilidades y se documentan errores semánticos posibles. No se llama RAG porque las referencias no condicionan el texto generado. Pesos en caché y descarga explícita.

### D69 — Tres niveles de evidencia y CI
Suite offline con Chroma temporal y HTTP; integración S3 aislada con encoders deterministas; aceptación separada con modelos CPU reales. Las pruebas bloquean S3 de producción. El workflow Windows/Linux configura CI, pero su existencia no demuestra una ejecución remota correcta. La cobertura global se comunica incluyendo adquisición y CLIs, sin excluir módulos para inflarla.

### D70 — Procedencia completa y metadatos atómicos
Los proveedores preservan `_metadata.json` mediante fsync y reemplazo atómico y fallan ante corrupción. Nuevas ingestas guardan un registro de adquisición separado y propagan su referencia. Los datos históricos no se reescriben para backfill automático. Coste: objetos de control adicionales y convivencia explícita con metadatos antiguos.


## H. Task 3 RAG (24-10-2026)

### D71 — Recuperar antes de generar
Sustituye el alcance principal de D68: se conserva el captioning auxiliar, pero la Task 3 ahora recupera contexto E5/CLIP antes de invocar Qwen. Las imágenes se adaptan mediante BLIP y embeddings; Qwen recibe texto, no píxeles. No se afirma que sea un VLM conversacional. La entrada puede ser una imagen existente de Trusted, una subida o una pregunta textual.

### D72 — Generador CPU GGUF oficial, versionado y verificado
Qwen2.5-3B-Instruct-GGUF Q4_K_M, commit y SHA-256 fijados, con llama-cpp-python CPU precompilado. Se añade una dependencia de runtime justificada por las pruebas: BF16 e INT8 PyTorch se descartaron por lentitud y salidas inválidas. No se conserva conversión manual de pesos en producción. Se usa mmap, cero capas GPU, esquema JSON limitado a las fuentes y cierre explícito del contexto nativo. El control de memoria no garantiza un máximo de RSS; la parada entre tokens no equivale a un timeout duro de todo el proceso.

### D73 — Citas verificadas y abstención
El modelo selecciona IDs de unidades de evidencia permitidos por una gramática JSON y redacta sus afirmaciones. El servidor resuelve esos IDs a fuentes y citas literales de 24–240 caracteres; no depende de que el LLM copie el texto. Se exige que la cita exista en el extracto correcto; una salida inválida se descarta completa. Este control no prueba entailment semántico ni identidad de especie. La web utiliza textContent para contenido externo. Los informes de aceptación conservan salidas rechazadas como diagnóstico, no como respuestas válidas.

### D74 — Contexto limitado y dominio conservador
RRF por activo, fragmentos textuales E5 más amplios, referencia visual cuando existe y límites de fuentes/caracteres/tokens. Solo un nombre completo explícito de especie produce un filtro. Un vocabulario de dominio puede abstenerse antes del LLM; es una heurística con falsos positivos/negativos posibles, no un detector OOD calibrado. Los nombres compuestos no aportan adjetivos genéricos aislados como red.

### D75 — Protección de datos y evidencias diferenciadas
El RAG consulta una copia y lee Trusted; no añade vectores ni escribe MinIO. Las exportaciones JSON rechazan destinos en data/, minio_data/ y .git/. Las pruebas offline inyectan modelos, prueban HTTP y Chroma temporal y bloquean producción. La aceptación de modelos reales es separada y registra fallos reales, tiempos, citas y hashes originales. No se declara una validación satisfactoria por haber recibido cualquier texto del LLM.

### D76 — Separar fallo técnico y abstención documental
Una reproducción del caso de rana produjo 35 tokens y un JSON abierto al alcanzar 120 segundos. `invalid_json` no demostraba falta de evidencia. Se conserva el límite temporal y se reduce el contexto del prompt a ocho unidades/1.600 caracteres; las referencias completas permanecen visibles. `status=error` distingue tiempo, tokens y validación de `status=abstained`. No se reparan salidas truncadas. Las frases y unidades con finales claramente incompletos se rechazan, sin añadir continuaciones.

### D77 — Recuperación híbrida por aspecto y fragmento
Aclara D74: las consultas sobre candidatas visuales pueden acotarse a esas etiquetas como hipótesis, manteniendo una búsqueda global de respaldo. Se separan hábitat, dieta y comportamiento para recuperar pasajes diferentes. La lectura léxica está limitada a 128 registros por candidata, sin vectores ni nuevos modelos, e informa si se trunca. RRF mantiene una contribución por activo y lista; el contexto admite hasta dos fragmentos de ese activo, con IDs distintos. Así la deduplicación para búsqueda no elimina información complementaria necesaria para RAG.

### D78 — Candidatas visibles y preguntas naturales
Las etiquetas de las dos primeras coincidencias visuales se presentan como candidatas del corpus, sin porcentajes de confianza. Se conservan aunque falle Qwen. Las preguntas de identidad permiten una sola afirmación condicional respaldada por texto; las multipartes hasta dos aspectos diferentes. La gramática y el validador limitan las afirmaciones a 240 caracteres. Esta decisión no convierte similitud en identificación confirmada ni demuestra entailment semántico.

### D79 — Cobertura explícita de preguntas multipartes
No basta con JSON válido: el generador podía responder dos veces sobre hábitat y omitir la dieta. La gramática incorpora posiciones por aspecto, con IDs de evidencia acotados léxicamente. Una posición `null` expresa falta de respaldo y produce una respuesta parcial visible. Esas ausencias se conservan en el informe; no se confunden con afirmaciones inválidas ni se proclama cobertura completa. Se mantienen el presupuesto global y una sola carga del modelo.

## I. Cierre de calidad y entrega (24-10-2026)

### D80 — Estática y formato reproducibles
Ruff 0.14.2 en el único `requirements.txt`, reglas E4/E7/E9/F y formato común. Los pocos E402 permitidos corresponden al bootstrap de scripts heredados ejecutables directamente; no se desactiva la regla globalmente. CI comprueba formato sin modificar archivos y exige 60 % de cobertura offline. Se mantiene todo el código de adquisición y los CLI dentro de la medición. Coste: un diff de formato amplio, separado conceptualmente de las correcciones funcionales y respaldado por la suite completa.

### D81 — Compleción verificable y límites numéricos finitos
La idempotencia vectorial exige IDs únicos y cobertura exacta de las partes `0..N-1`, además del hash de contenido/política y el número de registros. Un conteo correcto no demuestra que todas las partes estén presentes. Se rechazan booleanos, NaN e infinitos en los controles numéricos relevantes. Formatted y Trusted delegan sus fábricas públicas al mismo cliente S3 acotado, conservando las interfaces existentes. No cambian los contratos de las colecciones ni se regeneran embeddings compatibles.

### D82 — Entrega académica y evidencia portable
Una memoria PDF en inglés de ocho páginas, incluida la portada, y una hoja inicial de instrucciones excluida del límite oficial; el Markdown conserva su contenido editable. Un manual separado explica comandos Git Bash y casos de interfaz. Los resúmenes de calidad y validación se versionan en `docs/evidence/`, mientras que los informes completos, datos y pesos siguen ignorados. Se distingue una demostración técnica sintética de la reproducción exacta del corpus, que requiere un traspaso de datos autorizado. Coste: los autores deben coordinar ese acceso y comprobar la CI del commit publicado.
