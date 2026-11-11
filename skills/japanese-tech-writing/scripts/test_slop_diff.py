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
        mode="w", encoding="utf-8", suffix=suffix, delete=False, dir="."
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


class TestSlopDiffTypeMarks(unittest.TestCase):
    """文の種類の印(type_marks 系)の検出と非検出(上流 v1.1.2 test_diff_type_changes.py の移植)"""

    def changes(self, orig, rewrite):
        return slop_diff.diff(orig + "\n", rewrite + "\n")["type_changes"]

    def kinds(self, entries, side):
        return [mark["kind"] for entry in entries for mark in entry[side]]

    def test_diff_14_伝聞の断定化を検出する(self):
        found = self.changes("原因は設定ミスだとされる。", "原因は設定ミスだ。")
        self.assertEqual(self.kinds(found, "lost"), ["伝聞"])
        self.assertEqual(found[0]["lost"][0]["hits"], ["とされる"])
        self.assertEqual(found[0]["orig"], "原因は設定ミスだとされる。")
        self.assertEqual(found[0]["rewrite"], "原因は設定ミスだ。")

    def test_diff_15_各種類の印の消失を検出する(self):
        for orig, rewrite, kind in (
                ("机はまるで戦場のようだ。", "机は戦場だ。", "例え"),
                ("この方式は遅いと思う。", "この方式は遅い。", "意見"),
                ("資料を共有してください。", "資料を共有します。", "依頼・決まり"),
                ("新しい版では起動が速くなったらしい。", "新しい版では起動が速くなった。", "推量"),
                ("明日は雨が降るそうだ。", "明日は雨が降る。", "伝聞")):
            with self.subTest(orig=orig):
                found = self.changes(orig, rewrite)
                self.assertIn(kind, self.kinds(found, "lost"))

    def test_diff_16_印の追加を検出する(self):
        found = self.changes("修正は済んでいる。", "担当者によると、修正は済んでいる。")
        self.assertEqual(self.kinds(found, "added"), ["伝聞"])
        found = self.changes("Aは速い", "Aは速いらしい")
        self.assertEqual(self.kinds(found, "added"), ["推量"])

    def test_diff_17_文を分けてもつないでも印が保たれれば出さない(self):
        for orig, rewrite in (
                ("Aは速いらしいが、Bは遅い。", "Aは速いらしい。Bは遅い。"),
                ("原因は設定ミスだとされる。", "原因は、設定ミスだとされる。"),
                ("机はまるで戦場のようだ。", "机は、まるで戦場のようだ。"),
                ("資料を共有してください。", "資料を、共有フォルダに置いてください。"),
                ("新しい版は**起動が速いらしい**。", "新しい版は起動が速いらしい。")):
            with self.subTest(orig=orig):
                self.assertEqual(self.changes(orig, rewrite), [])

    def test_diff_18_文の間で印が移っただけなら出さない(self):
        found = self.changes("Aは速いらしい。Bは遅い。", "Aは速い。Bは遅いだろう。")
        self.assertEqual([(entry["orig"], self.kinds([entry], "lost"), self.kinds([entry], "added")) for entry in found],
                         [("Aは速いらしい。", ["推量"], []), ("Bは遅い。", [], ["推量"])])

    def test_diff_19_同じ種類の言い換えは出さない(self):
        for orig, rewrite in (
                ("木曜までに私へ連絡をください。", "木曜までに私へ連絡してください。"),
                ("作業前に保存をお願いします。", "作業前に保存してください。"),
                ("キャッシュ設計を自前で固める必要がある。", "キャッシュ設計を自前で実装しなければならない。"),
                ("どうやらサーバーが落ちたみたいだ。", "どうやらサーバーが落ちたようだ。"),
                ("設定を反映するには、サーバーを再起動する必要があります。", "設定を反映するには、サーバーの再起動が必要です。")):
            with self.subTest(orig=orig):
                self.assertEqual(self.changes(orig, rewrite), [])

    def test_diff_20_印でない用法は出さない(self):
        for orig, rewrite in (
                ("空を見ると、雨が降りそうだ。", "空を見ると、雨が降る気配がある。"),
                ("今回の改善は本当に素晴らしい。", "今回の改善は見事だ。"),
                ("春らしい陽気が続いた。", "暖かい日が続いた。"),
                ("この進め方で問題ないでしょうか。", "この進め方で問題ありませんか。"),
                ("レビューでこの不具合は見落とされた。", "レビュー担当者がこの不具合を見落とした。"),
                ("この関数はべき乗を計算する。", "この関数は累乗を計算する。"),
                ("場合によると、再起動が要る。", "再起動が要ることもある。")):
            with self.subTest(orig=orig):
                self.assertEqual(self.changes(orig, rewrite), [])

    def test_diff_20b_言い換えて依頼が消えたら検出する(self):
        found = self.changes("ログの保存先は管理画面から変更してください。詳細は担当者に確認してください。",
                             "管理画面でログの保存先を変える。詳しくは担当者に聞いてください。")
        self.assertEqual(sorted(self.kinds(found, "lost")), ["依頼・決まり"])

    def test_diff_21_消した文は組にしない(self):
        self.assertEqual(self.changes("原因は設定ミスだとされる。対策は来週から始める。", "対策は来週から始める。"), [])

    def test_diff_22_隣の文の印を取り違えない(self):
        found = self.changes("障害の原因は設定ミスだとされる。古い手順は今後使わない。", "障害の原因は設定ミスかもしれない。")
        self.assertEqual(sorted(self.kinds(found, "lost")), ["伝聞"])
        self.assertEqual(sorted(self.kinds(found, "added")), ["推量"])

    def test_diff_23_jsonにtype_changesが入りレポートに節が出る(self):
        orig = write_temp("原因は設定ミスだとされる。\n")
        rewrite = write_temp("原因は設定ミスだ。\n")
        result = run_diff(orig, rewrite, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data["type_changes"][0]), {"orig", "rewrite", "lost", "added"})
        self.assertEqual(data["type_changes"][0]["lost"][0]["kind"], "伝聞")
        report = run_diff(orig, rewrite)
        self.assertIn("■ 文の種類の印が変わった文", report.stdout)
        self.assertIn("消えた印: 伝聞（とされる）", report.stdout)
        quiet = run_diff(write_temp("原因は設定ミスだとされる。\n"), write_temp("原因は、設定ミスだとされる。\n"))
        self.assertNotIn("文の種類の印", quiet.stdout)


