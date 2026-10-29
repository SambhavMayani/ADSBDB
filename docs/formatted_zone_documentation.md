# EcoSentinel — Formatted Zone

**Estado:** implementada y comprobada sobre 198 objetos reales (100 imágenes, 34 audios y 64 textos), con lectura posterior correcta desde Trusted. **Fecha de revisión:** 19-10-2026.

> **Responsabilidad:** homogeneizar la **representación técnica** de cada modalidad y mantener su trazabilidad. No filtrar calidad, deduplicar el dataset ni adaptar formatos a un modelo específico. Los archivos adquiridos siguen disponibles en Persistent Landing.

## 1. Contrato de entrada y salida

```text
landing-zone/persistent_landing/<modality>/<species>/<source>.<ext>
                            |
          scripts de Formatted por modalidad
                            v
formatted-zone/<modality>/<species>/<source-stem>.<canonical-extension>
                            |
                      Trusted Zone
```

| Modalidad | Script | Representación canónica | Objetos validados |
|---|---|---|---:|
| Imágenes | `formatted_zone/format_images.py` | JPEG `.jpg`, RGB, encoder `quality=95` | 100 |
| Audio | `formatted_zone/format_audio.py` | FLAC `.flac`, muestras PCM con resolución de 16 bits | 34 |
| Texto | `formatted_zone/format_text.py` | TXT `.txt`, UTF-8 sin BOM, LF, Unicode NFC | 64 |
| **Total** | | | **198** |

Los datos se organizan bajo `images/<species_id>/`, `audio/<species_id>/` y `text/<species_id>/`. Los nombres heredan el *stem* de Persistent (`<source>$<species>$<timestamp>$<hash>`). **El hash incrustado en el nombre corresponde al activo raw**, no al checksum del objeto convertido.

## 2. Imágenes: JPEG/RGB/95

