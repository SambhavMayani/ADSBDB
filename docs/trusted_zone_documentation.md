# EcoSentinel — Trusted Zone: Images, Audio y Text

**Estado:** las **tres modalidades están implementadas, probadas en MinIO y validadas con el dataset actual**. Reejecución idempotente comprobada. **Fecha de revisión:** 19-10-2026.

Este documento **sustituye** los anteriores `trusted_zone_design.md`, `trusted_audio_text_design.md` y `trusted_audio_text_usage.md`. Reúne arquitectura, criterios, pruebas, perfiles de calidad y guía de uso, evitando información duplicada o incompatible.

> **Principio rector:** controles de calidad explicables y trazables, **conservar información ecológica relevante** y no transformar los datos para un modelo concreto. Formatted estandariza codificación; Trusted comprueba validez, aplica política de duplicados y registra métricas. El Security Gate de ingestión se explica en [Landing](landing_zone_documentation.md) porque actúa **antes** de Temporal, no aquí.

## 1. Flujo, claves y separación de responsabilidades

```text
landing-zone/persistent_landing/  # Original captado, intacto
              |
              v
formatted-zone/
├── images/<species>/<name>.jpg    # JPEG RGB95
├── audio/<species>/<name>.flac    # FLAC PCM16
└── text/<species>/<name>.txt      # UTF-8 LF NFC
              |
    Validación de calidad por modalidad
              v
trusted-zone/
├── images/<species>/<name>.jpg    # Solo aceptados
├── audio/<species>/<name>.flac    # Solo aceptados; mismos bytes FLAC
├── text/<species>/<name>.txt      # Solo aceptados; normalización conservadora
└── _quality/
    ├── images/<species>/<name>.json
    ├── audio/<species>/<name>.json
    └── text/<species>/<name>.json
```

**Importante:** `_quality/` contiene **JSON de auditoría**, no copias del contenido. Un archivo rechazado **no se publica** bajo `images/`, `audio/` o `text/`, pero deja un registro de por qué fue evaluado como rechazo. Persistent y Formatted permanecen disponibles para reproducir o revisar decisiones.

| Etapa | Pregunta que resuelve |
|---|---|
| Security Gate — Landing | ¿Es admisible y razonablemente seguro **intentar ingerir** el archivo? |
| Formatted | ¿Representación técnica canónica y procedencia correcta? |
| Trusted | ¿Cumple la política de calidad? ¿Qué métricas/anomalías/duplicados presenta? |
| Exploitation (pendiente) | ¿Cómo preparar entradas y embeddings para **un modelo concreto**? |

## 2. Archivos y configuración

```text
config/security_policy.yaml                   # Seguridad antes de Landing; no es Trusted
config/trusted_quality.yaml                  # Política de imágenes (v1)
config/trusted_audio_quality.yaml            # Política de audio (v1)
config/trusted_text_quality.yaml             # Política de texto (v1)

trusted_zone/validate_images.py
trusted_zone/validate_audio.py
trusted_zone/validate_text.py
trusted_zone/pipeline_common.py              # Utilidades compartidas de Audio/Text
trusted_zone/quality/image_quality.py
trusted_zone/quality/duplicate_index.py      # SQLite temporal para candidatos de imagen
trusted_zone/quality/audio_quality.py
trusted_zone/quality/text_quality.py
trusted_zone/reporting/generate_image_report.py
trusted_zone/reporting/generate_modality_report.py
trusted_zone/reporting/templates/            # HTML/Jinja2

tests/test_trusted_images.py
tests/test_trusted_audio_text.py
tests/demo_security_gate.py
```

Los YAML son las **fuentes de verdad de umbrales**, no esta tabla de documentación. Cada regla debe distinguir claramente entre **rechazo obligatorio**, **candidato a duplicado** y **alerta meramente informativa**. No se acepta que un warning por sí solo pruebe un defecto o una clasificación taxonómica incorrecta.

## 3. Trusted Images (v1)

**Entrada:** `formatted-zone/images/<species>/<name>.jpg`.

