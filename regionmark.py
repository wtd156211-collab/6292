#!/usr/bin/env python3
"""regionmark: 四连通区域标记。

读取 0/1 网格，按 README 口径做四连通标记（对角不算、图外不算连通），
输出内联编号图与统计表的单文件 HTML。仅使用标准库。

用法: python3 regionmark.py <网格文件> <输出 html 路径>
"""

import json
import re
import sys
from array import array
from html import escape
from pathlib import Path

MAX_DIM = 2048
STATS_HEADER = "label pixels min_row min_col max_row max_col centroid_row centroid_col"
_RUN_RE = re.compile("1+")

# 面积不足全图像素数该比例的区域在页面中淡化显示（大图碎块淡化，小图全亮）
FADE_RATIO = 0.001


class GridError(Exception):
    """输入非法时抛出，消息不含 'error:' 前缀。"""


def parse_grid(path):
    """解析网格文件，返回 (W, H, rows)。非法输入抛 GridError。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise GridError(f"cannot read input file: {exc.strerror or exc}") from exc
    lines = text.splitlines()
    if not lines:
        raise GridError("empty file: missing 'W H' header")
    parts = lines[0].split()
    if len(parts) != 2:
        raise GridError("first line must be 'W H' (two integers)")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError:
        raise GridError("W and H must be decimal integers") from None
    if not (1 <= width <= MAX_DIM and 1 <= height <= MAX_DIM):
        raise GridError(f"dimensions out of range: need 1 <= W, H <= {MAX_DIM}")
    rows = []
    for lineno, raw in enumerate(lines[1:], start=2):
        stripped = raw.strip()
        if not stripped:
            if len(rows) >= height:
                continue  # 文件末尾允许空行
            raise GridError(f"line {lineno}: expected {height} data rows, row is blank")
        if len(rows) >= height:
            raise GridError(f"line {lineno}: extra content after {height} data rows")
        if len(stripped) != width:
            raise GridError(
                f"line {lineno}: row width {len(stripped)} != {width}"
            )
        if stripped.strip("01"):
            raise GridError(f"line {lineno}: only '0' and '1' are allowed")
        rows.append(stripped)
    if len(rows) < height:
        raise GridError(f"expected {height} data rows, got {len(rows)}")
    return width, height, rows


def label_runs(rows, width, height):
    """两遍扫描（行游程 + 并查集）。

    返回 (run_start, run_end, run_row, row_offsets, run_label, stats_rows)：
    全部游程按扫描序扁平存放在 array 中（end 为开区间），row_offsets[r]
    是第 r 行第一个游程的下标；run_label 为每个游程的最终区域编号（1 起）；
    stats_rows 按编号升序，每行 [label, n, min_r, min_c, max_r, max_c,
    sum_r, sum_c]。不递归、不驻留逐像素编号图，内存与游程数成正比。
    """
    run_start = array("i")   # 每个游程的起始列
    run_end = array("i")     # 每个游程的结束列（开区间）
    run_row = array("i")     # 每个游程所在行
    parent = array("i")      # 并查集，下标即游程序号
    row_offsets = [0]        # 每行游程在扁平数组中的起始下标

    prev_starts = []
    prev_ends = []
    prev_ids = []

    for r in range(height):
        line = rows[r]
        cur_starts = []
        cur_ends = []
        cur_ids = []
        j = 0
        n_prev = len(prev_starts)
        for match in _RUN_RE.finditer(line):
            s = match.start()
            e = match.end()
            rid = len(parent)
            parent.append(rid)
            run_start.append(s)
            run_end.append(e)
            run_row.append(r)
            while j < n_prev and prev_ends[j] <= s:
                j += 1
            k = j
            while k < n_prev and prev_starts[k] < e:
                # 与上一行第 k 个游程列区间相交：并入同一集合
                x = rid
                y = prev_ids[k]
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                while parent[y] != y:
                    parent[y] = parent[parent[y]]
                    y = parent[y]
                if x != y:
                    parent[x] = y
                k += 1
            cur_starts.append(s)
            cur_ends.append(e)
            cur_ids.append(rid)
        row_offsets.append(len(parent))
        prev_starts = cur_starts
        prev_ends = cur_ends
        prev_ids = cur_ids

    # 第二遍：按扫描序为集合根分配最终编号并累计统计
    root_label = {}
    stats = []  # 下标 = label - 1 -> [n, min_r, min_c, max_r, max_c, sum_r, sum_c]
    run_label = array("i", [0]) * len(parent)
    next_label = 0
    for i in range(len(parent)):
        x = i
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        label = root_label.get(x)
        if label is None:
            next_label += 1
            label = next_label
            root_label[x] = label
            stats.append([0, height, width, -1, -1, 0, 0])
        run_label[i] = label
        st = stats[label - 1]
        r = run_row[i]
        s = run_start[i]
        e = run_end[i]
        cnt = e - s
        st[0] += cnt
        if r < st[1]:
            st[1] = r
        if s < st[2]:
            st[2] = s
        if r > st[3]:
            st[3] = r
        if e - 1 > st[4]:
            st[4] = e - 1
        st[5] += r * cnt
        st[6] += (s + e - 1) * cnt // 2

    stats_rows = [
        [label] + st for label, st in enumerate(stats, start=1)
    ]
    return run_start, run_end, run_row, row_offsets, run_label, stats_rows


def format_stats(stats_rows):
    """生成统计表文本（含表头）。"""
    lines = [STATS_HEADER]
    for label, n, min_r, min_c, max_r, max_c, sum_r, sum_c in stats_rows:
        lines.append(
            f"{label} {n} {min_r} {min_c} {max_r} {max_c} "
            f"{format(sum_r / n, '.4f')} {format(sum_c / n, '.4f')}"
        )
    return "\n".join(lines)


def format_label_map(run_start, run_end, row_offsets, run_label, width, height):
    """生成编号图文本：H 行，每行 W 个编号，单空格分隔。"""
    zero_row = ["0"] * width
    lines = []
    for r in range(height):
        tokens = list(zero_row)
        for i in range(row_offsets[r], row_offsets[r + 1]):
            s = run_start[i]
            e = run_end[i]
            tokens[s:e] = [str(run_label[i])] * (e - s)
        lines.append(" ".join(tokens))
    return "\n".join(lines)


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>regionmark · {title}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5em; color: #222; }}
h1 {{ font-size: 1.2em; }}
h2 {{ font-size: 1em; margin-top: 1.5em; }}
pre {{ background: #f6f6f6; border: 1px solid #ddd; padding: .6em;
      overflow: auto; font-size: 11px; line-height: 1.2; }}
canvas {{ border: 1px solid #ccc; image-rendering: pixelated;
         max-width: 100%; margin-top: .5em; }}
table {{ border-collapse: collapse; font-size: 13px; }}
th, td {{ border: 1px solid #ccc; padding: 2px 8px; text-align: right; }}
th {{ background: #f0f0f0; }}
.meta {{ color: #555; font-size: 13px; }}
</style>
</head>
<body>
<h1>regionmark · {title}</h1>
<p class="meta">{width} × {height}，四连通，共 {n_regions} 个区域。
面积不足全图 {fade_pct}% 的碎块已自动淡化。</p>
<canvas id="view" width="{width}" height="{height}"></canvas>
<h2>最大的区域（按像素数，至多 10 个）</h2>
<table id="top-regions">
<thead><tr><th>label</th><th>pixels</th><th>min_row</th><th>min_col</th>
<th>max_row</th><th>max_col</th><th>centroid_row</th><th>centroid_col</th></tr></thead>
<tbody></tbody>
</table>
<h2>编号图</h2>
<pre id="label-map">
{label_map}
</pre>
<h2>统计表</h2>
<pre id="stats">
{stats}
</pre>
<script id="region-stats" type="application/json">
{stats_json}
</script>
<script>
"use strict";
const STATS = JSON.parse(document.getElementById("region-stats").textContent);
const W = {width}, H = {height};
const rows = document.getElementById("label-map").textContent
  .trim().split("\\n").map(line => line.trim().split(" ").map(Number));
const fadeCut = W * H * {fade_ratio};
function colorFor(label) {{
  const hue = (label * 137.508) % 360;
  return `hsl(${{hue.toFixed(1)}}, 70%, 45%)`;
}}
const canvas = document.getElementById("view");
const ctx = canvas.getContext("2d");
const img = ctx.createImageData(W, H);
const cache = new Map();
for (let r = 0; r < H; r++) {{
  for (let c = 0; c < W; c++) {{
    const label = rows[r][c];
    const off = (r * W + c) * 4;
    if (label === 0) {{ img.data[off + 3] = 255; continue; }}
    let col = cache.get(label);
    if (col === undefined) {{
      const tmp = document.createElement("canvas").getContext("2d");
      tmp.fillStyle = colorFor(label);
      tmp.fillRect(0, 0, 1, 1);
      const d = tmp.getImageData(0, 0, 1, 1).data;
      col = [d[0], d[1], d[2]];
      cache.set(label, col);
    }}
    const faded = STATS[label - 1].pixels < fadeCut;
    img.data[off] = col[0]; img.data[off + 1] = col[1]; img.data[off + 2] = col[2];
    img.data[off + 3] = faded ? 60 : 255;
  }}
}}
ctx.putImageData(img, 0, 0);
const tbody = document.querySelector("#top-regions tbody");
const top = [...STATS].sort((a, b) => b.pixels - a.pixels || a.label - b.label)
  .slice(0, 10);
for (const s of top) {{
  const tr = document.createElement("tr");
  for (const v of [s.label, s.pixels, s.min_row, s.min_col,
                   s.max_row, s.max_col, s.centroid_row, s.centroid_col]) {{
    const td = document.createElement("td");
    td.textContent = v;
    tr.appendChild(td);
  }}
  tbody.appendChild(tr);
}}
</script>
</body>
</html>
"""


