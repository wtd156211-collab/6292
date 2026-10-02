#!/usr/bin/env python3
"""regionmark 的单元测试（标准库 unittest）。

运行: python3 -m unittest discover -s tests -v
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import regionmark  # noqa: E402

GRIDS = ROOT / "samples" / "grids"
EXPECTED = ROOT / "samples" / "expected"


def write_grid(tmp, text):
    path = Path(tmp) / "grid.txt"
    path.write_text(text, encoding="utf-8")
    return path


def run_engine(grid_text, tmp):
    path = write_grid(tmp, grid_text)
    width, height, rows = regionmark.parse_grid(path)
    (run_start, run_end, run_row, row_offsets, run_label, stats_rows) = (
        regionmark.label_runs(rows, width, height)
    )
    label_map = regionmark.format_label_map(
        run_start, run_end, row_offsets, run_label, width, height
    )
    stats = regionmark.format_stats(stats_rows)
    return label_map, stats


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def parse(self, text):
        return regionmark.parse_grid(write_grid(self.tmp.name, text))

    def test_valid_grid(self):
        width, height, rows = self.parse("3 2\n101\n010\n")
        self.assertEqual((width, height), (3, 2))
        self.assertEqual(rows, ["101", "010"])

    def test_trailing_blank_lines_allowed(self):
        width, height, rows = self.parse("2 1\n11\n\n\n")
        self.assertEqual(rows, ["11"])

    def test_surrounding_whitespace_ignored(self):
        _, _, rows = self.parse(" 2 1 \n  10  \n")
        self.assertEqual(rows, ["10"])

    def test_missing_file(self):
        with self.assertRaises(regionmark.GridError):
            regionmark.parse_grid(Path(self.tmp.name) / "nope.txt")

    def test_bad_header(self):
        for text in ["", "3\n1 0 1\n", "x 2\n10\n01\n", "1 2 3\n1\n0\n"]:
            with self.assertRaises(regionmark.GridError, msg=text):
                self.parse(text)

    def test_dimension_out_of_range(self):
        for header in ["0 1", "1 0", "2049 1", "1 2049", "-1 2"]:
            with self.assertRaises(regionmark.GridError, msg=header):
                self.parse(f"{header}\n1\n")

    def test_bad_character(self):
        with self.assertRaises(regionmark.GridError):
            self.parse("3 1\n102\n")

    def test_inner_whitespace_rejected(self):
        with self.assertRaises(regionmark.GridError):
            self.parse("3 1\n1 1\n")

    def test_wrong_row_width(self):
        with self.assertRaises(regionmark.GridError):
            self.parse("3 2\n111\n11\n")

    def test_too_few_rows(self):
        with self.assertRaises(regionmark.GridError):
            self.parse("2 3\n11\n00\n")

    def test_extra_rows_rejected(self):
        with self.assertRaises(regionmark.GridError):
            self.parse("2 1\n11\n00\n")


class LabelingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def engine(self, text):
        return run_engine(text, self.tmp.name)

    def test_diagonal_not_connected(self):
        # 对角相接不算连通；编号按行优先扫描次序
        label_map, stats = self.engine("2 2\n10\n01\n")
        self.assertEqual(label_map, "1 0\n0 2")
        self.assertEqual(
            stats.splitlines()[1:],
            ["1 1 0 0 0 0 0.0000 0.0000", "2 1 1 1 1 1 1.0000 1.0000"],
        )

    def test_four_connectivity_merges(self):
        label_map, stats = self.engine("2 2\n11\n10\n")
        self.assertEqual(label_map, "1 1\n1 0")
        self.assertEqual(
            stats.splitlines()[1:], ["1 3 0 0 1 1 0.3333 0.3333"]
        )

    def test_edges_do_not_wrap(self):
        # 两块都贴边、图内不相通：仍是两个区域
        label_map, stats = self.engine("4 2\n1001\n0000\n")
        self.assertEqual(label_map, "1 0 0 2\n0 0 0 0")

    def test_hole_stays_background(self):
        label_map, _ = self.engine("3 3\n111\n101\n111\n")
        self.assertEqual(label_map, "1 1 1\n1 0 1\n1 1 1")

    def test_all_white_has_zero_regions(self):
        label_map, stats = self.engine("2 2\n00\n00\n")
        self.assertEqual(label_map, "0 0\n0 0")
        self.assertEqual(stats, regionmark.STATS_HEADER)

    def test_scan_order_numbering(self):
        # 后扫描到的区域编号更大，即使它位置更靠下
        label_map, _ = self.engine("3 3\n101\n000\n010\n")
        self.assertEqual(label_map, "1 0 2\n0 0 0\n0 3 0")

    def test_centroid_format(self):
        _, stats = self.engine("3 1\n111\n")
        self.assertEqual(
            stats.splitlines()[1], "1 3 0 0 0 2 0.0000 1.0000"
        )

    def test_deterministic_across_runs(self):
        text = "5 4\n10101\n01010\n11111\n00001\n"
        first = self.engine(text)
        second = self.engine(text)
        self.assertEqual(first, second)


class SampleTests(unittest.TestCase):
    """samples 下每组网格必须与 expected 逐值一致。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_all_samples(self):
        for grid in sorted(GRIDS.glob("*.txt")):
            name = grid.stem
            with self.subTest(sample=name):
                width, height, rows = regionmark.parse_grid(grid)
                (rs, re_, rr, ro, rl, stats_rows) = regionmark.label_runs(
                    rows, width, height
                )
                label_map = regionmark.format_label_map(
                    rs, re_, ro, rl, width, height
                )
                stats = regionmark.format_stats(stats_rows)
                expected_labels = (EXPECTED / f"{name}.labels.txt").read_text(
                    encoding="utf-8"
                ).strip("\n")
                expected_stats = (EXPECTED / f"{name}.stats.txt").read_text(
                    encoding="utf-8"
                ).strip("\n")
                self.assertEqual(label_map, expected_labels)
                self.assertEqual(stats, expected_stats)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "nested" / "dir" / "out.html"

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "regionmark.py"), *args],
            capture_output=True,
            text=True,
        )

    def test_success_creates_parent_dirs(self):
        grid = write_grid(self.tmp.name, "2 2\n11\n01\n")
        proc = self.run_cli(str(grid), str(self.out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.out.exists())
        html = self.out.read_text(encoding="utf-8")
        self.assertIn('<pre id="label-map">', html)
        self.assertIn('<pre id="stats">', html)

    def test_output_is_deterministic(self):
        grid = write_grid(self.tmp.name, "3 3\n101\n010\n111\n")
        out2 = Path(self.tmp.name) / "out2.html"
        self.assertEqual(self.run_cli(str(grid), str(self.out)).returncode, 0)
        self.assertEqual(self.run_cli(str(grid), str(out2)).returncode, 0)
        self.assertEqual(
            self.out.read_bytes(), out2.read_bytes(),
            "同一网格两次运行的输出必须完全一致",
        )

    def test_no_external_resources(self):
        grid = write_grid(self.tmp.name, "2 1\n11\n")
        self.assertEqual(self.run_cli(str(grid), str(self.out)).returncode, 0)
        html = self.out.read_text(encoding="utf-8")
        pattern = re.compile(
            r"src\s*=|href\s*=|@import|url\(|fetch\(|XMLHttpRequest|"
            r"https?://|<link\b",
            re.IGNORECASE,
        )
        self.assertIsNone(pattern.search(html))

    def test_wrong_arg_count(self):
        for args in [[], ["only-one"], ["a", "b", "c"]]:
            proc = self.run_cli(*args)
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("error:"))
            self.assertEqual(proc.stderr.count("\n"), 1)

    def test_missing_input_file(self):
        proc = self.run_cli("/nonexistent/grid.txt", str(self.out))
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(proc.stderr.startswith("error:"))
        self.assertFalse(self.out.exists())

    def test_invalid_grid_writes_nothing(self):
        grid = write_grid(self.tmp.name, "2 2\n11\n1\n")
        proc = self.run_cli(str(grid), str(self.out))
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(proc.stderr.startswith("error:"))
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
