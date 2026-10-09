#!/usr/bin/env python3
"""
slop_lint.py - 日本語文章の AI っぽさ(LLM スロップ)機械検査スクリプト

nanaism/yomiyasu (MIT License, Copyright (c) 2026 nanaism) の
yomiyasu_lint.py を基に、shared-skills:japanese-tech-writing の
規範と衝突しないよう改変したもの。
ライセンス条文はスキルディレクトリの LICENSE-yomiyasu を参照。

本スキルとの調整点:
- 太字頻度と箇条書き比率は info に降格(定義語の太字・定義列挙の
  箇条書きは本スキルが許容するため、警告ではなく情報として出す)
- 行内のダッシュ記号(em ダッシュ等)の検出を追加(本スキルの整形規範)
- 「〜に他なりません」の検出が波線の直前に限られていた問題を修正
- 「」で囲まれた言及(禁止表現の例示)を語彙・構文検査の対象から除外
- 助詞「の」で数珠つなぎになった名詞連結(過圧縮)の検出を追加
- 中黒(・)の日本語並列、一行の複数文、見出しの罫線(U+2500)の検出を追加

上流の変更で取り込んだ調整点:
- 比喩動詞の追加(Xが壊れる、踏み込む、引き返す、添える、収斂)と
  「Xが壊れる」「静かに壊れる」の同一動詞への二重反応の回避
- 同一文末の連続検出は段落(隣接する地の文)の内側に限定する
- 「A ではなく B」構文は上流の正確な字句走査で判定する
- 太字の印(**)が表示されない書き方の検査を markdown_bold.py から
  呼び出す(上流の判定機械を共通モジュールへ切り出したもの)
- 行ごとの正規表現走査を markdown_visibility.py の構造解析へ移行。
  コード・URL・HTML・参照定義などの不透明領域は可視テキストで
  空白化し、引用・表・HTML ブロックはブロック種別で除外する
- v1.1.1 追従: SLOP_WORD_PATTERNS(形で確かめる語彙)、フィラーの
  文単位走査と FILLER_NOTES、INFO_SENTENCE_PATTERNS、もちろん
  短答・断片連続・太字ラベル列挙・まとめ見出しの info 検出、
  リテラル事前絞り込み(_narrowed_document_rows)による走査削減

検出結果は機械的な見直し候補であり、SKILL.md の規範で正当な
記述と判断できるものはそのまま保持する。
標準ライブラリのみで動作する。
"""

import sys
import re
import argparse
import json
from bisect import bisect_right
from itertools import chain, compress
from operator import is_
from typing import List, Dict, Any, Tuple, Optional

try:
    from markdown_bold import bold_problems, _bold_problems_with_analysis
    from markdown_visibility import (
        analyze_markdown, line_visible_text, range_overlaps_protected,
    )
except ModuleNotFoundError as error:
    # spec_from_file_location などで読み込まれた場合でも同ディレクトリの
    # モジュールを解決できるようにする
    if error.name not in ("markdown_bold", "markdown_visibility"):
        raise
    import importlib.util
    from pathlib import Path

    def _load_sibling(name):
        spec = importlib.util.spec_from_file_location(
            "_yomiyasu_" + name, Path(__file__).with_name(name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    _bold_module = _load_sibling("markdown_bold")
    bold_problems = _bold_module.bold_problems
    _bold_problems_with_analysis = _bold_module._bold_problems_with_analysis
    _visibility_module = _load_sibling("markdown_visibility")
    analyze_markdown = _visibility_module.analyze_markdown
    line_visible_text = _visibility_module.line_visible_text
    range_overlaps_protected = _visibility_module.range_overlaps_protected

# 絵文字正規表現パターン(CJK 統合漢字拡張などのサロゲートペア漢字を除外した厳密な絵文字範囲)
EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F]"  # Emoticons
    r"|[\U0001F300-\U0001F5FF]"  # Misc Symbols and Pictographs
    r"|[\U0001F680-\U0001F6FF]"  # Transport and Map
    r"|[\U0001F700-\U0001F77F]"  # Alchemical Symbols
    r"|[\U0001F780-\U0001F7FF]"  # Geometric Shapes Extended
    r"|[\U0001F800-\U0001F8FF]"  # Supplemental Arrows-C
    r"|[\U0001F900-\U0001F9FF]"  # Supplemental Symbols and Pictographs
    r"|[\U0001FA00-\U0001FA6F]"  # Chess Symbols
    r"|[\U0001FA70-\U0001FAFF]"  # Symbols and Pictographs Extended-A
    r"|[\u2600-\u27BF]"          # Misc Symbols, Dingbats
    r"|[\u2300-\u23FF]"          # Misc Technical
    r"|[\u2B50-\u2B55]"
)

# ダッシュ記号(em ダッシュ、horizontal bar、2 倍ダッシュ)と罫線(U+2500)。
# 範囲を示す en ダッシュ(U+2013)は対象外。
DASH_PATTERN = re.compile(r"[—―─]|——")

# 中黒(・)による日本語の並列。「作成・推敲」のような列挙を拾う。
# セグメントは同一文字種のランに限る。混在させると「ウォルト・ディズニーの作品」で
# 後続の「の作品」まで連結に吸収され、固有名詞まで並列と誤認するため。
# すべてのセグメントがカタカナまたは大写英字一文字の場合は単一固有名詞
# (「ウォルト・ディズニー」「ジョン・フィッツジェラルド・ケネディ」のような人名)の
# 可能性が高いため検査側で除外する。「メール・電話」やカタカナ四要素以上の列挙も
# 見逃しうるが、固有名詞の誤検出を避けることを優先した。
NAKAGURO_SEGMENT = r"(?:[ァ-ヶー]+|[一-龯]+|[ぁ-ん]+|[0-9A-Za-z]+)"
NAKAGURO_ENUM_PATTERN = re.compile(
    NAKAGURO_SEGMENT + r"(?:[・･]" + NAKAGURO_SEGMENT + r")+"
)
PROPER_NOUN_SEGMENT_PATTERN = re.compile(r"[ァ-ヶー]+|[A-Z]")

# 一行に複数の文がある形。文末記号の直後に文末記号・閉じ括弧類・空白以外が
# 続けば、その行には二文以上があるとみなす。
SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？](?![。！？」）』\s]*$)")

# AI 頻出語彙リスト。文脈上正当な専門用語(医学の「体温」、画像処理の
# 「解像度」、化学の「触媒」など)であれば保持する。
SLOP_WORDS = [
    # 質感を装う疑似具体語
    "手触り", "肌感", "肌感覚", "体温", "温度感", "熱量", "血の通った", "泥臭い", "泥臭さ",
    # 認知・評価を装う語
    "解像度", "腹落ち", "メンタルモデル", "本質的", "地に足のついた", "等身大",
    # 抽象比喩名詞
    "営み", "装置", "土台", "羅針盤", "起爆剤", "触媒",
    # 必殺技造語(体験の壮大化)
    "真理", "虚飾", "境地", "美学", "深淵", "冷徹", "禁欲的", "優美", "極致", "宿命",
    # 文脈によるが要点検の語
    "正本",
]

