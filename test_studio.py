"""Offline integration tests of revisions, evidence, release integrity and web access."""

import hashlib
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import zipfile

import app
import providers
import studio


def call(path, data=None, key=None, **environment):
    body = b"" if data is None else json.dumps(data).encode()
    env = {
        "PATH_INFO": path,
        "REQUEST_METHOD": "GET" if data is None else "POST",
        "HTTP_HOST": "localhost:8000",
        "REMOTE_ADDR": "127.0.0.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        **environment,
    }
    if key:
        env["HTTP_X_WORKSPACE_KEY"] = key
    response = {}

    def start(status, headers):
        response["code"] = int(status.split()[0])
        response["headers"] = dict(headers)

    payload = b"".join(app.application(env, start))
    assert len(payload) == int(response["headers"]["Content-Length"])
    return response["code"], (
        json.loads(payload)
        if response["headers"]["Content-Type"].startswith("application/json")
        else payload
    )


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.scope = patch.dict(
            os.environ,
            {
                "WORKSPACE_DB": str(Path(tmp.name) / "workspace.sqlite3"),
                "MODEL_PROVIDER": "off",
            },
            clear=True,
        )
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.source = app.example()

    def test_independent_workspaces_and_immutable_revisions(self):
        first = studio.save(self.source, {})
        other = studio.save(self.source, {})
        self.assertNotEqual(first["workspace"], other["workspace"])
        second = studio.save(self.source, {}, first["workspace"], base=1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(studio.read(first["workspace"], 1)["revision"], 1)
        self.assertEqual(studio.read(first["workspace"])["revision"], 2)
        self.assertEqual(studio.read(other["workspace"])["revision"], 1)
        self.assertEqual(
            [r["revision"] for r in studio.history(first["workspace"])], [2, 1]
        )
        self.assertRaises(KeyError, studio.read, other["workspace"], 2)

    def test_one_winner_for_simultaneous_same_base(self):
        ws = studio.save(self.source, {})["workspace"]

        def submit(_):
            try:
                return studio.save(self.source, {}, ws, 1)["revision"]
            except studio.Conflict:
                return "conflict"

        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(pool.map(submit, range(2)), [2, "conflict"])
        self.assertEqual(len(studio.history(ws)), 2)

    def test_compare_and_review_note_validation(self):
        left = {
            "revision": 1,
            "source": {"amount": 5},
            "choices": {"x": "yes", "old": ""},
        }
        right = {
            "revision": 2,
            "source": {"amount": 6},
            "choices": {"x": "checked", "new": ""},
        }
        diff = studio.compare(left, right)
        self.assertEqual(
            (diff["approved"], diff["removed"], diff["notes_changed"]),
            (["new"], ["old"], ["x"]),
        )
        self.assertTrue(diff["source_changed"])
        with self.assertRaises(ValueError):
            studio.decisions({"candidates": [{"id": "a"}]}, {"missing": "no"})
        with self.assertRaises(ValueError):
            studio.decisions({"candidates": [{"id": "a"}]}, {"a": "x" * 1201})

    def test_archive_keeps_source_and_matches_native_file_hashes(self):
        release = studio.release(self.source, {}, 7)
        with zipfile.ZipFile(io.BytesIO(release)) as bundle:
            self.assertIsNone(bundle.testzip())
            manifest = json.loads(bundle.read("_studio/manifest.json"))
            original = bundle.read("_studio/source.json")
            self.assertEqual(json.loads(original), self.source)
            self.assertEqual(
                manifest["source_sha256"], hashlib.sha256(original).hexdigest()
            )
            self.assertEqual(manifest["revision"], 7)
            self.assertTrue(manifest["sha256"])
            for name, digest in manifest["sha256"].items():
                self.assertEqual(digest, hashlib.sha256(bundle.read(name)).hexdigest())

    def test_model_citations_must_belong_to_the_recommended_candidate(self):
        report = {
            "records": [{"id": "r1", "value": 1}, {"id": "r2", "value": 2}],
            "candidates": [
                {"id": "c1", "action": "Move", "evidence_ids": ["r1"]},
                {"id": "c2", "action": "Keep", "evidence_ids": ["r2"]},
            ],
        }
        invalid = {"id": "c1", "evidence_id": "r2", "why": "Wrong source"}
        valid = {"id": "c2", "evidence_id": "r2", "why": "Current count is two."}
        serialize = lambda rows: json.dumps({"recommendations": rows})
        with patch.object(
            providers,
            "complete",
            side_effect=[serialize([invalid]), serialize([invalid, valid, valid])],
        ) as model:
            recommendation = studio.recommend(report)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(recommendation["recommendations"], [valid])
        self.assertNotIn("choices", recommendation)
        with patch.object(providers, "complete", return_value=serialize([invalid])):
            self.assertRaises(providers.ModelError, studio.recommend, report)

    def test_review_focus_is_optional_bounded_data(self):
        report = studio.analyze(self.source)
        candidate = report["candidates"][0]
        row = {
            "id": candidate["id"],
            "evidence_id": candidate["evidence_ids"][0],
            "why": "Inspect this source.",
        }
        with patch.object(
            providers, "complete", return_value=json.dumps({"recommendations": [row]})
        ) as model:
            result = studio.recommend(report, "Review the first change carefully.")
        context = json.loads(model.call_args.args[0][1]["content"])
        self.assertEqual(context["review_focus"], "Review the first change carefully.")
        self.assertEqual(result["recommendations"], [row])
        with self.assertRaises(ValueError):
            studio.recommend(report, "x" * 601)

    def test_bundled_approval_reproduces_all_native_files(self):
        root = Path(__file__).resolve().parent / "docs"
        case = json.loads((root / "example-review.json").read_text("utf-8"))
        artifacts = studio.artifacts(
            self.source, studio.analyze(self.source), case["choices"]
        )
        self.assertEqual(set(artifacts), set(case["artifacts"]))
        for name, body in artifacts.items():
            self.assertEqual(
                (root / "example-release" / name).read_bytes(), body.encode()
            )
            self.assertEqual(
                case["artifacts"][name]["sha256"],
                hashlib.sha256(body.encode()).hexdigest(),
            )

    def test_hosted_public_preview_and_private_revision_boundary(self):
        with patch.dict(
            os.environ, {"PUBLIC_BIND": "1", "WORKSPACE_KEY": "test-secret"}
        ):
            self.assertEqual(call("/health"), (200, {"ok": True}))
            status, example = call("/api/example")
            self.assertEqual(status, 200)
            self.assertTrue(example["key_required"])
            self.assertNotIn("test-secret", str(example))
            self.assertEqual(call("/api/analyze", {"source": self.source})[0], 200)
            self.assertEqual(call("/api/export", {"source": self.source})[0], 200)
            ws = call("/api/save", {"source": self.source}, "test-secret")[1][
                "workspace"
            ]
            for path in ("save", "history", "read", "compare", "recommend", "export"):
                with self.subTest(path=path):
                    self.assertEqual(
                        call(
                            "/api/" + path,
                            {"workspace": ws, "source": self.source},
                            key="wrong",
                        )[0],
                        403,
                    )
            self.assertEqual(
                call("/api/read", {"workspace": ws}, key="test-secret")[1]["source"],
                self.source,
            )
            self.assertEqual(
                call(
                    "/api/save",
                    {"source": self.source, "workspace": ws, "base": 0},
                    key="test-secret",
                )[0],
                409,
            )
            self.assertEqual(
                call(
                    "/api/read",
                    {"workspace": ws},
                    key="test-secret",
                    HTTP_ORIGIN="https://other.test",
                )[0],
                403,
            )

    def test_request_validation_and_loopback_fallback(self):
        self.assertEqual(
            call("/api/analyze", [], CONTENT_TYPE="application/json")[0], 400
        )
        self.assertEqual(call("/api/analyze", {}, CONTENT_TYPE="text/plain")[0], 400)
        self.assertEqual(call("/api/analyze", {}, CONTENT_LENGTH="1200001")[0], 400)
        self.assertEqual(
            call("/api/save", {"source": self.source}, HTTP_HOST="example.test")[0], 403
        )
        with patch.dict(os.environ, {"PUBLIC_BIND": "1"}):
            self.assertEqual(call("/api/save", {"source": self.source})[0], 403)
        self.assertEqual(call("/api/save", {"source": self.source})[0], 200)
        self.assertEqual(call("/missing")[0], 404)
