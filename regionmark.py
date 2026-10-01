#!/usr/bin/env python3
"""regionmark: 4-connectivity connected-component labeling for 0/1 grids.

Usage:
    python3 regionmark.py <grid-file> <output-html>

Reads a 0/1 grid, labels connected regions (4-connectivity, row-major
numbering starting at 1, background is 0), and writes a self-contained
HTML report with the label map, per-region statistics and a colored
visualization. Standard library only.
"""

import os
import sys
from array import array

MAX_DIM = 2048
STATS_HEADER = (
    "label pixels min_row min_col max_row max_col centroid_row centroid_col"
)
TOP_REGIONS_SHOWN = 10


class GridError(Exception):
    """Raised when the input grid file is malformed."""


def parse_grid(text):
    """Parse grid file text into (width, height, rows). Raises GridError."""
    lines = text.splitlines()
    if not lines:
        raise GridError("empty file")
    header = lines[0].split()
    if len(header) != 2 or not all(tok.isdigit() for tok in header):
        raise GridError("first line must be 'W H' (two decimal integers)")
    width, height = int(header[0]), int(header[1])
    if not (1 <= width <= MAX_DIM and 1 <= height <= MAX_DIM):
        raise GridError(
            "dimensions out of range (1..%d): %d x %d" % (MAX_DIM, width, height)
        )
    body = lines[1:]
    if len(body) < height:
        raise GridError("expected %d grid rows, found %d" % (height, len(body)))
    rows = []
    for r in range(height):
        row = body[r].strip()
        if len(row) != width:
            raise GridError(
                "row %d: expected %d chars, got %d" % (r, width, len(row))
            )
        if row.strip("01"):
            raise GridError("row %d: only '0' and '1' are allowed" % r)
        rows.append(row)
    for extra in body[height:]:
        if extra.strip():
            raise GridError("unexpected content after the %d grid rows" % height)
    return width, height, rows


def label_regions(width, height, rows):
    """Two-pass 4-connectivity labeling with union-find.

    Returns (labels, stats) where labels is a flat array('i') of size
    width*height (0 = background, 1..N = region id assigned in row-major
    first-appearance order) and stats is a list of tuples:
    (label, pixels, min_row, min_col, max_row, max_col, centroid_row, centroid_col)
    with the centroids formatted to 4 decimals.
    """
    size = width * height
    lab = array("i", [0]) * size
    par = array("i", [0])  # union-find parent, 1-based provisional labels
    nxt = 0

    # First pass, row 0 (no above neighbor).
    row = rows[0]
    left = 0
    for c in range(width):
        if row[c] == "1":
            if left == 0:
                nxt += 1
                par.append(nxt)
                left = nxt
            lab[c] = left
        else:
            left = 0

    # First pass, remaining rows.
    for r in range(1, height):
        row = rows[r]
        base = r * width
        off = base - width
        left = 0
        for c in range(width):
            if row[c] == "1":
                above = lab[off + c]
                if left == 0:
                    if above == 0:
                        nxt += 1
                        par.append(nxt)
                        lab[base + c] = nxt
                        left = nxt
                    else:
                        lab[base + c] = above
                        left = above
                elif above == 0 or above == left:
                    lab[base + c] = left
                else:
                    ra = left
                    while par[ra] != ra:
                        par[ra] = par[par[ra]]
                        ra = par[ra]
                    rb = above
                    while par[rb] != rb:
                        par[rb] = par[par[rb]]
                        rb = par[rb]
                    if ra != rb:
                        if ra < rb:
                            par[rb] = ra
                            root = ra
                        else:
                            par[ra] = rb
                            root = rb
                    else:
                        root = ra
                    lab[base + c] = root
                    left = root
            else:
                left = 0

    # Second pass: remap roots to final ids in row-major first-appearance
    # order (which is exactly the spec's numbering) and gather statistics.
    n1 = nxt + 1
    remap = array("i", [0]) * n1
    count = array("i", [0]) * n1
    min_row = array("i", [0]) * n1
    min_col = array("i", [0]) * n1
    max_row = array("i", [0]) * n1
    max_col = array("i", [0]) * n1
    sum_row = array("q", [0]) * n1
    sum_col = array("q", [0]) * n1

    new_id = 0
    for r in range(height):
        base = r * width
        for c in range(width):
            i = base + c
            lb = lab[i]
            if lb:
                nid = remap[lb]
                if nid == 0:
                    root = lb
                    while par[root] != root:
                        par[root] = par[par[root]]
                        root = par[root]
                    nid = remap[root]
                    if nid == 0:
                        new_id += 1
                        nid = new_id
                        remap[root] = nid
                        min_row[nid] = r
                        min_col[nid] = c
                        max_col[nid] = c
                lab[i] = nid
                count[nid] += 1
                max_row[nid] = r
                if c < min_col[nid]:
                    min_col[nid] = c
                if c > max_col[nid]:
                    max_col[nid] = c
                sum_row[nid] += r
                sum_col[nid] += c

    stats = []
    for nid in range(1, new_id + 1):
        n = count[nid]
        stats.append(
            (
                nid,
                n,
                min_row[nid],
                min_col[nid],
                max_row[nid],
                max_col[nid],
                format(sum_row[nid] / n, ".4f"),
                format(sum_col[nid] / n, ".4f"),
            )
        )
    return lab, stats


