"""slop_diff の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は DIFF-連番。CLI の入出力契約(原文ファイルと推敲ファイルの 2 引数、
`--json` と `--endings` オプション)と、依頼文を動作文へ書き換えたときの
文末種別のずれ検出を固定する。

実行: `python3 test_slop_diff.py`(同ディレクトリから)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "slop_diff.py"


def run_diff(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
