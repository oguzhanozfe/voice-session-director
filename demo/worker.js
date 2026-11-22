/* Classic dedicated worker. Python and the project modules are served locally. */
"use strict";

const engineURL = new URL("./python/", self.location.href);
const files = ["bridge.py", "pipeline.py", "studio.py", "providers.py"];
const operations = new Set(["analyze", "artifacts", "export", "import", "validate"]);
let boot;

async function initialize() {
  if (typeof self.loadPyodide !== "function") {
    importScripts(new URL("pyodide.js", engineURL).href);
  }
  const py = await self.loadPyodide({
    indexURL: engineURL.href,
    fullStdLib: false,
  });
  if (py.version !== "0.29.4") {
    throw new Error("The bundled Python runtime does not match version 0.29.4.");
  }
  // studio imports sqlite3 even though browser persistence is handled by the page.
  await py.loadPackage("sqlite3");
  const modules = await Promise.all(files.map(async (file) => {
    const url = new URL(file, self.location.href);
    const response = await fetch(url, {credentials: "same-origin"});
    if (!response.ok) throw new Error("Cannot load " + file + " (HTTP " + response.status + ").");
    return [file, await response.text()];
  }));
  for (const [file, source] of modules) {
    py.FS.writeFile("/home/pyodide/" + file, source, {encoding: "utf8"});
  }
  const bridge = py.pyimport("bridge");
  // Keep the interpreter alive alongside its long-lived bridge proxy.
  return {py, bridge};
}

function runtime() {
  if (!boot) {
    boot = initialize().catch((error) => {
      boot = undefined;
      throw error;
    });
  }
  return boot;
}

self.onmessage = async (event) => {
  const message = event.data;
  const id = message && message.id;
  try {
    const action = typeof message?.path === "string"
      ? message.path.replace(/^\/(?:api\/)?/, "")
      : "";
    if (!operations.has(action)) throw new Error("Unknown workspace operation.");
    const payload = JSON.stringify(message.payload);
    if (typeof payload !== "string" || payload.length > 1200000) {
      throw new Error("The request is empty or exceeds the 1.2 MB limit.");
    }
    const {bridge} = await runtime();
    // dispatch is synchronous. No request can change another request's input
    // while Python runs, including when several await the same initialization.
    const reply = bridge.dispatch(action, payload);
    if (typeof reply === "string") {
      const envelope = JSON.parse(reply);
      if ("error" in envelope) throw new Error(envelope.error);
      self.postMessage({id, result: envelope.result});
      return;
    }
    try {
      if (action !== "export") throw new Error("Unexpected binary response.");
      const view = typeof reply.toJs === "function" ? reply.toJs() : reply;
      if (!(view instanceof Uint8Array)) throw new Error("Invalid ZIP response.");
      // Copy only this view's exact range. Never transfer the WebAssembly heap.
      const zip = new Uint8Array(view);
      self.postMessage({id, result: zip}, [zip.buffer]);
    } finally {
      if (typeof reply?.destroy === "function") reply.destroy();
    }
  } catch (error) {
    self.postMessage({id, error: error instanceof Error ? error.message : String(error)});
  }
};