# 部分一致では別の語を巻き込むため、形で確かめる語(語, パターン)。
# 「意思決定OS」は語彙リストからこちらの形判定へ移した。
SLOP_WORD_PATTERNS = [
    # ナビゲート、デリゲートなど -gate で終わる外来語は、直前のカタカナで除く(レビューゲートなどは拾う)。
    ("ゲート", r"(?:(?<![ァ-ヴー])|(?<=レビュー)|(?<=リリース)|(?<=チェック)|(?<=デプロイ)|(?<=マージ)|(?<=テスト))"
               r"(?<!搭乗)(?<!改札)ゲート(?!ウ[ェエ]イ|ボール|キーパー)"),
    # 数学の閉包(推移閉包、閉包演算など)や、会計・行政の台帳は定義どおりの用語として残す。
    ("閉包", r"(?<!推移)(?<!反射)(?<!対称)(?<!凸)(?<!代数)(?<!代数的)閉包(?!演算)"),
    ("台帳", r"(?<!資産)(?<!住民基本)(?<!会計)(?<!会計の)(?<!行政の)(?<!課税)(?<!土地)(?<!家屋)(?<!備品)(?<!登記)台帳"),
    ("〜のOS", r"(思考|意思決定|仕事|人生|組織|チーム|学習|経営)の?OS(?![A-Za-z])"),
    ("本質を突く", r"本質を突"),
]

