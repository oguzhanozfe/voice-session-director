"""Fetch the pinned browser runtime and model. No application data leaves the browser."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.request import urlopen


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(item, site, cache):
    name, spec = item
    target = site / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and digest(target) == spec["sha256"]:
        return
    if cache:
        existing = cache / spec["sha256"]
        if existing.is_file() and digest(existing) == spec["sha256"]:
            shutil.copyfile(existing, target)
            return
    for attempt in range(3):
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
                pending = Path(tmp.name)
                with urlopen(spec["url"], timeout=90) as response:
                    shutil.copyfileobj(response, tmp)
            if pending.stat().st_size != spec["bytes"] or digest(pending) != spec["sha256"]:
                raise ValueError(f"Checksum mismatch for {name}")
            os.replace(pending, target)
            return
        except (OSError, ValueError) as error:
            if "pending" in locals():
                pending.unlink(missing_ok=True)
            if attempt == 2:
                raise RuntimeError(f"Could not fetch verified asset {name}: {error}") from error
            time.sleep(1 + attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python_dir", type=Path, help="The python directory inside the static site output")
    parser.add_argument("--cache", type=Path, help="Optional local directory of SHA-256-addressed files")
    args = parser.parse_args()
    if args.python_dir.name != "python":
        parser.error("Use an output path ending in /python, for example public/python.")
    manifest = json.loads(Path(__file__).with_name("assets.lock.json").read_text("utf-8"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: fetch(item, args.python_dir.parent, args.cache), manifest.items()))


if __name__ == "__main__":
    main()
