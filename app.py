"""Web and command-line entry points for the review workspace."""

import argparse
from http import HTTPStatus
import hmac
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn

import pipeline
import providers
import studio

ROOT = Path(__file__).resolve().parent
STATIC = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/ui.js": ("web/ui.js", "text/javascript; charset=utf-8"),
    "/style.css": ("web/style.css", "text/css; charset=utf-8"),
}


class AccessError(ValueError):
    pass


def example():
    return json.loads((ROOT / "example.json").read_text("utf-8"))


def authorized(env):
    key = os.environ.get("WORKSPACE_KEY", "")
    if key:
        return hmac.compare_digest(
            env.get("HTTP_X_WORKSPACE_KEY", "").encode(), key.encode()
        )
    host = urlsplit("//" + env.get("HTTP_HOST", "")).hostname
    return os.environ.get("PUBLIC_BIND") != "1" and host in (
        "localhost",
        "127.0.0.1",
        "::1",
    )


def application(env, respond):
    path, method = env["PATH_INFO"], env["REQUEST_METHOD"]
    status, mime, headers = 200, "application/json; charset=utf-8", []
    try:
        if method == "GET" and path in STATIC:
            name, mime = STATIC[path]
            body = (ROOT / name).read_bytes()
        elif method == "GET" and path == "/health":
            body = {"ok": True}
        elif method == "GET" and path == "/api/example":
            body = {
                "title": pipeline.TITLE,
                "description": pipeline.DESCRIPTION,
                "source": example(),
                "native_import": hasattr(pipeline, "import_text"),
                "provider": providers.active_provider(),
                "key_required": not authorized(env),
            }
        elif method == "POST" and path in (
            "/api/analyze",
            "/api/import",
            "/api/export",
            "/api/artifacts",
            "/api/save",
            "/api/read",
            "/api/history",
            "/api/compare",
            "/api/recommend",
        ):
            origin = env.get("HTTP_ORIGIN")
            if origin and urlsplit(origin).netloc != env.get("HTTP_HOST"):
                raise AccessError("Use the same origin as the workspace.")
            if env.get("CONTENT_TYPE", "").split(";")[0].strip() != "application/json":
                raise ValueError("Send application/json.")
            size = int(env.get("CONTENT_LENGTH") or 0)
            if not 0 < size <= 1_200_000:
                raise ValueError("The request is empty or exceeds the 1.2 MB limit.")
            if path in (
                "/api/save",
                "/api/read",
                "/api/history",
                "/api/compare",
                "/api/recommend",
            ) and not authorized(env):
                raise AccessError(
                    "Enter the deployment's workspace key to save, reopen or request model advice."
                )
            data = json.loads(env["wsgi.input"].read(size))
            if not isinstance(data, dict):
                raise ValueError("Submit a JSON object.")
            source, choices = data.get("source"), data.get("choices", {})
            workspace = data.get("workspace")
            if path == "/api/analyze":
                body = studio.analyze(source)
            elif path == "/api/import":
                if not hasattr(pipeline, "import_text"):
                    raise ValueError("This project imports a JSON source file.")
                name, value = data.get("filename"), data.get("text")
                if not isinstance(name, str) or not isinstance(value, str):
                    raise ValueError("Supply a file name and text.")
                source = pipeline.import_text(name, value)
                body = {"source": source, "report": studio.analyze(source)}
            elif path == "/api/artifacts":
                files = studio.artifacts(source, studio.analyze(source), choices)
                body = {
                    name: {"text": value[:6000], "characters": len(value)}
                    for name, value in files.items()
                }
            elif path == "/api/export":
                if workspace:
                    if not authorized(env):
                        raise AccessError(
                            "Enter the workspace key to export a saved revision."
                        )
                    saved = studio.read(workspace, data.get("revision"))
                    body = studio.release(
                        saved["source"], saved["choices"], saved["revision"]
                    )
                else:
                    body = studio.release(source, choices)
                mime = "application/zip"
                headers.append(
                    (
                        "Content-Disposition",
                        'attachment; filename="reviewed-release.zip"',
                    )
                )
            elif path == "/api/save":
                body = studio.save(source, choices, workspace, data.get("base", 0))
            elif path == "/api/read":
                body = studio.read(workspace, data.get("revision"))
            elif path == "/api/history":
                body = studio.history(workspace)
            elif path == "/api/compare":
                body = studio.compare(
                    studio.read(workspace, data.get("before")),
                    studio.read(workspace, data.get("after")),
                )
            else:
                body = studio.recommend(studio.analyze(source), data.get("focus", ""))
        else:
            status, body = 404, {"error": "Unknown endpoint."}
    except AccessError as error:
        status, body = 403, {"error": str(error)}
    except studio.Conflict as error:
        status, body = 409, {"error": str(error)}
    except KeyError as error:
        status, body = 404, {"error": str(error.args[0])}
    except providers.ModelError as error:
        status, body = 422, {"error": str(error)}
    except (
        ValueError,
        TypeError,
        UnicodeError,
        RecursionError,
        OverflowError,
    ) as error:
        status, body = 400, {"error": str(error) or "Invalid input."}
    if not isinstance(body, bytes):
        body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
    headers.extend(
        [
            ("Content-Type", mime),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            (
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            ),
        ]
    )
    respond(f"{status} {HTTPStatus(status).phrase}", headers)
    return [body]


class LocalServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=pipeline.DESCRIPTION)
    sub = parser.add_subparsers(dest="command")
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    for name in ("analyze", "recommend", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("source", nargs="?", default=str(ROOT / "example.json"))
        if name == "recommend":
            cmd.add_argument(
                "--focus",
                default="",
                help="What the model should prioritize during review.",
            )
        if name == "export":
            cmd.add_argument("--approve", action="append", default=[], metavar="ID")
            cmd.add_argument("--out", default="release.zip")
    args = parser.parse_args()
    if args.command in (None, "serve"):
        port = getattr(args, "port", int(os.environ.get("PORT", "8000")))
        with make_server(
            "127.0.0.1", port, application, server_class=LocalServer
        ) as http:
            print(f"Open http://127.0.0.1:{http.server_port}", flush=True)
            http.serve_forever()
        return
    source_path = Path(args.source)
    content = source_path.read_text("utf-8-sig")
    if source_path.suffix.lower() == ".json" or not hasattr(pipeline, "import_text"):
        source = json.loads(content)
    else:
        source = pipeline.import_text(source_path.name, content)
    if args.command == "export":
        Path(args.out).write_bytes(
            studio.release(source, dict.fromkeys(args.approve, ""))
        )
        print(args.out)
    else:
        report = studio.analyze(source)
        result = (
            studio.recommend(report, args.focus)
            if args.command == "recommend"
            else report
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, providers.ModelError) as error:
        sys.exit(str(error))
