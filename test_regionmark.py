#!/usr/bin/env python3
"""unittest suite for regionmark.py (standard library only)."""

import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import regionmark  # noqa: E402

SAMPLES = ROOT / "samples"
GRIDS = SAMPLES / "grids"
EXPECTED = SAMPLES / "expected"

SAMPLE_NAMES = [
    "border",
    "diagonal",
    "fragments",
    "ring",
    "solid_black",
    "solid_white",
    "thin",
]

EXTERNAL_REF = re.compile(r'src=|href=|url\(|@import|fetch\(|https?://', re.I)


def run_labeling(name):
    text = (GRIDS / (name + ".txt")).read_text(encoding="utf-8")
    width, height, rows = regionmark.parse_grid(text)
    labels, stats = regionmark.label_regions(width, height, rows)
    return (
        regionmark.label_map_text(width, height, labels),
        regionmark.stats_text(stats),
    )


def expected_text(name, kind):
    raw = (EXPECTED / ("%s.%s.txt" % (name, kind))).read_text(encoding="utf-8")
    return "\n".join(line.strip() for line in raw.strip().splitlines())


class TestSamples(unittest.TestCase):
    def test_label_maps_match_expected(self):
        for name in SAMPLE_NAMES:
            with self.subTest(sample=name):
                map_text, _ = run_labeling(name)
                self.assertEqual(map_text, expected_text(name, "labels"))

    def test_stats_match_expected(self):
        for name in SAMPLE_NAMES:
            with self.subTest(sample=name):
                _, stats_block = run_labeling(name)
                self.assertEqual(stats_block, expected_text(name, "stats"))

    def test_determinism(self):
        for name in SAMPLE_NAMES:
            with self.subTest(sample=name):
                first = run_labeling(name)
                second = run_labeling(name)
                self.assertEqual(first, second)

    def test_region_count_and_total_pixels(self):
        text = (GRIDS / "fragments.txt").read_text(encoding="utf-8")
        width, height, rows = regionmark.parse_grid(text)
        _, stats = regionmark.label_regions(width, height, rows)
        foreground = sum(row.count("1") for row in rows)
        self.assertEqual(len(stats), 48)
        self.assertEqual(sum(s[1] for s in stats), foreground)


class TestParseGrid(unittest.TestCase):
    def parse(self, text):
        return regionmark.parse_grid(text)

    def test_valid_minimal(self):
        width, height, rows = self.parse("1 1\n1\n")
        self.assertEqual((width, height, rows), (1, 1, ["1"]))

    def test_trailing_blank_lines_ok(self):
        width, height, rows = self.parse("2 2\n01\n10\n\n\n")
        self.assertEqual(rows, ["01", "10"])

    def test_row_surrounding_whitespace_ok(self):
        width, height, rows = self.parse("2 1\n  01  \n")
        self.assertEqual(rows, ["01"])

    def test_bad_header(self):
        for text in ("", "3\n0 1 0\n", "a b\n0\n", "1 2 3\n0\n"):
            with self.subTest(text=text):
                self.assertRaises(regionmark.GridError, self.parse, text)

    def test_dimensions_out_of_range(self):
        self.assertRaises(regionmark.GridError, self.parse, "0 1\n0\n")
        self.assertRaises(regionmark.GridError, self.parse, "1 0\n0\n")
        self.assertRaises(
            regionmark.GridError, self.parse, "2049 1\n" + "0" * 2049 + "\n"
        )
        self.assertRaises(regionmark.GridError, self.parse, "1 2049\n0\n")

    def test_wrong_row_count(self):
        self.assertRaises(regionmark.GridError, self.parse, "2 3\n01\n10\n")
        self.assertRaises(
            regionmark.GridError, self.parse, "2 1\n01\n10\n"
        )

    def test_wrong_row_width(self):
        self.assertRaises(regionmark.GridError, self.parse, "3 1\n01\n")
        self.assertRaises(regionmark.GridError, self.parse, "1 1\n01\n")

    def test_invalid_characters(self):
        self.assertRaises(regionmark.GridError, self.parse, "2 1\n0x\n")
        self.assertRaises(regionmark.GridError, self.parse, "2 1\n0 1\n")

    def test_max_dimensions_accepted(self):
        width, height, _ = self.parse("2048 2048\n" + ("0" * 2048 + "\n") * 2048)
        self.assertEqual((width, height), (2048, 2048))


