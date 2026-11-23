"use strict";

const $ = (selector) => document.querySelector(selector);
const labels = {
  grounding: "Grounding",
  main_takeaway: "Main takeaway",
  useful_context: "Useful context",
  spoken_naturalness: "Spoken naturalness",
  visual_reference: "Visual reference",
  cross_slide_connection: "Cross-slide connection",
  coherence: "Coherence",
};
const state = { examples: [], visible: [], selected: null, run: null, runCount: 0, requestNumber: 0 };

function node(tag, className, content) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content !== undefined && content !== null) item.textContent = String(content);
  return item;
}
function add(parent, ...children) { children.forEach((child) => parent.append(child)); return parent; }
function scoreText(value) { return `${(Number(value) * 100).toFixed(1)}%`; }
function positionText(value) { return ({beginning:"Beginning",middle:"Middle",penultimate_page:"Penultimate"})[value] || value || "Unlabeled"; }

function updateList() {
  const search = $("#search").value.trim().toLowerCase();
  const position = $("#position-filter").value;
  const visual = $("#visual-filter").value;
  const sort = $("#sort").value;
  state.visible = state.examples.filter((item) => {
    const matchesSearch = !search || `${item.example_id} ${item.deck_id}`.toLowerCase().includes(search);
    const matchesPosition = !position || item.position === position;
    const matchesVisual = !visual || (visual === "na" ? item.ratings.visual_reference === null : item.ratings.visual_reference === Number(visual));
    return matchesSearch && matchesPosition && matchesVisual;
  });
  if (sort !== "order") state.visible.sort((a,b) => sort === "score-asc" ? a.score-b.score : b.score-a.score);
  $("#list-count").textContent = `${state.visible.length} of ${state.examples.length} scripts`;
  const list = $("#example-list");
  list.replaceChildren();
  for (const item of state.visible) {
    const button = node("button", `example-item${item.example_id === state.selected ? " active" : ""}`);
    button.type = "button";
    button.setAttribute("aria-label", `${item.deck_id}, slide ${item.slide_number}, score ${scoreText(item.score)}`);
    const top = node("span", "example-top");
    add(top, node("span", "", `${item.deck_id} · slide ${item.slide_number}`), node("span", "mini-score", scoreText(item.score)));
    add(button, top, node("span", "example-sub", `${positionText(item.position)} · visual ${item.ratings.visual_reference ?? "N/A"}`));
    button.addEventListener("click", () => selectExample(item.example_id));
    list.append(button);
  }
}

function section(title, body, side) {
  const wrapper = node("section", "section");
  const head = node("div", "section-head");
  head.append(node("h2", "", title));
  if (side) head.append(side);
  add(wrapper, head, add(node("div", "section-body"), body));
  return wrapper;
}

function slideCard(label, url, page, isTarget) {
  const card = node("div", `slide-card${isTarget ? " target" : ""}`);
  const head = node("div", "slide-label");
  add(head, node("span", "", label), node("span", "", page ? `Page ${page}` : ""));
  card.append(head);
  if (!url) { card.append(node("div", "no-image", "Not provided")); return card; }
  const img = node("img", "slide-image");
  img.src = url;
  img.alt = `${label} image${page ? `, page ${page}` : ""}`;
  img.loading = isTarget ? "eager" : "lazy";
  img.addEventListener("click", () => openImage(label, url));
  add(card, img, node("div", "image-caption", "Click to enlarge"));
  return card;
}

