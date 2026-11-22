"use strict";
const $ = id => document.getElementById(id);
const state = {source: {}, report: null, choices: new Map(), current: null, limit: 18, workspace: null, revision: 0, initial: null};
const element = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
function status(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}
async function call(path, payload, binary = false) {
  const response = await fetch("/api/" + path, payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Workspace-Key": $("key").value},
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw Error((await response.json()).error || "Request failed.");
  return binary ? response.blob() : response.json();
}
function button(label, run, cls) {
  const node = element("button", label, cls);
  node.onclick = () => guarded(node, run);
  return node;
}
async function guarded(node, run) {
  node.disabled = true;
  try { await run(); } catch (err) { status(err.message, true); }
  finally { node.disabled = false; }
}
function panel(id) {
  for (const node of document.querySelectorAll("[data-panel]")) {
    const active = node.dataset.panel === id;
    $(node.dataset.panel).hidden = !active;
    node.setAttribute("aria-pressed", String(active));
  }
}
function choose(item) {
  state.current = item.id;
  $("indicator").textContent = item.action;
  const index = state.index;
  const records = item.evidence_ids.slice(0, 12).map(key => element("pre", JSON.stringify(index.get(key), null, 2)));
  const fields = Object.fromEntries(Object.entries(item).filter(([key]) => !["id","action","evidence_ids"].includes(key)));
  const proposal = Object.keys(fields).length ? [element("strong","Proposed change"), element("pre", JSON.stringify(fields, null, 2).slice(0, 2500))] : [];
  $("evidence").replaceChildren(...proposal, element("strong","Source records"), ...records);
  if (item.evidence_ids.length > 12) $("evidence").append(element("p", "Showing the first 12 linked records."));
  for (const card of document.querySelectorAll(".card")) card.classList.toggle("current", card.dataset.id === item.id);
}
function cards() {
  const list = $("candidates");
  list.replaceChildren();
  for (const item of state.report.candidates.slice(0, state.limit)) {
    const card = element("article", undefined, "card");
    card.dataset.id = item.id;
    card.classList.toggle("current", state.current === item.id);
    const label = element("label"), check = element("input");
    check.type = "checkbox";
    check.checked = state.choices.has(item.id);
    label.append(check, element("span", item.action));
    const note = element("textarea");
    note.rows = 2; note.maxLength = 1200; note.placeholder = "Optional review note";
    note.setAttribute("aria-label", "Review note for " + item.id);
    note.hidden = !check.checked; note.value = state.choices.get(item.id) || "";
    note.oninput = () => state.choices.set(item.id, note.value);
    check.onchange = () => {
      if (check.checked) state.choices.set(item.id, note.value); else state.choices.delete(item.id);
      note.hidden = !check.checked; choose(item); count();
      status(state.choices.size + " approved change(s). Open Release preview to inspect the output.");
    };
    card.append(label, element("small", item.id), button("Inspect " + item.evidence_ids.length + " source record(s)", () => choose(item), "details"), note);
    list.append(card);
  }
  if (!state.report.candidates.length) list.append(element("p", "No proposed changes for this input."));
  $("more").hidden = state.report.candidates.length <= state.limit;
  count();
}
function count() { $("count").textContent = state.choices.size + " approved / " + state.report.candidates.length; }
function paint(source, report, choices = {}) {
  state.source = source; state.report = report; state.choices = new Map(Object.entries(choices));
  state.limit = 18; state.current = null; state.index = new Map(report.records.map(r => [r.id, r]));
  $("input").value = JSON.stringify(source, null, 2); $("summary").textContent = report.summary;
  $("suggestions").replaceChildren(); $("evidence").replaceChildren(); $("indicator").textContent = "";
  $("metrics").replaceChildren(...Object.entries(report.metrics).map(([name, value]) => {
    const node = element("div", undefined, "metric");
    node.append(element("b", typeof value === "object" ? JSON.stringify(value) : String(value)), element("small", name));
    return node;
  }));
  cards(); if (report.candidates.length) choose(report.candidates[0]);
}
async function analyze(source) {
  const report = await call("analyze", {source});
  paint(source, report); panel("review"); status("Input analyzed. Select changes to include in your release.");
}
function payload() { return {source: state.source, choices: Object.fromEntries(state.choices)}; }
function register(id, run) { $(id).onclick = () => guarded($(id), run); }
async function openRevision(workspace, revision) {
  const saved = await call("read", {workspace, revision});
  const report = await call("analyze", {source: saved.source});
  paint(saved.source, report, saved.choices); state.workspace = workspace; state.revision = saved.revision;
  $("workspace").value = workspace; await versions(); status("Opened revision " + saved.revision + ".");
}
async function versions() {
  const list = await call("history", {workspace: state.workspace});
  $("revision").textContent = "Current revision " + state.revision;
  $("difference").hidden = true;
  $("versions").replaceChildren(...list.map(row => {
    const node = element("article");
    node.append(element("span", "Revision " + row.revision + " · " + row.created),
      button("Open", () => openRevision(state.workspace, row.revision)),
      button("Compare with current", async () => {
        const diff = await call("compare", {workspace: state.workspace, before: row.revision, after: state.revision});
        $("difference").hidden = false; $("difference").textContent = JSON.stringify(diff, null, 2);
      }));
    return node;
  }));
}
for (const node of document.querySelectorAll("[data-panel]")) node.onclick = async () => {
  panel(node.dataset.panel);
  if (node.dataset.panel !== "files") return;
  $("artifacts").replaceChildren();
  try {
    const files = await call("artifacts", payload());
    for (const [name, file] of Object.entries(files)) {
      const part = element("article", undefined, "card");
      part.append(element("h2", name), element("small", file.characters + " characters"), element("pre", file.text));
      $("artifacts").append(part);
    }
  } catch (err) { status(err.message, true); }
};
register("more", () => { state.limit += 30; cards(); });
register("analyze", () => analyze(JSON.parse($("input").value)));
register("reset", () => analyze(state.initial));
$("upload").onchange = async event => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 800000) throw Error("The input must fit within 800 KB.");
    const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) await analyze(JSON.parse(text));
    else {
      const result = await call("import", {filename: file.name, text});
      paint(result.source, result.report); panel("review"); status("Imported " + file.name);
    }
  } catch (err) { status(err.message, true); }
  event.target.value = "";
};
register("export", async () => {
  const blob = await call("export", payload(), true);
  const url = URL.createObjectURL(blob), link = element("a");
  link.href = url; link.download = "reviewed-release.zip"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  status("Downloaded release with " + state.choices.size + " approved change(s).");
});
register("recommend", async () => {
  const source = state.source;
  status("Waiting for evidence-linked model suggestions…");
  const result = await call("recommend", {source, focus: $("focus").value});
  if (source !== state.source) return status("The input changed while the model was reviewing.");
  $("suggestions").replaceChildren(...result.recommendations.map(row => {
    const node = element("article"), item = state.report.candidates.find(c => c.id === row.id);
    node.append(element("p", row.why), element("small", row.evidence_id), button("Inspect suggestion", () => choose(item)));
    return node;
  }));
  status("Model considered " + result.considered + " of " + result.total + " changes. Review each suggestion before approving.");
});
register("save", async () => {
  if ($("workspace").value.trim() !== (state.workspace || "")) throw Error("Open that workspace first, or start a separate workspace.");
  const saved = await call("save", {...payload(), workspace: state.workspace, base: state.revision});
  state.workspace = saved.workspace; state.revision = saved.revision; $("workspace").value = saved.workspace;
  await versions(); status("Saved revision " + saved.revision + ".");
});
register("open", () => openRevision($("workspace").value.trim(), null));
register("fork", () => {
  state.workspace = null; state.revision = 0; $("workspace").value = ""; $("versions").replaceChildren();
  $("revision").textContent = ""; $("difference").hidden = true; status("The next save will start a separate workspace with the current review.");
});
(async () => {
  try {
    const meta = await call("example");
    document.title = meta.title; $("title").textContent = meta.title; $("footer-title").textContent = meta.title;
    $("description").textContent = meta.description; state.initial = meta.source;
    $("model-state").textContent = meta.provider === "off" ? "Configure a local or hosted model to request cited suggestions." : "Configured provider: " + meta.provider;
    $("recommend").disabled = meta.provider === "off";
    if (!meta.native_import) $("upload").accept = ".json,application/json";
    await analyze(meta.source); status("Example loaded. Inspect a change or open your own source data.");
  } catch (err) { status(err.message, true); }
})();
