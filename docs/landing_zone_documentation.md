# EcoSentinel — Landing Zone

**Estado:** implementada y validada con las tres modalidades (100 imágenes, 34 audios, 64 textos). La incorporación posterior del **Security Gate** se ha probado sin romper el control incremental. **Fecha de revisión:** 19-10-2026.

> **Responsabilidad:** adquirir y preservar activos sin limpiarlos; identificar su procedencia; controlar qué ingestas técnicas han terminado. No decidir duplicados de calidad ni convertir formatos. Para las razones históricas de cada decisión, véase [decision_log.md](decision_log.md).

## 1. Lugar en la arquitectura

```text
Fuentes externas
   |  Wikimedia Commons / Xeno-canto / Wikipedia / GBIF
   v
landing_zone/data_acquisition/*
   |  archivos originales y _metadata.json
   v
data/raw_dataset/<modality>/<species_id>/<file>
   |  Security Gate: inspección preliminar ANTES de subir
   v
landing-zone/temporal_landing/
   |  process_to_persistent.py: copia/verifica/registra/elimina temporal
   v
landing-zone/persistent_landing/<modality>/<species_id>/<file>
   +--> landing-zone/_control/completed/<sha256_temporal_key>.json
   |
   +--> Formatted Zone (conservando Persistent)
```

Tres modalidades reconocidas por el contrato: `images`, `audio`, `text`. Los prefijos de MinIO son carpetas **lógicas**: `temporal_landing/` puede no aparecer en la consola cuando no contiene objetos.

## 2. Datos de adquisición y metadatos

Estructura local acordada:

```text
data/raw_dataset/
├── images/<species_id>/<asset>  + _metadata.json
├── audio/<species_id>/<asset>   + _metadata.json
└── text/<species_id>/<asset>    + _metadata.json
```

Cada `_metadata.json` asocia `local_filename`, `source_name` y `species_id`. Los proveedores pueden aportar más campos: URL e ID de origen, nombre científico, licencia/autor, información de grabación o idioma. La procedencia se captura en adquisición y viaja a las zonas siguientes; `source_name=unknown` no se admite.

| Modalidad | Fuente principal | Conservación en Landing |
|---|---|---|
| Imagen | Wikimedia Commons | JPEG, PNG, WEBP u otro original admitido, sin recomprimir |
| Audio | Xeno-canto | Grabaciones originales, sin convertir a FLAC en esta etapa |
| Texto | Wikipedia y GBIF | Representaciones originales, antes de extraer a TXT canónico |

La adquisición de Wikimedia está en `landing_zone/data_acquisition/download_wikimedia_images.py`. Lee `config/species.yaml`, registra licencia/procedencia y SHA-256, hace reintentos HTTP, escribe metadatos incrementalmente, limita tamaño/resolución y sanea nombres incompatibles con Windows. Estos son filtros de captación, **no una evaluación semántica**: pertenecer a una categoría de Wikimedia no prueba que la fotografía represente de forma idónea al animal.

Los scripts correspondientes de audio y texto deben mantener este contrato común; su lógica de obtención es propia de la fuente. El directorio por especie es una dependencia **deliberada y documentada**, adecuada al proyecto universitario; un catálogo independiente sería preferible para una plataforma mucho mayor.

## 3. Security Gate: control anterior a Temporal

**Archivos:**

- `landing_zone/temporal_landing/security_gate.py`
- `config/security_policy.yaml`
- Integración en `landing_zone/temporal_landing/ingest_local_data.py`

Cada candidato descubierto pasa por `inspect_file(...)` **antes de su subida**. Los fallos se registran como incidentes y se omiten; el proceso devuelve un código distinto de cero si se produjeron bloqueos o errores.

**Controles actuales:** extensiones permitidas por modalidad; longitud/nombre de archivo; archivos regulares (no symlinks); tamaño y cabeceras (*magic bytes*); rechazo de indicadores evidentes de binarios ejecutables disfrazados; inspección estructural de imágenes y límites de píxeles; límites de entradas, expansión y razón de compresión en DOCX/ODT. Para texto plano se filtran indicadores binarios básicos; la decodificación y extracción completa pertenecen a Formatted.

| Límite de seguridad (`config/security_policy.yaml`, v1) | Valor |
|---|---:|
| Longitud máxima del nombre | 240 caracteres |
| Imagen: tamaño máximo | 200 MB |
| Imagen: píxeles máximos | 80 MP |
| Audio: tamaño máximo | 1.024 MB |
| Texto: tamaño máximo | 250 MB |
| DOCX/ODT: expansión máxima | 1.000 MB |
| DOCX/ODT: entradas máximas | 10.000 |
| DOCX/ODT: ratio de compresión máximo | 200 |

Son **límites operativos preventivos**, no umbrales de calidad del contenido. Los límites de Trusted pueden ser más estrictos. El registro local se escribe en `reports/security/incidents.jsonl`; puede notificarse mediante un webhook HTTPS configurado opcionalmente. No incluir datos confidenciales en mensajes o repositorios.

