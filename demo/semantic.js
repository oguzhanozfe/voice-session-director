// Semantic search runs in a worker. The user's focus and source records stay on this device.
if (typeof window === "undefined") {
  let extractor;
  async function encoder() {
    if (!extractor) {
      extractor = (async () => {
        const {pipeline, env} = await import("./ai/transformers.min.js");
        env.allowRemoteModels = false;
        env.allowLocalModels = true;
        env.localModelPath = new URL("./ai/models/", import.meta.url).href;
        env.backends.onnx.wasm.wasmPaths = new URL("./ai/", import.meta.url).href;
        env.backends.onnx.wasm.numThreads = 1;
        env.backends.onnx.wasm.proxy = false;
        return pipeline("feature-extraction", "minilm", {dtype: "q8", device: "wasm"});
      })().catch(error => { extractor = undefined; throw error; });
    }
    return extractor;
  }
  self.onmessage = async event => {
    try {
      const {focus, candidates} = event.data;
      const encode = await encoder();
      const options = {pooling: "mean", normalize: true};
      const [query] = (await encode([focus], options)).tolist();
      const matches = [];
      for (let from = 0; from < candidates.length; from += 4) {
        const batch = candidates.slice(from, from + 4);
        const vectors = (await encode(batch.map(c => c.text), options)).tolist();
        vectors.forEach((v, i) => {
          const score = v.reduce((total, value, j) => total + value * query[j], 0);
          matches.push({id: batch[i].id, evidence: batch[i].evidence, score});
        });
      }
      matches.sort((a, b) => b.score - a.score);
      self.postMessage({matches: matches.slice(0, 3)});
    } catch (error) {
      self.postMessage({error: "The browser model could not run. Check the connection and try a current browser with WebAssembly. " + error.message});
    }
  };
} else {
  const el = id => document.getElementById(id);
  const status = el("semantic-status"), list = el("semantic-results"), button = el("semantic-run");
  let worker, generation = 0;
  const invalidate = () => {
    generation++;
    list.replaceChildren();
    status.textContent = "";
  };
  window.addEventListener("demoreviewchange", invalidate);
  el("semantic-focus").addEventListener("input", invalidate);
  button.addEventListener("click", async () => {
    const focus = el("semantic-focus").value.trim();
    const report = window.getDemoReview?.()?.report;
    if (!focus || !report) {
      status.textContent = "Enter a review focus and load a source first.";
      return;
    }
    const lookup = new Map(report.records.map(record => [record.id, record]));
    const candidates = report.candidates.slice(0, 16).map(item => {
      const ids = item.evidence_ids.slice(0, 2);
      const proposal = Object.fromEntries(Object.entries(item).filter(([k]) => !["id", "action", "evidence_ids"].includes(k)));
      const text = [item.action, JSON.stringify(proposal).slice(0, 260), ...ids.map(id => JSON.stringify(lookup.get(id) ?? {}).slice(0, 240))].join(" ");
      return {id: item.id, evidence: ids, text};
    });
    if (!candidates.length) {status.textContent = "This source has no proposed changes."; return;}
    const version = ++generation;
    list.replaceChildren();
    button.disabled = true;
    status.textContent = "Loading MiniLM and matching the review focus on this device…";
    try {
      worker ||= new Worker(new URL("./semantic.js", import.meta.url), {type: "module"});
      const matches = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          worker.terminate(); worker = undefined;
          reject(Error("Model loading timed out. Check the connection and try again."));
        }, 150000);
        worker.onmessage = ({data}) => { clearTimeout(timeout); data.error ? reject(Error(data.error)) : resolve(data.matches); };
        worker.onerror = event => {
          clearTimeout(timeout); worker.terminate(); worker = undefined;
          reject(Error(event.message || "Browser model unavailable."));
        };
        worker.postMessage({focus, candidates});
      });
      if (version !== generation) return;
      for (const match of matches) {
        const item = report.candidates.find(c => c.id === match.id);
        if (!item) continue;
        const row = document.createElement("article");
        row.className = "card"; row.dataset.candidate = item.id;
        const title = document.createElement("strong"); title.textContent = item.action;
        const info = document.createElement("small");
        info.textContent = "Cosine similarity " + match.score.toFixed(3) + " · Source: " + match.evidence.join(", ");
        const inspect = document.createElement("button"); inspect.type = "button";
        inspect.textContent = "Inspect evidence"; inspect.onclick = () => window.inspectDemoCandidate?.(item.id);
        row.append(title, info, inspect); list.append(row);
      }
      status.textContent = "MiniLM ranked " + candidates.length + " of " + report.candidates.length + " changes by meaning. Scores measure text similarity.";
    } catch (error) {
      if (version === generation) status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
}
