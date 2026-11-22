"""Compile the repository's workspace into a standalone GitHub Pages demo."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys


DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"The web template changed. Update the Pages adapter for {old[:65]!r}.")
    return text.replace(old, new, 1)


def between(text, first, following, replacement):
    if text.count(first) != 1 or text.count(following) != 1:
        raise ValueError(f"The web template changed near {first!r}.")
    begin = text.index(first)
    end = text.index(following, begin + len(first))
    return text[:begin] + replacement + "\n" + text[end:]


def recorded_review(report, original_bytes):
    path = DEMO / "model-example.json"
    if not path.is_file():
        return None
    item = json.loads(path.read_text("utf-8-sig"))
    digest = hashlib.sha256(original_bytes).hexdigest()
    if not isinstance(item, dict) or item.get("source_sha256") != digest:
        print("Recorded review omitted: its source digest differs from example.json.", file=sys.stderr)
        return None
    candidates = {c["id"]: c for c in report["candidates"]}
    rows = item.get("recommendations")
    if not isinstance(rows, list) or not rows or not isinstance(item.get("model"), str) or not item["model"].strip():
        raise ValueError("Verified model-example.json needs a model name and recorded recommendations.")
    result = []
    for row in rows:
        candidate = candidates.get(row["id"])
        if (not candidate or row["evidence_id"] not in candidate["evidence_ids"] or
                not isinstance(row["why"], str) or not row["why"].strip()):
            print("Recorded review omitted: the current pipeline cannot verify a citation.", file=sys.stderr)
            return None
        result.append({key: row[key] for key in ("id", "evidence_id", "why")})
    return {"model": item["model"], "provider": item.get("provider"), "recommendations": result,
            "considered": item.get("considered"), "total": item.get("total"), "source_sha256": digest}


def static_ui(text):
    text = between(text, "async function call(path, payload, binary = false) {", "function button(label, run, cls)",
                   "async function call(path, payload) { return window.demoCall(path, payload); }")
    text = replace_once(text, "cards(); if (report.candidates.length) choose(report.candidates[0]);",
                        "cards(); if (report.candidates.length) choose(report.candidates[0]);\n  window.demoPaint(source, report, choose);")
    text = between(text, 'register("recommend", async () => {', 'register("save", async () => {',
                   'register("recommend", () => window.demoToggleSuggestions());')
    text = between(text, '    $("model-state").textContent = meta.provider', '    if (!meta.native_import)', "")
    text = replace_once(text, "Example loaded. Inspect a change or open your own source data.",
                        "Example loaded. Inspect a change, approve it, or open your own source data.")
    return text + """
window.getDemoReview = () => state.report ? {source: state.source, report: state.report} : null;
window.inspectDemoCandidate = id => {
  const candidate = state.report && state.report.candidates.find(item => item.id === id);
  if (candidate) { panel("review"); choose(candidate); }
};
"""


SEMANTIC_PANEL = """<section id="live-model"><h2>Find changes by meaning</h2>
<p>Match a review focus to the candidate actions with a small model on this device. The first run downloads the model.</p>
<label>Review focus <input id="semantic-focus" maxlength="600" placeholder="What matters in this review?"></label>
<button type="button" id="semantic-run">Find matching changes</button>
<p id="semantic-status" role="status"></p><div id="semantic-results"></div></section>"""


def static_html(text, title, description, repo_url):
    text = replace_once(text, "<title>Review workspace</title>",
                        "<title>" + html.escape(title) + " · Interactive demo</title>")
    text = replace_once(text, '<link rel="stylesheet" href="/style.css"><script defer src="/ui.js"></script>',
                        '<link rel="stylesheet" href="./style.css"><script defer src="./browser.js"></script>'
                        '<script defer src="./ui.js"></script><script type="module" src="./semantic.js"></script>')
    text = replace_once(text, '<h1 id="title">Review workspace</h1><p id="description"></p>',
                        '<h1 id="title">' + html.escape(title) + '</h1><p id="description">' + html.escape(description) + '</p>')
    text = replace_once(text, '>Project workspace</p>', '>Interactive browser demo</p>')
    text = replace_once(text, '<p id="status"', '<p id="demo-runtime">Loading the bundled example…</p>\n<p id="status"')
    text = replace_once(text, '<hr><h2>Model review</h2>', '<hr>' + SEMANTIC_PANEL + '<hr><h2>Recorded model review</h2>')
    text = between(text, '<label>Review focus <input id="focus"', '<div id="suggestions">',
                   '<button id="recommend" type="button" hidden aria-controls="suggestions">Show recorded suggestions</button>')
    text = replace_once(text, '</div></aside>', '</div><p><a href="' + html.escape(repo_url, quote=True) +
                        '#model-assisted-review">Run the full workspace for fresh generative model reviews ↗</a></p></aside>')
    text = replace_once(text, 'Save the current source, approvals and notes. Copy the workspace ID to reopen its history.',
                        'Revisions are saved in this browser on this device. Reopen a workspace by choosing or pasting its ID.')
    text = replace_once(text, '<label>Deployment key <input id="key" type="password" autocomplete="off" placeholder="Optional on localhost"></label>', '')
    text = replace_once(text, '<input id="workspace" placeholder="Assigned on first save" spellcheck="false">',
                        '<input id="workspace" list="demo-workspaces" placeholder="Assigned on first save" spellcheck="false">'
                        '<datalist id="demo-workspaces"></datalist>')
    return text


def build(output):
    output = output.resolve()
    if output in {ROOT, DEMO, ROOT / "web"}:
        raise ValueError("Choose an output directory separate from the source files.")
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    import pipeline
    import studio

    page = (ROOT / "web/index.html").read_text("utf-8")
    repository = re.search(r'href="(https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"', page)
    if not repository:
        raise ValueError("The workspace footer needs its repository link.")
    if repository.group(1).endswith("/REPO_SLUG"):
        raise ValueError("The workspace footer must point to the published repository.")
    repo_url = repository.group(1)
    source_bytes = (ROOT / "example.json").read_bytes()
    source = json.loads(source_bytes.decode("utf-8-sig"))
    report = studio.analyze(source)
    meta = {"project": repo_url.removeprefix("https://github.com/"), "title": pipeline.TITLE,
            "description": pipeline.DESCRIPTION, "native_import": hasattr(pipeline, "import_text"),
            "source": source, "report": report, "recorded": recorded_review(report, source_bytes)}
    for name in ("pipeline.py", "studio.py", "providers.py", "example.json"):
        shutil.copyfile(ROOT / name, output / name)
    for name in ("worker.js", "bridge.py", "browser.js", "semantic.js"):
        shutil.copyfile(DEMO / name, output / name)
    shutil.copyfile(ROOT / "web/style.css", output / "style.css")
    (output / "demo-data.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    (output / "ui.js").write_text(static_ui((ROOT / "web/ui.js").read_text("utf-8")), encoding="utf-8")
    (output / "index.html").write_text(static_html(page, pipeline.TITLE, pipeline.DESCRIPTION, repo_url), encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f"Built {repo_url} browser workspace in {output}")


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