**Por qué para fauna:** las fotografías contienen textura y variación de color. JPEG suele ocupar menos que PNG a una calidad visual aceptable; `quality=95` busca conservar detalle mientras reduce el coste de almacenar y leer fotografías. No es una garantía de menor tamaño para todos los archivos, ni de igual exactitud de búsqueda. PNG sería preferible para conservar píxeles/alpha exactamente. La calidad visual sí importa: por eso conservamos dimensiones y el original, y explicitamos la pérdida. Véase [PNG: The Definitive Guide, 9.4.1](https://www.libpng.org/pub/png/book/chapter09.html).


**Entradas previstas:** `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tif`, `.tiff` y `.mpo`, coherentes con el Security Gate. Pillow inspecciona la codificación interna; se encontraron archivos `.jpg` internamente MPO. En entradas multiframe se usa frame 0, sin expansión del número de activos.

**Revisión 23-10-2026:** pruebas de modos de color, entradas inválidas, WAV/FLAC y extracción HTML/JSON/JSONL/Markdown/XML y texto UTF-16. El Security Gate reconoce BOM Unicode para no rechazar UTF-16/32 únicamente por sus bytes NUL. Los buckets pueden aislarse mediante variables de entorno y los clientes se crean de forma perezosa. El corpus original no se reconvirtió durante estas pruebas; véase [validación](testing_and_validation.md).

| Operación | Política | Razón / limitación |
|---|---|---|
| Decodificación e inspección | Pillow, formato interno real | Una extensión no prueba la codificación |
| Modo de color | Convertir a RGB | Evita variaciones L/P/RGBA posteriores |
| Transparencia | Componer sobre blanco y convertir a RGB | JPEG no almacena alpha; la apariencia puede variar |
| Codificación | JPEG `quality=95` | Prioriza fidelidad visual, pero **sigue siendo con pérdida** |
| Resolución | Conservar ancho y alto | No añadir resize/crop pensado para CLIP o similares |
| Orientación | No rotar píxeles por EXIF; preservar EXIF cuando existe | Algunos visores interpretan orientación de modo distinto |
| MPO | Extraer solo frame 0 | Mantiene relación 1:1 entre activo Persistent y Formatted |

**Caso real MPO:** cuatro fuentes de `aquila_chrysaetos` con dos frames y dos de `canis_lupus` con tres; **seis activos** generan seis JPEG principales. Sus ocho frames adicionales no se exportan a Formatted, pero están conservados en los originales Persistent. La primera ejecución de imágenes requirió esta corrección; tras implementarla se comprobaron **100 JPEG/RGB válidos** (10 por especie).

Formatted **no** valora desenfoque, exposición, marcas de agua, duplicados ni adecuación de la especie. Eso pertenece a Trusted o a una revisión semántica posterior.

## 3. Audio: FLAC PCM16

**Por qué para grabaciones de fauna:** una llamada débil puede convivir con lluvia, viento, insectos u otras especies. Evitamos añadir otra compresión perceptual, como un nuevo MP3/AAC, que podría descartar información acústica. FLAC comprime sin pérdida los valores PCM16 seleccionados, con menor almacenamiento que PCM sin comprimir en muchos casos; el tamaño depende del ruido y del contenido. Conservamos fondo y pausas, sin denoising ni recortes, porque pueden contener llamadas lejanas o contexto ecológico. Esto es una decisión de preservación, no una mejora de CLAP medida. Convertir audio de 24 bits/float a PCM16 sí puede perder precisión, y FLAC no recupera información perdida en un MP3 anterior. Véanse [FLAC Features](https://www.xiph.org/flac/features.html) y el contrato del conversor.


**Script:** `formatted_zone/format_audio.py`.

- Decodifica los formatos admitidos por los decodificadores disponibles, preferentemente mediante ffmpeg, con respaldo de `soundfile`/libsndfile cuando procede. Soportar una extensión **no** garantiza decodificar todas sus variantes.
- Escribe un único FLAC con muestras de 16 bits; usa la **primera pista de audio** cuando hay varios streams. El resto de pistas, arte/capítulos y metadatos internos del contenedor no se exportan a Formatted.
- **No fuerza frecuencia de muestreo ni número de canales:** ambas propiedades de la señal se conservan en la conversión cuando es posible. Downmix y resampling se reservan, si se necesitan, a Explotación.
- FLAC es un códec sin pérdidas **respecto al PCM que recibe**, pero convertir señales de 24 bits/float a PCM16 implica cuantización y un MP3 previo ya sufrió compresión con pérdida. El original completo sigue en Persistent.
- Comprueba que el resultado decodifica y tiene el formato/subtipo esperado, y guarda información de duración, frames, canales, frecuencia y decodificador en la procedencia.

La calidad sonora (clipping, RMS, partes silenciosas) se estudia en Trusted **sin modificar** el FLAC aceptado.

## 4. Texto: TXT UTF-8 / LF / NFC

**Script:** `formatted_zone/format_text.py`.

Admite texto plano y Markdown, HTML/XHTML/XML, JSON/JSONL/NDJSON, PDF con capa textual, DOCX y ODT. El contrato de salida es **texto plano legible**, UTF-8 sin BOM, saltos LF, Unicode NFC, controles excluidos y un salto de línea final.

| Entrada | Comportamiento | Límite conocido |
|---|---|---|
| HTML/XML | Extraer contenido textual sin scripts/estilos | El layout y parte de la estructura se pierden |
| Markdown | Quitar marcado frecuente | No es un parser CommonMark completo |
| JSON/JSONL | Priorizar claves semánticas (`text`, `content`, `description`, etc.) por recorrido BFS; fallback al texto más largo | El fallback heurístico puede elegir contenido no relevante |
| PDF | `pypdf` sobre capa de texto disponible | No ejecuta OCR sobre PDFs escaneados |
| DOCX/ODT | Extraer párrafos y texto | Tablas y diseño complejo pueden aplanarse |
| Texto plano | Detectar BOM/UTF-8 y usar fallback de codificación cuando procede | La detección heurística de codificación puede equivocarse |

La extracción **no es reversible**: suprime marcado o presentación, pero el original completo se conserva en Persistent. Formatted no elimina stopwords, no filtra por idioma, no detecta duplicados ni evalúa la veracidad del contenido.

## 5. Metadatos, identidad y ejecución incremental

**Mínimos exigidos al origen Persistent:** `modality`, `species_id`, `source_name`, `asset_hash`; se comprueba concordancia entre la ruta y la especie declarada. Se propaga información de origen y se añade la clave Persistent URL-encoded como `source_persistent_key_encoded`.

| Campos adicionales | Significado |
|---|---|
| `original_format` / `source_format` | Formato detectado de entrada |
| `formatted_format` / `canonical_format` | Representación de salida |
| `format_version` / `formatter_version` | Versión de contrato; imágenes y audio/texto tienen versiones propias |
| `formatted_at` / `formatted_timestamp` | Fecha UTC de transformación |
| `color_mode`, `jpeg_quality` | Características de JPEG canónico |
| Sample rate, channels, frames, duration | Características FLAC |
| Encoding, extraction method, character count | Características TXT |

Los nombres de campos históricos conservan algunas diferencias entre modalidades; existen alias comunes para interoperabilidad. **No debe asumirse que todos los objetos antiguos contienen todos los alias** sin regeneración explícita.

La ejecución usa claves deterministas y comprueba la existencia, procedencia y política del destino antes de repetir una conversión. **Compatible → se omite. Conflictivo → error, sin sobrescritura silenciosa.** Para audio/texto existe `--force` destinado a regeneraciones deliberadas, no a la operación diaria. Las conversiones verifican existencia/tamaño del resultado; esa comprobación por sí sola **no constituye una auditoría criptográfica del destino**.

`--max-items` cuenta operaciones nuevas realizadas o previstas, no todos los objetos examinados. El `--dry-run` de Formatted prevé operaciones, pero **no equivale a decodificación real exhaustiva**.

## 6. Comandos de operación

Desde la raíz del repositorio, después de activar `.venv`, configurar `.env` **sin compartir credenciales** y arrancar MinIO (`docker compose up -d`):

```bash
# Previsualización sin escrituras
python formatted_zone/format_images.py --dry-run --max-items 1
python formatted_zone/format_audio.py --dry-run --max-items 1
python formatted_zone/format_text.py --dry-run --max-items 1

# Procesamiento completo, seguro de reejecutar con política compatible
python formatted_zone/format_images.py
python formatted_zone/format_audio.py
python formatted_zone/format_text.py
```

Para audio/texto, `--species <species_id>` permite limitar pruebas por especie; `--force` debe quedar reservado a cambios planificados. El controlador de calidad posterior está descrito en [Trusted Zone](trusted_zone_documentation.md).

## 7. Evidencia real y cautelas

**Evidencia más reciente de integración:** 100 imágenes JPEG RGB, 34 audios FLAC PCM16 y 64 textos TXT están disponibles en Formatted y han sido leídos y aceptados por los scripts Trusted correspondientes. Para los scripts de audio/texto existen asimismo pruebas de regresión offline previas. Esta validación de integración **no demuestra** perfección taxonómica, conformidad legal de todas las licencias, fidelidad al raw a nivel de píxel/señal, ni exactitud semántica del contenido.

**Compromisos conocidos:** JPEG y extracción textual pueden modificar el contenido; MPO solo exporta el frame primario; PCM16 puede perder precisión de fuentes de más resolución; el primer stream de audio descarta extras del contenedor; las comprobaciones de destinos existentes no equivalen a recalcular un hash completo en cada reejecución. Todos ellos son compromisos documentados, no fallos ocultos.

**Continuación:** [Landing](landing_zone_documentation.md) · [Trusted](trusted_zone_documentation.md) · [Decisiones](decision_log.md).