# 比喩動詞・AI 偏愛動詞パターン
METAPHOR_VERB_PATTERNS = [
    (r"(地味に|よく|じわじわ)効[かきくけいた]", "比喩動詞「効く」の過剰使用"),
    (r"(データ|仕様|設計|環境|ビルド|システム|秩序)が(静かに)?壊れ", "比喩動詞「壊れる」"),
    (r"静かに(壊れ|落ち|失敗|沈黙)", "英語直訳「静かに壊れる (silently fail)」"),
    (r"黙って(無視|捨て|スキップ|破棄)", "英語直訳「黙って無視される」"),
    (r"側に倒[すしせ]", "判断を方向で表現する「〜側に倒す」"),
    (r"時間[をに]溶か[したす]", "比喩動詞「時間を溶かす」"),
    (r"(1つずつ|一つずつ)潰[していくす]", "比喩動詞「潰す」"),
    (r"(実装|詳細|コード|設計|内部|仕組み|領域|本質)(に|まで|へ)踏み込[んむみま]", "比喩動詞「踏み込む」"),
    (r"動かしながら引き返[すし]", "比喩動詞「引き返す」"),
    (r"代わりに添え[るた]", "比喩動詞「添える」"),
    (r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂", "比喩動詞「収斂する」"),
    (r"した瞬間に?", "英語直訳「〜した瞬間 (the moment ...)」"),
    (r"(前提|基盤)が崩れ[るた]", "抽象比喩「前提が崩れる」"),
    (r"文化が醸成", "非生物主語「文化が醸成される」"),
    (r"プロセスが定着", "非生物主語「プロセスが定着する」"),
    (r"事例が残した", "非生物主語「事例が残した」"),
]

# メタフィラー・定型句
# 文ごとに当てる(^ と $ は文の頭と終わり)。
FILLER_PATTERNS = [
    (r"^(まず|ここで)?(重要|大切|大事)なのは、?", "前置フィラー「重要なのは」"),
    (r"^結論から(言|い)(う|い|え)|^結論から申し上げ", "前置フィラー「結論から言うと」"),
    (r"^正直に言うと、?", "前置フィラー「正直に言うと」"),
    (r"^本音を言うと、?", "前置フィラー「本音を言うと」"),
    (r"^避けたいのは、?", "前置フィラー「避けたいのは」"),
    (r"^ポイントは、", "前置フィラー「ポイントは、」"),
    (r"見落とされがち|面白いのはここ|まさにそこがポイント", "自己ラベル「見落とされがち」など"),
    (r"いかがでした(でしょうか|か)?[？?。]?$", "定型クロージング「いかがでしたでしょうか」"),
    (r"ぜひ(参考|試し|活用)(に)?して(みて)?ください[！!。]?", "定型クロージング「ぜひ〜してみてください」"),
    (r"参考に(なれ|な)ば幸い|お役に立て(れ)?ば幸い|ぜひご(活用|参考に)ください|まずは小さく(始め|はじめ)(?:ましょう|てみましょう|てください|てみてください|てみませんか|て(?:みて)?はいかが(?:ですか|でしょうか)|る(?:ことが(?:大切|大事|重要)|のがおすすめ)です)[。！？!?]?$", "定型クロージング「参考になれば幸いです」など"),
    (r"に他なりません", "過剰な自己ラベリング「〜に他なりません」"),
    (r"^ご質問ありがとうございます", "チャット応答の名残「ご質問ありがとうございます」"),
    (r"見ていきましょう[。！!]?$|深掘りしていきます", "定型導入「それでは見ていきましょう」など"),
    (r"^(必要なら|ご希望があれば|よろしければ)、?(次に|続けて|この後(?!の))[^。！？!?]*(?:ます|ましょう)(?:か|よ|ね|よね)?(?:（[^。！？!?（）]*）)?[。！？!?]?$", "チャット応答の名残「必要なら次に〜します」"),
]

# 規則の説明に添える、残してよい場合(指針の例外に合わせる)
FILLER_NOTES = {
    "チャット応答の名残「ご質問ありがとうございます」": "チャットやメールの返信そのものなら残してかまいません。",
    "チャット応答の名残「必要なら次に〜します」": "書き手が読み手に実際に申し出ている案内なら残してかまいません。",
    "定型クロージング「参考になれば幸いです」など": "メールや手紙の結びの挨拶や、書き手が実際に勧めている内容なら残してかまいません。",
    "定型クロージング「いかがでしたでしょうか」": "メールや手紙の結びの挨拶なら残してかまいません。",
    "定型クロージング「ぜひ〜してみてください」": "書き手が実際に勧めている内容なら残してかまいません。",
}

# 見直しのきっかけにとどめる文単位の型(info)。(パターン, 規則, 説明)
INFO_SENTENCE_PATTERNS = [
    (r"^(まとめると|総じて)、", "summary_restatement",
     "言い直しの締め(「まとめると」「総じて」)が検出されました。本文で言い終えた内容を繰り返すだけなら削ってください。新しい情報、条件、結論の絞り込みを担う場合や、長い文書や発表で要約の役割を担う場合は残してください。削るときも、その箇所にしかない数値・条件・例外は落とさないでください。"),
    (r"^本記事では", "meta_intro",
     "「本記事では」で始まる案内が検出されました。続く本文と同じ内容を予告しているだけなら削り、長い文書の目次的な案内なら残してください。"),
    (r"(ポイント|理由|観点|コツ|方法)は(3|三|３)つ(です|あります)|以下の(3|三|３)つの(観点|ポイント)", "count_declaration",
     "数の宣言(「ポイントは3つです」など)が検出されました。宣言した数と続く項目の数が合っていれば、宣言の文を中身とまとめるか削ってください。項目を数に合わせて足したり削ったりしないでください。"),
]

# これらの正確なパターンに必要なリテラル。置換ルールではなく、変更された
# パターンやヒントのないカスタムパターンは従来どおり全文を走査する。
_PATTERN_LITERAL_HINTS = {
    r"(地味に|よく|じわじわ)効[かきくけいた]": ("効",),
    r"(データ|仕様|設計|環境|ビルド|システム|秩序)が(静かに)?壊れ": ("壊れ",),
    r"静かに(壊れ|落ち|失敗|沈黙)": ("静かに",),
    r"黙って(無視|捨て|スキップ|破棄)": ("黙って",),
    r"側に倒[すしせ]": ("側に倒",),
    r"時間[をに]溶か[したす]": ("溶か",),
    r"(1つずつ|一つずつ)潰[していくす]": ("つずつ潰",),
    r"(実装|詳細|コード|設計|内部|仕組み|領域|本質)(に|まで|へ)踏み込[んむみま]": ("踏み込",),
    r"動かしながら引き返[すし]": ("動かしながら引き返",),
    r"代わりに添え[るた]": ("代わりに添え",),
    r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂": ("収斂",),
    r"した瞬間に?": ("した瞬間",),
    r"(前提|基盤)が崩れ[るた]": ("が崩れ",),
    r"文化が醸成": ("文化が醸成",),
    r"プロセスが定着": ("プロセスが定着",),
    r"事例が残した": ("事例が残した",),
    r"^(まず|ここで)?(重要|大切|大事)なのは、?": ("なのは",),
    r"^結論から(言|い)(う|い|え)|^結論から申し上げ": ("結論から",),
    r"^正直に言うと、?": ("正直に言うと",),
    r"^本音を言うと、?": ("本音を言うと",),
    r"^避けたいのは、?": ("避けたいのは",),
    r"^ポイントは、": ("ポイントは、",),
    r"見落とされがち|面白いのはここ|まさにそこがポイント": ("見落とされがち", "面白いのはここ", "まさにそこがポイント"),
    r"いかがでした(でしょうか|か)?[？?。]?$": ("いかがでした",),
    r"ぜひ(参考|試し|活用)(に)?して(みて)?ください[！!。]?": ("ぜひ",),
    r"参考に(なれ|な)ば幸い|お役に立て(れ)?ば幸い|ぜひご(活用|参考に)ください|まずは小さく(始め|はじめ)(?:ましょう|てみましょう|てください|てみてください|てみませんか|て(?:みて)?はいかが(?:ですか|でしょうか)|る(?:ことが(?:大切|大事|重要)|のがおすすめ)です)[。！？!?]?$": ("ば幸い", "ぜひご", "まずは小さく"),
    r"に他なりません": ("に他なりません",),
    r"^ご質問ありがとうございます": ("ご質問ありがとうございます",),
    r"見ていきましょう[。！!]?$|深掘りしていきます": ("見ていきましょう", "深掘りしていきます"),
    r"^(必要なら|ご希望があれば|よろしければ)、?(次に|続けて|この後(?!の))[^。！？!?]*(?:ます|ましょう)(?:か|よ|ね|よね)?(?:（[^。！？!?（）]*）)?[。！？!?]?$": ("必要なら", "ご希望があれば", "よろしければ"),
    r"^(まとめると|総じて)、": ("まとめると", "総じて"),
    r"^本記事では": ("本記事では",),
    r"(ポイント|理由|観点|コツ|方法)は(3|三|３)つ(です|あります)|以下の(3|三|３)つの(観点|ポイント)": ("3つ", "三つ", "３つ"),
    r"(?:(?<![ァ-ヴー])|(?<=レビュー)|(?<=リリース)|(?<=チェック)|(?<=デプロイ)|(?<=マージ)|(?<=テスト))(?<!搭乗)(?<!改札)ゲート(?!ウ[ェエ]イ|ボール|キーパー)": ("ゲート",),
    r"(?<!推移)(?<!反射)(?<!対称)(?<!凸)(?<!代数)(?<!代数的)閉包(?!演算)": ("閉包",),
    r"(?<!資産)(?<!住民基本)(?<!会計)(?<!会計の)(?<!行政の)(?<!課税)(?<!土地)(?<!家屋)(?<!備品)(?<!登記)台帳": ("台帳",),
    r"(思考|意思決定|仕事|人生|組織|チーム|学習|経営)の?OS(?![A-Za-z])": ("OS",),
    r"本質を突": ("本質を突",),
}
_ALWAYS_SCAN = object()
_DOCUMENT_TABLES_CACHE = []


def _literal_can_cover(literal, other):
    return other != literal and any(
        other[index:].startswith(literal)
        or (index and literal.startswith(other[index:]))
        for index in range(len(other))
    )


def _document_tables():
    """検査用パターン表を一度だけ組み立て、文書内に現れる候補だけへ絞る索引を返す"""
    tables = (SLOP_WORDS, SLOP_WORD_PATTERNS, METAPHOR_VERB_PATTERNS,
              FILLER_PATTERNS, INFO_SENTENCE_PATTERNS)
    if any(type(table) not in (list, tuple) for table in tables):
        return None
    if _DOCUMENT_TABLES_CACHE:
        saved, result, lengths, flat = _DOCUMENT_TABLES_CACHE
        # キャッシュした要素は不変の素の文字列とタプルのみ。同一性チェックは
        # 置き換えられた要素の等価・ハッシュフックを呼び出さない
        if tuple(map(len, tables)) == lengths and all(map(is_, chain.from_iterable(tables), flat)):
            return result
    words, *families = tables
    if not all(type(word) is str for word in words):
        return None
    if not all(type(row) is tuple and len(row) == width
               and all(type(item) is str for item in row)
               for table, width in zip(families, (2, 2, 2, 3)) for row in table):
        return None
    saved = tuple(tuple(table) for table in tables)
    words, slop, metaphor, filler, info = saved
    literals = []
    alternatives = []

    def keyed(rows, sources):
        keys = []
        out = []
        for row, source in zip(rows, sources):
            required = _PATTERN_LITERAL_HINTS.get(source)
            out.append((*row, required))
            if required is None:
                keys.append(_ALWAYS_SCAN)
            elif len(required) == 1:
                keys.append(required[0])
            else:
                keys.append(required)
                alternatives.append(required)
            literals.extend(required or ())
        return out, keys

    indexed = (
        keyed(slop, [pattern for _, pattern in slop]),
        keyed([(re.compile(pattern), desc) for pattern, desc in metaphor], [pattern for pattern, _ in metaphor]),
        keyed([(re.compile(pattern), desc) for pattern, desc in filler], [pattern for pattern, _ in filler]),
        keyed([(re.compile(pattern), rule, message) for pattern, rule, message in info], [pattern for pattern, _, _ in info]),
    )
    word_keys = [word if word and len(word) <= 64
                 and not any(char in "*_" or char.isspace() for char in word)
                 else _ALWAYS_SCAN for word in words]
    literals.extend(word for word in word_keys if word is not _ALWAYS_SCAN)
    literals = list(dict.fromkeys(literals))
    if len(literals) > 128:
        return None
    ordered = sorted(literals, key=len, reverse=True)
    finder = re.compile("|".join(map(re.escape, ordered))) if ordered else None
    covered = [(literal, covers) for literal in literals
               for covers in [frozenset(other for other in literals if _literal_can_cover(literal, other))]
               if covers]
    result = finder, covered, alternatives, (list(words), word_keys), indexed, literals
    _DOCUMENT_TABLES_CACHE[:] = [saved, result, tuple(map(len, saved)), tuple(chain.from_iterable(saved))]
    return result


def _narrowed_document_rows(text):
    """文書内に現れる語彙・パターンだけを残した検査表を返す。検出結果は変わらない"""
    tables = _document_tables()
    if tables is None:
        return None
    finder, covered, alternatives, (words, word_keys), families, literals = tables
    gate = text.replace("*", "").replace("_", "")
    if finder is None:
        found = frozenset()
    elif len(gate) <= 2048:
        found = frozenset(finder.findall(gate))
    else:
        # 高密度の長文で繰り返しヒットのコストを抑える。短文の走査予算を
        # 使い切ったら、直接の包含確認で同じ集合を完成させる
        found = set()
        for index, match in enumerate(finder.finditer(gate)):
            if index == 8:
                found = {literal for literal in literals if literal in gate}
                break
            found.add(match.group())
        found = frozenset(found)
    present = set(found)
    for literal, covers in covered:
        if not found.isdisjoint(covers) and literal in gate:
            present.add(literal)
    present.add(_ALWAYS_SCAN)
    for required in alternatives:
        if not present.isdisjoint(required):
            present.add(required)
    contains = present.__contains__
    return ([list(compress(words, map(contains, word_keys)))]
            + [list(compress(rows, map(contains, keys))) for rows, keys in families])


def _may_match_literals(literals, text):
    if literals is None:
        return True
    for literal in literals:
        if literal in text:
            return True
    return False


# 評価の語だけの短い文を3つ以上並べる型(「効く。重い。安い。」)
_FRAGMENT_RUN = re.compile(r"(?:^|(?<=[。！？]))(?:[^。！？、\s「」『』]{1,4}[。！]){3,}")

# 引用の区切り。「」とリンクは中身を伏せて断片化を防ぐための置換対象
_QUOTED_SEGMENT = re.compile(r"「[^「」]*」|『[^『』]*』|\[[^\[\]]*\]")

# 1行の文区切り(文末記号の直後)
_LINE_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?])")