**Política:** verificar bytes JPEG y decodificación, tamaño/megapíxeles/dimensiones mínimos, procedencia y consistencia de rutas. **No** recortar, cambiar escala, recomprimir, iluminar, enfocar, eliminar marca de agua ni modificar los bytes del JPEG aceptado.

| Criterio | Configuración actual | Acción |
|---|---:|---|
| Tamaño máximo | 20 MB | Rechazar si se supera |
| Megapíxeles máximos | 40 MP | Rechazar si se supera |
| Ancho y alto mínimos | 128 px cada uno | Rechazar si no se alcanza |
| Relación de aspecto fuera de rango | <0,2 o >5,0 | Advertencia |
| Brillo medio bajo | Umbral 45 | Advertencia; la noche puede ser válida |
| Nitidez Laplaciana baja | Umbral 60 | Advertencia; movimiento no siempre invalida |
| Poca cromaticidad | Umbral 9 | Advertencia; monocromo no es defecto por defecto |
| pHash Hamming | ≤6 para candidatos | Solo genera comparaciones posteriores |
| SSIM | ≥0,975 más comprobación de diferencia RGB (≤0,08) | Confirmación estricta de duplicado visual |
| Watermark | OCR avanzado hasta 1.000 candidatos si Tesseract existe; método ligero alternativo | **Nunca rechazar solo por esta señal en v1** |

### Duplicados de imagen

- SHA-256 detecta coincidencia exacta de bytes.
- pHash indexado en **SQLite temporal por ejecución** localiza candidatos sin comparar todos los pares.
- SSIM y distancia RGB verifican similitud antes de excluir; se prioriza evitar falsos positivos.
- El primer activo admisible por orden determinista actúa como representante canónico. Cuando dos archivos presentan misma imagen y **etiquetas de especie incompatibles**, la implementación registra `cross_species_duplicate` y excluye el posterior: exige revisión si aparece, no supone que una etiqueta sea correcta.

El índice SQLite **no persiste entre ejecuciones**: por diseño se reconstruye y se borra al finalizar, por lo que la idempotencia evita subidas, pero **no elimina el coste de volver a evaluar**.

### Marcas de agua

El uso de OCR mediante Tesseract es **opcional en el entorno de ejecución**; `pytesseract` por sí solo no instala el ejecutable. `advanced_ocr` o el detector ligero señalan una **posibilidad**, no validan la existencia de marcas de agua. Texto natural, sellos, vegetación o bordes pueden producir falsos positivos. No hemos medido precisión/recall del detector con etiquetas humanas.

**Observación del informe de referencia:** 100 imágenes aceptadas; 14 con `monochrome_like` y 32 con `possible_watermark`, **ambas señales no excluyentes**. Estas alertas son útiles para revisión futura, no prueba de 32 fotografías con marca de agua real.

## 4. Trusted Audio (v1)

**Entrada:** `formatted-zone/audio/<species>/<name>.flac`, con FLAC PCM16 ya estandarizado en Formatted.

### Política conservadora: no modificar el audio

No se realiza **trimming, denoising, filtrado de paso alto, eliminación de DC-offset, reducción a mono, remuestreo, normalización LUFS/RMS ni limitación de picos**. Los audios aceptados son **bit a bit idénticos** al archivo FLAC de Formatted.

**Razón:** en naturaleza, silencios, sonidos lejanos, viento y frecuencias extremas pueden aportar contexto o señal biológica. Un filtro seguro para voz humana o un modelo específico puede borrar vocalizaciones. La reproducción cómoda (ganancia/limitador) debe resolverse en la aplicación o mediante un derivado claramente identificado, **no reemplazando el activo científico conservado**. No se guarda una segunda copia raw dentro de Trusted: ya hay originales en Persistent y canonizados en Formatted.

### Validación, deduplicación y métricas

