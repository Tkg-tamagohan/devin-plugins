"""slop-catalog.md と slop_lint.py の整合テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は CAT-連番。方向1(カタログの各表現がリントで検出される)と
方向2(リントの検出対象がすべてカタログに記載される)を両方担保する。

実行: `python3 test_catalog_consistency.py`(同ディレクトリから)

## 機械読み取りの契約(節ごとの抽出規則)

カタログは節ごとに表の意味づけが違うため、抽出列と検証方法を節単位で定義する。

- 節 1「AI 偏愛動詞・比喩動詞」: 表は「対象動詞 | 用例 | 修正方針」の 3 列。
  列1 の **太字**(「 / 」区切りで複数形を含む)と列2 の「…」引用を取り出す。
  その行のいずれかの用例をいずれかの検出パターンが拾うか、対象動詞が
  SLOP_WORDS にあれば検出可能とみなす(用例単位ではなく行単位)。
- 節 2「英語直訳調」: 表は「英語の原表現 | AI の直訳日本語 | 自然な日本語」。
  列2 の「…」引用が検出対象。いずれかの用例がパターンに一致するか、
  用例内の語彙が SLOP_WORDS にあればその行を検出可能とみなす。
- 節 3-6: 表の語彙列(節 3 は 2 列目、節 4-6 は節ごとの `語彙/熟語群/対象語彙/
  対象表現` 列)にある `バッククォート` 語彙が検出対象。語が SLOP_WORDS にあるか
  いずれかのパターンに一致すれば検出可能とみなす。

上記で検出できない項目は EXEMPTIONS に「項目 -> 免除理由」として列挙する。
理由のない免除はテストが弾くため、カタログ側に表現を増やすか理由を書く。

方向2 は逆方向の担保で、リント側の SLOP_WORDS の各語と全検出パターン
(比喩動詞、フィラー、対比構文、ダッシュ)が、節ごとの抽出規則が拾う表の
セル(太字・バッククォート・「」引用)に現れることを確認する。
導入文や修正方針への言及だけでは掲載とみなさない。
リントにあってカタログにない項目はカタログを正規化して足す。
"""

import re
import unittest
from pathlib import Path

from slop_lint import (
    FILLER_PATTERNS,
    INFO_SENTENCE_PATTERNS,
    METAPHOR_VERB_PATTERNS,
    NEGATIVE_PARALLELISM_PATTERN,
    SLOP_WORD_PATTERNS,
    SLOP_WORDS,
    _BOLD_LABEL_ITEM,
    _DASH_RUN,
    _FRAGMENT_RUN,
    _NEGATION_EXTRA,
    _NEGATION_JANAI,
    _SHORT_MOCHIRON,
    _SUMMARY_HEADING,
    _dash_finding,
)

CATALOG_PATH = Path(__file__).resolve().parent.parent / "references" / "slop-catalog.md"

QUOTE_PATTERN = re.compile(r"「([^」]+)」")
BACKQUOTE_PATTERN = re.compile(r"`([^`]+)`")
BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")

# 用例を検出する側のパターン一式
DETECTION_PATTERNS = (
    [p for p, _ in METAPHOR_VERB_PATTERNS + FILLER_PATTERNS]
    + [p for _, p in SLOP_WORD_PATTERNS]
    + [p for p, _, _ in INFO_SENTENCE_PATTERNS]
    + [NEGATIVE_PARALLELISM_PATTERN, _NEGATION_EXTRA, _NEGATION_JANAI,
       _SHORT_MOCHIRON, _FRAGMENT_RUN, _BOLD_LABEL_ITEM, _SUMMARY_HEADING,
       _DASH_RUN]
)

