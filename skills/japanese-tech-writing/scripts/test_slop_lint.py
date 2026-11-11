"""slop_lint の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は <対象>-<連番>: MENTION=言及除外、CHAIN=名詞連結、END=文末連続、BASE=既存ルールの維持、
NAKA=中黒並列、LINE=一文一行、HEAD=見出し罫線、MET=比喩動詞、EMOJI=絵文字、
NEG=対比構文、BOLD=太字表示、STRUCT=構造解析移行、STDIO=標準入出力の UTF-8 化、
V2=v1.1.1 Phase 2 の検出強化(語彙パターン、フィラー文単位化、info 文型、絞り込み)、
V3=v1.1.1 Phase 3 のダッシュ3ルール化と否定構文強化、
P2=yomiyasu v3.0.0 Phase 2 の info 系規則14件、
P3=yomiyasu v3.0.0 Phase 3 の calque 型1〜3、
P4=yomiyasu v3.0.0 Phase 4 の JSON 形式2・終了コード・--strict/--fail-on・通常出力。

実行: `python3 test_slop_lint.py`(同ディレクトリから)
"""

import contextlib
import io
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from slop_lint import lint_text, _rule_penalty_score
import slop_lint
from markdown_bold import bold_problems


def rules_of(text: str) -> list:
    return [f["rule"] for f in lint_text(text)["findings"]]


class TestMentionExemption(unittest.TestCase):
    """「」で囲まれた言及は use ではなく mention として検査対象外とする"""

    def test_mention_01_引用例は比喩動詞を検出しない(self):
        self.assertNotIn(
            "metaphor_verb",
            rules_of("「静かに壊れる」という表現は禁止です。"),
        )

    def test_mention_02_引用除去で前後が接合しない(self):
        # 空文字除去だと「静かに壊れる」が誤検出される回帰
        self.assertNotIn(
            "metaphor_verb",
            rules_of("静かに「警告を出しながら」壊れる。"),
        )

    def test_mention_03_実際の引用つき対比は検出する(self):
        # 引用内の語彙は無視しても、実際の ではなく 対比は見直し候補になる
        self.assertIn(
            "negative_parallelism",
            rules_of("「同期」ではなく「非同期」を採用する。"),
        )


class TestNounChain(unittest.TestCase):
    """助詞「の」の名詞連結(過圧縮)検出"""

    def test_chain_01_サ変名詞の数珠つなぎを検出する(self):
        self.assertIn(
            "noun_chain",
            rules_of("保守性担保機能の形骸化の防止の徹底を図ります。"),
        )

    def test_chain_02_自然な連結は検出しない(self):
        self.assertNotIn(
            "noun_chain",
            rules_of("東京の桜の名所の一つを訪れました。"),
        )

    def test_chain_03_先頭候補が不適格でも後続を評価する(self):
        # 最初の連結が閾値未満でも後続の過圧縮を拾う回帰
        self.assertIn(
            "noun_chain",
            rules_of("東京の桜の名所。保守性担保機能の形骸化の防止。"),
        )

    def test_chain_04_格助詞を含む断片は連結とみなさない(self):
        self.assertNotIn(
            "noun_chain",
            rules_of("実装の変更は問題の解決のための手段です。"),
        )

    def test_chain_05_のでの接続は連結とみなさない(self):
        self.assertNotIn(
            "noun_chain",
            rules_of("雨なので傘の確認をしました。"),
        )


class TestSentenceEndRepetition(unittest.TestCase):
    """同一文末の連続検出。見出しの境界マーカーは反復対象ではなく連続数の切り離し"""

    def test_end_01_見出しと箇条書きだけの節が続いても検出しない(self):
        # 境界マーカーを反復文末として数えていた誤判定の回帰
        text = "# A\n\n- x\n\n## B\n\n- y\n\n## C\n\n- z\n"
        self.assertNotIn(
            "sentence_end_repetition",
            rules_of(text),
        )

    def test_end_02_同一文末の三連続は検出する(self):
        text = "値は正しいです。\n形式も正しいです。\n結果も正しいです。\n"
        self.assertIn(
            "sentence_end_repetition",
            rules_of(text),
        )

    def test_end_03_見出しで連続数が切り離される(self):
        text = "値は正しいです。\n形式も正しいです。\n\n## 次の節\n\n結果も正しいです。\n"
        self.assertNotIn(
            "sentence_end_repetition",
            rules_of(text),
        )

    def test_end_04_空行の段落境界で連続数が切り離される(self):
        # 空行を挟んだ別段落は同一文末でも連続と数えない
        text = "値は正しいです。\n形式も正しいです。\n\n結果も正しいです。\nまとめも正しいです。\n"
        self.assertNotIn(
            "sentence_end_repetition",
            rules_of(text),
        )

    def test_end_05_箇条書きなどの除外ブロックを挟んでも数え直す(self):
        text = "値は正しいです。\n形式も正しいです。\n- a\n- b\n結果も正しいです。\n"
        self.assertNotIn(
            "sentence_end_repetition",
            rules_of(text),
        )


class TestMetaphorVerbs(unittest.TestCase):
    """上流で追加された比喩動詞パターンと同一動詞への二重反応の回避"""

    def test_met_01_名詞主語の壊れるを検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("設計が壊れる可能性がある。"),
        )

    def test_met_02_壊れると静かに壊れるは同一動詞に二重反応しない(self):
        findings = lint_text("データが静かに壊れることがある。")["findings"]
        count = sum(1 for f in findings if f["rule"] == "metaphor_verb")
        self.assertEqual(1, count)

    def test_met_03_別動詞の静かに系は重複回避しない(self):
        # 「設計が壊れる」の範囲外にある「静かに失敗」は独立して検出する
        findings = lint_text("設計が壊れると、別の箇所が静かに失敗する。")["findings"]
        count = sum(1 for f in findings if f["rule"] == "metaphor_verb")
        self.assertEqual(2, count)

    def test_met_04_対象名詞への踏み込むを検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("内部実装まで踏み込んで確認する。"),
        )

    def test_met_05_対象外の名詞への踏み込むは検出しない(self):
        self.assertNotIn(
            "metaphor_verb",
            rules_of("議論に踏み込む。"),
        )

    def test_met_06_動かしながら引き返すを検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("動かしながら引き返した。"),
        )

    def test_met_07_代わりに添えるを検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("経路を代わりに添える。"),
        )

    def test_met_08_並置されない添えるは検出しない(self):
        self.assertNotIn(
            "metaphor_verb",
            rules_of("説明を添える。"),
        )

    def test_met_09_主語つきの収斂を検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("議論が収斂するまで待つ。"),
        )

    def test_met_10_収斂は文境界を越えない(self):
        # 主語と「収斂」が別文に分かれている形は対象外
        self.assertNotIn(
            "metaphor_verb",
            rules_of("議論がある。別件で収斂した。"),
        )

    def test_met_11_効くの語尾変化を検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("この修正は地味に効かない。"),
        )

    def test_met_12_効果などの別語は検出しない(self):
        self.assertNotIn(
            "metaphor_verb",
            rules_of("役割が効果を発揮する。"),
        )


class TestEmojiVisibleText(unittest.TestCase):
    """絵文字検査は可視テキストで行い、コードや URL の内部は対象外とする"""

    def test_emoji_01_本文の絵文字は検出する(self):
        self.assertIn(
            "emoji_prohibited",
            rules_of("作業が完了しました。✅"),
        )

    def test_emoji_02_インラインコード内の絵文字は検出しない(self):
        self.assertNotIn(
            "emoji_prohibited",
            rules_of("`check ✅` を実行する。"),
        )

    def test_emoji_03_裸のURL内の絵文字は検出しない(self):
        self.assertNotIn(
            "emoji_prohibited",
            rules_of("詳細は https://example.com/✅ を参照。"),
        )

    def test_emoji_04_リンク宛先と画像の絵文字は検出しない(self):
        self.assertNotIn(
            "emoji_prohibited",
            rules_of("![icon](icon-✅.png) を貼る。"),
        )

    def test_emoji_05_リンク文言の絵文字は検出する(self):
        self.assertIn(
            "emoji_prohibited",
            rules_of("[✅リンク](https://example.com) を参照。"),
        )

    def test_emoji_06_autolink内の絵文字は検出しない(self):
        self.assertNotIn(
            "emoji_prohibited",
            rules_of("<https://example.com/✅> を参照。"),
        )