# 文頭の「もちろん、」のあとに数語だけが続いて終わる短い文(「もちろん、失敗もする。」)
_SHORT_MOCHIRON = re.compile(r"^(もちろん|勿論)、[^。！？!?、「」『』]{1,10}[。！!]$")
# 問いや依頼への答えの定型(「もちろん、大丈夫です。」)は先回りの認めではない
_MOCHIRON_ANSWER = re.compile(r"^(もちろん|勿論)、(大丈夫|構いません|かまいません|いいですよ|いいよ|できます|可能です|です|だ)")

_QUESTION_CLOSERS = "」』）)\"'*_"
_QUESTION_SUFFIXES = ("ですか", "ますか", "ませんか", "でしょうか", "だろうか", "のか", "ないか",
                      "うか", "くか", "ぐか", "すか", "つか", "ぬか", "ぶか", "むか", "るか", "たか", "いいか", "よいか")
_WH_QUESTION = re.compile(
    r"なぜ|どうして(?!も)|どのよう(?:に|な)|いつ(?!でも|も|か(?!ら))|どこ(?!でも|も|か(?!ら))|"
    r"誰(?!でも|も|か(?!ら))|何(?!でも|も|か(?!ら))|どれ(?!でも|も|か(?!ら))|どの(?![^。！？!?、]{1,12}でも)"
)


def _question_content_end(sentence):
    end = len(sentence)
    while end and (sentence[end - 1].isspace() or sentence[end - 1] in _QUESTION_CLOSERS):
        end -= 1
    return end


def _last_context_sentence(text):
    end = _question_content_end(text)
    if not end:
        return ""
    start = max(text.rfind(mark, 0, end - 1) for mark in "。！？!?") + 1
    return text[start:end]


def _ends_with_question(sentence):
    """連続する yes/no 疑問文の判定。かで終わるだけの語を疑問文とみなさない"""
    end = _question_content_end(sentence)
    if not end:
        return False
    explicit = sentence[end - 1] in "？?"
    if not explicit and sentence[end - 1] == "。":
        end -= 1
    if not explicit and (sentence.endswith("いくつか", 0, end)
                         or not sentence.endswith(_QUESTION_SUFFIXES, 0, end)):
        return False
    return _WH_QUESTION.search(sentence, 0, end) is None


# 「- **特徴**: 説明」のように、太字の見出し語とコロンで始まる箇条書き
# 「- **特徴：** 説明」(コロンが太字の内側)や番号付きリストも同じ型として数える。
_BOLD_LABEL_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\*\*[^*]+?(?:\*\*\s*[:：]|[:：]\s*\*\*)")
# ATX(「## まとめ」「## まとめ ##」)と setext(タイトル行だけが heading に
# 分類される)の両形式を拾うため、# は任意扱いにする
_SUMMARY_HEADING = re.compile(r"^(?:#{1,6}\s*)?(まとめ|おわりに)\s*#*\s*$")

# ネガティブパラレリズム(A ではなく B)
NEGATIVE_PARALLELISM_PATTERN = re.compile(r"([^。、]+)ではなく、?([^。、]+)")
_NEGATIVE_PARALLELISM_DEFAULT = NEGATIVE_PARALLELISM_PATTERN


def _has_negative_parallelism(text: str) -> bool:
    """既定パターンと同等の「A ではなく B」構文の存在判定

    リテラル「ではなく」の直前に文区切り(。、)を挟まず、直後にも
    実質的な後項が続く出現だけを数える。リテラルは自己重複しない
    ため、見つかった位置の次から探索を進める。
    """
    pattern = NEGATIVE_PARALLELISM_PATTERN
    default = _NEGATIVE_PARALLELISM_DEFAULT
    if (type(pattern) is not type(default) or pattern.pattern != default.pattern
            or pattern.flags != default.flags):
        return "ではなく" in text and bool(pattern.search(text))

    literal = "ではなく"
    offset = 0
    while True:
        position = text.find(literal, offset)
        if position == -1:
            return False
        end = position + len(literal)
        if position > 0 and text[position - 1] not in "。、" and end < len(text):
            if text[end] not in "。、":
                return True
            if text[end] == "、" and end + 1 < len(text) and text[end + 1] not in "。、":
                return True
        offset = position + len(literal)

# 名詞の過剰連結(サ変名詞の数珠つなぎ)。助詞「の」で 3 つ以上の名詞が
# 連結している断片を拾い、サ変名詞・抽象名詞の個数で絞り込む。
# セグメントは純粋な名詞句に限るため、格助詞や接続助詞(は・が・を・も・と)を
# 含む断片は連結とみなさない
NOUN_CHAIN_PATTERN = re.compile(r"[^\s、。！？「」（）：:<>はがをもと・]{1,15}の[^\s、。！？「」（）：:<>はがをもと・]{1,15}の[^\s、。！？「」（）：:<>はがをもと・]+")
# サ変名詞・抽象名詞の目印(代表的な語尾、または 3 字以上のカタカナ語)
ABSTRACT_NOUN_PATTERN = re.compile(
    r"(化|性|度|率|量|観|感|的|止|施|討|生|認|理|延|善|応|用|保|能|合|解|断|開|成|定|務|証|準|装|報)$|[ァ-ヶー]{3,}"
)
# 格助詞でない「の」を含む定型(一つの、ものの、ための、ので)は連結判定から隠す
CHAIN_MASK_PATTERN = re.compile(r"一つの|ものの|ための|ので")


