#!/usr/bin/env python3
"""自动比对：对 samples/grids 下每个网格运行 regionmark.py，
抽取 HTML 中 <pre id="label-map"> 与 <pre id="stats"> 的文本，
与 samples/expected 下对应文件逐行核对（README 第 5 节第 1-4 步）。

用法: python3 tools/check_samples.py
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "samples" / "grids"
EXPECTED = ROOT / "samples" / "expected"
OUT = ROOT / "var"

EXTERNAL_RE = re.compile(
    r"src\s*=|href\s*=|@import|url\(|fetch\(|XMLHttpRequest|"
    r"https?://|//cdn\.|<link\b",
    re.IGNORECASE,
)


def extract_block(html, block_id):
    match = re.search(
        r'<pre id="' + block_id + r'">(.*?)</pre>', html, re.DOTALL
    )
    if not match:
        raise AssertionError(f"missing <pre id={block_id}>")
    text = match.group(1).strip("\n")
    return "\n".join(line.strip() for line in text.splitlines())


def normalize(path):
    text = path.read_text(encoding="utf-8").strip("\n")
    return "\n".join(line.strip() for line in text.splitlines())


def main():
    OUT.mkdir(exist_ok=True)
    failures = 0
    for grid in sorted(GRIDS.glob("*.txt")):
        name = grid.stem
        html_path = OUT / f"{name}.html"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "regionmark.py"), str(grid), str(html_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"FAIL {name}: exit code {proc.returncode}: {proc.stderr.strip()}")
            failures += 1
            continue
        html = html_path.read_text(encoding="utf-8")
        try:
            labels = extract_block(html, "label-map")
            stats = extract_block(html, "stats")
            assert labels == normalize(EXPECTED / f"{name}.labels.txt"), "label-map mismatch"
            assert stats == normalize(EXPECTED / f"{name}.stats.txt"), "stats mismatch"
            assert not EXTERNAL_RE.search(html), "external resource reference found"
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failures += 1
        else:
            print(f"OK   {name}")
    if failures:
        print(f"{failures} sample(s) failed")
        return 1
    print("all samples match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