**Alcance real:** comprobar firmas y cabeceras ayuda a reducir riesgos, pero **no sustituye un antivirus, análisis dinámico, sandboxing ni decodificadores aislados**. La demostración `python tests/demo_security_gate.py` utiliza bytes sintéticos inertes con extensión `.jpg`; no ejecuta código sospechoso.

## 4. Temporal Landing: identidad e idempotencia técnica

**Script:** `landing_zone/temporal_landing/ingest_local_data.py`.

Objeto de Temporal:

```text
temporal_landing/<primeros_16_hex_SHA256_bytes>__<nombre_local>
```

Ejemplo ilustrativo: `temporal_landing/07c5c9dbf9959468__wild_boar.jpg`.

El hash + nombre diferencia cambios de contenido y preserva varias identidades de captación. **No elimina duplicados del dataset**; únicamente identifica un intento técnico de ingestión.

Un archivo completado ya no está en Temporal, por lo que no basta con comprobar `head_object` en ese prefijo. Se usa un registro de finalización compartido en MinIO:

```text
_control/completed/<SHA256(clave_temporal_completa)>.json
```

El marcador apunta a la identidad Temporal, a su clave Persistent, modalidad/especie/origen y fecha UTC. Se genera **después** de verificar la copia persistente. Por tanto, repetir la ingestión del mismo contenido con el mismo nombre no vuelve a subirlo. Un nombre distinto o bytes cambiados generan otra identidad; Trusted decide si son duplicados de calidad.

La prioridad operativa de la ingesta es: descubrir archivo → inspeccionar Security Gate → construir/comprobar identidad Temporal → comprobar marcador de completado → subir a Temporal si procede. La inspección previa puede consumir algo de CPU al repetir la ingesta, pero evita eludir el control de seguridad.

## 5. Persistent Landing: organización y recuperación

**Script:** `landing_zone/persistent_landing/process_to_persistent.py`.

```text
persistent_landing/<modality>/<species_id>/
  <source>$<species>$<UTC_ingestion_timestamp>$<hash>.<original_extension>
```

El sello temporal representa la entrada original en Temporal (campo `LastModified`), no el momento posterior de la copia. El hash del nombre identifica el activo bruto, **no** el archivo transformado de Formatted.

Secuencia de escritura deliberada:

1. Obtener Temporal y validar metadatos obligatorios.
2. Copiar bytes **sin convertir** a Persistent y comprobar existencia.
3. Crear el marcador `_control/completed/` y comprobar existencia.
4. Solo entonces eliminar el objeto Temporal.

Si ya existe Persistent sin marcador, el proceso puede reconstruir el registro; si existe marcador pero sigue habiendo copia Temporal, puede terminar su limpieza. El procedimiento histórico explícito es:

```bash
python landing_zone/persistent_landing/process_to_persistent.py --backfill-control
```

Este backfill se introdujo por activos antiguos creados antes del control de finalización; no forma parte de la operación habitual.

## 6. Operación y verificación

Desde la raíz del repositorio, con MinIO ejecutándose (`docker compose up -d`), `.env` local y entorno virtual activo:

```bash
# Ingestión desde raw_dataset con Security Gate integrado
python landing_zone/temporal_landing/ingest_local_data.py

# Paso de Temporal a Persistent; primero vista previa cuando proceda
python landing_zone/persistent_landing/process_to_persistent.py --dry-run
python landing_zone/persistent_landing/process_to_persistent.py

# Demostración controlada del bloqueo de seguridad
python tests/demo_security_gate.py
```

**Validaciones efectuadas:** ingestión incremental y marcadores para imágenes; extensión operativa del mismo contrato a los 198 activos; integración del Security Gate comprobada con una repetición de la ingesta que conservó los marcadores y no provocó nuevas subidas innecesarias; demostración sintética de bloqueo. El estado de referencia tras persistencia completa son 100 imágenes, 34 audios y 64 textos, con Temporal vacía de los activos ya completados.

La prueba de `--dry-run` por sí sola no verifica todos los bytes ni la seguridad absoluta del contenido. Un contador de errores/bloqueos distinto de cero requiere investigación; no lanzar las etapas siguientes tras una ingestión fallida.

## 7. Límites y compromisos

- La identidad Temporal utiliza 64 bits (16 dígitos hexadecimales) del SHA-256 para abreviar claves; la probabilidad de colisión es pequeña a escala académica, pero no nula. El marcador usa el SHA-256 **completo** de la clave Temporal.
- Los marcadores de MinIO constituyen estado operativo adicional que debe mantenerse consistente; no son datos para Exploitation.
- La comprobación previa de seguridad cubre amenazas evidentes, no malware arbitrario ni formatos complejos exhaustivamente.
- El dataset bruto y las credenciales no se versionan en Git; la reproducción depende de scripts, metadatos, configuración y disponibilidad de las fuentes.
- No alterar el contrato genérico de Landing para añadir reglas específicas de imágenes, audio o texto. El Security Gate se integró como excepción **transversal a las tres modalidades**.

**Continuación:** [Formatted](formatted_zone_documentation.md) · [Trusted](trusted_zone_documentation.md) · [Decisiones](decision_log.md).
