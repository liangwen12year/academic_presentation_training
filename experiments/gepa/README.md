# GEPA speaker-script prompt optimization

## Objective

Use GEPA to improve the multimodal prompt that generates a speaker script for
one research-presentation slide. Candidate prompts will be evaluated on seven
dimensions:

1. grounding in the slide and supplied sources,
2. a clear main takeaway,
3. useful, supported context,
4. natural spoken delivery,
5. meaningful visual reference,
6. connection across slides, and
7. coherence.

The first goal is not to claim that the resulting prompt is universally
optimal. It is to establish a reproducible comparison against the current seed
prompt on a held-out set of research slides.

## Current artifacts

- Generation baseline:
  `prompts/speaker_script_gen/seed_v1_multimodal.md`
- Evaluator prompt:
  `prompts/gepa_eval/evaluator_prompt.md`
- Evaluation rubric:
  `evaluation/speaker_script_rubric.yaml`
- Validated evaluator output model and scalar score:
  `evaluation/evaluator_schema.py`, `evaluation/scoring.py`
- Pilot preparation, fixed-prompt evaluation, and GEPA runners:
  `experiments/gepa/prepare_pilot.py`, `experiments/gepa/run_evaluation.py`,
  `experiments/gepa/run_optimization.py`

The generation prompt is the object GEPA may modify. The evaluator prompt and
rubric should remain fixed during an optimization run. If either evaluator
artifact changes, start a new run and record the new version rather than mixing
scores across versions.

## Evaluation unit and inputs

One example consists of:

- a required target slide image;
- presentation title, slide number, intended audience, and target speaking
  time when available;
- preceding- and following-slide images when available;
- optional speaker notes, raw script, or relevant source excerpt; and
- one candidate speaker script.

The target image is primary evidence. Neighboring slide images provide
narrative context and must be clearly labeled so their content is not mistaken
for content on the target slide.

## Dataset construction

Begin with a small, inspectable sample of approximately 50--100 slides from the
locally downloaded ArcBench and MIT OpenCourseWare material. Include varied
slide types:

- text-heavy slides;
- charts and plots;
- tables;
- diagrams and pipelines;
- equations;
- image-dominant slides; and
- title, section, and transition slides.

Split examples by presentation deck, not by individual slide. All slides from
one deck must belong to only one split. This prevents neighboring slides and a
deck's repeated language or design from leaking between development and test
sets.

Implemented split:

- `train`: examples GEPA uses for reflective feedback;
- `val`: examples GEPA uses to compare and select prompt candidates;
- `test`: held out from GEPA and used only after prompt selection.

`example_selection.json` selects one target slide from each of three ArcBench
decks. It illustrates the wiring and deck separation. Its page counts have not
been checked, and three slides cannot establish that an optimized prompt is
better. Expand and inspect this selection before a meaningful study.

Downloaded PDFs, rendered images, and generated audio remain local and should
not be committed. A future manifest may be committed if it contains only
reproducible dataset identifiers, relative paths, checksums, split assignments,
and non-sensitive metadata.

## Baselines

The separate fixed-prompt 90-script ArcBench study is documented in
`experiments/baseline/README.md`. It uses the seed prompt without GEPA.

The prototype compares:

1. the unmodified `seed_v1_multimodal.md` prompt;
2. the prompt selected by GEPA.

A later study can add a minimal instruction or the existing text-only app
prompt as additional baselines. This prototype does not generate those scores.

Use the same examples, model settings, evidence inputs, and evaluator version
for all systems in a comparison.

## Evaluation protocol

For every candidate script:

1. render and attach the target slide image;
2. supply the same available context used during generation;
3. run the fixed evaluator prompt with the YAML rubric;
4. retain all seven dimension scores and the diagnostic feedback;
5. divide the unweighted mean over applicable 1--5 scores by 5 to produce a
   0.2--1.0 scalar. Factual errors are reflected in the grounding dimension.

Equal weighting is a provisional engineering choice. Report the seven-score
vector alongside any aggregate so an improvement in style cannot hide a loss
of factual grounding. Visual reference and cross-slide connection may be
`not_applicable` under the conditions defined in the rubric.

The evaluator's prose feedback is part of the GEPA signal. It should identify
specific failures and suggest prompt-level improvements without writing a
replacement candidate script.

## Human validation before optimization

Before trusting the model-based evaluator:

1. ask at least two human raters to score the same 20--30 candidate scripts;
2. randomize script order and hide the generating prompt or model;
3. compare human--human and evaluator--human agreement by dimension;
4. inspect disagreements, especially polished hallucinations, copied slide
   text, charts, and scripts with missing optional context; and
5. revise and version the rubric or evaluator if systematic errors appear.

Do not tune the evaluator on the held-out test set.

## GEPA experiment loop

After evaluator validation, one optimization run should follow this sequence:

1. Generate baseline scripts on the development examples.
2. Evaluate them and preserve dimension-level scores and feedback.
3. Allow GEPA to propose mutations of the generation prompt.
4. Generate and evaluate scripts using each candidate prompt under identical
   settings.
5. Select candidates using the configured score while checking the full score
   vector and grounding failures.
6. Stop according to the declared GEPA metric-call budget and separately
   monitor provider token and monetary use.
7. Freeze the selected prompt before evaluating the held-out test set.
8. Compare the selected prompt with the seed and manually inspect both
   improvements and regressions.