class TestNegativeParallelism(unittest.TestCase):
    """「A ではなく B」構文の正確な存在判定"""

    def test_neg_01_対比構文は検出する(self):
        self.assertIn(
            "negative_parallelism",
            rules_of("これは手順ではなく、見解です。"),
        )

    def test_neg_02_文頭に孤立したではなくは検出しない(self):
        # 「ではなく」の直前が文区切りなら対比の前項を欠くため対象外
        self.assertNotIn(
            "negative_parallelism",
            rules_of("確認した。ではなく、次へ進む。"),
        )

    def test_neg_03_文末にぶら下がるだけのではなくは検出しない(self):
        self.assertNotIn(
            "negative_parallelism",
            rules_of("確認した。ではなく"),
        )


class TestNakaguroParallel(unittest.TestCase):
    """中黒(・)の日本語並列の検出。整形規範「中黒を日本語の並列で使わない」に対応"""

    def test_naka_01_漢字の並列は検出する(self):
        self.assertIn(
            "nakaguro_parallel",
            rules_of("修正したら確認・遵守してください。"),
        )

    def test_naka_02_カタカナのみの二要素は単一固有名詞として除外する(self):
        self.assertNotIn(
            "nakaguro_parallel",
            rules_of("ウォルト・ディズニーの作品を見た。"),
        )

    def test_naka_03_三要素以上の並列はカタカナでも検出する(self):
        self.assertIn(
            "nakaguro_parallel",
            rules_of("作成・推敲・公開の順で進める。"),
        )

    def test_naka_04_言及の内部の中黒は検出しない(self):
        self.assertNotIn(
            "nakaguro_parallel",
            rules_of("「作成・推敲」は禁止表現の例です。"),
        )

    def test_naka_05_表行の並列も検出する(self):
        self.assertIn(
            "nakaguro_parallel",
            rules_of("| 項目 | 内容 |\n| --- | --- |\n| 変更 | 作成・修正 |"),
        )

    def test_naka_06_インラインコードをまたぐ偽の並列は検出しない(self):
        self.assertNotIn(
            "nakaguro_parallel",
            rules_of("値は `a`・`b` のどちらかを取る。"),
        )

    def test_naka_07_三要素の人名は固有名詞として除外する(self):
        # 規範は単一固有名詞内の中黒を要素数にかかわらず許可する
        self.assertNotIn(
            "nakaguro_parallel",
            rules_of("ジョン・フィッツジェラルド・ケネディを参照する。"),
        )

    def test_naka_08_イニシャルを含む人名も固有名詞として除外する(self):
        self.assertNotIn(
            "nakaguro_parallel",
            rules_of("アーサー・C・クラークの例を挙げる。"),
        )

    def test_naka_09_太字の語を含む並列も検出する(self):
        # 装飾記号の除去を忘れると中黒の前後が * になり並列と認識できない回帰
        self.assertIn(
            "nakaguro_parallel",
            rules_of("**作成**・**推敲**を進める。"),
        )

    def test_naka_10_片側だけ太字の並列も検出する(self):
        self.assertIn(
            "nakaguro_parallel",
            rules_of("**作成**・推敲を進める。"),
        )


class TestOneSentencePerLine(unittest.TestCase):
    """一行に複数の文がある形の検出。整形規範「一文ごとに改行する」に対応"""

    def test_line_01_一行の複数文は検出する(self):
        self.assertIn(
            "one_sentence_per_line",
            rules_of("値は正しいです。形式も正しいです。"),
        )

    def test_line_02_改行済みの複数文は検出しない(self):
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("値は正しいです。\n形式も正しいです。"),
        )

    def test_line_03_言及内の複数文は検出しない(self):
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("「値は正しいです。形式も正しいです」という文を引用する。"),
        )

    def test_line_04_箇条書き内の複数文も検出する(self):
        self.assertIn(
            "one_sentence_per_line",
            rules_of("- 値は正しいです。形式も正しいです。"),
        )

    def test_line_05_文を含まない括弧だけの後続は検出しない(self):
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("値は正しいです。（後述）"),
        )

    def test_line_06_表行の複数文は対象外とする(self):
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("| 項目 | 内容 |\n| --- | --- |\n| 結果 | 正しいです。確認済みです。 |"),
        )

    def test_line_07_脚注参照の後続は一文のままとする(self):
        # 「文。[^脚注]」は一文であり、脚注は規範が推奨する記法
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("値は正しい。[^根拠]"),
        )

    def test_line_08_リンク文言の二文目は検出する(self):
        # リンク文言は表示される文章であり、内部の文は検査対象
        self.assertIn(
            "one_sentence_per_line",
            rules_of("手順を説明します。[詳しく説明します。](https://example.com)"),
        )

    def test_line_09_文中のリンクは一文の一部とする(self):
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("この[手順](https://example.com)を実行します。"),
        )

    def test_line_10_文末の参照リンクは一文のままとする(self):
        # 文の終わりに資料名だけのリンクを添える形は一文扱い
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("詳細は正しいです。[参考](https://example.com)"),
        )

    def test_line_11_文中の画像は一文の一部とする(self):
        # 代替テキストは表示文ではないため、その句点は文数に数えない
        self.assertNotIn(
            "one_sentence_per_line",
            rules_of("これは![画面。](image.png)を示します。"),
        )

    def test_line_12_リンク外の句点で終わる二文目は検出する(self):
        # リンク文言に続けて句点を置く書式の二文目も検査対象
        self.assertIn(
            "one_sentence_per_line",
            rules_of("概要です。[詳細を確認します](https://example.com)。"),
        )


class TestHeadingDecoration(unittest.TestCase):
    """見出しの罫線(U+2500)の検出。整形規範「見出しに区切り線で二要素を詰め込まない」に対応。
    ダッシュ3ルール化に伴い、単独の罫線は dash_decoration として出る"""

    def test_head_01_見出しの罫線は検出する(self):
        self.assertIn(
            "dash_decoration",
            rules_of("# 種別─主題"),
        )

    def test_head_02_本文の罫線も検出する(self):
        self.assertIn(
            "dash_decoration",
            rules_of("種別─主題のように並べない。"),
        )


class TestBoldNotRendered(unittest.TestCase):
    """太字の印(**)が表示されない書き方の検査。上流 test_bold_multiline.py の
    主要ケースを移植したもの。機械の判定は markdown_bold.bold_problems、
    検査結果としての見え方は lint_text の bold_not_rendered で確かめる。"""

    def bold_findings(self, text: str) -> list:
        return [f for f in lint_text(text)["findings"] if f["rule"] == "bold_not_rendered"]

    def test_bold_01_かっこで囲まれた太字は直し方付きで検出する(self):
        problems = bold_problems("次に**「例」**を決めます。")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["how"], "かっこの内側だけを太字にする")
        self.assertIn("「**例**」", problems[0]["suggest"])

    def test_bold_02_検査結果はerrorとして出る(self):
        findings = self.bold_findings("次に**「例」**を決めます。")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "error")
        self.assertEqual(findings[0]["line"], 1)
        self.assertIn("→", findings[0]["snippet"])

    def test_bold_03_通常の太字は検出しない(self):
        self.assertEqual(bold_problems("**定義語**は太字にする。"), [])
        self.assertEqual(self.bold_findings("**定義語**は太字にする。"), [])

    def test_bold_04_複数行にまたがる正常な太字は検出しない(self):
        text = "**太字は1行目から始まり、\n2行目で閉じる。** 続きの文には**別の太字**もある。"
        self.assertEqual(bold_problems(text), [])

    def test_bold_05_複数行太字の交差でも誤検出しない(self):
        text = "**太字は1行目から始まり、\n2行目で閉じる。** 続きの文では**次の太字が始まり、\n3行目で閉じる。**"
        self.assertEqual(bold_problems(text), [])

    def test_bold_06_壊れた複数行太字は検出し改行を保った案を出す(self):
        text = "次に**「太字は1行目から始まり、\n2行目で閉じる。」**を決めます。"
        problems = bold_problems(text)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["line"], 1)
        self.assertEqual(problems[0]["how"], "かっこの内側だけを太字にする")
        self.assertIn("「**太字は1行目から始まり、\n2行目で閉じる。**」", problems[0]["suggest"])

    def test_bold_07_空行をまたいでペアにしない(self):
        self.assertEqual(bold_problems("**段落1で開いたまま\n\n段落2で閉じる。**"), [])

    def test_bold_08_見出しと本文をまたいでペアにしない(self):
        self.assertEqual(bold_problems("# **見出しの太字\n本文で閉じる。**"), [])

    def test_bold_09_リスト項目をまたいでペアにしない(self):
        self.assertEqual(bold_problems("- **リスト1で開き\n- リスト2で閉じる**"), [])

    def test_bold_10_複数行のインラインコード内は検出しない(self):
        self.assertEqual(bold_problems("`code line 1\n**not bold in code**\ncode line 2`"), [])

    def test_bold_11_フェンスコード内は検出しない(self):
        self.assertEqual(bold_problems("```\n**not bold**\n```\n~~~\n**also not bold**\n~~~"), [])

    def test_bold_12_エスケープしたアスタリスクは検出しない(self):
        self.assertEqual(bold_problems(r"\*\*これは太字ではない\*\*"), [])

    def test_bold_13_句読点は太字の外に出す案を出す(self):
        problems = bold_problems("これは**必須です。**詳しくは下に書きます。")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["how"], "句読点を太字の外に出す")
        self.assertIn("**必須です**。", problems[0]["suggest"])

    def test_bold_14_文字に接する側は半角スペースを入れる案を出す(self):
        problems = bold_problems("立場は**「勧め」か「決まり」**で決めます。")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["how"], "文字に接する側に半角スペースを入れる")
        self.assertIn(" **「勧め」か「決まり」** ", problems[0]["suggest"])

    def test_bold_15_開始行を正しく報告する(self):
        text = "1行目\n2行目\n3行目で**「太字が始まり、\n4行目で閉じる。」**のを決めます。"
        problems = bold_problems(text)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["line"], 3)

    def test_bold_16_内側の空白は取る案を出す(self):
        for src, expected in [
            ("** 重要 **", "**重要**"),
            ("次は**重要 **です", "次は**重要**です"),
            ("次は** 重要**です", "次は**重要**です"),
        ]:
            problems = bold_problems(src)
            self.assertEqual(len(problems), 1, f"{src!r} で1件出るはずが {problems}")
            self.assertEqual(problems[0]["how"], "太字の内側の空白を取る")
            self.assertEqual(problems[0]["suggest"], expected)

    def test_bold_17_複数行にまたがる内側空白も検出する(self):
        problems = bold_problems("** 重要\n重要 **")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["how"], "太字の内側の空白を取る")
        self.assertIn("**重要\n重要**", problems[0]["suggest"])

    def test_bold_18_crlf改行でも正常な太字は検出しない(self):
        text = "**太字は1行目から始まり、\r\n2行目で閉じる。** 続きの文には**別の太字**もある。"
        self.assertEqual(bold_problems(text), [])