def get_frontmatter_line_count(lines: List[str]) -> int:
    """YAML フロントマター(先頭の --- から次の --- まで)の行数を返す"""
    if not lines or lines[0].strip() != "---":
        return 0
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return idx + 1
    return 0


def _plain_sentence_records(analysis):
    """地の文の段落文を (行番号, 可視テキスト, 原文断片, 段落グループ) で返す

    段落ブロックだけを対象とし、引用・箇条書き・表・見出し・コード等は
    ブロックの種別で除く。画像だけの行は段落の区切りとして扱い、
    段落グループを進める。
    """
    records = []
    for block_id, block in enumerate(analysis["blocks"]):
        if block["kind"] != "paragraph":
            continue
        section = 0
        for row in block["lines"]:
            visible = _prose_visible_text(analysis, row["line"])
            if _image_only_row(analysis, row, visible):
                section += 1
                continue
            if not visible.strip():
                continue
            start = 0
            ends = [match.start() for match in re.finditer(r"(?<=[。！？])", visible)]
            if not ends or ends[-1] != len(visible):
                ends.append(len(visible))
            for end in ends:
                clean = visible[start:end].strip()
                if clean and len(clean) > 3:
                    records.append((row["line"], clean, row["raw"][start:end].strip(), (block_id, section)))
                start = end
    return records


def extract_plain_sentences(text: str) -> List[Tuple[int, str]]:
    """コードブロックや引用、箇条書きを除き、元の行番号つきで地の文を抽出する。"""
    records = _plain_sentence_records(analyze_markdown(text))
    return [(line, visible) for line, visible, _, _ in records]


def _sentence_end_findings(sentences, source_sentences=None, paragraph_groups=None):
    """3 文以上連続する同一語尾の検知。段落グループまたは行の隣接で切り離す"""
    findings = []
    end_types = []

    for line_no, s in sentences:
        end = len(s)
        floor = max(0, end - 64)
        while end > floor and (s[end - 1] in "。！？" or s[end - 1].isspace()):
            end -= 1
        if end == floor and end and (s[end - 1] in "。！？" or s[end - 1].isspace()):
            clean = re.sub(r"(?<![。！？\s])[。！？\s]+$", "", s)
        else:
            clean = s[:end]
        end_type = "その他"
        if clean.endswith("です"):
            end_type = "です"
        elif clean.endswith("ます"):
            end_type = "ます"
        elif clean.endswith("でした"):
            end_type = "でした"
        elif clean.endswith("ました"):
            end_type = "ました"
        elif clean.endswith("である"):
            end_type = "である"
        elif clean.endswith("だ"):
            end_type = "だ"
        elif clean.endswith("だろう"):
            end_type = "だろう"
        end_types.append((line_no, s, end_type))

    # 3 連続チェック
    count = 1
    for i in range(1, len(end_types)):
        prev_line, prev_s, prev_type = end_types[i - 1]
        curr_line, curr_s, curr_type = end_types[i]

        # 同じ段落だけを数え、空行や除外したブロック(見出し、箇条書き、
        # 引用、表など)を挟めば数え直す
        same_paragraph = (paragraph_groups[i] == paragraph_groups[i - 1]
                          if paragraph_groups is not None else curr_line <= prev_line + 1)
        if same_paragraph and curr_type != "その他" and curr_type == prev_type:
            count += 1
            if count == 3:
                findings.append({
                    "rule": "sentence_end_repetition",
                    "line": curr_line,
                    "severity": "warn",
                    "message": f"同一文末「{curr_type}」が3回以上連続しています。文末のリズムを調整してください。",
                    "snippet": source_sentences[i][1] if source_sentences is not None else curr_s
                })
        else:
            count = 1

    return findings


def check_sentence_end_repetitions(sentences: List[Tuple[int, Optional[str]]]) -> List[Dict[str, Any]]:
    """互換 API。段落グループ情報のない呼び出しでは行の隣接で判定する"""
    return _sentence_end_findings(sentences)


_METRIC_OPAQUE_KINDS = frozenset((
    "code", "frontmatter", "html_block", "reference_definition", "inline_code",
    "html_token", "autolink", "link_destination", "image", "bare_url"
))
_PROSE_SCAN_KINDS = _METRIC_OPAQUE_KINDS | frozenset(("container_prefix",))


def _prose_visible_text(analysis, line_no):
    """語彙・構文検査と文末抽出が共有する、不透明領域を空白化した可視テキスト"""
    cache = analysis.setdefault("_prose_line_cache", {})
    if line_no not in cache:
        cache[line_no] = line_visible_text(analysis, line_no, _PROSE_SCAN_KINDS)
    return cache[line_no]


def _image_only_row(analysis, row, visible):
    """実画像だけの行は区切りとして扱うが、画像の後の本文は読み飛ばさない"""
    if not visible.strip():
        return range_overlaps_protected(analysis, row["start"], row["start"] + len(row["raw"]),
                                        frozenset(("image",)))
    raw = row["raw"]
    if not raw.strip().startswith("[!["):
        return False
    if "_image_link_start_indexes" not in analysis:
        images, destinations = {}, {}
        for left, right, kind in analysis["protected_spans"]:
            if kind == "image":
                images[left] = right
            elif kind == "link_destination":
                destinations[left] = right
        analysis["_image_link_start_indexes"] = (images, destinations)
    images, destinations = analysis["_image_link_start_indexes"]
    start = row["start"] + len(raw) - len(raw.lstrip())
    end = row["start"] + len(raw.rstrip())
    image_end = images.get(start + 1)
    return (image_end is not None
            and analysis["text"][image_end:image_end + 2] == "]("
            and destinations.get(image_end + 1) == end)


def _paragraph_prose_parts(analysis):
    """段落ブロックの地の文行を(行番号, 可視文字列)の連続区間へ分ける。
    引用・画像だけの行と段落の境界で区切り、ブロックをまたがない"""
    for block in analysis["blocks"]:
        if block["kind"] != "paragraph":
            continue
        parts = []
        for row in block["lines"]:
            visible = _prose_visible_text(analysis, row["line"])
            if row["quote_depth"] or _image_only_row(analysis, row, visible):
                if parts:
                    yield parts
                    parts = []
                continue
            visible = visible.replace("__", "").replace("*", "").strip()
            if visible:
                parts.append((row["line"], visible))
        if parts:
            yield parts