def render_html(width, height, label_map_text, stats_text, stats_rows, title):
    """渲染单文件 HTML；着色与统计只使用引擎输出，页面内不重新计数。"""
    stats_json = json.dumps(
        [
            {
                "label": label,
                "pixels": n,
                "min_row": min_r,
                "min_col": min_c,
                "max_row": max_r,
                "max_col": max_c,
                "centroid_row": format(sum_r / n, ".4f"),
                "centroid_col": format(sum_c / n, ".4f"),
            }
            for label, n, min_r, min_c, max_r, max_c, sum_r, sum_c in stats_rows
        ],
        separators=(",", ":"),
    )
    return _PAGE_TEMPLATE.format(
        title=escape(title),
        width=width,
        height=height,
        n_regions=len(stats_rows),
        fade_pct=FADE_RATIO * 100,
        fade_ratio=FADE_RATIO,
        label_map=escape(label_map_text),
        stats=escape(stats_text),
        stats_json=stats_json,
    )


def main(argv):
    if len(argv) != 3:
        print(
            "error: usage: python3 regionmark.py <网格文件> <输出 html 路径>",
            file=sys.stderr,
        )
        return 2
    grid_path, out_path = argv[1], argv[2]
    try:
        width, height, rows = parse_grid(grid_path)
    except GridError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    run_start, run_end, run_row, row_offsets, run_label, stats_rows = label_runs(
        rows, width, height
    )
    label_map_text = format_label_map(
        run_start, run_end, row_offsets, run_label, width, height
    )
    stats_text = format_stats(stats_rows)
    html = render_html(
        width, height, label_map_text, stats_text, stats_rows, Path(grid_path).name
    )

    try:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write output: {exc.strerror or exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
