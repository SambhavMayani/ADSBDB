# EcoSentinel presentation

**English / 19 slides / rehearsal target 19:20, with a margin up to 20 minutes.**

- [Editable PowerPoint](EcoSentinel_presentation.pptx), with full speech and source references in slide notes.
- [Projection PDF](EcoSentinel_presentation.pdf), a fixed-layout backup.
- [Speaker script PDF](speaker_script.pdf), timing overview and one page per slide.
- [Editable script](speaker_script.md), including answers to likely examiner questions.
- [Content source](presentation_content.json), [recorded retrieval examples](task_examples.json) and [quality chart data](quality_charts.json).
- [Pipeline overview](pipeline_overview.png), the architecture diagram from slide 4 exported as an image.

Mario covers slides 1–6 (00:00–06:30), Sambhav 7–14 (06:30–13:20), and Wassim 15–19 (13:20–19:20). Speaker allocation is a proposal. Rehearse together; actual duration depends on pace and pauses. Questions and live CPU inference are outside the timed talk.

## Decisions and report examples

Slide 5 explains completed-ingest reuse. Slide 6 assigns representation choices to **Formatted**: RGB JPEG at encoder quality 95; original image dimensions, without crop/resize; white beneath transparency; FLAC PCM16 preserving audio rate/channels/duration; UTF-8, LF and NFC while retaining language/case/punctuation. The speech explains JPEG loss, quantisation, extraction loss, EXIF and primary-frame handling. Original bytes remain in Landing. Model-specific adaptation belongs in Exploitation.

Slide 7 explains **Trusted** quality rules and budgets: images 20 decimal MB, 40 MP and minimum 128 by 128; audio 200 MB; text 4 MB. These are operational thresholds. Warnings remain distinct from rejection, and later errors/rejections retain earlier accepted bytes.

Slide 8 shows the actual 19 October 2026 image-quality report. Slides 9 and 10 contain **editable native charts** derived from its recorded data and the corresponding audio report. Images remain at ten per species, with zero observed Jensen–Shannon distribution shift. All 34 recordings remain accepted, including nine with many low-energy windows. Neither metric proves biological correctness or population representativeness.

The audio chart groups existing per-recording measurements into fixed 20-percentage-point bins for legibility. The original HTML uses six data-dependent bins. No per-asset measurement or quality decision was recomputed. The data file records bin boundaries, counts, source CSV hash and image species-label mapping. English chart labels abbreviate golden eagle, Iberian lynx and ocellated lizard; full species IDs remain in the data. PowerPoint embeds chart data snapshots for editing.

## Task examples and validation

Slide 13 shows actual Task 1 matches at ranks 1 and 3, with the full five-asset ranking retained in the JSON. Four catalogue labels are lynx and one is wolf; rank 2 is a cropped variant. Slide 14 shows the exact Task 2 query, overall image hit 5 and text hit 4 from eight results under the diversity policy. Scores are not identification probabilities.

Slide 16 uses the recorded real-model frog UI example. The interface remains in Spanish and the enlarged extracts are English translations. A complete-genome abstention is a separate test. Slide 18 explains the harmless executable-header fixture and the recorded regression results: 364 offline tests, one isolated integration test, 71.82% combined statement coverage.

The pipeline, encoder and RAG diagrams use editable PowerPoint shapes/connectors. Corpus photographs retain attribution/licences in notes and the example JSON. The slide 2 photograph is illustrative, not claimed to be the recorded RAG acceptance image. Original media and vectors were not rebuilt for this presentation.

Open the PPTX in the classroom software before the defence; package/import/layout checks do not establish identical native font rendering. Use the PDF as fallback. Remote CI must be checked for the submitted commit. The examples are qualitative rather than a labelled biological accuracy benchmark.
