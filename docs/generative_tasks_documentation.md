# EcoSentinel — Task 3: descripción generativa y recuperación

**Responsabilidad:** invocar un modelo generativo preentrenado sobre una imagen del dominio y combinar su salida con la recuperación multimodal existente. **Código:** `multimodal_tasks/generate.py`.

## 1. Diseño elegido

```text
Imagen de consulta (memoria)
    ↓ BLIP, CPU, inferencia determinista
Descripción generada en inglés
    ↓ encoder textual CLIP alineado
Colección image_text de la instantánea
    ↓ agrupación y diversificación
Descripción + referencias de imagen y texto + procedencia
```

Se utiliza `Salesforce/blip-image-captioning-base`, fijado al commit `82a37760796d32b1411fe092ab5d4e227313294b`. La entrada visual se convierte a RGB únicamente en memoria. La generación tiene un límite de 48 tokens nuevos, sin muestreo, y se ejecuta en CPU. El modelo se libera antes de cargar el encoder de recuperación.

La Task 3 del enunciado permite descripciones de imágenes con modelos externos preentrenados. «Externo» no implica necesariamente una API de pago: BLIP se obtiene de su repositorio oficial y se ejecuta localmente. La propuesta de RAG del enunciado es una extensión recomendada, no el único modo de satisfacer Constraint 14.

La descripción se genera **antes** de recuperar referencias. Por tanto, este flujo es captioning seguido de recuperación; **no se presenta como una respuesta RAG fundamentada en documentos**, ni como una identificación de especie verificada. Una descripción genérica como «a bird sitting on top of a plant» es una salida válida del modelo, aunque no resuelva la taxonomía.

## 2. Procedencia y resultado

La respuesta conserva:

- identificador y revisión del modelo;
- SHA-256 de la imagen de entrada;
- texto generado;
- referencias recuperadas, con las claves y metadatos de las Tasks 1/2;
- duración total y limitación explícita sobre identificación y exactitud.

No se guarda la consulta, no se generan embeddings persistentes para ella y no se modifica MinIO. Una ampliación futura puede conservar resultados derivados en un almacén separado y versionado; no debe reemplazar el original científico.

## 3. Preparación y uso

La primera ejecución requiere descargar aproximadamente 1 GB de pesos. Es una operación explícita; las siguientes utilizan la caché. No requiere claves de API ni GPU.

```bash
# Una única vez, si BLIP aún no está en la caché
python -m multimodal_tasks.generate ruta/imagen.jpg --allow-model-download

# Operación habitual offline, con la instantánea de búsqueda preparada
python -m multimodal_tasks.generate ruta/imagen.jpg
```

La descarga utiliza la revisión fijada; no sustituye las cuatro familias ya usadas para los 6.021 embeddings. En Windows, la ausencia de symlinks puede aumentar el espacio de caché; no es necesario activar permisos de administrador para utilizar el modelo.

En la interfaz, abrir **Describir una imagen**, seleccionar un JPEG/PNG/WEBP de hasta 10 MB y pulsar **Describir**. La web no inicia descargas: si falta el modelo, indica que debe prepararse localmente. El resultado incluye la descripción y tarjetas de referencias mixtas.

## 4. Validación

Los tests aislados inyectan un captioner controlado y verifican el contrato de salida, hash, revisión, referencias mixtas y rechazo de descripción vacía. Son pruebas de arquitectura; no afirman validar los pesos reales.

La aceptación real ejecuta BLIP en CPU sobre una imagen leída de Trusted y recupera referencias con el encoder CLIP real:

```bash
python -m orchestration.validate_reference --models --task3
```

Si se necesita preparar los pesos durante esa comprobación, añadir explícitamente `--allow-model-download`. Se registra el resultado en `reports/validation/reference.json`. En la ejecución del 23-10-2026 se generó **«a bird sitting on top of a plant»**, se obtuvieron referencias y se comprobaron intactos los ficheros del índice original.

## 5. Límites y evolución

- BLIP está preentrenado con imágenes generales; una descripción plausible puede ser incorrecta o poco específica.
- Las referencias recuperadas permiten explorar y contrastar; no prueban por sí mismas que la frase generada sea verdadera.
- La salida es inglesa; no se añade un segundo modelo de traducción ni se altera el corpus.
- La memoria mínima depende de los pesos y del runtime. No se ha implementado cuantización ni se promete compatibilidad con cualquier equipo.
- Como extensión, podría añadirse generación condicionada por documentos recuperados, con citas y evaluación de grounding. Eso exigiría otro contrato y pruebas; no se declara implementado.

**Fuente:** [ficha oficial de BLIP y ejemplo CPU](https://huggingface.co/Salesforce/blip-image-captioning-base). **Continuación:** [Tasks 1/2](multimodal_tasks_documentation.md) · [Pruebas](testing_and_validation.md).
