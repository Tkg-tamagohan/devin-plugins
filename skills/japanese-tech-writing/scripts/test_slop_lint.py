"""slop_lint の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は <対象>-<連番>: MENTION=言及除外、CHAIN=名詞連結、END=文末連続、BASE=既存ルールの維持、
NAKA=中黒並列、LINE=一文一行、HEAD=見出し罫線、MET=比喩動詞、EMOJI=絵文字、
NEG=対比構文、BOLD=太字表示、STRUCT=構造解析移行。

実行: `python3 test_slop_lint.py`(同ディレクトリから)
"""

import unittest

from slop_lint import lint_text
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
    """見出しの罫線(U+2500)の検出。整形規範「見出しに区切り線で二要素を詰め込まない」に対応"""

    def test_head_01_見出しの罫線は検出する(self):
        self.assertIn(
            "dash_prohibited",
            rules_of("# 種別─主題"),
        )

    def test_head_02_本文の罫線も検出する(self):
        self.assertIn(
            "dash_prohibited",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
