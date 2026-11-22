"""Allocate dialogue and pickup lines to fixed single-booth recording windows."""

import csv
import io
import math

TITLE = "Voice Session Director"
DESCRIPTION = "Batch dialogue and pickups into performer-specific recording windows and export an approved booth schedule."
PROMPT = "Explain unscheduled lines, pickup priorities and scene changes using the recorded window evidence. Durations are estimates, not actor performance measurements."


def rows(data, key, limit=250, empty=False):
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, list) or len(value) > limit or (not value and not empty):
        raise ValueError(
            f"{key} must be a list with {'0' if empty else '1'} to {limit} entries"
        )
    if any(not isinstance(entry, dict) for entry in value):
        raise ValueError(f"Every {key} entry must be an object")
    return value


def text(value, name, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonblank text, at most {limit} characters")
    return value.strip()


def integer(value, name, lo=0, hi=1_000_000):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer between {lo} and {hi}")
    return value


def selected(evidence, approved):
    by_id = {c["id"]: c for c in evidence["candidates"]}
    result = []
    seen = set()
    for item in approved:
        key = item.get("id") if isinstance(item, dict) else None
        if not isinstance(key, str) or key not in by_id or key in seen:
            raise ValueError("Unknown or duplicate approval")
        seen.add(key)
        result.append(by_id[key])
    return result


def prepare(data: dict) -> dict:
    windows = []
    records = []
    names = set()
    for w in rows(data, "windows", 100):
        name = text(w.get("id"), "window id")
        actor = text(w.get("performer"), "performer")
        a = integer(w.get("start_minute"), "start_minute", 0, 1439) * 60
        b = integer(w.get("end_minute"), "end_minute", 1, 1440) * 60
        if b <= a or name in names:
            raise ValueError("Windows need a unique ID and positive length")
        names.add(name)
        windows.append((a, b, name, actor))
        records.append(
            {"id": "window:" + name, "performer": actor, "start_s": a, "end_s": b}
        )
    windows.sort()
    if any(y[0] < x[1] for x, y in zip(windows, windows[1:])):
        raise ValueError("Single-booth session windows cannot overlap")
    wpm = integer(data.get("words_per_minute", 135), "words_per_minute", 40, 350)
    setup = integer(data.get("scene_setup_seconds", 15), "scene_setup_seconds", 0, 600)
    reset = integer(data.get("take_reset_seconds", 4), "take_reset_seconds", 0, 60)
    backlog = []
    line_ids = set()
    for i, line in enumerate(rows(data, "lines", 500)):
        key = text(line.get("id"), "line id")
        scene = text(line.get("scene"), "scene")
        actor = text(line.get("performer"), "performer")
        script = text(line.get("text"), "line text", 4000)
        pickup = line.get("pickup", False)
        takes = integer(line.get("takes", 2), "takes", 1, 20)
        if key in line_ids or type(pickup) is not bool:
            raise ValueError("Line IDs must be unique and pickup must be boolean")
        line_ids.add(key)
        length = math.ceil(len(script.split()) * 60 / wpm) * takes + reset * (takes - 1)
        row = {
            "id": "line:" + key,
            "line": key,
            "performer": actor,
            "scene": scene,
            "text": script,
            "pickup": pickup,
            "takes": takes,
            "record_s": length,
            "status": "No matching window with sufficient time",
        }
        backlog.append((i, row))
        records.append(row)
    candidates = []
    for start, end, wid, actor in windows:
        cursor = start
        current_scene = None
        while cursor < end:
            fits = []
            for seq, row in backlog:
                gap = setup if row["scene"] != current_scene else 0
                if row["performer"] == actor and cursor + gap + row["record_s"] <= end:
                    fits.append((not row["pickup"], gap, seq, row))
            if not fits:
                break
            _, gap, seq, row = min(fits, key=lambda x: x[:3])
            begin = cursor + gap
            cursor = begin + row["record_s"]
            current_scene = row["scene"]
            row["status"] = "Scheduled"
            backlog.remove((seq, row))
            candidates.append(
                {
                    "id": "record:" + row["line"],
                    "action": "Record " + row["line"] + " with " + actor,
                    "evidence_ids": [row["id"], "window:" + wid],
                    "performer": actor,
                    "scene": current_scene,
                    "line": row["line"],
                    "start_s": begin,
                    "end_s": cursor,
                    "setup_s": gap,
                    "takes": row["takes"],
                    "text": row["text"],
                }
            )
    return {
        "summary": f"Placed {len(candidates)} lines in {len(windows)} booth windows. Unplaced lines: {len(backlog)}.",
        "metrics": {
            "Scheduled": len(candidates),
            "Unplaced": len(backlog),
            "Windows": len(windows),
        },
        "records": records,
        "candidates": candidates,
    }


def export(data, evidence, approved):
    file = io.StringIO(newline="")
    writer = csv.writer(file)
    writer.writerow(
        [
            "Start",
            "End",
            "Setup seconds",
            "Performer",
            "Scene",
            "Line ID",
            "Takes",
            "Line",
        ]
    )

    def clock(s):
        return f"{s // 3600:02}:{(s // 60) % 60:02}:{s % 60:02}"

    def cell(s):
        return (
            "'" + s
            if isinstance(s, str) and s.lstrip().startswith(("=", "+", "-", "@"))
            else s
        )

    for item in sorted(selected(evidence, approved), key=lambda c: c["start_s"]):
        writer.writerow(
            [
                cell(v)
                for v in [
                    clock(item["start_s"]),
                    clock(item["end_s"]),
                    item["setup_s"],
                    item["performer"],
                    item["scene"],
                    item["line"],
                    item["takes"],
                    item["text"],
                ]
            ]
        )
    return {"booth-schedule.csv": file.getvalue()}
