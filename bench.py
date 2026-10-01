#!/usr/bin/env python3
"""Benchmark A and B from README section 5: timing and peak RSS.

Benchmark A: 2048x2048 all-ones grid (single region).
Benchmark B: 2048x2048 grid, even columns all 1, odd columns all 0
             (1024 one-pixel-wide vertical stripes).

Budgets: <= 5.0 s wall time and <= 256 MiB peak RSS per run.

Usage: python3 bench.py
Exit code 0 iff both benchmarks stay within budget.
"""

import pathlib
import resource
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
OUT_DIR = ROOT / "var"
SIZE = 2048
TIME_BUDGET_S = 5.0
RSS_BUDGET_KIB = 256 * 1024


def generate(path, row):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("%d %d\n" % (SIZE, SIZE))
        for _ in range(SIZE):
            fh.write(row)
            fh.write("\n")


def run_bench(name, grid_path, out_path):
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "regionmark.py"), str(grid_path), str(out_path)],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    # ru_maxrss (KiB on Linux) of the largest child reaped so far; each
    # benchmark runs in its own helper process, so read it per run below.
    rss_kib = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    ok = proc.returncode == 0 and elapsed <= TIME_BUDGET_S and rss_kib <= RSS_BUDGET_KIB
    status = "PASS" if ok else "FAIL"
    print(
        "%s bench %s: %.2fs (budget %.1fs), peak RSS %.0f MiB (budget 256 MiB), exit %d"
        % (status, name, elapsed, TIME_BUDGET_S, rss_kib / 1024, proc.returncode)
    )
    if proc.returncode != 0:
        print("  stderr: %s" % proc.stderr.strip())
    return ok


def main():
    OUT_DIR.mkdir(exist_ok=True)
    grid_a = OUT_DIR / "bench_a.txt"
    grid_b = OUT_DIR / "bench_b.txt"
    generate(grid_a, "1" * SIZE)
    generate(grid_b, "10" * (SIZE // 2))
    ok_a = run_bench("A (all ones)", grid_a, OUT_DIR / "bench_a.html")
    ok_b = run_bench("B (stripes)", grid_b, OUT_DIR / "bench_b.html")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    sys.exit(main())
