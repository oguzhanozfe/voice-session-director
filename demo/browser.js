/* Static Pages transport. Python computes new reports and exports in a worker. */
(() => {
  "use strict";
  let sample;
  let sampleRequest;
  let worker;
  let nextId = 0;
  const pending = new Map();
  const byId = id => document.getElementById(id);
  const runtimeStatus = message => { byId("demo-runtime").textContent = message; };
  const ready = () => runtimeStatus("Python is ready. Source files and exports are processed on this device.");
  let runtimeReady = false;
  let warmStarted = false;

  function loadSample() {
    if (!sampleRequest) {
      sampleRequest = fetch("./demo-data.json").then(response => {
        if (!response.ok) throw Error("The published example could not be loaded. Reload this page.");
        return response.json();
      }).then(value => (sample = value)).catch(error => {
        sampleRequest = null;
        throw error;
      });
    }
    return sampleRequest;
  }

  // Key order does not change a JSON object. Array order and scalar types do.
  function sameJSON(a, b) {
    if (a === b) return true;
    if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length &&
      keys.every(k => Object.prototype.hasOwnProperty.call(b, k) && sameJSON(a[k], b[k]));
  }

  function stopWorker(message) {
    if (worker) worker.terminate();
    worker = undefined;
    runtimeReady = false;
    runtimeStatus("The Python runtime could not complete this request. Check your connection to this site and try again.");
    for (const {reject, timer} of pending.values()) {
      clearTimeout(timer);
      reject(Error(message));
    }
    pending.clear();
  }

  function python(path, payload) {
    if (!worker) {
      runtimeStatus("Loading Python on this device. You can inspect the example while it starts.");
      worker = new Worker(new URL("./worker.js", document.baseURI));
      worker.onerror = () => stopWorker("The browser could not start the local Python worker. Retry the operation.");
      worker.onmessageerror = () => stopWorker("The browser could not read the Python worker response.");
      worker.onmessage = event => {
        const {id, result, error} = event.data;
        const request = pending.get(id);
        if (!request) return;
        pending.delete(id);
        clearTimeout(request.timer);
        if (error !== undefined && error !== null) {
          if (!runtimeReady) runtimeStatus("Python could not finish startup. Retry an action to load the runtime again.");
          request.reject(Error(String(error)));
          return;
        }
        if (!runtimeReady) { runtimeReady = true; ready(); }
        request.resolve(result);
      };
    }
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => stopWorker("The local calculation timed out. Please retry."), 180000);
      pending.set(id, {resolve, reject, timer});
      try { worker.postMessage({id, path, payload}); }
      catch (error) {
        pending.delete(id); clearTimeout(timer); reject(error);
      }
    });
  }

  let databaseRequest;
  function database() {
    if (!databaseRequest) {
      databaseRequest = new Promise((resolve, reject) => {
        // Several Pages projects share an origin. Give each repository its own database.
        const opened = indexedDB.open("review-workspace-v1:" + sample.project, 1);
        opened.onupgradeneeded = () => {
          opened.result.createObjectStore("heads", {keyPath: "workspace"});
          opened.result.createObjectStore("revisions", {keyPath: ["workspace", "revision"]});
          opened.result.createObjectStore("metadata", {keyPath: ["workspace", "revision"]});
        };
        opened.onsuccess = () => {
          const db = opened.result;
          db.onversionchange = () => { db.close(); databaseRequest = null; };
          resolve(db);
        };
        opened.onerror = () => reject(Error("Browser storage is unavailable. Enable storage for this site to save or reopen revisions."));
      }).catch(error => { databaseRequest = null; throw error; });
    }
    return databaseRequest;
  }

  function workspaceId(value) {
    if (typeof value !== "string" || !/^[0-9a-f]{32}$/.test(value)) throw Error("Enter a valid saved workspace ID.");
    return value;
  }

  function positiveRevision(value) {
    if (!Number.isSafeInteger(value) || value < 1) throw Error("Revision must be a positive integer.");
    return value;
  }

  function idbResult(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || Error("Browser storage could not read this revision."));
    });
  }

  async function save({source, choices, workspace, base = 0}) {
    if (!Number.isSafeInteger(base) || base < 0) throw Error("Base revision must be a nonnegative integer.");
    await python("validate", {source, choices});
    const isNew = workspace == null;
    const id = isNew ? Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,"0")).join("") : workspaceId(workspace);
    const db = await database();
    return new Promise((resolve, reject) => {
      // The head read and all three writes belong to one read/write transaction.
      const tx = db.transaction(["heads","revisions","metadata"], "readwrite");
      const heads = tx.objectStore("heads");
      let reason, metadata;
      const get = heads.get(id);
      get.onsuccess = () => {
        const head = get.result;
        if (!head && !isNew) reason = "Workspace unavailable in this browser.";
        else if ((head ? head.revision : 0) !== base || (isNew && head)) reason = "This workspace changed. Reopen the latest revision before saving.";
        if (reason) { tx.abort(); return; }
        metadata = {workspace: id, revision: base + 1, created: new Date().toISOString()};
        tx.objectStore("revisions").add({...metadata, source, choices});
        tx.objectStore("metadata").add(metadata);
        heads.put(metadata);
      };
      tx.oncomplete = () => { refreshPicker().catch(() => {}); resolve(metadata); };
      tx.onabort = () => reject(Error(reason || "The revision could not be saved. Check browser storage space and permissions."));
    });
  }

  async function history(value) {
    const id = workspaceId(value), db = await database();
    const range = IDBKeyRange.bound([id, 1], [id, Number.MAX_SAFE_INTEGER]);
    const rows = await idbResult(db.transaction("metadata").objectStore("metadata").getAll(range));
    if (!rows.length) throw Error("Workspace unavailable in this browser.");
    return rows.reverse().map(({revision, created}) => ({revision, created}));
  }

  async function read({workspace, revision}) {
    const id = workspaceId(workspace), db = await database();
    if (revision == null) {
      const head = await idbResult(db.transaction("heads").objectStore("heads").get(id));
      if (!head) throw Error("Workspace unavailable in this browser.");
      revision = head.revision;
    }
    const row = await idbResult(db.transaction("revisions").objectStore("revisions").get([id, positiveRevision(revision)]));
    if (!row) throw Error("Revision unavailable in this browser.");
    return row;
  }

  async function refreshPicker() {
    const db = await database();
    const rows = await idbResult(db.transaction("heads").objectStore("heads").getAll());
    byId("demo-workspaces").replaceChildren(...rows.sort((a,b) => b.created.localeCompare(a.created)).map(row => {
      const option = document.createElement("option");
      option.value = row.workspace;
      option.label = "Revision " + row.revision + " · " + row.created;
      return option;
    }));
  }

  function compareRows(left, right) {
    const a = Object.keys(left.choices).sort(), b = Object.keys(right.choices).sort();
    const first = new Set(a), second = new Set(b);
    return {from: left.revision, to: right.revision, source_changed: !sameJSON(left.source, right.source),
      approved: b.filter(id => !first.has(id)), removed: a.filter(id => !second.has(id)),
      notes_changed: a.filter(id => second.has(id) && left.choices[id] !== right.choices[id])};
  }

  window.demoCall = async (path, payload = {}) => {
    const meta = await loadSample();
    switch (path) {
      case "example": return meta;
      case "analyze":
        if (sameJSON(payload.source, meta.source)) return meta.report;
        return python(path, payload);
      case "artifacts":
      case "import": return python(path, payload);
      case "export": {
        let input = payload;
        if (payload.workspace) {
          const saved = await read(payload);
          input = {source: saved.source, choices: saved.choices, revision: saved.revision};
        }
        const bytes = await python(path, input);
        if (bytes instanceof Blob) return bytes;
        if (!(bytes instanceof ArrayBuffer || ArrayBuffer.isView(bytes))) throw Error("Python did not return a ZIP file.");
        return new Blob([bytes], {type:"application/zip"});
      }
      case "save": return save(payload);
      case "history": return history(payload.workspace);
      case "read": return read(payload);
      case "compare": {
        const [left, right] = await Promise.all([read({workspace:payload.workspace, revision:payload.before}),
          read({workspace:payload.workspace, revision:payload.after})]);
        return compareRows(left, right);
      }
      default: throw Error("Unknown browser operation.");
    }
  };

  window.demoPaint = (source, report, inspect) => {
    const example = sameJSON(source, sample.source);
    const review = example && sample.recorded;
    const area = byId("suggestions"), toggle = byId("recommend"), info = byId("model-state");
    area.replaceChildren(); area.hidden = false;
    toggle.hidden = !review;
    if (review) {
      info.textContent = "Precomputed on the bundled example with " + review.model + ". These are recorded suggestions.";
      const candidates = new Map(report.candidates.map(candidate => [candidate.id, candidate]));
      for (const row of review.recommendations) {
        const item = candidates.get(row.id);
        if (!item || !item.evidence_ids.includes(row.evidence_id)) continue;
        const node = document.createElement("article"), why = document.createElement("p"),
          evidence = document.createElement("small"), show = document.createElement("button");
        why.textContent = row.why; evidence.textContent = row.evidence_id;
        show.textContent = "Inspect suggestion"; show.type = "button"; show.onclick = () => inspect(item);
        node.append(why, evidence, document.createTextNode(" "), show); area.append(node);
      }
      toggle.textContent = "Hide recorded suggestions"; toggle.setAttribute("aria-expanded","true");
    } else {
      info.textContent = example ? "This sample has no verified recorded model review." :
        "Recorded suggestions belong to the bundled example. Use Find changes by meaning above for this source.";
    }
    byId("semantic-results").replaceChildren();
    byId("semantic-status").textContent = "";
    window.dispatchEvent(new Event("demoreviewchange"));
    if (!warmStarted) {
      warmStarted = true;
      // Render the verified sample before downloading or starting the interpreter.
      setTimeout(() => {
        python("analyze", {source: sample.source}).catch(() => {});
        refreshPicker().catch(() => {});
      }, 0);
    }
  };

  window.demoToggleSuggestions = () => {
    const area = byId("suggestions"), toggle = byId("recommend");
    area.hidden = !area.hidden;
    toggle.textContent = area.hidden ? "Show recorded suggestions" : "Hide recorded suggestions";
    toggle.setAttribute("aria-expanded", String(!area.hidden));
  };
})();
