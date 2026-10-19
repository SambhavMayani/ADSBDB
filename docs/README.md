# EcoSentinel — Índice de documentación técnica

**Estado de referencia:** 19-10-2026 · Proyecto P1 · 10 especies ibéricas · 198 activos multimodales.

Este directorio contiene la documentación técnica **vigente**. El `README.md` de la raíz del repositorio sirve de presentación general y punto de entrada al proyecto; este índice evita repetirlo.

| Documento | Qué explica | Cuándo consultarlo |
|---|---|---|
| [Landing Zone](landing_zone_documentation.md) | Adquisición, contrato raw, Security Gate, Temporal/Persistent, marcadores e idempotencia | Cambios en fuentes, ingestión, seguridad o procedencia |
| [Formatted Zone](formatted_zone_documentation.md) | Contratos JPEG/RGB95, FLAC/PCM16, TXT/UTF-8/LF/NFC; conversiones, metadatos y ejecución | Cambios de codificación o extracción |
| [Trusted Zone](trusted_zone_documentation.md) | **Las tres modalidades en un único documento:** políticas, validación, duplicados, informes, comandos y resultados | Controles de calidad, perfiles y decisiones de aceptación |
| [Decision Log](decision_log.md) | Motivos, alternativas y compromisos de diseño; conserva los ID D01–D52 y añade las decisiones nuevas | Memoria, presentación, revisiones técnicas |

## Estado de la implementación

| Etapa | Imágenes | Audio | Texto |
|---|---:|---:|---:|
| Landing Persistent (objetos) | 100 | 34 | 64 |
| Formatted (objetos) | 100 JPEG RGB | 34 FLAC PCM16 | 64 TXT UTF-8 |
| Trusted (aceptados) | 100 | 34 | 64 |
| Trusted (rechazados en ejecución validada) | 0 | 0 | 0 |
| Trusted (segunda ejecución, subidas innecesarias) | 0 | 0 | 0 |

**Alcance de estas cifras:** ejecución local de referencia comunicada y comprobada durante la integración, no una garantía para futuros datasets o nuevas versiones de políticas. Las alertas de calidad no equivalen a fallos. Ningún archivo aceptado por Trusted Images o Trusted Audio se transforma acústica/visualmente en esa etapa; Trusted Text solo permite normalización conservadora.

### Dónde vive cada cosa

```text
config/                         # Contratos y umbrales versionados
landing_zone/                   # Adquisición, Temporal, Persistent y Security Gate
formatted_zone/                 # Tres formateadores
trusted_zone/                   # Tres validadores, módulos quality/ y reporting/
docs/                           # Documentación mantenida en Git
reports/trusted_quality/        # Informes generados; ignorados por Git
  images/<UTC-run-id>/
  audio/<UTC-run-id>/
  text/<UTC-run-id>/
```

Los documentos explican la **arquitectura y los criterios**. Los valores efectivos se cambian en los YAML bajo `config/`; **el código es la referencia final del comportamiento ejecutable**. Mantener documento, política y pruebas alineados cuando se revise un criterio.

## Convenciones de mantenimiento

- Comandos ejecutados desde la raíz `~/ADSBDB`, con el `.venv` activado y MinIO de Docker disponible.
- No incluir `.env`, credenciales, dataset bruto ni informes voluminosos en Git.
- Actualizar primero el documento de la zona afectada y luego el [registro de decisiones](decision_log.md) **solo si hay un compromiso arquitectónico nuevo**.
- `reports/trusted_quality/` contiene ejecuciones fechadas. Un segundo informe no es un segundo dataset ni una segunda publicación en MinIO.
- Las pruebas offline, un `--dry-run` y un procesamiento real son evidencias distintas; registrarlas sin confundirlas.

## Pendiente fuera del alcance cerrado

Exploitation Zone, tareas multimodales, orquestación y memoria final. Entre las mejoras **opcionales** de Trusted Images están validar falsos positivos de watermark OCR y enriquecer ejemplos/estadísticas del informe; no se declaran implementadas.