def _fragment_run_line_numbers(analysis):
    """段落内の隣接する地の文をつないで短文連打を拾う。
    一文一行の規範では断片は行をまたぐため、行ごとの判定では拾えない"""
    hit_lines = set()
    for parts in _paragraph_prose_parts(analysis):
        masked = [(n, _QUOTED_SEGMENT.sub("「」", v)) for n, v in parts]
        joined = "".join(v for _, v in masked)
        if joined.count("。") + joined.count("！") < 3:
            continue
        offsets = []
        total = 0
        for _, v in masked:
            offsets.append(total)
            total += len(v)
        for match in _FRAGMENT_RUN.finditer(joined):
            index = bisect_right(offsets, match.start()) - 1
            hit_lines.add(masked[index][0])
    return hit_lines


def _metrics_from_analysis(analysis):
    """語彙・文末検査と同じ不透明領域の境界で構造メトリクスを算出する"""
    plain_rows = []
    for row in analysis["lines"]:
        stripped = row["raw"].strip()
        if row["kind"] in ("code", "frontmatter", "html_block", "reference_definition"):
            continue
        if row["quote_depth"] or row["kind"] == "table":
            continue
        visible = line_visible_text(analysis, row["line"], _METRIC_OPAQUE_KINDS)
        if _image_only_row(analysis, row, visible):
            continue
        if stripped:
            plain_rows.append((row, visible))
    total_lines = len(plain_rows)
    list_lines = 0
    for row, _ in plain_rows:
        if re.match(r"^\s*([-*+]|\d+\.)\s+", row["raw"]):
            # 外部参照リンク(- [タイトル](http...))は並列データのため思考リストから除外
            if not re.search(r"[-*+]\s+\[.*?\]\(https?://", row["raw"]):
                list_lines += 1
    plain_content = "\n".join(visible for _, visible in plain_rows)
    bold_count = len(re.findall(r"\*\*[^*]+\*\*", plain_content))
    char_count = len(re.sub(r"\s+", "", plain_content))
    bold_per_1000 = bold_count / char_count * 1000 if char_count > 0 else 0
    list_ratio = list_lines / total_lines if total_lines > 0 else 0
    return {"char_count": char_count, "total_lines": total_lines, "list_lines": list_lines,
            "list_ratio": round(list_ratio, 3), "bold_count": bold_count,
            "bold_per_1000": round(bold_per_1000, 2)}


def analyze_markdown_metrics(text: str) -> Dict[str, Any]:
    """太字頻度、箇条書き比率などの構造メトリクスを算出(引用文やコードブロックは除外)"""
    return _metrics_from_analysis(analyze_markdown(text))


