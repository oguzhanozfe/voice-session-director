# Browser demo

The public demo runs the project's Python engine in a WebAssembly worker. Open **Source data** to change or import an input. Select an action, inspect the linked records, and download a ZIP containing your approved files, source and manifest. **Saved revisions** stores work in this browser's IndexedDB. Copy a release ZIP if you need to retain your work outside this browser.

**Find changes by meaning** runs the quantized English MiniLM sentence encoder on your device. Enter a focus in your own words, then inspect the action and evidence behind each match. The first search downloads about 46 MB of model and runtime files. The panel reports cosine similarity for up to 16 candidate actions. **Recorded model review** shows the cited Gemma recommendations previously generated for the bundled input. For new generative reviews through a local chat model, Azure OpenAI, Bedrock or an API, use the full server in the repository.

The browser downloads all application, runtime and model files from the demo site. Review text and uploaded data are processed on your device.

## Build and run

From the repository root:

```sh
python demo/build_demo.py --out public
python demo/fetch_runtime.py public/python
python -m http.server 8000 --directory public --bind 127.0.0.1
```

Open <http://127.0.0.1:8000>. The first build requires internet access. Runtime binaries and model weights are checked against [the asset lockfile](assets.lock.json). Pushes to `main` rebuild the Pages demo. To enable this workflow on a fork, set its Pages publishing source to GitHub Actions.

## Browser components

[Pyodide](https://github.com/pyodide/pyodide) supplies the Python runtime. Semantic search uses [Transformers.js](https://github.com/huggingface/transformers.js), [ONNX Runtime](https://onnxruntime.ai/) and the [quantized MiniLM model](https://huggingface.co/Xenova/all-MiniLM-L6-v2), derived from [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). Downloaded software and weights retain their upstream licenses. The static build ships license files and the model card alongside the runtime under `licenses/`.
