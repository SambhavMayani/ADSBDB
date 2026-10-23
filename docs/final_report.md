# EcoSentinel — Borrador de memoria P1

**Borrador técnico para revisión por los autores.** Adaptar al formato de la asignatura, incorporar autoría y referencias bibliográficas, comprobar las cifras con los informes y maquetar a un máximo de ocho páginas. Las instrucciones de ejecución deben ir en una página separada y sin numeración según el enunciado; [demo.md](demo.md) y el README contienen material de apoyo, todavía sin maquetar.

## Contexto y datos

EcoSentinel organiza información multimodal de fauna ibérica para consultar imágenes, grabaciones y descripciones en un sistema común. El corpus de referencia contiene diez especies y 198 activos aceptados: 100 imágenes, 34 audios y 64 textos. Wikimedia, Xeno-canto y fuentes textuales aportan datos heterogéneos. La adquisición es opcional y preserva registros de procedencia; las atribuciones y condiciones de uso requieren revisión específica por fuente.

La arquitectura distingue calidad técnica y validez biológica: que un archivo sea decodificable y coherente con sus metadatos no prueba que su etiqueta taxonómica sea correcta. Las advertencias sobre iluminación, ruido o similitud no justifican por sí solas descartar material ecológico.

## Arquitectura por zonas

MinIO almacena las zonas de datos. Landing separa entrada Temporal y preservación Persistent, aplica un Security Gate antes de subir y usa identidades por contenido y marcadores de finalización. Persistent se verifica mediante metadatos, tamaño y SHA-256; Temporal se conserva por defecto, con limpieza explícita después de verificar la copia.

Formatted convierte imágenes a JPEG RGB, audio a FLAC PCM16 y texto a UTF-8/LF/NFC. Los originales permanecen disponibles. Trusted aplica políticas YAML por modalidad, identifica duplicados y produce manifiestos e informes HTML/PNG/CSV/JSON. Los errores operativos se distinguen de rechazos de calidad; una reevaluación no borra automáticamente activos previamente aceptados.

Exploitation usa Chroma persistente y cinco colecciones. CLIP representa imágenes (100 embeddings), CLAP representa ventanas de audio (357) y E5 representa fragmentos de texto (547). Las colecciones compartidas imagen-texto CLIP (1.763) y audio-texto CLAP (3.254) permiten recuperación cruzada. El total es 6.021. Cada segmento conserva activo, origen, especie, hash y versión de procesamiento. La indexación incremental identifica registros compatibles, repara lotes incompletos y evita inferencia innecesaria. Las revisiones nulas del contrato histórico se conservan para no invalidar el índice; el manifiesto recoge los commits de la caché observada y documenta esa limitación de reproducibilidad.

## Tareas de explotación

Task 1 recupera activos del mismo tipo a partir de un registro, una imagen o un audio externos, o una consulta textual E5. Los resultados se agrupan por activo y excluyen el activo de consulta completo, no solo el fragmento utilizado.

Task 2 consulta los espacios compartidos CLIP y CLAP y puede devolver modalidades distintas. Una política de diversidad evita que los fragmentos textuales ocupen todas las posiciones; la búsqueda federada combina rankings mediante Reciprocal Rank Fusion con constante 60. Las puntuaciones de encoders distintos no se comparan directamente. Esta política debe distinguirse de un top-k global puro y sus scores no son probabilidades de especie.

Task 3 incorpora BLIP, un modelo generativo externo preentrenado, para describir imágenes en CPU. La descripción se utiliza después para recuperar referencias mediante CLIP. Se registra modelo, revisión e identidad de entrada. Se trata de descripción seguida de recuperación; no se presenta como generación condicionada por referencias ni como RAG. El modelo puede inventar detalles o confundir especies y necesita revisión humana.

La interfaz web local expone estas tareas mediante tres pestañas: consulta textual, archivo de imagen/audio y descripción generativa. Las tarjetas muestran modalidad, procedencia y acciones de recuperación. El servidor serializa inferencias para contener la carga y limita tamaños de entrada; no está diseñado como servicio público multiusuario.

## Orquestación, recuperación y seguridad de datos

El orquestador ejecuta 16 pasos desde comprobación del almacenamiento hasta conciliación final; la adquisición opcional añade tres pasos. Usa el intérprete activo y subprocesos sin shell, un bloqueo compartido, timeouts, cierre del árbol de procesos, logs UTF-8 e informes JSON atómicos. Tras un fallo se interrumpe la cadena; repetirla vuelve a verificar el estado y aprovecha la idempotencia de cada zona.

El índice original se audita mediante SQLite en modo lectura y hashes de archivos; las búsquedas usan una instantánea separada. Las pruebas que escriben utilizan otro servicio S3 en el puerto 19000, buckets independientes y Chroma temporal. Las credenciales se cargan localmente, se redactan en logs y no se versionan. Los modelos se ejecutan en CPU y las descargas requieren una acción explícita. No se promete memoria constante: ciertas operaciones todavía decodifican un audio completo.

## Validación y resultados

La suite incluye contratos unitarios, archivos reales por modalidad, fallos S3, corrupción, recuperación parcial, concurrencia, timeouts, HTTP y Chroma temporal. La integración recorre todas las zonas con S3 y Chroma reales y encoders deterministas; una aceptación adicional ejecuta el CLI con modelos CPU reales. Los números y la cobertura medidos se mantienen en [testing_and_validation.md](testing_and_validation.md), separados de esta memoria para evitar cifras sin evidencia.

La aceptación del corpus comprueba la conciliación de los 198 activos y 6.021 embeddings, la ausencia de inferencias al repetir la indexación compatible sobre una copia y consultas reales de las tres modalidades, espacios compartidos y generación. La prueba sintética completa genera siete vectores en su primera ejecución; la repetición debe añadir cero. Estas evidencias prueban funcionamiento e idempotencia, no precisión ecológica.

GitHub Actions instala desde un único requirements, ejecuta la suite offline en Windows/Linux y una integración S3 en Linux, conservando artefactos de resultados. La configuración existe; debe adjuntarse una ejecución remota satisfactoria antes de declarar esa evidencia cerrada.

## Límites y evolución

Quedan como evaluación futura un benchmark etiquetado de recuperación, análisis de falsos positivos de calidad, revisión experta de especies, medición sistemática de RAM/latencia y actualización controlada de modelos con colecciones versionadas. Las bajas o rechazos posteriores se detectan mediante conciliación, pero no purgan automáticamente los datos históricos. Las instrucciones de instalación y demostración permiten repetir las verificaciones sin modificar el corpus original.
