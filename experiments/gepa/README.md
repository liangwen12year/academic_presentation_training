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

Suggested initial split:

- development set: used by GEPA for feedback and prompt selection;
- validation set: used for configuration decisions without prompt evolution;
- held-out test set: used once for the final comparison.

Downloaded PDFs, rendered images, and generated audio remain local and should
not be committed. A future manifest may be committed if it contains only
reproducible dataset identifiers, relative paths, checksums, split assignments,
and non-sensitive metadata.

## Baselines

At minimum, compare:

1. the unmodified `seed_v1_multimodal.md` prompt;
2. a minimal instruction such as "Write a speaker script for this slide"; and
3. the prompt selected by GEPA.

Use the same examples, model settings, evidence inputs, and evaluator version
for all systems in a comparison.

## Evaluation protocol

For every candidate script:

1. render and attach the target slide image;
2. supply the same available context used during generation;
3. run the fixed evaluator prompt with the YAML rubric;
4. retain all seven dimension scores and the diagnostic feedback;
5. compute the unweighted mean over applicable dimensions; and
6. reject the candidate from optimization selection if the evaluator identifies
   a critical grounding error.

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
6. Stop according to a declared call, token, or cost budget.
7. Freeze the selected prompt before evaluating the held-out test set.
8. Compare the selected prompt with every baseline and manually inspect both
   improvements and regressions.

The GEPA library integration and exact command-line interface are intentionally
left unspecified until the package version and model provider are selected.

## Reproducibility record

Each run should record at least:

- run identifier and timestamp;
- Git commit and working-tree state;
- dataset manifest and split version;
- generation and evaluator prompt contents or hashes;
- generation and evaluator model identifiers;
- API/provider version when available;
- temperature, reasoning effort, random seed, and output limits;
- slide rendering resolution and image-detail setting;
- target speaking-time policy;
- GEPA configuration and stopping budget;
- raw candidate scripts and evaluator JSON;
- token usage, latency, and estimated cost; and
- aggregate, per-dimension, and grounding-failure results.

Store credentials only in environment variables or an ignored `.env` file.
Generated outputs should live in an ignored local results directory unless a
small, reviewed fixture is deliberately added for testing.

## Initial success criteria

Before calling an optimized prompt better than the seed prompt, require:

- no increase in critical grounding-error rate;
- an improvement in the preregistered aggregate on the held-out test set;
- no substantial unexplained regression in any individual dimension;
- qualitative human review of representative gains and failures; and
- reported token and monetary cost alongside quality results.

These criteria should be finalized before the held-out test set is evaluated.