The prototype targets the published GEPA 0.1.4 `optimize_anything` interface:
`seed_candidate`, `evaluator`, `dataset`, `valset`, and `GEPAConfig`. That
version has no `test_set` parameter. The optimization runner never evaluates
the test split; `run_evaluation.py` has a separate, explicitly unlocked final
comparison mode. `max_metric_calls` caps GEPA
metric evaluations; each evaluation makes one generation and one evaluator API
call. GEPA reflection calls and a later held-out comparison add more calls.

## Commands for the later review and run

These commands document the intended sequence. They have **not been run** as
part of this prototype. From the repository root, first inspect and expand
`experiments/gepa/example_selection.json`. ArcBench PDFs are expected in
`data/slides/arcbench/slides/`. Rendering needs Poppler's `pdfinfo` and
`pdftoppm` executables.

```sh
python -m experiments.gepa.prepare_pilot \
  --selection experiments/gepa/example_selection.json \
  --output-root data/gepa/pilot
```

The preparer checks the chosen PDFs and page numbers, renders each target and
available neighboring pages at 200 DPI, and writes
`data/gepa/pilot/manifest.json` plus `data/gepa/pilot/images/`. These outputs
are ignored by Git. It refuses to overwrite an existing output directory.

After reviewing the manifest and validating the rubric with human ratings,
install the project dependencies in a Python 3.10--3.13 environment and set
an OpenAI API key:

```sh
uv pip install -r requirements.txt
export OPENAI_API_KEY=...
```

To evaluate a fixed prompt on the training split:

```sh
python -m experiments.gepa.run_evaluation \
  --manifest data/gepa/pilot/manifest.json \
  --image-root data/gepa/pilot/images \
  --split train \
  --generation-model YOUR_IMAGE_CAPABLE_MODEL \
  --evaluator-model YOUR_STRUCTURED_OUTPUT_MODEL \
  --output-dir data/gepa/runs/seed_train
```

Once the evaluator and dataset are ready, run GEPA with a declared budget:

```sh
python -m experiments.gepa.run_optimization \
  --manifest data/gepa/pilot/manifest.json \
  --image-root data/gepa/pilot/images \
  --generation-model YOUR_IMAGE_CAPABLE_MODEL \
  --evaluator-model YOUR_STRUCTURED_OUTPUT_MODEL \
  --reflection-model YOUR_REFLECTION_MODEL \
  --max-metric-calls 100 \
  --output-dir data/gepa/runs/pilot_001
```

After choosing and freezing the final prompt, compare it with the seed on the
untouched test split once:

```sh
python -m experiments.gepa.run_evaluation \
  --manifest data/gepa/pilot/manifest.json \
  --image-root data/gepa/pilot/images \
  --split test --allow-test \
  --prompt prompts/speaker_script_gen/seed_v1_multimodal.md \
  --compare-prompt data/gepa/runs/pilot_001/best_prompt.txt \
  --generation-model YOUR_IMAGE_CAPABLE_MODEL \
  --evaluator-model YOUR_STRUCTURED_OUTPUT_MODEL \
  --output-dir data/gepa/runs/final_test
```

The generation and evaluator model names must support slide images; the
evaluator must also support structured JSON output. The reflection model is
passed to GEPA through LiteLLM and need not process slide images. Reasoning
effort and output limits have optional flags in each runner. Model and rubric
failures stop the run; they are not silently recorded as low script quality.

To try a reviewed prompt through the web app, put these values in the ignored
`.env` file and restart the app:

```dotenv
OPENAI_API_KEY=...
SPEAKER_SCRIPT_PROMPT_PATH=data/gepa/runs/pilot_001/best_prompt.txt
SPEAKER_SCRIPT_MODEL=YOUR_IMAGE_CAPABLE_MODEL
```

This app path uses the same image-based generation request. For PPTX, it
requires LibreOffice to render every slide fully. The existing app behavior
remains the default when `SPEAKER_SCRIPT_PROMPT_PATH` is absent.

## Reproducibility record

The optimization run records:

- run identifier and timestamp;
- Git commit;
- dataset manifest hash and split counts;
- generation and evaluator prompt contents and hashes;
- generation and evaluator model identifiers;
- installed GEPA and OpenAI package versions;
- reasoning effort, random seed, and output limits;
- image-detail setting and preparation manifest rendering resolution;
- GEPA metric-call budget;
- raw candidate scripts and evaluator JSON;
- generation and evaluator token usage when returned by the provider; and
- aggregate, per-dimension, and grounding-failure results.

The fixed-prompt evaluation runner records its prompt, manifest, models,
individual results, and aggregate score in a separate output directory.
Latency, model price snapshots, monetary cost, and working-tree state are not
yet recorded. A full study should add them before reporting total cost.

Store credentials only in environment variables or an ignored `.env` file.
Generated outputs should live in an ignored local results directory unless a
small, reviewed fixture is deliberately added for testing.

## Initial success criteria

Before calling an optimized prompt better than the seed prompt, require:

- no substantial unexplained regression in the grounding dimension;
- an improvement in the preregistered aggregate on the held-out test set;
- no substantial unexplained regression in the other individual dimensions;
- qualitative human review of representative gains and failures; and
- reported token and monetary cost alongside quality results.

These criteria should be finalized before the held-out test set is evaluated.