class TestSlopDiffStructureSections(unittest.TestCase):
    """見出しと読点の軽量な構造節の検出と非検出"""

    def test_diff_24_見出しの数の変化を検出する(self):
        result = slop_diff.diff("# A\n\n## B\n\n本文。\n", "# A\n\n本文。\n")
        self.assertTrue(any("見出しの数が変わった（2 → 1）" in s for s in result["structure"]))
        self.assertTrue(any("消えた見出し: B" in s for s in result["structure"]))
        self.assertEqual(result["heading_shapes"], [])

    def test_diff_25_見出しのレベルの変化を検出する(self):
        result = slop_diff.diff("# 見出し\n\n本文です。\n", "## 見出し\n\n本文です。\n")
        self.assertEqual(len(result["structure"]), 1)
        self.assertIn("見出しのレベルを変えた", result["structure"][0])
        self.assertIn("レベル1", result["structure"][0])
        self.assertIn("レベル2", result["structure"][0])

    def test_diff_26_見出しの形の変化を検出する(self):
        result = slop_diff.diff("# これは大切な話です。\n\n本文。\n", "# 大切な話\n\n本文。\n")
        self.assertEqual(len(result["heading_shapes"]), 1)
        self.assertEqual(result["heading_shapes"][0]["old"], "これは大切な話です。")
        self.assertEqual(result["heading_shapes"][0]["new"], "大切な話")
        report = slop_diff.report(result)
        self.assertIn("■ 見出しの形が変わった", report)
        self.assertIn("元: これは大切な話です。", report)

    def test_diff_27_見出しが変わらなければ出さない(self):
        for orig, rewrite in (
                ("# 見出し\n\n本文。\n", "# 見出し\n\n本文を直した。\n"),
                ("# A\n\n## B\n\n本文。\n", "# A\n\n## B\n\n本文。\n"),
                ("見出し\n===\n\n本文。\n", "見出し\n===\n\n本文。\n")):
            with self.subTest(orig=orig):
                result = slop_diff.diff(orig, rewrite)
                self.assertFalse(any("見出し" in s for s in result["structure"]))
                self.assertEqual(result["heading_shapes"], [])

    def test_diff_28_読点の増加を検出する(self):
        result = slop_diff.diff("設定を確認します。実行します。\n", "設定を、確認し、実行し、記録します。\n")
        item = result["comma_increase"]
        self.assertIsNotNone(item)
        self.assertEqual((item["old_count"], item["new_count"]), (0, 3))
        self.assertEqual(item["sentences"][0]["old_count"], 0)
        self.assertEqual(item["sentences"][0]["new_count"], 3)
        report = slop_diff.report(result)
        self.assertIn("■ 読点が増えた", report)
        self.assertIn("読点が0個から3個に増えました", report)

    def test_diff_29_読点の増加が小さければ出さない(self):
        for orig, rewrite in (
                ("設定を確認します。実行します。\n", "設定を、確認します。実行します。\n"),
                ("Aを確認します。Bを実行します。\n", "Aを、確認します。Bを、実行します。\n"),
                ("設定を確認します。\n", "設定を確認します。\n")):
            with self.subTest(orig=orig):
                self.assertIsNone(slop_diff.diff(orig, rewrite)["comma_increase"])

    def test_diff_30_引用とコードと表と見出しの中の読点は数えない(self):
        for orig, rewrite in (
                ("「あ、い、う」と言った。\n", "「あ、い、う、え」と言った。\n"),
                ("確認します。\n\n```\na、b\n```\n", "確認します、実際に。\n\n```\na、b、c、d\n```\n"),
                ("| A | B |\n|---|---|\n| x、y | z |\n", "| A | B |\n|---|---|\n| x、y、w | z、v |\n"),
                ("# あ、い、う\n\n本文。\n", "# あ、い、う、え、お\n\n本文。\n"),
                ("「引用です。」と書いた。\n", "「引用です、強調です。」と書いた。\n")):
            with self.subTest(orig=orig):
                self.assertIsNone(slop_diff.diff(orig, rewrite)["comma_increase"])

    def test_diff_31_endingsの検出はtype_marksの追加で変わらない(self):
        # 依頼文を動作文へ書き換えたとき、文末の種類のずれと文の種類の印の両方が出る
        result = slop_diff.diff("設定ファイルを確認してください。\n", "設定ファイルを確認する。\n")
        self.assertEqual(result["endings"]["changes"][0]["orig_kind"], "依頼")
        self.assertEqual(result["endings"]["changes"][0]["rewrite_kind"], "常体")
        lost = [mark["kind"] for entry in result["type_changes"] for mark in entry["lost"]]
        self.assertEqual(lost, ["依頼・決まり"])