# 免除マニフェスト: カタログの表現で機械検出できないものとその理由。
# キーはカタログ中の対象語・節2 では英語の原表現のセル文字列。値は免除の根拠で空文字は不可。
_CONTEXT_DEPENDENT = "文脈依存の一般用語で機械検出すると誤検出が多いため、カタログは推敲時の参照に留める"
_FILLER_UNIMPLEMENTED = "リント側に検出パターンがない定型句で、機械検出は将来のリント拡張に委ねて参照に留める"
EXEMPTIONS = {
    # 節 2: 直訳形が正当な説明表現と識別できない行
    "*point to / suggest*": "「指している」「示唆している」は正当な説明表現と機械的に識別できないため参照に留める",
    "*load-bearing*": "「耐力のある」「構造を支える」は正当な物理・構造の記述と機械的に識別できないため参照に留める",
    "*delve into*": "「深掘りする」は SKILL.md の LLM 節が扱う空虚な動詞だがリントの機械パターンにはなく、参照に留める",
    # 節 1
    "逃がす": "字義どおりの用法(熱を逃がす等)と区別できないため機械検出の対象外とし、推敲時の参照に留める",
    # 節 3: 急増比喩・評価名詞は文脈依存の一般用語が大半
    "事故": _CONTEXT_DEPENDENT, "混ざる": _CONTEXT_DEPENDENT, "落とし穴": _CONTEXT_DEPENDENT,
    "破綻": _CONTEXT_DEPENDENT, "実害": _CONTEXT_DEPENDENT, "素通り": _CONTEXT_DEPENDENT,
    "実測": _CONTEXT_DEPENDENT, "疑う": _CONTEXT_DEPENDENT, "照合": _CONTEXT_DEPENDENT,
    "突き合わせる": _CONTEXT_DEPENDENT, "断定": _CONTEXT_DEPENDENT, "取り違える": _CONTEXT_DEPENDENT,
    "見落とす": _CONTEXT_DEPENDENT,
    "入口": _CONTEXT_DEPENDENT, "道具": _CONTEXT_DEPENDENT, "核心": _CONTEXT_DEPENDENT,
    "主役": _CONTEXT_DEPENDENT, "構図": _CONTEXT_DEPENDENT, "線引き": _CONTEXT_DEPENDENT,
    "導線": _CONTEXT_DEPENDENT, "出口": _CONTEXT_DEPENDENT, "〜のカギ": _CONTEXT_DEPENDENT,
    "〜への近道": _CONTEXT_DEPENDENT, "〜の第一歩": _CONTEXT_DEPENDENT, "両輪": _CONTEXT_DEPENDENT,
    "既定": _CONTEXT_DEPENDENT, "別物": _CONTEXT_DEPENDENT, "定番": _CONTEXT_DEPENDENT,
    "要点": _CONTEXT_DEPENDENT, "定石": _CONTEXT_DEPENDENT, "桁違い": _CONTEXT_DEPENDENT,
    "勝ち筋": _CONTEXT_DEPENDENT, "刺さる": _CONTEXT_DEPENDENT, "〜で決まる": _CONTEXT_DEPENDENT,
    # 節 4: 壮大化熟語のうち SLOP_WORDS にないもの
    "真実": _CONTEXT_DEPENDENT, "結末": _CONTEXT_DEPENDENT, "運命": _CONTEXT_DEPENDENT,
    "究極": _CONTEXT_DEPENDENT, "虚像": _CONTEXT_DEPENDENT, "残酷": _CONTEXT_DEPENDENT,
    "凝縮": _CONTEXT_DEPENDENT, "結晶": _CONTEXT_DEPENDENT,
    # 節 5
    "文脈": "正当な技術語として多用されるため機械検出の対象外とする",
    "本質": "リントは「本質的」のみ検出し、単独の「本質」は文脈依存のため対象外とする",
    "契約": "取引・合意としての正当な用法と区別できないため機械検出の対象外とし、推敲時の参照に留める",
    "仕組み": "実際の処理を説明する正当な用法が多く機械検出すると誤検出が多いため、推敲時の参照に留める",
    "境界": "数学・区域の境界や境界値など正当な用法が多く機械検出すると誤検出が多いため、推敲時の参照に留める",
    "粒度": "データの粒度など正当な技術用法と区別できないため機械検出の対象外とし、推敲時の参照に留める",
    "余白": "紙面の余白のような字義どおりの用法と区別できないため機械検出の対象外とし、推敲時の参照に留める",
    "軸": "座標軸など正当な技術用法と区別できないため機械検出の対象外とし、推敲時の参照に留める",
    "言語化": _CONTEXT_DEPENDENT,
    "落とし込む": _CONTEXT_DEPENDENT, "紐解く": _CONTEXT_DEPENDENT, "これは強い": _CONTEXT_DEPENDENT,
    # 節 6: フィラー定型句のうち未実装のもの
    "ここで注目すべきは": _FILLER_UNIMPLEMENTED,
    "原因はシンプルです": _FILLER_UNIMPLEMENTED,
    "ここまで見てきました": _FILLER_UNIMPLEMENTED,
    "驚くべきことに": _FILLER_UNIMPLEMENTED,
    "結局のところ": _FILLER_UNIMPLEMENTED, "要するに": _FILLER_UNIMPLEMENTED,
    "おっしゃる通りです": _FILLER_UNIMPLEMENTED,
    "ご希望があれば〜できます": "「ご希望があれば」検出は後続の「次に」「続けて」等を要求するため、この形は参照に留める",
    "〜を知りたいですか？": _FILLER_UNIMPLEMENTED,
    "〜というわけです": _FILLER_UNIMPLEMENTED,
    "〜と言えるでしょう": _FILLER_UNIMPLEMENTED,
    "ぜひ試してみてください": "リントの定型クロージング検出は「ぜひ(参考|試し|活用)(に)して…ください」の形を要求するため、素の「ぜひ試して」形は参照に留める",
    # 節 7: 硬い漢語と決まり文句はいずれも文脈依存の一般用語
    "活用する": _CONTEXT_DEPENDENT, "実施する": _CONTEXT_DEPENDENT,
    "多角的": _CONTEXT_DEPENDENT, "包括的": _CONTEXT_DEPENDENT,
    "〜を実現することができます": _CONTEXT_DEPENDENT,
    "シームレス": _CONTEXT_DEPENDENT, "シナジー": _CONTEXT_DEPENDENT,
    "価値を最大化": _CONTEXT_DEPENDENT, "次のレベルへ": _CONTEXT_DEPENDENT,
    "圧倒的": _CONTEXT_DEPENDENT, "爆速": _CONTEXT_DEPENDENT,
    "革命的": _CONTEXT_DEPENDENT, "徹底解説": _CONTEXT_DEPENDENT,
}