def lint_text(text: str) -> Dict[str, Any]:
    """文章全体を総合検査する"""
    findings = []
    analysis = analyze_markdown(text)
    metrics = _metrics_from_analysis(analysis)
    fragment_run_lines = _fragment_run_line_numbers(analysis)
    sentence_records = _plain_sentence_records(analysis)
    sentences = [(line, visible) for line, visible, _, _ in sentence_records]
    source_sentences = [(line, source) for line, _, source, _ in sentence_records]
    paragraph_groups = [block_id for _, _, _, block_id in sentence_records]
    narrowed = _narrowed_document_rows(text)
    if narrowed is None:
        # コンパイル済みパターンやジェネレータなど通常と違う設定値では、
        # 従来どおり行ごとの遅延走査に戻る
        metaphor_patterns = [(re.compile(pattern), desc, None) for pattern, desc in METAPHOR_VERB_PATTERNS]
        filler_patterns = [(re.compile(pattern), desc, None) for pattern, desc in FILLER_PATTERNS]
        info_sentence_patterns = [(re.compile(pattern), rule, message, None)
                                  for pattern, rule, message in INFO_SENTENCE_PATTERNS]
    else:
        slop_words, slop_patterns, metaphor_patterns, filler_patterns, info_sentence_patterns = narrowed
    previous_sentence = ""
    bold_label_lines = []

    # 1. メトリクス異常の検査(地の文が十分ある場合に適用)
    #    本スキルが許容する記法(定義語の太字、定義列挙の箇条書き)でも
    #    閾値を超えうるため、これらは警告ではなく情報(info)として出す。
    if metrics["char_count"] > 300:
        if metrics["bold_per_1000"] > 3.0:
            findings.append({
                "rule": "excess_bold",
                "line": 1,
                "severity": "info",
                "message": f"太字の頻度(1,000 字あたり {metrics['bold_per_1000']} 個)が高めです。定義語の太字は本スキルが許容しますが、強調のためだけの太字は一節あたり一、二箇所に絞ってください。",
                "snippet": f"太字数: {metrics['bold_count']}回 / {metrics['char_count']}文字"
            })

        if metrics["list_ratio"] > 0.25:
            findings.append({
                "rule": "excess_list",
                "line": 1,
                "severity": "info",
                "message": f"箇条書きの比率({round(metrics['list_ratio']*100, 1)}%)が高めです。定義や分類の列挙は本スキルが許容しますが、論証の流れを箇条書きに頼っている箇所は段落への統合を検討してください。",
                "snippet": f"リスト行: {metrics['list_lines']} / 全非空行: {metrics['total_lines']}"
            })

    # 2. 文末重複検査
    findings.extend(_sentence_end_findings(sentences, source_sentences, paragraph_groups))

    # 2.5 太字が表示されるか(GitHub などで ** がそのまま出ることがある箇所)
    for p in _bold_problems_with_analysis(text, analysis):
        findings.append({
            "rule": "bold_not_rendered",
            "line": p["line"],
            "severity": "error",
            "message": f"太字の印(**)が表示されない可能性のある書き方が検出されました。GitHub などで太字にならず ** がそのまま表示されることがあります。直し方の案: {p['how']}。",
            "snippet": f"{p['found']} → {p['suggest']}" if p["suggest"] else p["found"]
        })

    # 3. 語彙・構文パターン検査
    for row in analysis["lines"]:
        line_no, line = row["line"], row["raw"]
        kind = row["kind"]
        if kind == "code":
            previous_sentence = ""
            continue
        stripped = line.strip()
        scan_text = _prose_visible_text(analysis, line_no).strip()
        # 引用・表・水平線や画像だけの行は文脈を引き継がない
        if kind in ("table", "thematic_break", "quote") or row["quote_depth"]:
            previous_sentence = ""

        # 中黒による並列(本スキルの整形規範。固有名詞の内部は例外)。
        # 記号だけで判定できる検査はフロントマターを含む全行が対象だが、
        # HTML ブロック・参照定義・コードや URL の不透明領域は除く
        if kind not in ("html_block", "reference_definition"):
            if kind == "frontmatter":
                masked_text = re.sub(r"`[^`]+`", "　", stripped)
            else:
                masked_text = scan_text
            # 「」の言及は区切り(全角空白)に置き換えて誤検出を防ぐ。
            # 太字や強調の記号も除く(「**作成**・**推敲**」を遮断しないため)
            masked_text = re.sub(r"「[^」]*」", "　", masked_text)
            masked_text = re.sub(r"\*\*|\*|__", "", masked_text)
            for m in NAKAGURO_ENUM_PATTERN.finditer(masked_text):
                segments = re.split(r"[・･]", m.group(0))
                if all(PROPER_NOUN_SEGMENT_PATTERN.fullmatch(s) for s in segments):
                    continue
                findings.append({
                    "rule": "nakaguro_parallel",
                    "line": line_no,
                    "severity": "warn",
                    "message": "中黒(・)の並列が検出されました。読点や「や」「と」などに書き直してください。単一の固有名詞の内部は対象外です。",
                    "snippet": line.strip()
                })
                break

        if kind in ("frontmatter", "html_block", "reference_definition"):
            previous_sentence = ""
            continue
        if not scan_text:
            continue

        # 「」で囲まれた言及は禁止表現の例示であることが多い。use と mention を
        # 区別するため、語彙・構文検査は言及を除いたテキストで行う。
        # 中黒は各検査パターンを跨げない区切りになる。「X」ではなく「Y」では
        # ではなく が残るので、実際の対比は引き続き検査できる
        mention_free = re.sub(r"「[^」]*」", "・", scan_text)

        # 「もちろん、」短答の文脈判定用に、直前の地の文を追跡する
        sentence_before_line = previous_sentence
        previous_sentence = re.sub(r"\*\*|\*|__", "", mention_free)

        # 一文一行(本スキルの整形規範)。引用・表は対象外
        if not row["quote_depth"] and kind not in ("quote", "table"):
            sent_text = re.sub(r"「[^」]*」", "", _prose_visible_text(analysis, line_no))
            sent_text = re.sub(r"\[\^[^\]]*\]", "", sent_text)
            # リンクは文言か直後の句読点が文の一部を示すときだけ文言を残し、
            # 記法と宛先(可視化で空白化済み)を消す。文言まで消すと
            # 「文A。[文B。](url)」の二文目を漏らし、無条件に残すと
            # 「文。[参考](url)」の末尾参照名を二文と誤判定する。
            # 「文A。[文B](url)。」のように句点がリンク外にある形も二文として捉える
            sent_text = re.sub(
                r"\[([^\]]*)\][ \t]+([。！？]?)",
                lambda m: m.group(1) + m.group(2)
                if m.group(2) or re.search(r"[。！？]", m.group(1))
                else "",
                sent_text,
            )
            sent_text = re.sub(r"（[^（）。！？]*）", "", sent_text)
            sent_text = re.sub(r"\*\*|\*|__", "", sent_text)
            if SENTENCE_SPLIT_PATTERN.search(sent_text):
                findings.append({
                    "rule": "one_sentence_per_line",
                    "line": line_no,
                    "severity": "warn",
                    "message": "一行に複数の文が含まれています。一文ごとに改行してください。",
                    "snippet": line.strip()
                })

        # 絵文字検知(見出し・本文問わず禁止)。コード片・URL・HTML の内部に
        # ある絵文字は装飾ではないため、可視テキストでは空白化済み
        emoji_matches = EMOJI_PATTERN.findall(scan_text)
        if emoji_matches:
            findings.append({
                "rule": "emoji_prohibited",
                "line": line_no,
                "severity": "warn",
                "message": f"絵文字({' '.join(emoji_matches[:3])})が検出されました。装飾を排し、平文で記述してください。",
                "snippet": line.strip()
            })

        # 引用ブロックや表行はアンチパターン例示等の可能性が高いため語彙スキャンをスキップ
        if row["quote_depth"] or kind in ("quote", "table"):
            previous_sentence = ""
            continue

        # 見出し行は補足カッコとダッシュのみ検査し、本文の語彙・構文検査はスキップ
        if kind == "heading":
            if _SUMMARY_HEADING.match(stripped) and metrics["char_count"] < 2000:
                findings.append({
                    "rule": "short_summary_heading",
                    "line": line_no,
                    "severity": "info",
                    "message": "短い文書に「まとめ」「おわりに」の見出しがあります。本文の繰り返しになっていないか確かめてください。新しい情報や結論の絞り込み、数値を担う場合は残してください。",
                    "snippet": stripped
                })
            if re.search(r"（(素の出力|いわゆる|概要|詳細|感謝と設計への反映)）", scan_text):
                findings.append({
                    "rule": "redundant_bracket",
                    "line": line_no,
                    "severity": "warn",
                    "message": "見出しに情報量の増えない補足カッコが含まれています。平文で簡潔に記述してください。",
                    "snippet": line.strip()
                })
            if DASH_PATTERN.search(mention_free):
                findings.append({
                    "rule": "dash_prohibited",
                    "line": line_no,
                    "severity": "warn",
                    "message": "見出しにダッシュ・罫線記号(—、―、——、─)が含まれています。単一の自然な句に書き直してください。",
                    "snippet": line.strip()
                })
            continue

        plain_text = re.sub(r"\*\*|\*|__", "", mention_free)
        if _BOLD_LABEL_ITEM.match(line):
            bold_label_lines.append(line_no)
        line_sentences = [clean for part in _LINE_SENTENCE_BREAK.split(plain_text) if (clean := part.strip())]

        # ダッシュ記号検知(本スキルの整形規範)
        if DASH_PATTERN.search(mention_free):
            findings.append({
                "rule": "dash_prohibited",
                "line": line_no,
                "severity": "warn",
                "message": "ダッシュ・罫線記号(—、―、——、─)が検出されました。挿入は括弧へ、言い換えは句点や読点へ書き直してください。",
                "snippet": line.strip()
            })

        # 文末コロン(全角「:」または半角「:」)検知。
        # 行末のコロンがコード・URL 等の不透明領域の内側にある場合は除く
        if re.search(r"[：:]$", stripped):
            uri_prefix_text = line_visible_text(analysis, line_no, frozenset(("inline_code",))).strip()
            last = len(line.rstrip()) - 1
            if (not uri_prefix_text.startswith("http")
                    and not range_overlaps_protected(analysis, row["start"] + last, row["start"] + last + 1, _METRIC_OPAQUE_KINDS)):
                findings.append({
                    "rule": "trailing_colon",
                    "line": line_no,
                    "severity": "warn",
                    "message": "文末にコロンが使われています。平文の句点(。)で終えるか前置きを省いてください。箇条書き中の「**用語**:説明」形式は対象外です。",
                    "snippet": line.strip()
                })

        # スロップ語彙
        if narrowed is None:
            slop_hits = [word for word in SLOP_WORDS if word in plain_text]
            slop_hits += [word for word, pattern in SLOP_WORD_PATTERNS if re.search(pattern, plain_text)]
        else:
            slop_hits = [word for word in slop_words if word in plain_text]
            slop_hits += [word for word, pattern, required in slop_patterns
                          if _may_match_literals(required, plain_text) and re.search(pattern, plain_text)]
        for word in slop_hits:
            findings.append({
                "rule": "slop_vocabulary",
                "line": line_no,
                "severity": "warn",
                "message": f"AI 頻出語彙「{word}」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、具体的な客観表現に置き換えてください。",
                "snippet": line.strip()
            })

        # 比喩動詞パターン
        kowareru_span = None
        for pattern, desc, required in metaphor_patterns:
            if not _may_match_literals(required, plain_text):
                continue
            if desc == "英語直訳「静かに壊れる (silently fail)」" and kowareru_span:
                # 「Xが壊れる」と「静かに壊れる」が同一動詞に二重反応することを防止
                for m in pattern.finditer(plain_text):
                    span = (m.start(), m.end())
                    if kowareru_span[0] <= span[0] and span[1] <= kowareru_span[1]:
                        continue
                    findings.append({
                        "rule": "metaphor_verb",
                        "line": line_no,
                        "severity": "warn",
                        "message": f"{desc}が検出されました。具体的な操作や状態変化に書き直してください。",
                        "snippet": line.strip()
                    })
                    break
                continue

            m = pattern.search(plain_text)
            if m:
                if desc == "比喩動詞「壊れる」":
                    kowareru_span = (m.start(), m.end())
                findings.append({
                    "rule": "metaphor_verb",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。具体的な操作や状態変化に書き直してください。",
                    "snippet": line.strip()
                })

        # フィラーパターン(文ごとに見て、同じ型は1行1件)
        for pattern, desc, required in filler_patterns:
            if _may_match_literals(required, plain_text) and any(pattern.search(sentence) for sentence in line_sentences):
                findings.append({
                    "rule": "meta_filler",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。単なる前置きや不要な飾りであれば削り、本題から書いてください。ただし、「何が大事か」という評価や主張そのものを担っている場合は、述語に移すなどして意味を残してください。" + FILLER_NOTES.get(desc, ""),
                    "snippet": line.strip()
                })

        # 見直しのきっかけにとどめる文の型
        for pattern, rule, message, required in info_sentence_patterns:
            if _may_match_literals(required, plain_text) and any(pattern.search(sentence) for sentence in line_sentences):
                findings.append({"rule": rule, "line": line_no, "severity": "info", "message": message, "snippet": stripped})

        # 文頭の「もちろん、」に数語だけ続く短い文
        for index, sentence in enumerate(line_sentences):
            if ("もちろん、" not in plain_text and "勿論、" not in plain_text):
                break
            if not _SHORT_MOCHIRON.match(sentence) or _MOCHIRON_ANSWER.match(sentence):
                continue
            if _ends_with_question(line_sentences[index - 1] if index else _last_context_sentence(sentence_before_line)):
                continue
            findings.append({
                "rule": "short_mochiron",
                "line": line_no,
                "severity": "info",
                "message": "文頭の「もちろん、」のあとに数語だけが続く短い文が検出されました。読み手が思いそうなことを先回りして認めているだけなら「もちろん、」を外してください。その含みを「当然、」などの別の語で補ったり、元にない理由や因果を足したりはしないでください。問いや依頼への答え、条件や前提の確認なら残してかまいません。",
                "snippet": stripped
            })
            break

        # 段落単位で集計済みの短文連打。引用は中身を伏せた「」に置き換えて
        # 短い文の数に入れない(「1位は「田中」。」を断片にしない)
        if line_no in fragment_run_lines:
            findings.append({
                "rule": "fragment_run",
                "line": line_no,
                "severity": "info",
                "message": "評価の語だけの短い文が3つ以上続いています(「効く。重い。安い。」など)。何がどうなのかが前後から分かる場合は、対象と評価を述語までつないでください。分からない場合は主語や理由を作らず、原文を残して書き手に確かめてください。小説の語りや詩など、書き手が意図した表現は残してかまいません。",
                "snippet": stripped
            })

        # ネガティブパラレリズム
        if _has_negative_parallelism(plain_text):
            findings.append({
                "rule": "negative_parallelism",
                "line": line_no,
                "severity": "info",
                "message": "「A ではなく B」構文が検出されました。誤解を解くために残す場合は否定の根拠を一文添え、それ以外は肯定文で直接書けないか検討してください。",
                "snippet": line.strip()
            })

        # 名詞の過剰連結(サ変名詞の数珠つなぎ)。最初の候補が閾値未満でも後続を
        # 評価し、閾値を満たす候補があれば 1 行につき 1 件だけ出す
        for m in NOUN_CHAIN_PATTERN.finditer(CHAIN_MASK_PATTERN.sub("・", plain_text)):
            segments = m.group(0).split("の")
            abstract_hits = sum(1 for s in segments if ABSTRACT_NOUN_PATTERN.search(s))
            if abstract_hits >= 2 or (len(segments) >= 4 and abstract_hits >= 1):
                findings.append({
                    "rule": "noun_chain",
                    "line": line_no,
                    "severity": "info",
                    "message": "名詞が助詞「の」で数珠つなぎに連結されています。過圧縮であれば、行為者を主語に据えて動詞の文へ展開するか検討してください。",
                    "snippet": line.strip()
                })
                break

    # 文書全体の型
    if len(bold_label_lines) >= 3:
        findings.append({
            "rule": "bold_label_list",
            "line": bold_label_lines[0],
            "severity": "info",
            "message": f"太字の見出し語とコロンで始まる箇条書きが{len(bold_label_lines)}行あります。値が日時や場所、担当、数値などの短い事実なら残してください。見出し語が抽象的で、値が一文の説明なら、地の文にするか、太字とコロンを外してください。並列関係が明確で読みやすい箇条書きは箇条書きのまま残し、項目の区別と数・順序は変えないでください。",
            "snippet": f"行: {', '.join(str(n) for n in bold_label_lines[:5])}"
        })

    # スコア計算(100 点満点からの減点方式: warn=5 点, info=2 点)
    penalty = sum(5 if f["severity"] in ("warn", "error") else 2 for f in findings)
    score = max(0, 100 - penalty)

    return {
        "score": score,
        "is_clean": len(findings) == 0,
        "metrics": metrics,
        "findings": findings
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="日本語文章の AI っぽさ機械検査リンター")
    parser.add_argument("file", nargs="?", help="検査対象の Markdown ファイルパス(指定なしの場合は標準入力)")
    parser.add_argument("--json", action="store_true", help="JSON 形式で出力")
    parser.add_argument("--strict", action="store_true", help="警告が 1 件でもあれば非ゼロ(終了コード 1)で終了")

    args = parser.parse_args()

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error opening file {args.file}: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        if sys.stdin is None:
            print("Error reading stdin: standard input is not available", file=sys.stderr)
            sys.exit(2)
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        try:
            content = sys.stdin.read()
        except (UnicodeDecodeError, OSError) as e:
            print(f"Error reading stdin: {e}", file=sys.stderr)
            sys.exit(2)

    result = lint_text(content)

    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        print("=" * 60)
        print(f"AI っぽさ 検査レポート (スコア: {result['score']}/100)")
        print("=" * 60)
        m = result["metrics"]
        print(f"・文字数: {m['char_count']} | 行数: {m['total_lines']}")
        print(f"・太字頻度: 1,000 字あたり {m['bold_per_1000']} 個 (情報基準: 3.0 超で表示)")
        print(f"・箇条書き比率: {round(m['list_ratio']*100, 1)}% (情報基準: 25% 超で表示)")
        print("-" * 60)

        if result["is_clean"]:
            print("[PASS] 検査ルールによる指摘はありません。")
        else:
            print(f"[NOTICE] {len(result['findings'])} 件の見直し候補が見つかりました。\n")
            for f in result["findings"]:
                sev = f"[{f['severity'].upper()}]"
                print(f"L{f['line']} {sev} {f['message']}")
                print(f"  > {f['snippet']}\n")

    if args.strict:
        warn_count = sum(1 for f in result["findings"] if f["severity"] in ("warn", "error"))
        if warn_count > 0:
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