class TestStructuralScan(unittest.TestCase):
    """analyze_markdown 移行: ブロック種別・保護領域に基づく検査対象の切り分け"""

    def test_struct_01_参照リンク定義の語彙は検出しない(self):
        # [label]: url "title" 形式の参照定義は本文ではなくデータのため語彙検査外
        self.assertNotIn(
            "metaphor_verb",
            rules_of('[ref]: https://example.com "静かに壊れる例の説明"'),
        )

    def test_struct_02_setext見出しも見出しとして扱う(self):
        # === 下線の直前行は ATX 見出しと同じ見出し規則で検査する
        self.assertIn(
            "redundant_bracket",
            rules_of("概要（素の出力）\n===\n本文です。"),
        )

    def test_struct_03_HTMLブロックの語彙は検出しない(self):
        self.assertNotIn(
            "metaphor_verb",
            rules_of("<div>\n<span>これは静かに壊れる例です。</span>\n</div>"),
        )

    def test_struct_04_入れ子引用の語彙は検出しない(self):
        # > > の入れ子引用も例示の可能性が高いため語彙検査の対象外
        self.assertNotIn(
            "metaphor_verb",
            rules_of("> > これは静かに壊れる例です。"),
        )

    def test_struct_05_表行の語彙は検出しない(self):
        self.assertNotIn(
            "metaphor_verb",
            rules_of("| 項目 | 説明 |\n| --- | --- |\n| 例 | 静かに壊れる |"),
        )

    def test_struct_06_URL内部のスロップ語彙は検出しない(self):
        # 裸の URL は不透明領域として空白化される
        self.assertNotIn(
            "metaphor_verb",
            rules_of("詳細は https://example.com/静かに壊れる を参照する。"),
        )

    def test_struct_07_本文の比喩動詞は従来どおり検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("障害時に設定が静かに壊れることがある。"),
        )


class TestExistingRules(unittest.TestCase):
    """言及除外の追加後も既存ルールが維持されること"""

    def test_base_01_引用なしの比喩動詞は検出する(self):
        self.assertIn(
            "metaphor_verb",
            rules_of("この文は静かに壊れるという比喩をそのまま使っています。"),
        )

    def test_base_02_素直な文は指摘しない(self):
        self.assertEqual(
            [],
            rules_of("質の高い文書を心がけます。"),
        )

    def test_base_03_和欧文間の半角空白は指摘しない(self):
        # 規範の改定で空白は許容された。空白検査自体が除去されたことの回帰
        self.assertEqual(
            [],
            rules_of("この README で確認する。"),
        )


SCRIPTS_DIR = Path(__file__).resolve().parent
LINT = SCRIPTS_DIR / "slop_lint.py"

# 上流 test_stdio_encoding.py の SAMPLE と同じ文。Phase 2 で meta_intro が
# 加わったため検出は 4 件(one_sentence_per_line, meta_intro, slop_vocabulary, meta_filler)
SAMPLE = "本記事では、手触りのある設計の本質に迫ります。いかがでしたでしょうか。\n"


def run_cp932(args, stdin=None):
    """標準入出力が cp932 の環境を PYTHONIOENCODING で作って子プロセスを実行する"""
    env = dict(os.environ, PYTHONIOENCODING="cp932:surrogateescape")
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-B"] + [str(a) for a in args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=10,
    )


_KEEP = object()


def run_in_process(script, args, stdin=_KEEP, stdout=_KEEP):
    """標準入出力を TextIOWrapper 以外(StringIO や None)に差し替えて、スクリプトを __main__ として実行する"""
    patches = [mock.patch.object(sys, "argv", [str(script)] + [str(a) for a in args])]
    if stdin is not _KEEP:
        patches.append(mock.patch.object(sys, "stdin", stdin))
    # スクリプトがテストランナー自身の stdout を reconfigure しないよう差し替える
    patches.append(mock.patch.object(sys, "stdout", io.StringIO() if stdout is _KEEP else stdout))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as stop:
            return stop.code or 0
    return 0