function openImage(label, url) {
  let dialog = $("#image-dialog");
  if (!dialog) {
    dialog = node("dialog", ""); dialog.id = "image-dialog";
    const head = node("div", "dialog-head");
    const title = node("span", ""); title.id = "dialog-title";
    const close = node("button", "", "Close"); close.type = "button";
    close.addEventListener("click", () => dialog.close());
    add(head, title, close);
    const img = node("img", ""); img.id = "dialog-image";
    add(dialog, head, img); document.body.append(dialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  $("#dialog-title").textContent = label;
  $("#dialog-image").src = url;
  $("#dialog-image").alt = label;
  dialog.showModal();
}

function feedbackList(title, values, className) {
  if (!values?.length) return null;
  const box = node("div", className || "");
  box.append(node("span", "feedback-label", title));
  const list = node("ul", "");
  values.forEach((value) => list.append(node("li", "", value)));
  box.append(list);
  return box;
}

function dimensionCard(name, result) {
  const card = node("article", "dimension");
  const head = node("div", "dimension-title");
  const ratingClass = !result.applicable ? "na" : result.score <= 2 ? "low" : result.score === 3 ? "mid" : "";
  add(head, node("h3", "", labels[name] || name), node("span", `rating ${ratingClass}`, result.applicable ? `${result.score} / 5` : "N/A"));
  add(card, head, node("p", "", result.rationale));
  const details = node("details", "");
  details.append(node("summary", "", "Evidence, problems & improvement"));
  for (const entry of [
    feedbackList("Evidence", result.evidence),
    feedbackList("Problems", result.problems, "problem"),
  ]) if (entry) details.append(entry);
  if (result.improvement) details.append(add(node("p", "improvement"), node("span", "feedback-label", "Suggested improvement: "), document.createTextNode(result.improvement)));
  if (!result.evidence?.length && !result.problems?.length && !result.improvement) details.append(node("p", "", "No additional feedback recorded."));
  card.append(details);
  return card;
}

function parametersPanel(generation) {
  const panel = node("div", "");
  const source = node("p", "source-note", `Source: ${generation.source}`);
  const model = generation.model ? `${generation.provider} · ${generation.model}` : "Generator request not recorded";
  add(panel, source, node("p", "meta", model));
  const grid = node("div", "parameters");
  for (const [key, value] of Object.entries(generation.parameters)) {
    const cell = node("div", "parameter");
    add(cell, node("strong", "", key), node("span", "", value));
    grid.append(cell);
  }
  panel.append(grid);
  if (generation.settings) {
    const settings = node("div", "parameter");
    add(settings, node("strong", "", "Model settings"), node("span", "", JSON.stringify(generation.settings)));
    settings.style.marginTop = "9px";
    panel.append(settings);
  }
  if (generation.system_text || generation.user_content) {
    const details = node("details", "prompt-details");
    details.append(node("summary", "", "Inspect the full recorded generator prompt"));
    if (generation.system_text) {
      const block = node("div", "prompt-block");
      add(block, node("strong", "", "SYSTEM INSTRUCTION"), node("pre", "", generation.system_text));
      details.append(block);
    }
    if (generation.user_content) {
      const block = node("div", "prompt-block");
      block.append(node("strong", "", "USER MESSAGE · IN ORDER"));
      generation.user_content.forEach((item, index) => {
        const row = node("div", "content-row");
        add(row, node("strong", "", `${index + 1}. ${item.type}`), node("pre", "", item.type === "image" ? `${item.path}\nSHA-256: ${item.sha256}` : item.text));
        block.append(row);
      });
      details.append(block);
    }
    panel.append(details);
  }
  return panel;
}

function render(data) {
  const main = $("#main"); main.replaceChildren();
  if (state.runCount > 1) main.append(node("p", "run-caution", "Both runs use rubric 1.1.0. Their evaluators differ, so score differences are not solely generator differences."));
  const lead = node("div", "lead");
  const title = node("div", "");
  add(title, node("h2", "", `${data.deck_id} · slide ${data.slide_number}`), node("div", "meta", `${positionText(data.position)} · ${data.slide_type || "Slide type unlabeled"} · ${data.example_id}`));
  add(lead, title, add(node("div", "overall"), node("span", "", scoreText(data.score)), node("small", "", " aggregate")));
  main.append(lead);

  const slides = node("div", "slides");
  add(slides,
    slideCard("Preceding", data.images.preceding, data.images.preceding ? data.slide_number-1 : null, false),
    slideCard("Target", data.images.target, data.slide_number, true),
    slideCard("Following", data.images.following, data.images.following ? data.slide_number+1 : null, false));
  main.append(section("Slide context", slides, node("span", "note", "Images sent to the models")));

  const copy = node("button", "copy-button", "Copy script"); copy.type = "button";
  copy.addEventListener("click", async () => { await navigator.clipboard.writeText(data.script); copy.textContent = "Copied"; setTimeout(() => copy.textContent = "Copy script", 1500); });
  main.append(section("Generated speaker script", node("p", "script", data.script), copy));

  const grid = node("div", "score-grid");
  for (const name of data.dimension_order) grid.append(dimensionCard(name, data.evaluation.dimensions[name]));
  main.append(section("Evaluator ratings", grid, node("span", "note", `${data.evaluation_model || "Evaluator model unavailable"} · rubric ${data.evaluation.rubric_version} · N/A excluded from aggregate`)));
  main.append(section("Generator prompt parameters", parametersPanel(data.generation)));
}

async function selectExample(exampleId) {
  state.selected = exampleId;
  updateList();
  const requestNumber = ++state.requestNumber;
  $("#main").replaceChildren(node("div", "empty", "Loading slide…"));
  try {
    const response = await fetch(`/api/examples/${encodeURIComponent(exampleId)}?run=${encodeURIComponent(state.run)}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const data = await response.json();
    if (requestNumber !== state.requestNumber) return;
    render(data);
    const url = new URL(location.href); url.searchParams.set("example", exampleId); url.searchParams.set("run", state.run);
    history.replaceState({}, "", url);
  } catch (error) {
    $("#main").replaceChildren(node("div", "empty", `Could not load example: ${error.message}`));
  }
}

async function loadRun(runKey, preferredExample) {
  const requestNumber = ++state.requestNumber;
  state.run = runKey;
  $("#main").replaceChildren(node("div", "empty", "Loading run…"));
  try {
    const response = await fetch(`/api/examples?run=${encodeURIComponent(runKey)}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const data = await response.json();
    if (requestNumber !== state.requestNumber) return;
    state.examples = data.examples;
    $("#result-count").textContent = `${data.count} scripts`;
    updateList();
    const selected = state.examples.find((row) => row.example_id === preferredExample)?.example_id || state.examples[0]?.example_id;
    if (selected) selectExample(selected);
    else $("#main").replaceChildren(node("div", "empty", "This run has no completed examples."));
  } catch (error) {
    $("#main").replaceChildren(node("div", "empty", `Could not load run: ${error.message}`));
  }
}

async function start() {
  try {
    const response = await fetch("/api/runs");
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const data = await response.json();
    state.runCount = data.runs.length;
    const selector = $("#run-select");
    for (const run of data.runs) {
      const option = node("option", "", `${run.label} · ${run.results_name}`);
      option.value = run.key;
      selector.append(option);
    }
    for (const selector of ["#search", "#position-filter", "#visual-filter", "#sort"]) $(selector).addEventListener("input", updateList);
    const url = new URL(location.href);
    const requestedRun = url.searchParams.get("run");
    const initialRun = data.runs.find((run) => run.key === requestedRun)?.key || data.default_run;
    selector.value = initialRun;
    selector.addEventListener("change", () => loadRun(selector.value, state.selected));
    loadRun(initialRun, url.searchParams.get("example"));
  } catch (error) {
    $("#main").replaceChildren(node("div", "empty", `Could not load results: ${error.message}`));
  }
}
start();