| Control | Política actual | Resultado |
|---|---|---|
| Ruta y metadatos | Especie/modalidad/origen y clave Persistent coherentes | Rechazo si inconsistente |
| Tamaño y bytes | No vacío; máximo 200 MB; cabecera FLAC | Rechazo si inválido |
| Integridad | Decodificación completa; subtipo PCM16, frames, canales y frecuencia válidos | Rechazo si falla |
| Duración | Mínimo técnico 0,01 s | Rechazo por debajo |
| Duplicado exacto | SHA-256 de bytes FLAC o PCM decodificado + frecuencia/canales | Rechazo de la copia posterior **dentro de la misma especie** |
| Mismo audio entre especies | Coincidencia del PCM | Advertencia y conservación para revisión |
| Duración breve | <0,5 s | Advertencia |
| RMS bajo | <−55 dBFS | Advertencia |
| Ventanas de baja energía | Ventanas de 50 ms bajo −50 dBFS; >80 % | Advertencia |
| Posible clipping | Muestras con amplitud absoluta ≥0,99; umbral de señal 1 % | Advertencia |
| Desplazamiento DC | Media absoluta >0,02 | Advertencia |

**Interpretación:** `rms_dbfs` y `peak_dbfs` expresan nivel digital **dBFS, no sonoridad perceptual LUFS**. `clipping_sample_pct` no demuestra por sí solo distorsión de grabación; ventanas de energía baja no implican ausencia de fauna. **No se mide SNR verdadero**, detección verificada de especies ni ACI como prueba de biofonía.

**Evidencia de referencia:** 34/34 audios aceptados y cero clipping detectado; 2 señales `low_rms` y 9 `many_low_energy_windows`. La duración mediana fue 40,91 s y la mayor 752,37 s. Se registraron 9 mono y 25 estéreo; sample rates 22.050 (1), 24.000 (5), 44.100 (12) y 48.000 Hz (16). Esta heterogeneidad se conserva intencionadamente. Que se acepten los 34 audios **no resuelve** la ausencia de grabaciones para `timon_lepidus` ni las dos de `lynx_pardinus`.

## 5. Trusted Text (v1)

**Entrada:** `formatted-zone/text/<species>/<name>.txt`.

### Preservación de contenido

El texto se decodifica con UTF-8 estricto, comprueba controles no permitidos y se representa mediante Unicode **NFC**, saltos **LF** y como máximo un salto final; se conservan idioma, párrafos, mayúsculas, puntuación y vocabulario. La fuente ya suele cumplir ese formato gracias a Formatted. **No** se eliminan stopwords, no se aplica stemming/lemmatización, traducción, filtrado por idioma ni redacción automática de nombres/PII.

| Control | Política actual | Resultado |
|---|---|---|
| Codificación, controles y contenido | UTF-8 estricto; no vacío; controles válidos | Rechazo ante fallo |
| Tamaño máximo | 4 MB | Rechazo si supera |
| Duplicado exacto | SHA-256 del texto normalizado | Rechazo de la copia posterior **en la misma especie** |
| Texto idéntico entre especies | Hash igual, especie distinta | Conservar y señalar |
| Documento breve | <20 palabras | Advertencia |
| Proporción alfanumérica | <0,45 | Advertencia |
| Duplicación aproximada | Jaccard de shingles de 5 palabras; ≥0,90, mínimo 5 shingles | **Candidato** de revisión, no rechazo |
| Posibles email / IPv4 | Patrones estructurados | Contar/advertir **sin guardar valores privados** |
| HTML residual o mojibake | Patrones heurísticos | Advertencia, no reparación semántica automática |

La búsqueda de documentos parecidos compara candidatos en memoria con coste **O(N²)**; es suficiente para 64 archivos, **no** adecuada como servicio para millones de documentos. Una expansión exigiría LSH/MinHash u otra estrategia de indexación. No se realiza detección de idioma porque con textos cortos/taxonómicos los errores podrían impulsar exclusiones injustificadas.

**Evidencia de referencia:** 64/64 aceptados, cero advertencias y cero coincidencias de patrones email/IPv4 en el informe analizado. Mediana de 208,5 palabras por documento; rango observado: 33–13.869 palabras. Un documento GBIF breve no debe compararse con una página enciclopédica extensa como si ambos persiguieran la misma longitud objetivo.

## 6. Políticas de duplicación por modalidad: diferencias deliberadas