def catalog_text() -> str:
    return CATALOG_PATH.read_text(encoding="utf-8")


def catalog_sections() -> list:
    """## N. で始まる節ごとの行リストを返す"""
    sections = []
    current = None
    for line in catalog_text().splitlines():
        m = re.match(r"^## (\d+)\.", line)
        if m:
            if current:
                sections.append(current)
            current = {"num": int(m.group(1)), "lines": []}
        elif current is not None:
            current["lines"].append(line)
    if current:
        sections.append(current)
    return sections


def table_rows(lines: list) -> list:
    """表の行(|a|b|c|)をセルのリストに分解する。区切り行 |---| は除く"""
    rows = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def quoted(text: str) -> list:
    return QUOTE_PATTERN.findall(text)


def backquoted(text: str) -> list:
    return BACKQUOTE_PATTERN.findall(text)


def bold_terms(text: str) -> list:
    out = []
    for t in BOLD_PATTERN.findall(text):
        out.extend(x.strip() for x in t.split("/") if x.strip())
    return out


def detected(expr: str) -> bool:
    """表現 expr がリントで検出可能か(SLOP_WORDS の語を含むかパターン一致)"""
    if any(w in expr for w in SLOP_WORDS):
        return True
    return any(
        p.search(expr) if hasattr(p, "search") else re.search(p, expr)
        for p in DETECTION_PATTERNS
    )


def row_detected(usages: list, terms: list) -> bool:
    """行の用例か対象語のどれか一つでも検出可能ならその行は検出可能"""
    return any(detected(u) for u in usages) or any(detected(t) for t in terms)