class TestSlopDiffReviewFixes(unittest.TestCase):
    """Devin Review 指摘の修正(コード・表の除外、複数行の保護範囲、ソフト改行、複数行 setext)のリグレッション"""

    def test_diff_32_チルダフェンスと先頭パイプなしの表の中の印は出さない(self):
        for orig, rewrite in (
                ("~~~\n原因は設定ミスだとされる。\n~~~\n", "~~~\n原因は設定ミスだ。\n~~~\n"),
                ("```\n原因は設定ミスだとされる。\n```\n", "```\n原因は設定ミスだ。\n```\n"),
                ("原因 | 説明\n---|---\n設定ミスだとされる | 詳細\n", "原因 | 説明\n---|---\n設定ミスだ | 詳細\n"),
                ("| 原因 | 説明 |\n|---|---|\n| とされる | 詳細 |\n", "| 原因 | 説明 |\n|---|---|\n| だ | 詳細 |\n")):
            with self.subTest(orig=orig):
                self.assertEqual(slop_diff.diff(orig, rewrite)["type_changes"], [])
        # 本文の印の変化は引き続き出す
        found = slop_diff.diff("原因は設定ミスだとされる。\n", "原因は設定ミスだ。\n")["type_changes"]
        self.assertEqual([mark["kind"] for entry in found for mark in entry["lost"]], ["伝聞"])

    def test_diff_33_複数行の引用とインラインコードの中の読点は数えない(self):
        for orig, rewrite in (
                ("彼は「これは、\nあれ、それ、どれ」と言った。\n",
                 "彼は「これは、さらに、その、うえ、\nあれ、それ、どれ、あそこ、ここ」と言った。\n"),
                ("`code、span\ncontinues` と本文です。\n",
                 "`code、span、a、b、c\ncontinues、d、e` と本文です。\n")):
            with self.subTest(orig=orig):
                self.assertIsNone(slop_diff.diff(orig, rewrite)["comma_increase"])
        # 引用があっても本文の読点の増加は出す
        result = slop_diff.diff("彼は「はい」と言い、設定を確認し\n実行します。\n",
                                "彼は「はい」と言い、設定を、確認し、\n実行し、記録します。\n")
        item = result["comma_increase"]
        self.assertIsNotNone(item)
        self.assertGreaterEqual(item["new_count"] - item["old_count"], 3)

    def test_diff_34_段落内のソフト改行はつないで一文として数える(self):
        result = slop_diff.diff("設定を確認し\n実行します。\n", "設定を、確認し、\n実行し、記録します。\n")
        item = result["comma_increase"]
        self.assertIsNotNone(item)
        self.assertEqual((item["old_sentences"], item["new_sentences"]), (1, 1))
        self.assertEqual(len(item["sentences"]), 1)
        self.assertEqual(item["sentences"][0]["old"], "設定を確認し実行します。")
        self.assertEqual(item["sentences"][0]["new"], "設定を、確認し、実行し、記録します。")
        self.assertEqual(item["sentences"][0]["old_line"], 1)
        # 句点で終わる別々の文は、ソフト改行でも別文のまま
        result = slop_diff.diff("設定を確認します。\n実行します。\n", "設定を、確認し、実行します。\n実行し、記録します。\n")
        item = result["comma_increase"]
        self.assertIsNotNone(item)
        self.assertEqual((item["old_sentences"], item["new_sentences"]), (2, 2))

    def test_diff_35_複数行のsetext見出しは全行から表示する(self):
        result = slop_diff.diff("見出しの1行目\n2行目は元のままです。\n===\n\n本文。\n",
                                "見出しの1行目\n2行目は書き換えました。\n===\n\n本文。\n")
        self.assertEqual(len(result["heading_shapes"]), 1)
        self.assertEqual(result["heading_shapes"][0]["old"], "見出しの1行目2行目は元のままです。")
        self.assertEqual(result["heading_shapes"][0]["new"], "見出しの1行目2行目は書き換えました。")
        # 変わらなければ出さない
        quiet = slop_diff.diff("見出しの1行目\n2行目は元のままです。\n===\n\n本文。\n",
                               "見出しの1行目\n2行目は元のままです。\n===\n\n本文を直した。\n")
        self.assertEqual(quiet["heading_shapes"], [])
        self.assertFalse(any("見出し" in s for s in quiet["structure"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