| Supuesto | Imágenes | Audio | Texto |
|---|---|---|---|
| Igualdad exacta | SHA-256 | SHA-256 FLAC y PCM | SHA-256 texto normalizado |
| Similitud aproximada | pHash candidatos + SSIM/RGB confirmación, excluyente si cumple | **No** se elimina por MFCC/huella acústica aproximada | Jaccard de shingles, **solo alerta** |
| Identidad entre distintas especies | Excluye la copia posterior con incidente de especie | Conserva ambas, marca conflicto | Conserva ambas, marca conflicto |

Esta asimetría refleja las **implementaciones actuales**, no un principio universal: la deduplicación aproximada de audio necesitaría calibración bioacústica, y eliminar textos parecidos podría suprimir descripciones valiosas. El conflicto de etiquetas entre especies requiere estudio manual antes de aseverar cuál es correcto.

## 7. Auditoría, idempotencia y errores

Cada script lee objetos de `formatted-zone`, los ordena de forma determinista y genera un JSON de auditoría por archivo evaluado:

```text
trusted-zone/_quality/<modality>/<species>/<stem>.json
```

El manifiesto contiene `source_key`, `species_id`, `source_name`, ETag, versión de política, `status`, `reason`, métricas, indicador de duplicación y fecha/hora de análisis. Para Audio/Text incorpora también hash de datos y **hash de la política**; las implementaciones de imágenes y Audio/Text no son idénticas en todas las claves internas.

**Estados:** `accepted` = objeto publicado; `rejected` = exclusión de calidad justificada en el manifiesto; `error` = problema de procesamiento que exige investigar. Los warnings no activan una cola obligatoria de revisión ni representan un estado adicional de publicación.

**Idempotencia:** si origen y política relevantes no cambiaron, una segunda ejecución evita las escrituras redundantes. Los scripts vuelven a leer/reanalizar entradas, por lo que **no prometemos ejecución de coste constante**. Audio/Text distinguen versión y *fingerprint* de política; en imágenes se compara procedencia/política definida en su implementación. Un rechazo determinista puede retirar un objeto anteriormente aceptado de Trusted, **sin tocar Formatted ni Persistent**. Un error transitorio no se utiliza para borrar por defecto.

**Limitación de los lotes parciales:** con `--max-items` o `--species` no se valida la deduplicación global; para publicar definitivamente debe ejecutarse el lote completo. Los informes basados en manifiestos pueden incluir registros antiguos de fuentes retiradas: **no existe todavía una conciliación automática de bajas en origen**.

## 8. Informes de calidad (Constraint 6)

**Ruta definitiva:**

```text
reports/trusted_quality/
├── images/<YYYYMMDDTHHMMSSZ>/
├── audio/<YYYYMMDDTHHMMSSZ>/
└── text/<YYYYMMDDTHHMMSSZ>/
```

Cada ejecución completa genera una **carpeta local nueva** con `quality_report.html`, `summary.json`, `metrics.csv` y los `*.png` enlazados de forma relativa. Se debe abrir el HTML **sin separar los PNG de su carpeta**. Estos resultados están ignorados en Git por `/reports/trusted_quality/`; pueden seleccionarse después como evidencia para la memoria. Una segunda ejecución idempotente crea **otro informe temporal**, pero no vuelve a publicar activos idénticos.

**Generadores:** `trusted_zone/reporting/generate_image_report.py` y `trusted_zone/reporting/generate_modality_report.py`. Leen los JSON existentes en `trusted-zone/_quality/<modality>/`, **no** vuelven a decodificar los medios para crear las gráficas.

| Mod. | Gráficos/medidas | Precaución |
|---|---|---|
| Imagen | Resolución, tamaño, brillo, nitidez, aspecto; por especie/fuente; shift Jensen–Shannon; watermark/método | OCR no equivale a watermark real; señal monocromática puede ser fauna nocturna |
| Audio | Duración, RMS y peak dBFS, clipping, baja energía, sample rate; canales y fuentes | No se ha normalizado nivel ni recortado; perfilado ≠ denoising |
| Texto | Palabras, caracteres, TTR, alfanuméricos, tamaño; fuentes y candidatos de privacidad | TTR depende mucho de longitud; patrones no prueban PII |

