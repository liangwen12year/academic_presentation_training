# Fixed-prompt ArcBench baseline

This study measures the unoptimized multimodal seed prompt on **30 ArcBench PDF
decks × 3 target slides = 90 scripts**. It does not invoke GEPA or change the
prompt. Generation uses `gpt-5.6-luna` with reasoning effort `medium`.
Evaluation uses `claude-haiku-5-5` with effort `medium`, the fixed seven-dimension
rubric, and the same target and neighboring slide images. Each target is one
generation call and one evaluation call, so a completed run has 90 of each,
plus any retries after provider errors.

## Selection and rendering

The selector samples 30 of the 100 locally downloaded ArcBench PDFs using a
fixed seed. It chooses page 2, the midpoint page, and the penultimate PDF page.
Manual review is optional. These are positions in the PDF, with no claim that
they contain research content. Use the following positions:

- `beginning`: page 2;
- `middle`: page `(page_count + 1) // 2`;
- `penultimate_page`: page `page_count - 1`.

The three target pages must be distinct. `slide_type` may remain `null`; if you
choose to label slides, use `text`, `chart`, `table`, `diagram`, `equation`,
`image`, `mixed`, or `other`. The type is descriptive metadata, not a model judgment.
The supplied prompt context remains the target slide image, immediate neighbor
images, and the 30-second speaking target. No slide text is extracted for
generation or evaluation.

From the repository root, when ready to prepare the data:

```sh
python -m experiments.baseline.select_arcbench \
  --output data/gepa/baseline_selection_draft.json --seed 33
```

If you already have `data/gepa/baseline_selection_draft.json`, use it directly;
you do not need to generate it again or edit the `reviewed` fields. Existing
drafts with `penultimate_substantive` are accepted and recorded in the manifest
as `penultimate_page`. Render target and neighbor pages at 200 DPI:

```sh
python -m experiments.gepa.prepare_pilot \
  --selection data/gepa/baseline_selection_draft.json \
  --output-root data/gepa/baseline
```

The output is `data/gepa/baseline/manifest.json` and
`data/gepa/baseline/images/`. The manifest records each target's deck, page,
position, slide type, source PDF, and neighboring images. The baseline runner
requires exactly 30 decks and 90 distinct targets.
The selector and renderer require Poppler's `pdfinfo`; rendering also requires
`pdftoppm`.

## Generation and evaluation

From the repository root, create a Python 3.10–3.13 environment, install the
project requirements, and set both provider keys. Keep keys out of Git. The
standalone runner reads environment variables; it does not load `.env`.

```sh
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

Start the paid run after checking the selection file and API budget:

```sh
python -m experiments.baseline.run_baseline \
  --manifest data/gepa/baseline/manifest.json \
  --image-root data/gepa/baseline/images \
  --output-dir data/gepa/runs/baseline_002
```

The runner writes each completed script, evaluator JSON, and both request
audits to `evaluations.jsonl`, plus the prompt snapshots, run configuration,
and `summary.json`. Each audit records the model settings, exact system and
user text submitted to the SDK, and image file paths with SHA-256 hashes in
content-block order. It does not duplicate base64 image payloads. Each request
is also saved **before its API call** as a readable `.txt` file and a structured
`.json` file under `log/generator/` or `log/evaluator/` in the run directory.
The evaluator log includes the generated candidate script. Logs for a failed
call may remain even when that example has no completed result; a retry updates
the corresponding log files. Before any
call, the runner checks that every image fits Claude's
base64 image-size limit. A provider error stops the run; it is not turned into a low
quality score. To continue an interrupted run without repeating completed
examples, use the same command with `--resume`. Resume verifies that the
manifest, prompt, rubric, model settings, and package versions have not changed.

## Inspect the model requests

For example, open
`data/gepa/runs/baseline_002/log/generator/arcbench_006_slide_0002.txt`
or the matching file under `log/evaluator/`. The `.json` files contain the same
request audit in a form suitable for further analysis. The logs are under
`data/`, which is ignored by Git.

To create these files for a run completed before the separate log folders were
added, export the request audits already saved in `evaluations.jsonl`. This
makes no API calls:

```sh
python -m experiments.baseline.export_prompt_logs \
  --results data/gepa/runs/baseline_002/evaluations.jsonl
```

After the run, list completed example IDs and print both recorded requests for
one example. Omit `--example-id` to inspect the first completed example.
This command only reads local files and makes no API calls.

```sh
python -m experiments.baseline.show_prompt \
  --results data/gepa/runs/baseline_002/evaluations.jsonl --list

python -m experiments.baseline.show_prompt \
  --results data/gepa/runs/baseline_002/evaluations.jsonl \
  --example-id EXAMPLE_ID --stage both
```

Use `--stage generation` or `--stage evaluation` to focus on one call. The
printed user message shows its text blocks and the attached preceding, target,
and following slide images in order; the image paths let you open the exact
rendered files. It also checks whether each image still matches the recorded
hash. `generation_prompt.txt` and `evaluator_instructions.txt` are the shared
system instruction snapshots. The generation instruction comes from the
`System instruction` section of the seed prompt; the evaluator instruction
combines its prompt, rubric, and output rules. Slide position and slide type
are analysis metadata, not fields sent to either model.
The seed file's `Multimodal user-message template` is design documentation;
the actual per-slide user message is assembled by `app/speaker_scripts.py` and
is what the audit prints. The evaluator user message includes the generated
candidate script, and its structured output schema is passed through the
Anthropic SDK.

## Distributions

After all 90 examples are complete, create the requested plots without
additional API calls:

```sh
python -m experiments.baseline.plot_results \
  --results data/gepa/runs/baseline_002/evaluations.jsonl \
  --output-dir data/gepa/runs/baseline_002/plots