class TestV111Phase2(unittest.TestCase):
    """v1.1.1 Phase 2: 形判定語彙、フィラー文単位化、info 文型、リテラル絞り込み"""

    def test_v2_01_ゲートは外来語末尾を避けレビューゲートを検出する(self):
        self.assertIn("slop_vocabulary", rules_of("このレビューゲートを通過する必要があります。"))
        self.assertNotIn("slop_vocabulary", rules_of("目的地までナビゲートします。"))
        # カタログで字義どおりの用法として保持する品質ゲートは検出しない
        self.assertNotIn("slop_vocabulary", rules_of("品質ゲートを設定します。"))

    def test_v2_02_閉包と台帳は定義済み用語を免除する(self):
        self.assertNotIn("slop_vocabulary", rules_of("推移閉包と閉包演算を計算します。"))
        self.assertNotIn("slop_vocabulary", rules_of("会計の台帳を更新します。"))
        self.assertIn("slop_vocabulary", rules_of("すべての判断をこの台帳に記録します。"))

    def test_v2_03_比喩のOS命名を検出する(self):
        self.assertIn("slop_vocabulary", rules_of("意思決定OSとして動作します。"))
        self.assertNotIn("slop_vocabulary", rules_of("対応OS は Windows と Linux です。"))

    def test_v2_04_本質を突くを検出する(self):
        self.assertIn("slop_vocabulary", rules_of("この設計は本質を突いています。"))

    def test_v2_05_拡充フィラーを検出する(self):
        self.assertIn("meta_filler", rules_of("本音を言うと、この設計は複雑です。"))
        self.assertIn("meta_filler", rules_of("ポイントは、速度だけです。"))
        self.assertIn("meta_filler", rules_of("ご質問ありがとうございます。確認します。"))
        self.assertIn("meta_filler", rules_of("必要なら次に説明します。"))
        self.assertIn("meta_filler", rules_of("それでは見ていきましょう。"))

    def test_v2_06_フィラーは文単位で行途中の文頭にも反応する(self):
        # 行単位から文単位への変更。二文目の文頭フィラーも検出する
        self.assertIn("meta_filler", rules_of("確認します。重要なのは、速度です。"))

    def test_v2_07_info文型を検出する(self):
        self.assertIn("meta_intro", rules_of("本記事では、構成を解説します。"))
        self.assertIn("summary_restatement", rules_of("まとめると、速度が重要です。"))
        self.assertIn("summary_restatement", rules_of("総じて、速度が重要です。"))
        self.assertIn("count_declaration", rules_of("ポイントは3つです。"))

    def test_v2_08_もちろん短答を検出し問いへの応答は免除する(self):
        self.assertIn("short_mochiron", rules_of("もちろん、失敗もする。"))
        self.assertNotIn("short_mochiron", rules_of("試してもいいですか。\nもちろん、大丈夫です。"))
        self.assertNotIn("short_mochiron", rules_of("もちろん、構いません。"))

    def test_v2_09_評価語だけの短文連続を検出する(self):
        self.assertIn("fragment_run", rules_of("速い。軽い。安い。"))
        self.assertNotIn("fragment_run", rules_of("速い。軽い。"))

    def test_v2_10_太字ラベル箇条書きは3行以上で検出する(self):
        three = "- **特徴**: 説明文です。\n- **長所**: 説明文です。\n- **短所**: 説明文です。"
        self.assertIn("bold_label_list", rules_of(three))
        two = "- **特徴**: 説明文です。\n- **長所**: 説明文です。"
        self.assertNotIn("bold_label_list", rules_of(two))

    def test_v2_11_短文書のまとめ見出しを検出する(self):
        self.assertIn("short_summary_heading", rules_of("確認する内容を説明します。\n\n## まとめ"))
        self.assertIn("short_summary_heading", rules_of("確認する内容を説明します。\n\n## おわりに"))

    def test_v2_12_info検出はseverityがinfoになる(self):
        findings = lint_text("本記事では、構成を解説します。")["findings"]
        self.assertTrue(all(f["severity"] == "info" for f in findings))

    def test_v2_13_絞り込みなしでも検出結果が同じ(self):
        # _narrowed_document_rows が None に倒れても検出結果は変わらない
        import slop_lint
        text = "本音を言うと、このレビューゲートは本質を突いています。効く設計です。"
        expected = lint_text(text)["findings"]
        with mock.patch.object(slop_lint, "_narrowed_document_rows", return_value=None):
            actual = lint_text(text)["findings"]
        self.assertEqual(
            [(f["rule"], f["line"], f["severity"]) for f in expected],
            [(f["rule"], f["line"], f["severity"]) for f in actual],
        )

    def test_v2_14_波線なしの他なりませんも検出する(self):
        # レビュー指摘: パターンが波線の直前に限られ「要点に他なりません」を
        # 見逃していた。定型句そのものを検出する
        self.assertIn("meta_filler", rules_of("この事実は要点に他なりません。"))
        self.assertIn("meta_filler", rules_of("この事実は〜に他なりません。"))

    def test_v2_15_短文連打は段落内の行をまたいで検出する(self):
        # レビュー指摘: 一文一行の規範では断片は行をまたぐため、
        # 行ごとの句点数では判定に到達しなかった
        self.assertIn("fragment_run", rules_of("速い。\n軽い。\n安い。"))
        self.assertNotIn("fragment_run", rules_of("速い。\n軽い。\n\n安い。"))

    def test_v2_16_まとめ見出しはsetextと閉じATXも検出する(self):
        # レビュー指摘: 「## まとめ」形式だけに一致し、setext や
        # 「## まとめ ##」を見逃していた
        self.assertIn("short_summary_heading",
                      rules_of("確認する内容を説明します。\n\nまとめ\n======"))
        self.assertIn("short_summary_heading",
                      rules_of("確認する内容を説明します。\n\n## まとめ ##"))

    def test_v2_17_行またぎの引用内の短文は断片に数えない(self):
        # レビュー指摘: 行ごとの伏せ字では行をまたぐ「」が残り、
        # 引用内の短文だけで fragment_run が出ていた
        self.assertNotIn("fragment_run",
                         rules_of("手順は「速い。\n軽い。\n安い。」と説明されている。"))
        self.assertNotIn("fragment_run",
                         rules_of("手順は「速い。軽い。安い。」と説明されている。"))
        self.assertIn("fragment_run", rules_of("速い。\n軽い。\n安い。"))

    def test_v2_18_まとめハッシュ連打はまとめ見出しにしない(self):
        # レビュー指摘: 末尾「#」に空白を要求していなかったため
        # 「まとめ###」を見出しと誤認していた
        self.assertNotIn("short_summary_heading",
                         rules_of("確認する内容を説明します。\n\n## まとめ###"))
        self.assertNotIn("short_summary_heading",
                         rules_of("確認する内容を説明します。\n\nまとめ###"))


class TestV111Phase3(unittest.TestCase):
    """v1.1.1 Phase 3: ダッシュ3ルール化と否定構文強化(上流 test_v111_* 系の移植)"""

    def test_v3_01_装飾ダッシュはdash_decorationを出す(self):
        self.assertIn("dash_decoration", rules_of("これは大切な話 — 本当です。"))

    def test_v3_02_ダッシュ挟みの挿入はdash_insertionを出す(self):
        self.assertIn("dash_insertion", rules_of("今日——正確には昨日——連絡しました。"))

    def test_v3_03_読点並べのダッシュ閉じはdash_list_endingを出す(self):
        self.assertIn("dash_list_ending", rules_of("速さ、軽さ、静けさ──。"))

    def test_v3_04_区間ダッシュは検出しない(self):
        self.assertNotIn("dash_decoration", rules_of("新宿—大阪間を移動します。"))
        self.assertNotIn("dash_insertion", rules_of("新宿—大阪間を移動します。"))

    def test_v3_05_出典行と図罫線は検出しない(self):
        self.assertEqual([], rules_of("— 著者: 山田太郎"))
        self.assertEqual([], rules_of("├── src\n│   └── main.py"))

    def test_v3_06_引用内のダッシュは検出しない(self):
        self.assertEqual([], rules_of("「速さ——軽さ」を例として挙げます。"))

    def test_v3_07_ダッシュ指摘は1文書3件まで(self):
        text = "A — 話。\nB — 話。\nC — 話。\nD — 話。\n"
        count = sum(1 for f in lint_text(text)["findings"] if f["rule"].startswith("dash_"))
        self.assertEqual(count, 3)

    def test_v3_08_二度否定して言い切る構文を検出する(self):
        self.assertIn("negative_parallelism", rules_of("車でも、家でもない。有頂天だった。"))

    def test_v3_09_段落内のソフト改行をまたぐ否定構文を検出する(self):
        self.assertIn("negative_parallelism", rules_of("努力ではない。\n才能でもない。\n仕組みだ。"))

    def test_v3_10_じゃないと言い切る構文を検出する(self):
        self.assertIn("negative_parallelism", rules_of("これは努力じゃない、仕組みです。"))

    def test_v3_11_でもあるで終わる対比は検出しない(self):
        self.assertNotIn("negative_parallelism", rules_of("彼は敵ではなく、味方でもある。"))

    def test_v3_12_慣用句や問いへの応答は検出しない(self):
        text = "何でもない。とんでもない。\nいいじゃない、これは君の成果だ。"
        self.assertNotIn("negative_parallelism", rules_of(text))
        self.assertNotIn("negative_parallelism", rules_of("簡単ではない。不可能でもない。"))

    def test_v3_13_否定の多発はdensityを出す(self):
        text = "AではなくBです。\n\nCではなくDです。\n\nEではなくFです。"
        self.assertIn("negative_parallelism_density", rules_of(text))

    def test_v3_14_でもある免除は同行の他の否定構文を潰さない(self):
        # レビュー指摘: 「AではなくBでもある」の免除が elif 連鎖の先頭で
        # 行全体を抑止し、同行の「でもない」「じゃない」を見逃していた
        self.assertIn("negative_parallelism",
                      rules_of("正しいのはAではなくBでもある。Cでも、Dでもない。Eだ。"))
        self.assertIn("negative_parallelism",
                      rules_of("正しいのはAではなくBでもある。これは努力じゃない、仕組みです。"))
        self.assertNotIn("negative_parallelism", rules_of("正しいのはAではなくBでもある。"))

    def test_v3_15_段落走査は行またぎの言及も伏せる(self):
        # レビュー指摘: 段落連結後の走査が「」内の言及を伏せておらず、
        # 引用として書いた否定構文の例を誤検出し得た
        self.assertNotIn("negative_parallelism",
                         rules_of("規範では「Aでも、\nBでもない。」と書く。実際はCだ。"))
        self.assertIn("negative_parallelism", rules_of("Aでも、\nBでもない。Cだ。"))

    def test_v3_16_経路マスクは間線便を含む普通名詞を誤認しない(self):
        # レビュー指摘: 「中間結果」「配線」のような普通名詞まで
        # 区間接尾辞とみなしてダッシュ指摘を伏せていた
        self.assertIn("dash_insertion", rules_of("結果—中間結果—を確認する。"))
        self.assertIn("dash_insertion", rules_of("装置—配線—の確認。"))
        self.assertIn("dash_insertion", rules_of("明日—郵便—で送る。"))
        self.assertNotIn("dash_decoration", rules_of("新宿—大阪間を移動します。"))
        self.assertNotIn("dash_decoration", rules_of("東京—山手線で移動します。"))
        self.assertNotIn("dash_decoration", rules_of("昼便—夜行便を利用します。"))