Los gráficos **Formatted vs. Trusted** comparan los **evaluados** frente a los **aceptados**, no necesariamente cambios físicos en los archivos. En la ejecución de referencia se aceptaron todos los objetos y las barras coinciden; eso **no implica que los controles no se hayan ejecutado**. Los reportes de audio/texto incluyen estadísticas descriptivas; el de imágenes todavía admite mejoras visuales y revisión de falsos positivos.

## 9. Procedimiento reproducible: Windows / Git Bash

Requisitos: Docker y MinIO funcionando, variables de `.env` configuradas **solo localmente**, `.venv` activado y dependencias en el `requirements.txt` **único** del proyecto.

```bash
cd ~/ADSBDB
source .venv/Scripts/activate
python -m pip install -r requirements.txt

# 1. Tests sin MinIO real
python -m pytest tests/test_trusted_images.py tests/test_trusted_audio_text.py -v

# 2. Pruebas de seguridad y vista previa (no publican Trusted)
python tests/demo_security_gate.py
python trusted_zone/validate_images.py --dry-run --max-items 3
python trusted_zone/validate_audio.py --dry-run --max-items 3
python trusted_zone/validate_text.py --dry-run --max-items 3

# 3. Evaluación completa sin escritura
python trusted_zone/validate_images.py --dry-run
python trusted_zone/validate_audio.py --dry-run
python trusted_zone/validate_text.py --dry-run

# 4. Publicación completa y creación de informes
python trusted_zone/validate_images.py
python trusted_zone/validate_audio.py
python trusted_zone/validate_text.py

# 5. Idempotencia: repetir los 3 scripts sin flags
# 6. Revisar reportes en reports/trusted_quality/<modality>/<fecha>/
```

**Pruebas realizadas y resultado observado:** tests automatizados de las tres modalidades superados en el entorno del proyecto; Security Gate demostró rechazo de bytes sintéticos disfrazados de JPEG; secos limitados/completos superados; procesamiento real aceptó **100/100 imágenes, 34/34 audios y 64/64 textos**, **sin errores**; repetición de cada modalidad con `uploaded=0` y `unchanged_objects=100/34/64` respectivamente.

Para volver a generar **solo Audio/Text** a partir de los manifiestos existentes sin tocar media:

```bash
python -m trusted_zone.reporting.generate_modality_report audio
python -m trusted_zone.reporting.generate_modality_report text
```

Puede usarse `--species <species_id>` o `--max-items N` en los validadores para diagnósticos limitados; `--no-report` omite el informe local. No declarar completo el lote a partir de una prueba limitada.

## 10. Pendiente conocido y límites de alcance

- No existe etiquetado manual que valide la detección de watermark, defectos visuales o identidad taxonómica.
- El informe de imágenes puede mejorarse con ejemplos verificables de anomalías, percentiles/unidades claras y estudio de falsos positivos OCR; son **propuestas futuras**, no tareas concluidas.
- El rendimiento actual implica relectura de archivos por ejecución; SQLite de imágenes es temporal y los parecidos textuales usan comparación cuadrática. Para gran escala se necesitarían índices persistentes, tareas por cambios y políticas de almacenamiento.
- Los detectores de datos personales en texto cubren solo patrones básicos; **no** hay garantía general de ausencia de PII ni redacción automática. También deben revisarse las condiciones de licencia y atribución de las fuentes.
- Los informes basados en manifiestos no eliminan automáticamente entradas cuya fuente fue borrada. Los HTML históricos quedan fechados y no deben presentarse como estado real de MinIO en una fecha posterior sin verificar.
- Las tres zonas de datos no sustituyen backups externos, controles IAM, aislamiento del procesamiento de ficheros no confiables ni validación por expertos en biodiversidad.

**Continuación:** [Índice](README.md) · [Landing](landing_zone_documentation.md) · [Formatted](formatted_zone_documentation.md) · [Decisiones](decision_log.md).