```

Outputs are `aggregate_score_distribution.png`,
`dimension_rating_distributions.png`, and `distribution_summary.json`.
The aggregate plot covers scores from 0.2 to 1.0, including low grounding
ratings in the same average as the other applicable dimensions. Its interval labels use `[a, b)` for bins
that include `a` but exclude `b`, and `[0.9, 1.0]` for the final bin. It shows
the mean, median, and exact bar counts. Rerunning the plotting command updates
the files in the same output directory. Each dimension plot counts ratings 1–5
and `N/A` where permitted. The summary also reports aggregate scores by
beginning, middle, and penultimate position.

These scores are Claude's rubric judgments, not established ground truth.
The 90 slides are grouped within 30 decks, so the plots are descriptive and
should not be treated as 90 independent presentations.
Before drawing quality conclusions, have people review a subset of scripts
alongside their slides, particularly cases with asserted factual errors or
surprisingly high scores.

## Baseline 2: swap the generator and evaluator

Use the same rendered 90-slide manifest, seed instruction, and rubric 1.1.0.
With `--swap`, Claude Haiku 5.5 generates each script at effort `medium`, and
GPT-5.6 Luna evaluates it at reasoning effort `medium`. Set both API keys as
shown above. Give this run a new output directory so it cannot overwrite the
first baseline:

```sh
python -m experiments.baseline.run_baseline \
  --manifest data/gepa/baseline/manifest.json \
  --image-root data/gepa/baseline/images \
  --output-dir data/gepa/runs/baseline_002_swapped \
  --swap
```

If interrupted, rerun the same command with `--resume`. The run configuration
records both providers and prevents resuming with the wrong pairing. Prompt
audits are saved under `log/generator/` and `log/evaluator/` just as in the
first baseline. Plot the results after all 90 examples finish:

```sh
python -m experiments.baseline.plot_results \
  --results data/gepa/runs/baseline_002_swapped/evaluations.jsonl \
  --output-dir data/gepa/runs/baseline_002_swapped/plots
```

Swapping both roles changes the generator **and** the judge. Differences in
aggregate scores between this run and baseline 1 therefore cannot be assigned
to the generator alone. To compare script quality fairly, score both sets of
scripts with the same evaluator and rubric, then review a sample with people.

## Local qualitative viewer

Open both saved baselines in a read-only browser viewer:

```sh
python -m experiments.baseline.viewer
```

Then open `http://127.0.0.1:8765`. Select **Baseline 1** or **Baseline 2** at
the top; switching keeps the same target slide selected. Baseline 1 uses the
fresh rubric 1.1.0 evaluations from `baseline_001_eval_v1_1` and the original
GPT-5.6 Luna generator requests from `baseline_001`. Baseline 2 uses Claude
Haiku 5.5 generation and GPT-5.6 Luna evaluation. Both runs use the same
90 target slides and rubric, but their evaluators differ, so differences in
ratings are not solely differences in generator quality.

The viewer shows the preceding, target,
and following slide images; the generated script; all seven ratings with
rationales, evidence, problems, and suggestions; and the generator's recorded
prompt parameters and full system/user messages. Search by deck or example ID,
filter by position or visual-reference rating (including N/A), and sort by
aggregate score. Click an image to enlarge it. The server makes no model calls
and binds to the local interface by default.

To inspect only another saved run, supply its results file with `--single-run`.
The manifest and image root defaults are the rendered ArcBench baseline used by
both runs:

```sh
python -m experiments.baseline.viewer \
  --results data/gepa/runs/my_run/evaluations.jsonl --single-run
```

Older results may not contain a generator request audit. In that case, the
viewer labels its prompt fields as a **manifest fallback**, rather than
claiming they were recorded from the model request. Use `--manifest` and
`--image-root` for a different dataset, or `--port` if 8765 is occupied.

## Historical rubric 1.0.0 baseline

The completed `baseline_001` run used rubric 1.0.0, which included a critical
grounding-error flag and a zero-score override. Preserve its results as the
original evaluation. To inspect what the existing dimension ratings would
score under the new aggregation rule, create a separate derived view without
any model calls:

```sh
python -m experiments.baseline.rescore_legacy \
  --source data/gepa/runs/baseline_001/evaluations.jsonl \
  --output-dir data/gepa/runs/baseline_001_rescored
```

This new directory has its own results, summary, plots, and provenance file.
Its ratings still came from the old evaluator instructions, so these plots are
exploratory. A fresh evaluation with rubric 1.1.0 needs new evaluator calls in
an unused run directory; the evaluation-only command below reuses the scripts.

## Evaluate the saved scripts with rubric 1.1.0

To keep the 90 scripts generated in `baseline_001` and get fresh judgments
under rubric 1.1.0, set `ANTHROPIC_API_KEY` in the active environment and run:

```sh
python -m experiments.baseline.evaluate_saved \
  --source-results data/gepa/runs/baseline_001/evaluations.jsonl \
  --manifest data/gepa/baseline/manifest.json \
  --image-root data/gepa/baseline/images \
  --output-dir data/gepa/runs/baseline_001_eval_v1_1
```

This makes **90 Claude evaluation calls and no generation calls**. It leaves
`baseline_001` intact, records each evaluator request under `log/evaluator/`,
and writes fresh rubric 1.1.0 results to `evaluations.jsonl`. An interrupted
run can be continued with the same command plus `--resume`; completed examples
are checked and skipped. To plot the new results:

```sh
python -m experiments.baseline.plot_results \
  --results data/gepa/runs/baseline_001_eval_v1_1/evaluations.jsonl \
  --output-dir data/gepa/runs/baseline_001_eval_v1_1/plots
```