class TestCatalogCoverage(unittest.TestCase):
    """方向1: カタログの各検出対象がリントで拾える"""

    def test_cat_01_節1の動詞行は用例か対象動詞で検出される(self):
        lines = catalog_sections()[0]["lines"]
        rows = table_rows(lines)
        failures = []
        for cells in rows[1:]:  # ヘッダ行を除く
            terms = bold_terms(cells[0])
            usages = quoted(cells[1]) if len(cells) > 1 else []
            exempted = all(t in EXEMPTIONS for t in terms)
            if not row_detected(usages, terms) and not exempted:
                failures.append(cells[0])
        self.assertEqual(failures, [])

    def test_cat_02_節2の直訳行は用例で検出される(self):
        lines = catalog_sections()[1]["lines"]
        rows = table_rows(lines)
        failures = []
        for cells in rows[1:]:
            usages = quoted(cells[1]) if len(cells) > 1 else []
            if not row_detected(usages, []) and cells[0] not in EXEMPTIONS:
                failures.append(cells[0])
        self.assertEqual(failures, [])

    def test_cat_03_節3以降の語彙は検出される(self):
        # 語彙の入った列は節ごとに決まっている(機械読み取りの契約参照)
        vocab_col = {3: 1, 4: 0, 5: 1, 6: 1, 7: 1}
        failures = []
        for sec in catalog_sections():
            if sec["num"] < 3:
                continue
            col = vocab_col[sec["num"]]
            for cells in table_rows(sec["lines"])[1:]:
                if len(cells) <= col:
                    continue
                for w in backquoted(cells[col]):
                    if not detected(w) and w not in EXEMPTIONS:
                        failures.append(w)
        self.assertEqual(sorted(set(failures)), [])

    def test_cat_04_免除マニフェストは理由つきで現存する項目のみ(self):
        covered = covered_expressions()
        text = catalog_text()
        for key, reason in EXEMPTIONS.items():
            self.assertTrue(reason, f"{key} の免除理由が空")
            self.assertTrue(
                key in text or any(key in c for c in covered),
                f"{key} はカタログに存在しない免除項目",
            )


def covered_expressions() -> list:
    """表のセルから抽出した検出対象の表現一式(太字・バッククォート・「」引用)"""
    covered = []
    for sec in catalog_sections():
        for cells in table_rows(sec["lines"]):
            for cell in cells:
                covered += backquoted(cell) + bold_terms(cell) + quoted(cell)
    return covered


class TestLintCoverage(unittest.TestCase):
    """方向2: リントの検出対象がすべてカタログに記載される"""

    def test_cat_05_スロップ語彙はカタログの検出対象列に記載される(self):
        # 導入文や修正方針への言及だけでは掲載とみなさず、
        # 節ごとの抽出規則が拾う表のセルに現れることを要求する
        covered = covered_expressions()
        missing = [w for w in SLOP_WORDS if not any(w in expr for expr in covered)]
        self.assertEqual(missing, [])

    def test_cat_06_比喩動詞パターンはカタログの用例を検出する(self):
        usages = covered_expressions()
        failures = []
        for pattern, desc in METAPHOR_VERB_PATTERNS:
            if not any(re.search(pattern, u) for u in usages):
                failures.append(desc)
        self.assertEqual(failures, [])

    def test_cat_07_フィラーパターンはカタログの用例を検出する(self):
        usages = covered_expressions()
        failures = []
        for pattern, desc in FILLER_PATTERNS:
            if not any(re.search(pattern, u) for u in usages):
                failures.append(desc)
        self.assertEqual(failures, [])

    def test_cat_08_対比構文とダッシュのパターンも用例を検出する(self):
        usages = covered_expressions()
        failures = []
        if not any(NEGATIVE_PARALLELISM_PATTERN.search(u) for u in usages):
            failures.append("対比構文「ではなく」")
        # DASH_PATTERN 廃止に伴い、3ルール化した _dash_finding がカタログの
        # 用例へ指摘を返すことを確かめる
        if not any(_dash_finding(u, 1, u) for u in usages):
            failures.append("ダッシュ3ルール(挿入・列挙閉じ・装飾)")
        self.assertEqual(failures, [])

    def test_cat_09_info系の文型パターンも用例を検出する(self):
        # Phase 2-3 で加えた info 系の型。カタログのセルに現れる用例を
        # いずれかのパターンが拾うことを確認する
        usages = covered_expressions()
        checks = [(re.compile(p), rule) for p, rule, _ in INFO_SENTENCE_PATTERNS]
        checks += [
            (_SHORT_MOCHIRON, "もちろん短答"),
            (_FRAGMENT_RUN, "断片連続"),
            (_BOLD_LABEL_ITEM, "太字ラベル箇条書き"),
            (_SUMMARY_HEADING, "まとめ/おわりに見出し"),
            (_NEGATION_EXTRA, "否定を重ねて言い切る構文"),
            (_NEGATION_JANAI, "じゃない、〜です構文"),
        ]
        failures = []
        for pattern, desc in checks:
            if not any(pattern.search(u) for u in usages):
                failures.append(desc)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
