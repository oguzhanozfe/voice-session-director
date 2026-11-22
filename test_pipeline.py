import json
from pathlib import Path
import unittest

from pipeline import prepare, export


def fixture():
    return json.loads(
        Path(__file__).with_name("example.json").read_text(encoding="utf-8")
    )


class PipelineTests(unittest.TestCase):
    def test_pickup_first_and_scene_setup(self):
        r = prepare(fixture())
        cs = r["candidates"]
        self.assertEqual(cs[0]["line"], "IR-103P")
        self.assertEqual(cs[1]["setup_s"], 0)
        self.assertEqual(r["metrics"]["Unplaced"], 1)
        self.assertTrue(all(a["end_s"] <= b["start_s"] for a, b in zip(cs, cs[1:])))

    def test_long_take_does_not_starve_shorter_line(self):
        d = fixture()
        d["lines"][1]["text"] = "a " * 900
        self.assertIn("IR-101", [c["line"] for c in prepare(d)["candidates"]])

    def test_filtered_csv_preserves_reserved_start(self):
        import csv, io

        d = fixture()
        r = prepare(d)
        pick = r["candidates"][1]
        lines = list(
            csv.DictReader(io.StringIO(export(d, r, [pick])["booth-schedule.csv"]))
        )
        self.assertEqual([v["Line ID"] for v in lines], [pick["line"]])
        self.assertNotEqual(lines[0]["Start"], "09:00:00")

    def test_double_booked_booth(self):
        d = fixture()
        d["windows"][1]["start_minute"] = 541
        with self.assertRaises(ValueError):
            prepare(d)


if __name__ == "__main__":
    unittest.main()