class TestConnectivitySpec(unittest.TestCase):
    def labels_of(self, text):
        width, height, rows = regionmark.parse_grid(text)
        labels, stats = regionmark.label_regions(width, height, rows)
        return width, height, labels, stats

    def test_diagonal_not_connected(self):
        _, _, labels, stats = self.labels_of("2 2\n10\n01\n")
        self.assertEqual(len(stats), 2)
        self.assertEqual(list(labels), [1, 0, 0, 2])

    def test_edges_not_connected_outside_image(self):
        # Two corners touching opposite edges are separate regions.
        _, _, _, stats = self.labels_of("3 1\n101\n")
        self.assertEqual(len(stats), 2)

    def test_row_major_numbering(self):
        _, _, labels, _ = self.labels_of("3 2\n101\n010\n")
        self.assertEqual(list(labels), [1, 0, 2, 0, 3, 0])

    def test_u_shape_union(self):
        # Two arms joined only at the bottom row form one region.
        _, _, _, stats = self.labels_of("3 3\n101\n101\n111\n")
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0][1], 7)

    def test_centroid_format(self):
        _, _, _, stats = self.labels_of("2 1\n11\n")
        self.assertEqual(stats[0][6], "0.0000")
        self.assertEqual(stats[0][7], "0.5000")


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "regionmark.py"), *args],
            capture_output=True,
            text=True,
        )

    def test_wrong_arg_count(self):
        for args in ((), ("only-one",), ("a", "b", "c")):
            with self.subTest(args=args):
                proc = self.run_cli(*args)
                self.assertEqual(proc.returncode, 2)
                self.assertTrue(proc.stderr.startswith("error:"))

    def test_missing_input_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out.html"
            proc = self.run_cli(str(pathlib.Path(tmp) / "nope.txt"), str(out))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("error:"))
            self.assertFalse(out.exists())

    def test_invalid_grid_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            grid = pathlib.Path(tmp) / "bad.txt"
            grid.write_text("2 2\n01\n0x\n", encoding="utf-8")
            out = pathlib.Path(tmp) / "out.html"
            proc = self.run_cli(str(grid), str(out))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("error:"))
            self.assertFalse(out.exists())

    def test_success_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "deep" / "nested" / "out.html"
            proc = self.run_cli(str(GRIDS / "ring.txt"), str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = out.read_text(encoding="utf-8")
            self.assertIn('<pre id="label-map">', html)
            self.assertIn('<pre id="stats">', html)
            self.assertNotRegex(html, EXTERNAL_REF)

    def test_cli_output_matches_expected_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "ring.html"
            proc = self.run_cli(str(GRIDS / "ring.txt"), str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = out.read_text(encoding="utf-8")
            for block_id, kind in (("label-map", "labels"), ("stats", "stats")):
                match = re.search(
                    r'<pre id="%s">\n?(.*?)\n?</pre>' % block_id, html, re.S
                )
                self.assertIsNotNone(match)
                got = "\n".join(
                    line.strip() for line in match.group(1).strip().splitlines()
                )
                self.assertEqual(got, expected_text("ring", kind))

    def test_cli_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            out1 = pathlib.Path(tmp) / "a.html"
            out2 = pathlib.Path(tmp) / "b.html"
            grid = str(GRIDS / "fragments.txt")
            self.assertEqual(self.run_cli(grid, str(out1)).returncode, 0)
            self.assertEqual(self.run_cli(grid, str(out2)).returncode, 0)
            self.assertEqual(out1.read_bytes(), out2.read_bytes())


def _reference_label(width, height, rows):
    """Independent naive reference: deque flood fill, row-major labeling."""
    from collections import deque

    grid = [[ch == "1" for ch in row] for row in rows]
    labels = [[0] * width for _ in range(height)]
    stats = {}
    next_id = 0
    for r in range(height):
        for c in range(width):
            if not grid[r][c] or labels[r][c]:
                continue
            next_id += 1
            nid = next_id
            queue = deque([(r, c)])
            labels[r][c] = nid
            pixels = 0
            min_r = max_r = r
            min_c = max_c = c
            sum_r = sum_c = 0
            while queue:
                y, x = queue.popleft()
                pixels += 1
                if y < min_r:
                    min_r = y
                if y > max_r:
                    max_r = y
                if x < min_c:
                    min_c = x
                if x > max_c:
                    max_c = x
                sum_r += y
                sum_c += x
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if (
                        0 <= ny < height
                        and 0 <= nx < width
                        and grid[ny][nx]
                        and labels[ny][nx] == 0
                    ):
                        labels[ny][nx] = nid
                        queue.append((ny, nx))
            stats[nid] = (
                pixels,
                min_r,
                min_c,
                max_r,
                max_c,
                format(sum_r / pixels, ".4f"),
                format(sum_c / pixels, ".4f"),
            )
    flat = [v for row in labels for v in row]
    rows_out = []
    for nid in range(1, next_id + 1):
        rows_out.append((nid,) + stats[nid])
    return flat, rows_out


class TestDifferentialRandom(unittest.TestCase):
    def test_matches_naive_flood_fill(self):
        import random

        rng = random.Random(20260928)
        for trial in range(40):
            width = rng.randint(1, 48)
            height = rng.randint(1, 48)
            density = rng.choice((0.1, 0.3, 0.5, 0.7, 0.9))
            rows = [
                "".join("1" if rng.random() < density else "0" for _ in range(width))
                for _ in range(height)
            ]
            text = "%d %d\n%s\n" % (width, height, "\n".join(rows))
            with self.subTest(
                trial=trial, size=(width, height), density=density
            ):
                w, h, parsed = regionmark.parse_grid(text)
                labels, stats = regionmark.label_regions(w, h, parsed)
                ref_labels, ref_stats = _reference_label(w, h, parsed)
                self.assertEqual(list(labels), ref_labels)
                self.assertEqual(
                    [(s[1:]) for s in stats], [(s[1:]) for s in ref_stats]
                )
                self.assertEqual(len(stats), len(ref_stats))


if __name__ == "__main__":
    unittest.main()
