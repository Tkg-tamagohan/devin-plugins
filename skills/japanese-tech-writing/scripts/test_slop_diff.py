"""slop_diff の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は DIFF-連番。CLI の入出力契約(原文ファイルと推敲ファイルの 2 引数、
`--json` と `--endings` オプション)と、依頼文を動作文へ書き換えたときの
文末種別のずれ検出を固定する。

実行: `python3 test_slop_diff.py`(同ディレクトリから)
"""

import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "slop_diff.py"

sys.path.insert(0, str(SCRIPT.parent))
import markdown_visibility
import slop_diff


def run_diff(*args: str) -> subprocess.CompletedProcess:
    # スクリプトは標準出力を UTF-8 に揃えるため、ロケール非依存で UTF-8 デコードする
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_diff_cp932(*args: str) -> subprocess.CompletedProcess:
    """標準入出力が cp932 の環境を PYTHONIOENCODING で作って子プロセスを実行する"""
    env = dict(os.environ, PYTHONIOENCODING="cp932:surrogateescape")
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT)] + [str(a) for a in args],
        capture_output=True,
        env=env,
        timeout=10,
    )


_KEEP = object()


def run_in_process(script, args, stdin=_KEEP, stdout=_KEEP):
    """標準入出力を TextIOWrapper 以外に差し替えて、スクリプトを __main__ として実行する"""
    patches = [mock.patch.object(sys, "argv", [str(script)] + [str(a) for a in args])]
    if stdin is not _KEEP:
        patches.append(mock.patch.object(sys, "stdin", stdin))
    patches.append(mock.patch.object(sys, "stdout", io.StringIO() if stdout is _KEEP else stdout))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as stop:
            return stop.code or 0
    return 0


_TEMP_FILES = []


def write_temp(content: str, suffix: str = ".md") -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=suffix, delete=False
    )
    f.write(content)
    f.close()
    _TEMP_FILES.append(f.name)
    return f.name


def tearDownModule():
    for path in _TEMP_FILES:
        os.unlink(path)


class TestSlopDiffCli(unittest.TestCase):
    """差分検査ツールの CLI 入出力契約"""

    def test_diff_01_二引数で文末種別のずれを報告する(self):
        # 依頼文を動作文へ書き換えたサンプルで「依頼 → 常体」のずれを検出する
        orig = write_temp("設定ファイルを確認してください。\n手順は以下のとおりです。\n")
        rewrite = write_temp("設定ファイルを確認する。\n手順は以下のとおりです。\n")
        result = run_diff(orig, rewrite)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("依頼 → 常体", result.stdout)

    def test_diff_02_jsonオプションは機械可読な結果を返す(self):
        orig = write_temp("設定ファイルを確認してください。\n")
        rewrite = write_temp("設定ファイルを確認する。\n")
        result = run_diff(orig, rewrite, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("markers", data)
        self.assertIn("endings", data)
        self.assertIn("changes", data["endings"])
        changes = data["endings"]["changes"]
        self.assertEqual(changes[0]["orig_kind"], "依頼")
        self.assertEqual(changes[0]["rewrite_kind"], "常体")

    def test_diff_03_endingsオプションは一文末一覧を返す(self):
        target = write_temp("設定ファイルを確認してください。\n手順は以下のとおりです。\n")
        result = run_diff("--endings", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("文末の種類", result.stdout)
        self.assertIn("依頼", result.stdout)

    def test_diff_04_引数不足は使い方を出して失敗する(self):
        result = run_diff()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("使い方", result.stdout)

    def test_diff_05_変化のない比較は候補なしとする(self):
        orig = write_temp("値は正しいです。\n形式も正しいです。\n")
        result = run_diff(orig, orig)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("候補なし", result.stdout)


class TestSlopDiffStdio(unittest.TestCase):
    """標準入出力が cp932 の環境でも UTF-8 で読み書きする(上流 test_stdio_encoding.py の移植)"""

    def test_diff_06_ダッシュを含む差分をcp932でjson出力できる(self):
        orig = write_temp("設定を更新します。\n")
        rewrite = write_temp("設定を更新しました — 再起動してください。\n")
        result = run_diff_cp932(orig, rewrite, "--json")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertTrue(result.stdout.isascii(), "--json の出力は ASCII だけにする")
        json.loads(result.stdout.decode("ascii"))

    def test_diff_07_絵文字を含む差分をcp932で落ちずに報告する(self):
        # 文末が変わった文はレポートにそのまま出るため、cp932 で表せない文字を含めて確かめる
        orig = write_temp("設定を更新します。\n")
        rewrite = write_temp("設定を🚀更新しました。\n")
        report = run_diff_cp932(orig, rewrite)
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        self.assertIn("🚀", report.stdout.decode("utf-8"))

    def test_diff_08_StringIOの標準出力へjsonを書き込める(self):
        # reconfigure() を持たない標準出力でも動く
        orig = write_temp("本記事では、手触りのある設計の本質に迫ります。\n")
        rewrite = write_temp("本記事では、設計の本質に迫りました。\n")
        out = io.StringIO()
        self.assertEqual(run_in_process(SCRIPT, [orig, rewrite, "--json"], stdout=out), 0)
        self.assertIsInstance(json.loads(out.getvalue()), dict)


class TestExactScanOptimizations(unittest.TestCase):
    """bare_end の括弧バランス処理と markdown_visibility の境界/性能(上流 test_exact_scan_optimizations.py の移植)"""

    def test_diff_09_bare_endは文末の括弧注釈を対応付きで除去する(self):
        examples = {
            "確認します（注）（補足）。": "確認します",
            "確認します（注) (補足）": "確認します",
            "確認します（外（内））": "確認します（外（内",
            "確認します（未完": "確認します（未完",
            "確認します）": "確認します",
            "確認します(注)。まだ続きます": "確認します(注)。まだ続きます",
            "確認します(注。)": "確認します",
            "確認します。(注)": "確認します。",
        }
        for original, expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(slop_diff.bare_end(original), expected)

    def test_diff_10_bare_endは注釈が大量に続いても定時間で終わる(self):
        # 旧実装は末尾の括弧ごとに正規表現を全文へ再適用し、注釈数に対して二次のコストだった
        text = "確認します" + "(注) " * 20_000
        started = time.perf_counter()
        self.assertEqual(slop_diff.bare_end(text), "確認します")
        self.assertLess(time.perf_counter() - started, 3.0)

    def test_diff_11_成立しないwww始まりでは残り候補を全検証しない(self):
        repetitions = 2_000
        with mock.patch.object(markdown_visibility.re, "fullmatch", wraps=markdown_visibility.re.fullmatch) as match:
            self.assertEqual(markdown_visibility.inline_protected_spans("www." * repetitions), [])
        self.assertLessEqual(match.call_count, repetitions + 10)

    def test_diff_12_wwwのURL境界と直前の本文を正しく判定する(self):
        for text, expected in (
            ("www.example.com", [(0, 15, "bare_url")]),
            ("awww.example.com", []),
            ("(www.example.com/path)", [(1, 21, "bare_url")]),
            ("文www.example.com", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(markdown_visibility.inline_protected_spans(text), expected)

    def test_diff_13_独立テーブル行は種別を保ち定時間で終わる(self):
        count = 12_000
        text = "| 項目 | 値 |\n|---|---|\n| A | B |\n\n" * count
        started = time.perf_counter()
        result = markdown_visibility.analyze_markdown(text)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertEqual(sum(row["kind"] == "table" for row in result["lines"]), count * 3)
        self.assertEqual(len(result["lines"]), count * 4 + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