def label_map_text(width, height, labels):
    out = []
    for r in range(height):
        base = r * width
        out.append(" ".join(map(str, labels[base : base + width])))
    return "\n".join(out)


def stats_text(stats):
    lines = [STATS_HEADER]
    for row in stats:
        lines.append(" ".join(map(str, row)))
    return "\n".join(lines)


def faded_labels(stats):
    """Labels treated as fragments: smaller than 0.1% of the largest region."""
    if not stats:
        return []
    biggest = max(row[1] for row in stats)
    return [row[0] for row in stats if row[1] * 1000 < biggest]


CSS = """
body { font-family: sans-serif; margin: 1.5em; color: #222; }
h1 { font-size: 1.3em; }
h2 { font-size: 1.05em; margin-top: 1.4em; }
canvas { border: 1px solid #999; max-width: 100%; image-rendering: pixelated; }
table { border-collapse: collapse; }
th, td { border: 1px solid #bbb; padding: 2px 8px; text-align: right;
         font-variant-numeric: tabular-nums; }
th { background: #eee; }
.swatch { display: inline-block; width: 0.9em; height: 0.9em;
          border: 1px solid #888; vertical-align: -0.1em; }
pre { background: #f6f6f6; border: 1px solid #ccc; padding: 0.6em;
      overflow: auto; font-size: 0.8em; line-height: 1.25; }
.note { color: #555; font-size: 0.9em; }
"""

JS = """
const W = GRID_W, H = GRID_H;
const FADED = new Set(FADED_LABELS);
const pre = document.getElementById('label-map');
const lines = pre.textContent.trim().split('\\n');
const canvas = document.getElementById('view');
canvas.width = W;
canvas.height = H;
const ctx = canvas.getContext('2d');
const img = ctx.createImageData(W, H);
const px = img.data;
function hsl2rgb(h, s, l) {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r, g, b;
  if (h < 60) { r = c; g = x; b = 0; }
  else if (h < 120) { r = x; g = c; b = 0; }
  else if (h < 180) { r = 0; g = c; b = x; }
  else if (h < 240) { r = 0; g = x; b = c; }
  else if (h < 300) { r = x; g = 0; b = c; }
  else { r = c; g = 0; b = x; }
  return [Math.round((r + m) * 255), Math.round((g + m) * 255),
          Math.round((b + m) * 255)];
}
const cache = new Map();
function colorFor(label) {
  let col = cache.get(label);
  if (col === undefined) {
    const hue = (label * 137.508) % 360;
    col = FADED.has(label) ? hsl2rgb(hue, 0.18, 0.88)
                           : hsl2rgb(hue, 0.65, 0.55);
    cache.set(label, col);
  }
  return col;
}
for (let y = 0; y < H; y++) {
  const cells = lines[y].split(' ');
  for (let x = 0; x < W; x++) {
    const label = Number(cells[x]);
    const o = (y * W + x) * 4;
    if (label === 0) {
      px[o] = 255; px[o + 1] = 255; px[o + 2] = 255;
    } else {
      const col = colorFor(label);
      px[o] = col[0]; px[o + 1] = col[1]; px[o + 2] = col[2];
    }
    px[o + 3] = 255;
  }
}
ctx.putImageData(img, 0, 0);
"""


