#!/usr/bin/env python3
"""生成基准 A（全 1）与基准 B（偶数列 1、奇数列 0）的 2048x2048 网格，
以子进程运行 regionmark.py，报告耗时与峰值 RSS（README 第 5 节预算：
单次 <= 5 秒，峰值 RSS <= 256 MiB）。

用法: python3 tools/bench.py
"""

import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAR = ROOT / "var"
SIZE = 2048
TIME_BUDGET = 5.0
RSS_BUDGET_MIB = 256


def make_grids():
    VAR.mkdir(exist_ok=True)
    a = VAR / "bench_a.txt"
    b = VAR / "bench_b.txt"
    if not a.exists():
        row = "1" * SIZE
        a.write_text(f"{SIZE} {SIZE}\n" + "\n".join([row] * SIZE) + "\n")
    if not b.exists():
        row = "10" * (SIZE // 2)
        b.write_text(f"{SIZE} {SIZE}\n" + "\n".join([row] * SIZE) + "\n")
    return a, b


def run_case(name, grid):
    out = VAR / f"bench_{name}.html"
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "regionmark.py"), str(grid), str(out)],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_kib = max(before, after)  # ru_maxrss 是历史峰值，取差语义上为本次峰值上界
    peak_mib = peak_kib / 1024
    ok = proc.returncode == 0 and elapsed <= TIME_BUDGET and peak_mib <= RSS_BUDGET_MIB
    status = "OK  " if ok else "FAIL"
    print(
        f"{status} bench {name}: {elapsed:.2f}s (budget {TIME_BUDGET}s), "
        f"peak RSS {peak_mib:.0f} MiB (budget {RSS_BUDGET_MIB} MiB), "
        f"exit {proc.returncode}"
    )
    if proc.returncode != 0:
        print(proc.stderr.strip())
    return ok


def main():
    grid_a, grid_b = make_grids()
    ok = run_case("a", grid_a)
    ok = run_case("b", grid_b) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
