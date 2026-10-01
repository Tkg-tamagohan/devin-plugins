"""slop_lint の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は <対象>-<連番>: MENTION=言及除外、CHAIN=名詞連結、END=文末連続、BASE=既存ルールの維持。

実行: `python3 test_slop_lint.py`(同ディレクトリから)
"""

import unittest

from slop_lint import lint_text


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
