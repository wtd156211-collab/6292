#!/usr/bin/env python3
"""Acceptance check, README section 5 steps 1-4.

Runs regionmark.py on every grid in samples/grids/, then compares the
label-map and stats <pre> blocks in the generated HTML against
samples/expected/, and verifies the HTML references no external resources.

Usage: python3 check_samples.py
Exit code 0 iff every sample passes.
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
GRIDS = ROOT / "samples" / "grids"
EXPECTED = ROOT / "samples" / "expected"
OUT_DIR = ROOT / "var"

EXTERNAL_REF = re.compile(r'src=|href=|url\(|@import|fetch\(|https?://', re.I)


def extract_block(html, block_id):
    match = re.search(r'<pre id="%s">\n?(.*?)\n?</pre>' % block_id, html, re.S)
    if match is None:
        return None
    return "\n".join(
        line.strip() for line in match.group(1).strip().splitlines()
    )


def normalize(text):
    return "\n".join(line.strip() for line in text.strip().splitlines())


def check_sample(grid_path):
    name = grid_path.stem
    out_path = OUT_DIR / (name + ".html")
    errors = []

    proc = subprocess.run(
        [sys.executable, str(ROOT / "regionmark.py"), str(grid_path), str(out_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ["exit code %d (stderr: %s)" % (proc.returncode, proc.stderr.strip())]

    html = out_path.read_text(encoding="utf-8")

    for block_id, kind in (("label-map", "labels"), ("stats", "stats")):
        got = extract_block(html, block_id)
        if got is None:
            errors.append("missing <pre id=%s> block" % block_id)
            continue
        expected_path = EXPECTED / ("%s.%s.txt" % (name, kind))
        want = normalize(expected_path.read_text(encoding="utf-8"))
        if got != want:
            got_lines, want_lines = got.splitlines(), want.splitlines()
            detail = "length %d vs %d" % (len(got_lines), len(want_lines))
            for i, (a, b) in enumerate(zip(got_lines, want_lines)):
                if a != b:
                    detail = "line %d: got %r, want %r" % (i, a, b)
                    break
            errors.append("%s mismatch (%s)" % (kind, detail))

    if EXTERNAL_REF.search(html):
        errors.append("HTML references external resources")

    return errors


def main():
    grid_paths = sorted(GRIDS.glob("*.txt"))
    if not grid_paths:
        print("no grids found under %s" % GRIDS)
        return 1
    OUT_DIR.mkdir(exist_ok=True)
    failed = 0
    for grid_path in grid_paths:
        errors = check_sample(grid_path)
        if errors:
            failed += 1
            print("FAIL %s" % grid_path.stem)
            for err in errors:
                print("     - %s" % err)
        else:
            print("OK   %s" % grid_path.stem)
    print("%d/%d samples passed" % (len(grid_paths) - failed, len(grid_paths)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