def render_html(width, height, labels, stats, map_text, stats_block):
    n_regions = len(stats)
    faded = faded_labels(stats)
    top = sorted(stats, key=lambda row: (-row[1], row[0]))[:TOP_REGIONS_SHOWN]

    top_rows = []
    for row in top:
        cells = "".join("<td>%s</td>" % v for v in row)
        top_rows.append(
            '<tr><td><span class="swatch" data-label="%s"></span></td>%s</tr>'
            % (row[0], cells)
        )
    top_table = (
        "<table>\n<thead><tr><th></th>"
        + "".join("<th>%s</th>" % h for h in STATS_HEADER.split())
        + "</tr></thead>\n<tbody>\n"
        + ("\n".join(top_rows) if top_rows else "")
        + "\n</tbody>\n</table>"
    )

    swatch_js = (
        "document.querySelectorAll('.swatch').forEach(function (el) {\n"
        "  const col = colorFor(Number(el.dataset.label));\n"
        "  el.style.background = 'rgb(' + col[0] + ',' + col[1] + ','\n"
        "                        + col[2] + ')';\n"
        "});"
    )

    js = (
        JS.replace("GRID_W", str(width), 1)
        .replace("GRID_H", str(height), 1)
        .replace("FADED_LABELS", "[" + ",".join(map(str, faded)) + "]", 1)
        + swatch_js
    )

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>regionmark: %d x %d, %d regions</title>" % (width, height, n_regions),
        "<style>%s</style>" % CSS,
        "</head>",
        "<body>",
        "<h1>连通域标记结果</h1>",
        '<p class="note">网格 %d × %d，共 %d 个区域（四连通，编号按行优先次序）。'
        "着色由编号确定；面积不足最大区域 0.1%% 的碎块区域已淡化。"
        % (width, height, n_regions)
        + "</p>",
        '<canvas id="view" width="%d" height="%d"></canvas>' % (width, height),
        "<h2>最大的区域（前 %d 个）</h2>" % min(TOP_REGIONS_SHOWN, n_regions),
        top_table,
        "<h2>编号图</h2>",
        '<pre id="label-map">',
        map_text,
        "</pre>",
        "<h2>统计表</h2>",
        '<pre id="stats">',
        stats_block,
        "</pre>",
        "<script>%s</script>" % js,
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def main(argv):
    if len(argv) != 3:
        print(
            "error: usage: python3 regionmark.py <grid-file> <output-html>",
            file=sys.stderr,
        )
        return 2
    grid_path, out_path = argv[1], argv[2]

    try:
        with open(grid_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(
            "error: cannot read %s: %s" % (grid_path, exc.strerror or exc),
            file=sys.stderr,
        )
        return 2
    except UnicodeDecodeError:
        print("error: %s is not valid UTF-8 text" % grid_path, file=sys.stderr)
        return 2

    try:
        width, height, rows = parse_grid(text)
    except GridError as exc:
        print("error: invalid grid: %s" % exc, file=sys.stderr)
        return 2

    labels, stats = label_regions(width, height, rows)
    map_text = label_map_text(width, height, labels)
    stats_block = stats_text(stats)
    html = render_html(width, height, labels, stats, map_text, stats_block)

    parent = os.path.dirname(out_path)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except OSError as exc:
        print(
            "error: cannot write %s: %s" % (out_path, exc.strerror or exc),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
