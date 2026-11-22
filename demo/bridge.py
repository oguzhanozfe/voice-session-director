"""Small JSON boundary around the repository's original Python studio."""

import json

import pipeline
import studio


def _run(action, payload):
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object.")
    if action == "import":
        filename = payload.get("filename")
        content = payload.get("text")
        if not isinstance(filename, str) or not isinstance(content, str):
            raise ValueError("Supply a file name and text.")
        if filename.lower().endswith(".json"):
            source = json.loads(content.lstrip("\ufeff"))
        elif hasattr(pipeline, "import_text"):
            source = pipeline.import_text(filename, content)
        else:
            raise ValueError("This project imports a JSON source file.")
        return {"source": source, "report": studio.analyze(source)}

    source = payload.get("source")
    choices = payload.get("choices", {})
    if action == "analyze":
        return studio.analyze(source)
    if action == "export":
        revision = payload.get("revision")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("A saved revision must be a positive integer.")
        return studio.release(source, choices, revision)
    if action in ("artifacts", "validate"):
        files = studio.artifacts(source, studio.analyze(source), choices)
        if action == "validate":
            return True
        return {
            name: {"text": value[:6000], "characters": len(value)}
            for name, value in files.items()
        }
    raise ValueError("Unknown workspace operation.")


def dispatch(action, raw_payload):
    """Return a JSON envelope or raw ZIP bytes; input is data, never Python code."""
    try:
        if not isinstance(raw_payload, str) or len(raw_payload.encode("utf-8")) > 1_200_000:
            raise ValueError("The request is empty or exceeds the 1.2 MB limit.")
        result = _run(action, json.loads(raw_payload))
        if isinstance(result, bytes):
            return result
        return json.dumps({"result": result}, ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as error:
        return json.dumps({"error": str(error) or "Invalid input."}, ensure_ascii=True)