class TestStdioEncoding(unittest.TestCase):
    """標準入出力が cp932 の環境でも UTF-8 で読み書きする(上流 test_stdio_encoding.py の移植)"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="slop-stdio-", dir=".")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def assert_ascii_json(self, process):
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        self.assertTrue(process.stdout.isascii(), "--json の出力は ASCII だけにする")
        return json.loads(process.stdout.decode("ascii"))

    def test_stdio_01_utf8の標準入力はファイル指定と同じ結果になる(self):
        path = self.write("sample.md", SAMPLE)
        from_file = self.assert_ascii_json(run_cp932([LINT, path, "--json"]))
        from_stdin = self.assert_ascii_json(run_cp932([LINT, "--json"], SAMPLE.encode("utf-8")))
        self.assertEqual(from_stdin, from_file)
        self.assertEqual(from_stdin["metrics"]["char_count"], 35)
        self.assertEqual(len(from_stdin["findings"]), 4)

    def test_stdio_02_utf8の標準入力でもstrictの終了コード1になる(self):
        process = run_cp932([LINT, "--strict"], SAMPLE.encode("utf-8"))
        self.assertEqual(process.returncode, 1, process.stderr.decode("utf-8", "replace"))
        self.assertEqual(process.stderr, b"")

    def test_stdio_03_utf8でない標準入力は終了コード2で拒否する(self):
        process = run_cp932([LINT, "--json"], SAMPLE.encode("cp932"))
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, b"")
        self.assertIn(b"Error reading stdin", process.stderr)

    def test_stdio_04_絵文字を含む指摘をcp932で落ちずに報告する(self):
        path = self.write("emoji.md", "🚀 設定ファイルを更新しました。\n")
        report = run_cp932([LINT, path])
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        self.assertIn("🚀", report.stdout.decode("utf-8"))
        result = self.assert_ascii_json(run_cp932([LINT, path, "--json"]))
        self.assertIn("🚀", result["findings"][0]["message"])

    def test_stdio_05_ダッシュを含む抜粋をcp932で落ちずに報告する(self):
        path = self.write("dash.md", "手触りのある設計です — いかがでしたでしょうか。\n")
        report = run_cp932([LINT, path])
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        self.assertIn("—", report.stdout.decode("utf-8"))
        result = self.assert_ascii_json(run_cp932([LINT, path, "--json"]))
        snippets = [f["snippet"] for f in result["findings"]]
        self.assertTrue(any("—" in s for s in snippets))


class TestYomiyasuV3Phase2(unittest.TestCase):
    """yomiyasu v3.0.0 Phase 2: info 系規則14件(上流 test_v2xx 系からの選択的移植)

    --doc-type を持たないため、上流で種類を限る規則(pause_comma、dialogue_period、
    narrative_density)も info の常時検出とする(Y-20)。project_term は .yomiyasu-words/
    の既定ファイルがないため、words を直接渡して検査する。検出例・非検出例は上流テストの類例。
    """

    FILLER = ("これは、みんなにくばる、ためしのぶんしょうです。よんでから、つぎのところへすすんでください。"
              "わからないところは、あとでききます。")
    LABEL_BODY = ("同じ顧客が同じ内容で24時間以内に送った問い合わせは、1件にまとめました。"
                  "区分は、受け付けた担当者が付けたものをそのまま使い、付け忘れの312件だけを集計の担当が読んで付け直しました。")
    WORDS = {"path": "/x", "allow": (), "flag": ("根の",), "allow_lines": 0,
             "flag_lines": 1, "allow_sha256": None, "flag_sha256": "0" * 64}

    def findings(self, text, words=None):
        return lint_text(text, words=words)["findings"]

    def rules(self, text, words=None):
        return [f["rule"] for f in self.findings(text, words=words)]

    def severities(self, rule, text, words=None):
        return [f["severity"] for f in self.findings(text, words=words) if f["rule"] == rule]

    # ai_phrase
    def test_p2_01_AIの言い回しをinfoで検出する(self):
        text = "今回の結果は、市場が回復に向かうという見立てです。\n"
        self.assertIn("ai_phrase", self.rules(text))
        self.assertEqual(self.severities("ai_phrase", text), ["info"])

    def test_p2_02_人の見立ては検出しない(self):
        self.assertNotIn("ai_phrase", self.rules("医師の見立てでは、軽い風邪です。\n"))

    # renyo_noun
    def test_p2_03_サ変名詞の連用形をinfoで検出する(self):
        text = "出した数字は、表の値との確かめが済んでいません。\n"
        self.assertIn("renyo_noun", self.rules(text))
        self.assertEqual(self.severities("renyo_noun", text), ["info"])

    def test_p2_04_辞書形は検出しない(self):
        self.assertNotIn("renyo_noun", self.rules("表の値との確認が済んでいません。\n"))

    # project_term
    def test_p2_05_語彙リストのflag語をinfoで検出する(self):
        text = "木の根の張り方を調べます。\n"
        self.assertIn("project_term", self.rules(text, self.WORDS))
        self.assertEqual(self.severities("project_term", text, self.WORDS), ["info"])

    def test_p2_06_allowの語は検出しない(self):
        words = dict(self.WORDS, allow=("根の",), allow_lines=1)
        self.assertNotIn("project_term", self.rules("木の根の張り方を調べます。\n", words))

    def test_p2_07_熟語の内部は検出しない(self):
        # 「大根」「箱根」のような漢字複合語の内部では当たらない(上流の境界規則)
        self.assertNotIn("project_term", self.rules("大根の煮物を作りました。\n", self.WORDS))
        self.assertNotIn("project_term", self.rules("箱根の宿に泊まりました。\n", self.WORDS))

    def test_p2_08_語彙リストがなければ検出しない(self):
        self.assertNotIn("project_term", self.rules("木の根の張り方を調べます。\n"))

    # thin_evaluation
    def test_p2_09_中身の薄い評価をinfoで検出する(self):
        text = "委託先の回答の品質も高いです。\n"
        self.assertIn("thin_evaluation", self.rules(text))
        self.assertEqual(self.severities("thin_evaluation", text), ["info"])

    def test_p2_10_数値の根拠がある評価は検出しない(self):
        self.assertNotIn("thin_evaluation",
                         self.rules("消費電力は従来品の9ワットから6ワットに下がり、省エネ性能が高くなりました。\n"))

    # katakana_term
    def test_p2_11_意味の薄いカタカナ語をinfoで検出する(self):
        text = "顧客とのエンゲージメントを高めることも課題です。\n"
        self.assertIn("katakana_term", self.rules(text))
        self.assertEqual(self.severities("katakana_term", text), ["info"])

    def test_p2_12_言及の中のカタカナ語は検出しない(self):
        self.assertNotIn("katakana_term",
                         self.rules("ポータルは、すでに全社で使っている「サクラ業務プラットフォーム」の上に作ります。\n"))

    # metaphor_label
    def label_document(self, heading, body):
        return "# 社内の資料\n\n{}\n\n{}\n\n{}\n".format(heading, body, self.FILLER)

    def test_p2_13_見出しの比喩ラベルをinfoで検出する(self):
        text = self.label_document("## 数え係", self.LABEL_BODY)
        self.assertIn("metaphor_label", self.rules(text))
        self.assertEqual(self.severities("metaphor_label", text), ["info"])

    def test_p2_14_普通の見出しは検出しない(self):
        text = self.label_document("## 件数の推移", self.LABEL_BODY)
        self.assertNotIn("metaphor_label", self.rules(text))

    # say_hedge
    def test_p2_15_と言えるでしょうの文末をinfoで検出する(self):
        text = "7月以降の増加は、定期便の開始が主な原因だったと言えるでしょう。\n"
        self.assertIn("say_hedge", self.rules(text))
        self.assertEqual(self.severities("say_hedge", text), ["info"])

    def test_p2_16_引用の中のと言えるでしょうは検出しない(self):
        self.assertNotIn("say_hedge", self.rules("「これは一生ものと言えるでしょう」というお便りも届いています。\n"))

    # narrative_density / dialogue_period(上流は doc-type 限定。ここでは常時 info で出る)
    NARRATIVE_TEXT = (
        "導入の手順について説明します。" * 3 + "\n\n"
        + "\n".join("- 設定値は{}で、確認項目は{}件です。".format(100 + i, 20 + i) for i in range(1, 16)) + "\n\n"
        + "各手順の結果は表にまとめ、差分が10%以上あれば再測定します。測定は3回ずつ行い、中央値を採用します。"
        "値が前回比で5%を超えて変わった場合は、設定の見直し対象とします。" * 8
    )

    def test_p2_17_読み物の一人称と数字の密度をinfoで検出する(self):
        text = self.NARRATIVE_TEXT + "\n"
        self.assertIn("narrative_density", self.rules(text))
        self.assertEqual(self.severities("narrative_density", text), ["info"])

    def test_p2_18_一人称の多い読み物は検出しない(self):
        text = self.NARRATIVE_TEXT.replace(
            "各手順の結果は", "私はこの手順を何度も試しました。私の経験では、各手順の結果は") + "\n"
        self.assertNotIn("narrative_density", self.rules(text))

    def test_p2_19_句点で終わる台詞の連続をinfoで検出する(self):
        text = "\n".join("「確認{}が済みました。」".format(i) for i in range(1, 11)) + "\n"
        self.assertIn("dialogue_period", self.rules(text))
        self.assertEqual(self.severities("dialogue_period", text), ["info"])

    def test_p2_20_句点で終わらない台詞は検出しない(self):
        text = "\n".join("「確認{}が済みました」".format(i) for i in range(1, 11)) + "\n"
        self.assertNotIn("dialogue_period", self.rules(text))

    # copy_comma_noun / bare_verb_chain(文の形の規則)
    def test_p2_21_名詞を並べる読点をinfoで検出する(self):
        text = "丁寧な、人。\n"
        self.assertIn("copy_comma_noun", self.rules(text))
        self.assertEqual(self.severities("copy_comma_noun", text), ["info"])

    def test_p2_22_副詞の読点は検出しない(self):
        self.assertNotIn("copy_comma_noun", self.rules("彼は、毎朝、コーヒーを飲みます。\n"))

    def test_p2_23_動詞だけを並べる文をinfoで検出する(self):
        text = "切るか、続けるか、決める。\n"
        self.assertIn("bare_verb_chain", self.rules(text))
        self.assertEqual(self.severities("bare_verb_chain", text), ["info"])

    def test_p2_24_主語や目的語のある動詞の連なりは検出しない(self):
        self.assertNotIn("bare_verb_chain",
                         self.rules("開発者が書き、CI が組み立て、レビュー担当が確かめる。\n"))

    # cleft_list_ending
    def test_p2_25_のはのあとの名詞並べをinfoで検出する(self):
        text = "書き換えの中で変動したのは、画面、帳票、通知。\n"
        self.assertIn("cleft_list_ending", self.rules(text))
        self.assertEqual(self.severities("cleft_list_ending", text), ["info"])

    def test_p2_26_述語まで書いた文は検出しない(self):
        self.assertNotIn("cleft_list_ending", self.rules("変わったのは、画面、帳票、通知です。\n"))

    # instruction_residue
    def test_p2_27_AIへの指示残りをinfoで検出する(self):
        text = "今回は一般論ではなく、自分の体験に絞って紹介します。\n"
        self.assertIn("instruction_residue", self.rules(text))
        self.assertEqual(self.severities("instruction_residue", text), ["info"])

    def test_p2_28_読者の対象を示す文は検出しない(self):
        self.assertNotIn("instruction_residue",
                         self.rules("この記事は、Docker を一度は使ったことがある人を対象にしています。\n"))

    # pause_comma
    def test_p2_29_短い主題のあとの読点をinfoで検出する(self):
        text = "受付の窓口には、来月から一人増やします。\n"
        self.assertIn("pause_comma", self.rules(text))
        self.assertEqual(self.severities("pause_comma", text), ["info"])

    def test_p2_30_長い主題の読点は検出しない(self):
        self.assertNotIn("pause_comma", self.rules("夜のうちに届いた荷物や手紙は、朝の便でまとめて配ります。\n"))

    # 語の一覧の allow.txt は既存の規則の候補も外せる(候補の内部の欄 _words で照合する)
    def test_p2_31_allowの語で比喩動詞の候補を外す(self):
        words = {"path": "/x", "allow": ("静かに壊れる",), "flag": (), "allow_lines": 1,
                 "flag_lines": 0, "allow_sha256": None, "flag_sha256": "0" * 64}
        text = "この処理は静かに壊れることがあります。\n"
        self.assertIn("metaphor_verb", self.rules(text))
        self.assertNotIn("metaphor_verb", self.rules(text, words))

    def test_p2_32_allowの語でスロップ語彙の候補を外す(self):
        words = {"path": "/x", "allow": ("体温", "思考のOS"), "flag": (), "allow_lines": 2,
                 "flag_lines": 0, "allow_sha256": None, "flag_sha256": "0" * 64}
        # 語そのものの候補と、型の語(〜のOS)の候補の両方が外れる
        self.assertIn("slop_vocabulary", self.rules("体温を測ります。\n"))
        self.assertNotIn("slop_vocabulary", self.rules("体温を測ります。\n", words))
        self.assertIn("slop_vocabulary", self.rules("これは思考のOSです。\n"))
        self.assertNotIn("slop_vocabulary", self.rules("これは思考のOSです。\n", words))
        # 語の一部(「OS」)では外れない
        partial = dict(words, allow=("OS",), allow_lines=1)
        self.assertIn("slop_vocabulary", self.rules("これは思考のOSです。\n", partial))

    # 「」が行をまたぐときも、対になった中身は引用として伏せる
    def test_p2_33_複数行のカギ括弧の中は検出しない(self):
        text = "次の言い回しは使いません。\n「エンゲージメント\nを高める手法」は旧来の表現です。\n"
        self.assertNotIn("katakana_term", self.rules(text))
        # 対照: 引用の外にある同じ語は検出する
        self.assertIn("katakana_term", self.rules("エンゲージメントを高める手法を使います。\n"))

    def test_p2_34_複数行のカギ括弧の中のflag語は検出しない(self):
        text = "調べます。\n「木の根の\n張り方」は例です。\n"
        self.assertNotIn("project_term", self.rules(text, self.WORDS))
        # 対照: 引用の外にある同じ語は検出する
        self.assertIn("project_term", self.rules("調べます。\n木の根の張り方を調べます。\n", self.WORDS))

    # 許可した語と未許可の語が同じ行の同じ型に共存するとき、候補は残る(全一致が許可されたときだけ外す)
    def test_p2_35_同じ行に許可済みと未許可の型の語があるとき候補を残す(self):
        words = {"path": "/x", "allow": ("思考のOS",), "flag": (), "allow_lines": 1,
                 "flag_lines": 0, "allow_sha256": None, "flag_sha256": "0" * 64}
        text = "これは思考のOSと仕事のOSです。\n"
        self.assertIn("slop_vocabulary", self.rules(text))
        # 「思考のOS」だけを許可しても、未許可の「仕事のOS」が残るので候補は消えない
        self.assertIn("slop_vocabulary", self.rules(text, words))
        # 両方を許可すれば候補は外れる
        both = dict(words, allow=("思考のOS", "仕事のOS"), allow_lines=2)
        self.assertNotIn("slop_vocabulary", self.rules(text, both))

    def test_p2_36_同じ行に許可済みと未許可の比喩動詞があるとき候補を残す(self):
        words = {"path": "/x", "allow": ("静かに壊れ",), "flag": (), "allow_lines": 1,
                 "flag_lines": 0, "allow_sha256": None, "flag_sha256": "0" * 64}
        text = "この処理は静かに壊れ、静かに落ちることがあります。\n"
        self.assertIn("metaphor_verb", self.rules(text))
        # 「静かに壊れ」だけを許可しても、未許可の「静かに落ち」が残るので候補は消えない
        self.assertIn("metaphor_verb", self.rules(text, words))
        both = dict(words, allow=("静かに壊れ", "静かに落ち"), allow_lines=2)
        self.assertNotIn("metaphor_verb", self.rules(text, both))

    # 「壊れる」パターンが1行に複数あるとき、2つ目以降の「静かに壊れ」も二重反応の除外対象にする
    def test_p2_37_同じ行の二つの静かに壊れるは二重検出しない(self):
        text = "データが静かに壊れ、仕様が静かに壊れる。\n"
        hits = [f for f in self.findings(text) if f["rule"] == "metaphor_verb"]
        # 比喩動詞「壊れる」の1件だけ(英語直訳「静かに壊れる」は二重反応として出ない)
        self.assertEqual(len(hits), 1)
        self.assertIn("壊れる", hits[0]["message"])


class TestYomiyasuV3Phase3(unittest.TestCase):
    """yomiyasu v3.0.0 Phase 3 の calque 型1〜3(info)と語彙リストとの整合。

    文例は上流 tests/test_v220_a1.py の CALQUE_FIX/CALQUE_KEEP の類例。"""

    def findings(self, text, words=None):
        return lint_text(text, words=words)["findings"]

    def rules(self, text, words=None):
        return [f["rule"] for f in self.findings(text, words)]

    def calques(self, text, words=None):
        return [f for f in self.findings(text, words) if f["rule"] == "calque"]

    def severities(self, rule, text, words=None):
        return [f["severity"] for f in self.findings(text, words) if f["rule"] == rule]

    def words(self, **kw):
        base = {"path": "/x", "allow": (), "flag": (), "allow_lines": 0,
                "flag_lines": 0, "allow_sha256": None, "flag_sha256": None}
        base.update(kw)
        return base

    # 型1: 機械やシステムが主語で人の動作の動詞
    def test_p3_01_型1の機械主語の動詞を検出する(self):
        text = "取りこぼした通知は、翌朝の再送ジョブが拾います。\n"
        hits = self.calques(text)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["severity"], "info")
        self.assertIn("型1", hits[0]["message"])
        self.assertIn("拾う", hits[0]["message"])

    def test_p3_02_型1の定着した言い方は検出しない(self):
        self.assertEqual(self.calques("すべてのテストが通ったら、レビューを依頼してください。\n"), [])
        self.assertEqual(self.calques("2回目からはキャッシュが効くので、同じ一覧は50ミリ秒ほどで返ります。\n"), [])

    def test_p3_03_型1は人の主語と名詞修飾を検出しない(self):
        self.assertEqual(self.calques("サーバー管理者が、毎朝ログを拾います。\n"), [])
        self.assertEqual(self.calques("担当者は、ジョブが拾った通知を確かめます。\n"), [])

    # 型2: 場所のたとえの名詞
    def test_p3_04_型2の受け口を検出する(self):
        text = "外部からの注文データは、すべてこの受け口に届きます。\n"
        hits = self.calques(text)
        self.assertEqual(len(hits), 1)
        self.assertIn("型2", hits[0]["message"])
        self.assertIn("受け口", hits[0]["message"])

    def test_p3_05_型2の入口は技術語がある文で検出する(self):
        text = "社外からの接続は、この入口を通ります。\n"
        hits = self.calques(text)
        self.assertEqual(len(hits), 1)
        self.assertIn("型2", hits[0]["message"])
        self.assertIn("入口", hits[0]["message"])

    def test_p3_06_型2の実物の場所と定着した先は検出しない(self):
        self.assertEqual(self.calques("本社ビルの正面入口は、工事のため11月末まで閉じています。\n"), [])
        self.assertEqual(self.calques("このパッケージの依存先は、`package.json` の `dependencies` に書いてあります。\n"), [])

    # 型3: 英語の言い方を一語ずつ写した句
    def test_p3_07_型3の句を検出する(self):
        text = "新しい鍵に替えると、古い鍵の失効が効きます。\n"
        hits = self.calques(text)
        self.assertEqual(len(hits), 1)
        self.assertIn("型3", hits[0]["message"])
        self.assertIn("失効が効く", hits[0]["message"])

    def test_p3_08_型3の別の句を検出する(self):
        text = "この変更には、足すものがありません。\n"
        hits = self.calques(text)
        self.assertEqual(len(hits), 1)
        self.assertIn("足すものがない", hits[0]["message"])

    def test_p3_09_型3は文字どおりの効くを検出しない(self):
        self.assertEqual(self.calques("この薬は、寝る前に飲むときに効きます。\n"), [])
        self.assertEqual(self.calques("雨の日はブレーキが効きにくくなるため、車間を広めに取ってください。\n"), [])

    # 1行に複数の型は1件にまとめ、型名と言い方を並べる
    def test_p3_10_1行の二つの型は一件で型名と言い方を並べる(self):
        text = "外部からの注文は、この受け口に届き、夜間の集計バッチが拾います。\n"
        hits = self.calques(text)
        self.assertEqual(len(hits), 1)
        self.assertIn("型1", hits[0]["message"])
        self.assertIn("型2", hits[0]["message"])
        self.assertIn("拾う", hits[0]["message"])
        self.assertIn("受け口", hits[0]["message"])

    # 同じ行に metaphor_verb の候補があれば calque を出さない
    def test_p3_11_同じ行の比喩動詞はcalqueを出さない(self):
        text = "データが静かに壊れても、再送ジョブが拾います。\n"
        self.assertIn("metaphor_verb", self.rules(text))
        self.assertNotIn("calque", self.rules(text))
        # 対照: 比喩動詞のない行では calque が出る
        self.assertIn("calque", self.rules("届かなくても、再送ジョブが拾います。\n"))

    # 語彙リストとの整合
    def test_p3_12_allowの語ですべての言い方を外せる(self):
        text = "取りこぼした通知は、翌朝の再送ジョブが拾います。\n"
        words = self.words(allow=("拾う",), allow_lines=1)
        self.assertNotIn("calque", self.rules(text, words))

    def test_p3_13_allowは残りの言い方でmessageを作り直す(self):
        text = "外部からの注文は、この受け口に届き、夜間の集計バッチが拾います。\n"
        words = self.words(allow=("拾う",), allow_lines=1)
        hits = self.calques(text, words)
        self.assertEqual(len(hits), 1)
        self.assertIn("型2", hits[0]["message"])
        self.assertIn("受け口", hits[0]["message"])
        self.assertNotIn("拾う", hits[0]["message"])
        self.assertNotIn("型1", hits[0]["message"])

    def test_p3_14_flagの語はcalqueを外さずproject_termを別に出す(self):
        text = "社外からの接続は、この入口を通ります。\n"
        words = self.words(flag=("入口",), flag_lines=1, flag_sha256="0" * 64)
        rules = self.rules(text, words)
        self.assertIn("calque", rules)
        self.assertIn("project_term", rules)

    def test_p3_15_flag_patternもcalqueを外さない(self):
        text = "外部からの注文データは、すべてこの受け口に届きます。\n"
        pattern = ("テスト用パターン", r"受け口", re.compile(r"受け口"), (("受け口",),))
        words = self.words(flag_patterns=(pattern,), flag_patterns_lines=1, flag_patterns_sha256="0" * 64)
        rules = self.rules(text, words)
        self.assertIn("calque", rules)
        self.assertIn("project_term", rules)
        # パターンの名前を allow.txt に書くと project_term だけが外れ、calque は残る
        allowed = self.words(allow=("テスト用パターン",), allow_lines=1,
                             flag_patterns=(pattern,), flag_patterns_lines=1, flag_patterns_sha256="0" * 64)
        rules = self.rules(text, allowed)
        self.assertIn("calque", rules)
        self.assertNotIn("project_term", rules)


class TestYomiyasuV3Phase4(unittest.TestCase):
    """yomiyasu v3.0.0 Phase 4: JSON 形式2、終了コード、--strict/--fail-on、通常出力。
    仕様の根拠は docs/implementation-plan-yomiyasu-v3-port.md の Phase 4 と
    docs/decision-records.md の Y-19・Y-20。"""

    CLEAN = "質の高い文書を心がけます。\n"
    INFO_ONLY = "本記事では、構成を解説します。\n"  # meta_intro(info)だけが出る
    ERROR_TEXT = "次に**「例」**を決めます。\n"  # bold_not_rendered(error)が出る

    # JSON 形式(形式2)

    def test_p4_01_候補なしのJSONは形式2のキーを持ち旧キーを持たない(self):
        result = lint_text(self.CLEAN)
        self.assertEqual(result["format"], "yomiyasu-lint")
        self.assertEqual(result["format_version"], 2)
        self.assertTrue(result["tool_version"])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["counts"], {"error": 0, "warn": 0, "info": 0})
        self.assertTrue(result["no_rule_findings"])
        self.assertEqual(result["rule_penalty_score"], 100)
        self.assertEqual(result["not_judged"], ["meaning_preservation", "reader_comprehension"])
        self.assertEqual(result["context"], {})
        self.assertIn("metrics", result)
        self.assertEqual(result["findings"], [])
        # 旧形式のキーは残さない
        self.assertNotIn("score", result)
        self.assertNotIn("is_clean", result)

    def test_p4_02_候補ありのJSONは件数と内訳が一致する(self):
        result = lint_text(SAMPLE)
        self.assertEqual(result["candidate_count"], 4)
        self.assertEqual(result["counts"], {"error": 0, "warn": 3, "info": 1})
        self.assertFalse(result["no_rule_findings"])
        self.assertLess(result["rule_penalty_score"], 100)
        self.assertGreaterEqual(result["rule_penalty_score"], 1)
        self.assertEqual(len(result["findings"]), 4)

    def test_p4_03_CLIのJSON出力も形式2である(self):
        out = io.StringIO()
        code = run_in_process(LINT, ["--json"], stdin=io.StringIO(SAMPLE), stdout=out)
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["format_version"], 2)
        self.assertEqual(result["candidate_count"], 4)
        self.assertNotIn("score", result)

    # rule_penalty_score

    def test_p4_04_点数に入れない規則だけなら100(self):
        # ai_phrase は上流 2.5.0 の規則で、点数を計算する前に除く
        result = lint_text("今回の結果は、市場が回復に向かうという見立てです。\n")
        self.assertIn("ai_phrase", [f["rule"] for f in result["findings"]])
        self.assertEqual(result["rule_penalty_score"], 100)

    def test_p4_05_ダッシュの非表示分も点数に数える(self):
        # 表示は1文書3件までだが、点数には4件目以降も数える
        dash3 = lint_text("A — 話。\nB — 話。\nC — 話。\n")
        dash4 = lint_text("A — 話。\nB — 話。\nC — 話。\nD — 話。\n")
        self.assertEqual(dash3["candidate_count"], 3)
        self.assertEqual(dash4["candidate_count"], 3)
        self.assertLess(dash4["rule_penalty_score"], dash3["rule_penalty_score"])

    def test_p4_06_点数の式は上流と同じ(self):
        # 上流の式: 100 × 40 ÷ (40 + x) を丸める。x は行の候補の重みを地の文1,000字あたりに
        # 直した数。warn 1件・地の文1,000字なら x=2 で 100×40÷42≒95.2 → 95
        finding = {"rule": "metaphor_verb", "line": 1, "severity": "warn",
                   "message": "", "snippet": ""}
        self.assertEqual(_rule_penalty_score([finding], 1000, 0), 95)
        # 候補がなければ100、文書が短くても分母は1,000字として割る
        self.assertEqual(_rule_penalty_score([], 100, 0), 100)

    # 終了コードと --strict/--fail-on

    def test_p4_07_strictはwarnかerrorで1でinfoだけなら0(self):
        self.assertEqual(run_in_process(LINT, ["--strict"], stdin=io.StringIO(SAMPLE), stdout=io.StringIO()), 1)
        self.assertEqual(run_in_process(LINT, ["--strict"], stdin=io.StringIO(self.INFO_ONLY), stdout=io.StringIO()), 0)
        self.assertEqual(run_in_process(LINT, ["--strict"], stdin=io.StringIO(self.CLEAN), stdout=io.StringIO()), 0)

    def test_p4_08_fail_onは指定した重さの候補で1になる(self):
        # warn のみの SAMPLE: --fail-on=error は 0、--fail-on=warn は 1
        self.assertEqual(run_in_process(LINT, ["--fail-on=error"], stdin=io.StringIO(SAMPLE), stdout=io.StringIO()), 0)
        self.assertEqual(run_in_process(LINT, ["--fail-on=warn"], stdin=io.StringIO(SAMPLE), stdout=io.StringIO()), 1)
        # error を含む文は両方で 1
        self.assertEqual(run_in_process(LINT, ["--fail-on=error"], stdin=io.StringIO(self.ERROR_TEXT), stdout=io.StringIO()), 1)
        self.assertEqual(run_in_process(LINT, ["--fail-on=warn"], stdin=io.StringIO(self.ERROR_TEXT), stdout=io.StringIO()), 1)

    def test_p4_09_fail_onの値は大文字とカンマ区切りと繰り返しを受ける(self):
        self.assertEqual(run_in_process(LINT, ["--fail-on=WARN,error"], stdin=io.StringIO(SAMPLE), stdout=io.StringIO()), 1)
        self.assertEqual(run_in_process(LINT, ["--fail-on=warn", "--fail-on=error"],
                                        stdin=io.StringIO(SAMPLE), stdout=io.StringIO()), 1)

    def test_p4_10_使えないfail_onの値は終了コード2(self):
        for value in ("info", "meaning_risk_extra"):
            with self.subTest(value=value):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = run_in_process(LINT, ["--fail-on=" + value], stdin=io.StringIO(self.CLEAN), stdout=io.StringIO())
                self.assertEqual(code, 2)
                self.assertIn("--fail-on に使えない値です", stderr.getvalue())

    def test_p4_11_meaning_riskは専用の文で終了コード2(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_in_process(LINT, ["--fail-on=meaning-risk"], stdin=io.StringIO(self.CLEAN), stdout=io.StringIO())
        self.assertEqual(code, 2)
        self.assertIn("slop_diff.py", stderr.getvalue())

    def test_p4_12_条件に当たった終了コード1の行を通常出力に足す(self):
        out = io.StringIO()
        code = run_in_process(LINT, ["--strict"], stdin=io.StringIO(SAMPLE), stdout=out)
        self.assertEqual(code, 1)
        self.assertIn("終了コード1: --strict の条件", out.getvalue())

    def test_p4_13_使えないオプションは終了コード2(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_in_process(LINT, ["--unknown-option"], stdin=io.StringIO(self.CLEAN), stdout=io.StringIO())
        self.assertEqual(code, 2)

    # 通常出力

    def test_p4_14_通常出力は上流の形式で点数を出さない(self):
        out = io.StringIO()
        code = run_in_process(LINT, [], stdin=io.StringIO(SAMPLE), stdout=out)
        self.assertEqual(code, 0)
        lines = out.getvalue().split("\n")
        self.assertEqual(lines[0], "表現・書式の検査を実行しました。")
        self.assertEqual(lines[1], "見直し候補: 4件")
        self.assertEqual(lines[2], "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。")
        self.assertIn("内訳: error 0件、warn 3件、info 1件", out.getvalue())
        self.assertIn("L1 [WARN] one_sentence_per_line: ", out.getvalue())
        self.assertIn("  > ", out.getvalue())
        self.assertNotIn("スコア", out.getvalue())

    def test_p4_15_候補なしの通常出力は見出し3行だけ(self):
        out = io.StringIO()
        code = run_in_process(LINT, [], stdin=io.StringIO(self.CLEAN), stdout=out)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip().split("\n"), [
            "表現・書式の検査を実行しました。",
            "見直し候補: 0件",
            "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
        ])

    # 語の一覧と内部エラー

    def test_p4_16_語の一覧のcontextがJSONに入る(self):
        words = {"path": "/x", "allow": ("手触り",), "flag": (), "allow_lines": 1, "flag_lines": 0,
                 "allow_sha256": None, "flag_sha256": "0" * 64}
        result = lint_text(SAMPLE, words=words)
        self.assertIn("words", result["context"])
        self.assertEqual(result["context"]["words"]["allow_removed"]["slop_vocabulary"], 1)
        # allow で外れた候補は件数に入らない
        self.assertEqual(result["candidate_count"], 3)

    def test_p4_17_内部エラーは終了コード3(self):
        stderr = io.StringIO()
        with mock.patch.object(slop_lint, "_read_input", return_value=(SAMPLE, None)), \
                mock.patch.object(slop_lint, "lint_text", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(stderr):
            code = slop_lint.main(["x.md"])
        self.assertEqual(code, 3)
        self.assertIn("内部エラー", stderr.getvalue())

    def test_p4_18_出力先が閉じられたら終了コード3(self):
        stderr = io.StringIO()
        with mock.patch.object(slop_lint, "_read_input", return_value=(SAMPLE, None)), \
                mock.patch.object(slop_lint, "render_report", side_effect=BrokenPipeError), \
                mock.patch.object(slop_lint, "_silence_stdout"), \
                contextlib.redirect_stderr(stderr):
            code = slop_lint.main(["x.md"])
        self.assertEqual(code, 3)
        self.assertIn("出力先が閉じられた", stderr.getvalue())


class TestStreamsWithoutReconfigure(unittest.TestCase):
    """reconfigure() を持たない標準入出力(IDLE やプロセス内実行)でも動く"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="slop-stdio-", dir=".")
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "sample.md"
        self.path.write_text(SAMPLE, encoding="utf-8")

    def test_stdio_06_StringIOの標準出力へjsonを書き込める(self):
        out = io.StringIO()
        self.assertEqual(run_in_process(LINT, [self.path, "--json"], stdout=out), 0)
        self.assertEqual(len(json.loads(out.getvalue())["findings"]), 4)

    def test_stdio_07_StringIOの標準入力を読める(self):
        out = io.StringIO()
        self.assertEqual(run_in_process(LINT, ["--json"], stdin=io.StringIO(SAMPLE), stdout=out), 0)
        self.assertEqual(json.loads(out.getvalue())["metrics"]["char_count"], 35)

    def test_stdio_08_標準出力がNoneでも実行できる(self):
        self.assertEqual(run_in_process(LINT, [self.path], stdout=None), 0)

    def test_stdio_09_標準入力がNoneなら終了コード2で拒否する(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_in_process(LINT, ["--json"], stdin=None, stdout=io.StringIO())
        self.assertEqual(code, 2)
        self.assertIn("Error reading stdin", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
