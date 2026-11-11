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
- 行内のダッシュ記号(em ダッシュ等)の検出を追加(本スキルの整形規範。
  v1.1.1 追従で上流の3ルール機械へ置き換え済み)
- 「〜に他なりません」の検出が波線の直前に限られていた問題を修正
- 「」で囲まれた言及(禁止表現の例示)を語彙・構文検査の対象から除外
- 助詞「の」で数珠つなぎになった名詞連結(過圧縮)の検出を追加
- 中黒(・)の日本語並列、一行の複数文、見出しの罫線(U+2500)の検出を追加

上流の変更で取り込んだ調整点:
- 比喩動詞の追加(Xが壊れる、踏み込む、引き返す、添える、収斂)と
  「Xが壊れる」「静かに壊れる」の同一動詞への二重反応の回避
- 同一文末の連続検出は段落(隣接する地の文)の内側に限定する
- 「A ではなく B」構文は上流の正確な字句走査で判定する
- v3.0.0 追従: calque(直訳語)の型1〜3を info で検出する
  (型4・型5と translated_term は不採用。docs/decision-records.md Y-21)
- 太字の印(**)が表示されない書き方の検査を markdown_bold.py から
  呼び出す(上流の判定機械を共通モジュールへ切り出したもの)
- 行ごとの正規表現走査を markdown_visibility.py の構造解析へ移行。
  コード・URL・HTML・参照定義などの不透明領域は可視テキストで
  空白化し、引用・表・HTML ブロックはブロック種別で除外する
- v1.1.1 追従: SLOP_WORD_PATTERNS(形で確かめる語彙)、フィラーの
  文単位走査と FILLER_NOTES、INFO_SENTENCE_PATTERNS、もちろん
  短答・断片連続・太字ラベル列挙・まとめ見出しの info 検出、
  リテラル事前絞り込み(_narrowed_document_rows)による走査削減。
  ダッシュ検査は単一パターンの禁止から3ルール(挿入・読点並べの
  閉じ・装飾)へ置き換え、区間・出典・引用・図罫線を免除し
  1文書3件に制限。否定構文は「AでもBでもない。Cだ。」
  「Aじゃない、Bです。」と段落内ソフト改行またぎを検出し、
  「でもある」で終わる対比を免除、多発は info で指摘する
- v3.0.0 追従(Phase 4): JSON 出力を上流 v2 形式(format_version=2)
  へ更新し、score を廃止して rule_penalty_score へ置き換えた。
  終了コードを再定義し(0: --strict/--fail-on の条件非該当、
  1: 条件該当、2: 使い方・入力の誤り、3: 内部エラー)、--fail-on を
  追加した。通常出力も上流の形式へ揃えた
  (docs/decision-records.md Y-19。--doc-type/--reader は導入しない。Y-20)

検出結果は機械的な見直し候補であり、SKILL.md の規範で正当な
記述と判断できるものはそのまま保持する。
標準ライブラリのみで動作する。
"""

import sys
import os
import re
import errno
import argparse
import functools
import json
import traceback
import unicodedata
from bisect import bisect_right
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from itertools import chain, compress
from operator import is_
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

try:
    from markdown_bold import bold_problems, _bold_problems_with_analysis
    from markdown_visibility import (
        analyze_markdown, decode_source, input_path_problem,
        line_visible_text, range_overlaps_protected,
        resolve_words, current_directory, WordsError, words_context,
        words_label,
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
    decode_source = _visibility_module.decode_source
    input_path_problem = _visibility_module.input_path_problem
    line_visible_text = _visibility_module.line_visible_text
    range_overlaps_protected = _visibility_module.range_overlaps_protected
    resolve_words = _visibility_module.resolve_words
    current_directory = _visibility_module.current_directory
    WordsError = _visibility_module.WordsError
    words_context = _visibility_module.words_context
    words_label = _visibility_module.words_label

# JSON 出力の形式の版。上流 v3.0.0 の lint JSON(形式2)に揃えた。
# 1 は score/is_clean を持つ旧形式。
LINT_FORMAT_VERSION = 2
# 上流 yomiyasu_lint.py v3.0.0 に対応する版(選択的移植のため全機能は揃っていない)。
__version__ = "3.0.0-port"

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

# ダッシュ類。em ダッシュ(—)、horizontal bar(―)、罫線(─ ━)。
# en ダッシュ(–)、長音(ー)、波ダッシュ(〜)は含めない。
DASH_CHARS = "—―─━"
_DASH_RUN = re.compile("[" + DASH_CHARS + "]+")
# 木構造や ASCII 図に使う罫線。これを含む行は図とみなし、ダッシュの検査をしない。
_DIAGRAM_CHARS = re.compile(r"[│┃├┣└┗┌┏┐┓┘┛┬┳┴┻┼╋╭╮╰╯]")
# 短い語を読点で3つ以上並べ、ダッシュで閉じて文を終える形(「速さ、軽さ、静けさ──。」)。文ごとに見る。
_LIST_ITEM = r"[^、。！？!?\s" + DASH_CHARS + "]{1,12}"
_DASH_LIST_ENDING = re.compile(
    r"(?:^|(?<=[。！？!?]))\s*" + _LIST_ITEM + "(?:、[ \t　]*" + _LIST_ITEM + "){2,}[ \t　]*[" + DASH_CHARS + "]+(?:[。．.]|$)")
# 出典ラベル、著者と書名、英語の著者名と書誌情報を手掛かりにする。短い行というだけでは除外しない。
_ATTRIBUTION_LABEL = re.compile(r"^(?:出典|引用元|著者|Source|Author)\s*[:：]", re.IGNORECASE)
_ATTRIBUTION_BOOK = re.compile(r"^[一-龥々ァ-ヴーA-Za-z .・'’-]+『[^』]+』(?:[ \t　]*(?:（[^）]*）|\([^)]*\)))*[。.]?$")
_ATTRIBUTION_ENGLISH = re.compile(r"^[A-Z][A-Za-z.'’−-]*(?:[ \t]+[A-Z][A-Za-z.'’−-]*)+,[ \t]+\S")
# 「人間」「作業時間」「目線」などの普通名詞は、区間を表す接尾辞と取り違えない。
_NON_ROUTE_ENDINGS = (
    "人間", "時間", "期間", "空間", "世間", "仲間", "手間", "中間", "瞬間", "隙間",
    "夜間", "昼間", "週間", "月間", "年間", "民間",
    "目線", "視線", "動線", "光線", "伏線", "生命線",
    "直線", "曲線", "点線", "実線", "破線", "罫線", "下線", "上線",
    "基線", "接線", "垂線", "水平線", "境界線", "配線", "回線", "無線", "有線", "電線",
    "方便", "利便", "不便", "郵便", "宅配便", "便乗", "便宜", "便益"
)


def _is_dash_attribution(text):
    text = text.strip()
    if not text or text[0] not in DASH_CHARS:
        return False
    credit = text.lstrip(DASH_CHARS + " \t　")
    return bool(_ATTRIBUTION_LABEL.match(credit) or _ATTRIBUTION_BOOK.match(credit)
                or _ATTRIBUTION_ENGLISH.match(credit))


def _mask_quoted_segments(text):
    """対応の取れた引用とリンクを、ネストを含めて一回の走査と累積和で伏せる"""
    closing = {"「": "」", "『": "』", "[": "]"}
    stacks = {closer: [] for closer in closing.values()}
    changes = [0] * (len(text) + 1)
    for index, char in enumerate(text):
        if char in closing:
            stacks[closing[char]].append(index)
        elif char in stacks and stacks[char]:
            start = stacks[char].pop()
            changes[start] += 1
            changes[index + 1] -= 1
    depth = 0
    result = []
    for index, char in enumerate(text):
        depth += changes[index]
        result.append(" " if depth else char)
    return "".join(result)


def _mask_route_dashes(text):
    """隣接する名詞ランをダッシュごとに一度だけ走査し、正規表現のバックトラックを避ける"""
    def noun_char(char):
        return "一" <= char <= "龥" or "ァ" <= char <= "ヴ" or char in "ー々"

    result = list(text)
    for match in _DASH_RUN.finditer(text):
        left, right = match.start(), match.end()
        if right - left != 1 or left == 0 or right == len(text):
            continue
        if not noun_char(text[left - 1]) or not noun_char(text[right]):
            continue
        end = right
        while end < len(text) and noun_char(text[end]):
            end += 1
        destination = text[right:end]
        for index, char in enumerate(destination):
            if char not in "間線便":
                continue
            end = index + 1
            suffix_length = 2 if destination.endswith("区間", 0, end) else 1
            if end > suffix_length and not destination.endswith(_NON_ROUTE_ENDINGS, 0, end):
                result[left] = " "
                break
    return "".join(result)


# ダッシュで補足や言い換えを挟む形(「今日——正確には昨日——連絡しました。」)
_DASH_INSERTION = re.compile("[" + DASH_CHARS + "]{1,2}[^" + DASH_CHARS + "。\n]{1,40}[" + DASH_CHARS + "]{1,2}")
# 小説などで点数が大きく下がらないよう、ダッシュの指摘は1文書あたりこの件数までにする。
DASH_FINDING_LIMIT = 3

# リンクの直後に著者などを添える区切り(「[記事](URL) — 著者氏」)。表示上のテキストでは URL が空白になる。
_LINK_ATTRIBUTION = re.compile(r"\][ \t]*[" + DASH_CHARS + "]+")


def _dash_finding(text, line_no, snippet):
    """散文の装飾ダッシュを1行1件だけ指摘する。図・区切り線・出典は散文ではない"""
    if not _DASH_RUN.search(text):
        return None
    if _is_dash_attribution(text):
        text = text.lstrip().lstrip(DASH_CHARS)
    text = _mask_route_dashes(_mask_quoted_segments(_LINK_ATTRIBUTION.sub("]", text))).strip()
    rest = text.strip(DASH_CHARS + " 　")
    if not _DASH_RUN.search(text) or _DIAGRAM_CHARS.search(text) or not rest:
        return None
    # 「――◆――」のように記号だけを挟んだ区切り線や、出典表記の行は散文ではない。
    if all(unicodedata.category(ch)[0] in "PSZ" or ch in DASH_CHARS for ch in rest):
        return None
    if _DASH_LIST_ENDING.search(text):
        rule = "dash_list_ending"
        message = ("名詞を読点で並べて末尾を「──」などのダッシュで閉じる書き方が検出されました。余韻を装う装飾に見えやすいため、"
                   "何についての列挙かを述語で言い切ってください。文脈から述語が分からない場合は、推測で補わず書き手に確かめてください。")
    elif _DASH_INSERTION.search(text):
        rule = "dash_insertion"
        message = ("補足や言い換えをダッシュで挟む書き方が検出されました。読点や助詞、括弧でつなぐか、文を分けてください。"
                   "ただし、小説や随筆で書き手が文体として使っている場合や、引用は残してかまいません。")
    else:
        rule = "dash_decoration"
        message = ("ダッシュ記号(—、―、──など)が検出されました。補足や余韻のための装飾であれば、読点や助詞、括弧でつなぐか、"
                   "文を分けてください。ただし、小説や随筆で書き手が文体として使っている場合や、引用は残してかまいません。")
    return {"rule": rule, "line": line_no, "severity": "warn", "message": message, "snippet": snippet}


_DASH_FINDING_DEFAULT = _dash_finding
_DASH_RUN_DEFAULT = _DASH_RUN

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
               r"(?<!搭乗)(?<!改札)(?<!品質)ゲート(?!ウ[ェエ]イ|ボール|キーパー)"),
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
    r"(?:(?<![ァ-ヴー])|(?<=レビュー)|(?<=リリース)|(?<=チェック)|(?<=デプロイ)|(?<=マージ)|(?<=テスト))(?<!搭乗)(?<!改札)(?<!品質)ゲート(?!ウ[ェエ]イ|ボール|キーパー)": ("ゲート",),
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
_SUMMARY_HEADING = re.compile(r"^(?:#{1,6}\s*)?(まとめ|おわりに)(?:\s+#+)?\s*$")

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

# 否定を重ねてから言い切る型(「車でも、家でもない。有頂天だ。」「これは努力じゃない、仕組みです。」)
# 二度否定してから言い切る文が続く形だけを見る(「何でもない」「とんでもない」、接続詞の「それでも、」は除く)。
_NOT_IDIOM = r"(?<!何)(?<!なん)(?<!まんざら)(?<!とん)"
_NEGATION_CONCLUSION_END = r"(?:[うくぐすつぬぶむるいだた]|だけ)(?:よね|よ|ね)?"
_NEGATION_NEGATIVE_END = (
    r"(?:[な無]い|[な無]かった|ません(?:でした)?)"
    r"(?:(?:の|ん)(?:だ|です|だった|でした|である|であった)|です|でした|でしょう|だろう|であろう)?(?:よね|よ|ね)?"
)
_NEGATION_EXTRA = re.compile(
    r"(?:[^。、]{1,15}(?:では|じゃ)ない。[^。]{0,15}|[^。、]{1,15}(?<!それ)(?<!今)(?<!いつ)(?<!誰)(?<!何)でも、[^。、]{1,15})"
    + _NOT_IDIOM + r"でもない。"
    + r"(?![^。！？!?]{0,40}" + _NEGATION_NEGATIVE_END + r"[。！!])"
    + r"[^。！？!?]{1,40}" + _NEGATION_CONCLUSION_END + r"[。！!]")
# 「これは努力じゃない、仕組みです。」(文ごとに見る)
_NEGATION_JANAI = re.compile(
    r"^(?:(?:でも|しかし|つまり|ただ|ただし|けれども?|けど|だが|それでも|だから)、)?"
    r"(?![い良]いじゃない、|すごいじゃない、|凄いじゃない、)"
    r"[^。、]{1,15}じゃない、[^。]{1,30}(?:です|だ)(?:よ|ね|よね)?[。！!]?$"
)
# 否定のあとに「でもある」と続ける文(「AではなくBでもある」)は、元の言い方のまま残す
_NEGATION_ALSO = re.compile(r"ではなく、?[^。]{1,40}?(?<!どこに)(?<!誰に)(?<!だれに)(?<!何)(?<!なん)(?<!いつ)でも(ある|あります|あった|ありました)")

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
    一文一行の規範では断片は行をまたぐため、行ごとの判定では拾えない。
    引用やリンク内の文は数に入れない(行またぎの引用も連結後に伏せる)"""
    hit_lines = set()
    for parts in _paragraph_prose_parts(analysis):
        joined = _mask_quoted_segments("".join(v for _, v in parts))
        if joined.count("。") + joined.count("！") < 3:
            continue
        offsets = []
        total = 0
        for _, v in parts:
            offsets.append(total)
            total += len(v)
        for match in _FRAGMENT_RUN.finditer(joined):
            index = bisect_right(offsets, match.start()) - 1
            hit_lines.add(parts[index][0])
    return hit_lines


def _extra_negation_line_numbers(analysis):
    """段落内のソフト改行をまたぐ否定の言い切り構文を、ブロックをまたがずに拾う。
    行ごとの検査と同じく「」内の言及は伏せる(行またぎの引用も連結後に伏せる)"""
    hit_lines = set()
    for parts in _paragraph_prose_parts(analysis):
        joined = _mask_quoted_segments("".join(v for _, v in parts))
        if "でもない。" not in joined:
            continue
        offsets = []
        total = 0
        for _, v in parts:
            offsets.append(total)
            total += len(v)
        for match in _NEGATION_EXTRA.finditer(joined):
            index = bisect_right(offsets, match.start()) - 1
            hit_lines.add(parts[index][0])
    return hit_lines


def _metrics_from_analysis(analysis):
    """語彙・文末検査と同じ不透明領域の境界で構造メトリクスを算出する。
    戻り値は (metrics, 点数計算用の地の文の字数)。地の文は行の見える文字から
    空白を除いたもので、見出し・見出しの罫線・水平線は含めない。"""
    plain_rows = []
    prose_chars = 0
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
            if row["kind"] not in ("heading", "heading_underline", "thematic_break"):
                prose_chars += len("".join(visible.split()))
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
    metrics = {"char_count": char_count, "total_lines": total_lines, "list_lines": list_lines,
               "list_ratio": round(list_ratio, 3), "bold_count": bold_count,
               "bold_per_1000": round(bold_per_1000, 2)}
    return metrics, prose_chars


def analyze_markdown_metrics(text: str) -> Dict[str, Any]:
    """太字頻度、箇条書き比率などの構造メトリクスを算出(引用文やコードブロックは除外)"""
    return _metrics_from_analysis(analyze_markdown(text))[0]


# rule_penalty_score の計算に使う重み。上流 v3.0.0 の _PENALTY_WEIGHTS などに対応する。
_PENALTY_WEIGHTS = {"error": 3, "warn": 2, "info": 1}
_PENALTY_FLOOR = 1000
_PENALTY_HALF = 40
# 文書単位の候補(太字・箇条書きのメトリクス)は地の文の長さで割らずに件数で効かせる
_DOCUMENT_RULE_WEIGHTS = {"excess_bold": 2, "excess_list": 2, "bold_label_list": 1}
_SUMMARY_RULES = ("negative_parallelism_density",)
# info の「見直しのきっかけ」の規則。上流の _V220_RULES・_V230_RULES・_V250_RULES に
# 対応し、点数を計算する前に除く(上流の _V240_RULES の slide_comma は --doc-type
# 依存のため本スキルでは実装しない。docs/decision-records.md Y-20)
_SCORE_EXCLUDED_RULES = ("calque", "metaphor_label", "say_hedge", "thin_evaluation",
                         "katakana_term", "dialogue_period", "narrative_density",
                         "copy_comma_noun", "bare_verb_chain", "project_term",
                         "renyo_noun", "ai_phrase")
_DASH_RULES = ("dash_decoration", "dash_insertion", "dash_list_ending")


def _rule_penalty_score(findings: list[dict], prose_chars: int, dash_hits: int) -> int:
    """行の候補の密度と文書単位の候補から、整数だけで目安を計算する。"""
    if not findings:
        return 100
    line_weight = 0
    document_weight = 0
    dash_found = 0
    for finding in findings:
        rule = finding["rule"]
        if rule in _DASH_RULES:
            dash_found += 1
        if rule in _DOCUMENT_RULE_WEIGHTS:
            document_weight += _DOCUMENT_RULE_WEIGHTS[rule]
        elif rule not in _SUMMARY_RULES:
            line_weight += _PENALTY_WEIGHTS[finding["severity"]]
    line_weight += max(0, dash_hits - dash_found) * _PENALTY_WEIGHTS["warn"]
    m = max(prose_chars, _PENALTY_FLOOR)
    num = 100 * _PENALTY_HALF * m
    den = (_PENALTY_HALF + document_weight) * m + 1000 * line_weight
    return max(1, min(99, (2 * num + den) // (2 * den)))


# 文末の後ろの飾り(絵文字・空白・閉じかっこ・矢印・波線と、対のない閉じ引用符)を除いて文の型を読む。
# 上流は絵文字の専用テーブルから字のclassを作るが、ここでは既存の EMOJI_PATTERN と同じ範囲に合わせる。
_END_KEYCAP = r"[0-9#*]\ufe0f?\u20e3"
_END_VISIBLE_CHARS = (
    "\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff\U0001f800-\U0001f8ff\U0001f900-\U0001f9ff\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff\u2600-\u27bf\u2300-\u23ff\u2b50-\u2b55"
)
_END_JOINER_CHARS = "\ufe0e\ufe0f\u200d\U000e0020-\U000e007f"
_END_SYMBOL_CHARS = "\u2b05-\u2b07\u2b1b-\u2b1c\u231a-\u231b\u23e9-\u23fa\u2934-\u2935\u3297\u3299\U0001f000-\U0001faff\U0001f1e6-\U0001f1ff"
_END_DECORATION_CHARS = _END_VISIBLE_CHARS + _END_JOINER_CHARS + _END_SYMBOL_CHARS
_END_DECORATION_CHAR = re.compile("[" + _END_DECORATION_CHARS + "]")
_END_DECORATION_RUN = r"(?:" + _END_KEYCAP + r"|[\s" + _END_DECORATION_CHARS + r"])*"
_END_BRACKETS = {"）": "（", ")": "(", "】": "【", "〕": "〔", "〉": "〈", "》": "《", "］": "［"}
_END_CLOSERS = "".join(_END_BRACKETS) + "←↑→↓〜～"
_END_QUOTES = {"」": "「", "』": "『", "”": "“", "’": "‘", '"': '"', "'": "'"}
_END_MARKS = "。．！？!?"
_END_BRACKET_AFTER_PREDICATE = re.compile(r"(?:です|ます|でした|ました|ません|ない|だ|た|る)$")


def _bracket_opens_sentence(text: str, position: int, closer: str) -> bool:
    """text[position] の閉じかっこと対の開きかっこが、文頭か、句点か述語の直後にあるか。

    見るのは閉じかっこの前の256字まで。そこで分からなければ除かない（長い行でも手間を抑える）。"""
    opener = _END_BRACKETS[closer]
    floor = max(0, position - 256)
    depth = 0
    index = position
    while index > floor:
        index -= 1
        char = text[index]
        if char == closer:
            depth += 1
        elif char == opener:
            if depth:
                depth -= 1
                continue
            before = index
            while before > floor and (text[before - 1].isspace() or _END_DECORATION_CHAR.match(text[before - 1])):
                before -= 1
            if not before:
                return True
            return before > floor and (text[before - 1] in _END_MARKS
                                       or bool(_END_BRACKET_AFTER_PREDICATE.search(text, max(0, before - 3), before)))
    return False


def _strip_end_decoration(text: str, closers: str = "") -> str:
    """文の終わりの後ろの飾りを除いた文を返す。飾りがなければ text をそのまま返す。

    句点、感嘆符、疑問符は残し、飾りとの並びの順も保つ。closers の字（閉じかっこ、矢印、波線と、
    呼び出し側が確かめた閉じ引用符）も飾りとして除く。閉じかっこは、対の開きかっこが文の頭か、句点か述語の直後に
    あるときだけ除く。"""
    position = len(text)
    marks = []
    removed = False
    while position:
        char = text[position - 1]
        if char in _END_MARKS:
            marks.append(char)
            position -= 1
        elif char == "\u20e3":
            removed = True
            position -= 1
            if position and text[position - 1] == "\ufe0f":
                position -= 1
            if position and text[position - 1] in "0123456789#*":
                position -= 1
        elif char.isspace() or _END_DECORATION_CHAR.match(char):
            removed = True
            position -= 1
        elif char in closers and (char not in _END_BRACKETS or _bracket_opens_sentence(text, position - 1, char)):
            removed = True
            position -= 1
        else:
            break
    if not removed:
        return text
    return text[:position] + "".join(reversed(marks))


# 文の途中で、句点の代わりに置いた絵文字の並び（「いかがでしたか😊 次回も…」）。並びは見える飾りの字で始まる。
_END_BREAK_RUN = re.compile(r"(?:" + _END_KEYCAP + r"|[" + _END_VISIBLE_CHARS + r"])"
                            r"(?:" + _END_KEYCAP + r"|[\s" + _END_DECORATION_CHARS + r"])*")
# 並びのあとが助詞なら、文が続いている（「いかがでしたか🚀という結び」「🍎を買う」）。
# 並びのあとが字（かな、漢字、英数字）でなく、かっこや記号のときも分けない（「〜です♪（笑）」）
_END_BREAK_CONTINUES = re.compile(
    r"(?:と|って|の|を|が|は|に|へ|や|か|から|まで|より|など|だけ|で(?![はも])|も(?!ちろん|し|っと|う)|ー)")
# 並びの前が助詞や読点なら、絵文字が語の代わりになっている（「設定は⚙ボタンから」）
_END_BREAK_HEAD_CHARS = "はがをのにでとへやも、，,：:"
_END_BREAK_PAIRS = (("「", "」"), ("『", "』"), ("（", "）"), ("(", ")"), ("【", "】"), ("“", "”"),
                    ("［", "］"), ("[", "]"))


def _decoration_breaks(sentence: str) -> list[str] | None:
    """句点の代わりに絵文字の並びを置いて次の文を続けた所で分けた文の並びを返す。分けられなければ None。

    分けた文は後ろに絵文字の並びを残す（呼び出し側が _strip_end_decoration で除く）。
    かっこや引用の中と、助詞や記号が続く所では分けない。"""
    if not _END_DECORATION_CHAR.search(sentence):
        return None
    pieces = []
    start = scanned = 0
    # 分けた所からのかっこの開きの数（開き − 閉じ）と、空白でない字があるか。長い行でも1回なめるだけにする
    balance = dict.fromkeys(_END_BREAK_PAIRS, 0)
    has_text = False
    length = len(sentence)
    for run in _END_BREAK_RUN.finditer(sentence):
        segment = sentence[scanned:run.start()]
        scanned = run.start()
        if segment:
            has_text = has_text or not segment.isspace()
            for pair in _END_BREAK_PAIRS:
                balance[pair] += segment.count(pair[0]) - segment.count(pair[1])
        end = run.end()
        word = end
        while word < length and sentence[word] in "*_":
            word += 1
        if word >= length or not sentence[word].isalnum() or _END_BREAK_CONTINUES.match(sentence, word):
            continue
        last = run.start()
        while last > start and sentence[last - 1].isspace():
            last -= 1
        if (not has_text or last == start or sentence[last - 1] in _END_BREAK_HEAD_CHARS
                or any(value > 0 for value in balance.values())):
            continue
        pieces.append(sentence[start:end])
        start = scanned = end
        balance = dict.fromkeys(_END_BREAK_PAIRS, 0)
        has_text = False
    if not pieces:
        return None
    pieces.append(sentence[start:])
    return pieces


def _end_quote_closers(analysis: dict) -> dict[int, str]:
    """行ごとに、文末の飾りとして除いてよい閉じ引用符を返す。

    同じ段落（箇条書きは項目ごと）のその行までに対の開き（「『“‘）がない閉じかぎと閉じ引用符だけを除く。
    "' は、その行までに1つしかなく、それがその行にあるときだけ除く。対になった引用（語への言及や会話）は除かない。"""
    allowed = {}
    for block in analysis["blocks"]:
        if block["kind"] not in ("paragraph", "list"):
            continue
        counts = dict.fromkeys(_END_QUOTES.values(), 0)
        for row in block["lines"]:
            visible = _prose_visible_text(analysis, row["line"])
            for opener in counts:
                counts[opener] += visible.count(opener)
            chars = "".join(closer for closer, opener in _END_QUOTES.items()
                            if closer in visible and counts[opener] == (1 if closer == opener else 0))
            if chars:
                allowed[row["line"]] = chars
    return allowed


def _end_closers_for(analysis: dict, line_no: int) -> str:
    """文の型を見る規則が、その行の文末で飾りとして除く字（閉じかっこ、矢印、波線と、対のない閉じ引用符）。"""
    allowed = analysis.get("_end_quote_closers")
    if allowed is None:
        allowed = analysis["_end_quote_closers"] = _end_quote_closers(analysis)
    return _END_CLOSERS + allowed.get(line_no, "")


_QUOTE_MARKS = re.compile(r"[「」『』\[\]]")


def _mask_quoted_segments_sparse(text: str) -> str:
    """_mask_quoted_segments と同じ結果を、括弧の記号だけを見て返す。

    文書全体に使う。文字ごとの繰り返しが主な手間なので、記号の位置だけを集めて差分で組み立てる。
    """
    closing = {"「": "」", "『": "』", "[": "]"}
    stacks = {closer: [] for closer in closing.values()}
    changes = {}
    for match in _QUOTE_MARKS.finditer(text):
        index = match.start()
        char = text[index]
        if char in closing:
            stacks[closing[char]].append(index)
        elif stacks[char]:
            start = stacks[char].pop()
            changes[start] = changes.get(start, 0) + 1
            changes[index + 1] = changes.get(index + 1, 0) - 1
    if not changes:
        return text
    pieces = []
    depth = 0
    cursor = 0
    for point in sorted(changes):
        if not changes[point]:
            continue
        pieces.append(" " * (point - cursor) if depth else text[cursor:point])
        cursor = point
        depth += changes[point]
    pieces.append(" " * (len(text) - cursor) if depth else text[cursor:])
    return "".join(pieces)

# 文頭の「〜(連体形)のは、」のあとに名詞を並べ、述語を書かずに終える文（「今回の改修で増えたのは、画面、帳票、通知。」）。
# 項目は格助詞（を・が・は・に・で・へ・から・まで・より）を含まず、名詞らしい字で終わる。読点（、，・）だけで並べるなら
# 3つ以上、「と・や・および」を交えるなら2つ以上。「〜など。」「〜の3つ。」「〜の3点。」で終わる形も当てる。
# 述語まで書いた文（です、だ、でした、に限る）、ダッシュで終わる文、限定の「〜のみ。」「〜だけ。」「〜ばかり。」は、
# 最後の項目が名詞の字で終わらないので当たらない。
_CLEFT_LIST_HEAD = r"^(?P<head>[^。！？!?]{0,60}?(?:[るたいうくすつぬむぶぐ]|な|[んい]だ))のは、"
_CLEFT_LIST_NOUN_END = r"(?:[一-龥々〆ヵヶァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ%％さ]|(?<!の)み)"
# 読点だけで区切る項目（項目の中の「と・や」はそのまま項目の字として読む）。動詞から作った名詞（言い回し、流れ、
# 見直し、書き出し）で終わる項目も認める。
_CLEFT_LIST_COMMA_ITEM = (r"(?:(?!から|より)[^、，,・。！？!?「」『』（）()\[\]\sをがはにでへ]){0,14}"
                          r"(?:" + _CLEFT_LIST_NOUN_END + r"|もの|こと|[しきれえげぎちせ]|(?<!ばか)り)")
# 「と・や・および」でも区切る項目（区切りの語を項目に含めず、区切り方を1つに決める）
_CLEFT_LIST_MIXED_ITEM = (r"(?:(?!から|より|および)[^、，,・。！？!?「」『』（）()\[\]\sをがはにでへとや]){0,14}"
                          r"(?:" + _CLEFT_LIST_NOUN_END + r"|もの)")
_CLEFT_LIST_TAIL = r"(?:など|の[0-9０-９一二三四五六七八九十]+[つ点])?[。！!]?$"
_CLEFT_LIST_COMMA = re.compile(_CLEFT_LIST_HEAD + _CLEFT_LIST_COMMA_ITEM
                               + r"(?:[、，・]" + _CLEFT_LIST_COMMA_ITEM + r"){2,}" + _CLEFT_LIST_TAIL)
_CLEFT_LIST_MIXED = re.compile(_CLEFT_LIST_HEAD + r"(?P<items>" + _CLEFT_LIST_MIXED_ITEM
                               + r"(?:(?:[、，・]|と|や|および)" + _CLEFT_LIST_MIXED_ITEM + r")+)" + _CLEFT_LIST_TAIL)
_CLEFT_LIST_JOINER = re.compile(r"[とや]|および")
_CLEFT_LIST_COMMA_MARK = re.compile(r"[、，・]")
# コード、リンク、脚注は空白に伏せてあるので、2字以上の空白の並びを名詞の仮の字に置き換え、ほかの空白は除いてから照合する
_CLEFT_LIST_MASKED_RUN = re.compile(r"\s{2,}")
_CLEFT_LIST_SPACE = re.compile(r"\s")
# 「のは」の前の動詞の語幹の漢字の並び（「変動したのは」なら「変動」）
_CLEFT_LIST_STEM = re.compile(r"[一-龥々〆ヵヶ]+(?=[ぁ-ん]*$)")
# 直前の文を探すときの文の終わりの字
_CLEFT_LIST_STOPS = "。！？!?"


def _cleft_list_head(sentence: str) -> str | None:
    """「〜のは、A、B、C。」の形なら「のは」の前までを返す。当たらなければ None。"""
    if "のは、" not in sentence:
        return None
    sentence = _CLEFT_LIST_SPACE.sub("", _CLEFT_LIST_MASKED_RUN.sub("Ｘ", sentence))
    comma = _CLEFT_LIST_COMMA.match(sentence)
    if comma:
        return comma.group("head")
    mixed = _CLEFT_LIST_MIXED.match(sentence)
    if not mixed:
        return None
    items = mixed.group("items")
    joiners = len(_CLEFT_LIST_JOINER.findall(items))
    # 読点だけの2項目（「目指したのは、速さ、軽さ。」）は当てない
    if not joiners:
        return None
    # 読点がなく「と・や」で1回つなぎ、最後の項目に「の」がある形（「父と母の笑顔」）は、1つの名詞句として当てない
    joiner = _CLEFT_LIST_JOINER.search(items)
    if (joiners == 1 and not _CLEFT_LIST_COMMA_MARK.search(items)
            and joiner is not None and "の" in items[joiner.end():]):
        return None
    return mixed.group("head")


def _cleft_list_premise(head: str, previous: str) -> bool:
    """直前の文が問いか、「のは」の前の動詞の語幹の漢字を含めば、前提を書いてあるとみる。"""
    end = _question_content_end(previous)
    if end and (previous[end - 1] in "？?" or previous.endswith(("か。", "か"), 0, end)):
        return True
    stem = _CLEFT_LIST_STEM.search(head)
    return bool(stem) and any(char in previous for char in stem.group())


def _cleft_list_join(analysis: dict, rows: list[dict], position: int, text: str) -> str:
    """rows[:position] の行を後ろから text の前につなぐ（改行で折り返した文を1つの文として読む）。
    最後の文が分かるだけ（句点などが2つになるまで）つなぐ。"""
    marks = sum(map(text.count, _CLEFT_LIST_STOPS))
    while position and marks < 2:
        position -= 1
        piece = _prose_visible_text(analysis, rows[position]["line"]).replace("__", "").replace("*", "").strip()
        marks += sum(map(piece.count, _CLEFT_LIST_STOPS))
        text = piece + text
    return text


def _cleft_list_previous(analysis: dict, line_no: int, before: str) -> str:
    """「〜のは、」の文の直前の文。同じ段落の前の文、なければ前の段落の最後の文、なければ直前の見出し。

    before はその行で「〜のは、」の文より前にある字。表、コード、引用などを挟んだときは前の文はないとみる。"""
    blocks = analysis["blocks"]
    places = analysis.get("_cleft_list_places")
    if places is None:
        places = analysis["_cleft_list_places"] = {
            row["line"]: (number, position) for number, block in enumerate(blocks)
            if block["kind"] in ("paragraph", "list") for position, row in enumerate(block["lines"])}
    number, position = places[line_no]
    text = _cleft_list_join(analysis, blocks[number]["lines"], position, before)
    end = max(map(text.rfind, _CLEFT_LIST_STOPS))
    if end >= 0:
        return _last_context_sentence(text[:end + 1])
    if not number or blocks[number - 1]["kind"] not in ("paragraph", "list", "heading"):
        return ""
    rows = blocks[number - 1]["lines"]
    return _last_context_sentence(_cleft_list_join(analysis, rows, len(rows), ""))


def _has_cleft_list_ending(analysis: dict, line_no: int, contexts: Sequence[tuple[str, str]], line_sentences: list[str], filler_patterns: Sequence[tuple]) -> bool:
    """行の文のどれかが、前提を書かずに「〜のは、A、B、C。」で終えていれば True。

    contexts は _rule9_context の行の文（引用を伏せた文と、同じブロックの次の文）。引用を伏せた文と伏せていない文の
    数が同じ行では、前の文を伏せていない文で見る（「」の中の語も前提に数える）。"""
    for index, (sentence, following) in enumerate(contexts):
        # 句点で終わらない文は、改行で折り返した文の途中でありうるので、ブロックの最後の文のときだけ当てる
        if following and not sentence.endswith(("。", "！", "!")):
            continue
        head = _cleft_list_head(sentence)
        # 文末の後ろの飾り（「画面、帳票、通知 🚀」）を除いて読む
        core = _strip_end_decoration(sentence, _end_closers_for(analysis, line_no))
        if head is None and core is not sentence:
            head = _cleft_list_head(core)
        # 頭が meta_filler の型の文（「重要なのは、」）は、そちらだけを出す
        if head is None or any(_may_match_literals(required, sentence) and (pattern.search(sentence) or pattern.search(core))
                               for pattern, _, required in filler_patterns):
            continue
        before = line_sentences if len(line_sentences) == len(contexts) else [item[0] for item in contexts]
        if not _cleft_list_premise(head, _cleft_list_previous(analysis, line_no, "".join(before[:index]))):
            return True
    return False
_LIST_MARKER_LINE = re.compile(r"^\s*([-*+]|\d+\.)\s+")
# AIへの指示残りは作者の意図を断定できないため info にとどめる。
# 書く行為の予告と、書き方・除外の条件が同居する型だけを見る。
_WRITING_ACTION = re.compile(
    r"(?:書(?:きます|く|いてみます|いていきます)|(?:説明|紹介|解説)し(?:ます|ていきます)|"
    r"まとめ(?:ます|る|ていきます)|お伝えし(?:ます|ていきます)|述べ(?:ます|る)|"
    r"振り返(?:ります|る|っていきます)|お話し?し(?:ます|ていきます)|お届けします|話していきます)[。！？!?]?$"
)
# 書き方の条件は、敬体の予告か、記事の範囲を示す書き出しの文だけで見る（小説の地の文や規程の文を除く）。
_RESIDUE_OPENER = r"^(?:この記事|本記事|本稿|このブログ|ここ|以下|今回)(?:では|は)"
_RESIDUE_OPENER_RE = re.compile(_RESIDUE_OPENER)
_WRITING_STYLE = re.compile(
    r"(?:トーン|文体|口調)で|(?:専門用語|箇条書き)を\s*(?:できるだけ|なるべく)?"
    r"(?:使わず|用いず|避け)|(?:AI|ＡＩ)(?:っぽさ|らしさ)(?:が出ないよう|を(?:抑え|なく|避け))|"
    r"飾らない言葉で|語り口で|トーンを意識|(?<![0-9０-９])[0-9０-９]+文?字(?:程度|以内|前後)?で"
)
_WRITING_LIMIT = re.compile(r"に(?:絞って|限定して|焦点を(?:当てて|絞って))|触れず|扱わず|立ち入らず|[はを]抜きにして")
_SCOPE_EXCLUSION = re.compile(
    _RESIDUE_OPENER + r"[^。！？!?]*"
    r"(?:扱いません|扱わない|触れません|触れない|省きます|省く|割愛します|省略します)[。！？!?]?$"
)
_READER_SCOPE = re.compile(r"^(?:この|本)?(?:マニュアル|手順書|ガイド|論文|研究)(?:では|は)")
_SCOPE_REFERENCE = re.compile(
    r"参照|ご覧|別途|付録|後述|後ほど|別の?[^。！？!?]{0,8}(?:記事|ページ|章|節|報告書?|資料|文書|ガイド)|"
    r"(?:後|次|前)の(?:章|節)|第[0-9０-９一二三四五六七八九十]+章"
)


def _rule9_context(analysis: dict) -> dict[int, list[tuple[str, str]]]:
    """新しい規則だけが使う、引用を伏せた地の文と、すぐ次の文。

    文に分ける前に、段落の区切りをまたいで対の引用を伏せる。元の行の幅を保つので、
    既存の行番号のまま使える。参照の文は、段落をまたいだ範囲の宣言を免除しない。
    """
    rows = analysis["lines"]
    parts = [(_prose_visible_text(analysis, row["line"]).replace("__", "").replace("*", "")
              if row["kind"] in ("paragraph", "list") and not row["quote_depth"] else "")
             for row in rows]
    masked = _mask_quoted_segments_sparse("\n".join(parts))
    # _mask_quoted_segments_sparse は引用の中の改行も伏せる。出力を改行で分けず、元の幅で切り出す
    offset = 0
    visible_lines = {}
    for row, part in zip(rows, parts):
        visible_lines[row["line"]] = masked[offset:offset + len(part)].strip()
        offset += len(part) + 1
    contexts = {}
    for block in analysis["blocks"]:
        if block["kind"] not in ("paragraph", "list"):
            continue
        records = []
        for row in block["lines"]:
            contexts[row["line"]] = []
            for sentence in _LINE_SENTENCE_BREAK.split(visible_lines[row["line"]]):
                if sentence.strip():
                    records.append((row["line"], sentence.strip()))
        for index, (line, sentence) in enumerate(records):
            following = records[index + 1][1] if index + 1 < len(records) else ""
            contexts[line].append((sentence, following))
    return contexts


def _has_instruction_residue(sentence: str, following: str) -> bool:
    writing = _WRITING_ACTION.search(sentence)
    if (writing and ("ます" in writing.group() or _RESIDUE_OPENER_RE.search(sentence))
            and _WRITING_STYLE.search(sentence)):
        return True
    if not (_SCOPE_EXCLUSION.search(sentence) or (writing and _WRITING_LIMIT.search(sentence))):
        return False
    # 読み手に向けた範囲の宣言と、そのすぐ隣の参照は有用な情報なので外さない。
    return not (_READER_SCOPE.search(sentence)
                or _SCOPE_REFERENCE.search(sentence) or _SCOPE_REFERENCE.search(following))


def _has_instruction_residue_core(sentence: str, following: str, closers: str = _END_CLOSERS) -> bool:
    """文末の後ろの飾り（「〜書いていきます 🚀」）を除いた文で、もう一度確かめる。飾りがなければ確かめない。

    句点の代わりに絵文字を置いて続けた文（「〜扱いません🙏 詳しくは〜」）は、分けた文ごとに次の文と合わせて確かめる。"""
    core = _strip_end_decoration(sentence, closers)
    if core is not sentence and _has_instruction_residue(core, following):
        return True
    pieces = _decoration_breaks(sentence)
    if not pieces:
        return False
    return any(_has_instruction_residue(_strip_end_decoration(piece, closers),
                                        pieces[index + 1] if index + 1 < len(pieces) else following)
               for index, piece in enumerate(pieces))

# 短い主語・主題の読点。判定は a〜t の順で、当てはまる除外条件があれば残す。
_PAUSE_KANJI = r"一-龥々〆ヵヶ"
_PAUSE_WORD = re.compile(r"[" + _PAUSE_KANJI + r"ぁ-んァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ]")
_PAUSE_OPEN = "「『（(“【［["
_PAUSE_CLOSE = "」』）)”】］]"
_PAUSE_BOUNDARY = "、，,。！？!?：:"
_PAUSE_LEAD_SYMBOLS = " \t　・※•●○◆◇■□▶▷→＊*-"
_PAUSE_CHECKBOX = re.compile(r"^\[[ xX]\]\s*")

# 助詞のかたまり（長いものから）。
_PAUSE_COMPOUND = sorted(set([
    "においては", "にとっては", "については", "に対しては", "によっては", "としては", "としても",
    "についても", "においても", "にとっても", "に対しても",
    "からは", "までは", "よりは", "へは", "とは", "では", "には", "にも", "でも", "とも", "からも",
    "までも", "へも", "ても",
]), key=len, reverse=True)
# 拾わない助詞のかたまり（接続・逆接・譲歩）
_PAUSE_SKIP_CHUNKS = {"でも", "ても", "とも", "としても", "によっては"}

# 文頭の接続・前置き・手紙の定型。句全体がこれに当たれば拾わない。
_PAUSE_CONNECTIVE = {
    "それでは", "これでは", "では", "しかも", "けれども", "それでも", "それにしても", "とはいえ",
    "ただ", "もっとも", "それとも", "そもそも", "つきましては", "少なくとも", "そのためには",
    "今でも", "なかでも", "中でも", "それには", "まずは", "最後には", "さらには", "ひいては", "ついては",
    "このたびは", "この度は", "平素は", "日頃は", "日ごろは", "先日は", "昨日は", "本日は", "今回も",
}
_PAUSE_CONNECTIVE_END = re.compile(r"的には$|的にも$")
# ほかの規則（meta_intro、meta_filler）がすでに拾う文頭の句。1つの読点に2つの候補を出さない。
_PAUSE_COVERED = re.compile(r"^(?:本記事では|ポイントは|(?:まず|ここで)?(?:重要|大切|大事)なのは|避けたいのは)$")

# 「が」の前が述語の終わり（逆接・前置きの「が、」）
_PAUSE_GA_CONJ_END = re.compile(
    r"(?:です|ます|でした|ました|ません|ませんでした|だ|だった|である|であった|た|る|い|ない|なかった|"
    r"う|く|ぐ|す|つ|ぬ|ぶ|む|よう|たい|らしい|ん|ある|いる|した|する|れる|せる|ている|ていた|ておく|けれど)$")
_PAUSE_GA_NOUN_HIRA = re.compile(r"(?:さん|さま|様|くん|ちゃん|こと|もの|とき|ところ|ほう|ため|の|さ|たち|ら|など|だけ|まで|ばかり|"
                          r"くらい|ぐらい|ほど|こそ|もと|うち|あと|まえ|わけ|はず|よう|みんな|それ|これ|あれ|どれ|ここ|そこ|どこ|誰|僕|私)$")
_PAUSE_NOUNISH_END = re.compile(r"[" + _PAUSE_KANJI + r"ァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ」』）)\]>%％]$")

_PAUSE_VERB_ATTR = (r"(?:[るたうくすつぬむぶぐ]|ない|ている|ていた|された|される|できる|した|する|った|んだ|いた|えた|れた|せた|"
             r"きた|だった|ような)")
_PAUSE_CLAUSE_IN = re.compile(r"(?<=[" + _PAUSE_KANJI + r"ぁ-んァ-ヴー])" + _PAUSE_VERB_ATTR +
                       r"(?=[" + _PAUSE_KANJI + r"ァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ【「『（(［\[]|の|こと|もの|とき|ところ|ほう)")
_PAUSE_OKURI_NOUN = re.compile(r"(?:問い合わせ|打ち合わせ|取り消し|申し込み|引き渡し|割り当て|振り込み|書き込み|読み込み|受け付け|"
                        r"立ち上げ|切り替え|切り出し|入れ替え|洗い出し|聞き取り|見積もり|取り込み|呼び出し|払い戻し|"
                        r"組み合わせ|貸し出し|締め|売り場|手当て|付け直し|使い方|考え方|進め方|書き方|作り)")
# 分裂文（〜のは、〜のが、〜ことが、）。
_PAUSE_CLEFT = re.compile(_PAUSE_VERB_ATTR + r"(?:の|こと)$|(?:かった|しい|たい|ない|な|だった)の$")
# 条件・場面・時の枠
_PAUSE_FRAME = re.compile(_PAUSE_VERB_ATTR + r"(?:場合|とき|時|際|ころ|あと|後|うち|ため|上|うえ|前|間|限り|範囲|以上|"
                   r"あいだ|のち|直前|直後|最中|途中|以降|以前|前後)(?:に|で)?$|"
                   r"(?:場合|とき|際)(?:に|で)?$|" + _PAUSE_VERB_ATTR + r"$")
_PAUSE_FRAME_CHUNKS = {"は", "も", "には", "では", "からは", "までは"}
# 人と指示語だけの主題（随筆の語りの間）
_PAUSE_PERSON = re.compile(r"(?:僕|ぼく|私|わたし|わたくし|俺|おれ|あたし|自分|彼女|彼|我々|われわれ|あなた|君|きみ)(?:たち|ら|達)?$|(?:の人|人たち|人々)$")
_PAUSE_DEMONSTRATIVE = re.compile(r"^(?:それ|これ|あれ|そこ|ここ|あそこ|こちら|そちら|どれ|どこ)$")
_PAUSE_FIXED_SUBJ = re.compile(r"(?:必要|こと|可能性|恐れ|おそれ|余地)$")
_PAUSE_NOMINAL_END = re.compile(r"(?:こと|もの)$|" + _PAUSE_VERB_ATTR + r"の$")
# 手紙の時候の挨拶「皆様には、ますます〜」（お客様は除く）
_PAUSE_LETTER_ADDRESS = re.compile(r"(?<!客)(?:様|さま|各位)$")
_PAUSE_LETTER_GREETING = re.compile(r"(?:ますます|益々|いよいよ|一層)")
# 並べの項目の前の句（名詞で終わる）。今回、現在のような副詞の名詞は1つだけでは並べにしない
_PAUSE_ADVERBIAL_NOUN = re.compile(r"(?:結果|ため|上|うえ|際|場合|とき|ところ|一方|今回|現在|今後|以前|当日|通常|実際|最初|最後|当初|従来)$")
_PAUSE_ITEM_START = re.compile(r"^\s*(?:[-*+•]|\d+[.)．])\s")
_PAUSE_LABEL_LINE = re.compile(r"^[^、，,]{0,12}$(?<![ぁ-ん。！？!?」』）)])")
# 「て」「で」で終わっても動詞のて形でない語（助詞の「について」「として」、つなぎの「そして」、副詞の「すべて」「改めて」）。
# pause_comma の掛かり先の形（_PAUSE_TE）と ai_phrase のて形の体言止めで使う
_TE_NOT_VERB = ("について", "によって", "として", "に関して", "に対して", "を通して", "にとって", "につれて", "において",
                "にあたって", "に当たって", "に際して", "をめぐって", "を巡って", "に沿って", "にわたって", "に先立って",
                "そして", "さて", "すべて", "全て", "かつて", "やがて", "改めて", "あらためて", "初めて", "はじめて", "決して",
                "けっして", "大して", "たいして", "極めて", "きわめて", "あえて", "敢えて", "かえって", "却って", "至って",
                "総じて", "概して", "がいして", "おしなべて", "強いて", "果たして", "はたして", "従って", "したがって",
                "よって", "次いで", "ついで", "併せて", "あわせて", "合わせて", "続いて", "揃って", "そろって", "あて", "宛て",
                "めがけて", "目がけて", "を通じて", "に応じて", "に基づいて", "に基いて", "に加えて", "に向けて", "を受けて",
                "をもって", "に従って", "を含めて", "に限って", "にかけて", "に比べて", "に伴って", "を除いて", "を経て",
                "にて", "せいで", "くらいで", "ぐらいで")
# 2.5.0: 読点のあとに動詞の「〜て」と連体の形の述語、名詞が続き、その名詞を目的語に取る形（店長は、慌てて逃げた客を追いかけた）。
# 読点を外すと「〜て」が主題の動作に掛かって読めるので、この読点は掛かり先を決めている。「て」は動詞の語幹の仮名（慌て、使っ、
# 書い）か1字の漢字の動詞（見、出）のあと、「で」は「ん」「い」のあと（読んで、急いで）だけを数える。助詞の「で」（会議で、
# 手元で）、「である」「ではなく」「すでに」「ので」と、「〜ている」「〜ておく」「〜ては」「〜ても」、_TE_NOT_VERB の語（として、
# 決して、のせいで）は数えない
_PAUSE_TE = (r"(?:(?<=[っいしきぎちにびみりえけげせぜてねべめれ])て|(?<=[見出寝着似煮経])て|(?<=[んい])で)"
             + "".join("(?<!" + re.escape(word) + ")" for word in _TE_NOT_VERB)
             + r"(?!い[るたなま]|る|き[たてま]|お[りくいき]|あ[るりげ]|は|も)")
_PAUSE_TE_ATTR_OBJECT = re.compile(r"[^、，,。！？!?]{1,8}?" + _PAUSE_TE + r"[^、，,。！？!?]{1,10}?" + _PAUSE_VERB_ATTR
                                   + r"[" + _PAUSE_KANJI + r"ァ-ヴー]{1,8}を")
# 2.5.0: 目的語の「を、」のあとに連体の形の節と名詞、助詞が続く形（鍵を、なくした人に届けた。資料を、急いで作った担当者に渡した）。
# 読点を外すと目的語が節の動詞の目的語に読めるので、この読点も掛かり先を決めている
_PAUSE_OBJECT_ATTACH = re.compile(r"(?:[^、，,。！？!?]{1,8}?" + _PAUSE_TE + r")?[^、，,。！？!?]{0,10}?" + _PAUSE_VERB_ATTR
                                  + r"[" + _PAUSE_KANJI + r"ァ-ヴー]{1,8}(?:に|へ|と|から|より|を)")
# 2.5.0: 6字以内の短い目的語の「を、」（設定を、変更したときに）。目的語は名詞（漢字、カタカナ、英数字）だけか、「名詞の名詞」で、
# 前に「この」「その」などを付けてよい。並べ（Aを、Bを、。AとBを、は名詞だけの形に当たらない）、7字以上の目的語、節の目的語
# （読んだ本を、）、送り仮名やカギ括弧、括弧を含む目的語、指示語と疑問の語だけの目的語（これを、何を、）、引用の中は拾わない。
# 読点で並べた名詞の最後の項目（メール、メモを、。前の句が8字以内の名詞の終わりなら並べとみなす）、読点のあとに別の主語や主題が
# 続く所（受付の流れを、後半は〜）、読点のあとの句にもう1つ「を」がある所（この画像を、ソフトを使って〜）も拾わない。
# 読み物（essay）では当てない（lint_text が決める）
_PAUSE_OBJECT_MAX = 6
_PAUSE_OBJECT_LIST_ITEM = 8
_PAUSE_OBJECT_QUESTION = frozenset(("何", "誰", "何か", "誰か", "何事", "何もの"))
_PAUSE_OBJECT_COMMA = re.compile(r"(?=を[、，,])")
_PAUSE_OBJECT_NOUN = re.compile(r"(?:この|その|あの|どの)?[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ・]+"
                                r"(?:の[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ]+)?")

_PAUSE_MAX_LEN = 15
_PAUSE_LIST_ITEM_MAX = 18
_PAUSE_SHORT_CLAUSE = 10


def _pause_comma_chunk(t: str, i: int) -> tuple[str, int]:
    for comp in _PAUSE_COMPOUND:
        st = i + 1 - len(comp)
        if st >= 0 and t[st:i + 1] == comp:
            prev = t[st - 1] if st > 0 else ""
            if comp.startswith("と") and prev in "こひもあ":
                continue
            if comp in ("では", "でも") and prev in "ん":
                continue
            if comp.startswith("に") and prev in "な":
                continue
            return comp, st
    return t[i], i

def _pause_comma_next_subject(after: str) -> bool:
    parts = re.split(r"(、|。)", after)
    text = ""
    for k in range(0, len(parts), 2):
        seg = parts[k]
        text += seg
        # 並べの1項目は目的語の「を」を含まない（「〜方法に変え、」は項目にしない）。
        is_list_item = (len(seg) <= _PAUSE_LIST_ITEM_MAX and not re.search(r"[ぁ-ん]{2,}$", seg) and not re.search(r"[をにでへとがはも]$", seg)
                        and "を" not in seg and k + 1 < len(parts) and parts[k + 1] == "、")
        if not is_list_item:
            break
        text += "、"
    for m in re.finditer(r"(が|は)", text[:60]):
        before = text[:m.start()]
        if not before or before[-1] in "、":
            continue
        if m.group(1) == "が":
            if _PAUSE_GA_CONJ_END.search(before) and not _PAUSE_GA_NOUN_HIRA.search(before):
                continue
            if _PAUSE_FIXED_SUBJ.search(before) and re.match(r"(?:あ|な|でき|大き|高)", text[m.end():]):
                continue
        # 「〜ことが」「〜するのが」は名詞化した主語なので、助詞の「と」「の」と分ける。
        nominal = _PAUSE_NOMINAL_END.search(before)
        if m.group(1) == "は" and not nominal:
            if re.search(r"(?:で|に|と|て|から|まで|へ|より|だけ|ので)$", before):
                continue
        if before[-1] in "をにへとのやか" and not nominal:
            continue
        return True
    return False

def _pause_comma_quote_blocks(phrase: str) -> list[str]:
    """句の中のかっこの中身を返す。"""
    out, depth, cur = [], 0, []
    for ch in phrase:
        if ch in _PAUSE_OPEN:
            depth += 1
            if depth == 1:
                cur = []
                continue
        if ch in _PAUSE_CLOSE and depth > 0:
            depth -= 1
            if depth == 0:
                out.append("".join(cur))
                continue
        if depth > 0:
            cur.append(ch)
    return out

def _pause_comma_context(text: str) -> tuple[list[int], list[int], list[int], list[tuple[int, int]], list[int]]:
    """深さ、句の頭、文の範囲、文頭判定の累積表を行につき1回作る。"""
    depths, phrase_starts, sentence_ids, spans = [], [0], [], []
    nonlead = [0]
    depth, boundary, sentence_start = 0, 0, 0
    for i, ch in enumerate(text):
        if ch in _PAUSE_OPEN:
            depth += 1
        depths.append(depth)
        sentence_ids.append(len(spans))
        if depth == 0:
            if ch in _PAUSE_BOUNDARY:
                boundary = i + 1
            if ch in "。！？!?":
                spans.append((sentence_start, i))
                sentence_start = i + 1
        phrase_starts.append(boundary)
        nonlead.append(nonlead[-1] + (ch not in _PAUSE_LEAD_SYMBOLS + _PAUSE_OPEN))
        if ch in _PAUSE_CLOSE and depth > 0:
            depth -= 1
    spans.append((sentence_start, len(text)))
    return depths, phrase_starts, sentence_ids, spans, nonlead


_PAUSE_PARTICLE_COMMA = re.compile(r"(?=(は|が|も)、)")
# 「Aも、Bも〜」のあとの「も」（「最も」「もの」は除く）
_PAUSE_LATER_MO = re.compile(r"(?<!最)[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9）」』]も(?!の)")
_PAUSE_LIST_AND = re.compile(r"[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9さみ](?:と|や)[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9]")


def _pause_comma_phrase_end(t: str, k: int, depth: list[int]) -> int:
    """位置 k から、深さ0の次の句の区切りの位置を返す。"""
    n = len(t)
    while k < n and not (depth[k] == 0 and t[k] in _PAUSE_BOUNDARY):
        k += 1
    return k


def _pause_comma_prev_segment(t: str, j: int, starts: list[int]) -> tuple[str | None, int]:
    """句の頭 j の直前が読点のとき、その前の句を返す（なければ None）。"""
    if j < 2 or t[j - 1] not in "、，,":
        return None, 0
    k = starts[j - 2]
    return t[k:j - 1].lstrip(_PAUSE_LEAD_SYMBOLS), k


def _pause_comma_list_before(t: str, j: int, starts: list[int]) -> bool:
    """句が、並んだ名詞の最後の項目か（「A、B、Cは、」「AやB、Cは、」）。"""
    prev, k = _pause_comma_prev_segment(t, j, starts)
    if not prev or not _PAUSE_NOUNISH_END.search(prev) or _PAUSE_ADVERBIAL_NOUN.search(prev):
        return False
    if _PAUSE_LIST_AND.search(prev):
        return True
    prev2, _ = _pause_comma_prev_segment(t, k, starts)
    return bool(prev2 and _PAUSE_NOUNISH_END.search(prev2) and not _PAUSE_ADVERBIAL_NOUN.search(prev2))


def _pause_comma_hits(plain_text: str) -> list[tuple[int, str, str]]:
    """見える1行から (助詞の位置, かたまり, 句) を出現順に返す。"""
    t = plain_text
    if not any(p in t for p in ("は、", "が、", "も、")):
        return []
    depth, starts, sentence_ids, spans, nonlead = _pause_comma_context(t)
    positions = [m.start() for m in _PAUSE_PARTICLE_COMMA.finditer(t)]
    # r の同じかたまりの出現数。複合助詞の接尾辞も数える。
    # 句ごとの sent.count や文の切り出しを避ける。
    counts = [{} for _ in spans]
    for i in positions:
        # 引用の中と、述語のあとの「が、」（逆接）は並べに数えない。
        if depth[i] > 0:
            continue
        if t[i] == "が":
            pre = t[max(0, i - 8):i]
            if _PAUSE_GA_CONJ_END.search(pre) and not (_PAUSE_GA_NOUN_HIRA.search(pre) or _PAUSE_NOUNISH_END.search(pre)):
                continue
        counts_in_sentence = counts[sentence_ids[i]]
        for chunk in _PAUSE_COMPOUND + ["は", "が", "も"]:
            if t.startswith(chunk, max(0, i + 1 - len(chunk)), i + 1):
                counts_in_sentence[chunk] = counts_in_sentence.get(chunk, 0) + 1
    hits = []
    unquoted = None
    for i in positions:
        # a: 引用の中。b: 長い助詞のかたまりから照合。c: 接続・譲歩。
        if depth[i] > 0:
            continue
        chunk, cstart = _pause_comma_chunk(t, i)
        if chunk in _PAUSE_SKIP_CHUNKS:
            continue
        # d: 句の頭の箇条書き記号とチェックボックスを除く。
        j = starts[cstart]
        phrase = _PAUSE_CHECKBOX.sub("", t[j:cstart].lstrip(_PAUSE_LEAD_SYMBOLS)).lstrip(_PAUSE_LEAD_SYMBOLS)
        if not phrase or not _PAUSE_WORD.search(phrase):
            continue
        # e: 引用から続く句。f: 逆接の「が」。g: て形。
        if phrase[0] in _PAUSE_CLOSE or (phrase[0] == "と" and j >= 1 and t[j - 1] in "、，,"):
            continue
        if (chunk == "が" and _PAUSE_GA_CONJ_END.search(phrase)
                and not (_PAUSE_GA_NOUN_HIRA.search(phrase) or _PAUSE_NOUNISH_END.search(phrase))):
            continue
        if chunk in ("は", "も") and re.search(r"(?:て|で)$", phrase):
            continue
        if chunk == "も" and re.search(r"(?:けれど|しか|それで|それに|ど)$", phrase):
            continue
        # h: 接続・定型。i: 既存規則が拾う文頭。
        sstart, send = spans[sentence_ids[i]]
        at_start = nonlead[j] == nonlead[sstart]
        whole = phrase + chunk
        if whole in _PAUSE_CONNECTIVE or _PAUSE_CONNECTIVE_END.search(whole):
            continue
        if at_start and _PAUSE_COVERED.match(whole):
            continue
        if chunk == "には" and _PAUSE_LETTER_ADDRESS.search(phrase) and _PAUSE_LETTER_GREETING.match(t, i + 2):
            continue
        # j: 引用を含む主語。k: 空白を除いて15字を超える句。
        if re.search(r"[」』”）)]と", phrase):
            continue
        if any(re.search(r"[、。！？!?]", inner) or len(inner) > 12
               for inner in _pause_comma_quote_blocks(phrase)):
            continue
        plen = len(re.sub(r"\s", "", phrase))
        if plen > _PAUSE_MAX_LEN:
            continue
        # l: 分裂文。m: 条件・場面。n: 問いの節。
        if chunk in ("は", "が") and _PAUSE_CLEFT.search(phrase):
            continue
        if chunk in _PAUSE_FRAME_CHUNKS and _PAUSE_FRAME.search(phrase):
            continue
        if phrase.endswith("か") and plen > _PAUSE_SHORT_CLAUSE:
            continue
        # o: 句の中の主語。p: 送り仮名の名詞を伏せて節を調べる。
        if len(phrase) > 1 and re.search(r"[^、]が(?!、)|[^でにとて]は(?!、)", phrase[:-1]):
            continue
        masked = _PAUSE_OKURI_NOUN.sub(lambda m: "名" * len(m.group(0)), phrase)
        if plen > _PAUSE_SHORT_CLAUSE and _PAUSE_CLAUSE_IN.search(masked):
            continue
        # q: あとの主語。先頭60字と、その直後の定型を判定できれば足りる。
        # 並んだ語句の1項目（18字まで）の終わりを見分ける余裕も含め84字に限り、長い接尾辞をコピーしない。
        # かっこの中（引用や題名）の助詞と読点は、あとの主語や並べに数えない。
        if unquoted is None:
            unquoted = "".join("〇" if d else ch for ch, d in zip(t, depth))
        after = unquoted[i + 2:min(send + 1, i + 2 + 84)]
        if _pause_comma_next_subject(after) or _PAUSE_TE_ATTR_OBJECT.match(after):
            continue
        # r: 同じ文で並んだ句、句の中で並んだ語、直前の「と、」「や、」。
        if counts[sentence_ids[i]].get(chunk, 0) > 1:
            continue
        if re.search(r"[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9さみ](と|や)[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9]", phrase):
            continue
        if j >= 2 and t[j - 2] in "とや" and t[j - 1] == "、":
            continue
        if _pause_comma_list_before(t, j, starts):
            continue
        if chunk.endswith("も") and _PAUSE_LATER_MO.search(t[i + 2:_pause_comma_phrase_end(t, i + 2, depth)]):
            continue
        # s: 人と指示語。t: 外すと同じ字がつながる所。
        if _PAUSE_PERSON.search(phrase) or _PAUSE_DEMONSTRATIVE.match(phrase):
            continue
        if i + 2 < len(t) and t[i + 2] == t[i]:
            continue
        hits.append((i, chunk, phrase))
    return hits


def _pause_comma_object_hits(plain_text: str) -> list[tuple[int, str, str]]:
    """2.5.0: 見える1行から、短い目的語の「を、」の (「を」の位置, "を", 目的語) を出現順に返す。"""
    t = plain_text
    if not any(p in t for p in ("を、", "を，", "を,")):
        return []
    depth, starts, sentence_ids, spans, _ = _pause_comma_context(t)
    hits = []
    unquoted = None
    for match in _PAUSE_OBJECT_COMMA.finditer(t):
        i = match.start()
        if depth[i] > 0:
            continue
        j = starts[i]
        phrase = _PAUSE_CHECKBOX.sub("", t[j:i].lstrip(_PAUSE_LEAD_SYMBOLS)).lstrip(_PAUSE_LEAD_SYMBOLS)
        if (len(phrase) > _PAUSE_OBJECT_MAX or not _PAUSE_OBJECT_NOUN.fullmatch(phrase)
                or phrase in _PAUSE_OBJECT_QUESTION):
            continue
        prev, _ = _pause_comma_prev_segment(t, j, starts)
        if prev and (prev.endswith("を") or (len(prev) <= _PAUSE_OBJECT_LIST_ITEM and _PAUSE_NOUNISH_END.search(prev))):
            continue    # Aを、Bを、の2つ目からと、A、Bを、
        if "を" in t[i + 2:_pause_comma_phrase_end(t, i + 2, depth)]:
            continue    # Aを、Bを、の1つ目と、読点のあとの句にもう1つの目的語
        if unquoted is None:
            unquoted = "".join("〇" if d else ch for ch, d in zip(t, depth))
        if _pause_comma_next_subject(unquoted[i + 2:min(spans[sentence_ids[i]][1] + 1, i + 2 + 84)]):
            continue    # 読点のあとに別の主語や主題が続く
        if _PAUSE_OBJECT_ATTACH.match(unquoted, i + 2):
            continue    # 掛かり先を決める読点（鍵を、なくした人に）
        hits.append((i, "を", phrase))
    return hits


def _pause_comma_line_hits(analysis: dict, objects: bool = False) -> dict[int, list[tuple[int, str, str]]]:
    """段落と箇条書きの1項目ごとに、見える行をつないで当てる（行をまたぐ文と引用を1つに読む）。
    行番号から、その行の見える文字での (助詞の位置, かたまり, 句) の並びへの表を返す。
    objects が真なら、短い目的語の「を、」（_pause_comma_object_hits）も位置の順に混ぜる（2.5.0）。"""
    out = {}

    def flush(unit: list[tuple[int, str]], kind: str) -> None:
        if not unit:
            return
        joined = "".join(plain for _, plain in unit)
        offsets, pos = [], 0
        for line_no, plain in unit:
            offsets.append(pos)
            out[line_no] = []
            pos += len(plain)
        # 段落が句点なしにかなや読点で終わるときは、文の途中で切れていてあとが見えないので、その文では拾わない
        # （名詞で終わる題名のような行は拾う）。
        tail = len(joined)
        if kind == "paragraph" and re.search(r"[ぁ-ん、，,]$", joined.rstrip()):
            tail = max(joined.rfind(ch) for ch in "。！？!?")
        hits = _pause_comma_hits(joined)
        if objects:
            hits = sorted(hits + _pause_comma_object_hits(joined))
        for i, chunk, phrase in hits:
            if i > tail:
                continue
            k = bisect_right(offsets, i) - 1
            out[unit[k][0]].append((i - offsets[k], chunk, phrase))
        del unit[:]

    for block in analysis["blocks"]:
        kind = block["kind"]
        if kind not in ("paragraph", "list"):
            continue
        unit = []
        for row in block["lines"]:
            if row["quote_depth"] or row["kind"] not in ("paragraph", "list"):
                flush(unit, kind)
                continue
            plain = _prose_visible_text(analysis, row["line"]).strip().replace("__", "").replace("*", "")
            if not plain:
                flush(unit, kind)
                continue
            # 新しい項目と、短く名詞で終わる見出しのような行（「■影響」）のあとでは、つながない。
            if unit and (_PAUSE_ITEM_START.match(row["raw"]) or _PAUSE_LABEL_LINE.match(unit[-1][1])):
                flush(unit, kind)
            unit.append((row["line"], plain))
        flush(unit, kind)
    return out


class _V220Lazy:
    """初めて使うときに組む正規表現（2.2.0 の規則の正規表現は、当たる手掛かりがある文書でだけ要るので、読み込みのときには
    組まない。lint を CLI で1文書ずつ動かすときの起動の時間を延ばさないため）。組んだあとは re.Pattern の関数をそのまま持つ。"""

    search: Callable[..., re.Match[str] | None]
    match: Callable[..., re.Match[str] | None]
    fullmatch: Callable[..., re.Match[str] | None]
    finditer: Callable[..., Iterator[re.Match[str]]]
    findall: Callable[..., list]
    sub: Callable[..., str]
    split: Callable[..., list[str]]

    def __init__(self, pattern: str, flags: int = 0) -> None:
        self.pattern = pattern
        self._flags = flags

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        compiled = re.compile(self.pattern, self._flags)
        for method in ("search", "match", "fullmatch", "finditer", "findall", "sub", "split"):
            setattr(self, method, getattr(compiled, method))
        return getattr(compiled, name)


_V220_MESSAGE_TAIL = "の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。"
_V220_QUOTES = _V220Lazy(r"“[^”\n]*”|\"[^\"\n]*\"|‘[^’\n]*’")
_V220_IDENTIFIER = _V220Lazy(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[_./\\][A-Za-z0-9]+)+[_./]?|(?<![a-z])[a-z]+[A-Z][A-Za-z0-9]*|[_./\\][A-Za-z0-9_]+")
_V220_SENTENCE = _V220Lazy(r"[^。．！？!?|｜]+[。．！？!?]*")
_LABEL_MAX = 8
_LABEL_COMMON = frozenset((
    "概要 背景 目的 手順 結果 まとめ はじめに おわりに 注意 注意点 前提 課題 対策 原因 "
    "準備 作り方 進め方 使い方 やり方 読み方 書き方 考え方 そのほか その他 参考 参考文献 "
    "付録 補足 備考 要約 結論 考察 方法 経緯 現状 影響 今後 次回 予定 日程 費用 "
    "体制 対象 範囲 方針 構成 仕様 設計 実装 導入 設定 環境 要件 機能 特徴 制限 "
    "制約 問題 解決策 謝辞 用語 定義 例 実例 例文 質問 回答 連絡先 問い合わせ "
    "お問い合わせ 変更点 変更履歴 更新履歴 履歴 一覧 目次 序文 序章 終章 本文 内容 詳細 "
    "評価 検証 試験 運用 保守 監視 障害 対応 復旧 再発防止 再発防止策 振り返り 所感 "
    "感想 学び 教訓 議題 決定事項 宿題 出席者 参加者 日時 場所 持ち物 料金 価格 "
    "申し込み 申込 締め切り 期限 期間 注意事項 留意事項 概略 全体像 仕組み 流れ 効果 "
    "成果 実績 比較 分析 調査 測定 計画 提案 依頼 報告 お知らせ ご案内 案内 概況 "
    "結び おわり 終わり あとがき まえがき 序論 本論 緒言 背景と目的 利点 欠点 長所 短所 "
    "前提条件 動作環境 必要なもの インストール セットアップ トラブルシューティング ライセンス 関連 "
    "関連資料 関連項目 参照 出典 注 脚注 当番 本番 順番 定番 一番 番号 係 "
    "変更 再現 再現手順 決まり 道具 限界 命名 スクリプト チェックポイント 修正 不具合 動作 期待する動作 "
    "実際の動作 回避策 移行 後片付け 片付け 後始末 引き継ぎ 切り戻し "
    # 文書の題によく使う語
    "資料 記録 メモ ノート 日報 週報 月報 議事録 手順書 仕様書 提案書 企画書 説明書 "
    "マニュアル ガイド 告知 通知 連絡 規約 規程 日記 雑記 覚え書き 備忘録 下書き 草稿 "
    "原稿 索引 用語集 年表 略歴 経歴 自己紹介 紹介 プロフィール 挨拶 あいさつ お願い "
    "お詫び おわび ご報告 ご連絡 ご依頼 ご提案 募集 求人 告示 公告 通達 時系列 経過 "
    "タイムライン あらすじ 登場人物 配役 見出し 本文 題名 題 タイトル 件名 "
).split())
_LABEL_NUMBERING = _V220Lazy(r"^(?:[0-9０-９]+[.)．）]|[（(][0-9０-９]+[)）]|[①-⑳]|第[0-9０-９一二三四五六七八九十]+[章節部回条])")
_LABEL_MARKS = "「『“\"（("
# 漢字と仮名でない字（伏せる前の行から、ラベルになりうる字だけを残すのに使う。漢字の範囲の正規表現はこの1つだけにする）
_LABEL_ASCII = _V220Lazy(r"[A-Za-z0-9０-９Ａ-Ｚａ-ｚ]")
_LABEL_NOT_JAPANESE = _V220Lazy(r"[^ぁ-んァ-ヴー一-龥々〆ヵヶ]+")
_LABEL_ENDINGS = ("の横", "のそば", "係", "番")
# 「関係」「番号」などと、宛名や人の呼び方（田中様、各位、御中）で終わる語はラベルにしない
_LABEL_NOT_ENDINGS = ("関係", "連係", "一番", "二番", "順番", "番号", "様", "さま", "殿", "各位", "御中", "さん", "くん", "ちゃん",
                      "先生", "氏")
# ラベルを見るのは、本文（その行のほかの文字）がこの字数以上ある文書だけ（本文がほとんどない文書では、語が本文に出てこないことが
# 比喩の手掛かりにならない）
_LABEL_MIN_BODY = 60
# 語と語を区切る記号（設計 — 実装、確認・修正、手順：準備）。見出しの中にあれば一語のラベルではない
_LABEL_SEPARATED = _V220Lazy(r"[^\s—―─━・/／:：、，,|｜~〜\-–]\s*[\s—―─━・/／:：、，,|｜~〜\-–]+\s*[^\s—―─━・/／:：、，,|｜~〜\-–]")
# 一語の近似: 漢字やカタカナのあとに助詞か「な」（の、と、や、を、に、が、は、で、へ、も、な）が続かず、
# 動詞や形容詞が名詞を修飾する形（使った技術、新しい道具）も、「から」「まで」などの句も、動詞で終わる形（いつ読むか）もないこと。
# 正規表現にすると漢字の範囲の字の組を組むのに時間がかかる（CLI の起動が遅くなる）ので、字ごとに調べる
_LABEL_AFTER_NOUN = "のとやをにがはでへもな"
_LABEL_ATTRIBUTIVE = "たるいうくすつむぶぐだ"
_LABEL_ANYWHERE = "のをがへ"
_LABEL_BETWEEN = "とやにでは"
_LABEL_VERB_END = "うくすつぬむぶぐる"
# 名前の語で終わるふつうの見出し（変更内容、確認方法、受信処理、冪等性、障害報告書）。「〜方」は仮名のあと（作り方、示し方）だけ
_LABEL_ABSTRACT_ENDINGS = (
    "性", "化", "さ", "み", "率", "量", "数", "値", "額", "費", "報", "処理", "方法", "方式", "内容", "制御", "報告", "報告書", "書",
    "事項", "事象", "一覧", "手順", "管理", "機能", "対応", "検証", "確認", "結果", "状況", "計画", "分析", "調査", "設計", "仕様",
    "要件", "概要", "方針", "表", "図", "例", "編", "章", "版", "案", "論", "法", "点", "策", "順", "式", "型", "層", "群", "集", "録",
    "記", "票", "欄", "項目", "条件", "基準", "形式", "構成", "構造", "一覧表", "履歴", "環境", "作業", "操作", "画面", "設定", "対象",
    "範囲", "期間", "日程", "体制", "役割", "担当", "権限", "規則", "ルール", "ポリシー", "ガイド",
)


def _v220_kanji(char: str) -> bool:
    return "一" <= char <= "龥" or char in "々〆ヵヶ"


def _v220_katakana(char: str) -> bool:
    return "ァ" <= char <= "ヴ" or char == "ー"


def _v220_hiragana(char: str) -> bool:
    return "ぁ" <= char <= "ん"


def _v220_word_char(char: str) -> bool:
    """漢字かカタカナ（長音を除く）。"""
    return _v220_kanji(char) or "ァ" <= char <= "ヴ"


def _v220_alnum(char: str) -> bool:
    return (char.isascii() and char.isalnum()) or "０" <= char <= "９" or "Ａ" <= char <= "Ｚ" or "ａ" <= char <= "ｚ"


def _label_is_phrase(label: str) -> bool:
    """ラベルが一語でなく句か（助詞、名詞を修飾する形、から・まで・より、動詞で終わる形）。"""
    if any(char in _LABEL_ANYWHERE for char in label) or "から" in label or "まで" in label or "より" in label:
        return True
    if label.endswith("か"):
        return True
    length = len(label)
    for index in range(1, length):
        char = label[index]
        before = label[index - 1]
        if char in _LABEL_AFTER_NOUN and (_v220_kanji(before) or _v220_katakana(before)):
            return True
        if char in _LABEL_BETWEEN and index + 1 < length and _v220_word_char(label[index + 1]):
            return True
        if _v220_hiragana(char) and not _v220_hiragana(before) and (_v220_kanji(before) or _v220_katakana(before)):
            end = index
            while end < length and _v220_hiragana(label[end]):
                end += 1
            if end < length and _v220_word_char(label[end]) and label[end - 1] in _LABEL_ATTRIBUTIVE:
                return True
    if label[-1] in _LABEL_VERB_END:
        index = length - 2
        while index >= 0 and _v220_hiragana(label[index]):
            index -= 1
        if index >= 0 and _v220_kanji(label[index]):
            return True
    # 動詞の終止形＋「こと」（守ること、いつも守ること）も句
    if length > 2 and label.endswith("こと") and label[-3] in _LABEL_VERB_END:
        return True
    return False


def _label_kanji_runs(text: str) -> list[tuple[str, str]]:
    """漢字の続き（2字以上）とカタカナの続き（2字以上）。"""
    runs = []
    current = ""
    kind = None
    for char in text + " ":
        now = "k" if _v220_kanji(char) else "t" if _v220_katakana(char) else None
        if now == kind and now is not None:
            current += char
            continue
        if kind is not None and len(current) >= 2:
            runs.append((kind, current))
        current, kind = (char, now) if now is not None else ("", None)
    return runs


# katakana_term と thin_evaluation の一覧（references/lists/ の隣の一覧を読む。ないとき、読めないときは内蔵の一覧）
_V220_BUILTIN_LISTS = {
    "katakana-terms": tuple((
        "マイルストーン シナジー ソリューション エンゲージメント プラットフォーム コミットメント アライメント ナレッジ イニシアチブ バリュー スキーム インサイト エコシステム ケイパビリティ "
        "レバレッジ オポチュニティ ステークホルダー コンセンサス ロードマップ ベストプラクティス イノベーション トランスフォーメーション エクスペリエンス カスタマージャーニー タッチポイント "
        "モメンタム コアコンピタンス プレゼンス ウェルビーイング パーパス "
    ).split()),
    "thin-evaluation": (
        ("座り心地", "(?:快適|よい|良い|いい|抜群)"),
        ("使い心地", "(?:よい|良い|いい|快適|抜群)"),
        ("書き心地", "(?:なめらか|滑らか|よい|良い|いい|抜群)"),
        ("寝心地", "(?:よい|良い|いい|快適|抜群)"),
        ("履き心地", "(?:よい|良い|いい|快適|抜群)"),
        ("着心地", "(?:よい|良い|いい|快適|抜群)"),
        ("乗り心地", "(?:快適|よい|良い|いい|抜群)"),
        ("居心地", "(?:よい|良い|いい|快適|抜群)"),
        ("肌触り", "(?:心地よい|心地良い|よい|良い|いい|なめらか|滑らか|抜群)"),
        ("手触り", "(?:心地よい|心地良い|よい|良い|いい|なめらか|滑らか|抜群)"),
        ("質感", "(?:上質|よい|良い|いい|高い|抜群)"),
        ("使い勝手", "(?:よい|良い|いい|抜群)"),
        ("手軽さ", "(?:抜群|魅力)"),
        ("打鍵感", "(?:心地よい|心地良い|よい|良い|いい|快適|抜群)"),
        ("装着感", "(?:快適|よい|良い|いい|抜群)"),
        ("仕上がり", "(?:美しい|きれい|綺麗|上質|抜群)"),
        ("味わい", "(?:深い|豊か|格別)"),
        ("香り", "(?:豊か|よい|良い|いい|格別)"),
        ("操作性", "(?:高い|優れてい(?:ます|る)|よい|良い|抜群)"),
        ("視認性", "(?:高い|優れてい(?:ます|る)|よい|良い|抜群)"),
        ("利便性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("快適性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("安定性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("耐久性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("携帯性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("静音性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("保温性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("信頼性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("拡張性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("保守性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("可読性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("機能性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("デザイン性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("品質", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("性能", "(?:高い|優れてい(?:ます|る)|抜群)"),
    ),
}
# 2.3.0: renyo_noun の一覧（references/lists/renyo-nouns.txt と同じ。1項目は「語」か「語<TAB>外す後ろの字」）
_V220_BUILTIN_LISTS["renyo-nouns"] = tuple((
    "確かめ 直し 比べ 測り 補い 決め 選び 集め 探し 捜し 整え 揃え そろえ 重ね 外し 戻し 削り 消し 残し 伏せ "
    "伝え 預け 並べ 分け 混ぜ 減らし 増やし 広げ 縮め 伸ばし 延ばし 遅らせ 終え 続け 動かし 移し 貼り 挙げ 数え 改め 入れ "
    "たしかめ くらべ おぎない ととのえ"
).split()) + ("育て\tの親|の母|の父", "足し\tに", "試し\tに")
_V220_LIST_CACHE = {}
# 一覧のファイルがあるのに読めなかった理由（なければ None）。lint の出力には出さない（diff の _LIST_PROBLEMS と同じ扱い）
_V220_LIST_PROBLEMS = {}
_V220_LIST_ABSENT = (FileNotFoundError, NotADirectoryError)


def _v220_parse_list(text: str, pattern: bool = False) -> tuple:
    """一覧のファイルの中身を読む（yomiyasu_diff.parse_list と同じ書き方）。空行と「#」で始まる行は読み飛ばす。
    正規表現の誤りはここでは確かめない（組むのに時間がかかるので、初めて使うときに _v220_thin_match が確かめる）。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    out = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if pattern:
            name, _, regex = line.partition("\t")
            if not name.strip() or not regex.strip() or "\t" in regex.strip():
                shown = line if len(line) <= 40 else line[:40] + "…"
                raise ValueError("「名詞<TAB>述語の正規表現」の形でない行があります: " + shown)
            out.append((name.strip(), regex.strip()))
        else:
            out.append(line.strip())
    return tuple(out)


def _v220_load_list(name: str) -> tuple[tuple, str]:
    """一覧を読む（yomiyasu_diff._load_list と同じ読み方）。(項目のタプル, 出どころ) を返す。出どころは
    "references/lists/<名前>.txt" か "builtin"。スクリプトの隣の ../references/lists/<名前>.txt を utf-8-sig で読む。
    ないときは何も言わずに内蔵の一覧で動き、読めないとき（UTF-8 でない、書き方の誤り、開けない）は、理由を
    _V220_LIST_PROBLEMS に残して内蔵の一覧で動く。thin-evaluation の正規表現の誤りは、初めて使うときに見つけて同じようにする。"""
    if name in _V220_LIST_CACHE:
        return _V220_LIST_CACHE[name]
    pattern = name == "thin-evaluation"
    items, problem = None, None
    path = Path(os.path.normpath(__file__)).absolute().parent / os.pardir / "references" / "lists" / (name + ".txt")
    try:
        with Path(path).open("rb") as handle:
            data = handle.read()
    except _V220_LIST_ABSENT:
        data = None
    except OSError as error:
        data, problem = None, "ファイルを開けません（{}）".format(getattr(error, "strerror", None) or error)
    if data is not None:
        try:
            items = _v220_parse_list(data.decode("utf-8-sig"), pattern=pattern)
        except UnicodeDecodeError:
            problem = "UTF-8 として読めません"
        except ValueError as error:
            problem = str(error)
    if items is None:
        result = (tuple(_V220_BUILTIN_LISTS[name]), "builtin")
    else:
        result = (items, "references/lists/{}.txt".format(name))
    _V220_LIST_CACHE[name] = result
    _V220_LIST_PROBLEMS[name] = problem
    return result


# 文書全体に一度だけ当てる手掛かりの語（型1の動詞の頭、型2の名詞、型3の句の頭）。katakana_term と thin_evaluation の一覧の語も足す。
# どの規則の正規表現も、当たるときはこのどれかを含む（試験で守る）
_V220_TRIGGER_LITERALS = tuple((
    # 型1の動詞
    "拾う 拾い 拾わ 拾っ 拾え 拾お 引く 引い 引か 引き 引け 通す 通し 通さ 通る 通り "
    "通ら 通っ 通れ 効く 効き 効か 効い 効け 響く 響き 響か 響い 響け 足す 足し 足さ "
    "足せ 抱え 見張 食う 食い 食わ 食っ 食べ 受け止め 飲み込 呑み込 覚え 忘れ 投げ 叩く "
    "叩き 叩か 叩い 話す 話し 話さ 話せ 喋 助け 手伝 気にす 気にし 気にせ 気にさ 怒る "
    "怒り 怒ら 怒っ 文句を "
    # 型2の名詞（「口」で受け口、入口、出口、窓口、裏口、〜向けの口を拾う）
    "口 玄関 関所 関門 抜け道 裏道 通り道 合流 防波堤 砦 先 "
    # 型3の句（足すものがない、価値を足す、失効が効く、〜から効く は型1の動詞の頭で拾う）
    "秒を取 分を取 時間を取 場所を取 ステップを取 意味を 針を 所有権を持 違いを作 手を伸ば ライブに "
    "同じページ 水を試 透明に ループを ループに 駆動され 配達 大きな絵 インパクトを持 決定を作 "
    "質問を持 真剣に取 目を保 テーブルに置 テーブルに載 テーブルに乗 テーブルに出 次のレベルに 機械 ターン "
    # 2.5.0 の型3の句（ここで効くのが は型1の動詞の頭で拾う）
    "レベルの テーブルにあ テーブルの上に "
    # 型4（2.4.0）の漢字1字の名詞と、3.0.0 で足した字
    "版 印 頭 枝 題 罫 "
    # 型5（3.0.0）の2字以上の名詞（上罫、下罫などは、型4の罫の形が前の漢字で外すので、型5で拾う）
    "背景 基準線 時間窓 上罫 下罫 左罫 右罫 偽緑 根因 生成器 検査器 飛行中 見張り 台本 "
).split())

_V220_TYPE1_END = _V220_TRIGGER_LITERALS.index("口")
_V220_TYPE2_END = _V220_TRIGGER_LITERALS.index("秒を取")
_V220_TYPE3_END = _V220_TRIGGER_LITERALS.index("版")


def _v220_literal_re(literals: Iterable[str]) -> _V220Lazy:
    """文字列のどれかに当たる正規表現。先頭の字ごとにまとめる（re は分かれ道を1つずつ試すので、同じ字で始まる語を
    1つの分かれ道にまとめると、その字の位置で試す数が減る）。長い語を先に試す。"""
    groups = {}
    for literal in sorted(set(literals), key=len, reverse=True):
        if literal:
            groups.setdefault(literal[0], []).append(literal[1:])
    parts = []
    for head, tails in groups.items():
        if "" in tails:
            tails = [tail for tail in tails if tail] + [""]
        if len(tails) == 1:
            parts.append(re.escape(head) + re.escape(tails[0]))
        else:
            parts.append(re.escape(head) + "(?:" + "|".join(map(re.escape, tails)) + ")")
    return _V220Lazy("|".join(parts))


# 文ごとに、型の手掛かりの語があるかを先に見る（ない文は型の正規表現を当てない）
_THIN_PREFIX_MAX = 20
_THIN_ADVERB = r"(?:とても|非常に|大変|たいへん|すごく|かなり|十分に?|抜群に|格段に|より|さらに|一段と)?"
_THIN_TAIL = r"(?:です|でした|だ|だった|である|でございます|ですね|ですよ)?"
_V220_COMPILED = {}


def _v220_patterns() -> tuple[_V220Lazy | None, _V220Lazy | None, tuple[str, ...], tuple[_V220Lazy, ...]]:
    """一覧から組んだ正規表現（katakana_term、thin_evaluation、文書全体の手掛かり）。一覧ごとに1回だけ組む。"""
    katakana, katakana_source = _v220_load_list("katakana-terms")
    thin, thin_source = _v220_load_list("thin-evaluation")
    key = (katakana_source, id(katakana), thin_source, id(thin))
    if _V220_COMPILED.get("key") == key:
        return _V220_COMPILED["value"]
    katakana_re = None
    if katakana:
        # 番号や記号を付けた項目の名前（マイルストーン1、マイルストーン B）は、何を指すかが決まっているので外す
        katakana_re = _V220Lazy("(?:" + "|".join(map(re.escape, sorted(set(katakana), key=len, reverse=True)))
                                 + r")(?![ 　]?[0-9０-９A-Za-zＡ-Ｚａ-ｚ])")
    thin_re = None
    nouns = ()
    if thin:
        nouns = tuple(sorted(set(noun for noun, _ in thin), key=len, reverse=True))
        body = "|".join("(?:{}(?:が|は|も){}(?:{}))".format(re.escape(noun), _THIN_ADVERB, predicate)
                        for noun, predicate in thin)
        thin_re = _V220Lazy(r"^(?P<prefix>[^、，,]{0," + str(_THIN_PREFIX_MAX) + r"}?)(?P<body>" + body + r")" + _THIN_TAIL
                             + r"[。．！!]*$")
    # 手掛かりの語は、先読みや後読み、捕まえる組のない文字列だけをつなぐ（re が先頭の字の候補で位置を飛ばせて速い）。
    # 先頭の平仮名は外し、漢字で始まる語とカタカナで始まる語を別の正規表現にする（1つにまとめると、よく出る字の位置で
    # すべての語を試すので遅い）
    literals = set(re.sub(r"^[ぁ-ん]+", "", literal) for literal in _V220_TRIGGER_LITERALS + tuple(katakana) + nouns)
    literals.discard("")
    trigger = tuple(_v220_literal_re(group) for group in (
        [literal for literal in literals if not ("ァ" <= literal[0] <= "ヴ" or literal[0] == "ー")],
        [literal for literal in literals if "ァ" <= literal[0] <= "ヴ" or literal[0] == "ー"]) if group)
    value = (katakana_re, thin_re, nouns, trigger)
    _V220_COMPILED["thin_nouns"] = _v220_literal_re(nouns) if nouns else None
    _V220_COMPILED["key"] = key
    _V220_COMPILED["value"] = value
    return value


def _v220_thin_match(sentence: str) -> re.Match[str] | None:
    """thin_evaluation の正規表現を文に当てる。一覧のファイルの正規表現に誤りがあれば、理由を残して内蔵の一覧で当てる。"""
    thin_re = _v220_patterns()[1]
    if thin_re is None:
        return None
    try:
        return thin_re.match(sentence)
    except re.error as error:
        _V220_LIST_CACHE["thin-evaluation"] = (tuple(_V220_BUILTIN_LISTS["thin-evaluation"]), "builtin")
        _V220_LIST_PROBLEMS["thin-evaluation"] = "正規表現の誤り（{}）".format(error)
        fallback = _v220_patterns()[1]
        return fallback.match(sentence) if fallback is not None else None


def _v220_masked_lines(analysis: dict) -> dict[int, str]:
    """行ごとの見える文字に、文書全体で対を取ったカギ括弧のマスクをかけたもの（行番号は変えない）。

    「」が行をまたぐときも中身を伏せるため、引用の行を除く全行の見える文字をつないで1度だけ
    _mask_quoted_segments_sparse を当て、元の行の幅で切り出す（_rule9_context と同じやり方）。
    """
    cached = analysis.get("_v220_masked_lines")
    if cached is not None:
        return cached
    rows = analysis["lines"]
    parts = [("" if row["quote_depth"]
              else _prose_visible_text(analysis, row["line"]).replace("__", "").replace("*", ""))
             for row in rows]
    masked = _mask_quoted_segments_sparse("\n".join(parts))
    # _mask_quoted_segments_sparse は引用の中の改行も伏せる。出力を改行で分けず、元の幅で切り出す
    offset = 0
    result = {}
    for row, part in zip(rows, parts):
        result[row["line"]] = masked[offset:offset + len(part)]
        offset += len(part) + 1
    analysis["_v220_masked_lines"] = result
    return result


def _v220_scan_text(analysis: dict, line_no: int) -> str:
    """新しい語の規則が見る行の文字。見える文字から、カギ括弧と引用符の中、英数字の識別子を空白にする。"""
    visible = _v220_masked_lines(analysis)[line_no]
    if "“" in visible or '"' in visible or "‘" in visible:
        visible = _V220_QUOTES.sub(lambda m: " " * len(m.group()), visible)
    return _V220_IDENTIFIER.sub(lambda m: " " * len(m.group()), visible)


def _label_text(analysis: dict, row: dict, scan: str) -> str:
    """見出しか1行目のラベル（記号と番号を除いた文字。英数字は残す）。"""
    text = scan.strip()
    if row["kind"] == "heading":
        text = text.strip("#").strip()
    text = _LABEL_NUMBERING.sub("", text).strip()
    return "".join(char for char in text if _v220_kanji(char) or _v220_katakana(char) or _v220_hiragana(char)
                   or _v220_alnum(char))


def _label_shape(label: str) -> bool:
    """ラベルの形の条件（8字以下で、よく使う節の名前でなく、「〜の横」「〜のそば」「〜係」「〜番」で終わるか一語）。"""
    if not label or len(label) < 2 or len(label) > _LABEL_MAX or label in _LABEL_COMMON:
        return False
    if any(_v220_alnum(char) for char in label) or label.endswith(_LABEL_NOT_ENDINGS):
        return False
    run = longest = 0
    for char in label:
        run = run + 1 if _v220_hiragana(char) else 0
        longest = max(longest, run)
    if longest >= 4 or not any(_v220_word_char(char) for char in label):
        return False
    if label.endswith(_LABEL_ENDINGS):
        return True
    if label.endswith(_LABEL_ABSTRACT_ENDINGS) or (label.endswith("方") and len(label) > 1 and _v220_hiragana(label[-2])):
        return False
    return not _label_is_phrase(label)


def _label_may_fit(row: dict) -> bool:
    """見出しか1行目が、伏せる前の文字でラベルになりうるか（長い見出しと、ふつうの見出しを先に飛ばす）。
    伏せる所（識別子、コード）は英数字か記号なので、漢字と仮名だけを残した文字で見る。"""
    raw = row["raw"]
    quick = _LABEL_NOT_JAPANESE.sub("", raw)
    if not 2 <= len(quick) <= _LABEL_MAX or any(mark in raw for mark in _LABEL_MARKS):
        return False    # 台詞や引用、作品の名前、括弧の補足を含む行は、一語のラベルではない
    return _label_shape(quick)


def _metaphor_label(analysis: dict, row: dict, scan: str) -> str | None:
    """metaphor_label のラベルを返す（当たらなければ None）。"""
    if row["kind"] not in ("heading", "paragraph"):
        return None     # 1行目が表や箇条書きのときは見ない
    if row["kind"] != "heading" and scan.rstrip().endswith(("。", "．", "！", "？", "!", "?")):
        return None     # 文として終わる1行目はラベルとみなさない
    if any(mark in row["raw"] for mark in _LABEL_MARKS):
        return None
    content = _LABEL_NUMBERING.sub("", scan.strip().strip("#").strip()).strip()
    if _LABEL_SEPARATED.search(content):
        return None
    # 番号のほかに英数字を含む見出し（v1.1.2 チェックポイント）は、版や名前を書いた見出しで、一語の比喩ではない
    if _LABEL_ASCII.search(_LABEL_NUMBERING.sub("", row["raw"].strip().strip("#").strip())):
        return None
    if len("".join(analysis["text"].split())) - len("".join(row["raw"].split())) < _LABEL_MIN_BODY:
        return None
    label = _label_text(analysis, row, scan)
    if not _label_shape(label):
        return None
    text = analysis["text"]
    raw = row["raw"]
    pieces = [label]
    stem = label
    for ending in _LABEL_ENDINGS:
        if stem.endswith(ending):
            stem = stem[:-len(ending)]
            break
    # ラベルの漢字の続きの2字（とカタカナの続き）。どれかが本文のほかの行に出れば、本文の話題の語とみなして出さない
    for kind, run in _label_kanji_runs(stem):
        if kind == "t":
            pieces.append(run)
        else:
            pieces.extend(run[index:index + 2] for index in range(len(run) - 1))
    if any(text.count(piece) > raw.count(piece) for piece in dict.fromkeys(pieces)):
        return None
    if not label.endswith(_LABEL_ENDINGS):
        # 一語のラベルの漢字が、どれも本文のほかの所に出る（文体の節に「文」と「体」が出る）なら、本文の話題の語とみなす
        kanji = [char for char in label if _v220_kanji(char)]
        if len(kanji) >= 2 and all(text.count(char) > raw.count(char) for char in kanji):
            return None
    return label


# calque（直訳語）: 型1〜3（上流 v3.0.0 の採用分。型4・型5 と translated_term は決定記録 Y-21 で不採用）。
# info で、1行に同じ規則の候補は1件まで。当たった言い方は候補の内部の欄 _words（と型の対応 _word_types）に入れる
# （語の一覧の allow.txt で外すため。出力には出ない）。行の見え方は _v220_word_findings と同じ（_v220_scan_text）。
# 同じ行に metaphor_verb の候補があれば出さない。上流は同じ行の translated_term があれば型3も外すが、
# translated_term は不採用なのでその判定はない。doc-type 依存の扱い（入口と出口、「全〇〇に響く」、
# 「ときに効く」の拾い方）は、--doc-type を導入せず（Y-20）、文書全体の技術語の数で決める内部の目安
# _v220_doc_tech で常に判定する。
_CALQUE_TYPE_NAMES = {1: "型1: 機械やシステムが人の動作をする言い方",
                      2: "型2: 実物の名前の代わりに場所のたとえを使う名詞",
                      3: "型3: 英語の言い方を一語ずつ写した句"}
# 型1: 機械やシステムが主語の文（主語の語に「は」「が」「も」「こそ」が付く）で、人や物の動作の動詞を使う形。
# 主語の語のあとに漢字やカタカナが続いて人や組織の語で終わるとき（サーバー管理者、情報システム部）は主語にしない。
_CALQUE_SUBJECTS = tuple((
    "ジョブ 処理 バッチ サーバー サーバ システム API 関数 スクリプト キュー ワーカー "
    "プロセス モジュール 設定 鍵 ミドルウェア クライアント ビルド エージェント フック クエリ "
    "チェック インデックス キャッシュ ライブラリ プログラム アプリ サービス ツール コマンド "
    "パイプライン ルーター ロードバランサー ゲートウェイ プロキシ データベース DB Webhook ボット "
    "クローラー スケジューラー コンテナ ノード クラスター センサー 端末 デバイス 機器 装置 "
    "受信側 送信側 監視 ファイアウォール フィルター パーサー コンパイラ リンター エンジン ブラウザ "
    "プラグイン 拡張機能 バックエンド フロントエンド テスト 体重計 計測器 cron CI "
).split())
_CALQUE_PERSON_END = r"(?:者|員|人|さん|様|さま|氏|チーム|部|課|室|班|係|担当|会社|社|陣|部門|部署)"
_CALQUE_SUBJECT_WORD = _V220Lazy(r"(?<![A-Za-z])(?:" + "|".join(sorted(map(re.escape, _CALQUE_SUBJECTS), key=len, reverse=True))
                                  + r")")
_CALQUE_SUBJECT_EXT = 6           # 主語の語のあとに続いてよい漢字、カタカナ、英数字の数（再送ジョブ管理画面が）
_CALQUE_SUBJECT_PARTICLES = ("こそ", "は", "が", "も")
_CALQUE_PERSON_SUBJECT = _V220Lazy(
    r"(?:" + _CALQUE_PERSON_END[3:-1] + r"|私|僕|わたし|ぼく|我々|皆さん|みなさん|お客様|彼|彼女|あなた)(?:は|が|も|こそ)")
_CALQUE_PERSON_EXT = _V220Lazy(_CALQUE_PERSON_END + r"$")
# (辞書の形, 正規表現)。活用の形まで書き、名詞の使い方（引き続き、通りに、足し算、食い違い）は外す。
# 動詞の漢字の前が漢字のとき（不足して、共通する、電話します、補足すると）は、_calque_type1 が外す（_CALQUE_COMPOUND_OK の動詞を除く）
_CALQUE_VERBS = (
    ("拾う", r"拾(?:う|い|わ|っ[てた]|え|お)"),
    ("引き込む", r"引き込(?:む|み|ん|ま|め)"),
    ("引く", r"(?<!差し)引(?:く|い[てた]|か(?:な|ず|れ)|き(?=[ぁ-ん])|け(?=[ぁ-ん]))"),
    ("通す", r"(?<!を)通(?:す|し(?=[ぁ-ん])|さ(?:な|ず|せ))"),
    ("通る", r"通(?:る|り(?=[ぁ-ん])(?![にのだでがはをもと])|ら(?:な|ず)|っ[てた]|れ(?=[ぁ-ん]))"),
    ("効く", r"効(?:く|き(?=[ぁ-ん])|か(?:な|ず)|い[てた]|け(?=[ぁ-ん]))"),
    ("響く", r"響(?:く|き(?=[ぁ-ん])|か(?:な|ず)|い[てた]|け(?=[ぁ-ん]))"),
    ("足す", r"足(?:す|し(?=[ぁ-ん])|さ(?:な|ず|れ)|せ(?=[ぁ-ん]))"),
    ("抱える", r"抱え(?:る|て|た|ま|な|ず|込)"),
    ("見張る", r"見張(?:る|り|っ[てた]|ら|れ)"),
    ("食う", r"食(?:う|い(?=[ぁ-ん])|わ(?:な|ず|れ)|っ[てた])|食べ(?:る|て|た|ま|な|ず|られ)"),
    ("受け止める", r"受け止め"),
    ("飲み込む", r"[飲呑]み込(?:む|み|ん|め|ま)"),
    ("覚える", r"覚え(?:る|て|た|ま|な|ず|させ|られ)"),
    ("忘れる", r"忘れ(?:る|て|た|ま|な|ず|られ)"),
    ("投げる", r"投げ(?:る|て|た|ま|な|ず|込|つけ|られ)"),
    ("叩く", r"叩(?:く|き(?=[ぁ-ん])|か(?:な|ず|れ)|い[てた])"),
    ("話す", r"話(?:す|し(?=[ぁ-ん])|さ(?:な|ず)|せ(?=[ぁ-ん]))"),
    ("喋る", r"喋(?:る|り|ら|っ[てた]|れ)"),
    ("助ける", r"助け(?:る|て|た|ま|な|ず|られ)"),
    ("手伝う", r"手伝(?:う|い|わ|っ[てた]|え)"),
    ("気にする", r"気に(?:す|し|せ|さ)"),
    ("怒る", r"怒(?:る|り(?=ま)|ら|っ[てた])"),
    ("文句を言う", r"文句を(?:言|い)"),
)
# 前が漢字でもよい動詞（引き込む、抱える、見張る など、漢字の熟語の一部にならない語幹）
_CALQUE_COMPOUND_OK = ("引き込む", "抱える", "見張る", "受け止める", "飲み込む", "覚える", "忘れる", "投げる", "喋る", "助ける",
                       "手伝う", "文句を言う")
# 動詞ごとの (語幹の字, 辞書の形, 正規表現)。文に語幹の字があるときだけ、その動詞の正規表現を組んで当てる
_CALQUE_VERB_EACH = tuple((re.sub(r"^(?:\(\?<![^)]*\))*(?:\[[^\]]*\])?", "", pattern)[0], name, _V220Lazy(pattern))
                          for name, pattern in _CALQUE_VERBS)
# 定着した言い方（テストが通る、キャッシュが効く）の助詞と動詞の間に入れてよい副詞。どの主語の行でも同じ一覧を使う。
# 副詞は2つまで続いてよく、助詞と副詞のあとの読点も許す（テストが、まだ通らない。CIはもう全部通りました）。
# 型1の見落としを増やさないよう、語の完全一致にして、任意の字の並びにはしない
_CALQUE_ESTABLISHED_ADVERBS = ("すべて", "全部", "全て", "無事に", "無事", "まだ", "もう", "ちゃんと", "きちんと", "しっかり",
                               "うまく", "よく", "正しく", "問題なく", "なかなか", "いつも", "必ず", "全然", "一度で", "最後まで")
_CALQUE_ESTABLISHED_ADVERB = (r"、?(?:(?:" + "|".join(sorted(_CALQUE_ESTABLISHED_ADVERBS, key=len, reverse=True))
                              + r")、?){0,2}")
# 型1の定着した言い方（試験で守る）。動詞がこの当たりの中にあれば出さない。
# 動詞が名詞を修飾する形（拾った通知、話した内容）は、主語が機械と決まらないので出さない
_CALQUE_ESTABLISHED_TYPE1 = (
    r"テスト(?:が|は|も)" + _CALQUE_ESTABLISHED_ADVERB + r"通",
    # 件数や一式、道具の名前をはさむ形（テストは218件とも通りました、テスト一式は pytest で通す）
    r"テスト(?:一式)?[0-9０-９]*件?(?:が|は|も)(?:[0-9０-９]+件(?:とも|すべて)?|\s?[A-Za-z][\w.-]{0,15}\s?で)?"
    + _CALQUE_ESTABLISHED_ADVERB + r"\s?通",
    r"(?:ビルド|CI|コンパイル|審査|申請|予算|企画|法案|稟議|認証|筋|話|声|意見|理屈|名前|電気|電流)\s?(?:が|は|も)"
    + _CALQUE_ESTABLISHED_ADVERB + r"通",
    r"(?i:ping)\s*(?:が|は|も)\s*通", r"疎通",
    r"(?:キャッシュ|インデックス|薬|ブレーキ|冷房|暖房|エアコン|設定|オプション|フラグ|権限|フック|上限)\s?(?:が|は|も)"
    + _CALQUE_ESTABLISHED_ADVERB + r"効",
    # 設定やフックが何に及ぶかを言う「〜にも効く」（フックは、サブエージェントの呼び出しにも効く）
    r"(?:設定|オプション|フラグ|権限|フック|上限|ルール|規則)\s?(?:が|は|も)、?[^。]{0,30}?に(?:も)?効",
    r"(?:声|音|ノイズ|電波|信号|振動)を拾",
    # 検出の意味の「拾う」（表現を拾う、エラーを拾う）
    r"(?:誤り|誤字|脱字|表現|候補|エラー|警告|違反|表記ゆれ|変更|差分)を[^。、]{0,6}拾",
    r"から[^。、]{0,15}(?:額|数|値|分|量|費|料|金|点|[0-9０-９]+)を引(?:く|き|い|か)",
    r"(?:線|辞書|くじ|クジ|風邪|かぜ|手|目|注意|関心|興味|気|幕|身|糸|尾|図|グラフ|罫線|下線|傍線|カーテン|ブラインド)を引",
    r"落とし物を拾", r"(?:例外|エラー|exception|Exception)を投げ",
    r"(?:課題|問題|負債|リスク|不安|悩み|弱点|欠陥|バグ|不具合|矛盾)を(?:多く|いくつも|たくさん)?抱え",
)
_CALQUE_ESTABLISHED_TYPE1_RE = _V220Lazy("|".join(_CALQUE_ESTABLISHED_TYPE1))
_CALQUE_KANA_RUN = _V220Lazy(r"[ぁ-ん]*")
# 主語から動詞までの字数の上限と、間にあれば主語と動詞を結ばない記号（括弧、矢印。例を並べた文）
_CALQUE_SUBJECT_REACH = 30
_CALQUE_SUBJECT_BREAK = _V220Lazy(r"[（()）「」『』→←]")
_CALQUE_REQUEST = ("てください", "て下さい", "てくださ", "いでくださ", "いで下さ", "なさい", "ましょう", "てほしい", "て欲しい",
                   "ていただ", "てもらえ")
_CALQUE_ATTRIBUTIVE_END = ("た", "る", "う", "く", "す", "つ", "む", "ぶ", "ぐ", "だ", "ない", "いる")
# 文ごとに、型の手掛かりの語があるかを先に見る（ない文は型の正規表現を当てない）
_CALQUE_VERB_STEMS = frozenset(stem for stem, _, _ in _CALQUE_VERB_EACH)     # どれも1字
_CALQUE_PLACE_HEAD = _v220_literal_re(_V220_TRIGGER_LITERALS[_V220_TYPE1_END:_V220_TYPE2_END])
_CALQUE_PHRASE_HEAD = _v220_literal_re(_V220_TRIGGER_LITERALS[_V220_TYPE2_END:_V220_TYPE3_END] + ("効", "足す", "足し", "響", "引", "通"))

# 型2: 場所のたとえの名詞。受け口と「〜向けの口」はいつも拾う。「〜先」は _CALQUE_SAKI の形で、定着した語
# （_CALQUE_ESTABLISHED_SAKI）を除いて拾う。入口、窓口などの実物にもある名前は、同じ文に機械やシステムの語（_CALQUE_TECH）が
# あるときだけ拾い、実物の場所（駅の入口）と組織の窓口（総務部の窓口）は外す
# 後ろに漢字やカタカナが続く語（入口付近、窓口業務、口座）は _calque_type2 が外す。動詞のあとの「口」（トークンを出す口）は、
# 実物の口（水を出す口、切符を受け取る口）と分けるため、機械やシステムの語がある文だけで拾う
_CALQUE_PLACE_ALWAYS = _V220Lazy(r"受け口|(?:向け|用)の口|(?:出す|受ける|受け取る|返す|渡す|発行する)口(?=[はがをにでもへと、。]|$)")
_CALQUE_PLACE_CONTEXT = _V220Lazy(r"(?:入り?口|出口|窓口|玄関口?|関所|関門|裏口|勝手口|抜け道|裏道|通り道|合流地点|合流点"
                                   r"|防波堤|砦)|の口(?=[はがをにでもへと、。]|$)")
# 実物の場所の入口（駅の入口、正面入口、2番入口）と、組織の窓口（総務部の窓口）
_CALQUE_PLACE_REAL = _V220Lazy(
    r"(?:駅|正面|[東西南北]|番|建物|ビル|店|会場|公園|館|門|地下|トンネル|洞窟|港|校舎|病院|施設|部屋|通用|非常|改札|階段"
    r"|空港|ホーム|ホール|劇場|球場|庭|家|屋敷|森|山|川|村|町|街|道|高速|本館|別館|棟|フロア|階"
    # 機械を置く部屋（サーバールーム、データセンター）。名前に技術の語があっても実物の場所
    r"|(?:サーバー?|マシン|コンピューター?|電算|計算機)(?:ルーム|室)|データセンター)の?$")
# 同じ文に技術の語がない入口と出口（技術の文書の判定）で、ほかに外す実物の場所（サーバールーム、北側の出口、
# 駐車場の出口）。同じ文に技術の語がある文は、_CALQUE_PLACE_REAL だけで外す
_CALQUE_PLACE_REAL_DOC = _V220Lazy(
    r"(?:ルーム|室|センター|オフィス|倉庫|工場|店舗|売り場|ロビー|受付|玄関|フロント|(?:[東西南北]|正面|裏|表|反対|道路|線路)側"
    r"|(?:駐車|駐輪|乗り|広|運動|工事)場|鉄|トイレ|学校|社屋|建屋|非常用|団地|園|マンション|通路)の?$")
# 入口の前で人が待つ、集まる形（入口の前でお待ちください）と、入口の前の物（入口の前のインターホン）は、技術の語のない文では
# 実物の場所として外す
_CALQUE_ENTRY_WAIT = _V220Lazy(r"の前(?:の|(?:で|に)(?:は、?)?(?:お?待|集ま|並|立))")
_CALQUE_PLACE_ORG = _V220Lazy(
    r"(?:部|課|室|係|局|センター|デスク|担当|相談|問い合わせ|問合せ|受付|事務所|事務局|総合|専用|役所|役場|銀行|郵便局"
    r"|市役所|区役所|窓口|申請|手続き|手続)の?$")
_CALQUE_MOUTH_REAL = _V220Lazy(
    r"(?:人|彼|彼女|私|僕|子|犬|猫|魚|鳥|瓶|びん|袋|ボトル|缶|容器|鍋|壺|樽|筒|穴|管|ホース|川|洞窟|トンネル|火山|傷|蛇)の口$")
_CALQUE_MOUTH_IDIOM = _V220Lazy(r"口(?:に合|が(?:堅|固|軽|悪|うま|上手|重|滑|すべ|裂)|を(?:出|挟|はさ|開|ひら|閉|とざ|揃|そろ"
                                 r"|つぐ|きく|利|割))")
_CALQUE_TECH = _V220Lazy(
    r"(?<![A-Za-z])(?:" + "|".join(sorted(map(re.escape, _CALQUE_SUBJECTS), key=len, reverse=True))
    + r"|データ|URL|リクエスト|レスポンス|接続|通信|トラフィック|ログイン|認証|ポータル|ページ|画面|サイト|フォーム"
    r"|アドレス|ポート|エンドポイント|ネットワーク|テーブル|ファイル|ログ|エラー|通知|CSV|JSON|HTTP|送信|受信|集計|決済"
    r"|リポジトリ|コード|メソッド|クラス|インターフェース|SDK|トークン|パケット|イベント|メッセージ|ドライブ|チャンネル)")
# 入口と出口は、同じ文に技術の語がなくても、技術の文書（_CALQUE_TECH の語のうち、案内や行事の文書にも出る語
# （_CALQUE_DOC_TECH_GENERAL）を除いた語が5種類以上）で、入口より前に要求や呼び出しの語の主題（_CALQUE_ENTRY_SUBJECT）があり、
# それを集めたり通したりする形（要求は、どれもこの入口を通ります）なら拾う。実物の場所（_CALQUE_PLACE_REAL と
# _CALQUE_PLACE_REAL_DOC）は外す
_CALQUE_DOC_TECH_MIN = 5
_CALQUE_DOC_TECH_GENERAL = frozenset((
    "画面 通知 メッセージ イベント サイト フォーム チャンネル ページ 送信 受信 ポータル アドレス ログイン 集計 決済 "
    "ドライブ ファイル データ コード 設定 チェック テスト 監視 ツール サービス アプリ 端末 機器 装置 デバイス 処理 "
    "センサー 体重計 計測器 エラー 鍵 テーブル クラス"
).split())
_CALQUE_ENTRY_FLOW = _V220Lazy(r"(?:の前|を通|に通|へ通|に集め|へ集め|にまとめ|へまとめ|に届|へ届|で受け|を経由|から入)")
# 人を呼ぶ、人が要求する文（来客の呼び出しがあったら、組合の要求を受けて）は外すため、「〜は」「〜も」の主題だけを見る
_CALQUE_ENTRY_SUBJECT = _V220Lazy(r"(?:要求|呼び出し|リクエスト|トラフィック|パケット|接続|通信)(?:は|も)")
# 窓口は、コードの部品の語が同じ文にあり、組織の名前（総務部、情報システム課、サポートセンター）がないときだけ
# （決済の窓口をこのモジュールに集める）
_CALQUE_ORG_WORDS = ("センター", "デスク", "担当", "事務局")
_CALQUE_ORG_SUFFIXES = "部課室係局班"
_CALQUE_CODE = _V220Lazy(r"(?<![A-Za-z])(?:モジュール|関数|クラス|API|エンドポイント|サーバー|サーバ|コード|ライブラリ|メソッド"
                          r"|インターフェース|SDK|ミドルウェア|プロキシ|ゲートウェイ)")
# 「〜先」: 漢字1字と動詞の連用形の送り仮名（し、せ、げ など）のあとの「先」（逃がし先、寄せ先）と、場所のたとえの漢語の「先」
# （_CALQUE_SAKI_KANJI。着地先）。漢字2字の「〜先」の多くは定着した語（保存先、接続先、修飾先）なので、一覧の語だけを拾う。
# 後ろに漢字やカタカナが続く語（先日、先方）と、助詞や「て」のあとの「先」（何を先に、置いて先に、項より先）は除く
_CALQUE_SAKI_KANJI = ("着地", "着弾", "漂着", "逃走", "終着", "着陸", "落下")
_CALQUE_SAKI_TAIL = "しせげけめりちきぎびみいえねべれじ"
# 定着した「〜先」（試験で守る）。当たった語がこのどれかで終われば出さない
_CALQUE_ESTABLISHED_SAKI = tuple((
    "宛先 宛て先 送信先 受信先 保存先 接続先 連絡先 取引先 依存先 問い合わせ先 問合せ先 "
    "回し先 割り振り先 振り分け先 立ち寄り先 働き先 通い先 務め先 引き合い先 取り寄せ先 借り先 貸し先 "
    "問合わせ先 提出先 申請先 申込先 申し込み先 照会先 相談先 通報先 報告先 連携先 格納先 "
    "出力先 入力先 書き込み先 読み込み先 書き出し先 取り込み先 移動先 移行先 遷移先 参照先 "
    "呼び出し先 配信先 通知先 公開先 共有先 掲載先 展開先 導入先 設置先 登録先 記録先 保管先 "
    "退避先 返却先 回収先 引き取り先 引き継ぎ先 譲渡先 売却先 取得先 利用先 適用先 反映先 "
    "割り当て先 割当先 代入先 転送先 送付先 返送先 請求先 支払先 支払い先 振込先 振り込み先 "
    "入金先 送金先 投資先 融資先 寄付先 預け先 預入先 勤務先 勤め先 所属先 配属先 委託先 "
    "外注先 発注先 受注先 仕入先 仕入れ先 購入先 調達先 供給先 納品先 納入先 出荷先 配送先 "
    "配達先 届け先 送り先 販売先 輸出先 輸入先 取材先 派遣先 出向先 転勤先 赴任先 就職先 "
    "転職先 進学先 留学先 旅行先 出張先 訪問先 避難先 移住先 越し先 滞在先 宿泊先 行き先 "
    "得意先 嫁ぎ先 落ち着き先 引受先 受け入れ先 受入先 実習先 研修先 見学先 紹介先 取次先 "
    "接種先 通院先 入院先 搬送先 転院先 飛び先 戻り先 移し先 写し先 優先 通信先 同期先 "
    "複製先 複写先 配置先 配備先 配布先 発行先 発送先 発信先 着信先 返信先 回答先 問合先 "
    "移転先 移設先 転居先 引越先 誘導先 案内先 相手先 顧客先 契約先 提携先 協力先 加盟先 "
    "参加先 出資先 移籍先 異動先 転属先 採用先 応募先 投稿先 寄稿先 掲示先 提供先 供与先 "
    "貸与先 買収先 寄贈先 支援先 返金先 引落先 引き落とし先 外出先 観光先 持参先 届出先 "
    "表示先 書込先 読込先 待避先 復元先 復旧先 切替先 置換先 変換先 変更先 更新先 追加先 "
    "代替先 委任先 依頼先 請負先 受託先 移管先 電話先 通話先 玄関先 納め先 戻し先 預かり先 "
    "付け先 込み先 出し先 入れ先 渡し先 継ぎ先 替え先 換え先 向け先 扱い先 一足先 "
    "掛かり先 係り先 掛り先 修飾先 "
    "少し先 一つ先 二つ先 三つ先 ひとつ先 以上先 以下先 "
).split())
# 時や距離の「先」（数年先、一歩先、数時間先）
_CALQUE_SAKI_TIME = _V220Lazy(r"[年月日週間時分秒歩手里キロメートル]先$|[たうくるだつむぬぶぐす]先$")

# 型3 が使う「効く」の文字どおりの語の判定（上流 _KIKU_RE のうち calque 型3 が使う4つのキーだけ。
# 残りのキーは上流の metaphor_verb の「効く」判定用で、本スキルには未移植）
_KIKU_END = "。．！？!?"
_KIKU_LITERAL_NEAR = (
    # 薬と体
    r"薬|剤|(?<=[0-9０-９数一二三四五六])錠|抗生物質|ワクチン|注射|点滴|麻酔|湿布|漢方|治療|鍼|ツボ|マッサージ|サプリメント|サプリ"
    r"|服用|服薬|内服|接種|症状|頭痛|腰痛|肩こり|肩凝り|花粉症|風邪|二日酔い|鼻炎|乾燥肌|肌荒れ|便秘|むくみ|筋肉痛|痛み"
    r"|日焼け止め|保湿|肥料|カフェイン|コーヒー|アルコール|酒|(?<!気の)毒"
    # 冷房や暖房、風呂
    r"|冷房|暖房|エアコン|クーラー|ヒーター|空調|除湿|床暖房|床暖|ストーブ|冷蔵|冷凍|扇風機|冷え|入浴|湯船|風呂|温泉"
    # 車
    r"|ブレーキ|制動|サスペンション|グリップ"
    # 調味料と味
    r"|わさび|ワサビ|山葵|塩加減|塩気|塩味|塩分|塩|胡椒|こしょう|コショウ|スパイス|辛子|カラシ|出汁|香辛料|調味料|酢"
    r"|生姜|ショウガ|山椒|唐辛子|七味|柚子|ハーブ|ミント|にんにく|ニンニク|レモン|炭酸"
    r"|隠し味|酸味|辛味|辛み|辛さ|甘さ|甘み|甘味|酸っぱさ|苦味|苦み|旨味|うま味|風味|香り(?!づけ|付け)|味付け|味つけ"
    r"|(?<![一-龥々])味")
# ソフトウェアの仕組みと設定の反映の語（と ABS）。「効く」の主語の位置（literal_subject）でだけ文字どおりとみなし、
# 同じ文と前の行の判定（context_near）では使わない
_KIKU_LITERAL_SOFTWARE = (r"(?<![A-Za-z])(?:ABS|JIT)|キャッシュ|インデックス|圧縮|最適化|プリフェッチ|チューニング"
                          r"|設定の変更|設定変更")
_KIKU_LITERAL = _KIKU_LITERAL_NEAR + "|" + _KIKU_LITERAL_SOFTWARE
# 主語の位置でなくても、近くにあれば文字どおりとみなす語（薬の飲み方の言い方）
_KIKU_CONTEXT = (r"飲んで|飲んだ|飲む|飲め|飲み(?:始め|はじめ|続け)|飲ませ|飲み物|飲み方|食後|食前|就寝前|用法|用量"
                 r"|効き目は個人差|個人差")
_KIKU_STOP = "、，，" + _KIKU_END
_KIKU_RE = {
    "literal_subject": _V220Lazy(r"(?:" + _KIKU_LITERAL + r")(?:(?:が|は|も|こそ|の|に|って|として)[、，,]?|[、，,])"
                                 r"[^" + _KIKU_STOP + r"を]{0,10}$"),
    "context": _V220Lazy(r"(?:" + _KIKU_LITERAL + r"|" + _KIKU_CONTEXT + r")(?![一-龥々ァ-ヴーA-Za-z])"),
    # 同じ文の中で見る語（ソフトウェアの語を除く）
    "context_near": _V220Lazy(r"(?:" + _KIKU_LITERAL_NEAR + r"|" + _KIKU_CONTEXT + r")(?![一-龥々ァ-ヴーA-Za-z])"),
    "timing": _V220Lazy(r"(?:[0-9０-９]+|数|半)\s*(?:分|時間)(?:間)?"
                        r"(?=ほど|くらい|ぐらい|程度|後|以内|経|たつ|たっ|で|もすると|もしないうち)"),
}

# 型3: 英語の言い方を一語ずつ写した句（試験で守る）。(名前, 正規表現)
_CALQUE_PHRASES = (
    ("足すものがない", r"足すもの(?:が|は|も)(?:ない|ありません|なかった|ありませんでした|何もない)"),
    ("価値を足す", r"価値を足"),
    ("失効が効く", r"失効が効"),
    ("から効く", r"(?:日|月|年|週|請求|分|回|以降|翌[日月週年]|来[月週年]|明日|今日|本日|次回)から効(?:く|き(?=[ぁ-ん])|い[てた])"),
    ("時間を取る", r"(?<![0-9０-９])[0-9０-９]+(?:[.．][0-9０-９]+)?\s*(?:ミリ秒|秒|分|時間)を取(?:る|り|っ|ら)"),
    ("意味をなす", r"意味を(?:なす|成す|なし|成し)(?!てい?な|ませ|えな|得な)"),
    ("針を動かす", r"針を(?:ほとんど|大きく|少し|まったく|全く|あまり)?動か"),
    ("ステップを取る", r"ステップを取"),
    ("所有権を持つ", r"(?:問題|課題|タスク|機能|サービス|障害|不具合|チケット|作業|プロジェクト|コード|モジュール)(?:に(?:は|ついては)|の)、?"
                    r"[^。]{0,12}所有権を持"),
    ("違いを作る", r"違いを作"),
    ("手を伸ばす", r"(?:部|課|室|チーム|担当者?|窓口|サポート|事務局|私たち|弊社|当社|我々)(?:まで|に|へ)(?:お?気軽に)?手を伸ば"),
    ("ライブになる", r"ライブに(?:な|し)"),
    ("同じページにいる", r"同じページ(?:の上)?に(?:い|立|そろ|揃)"),
    ("水を試す", r"水を試"),
    ("透明に", r"(?:にとって|に対して|から見て|からは)透明に|透明に(?:行われ|動作|処理|移行|切り替|動|扱)"),
    ("場所を取る", r"で場所を取(?:る|り|っ)"),
    ("ループを閉じる", r"ループを閉じ"),
    ("ループに入れる", r"ループに(?:入れ|入っ|加え)"),
    ("駆動される", r"(?:データ|数字|数値|指標|顧客|ユーザー|利用者|テスト|仕様)に駆動され"),
    ("配達する", r"(?:数字|数値|結果|成果|価値|売上|利益|成長|体験)を配達"),
    ("大きな絵", r"大きな絵(?:を|が|で|の中)(?![^。]*(?:描|画家|美術|展示|額|飾))"),
    ("インパクトを持つ", r"インパクトを持"),
    ("決定を作る", r"決定を作"),
    ("質問を持つ", r"質問を持(?:っ|ち|つ)"),
    ("真剣に取る", r"真剣に取(?:る|り|っ|ら)"),
    ("目を保つ", r"目を保"),
    ("テーブルに置く", r"(?:案|提案|選択肢|アイデア|条件|議題)を[^。]{0,6}テーブルに(?:置|載せ|乗せ|出)"),
    ("次のレベルに", r"次のレベルに(?:引き上げ|持っていく|押し上げ|連れて)"),
    # 直訳語の対応表から足した形（machine-to-machine、matter、affect、pull、go through、turn）
    ("機械どうし", r"機械(?:どうし|同士)(?:の|で|が|は|を|に)"),
    ("ときに効く", r"(?:とき|際|場合|うえ|上)に(?:いちばん|特に|大きく|強く)?効(?:く|き(?=[ぁ-ん])|い[てた])"),
    ("に響く", r"(?:クライアント|サーバー?|性能|応答|処理|ユーザー|利用者|ダッシュボード|システム|速度|画面|負荷|料金|費用"
              r"|コスト|請求)(?:の[^。、]{0,6})?に(?:まで|も)?響(?:く|き|い|か)"),
    # 間引く、差し引く、引き渡す、引き上げる、引きずる などの複合の動詞は外す
    ("データを引く", r"(?:データ|ログ|レコード|設定|履歴)を(?:[^。、]{0,6})?(?<![間割])(?<!差し)引"
                    r"(?:く|き(?![出継続受取渡伸上下ず合寄止戻抜締起換替])|い|か|け)"),
    # 「通」の前が漢字の語（予定通り、手順通り、一通り、大通り）と「通りに」などは外す
    ("書き込みが通る", r"(?:書き込み|読み込み|書き換え|削除|更新|操作|アクセス)(?:も|が|は)(?:[^。、]{0,4}[ぁ-ん])?通"
                     r"(?:る|り(?=[ぁ-ん])(?![にのだでがはをもと])|っ|ら|れ)"),
    # 数字の並びの途中から試さないよう、前に数字がないことを見る（長い数字の並びで遅くならない）
    ("ターン", r"(?:毎|(?<![0-9０-９一二三])[0-9０-９一二三]+|各|次の|前の|同じ)ターン(?![ァ-ヴー])"),
)
# 型3の句（何が大事かを言う形、〜レベルの、テーブルの上にある）
_CALQUE_PHRASES_V250 = (
    # 何が大事かを言う形（what matters）。ここで効いてくるのが、そこで効くのは
    ("ここで効くのが", r"(?:ここで|そこで|このとき|その場面で|最後に|ここから)[、，,]?効(?:く|いてくる)の(?:が|は)"),
    # 〜レベルの（repository-level）。OS やカーネルのような層の「レベル」、レベルの高い・低い、レベル3の は外す
    ("レベルの", r"(?:リポジトリ|プロジェクト|ワークスペース|組織|ファイル)\s?レベルの(?!高|低|差|違|向上|底上げ)"
                r"(?=[一-龥々ァ-ヴーA-Za-z])"),
    # テーブルの上にある（on the table）。主語が案、選択肢、提案、議題、条件の文だけ（_calque_type3 が見る）。前に名詞や「の」が
    # ある表（users テーブル、設定テーブル、下のテーブル）は外す
    ("テーブルにある", r"(?<![一-龥々ァ-ヴーA-Za-z0-9\s　の])テーブル(?:の上)?に(?:あ(?:る|り)|載って|乗って|載せ|乗せ)"),
)
_CALQUE_PHRASE = _V220Lazy("|".join("(?:{})".format(pattern) for _, pattern in _CALQUE_PHRASES + _CALQUE_PHRASES_V250))
_CALQUE_PHRASE_EACH = tuple((name, _V220Lazy(pattern)) for name, pattern in _CALQUE_PHRASES + _CALQUE_PHRASES_V250)
# 「〜から効く」は、薬や冷房の効き方（_KIKU_RE の文字どおりの語が同じ文にある）なら出さない
_CALQUE_PHRASE_KIKU = "から効く"
# 対応表から足した句と、型1の同じ動詞（型1が当てた文では句を重ねない）
_CALQUE_PHRASE_VERB = {"ときに効く": "効く", "に響く": "響く", "データを引く": "引く", "書き込みが通る": "通る",
                       "ここで効くのが": "効く"}
# 「ここで効いてくるのが」は、「効く」の主語の位置に文字どおりの語があるとき（薬はここで効いてくるのが分かります）、
# 「のが」「のは」のあとの名詞が文字どおりの語で終わる文（そこで効くのが、わさびです）、同じ文に薬や冷房の語
# （ソフトウェアの語は除く）か分や時間の長さがある文（薬を飲むと、ここで効いてくるのが分かります）では出さない
_CALQUE_PHRASE_MATTERS = "ここで効くのが"
_CALQUE_MATTERS_FOCUS = _V220Lazy(r"[、，,]?[^。、，,]{0,8}?(?:" + _KIKU_LITERAL + r")(?:です|でした|だ|だった|である)?[。．！!]*$")
# 「テーブルにある」の主語（案、選択肢、提案、議題、条件）。答案、図案、草案、文案のような紙の物は外す。
# 「テーブルの上にある資料」のように、すぐあとに名詞が続く連体の形も外す（_CALQUE_TABLE_ATTRIBUTIVE）
_CALQUE_TABLE_SUBJECT = _V220Lazy(r"(?:(?<![答図草文])案|選択肢|提案|議題|条件)(?:は|が|も|だけが|こそ)[、，,]?[^。]{0,20}$")
_CALQUE_TABLE_ATTRIBUTIVE = _V220Lazy(r"(?:いる|いた|おり)?[一-龥々ァ-ヴーA-Za-z0-9]")
_CALQUE_TURN_CONTEXT = _V220Lazy(r"指示|会話|依頼|プロンプト|モデル|エージェント|LLM|Claude|Codex|ツール|呼び出|読み込"
                                 r"|応答|返答|トークン|コンテキスト|セッション")
# ゲームの手番の「ターン」（毎ターン山札から引く、敵の AI は毎ターン行動を選ぶ）
_CALQUE_TURN_GAME = _V220Lazy(r"ゲーム|カード|山札|手札|プレイヤー|将棋|囲碁|チェス|手番|モンスター|敵|攻撃|対戦|駒|盤")
# 「ときに効く」は、構成や運用を決める話（what matters）か、機械やシステムの語がある文だけ（疲れたときに効くストレッチは外す）
_CALQUE_KIKU_DECIDE = _V220Lazy(r"構成|設計|選ぶ|選び|決め|判断|見積|運用|導入|移行|方針|検討")
# 「に響く」の文字どおりの音と心（心に響く、音が部屋に響く）
_CALQUE_HIBIKU_LITERAL = _V220Lazy(r"(?:心|胸|耳|琴線)に(?:まで|も)?響|(?:音|声|鐘|足音|歌)(?:が|は|も)")
# 「全〇〇に響く」の形と、前からある語の一覧の形（クライアントに響く など）。「全〇〇に響く」（全運転手に響きます）は
# 技術の文書のときだけ、_CALQUE_PHRASES とは別に探す（合わせた正規表現に入れると、中の「3ターン」などの句の
# 一致を飲み込むため）。安全、健全の「全」と、全然、全く、全体として は外す
_CALQUE_HIBIKU_ALL = _V220Lazy(r"(?<![安完健保万不十])全(?!然|く|体として|体的)[^。、のをがは\s]{1,6}に(?:まで|も)?響(?:く|き|い|か)")
# 「全〇〇に響く」で外す音や言葉。「全〇〇」より前の主語（警報が鳴り、全フロアに響きます、社長の言葉は、全社員に響きました）
# と、「響く」のすぐあとの名詞（全社員に響く言葉、全館に響く爆音で、サーバーが止まりました）。1字の語は電話、録音のような
# 語の一部では当てず、「思いがけない」も外す
_CALQUE_HIBIKU_ALL_LITERAL = _V220Lazy(
    r"(?:(?<![一-鿿])(?:話|音|声|歌|鐘|雷)|言葉|一言|スピーチ|訓示|あいさつ|挨拶|ニュース|演説|呼びかけ|呼び掛け|思い|想い|理念"
    r"|名声|名曲|痛み|衝撃|振動|揺れ|アラーム|アラート|サイレン|警報|ベル|チャイム|ブザー|汽笛|放送|アナウンス|メロディー|うなり"
    r"|着信|爆音|騒音|低音|足音|大声|拍手|歓声)(?:が|は|も)(?!け)")
# 「響く」のすぐあとの名詞は、音で終わる短い複合語（警告音、着信音、大音量）も外す
# 「全〇〇に響く」で機械の語に数える「〜機」（貸出機、券売機、機械）。危機、契機、動機、待機のような語に当てないよう、
# 機械の名前の一覧で見る
_CALQUE_HIBIKU_MACHINE = _V220Lazy(
    r"(?:券売|貸出|貸し出し|発券|自販|自動販売|複合|印刷|洗濯|精算|改札|読取|読み取り|端末|飛行|旅客|撮影|計算|工作|送風|空調"
    r"|掃除|乾燥|食洗|発電|充電|交換|配膳|給湯|注文|受付|両替|入金|出金|預け払い|搬送|仕分け|検品|梱包|包装|成形|射出|切削|溶接"
    r"|検査|測定|計測|加工|[0-9０-９]+号)機|機械")
_CALQUE_HIBIKU_ALL_NOUN = _V220Lazy(
    r"(?:[一-鿿ァ-ヴー]{0,3}(?:音|声|音量)|言葉|話|一言|スピーチ|訓示|あいさつ|挨拶|メッセージ|ニュース|演説|呼びかけ|呼び掛け"
    r"|思い|想い|名前|名声|名曲|痛み|衝撃|振動|揺れ|アラーム|アラート|サイレン|警報|ベル|チャイム|ブザー|汽笛|放送|アナウンス"
    r"|メロディー|うなり|鐘|歌|音楽|拍手|歓声)")
_CALQUE_HIBIKU_LISTED = _V220Lazy(_CALQUE_PHRASES[[name for name, _ in _CALQUE_PHRASES].index("に響く")][1])
# 「に響く」の料金や費用は、機械やシステムの語がある文だけ（円安が費用に響く は外す）
_CALQUE_HIBIKU_COST = ("料金", "費用", "コスト", "請求")
# 「機械どうし」は、通信ややり取りの話のときだけ（工場の機械同士の間隔は外す）
_CALQUE_MACHINE_TALK = _V220Lazy(r"通信|やり取り|やりとり|接続|データ|API|連携|認証|リクエスト|メッセージ|プロトコル|経路")


def _v220_noun_start(text: str, position: int) -> bool:
    """position の字が漢字かカタカナか英字か。"""
    if position >= len(text):
        return False
    char = text[position]
    return _v220_kanji(char) or _v220_katakana(char) or (char.isascii() and char.isalpha())


def _v220_has_verb_stem(text: str) -> bool:
    """型1の動詞の語幹の字があるか。"""
    return not _CALQUE_VERB_STEMS.isdisjoint(text)


def _calque_subject_end(sentence: str, limit: int) -> int:
    """limit より前で最後の、機械やシステムの語が主語の「は」「が」「も」「こそ」の終わりの位置（なければ -1）。
    主語の語のあとに漢字やカタカナが続いて、人や組織の語で終わるとき（サーバー管理者は）は主語にしない。"""
    last = -1
    for subject in _CALQUE_SUBJECT_WORD.finditer(sentence, 0, limit):
        end = subject.end()
        for extra in range(_CALQUE_SUBJECT_EXT + 1):
            position = end + extra
            if position >= limit:
                break
            particle = next((item for item in _CALQUE_SUBJECT_PARTICLES if sentence.startswith(item, position)), None)
            if particle is not None:
                if position + len(particle) <= limit and not _CALQUE_PERSON_EXT.search(sentence[end:position]):
                    last = position + len(particle)
                break
            char = sentence[position]
            if not (_v220_kanji(char) or _v220_katakana(char) or (char.isascii() and char.isalnum())):
                break
    return last


def _calque_type1(sentence: str, words: list) -> bool:
    """型1に当たれば True（当たった動詞の辞書の形を words に足す）。"""
    if not _v220_has_verb_stem(sentence) or not _CALQUE_SUBJECT_WORD.search(sentence):
        return False
    found = False
    established = None
    matches = sorted((match.start(), index, match) for index, (stem, _, pattern) in enumerate(_CALQUE_VERB_EACH)
                     if stem in sentence for match in pattern.finditer(sentence))
    covered = -1
    for start, index, match in matches:
        if start < covered:
            continue    # 同じ所に当たった別の動詞（引き込む と 引く）は、表の前のほうだけを数える
        if start and _v220_kanji(sentence[start - 1]) and _CALQUE_VERB_EACH[index][1] not in _CALQUE_COMPOUND_OK \
                and not match.group().startswith("食べ"):
            continue    # 漢字の熟語の一部（不足し、共通す、電話し、有効、朝食）
        covered = match.end()
        subject_end = _calque_subject_end(sentence, start)
        if subject_end < 0 or start - subject_end > _CALQUE_SUBJECT_REACH \
                or _CALQUE_SUBJECT_BREAK.search(sentence, subject_end, start):
            continue
        if any(person.end() > subject_end for person in _CALQUE_PERSON_SUBJECT.finditer(sentence, subject_end, start)):
            continue
        if established is None:
            established = [m.span() for m in _CALQUE_ESTABLISHED_TYPE1_RE.finditer(sentence)]
        if any(left <= start < right for left, right in established):
            continue
        kana_match = _CALQUE_KANA_RUN.match(sentence, match.end())
        assert kana_match is not None
        kana = kana_match.group()
        if (match.group() + kana).endswith(_CALQUE_ATTRIBUTIVE_END) \
                and _v220_noun_start(sentence, match.end() + len(kana)):
            continue    # 名詞を修飾する形（拾った通知、話した内容）
        if kana.startswith(_CALQUE_REQUEST):
            continue    # 読み手に頼む形（1行を足してください）。動作をするのは読み手
        words.append(_CALQUE_VERB_EACH[index][1])
        found = True
    return found


def _v220_noun_or_alnum(text: str, position: int) -> bool:
    return 0 <= position < len(text) and (_v220_kanji(text[position]) or _v220_katakana(text[position])
                                          or _v220_alnum(text[position]))


def _calque_saki_spans(sentence: str) -> list:
    """「〜先」の当たり（_CALQUE_SAKI_KANJI の語か、漢字1字と連用形の送り仮名のあとの「先」）の (始め, 終わり)。"""
    spans = []
    position = sentence.find("先")
    while position >= 0:
        end = position + 1
        if position and not (end < len(sentence) and (_v220_kanji(sentence[end]) or _v220_katakana(sentence[end]))):
            start = None
            for word in _CALQUE_SAKI_KANJI:
                if sentence.startswith(word, position - len(word)) and position >= len(word):
                    start = position - len(word)
                    break
            if start is None and sentence[position - 1] in _CALQUE_SAKI_TAIL:
                if position >= 2 and _v220_kanji(sentence[position - 2]):
                    start = position - 2
                elif (position >= 3 and _v220_hiragana(sentence[position - 2]) and _v220_kanji(sentence[position - 3])
                      and sentence[position - 2:position] != "より"):
                    start = position - 3
            if start is not None and not _v220_noun_or_alnum(sentence, start - 1):
                spans.append((start, end))
        position = sentence.find("先", end)
    return spans


def _calque_has_org(sentence: str) -> bool:
    """文に組織の名前（総務部、情報システム課、サポートセンター）があるか。"""
    if any(word in sentence for word in _CALQUE_ORG_WORDS):
        return True
    for index, char in enumerate(sentence):
        if (char in _CALQUE_ORG_SUFFIXES and index and (_v220_kanji(sentence[index - 1]) or _v220_katakana(sentence[index - 1]))
                and not (index + 1 < len(sentence) and _v220_kanji(sentence[index + 1]))):
            return True
    return False


def _v220_doc_tech(text: str) -> bool:
    """技術の文書か（_CALQUE_TECH の語のうち、_CALQUE_DOC_TECH_GENERAL を除いた語が _CALQUE_DOC_TECH_MIN 種類以上）。"""
    return len(set(_CALQUE_TECH.findall(text)) - _CALQUE_DOC_TECH_GENERAL) >= _CALQUE_DOC_TECH_MIN


def _entry_subject_end(sentence: str, cache: dict) -> int:
    """要求や呼び出しの主題（_CALQUE_ENTRY_SUBJECT）のいちばん早い終わり（なければ -1）。入口の一致ごとに文頭から
    読み直さず、文1つにつき1回だけ探す。"""
    if "subject" not in cache:
        first = _CALQUE_ENTRY_SUBJECT.search(sentence)
        cache["subject"] = first.end() if first is not None else -1
    return cache["subject"]


def _calque_type2(sentence: str, words: list, doc_tech: bool = False) -> bool:
    """型2に当たれば True（当たった名詞を words に足す）。doc_tech は技術の文書か（入口と出口の拾い方に使う）。"""
    if not _CALQUE_PLACE_HEAD.search(sentence):
        return False
    found = False
    tech = None
    cache = {}
    for match in _CALQUE_PLACE_ALWAYS.finditer(sentence):
        if match.group() != "受け口" and _v220_noun_start(sentence, match.end()):
            continue
        if not match.group().endswith(("受け口", "の口")):
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech:
                continue
        words.append("受け口" if match.group() == "受け口" else "口")
        found = True
    for start, end in _calque_saki_spans(sentence):
        word = sentence[start:end]
        before = sentence[max(0, start - 8):end]
        if _CALQUE_SAKI_TIME.search(word) or any(before.endswith(item) for item in _CALQUE_ESTABLISHED_SAKI):
            continue
        # 一覧の着地先などのほかは、技術の語のある文の「〜先」だけを見る（旅行の立ち寄り先、父の働き先は見ない）
        if not any(word.endswith(kanji + "先") for kanji in _CALQUE_SAKI_KANJI):
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech:
                continue
        words.append(word)
        found = True
    end_is_noun = _v220_noun_start
    for match in _CALQUE_PLACE_CONTEXT.finditer(sentence):
        word = match.group()
        if word != "の口" and end_is_noun(sentence, match.end()):
            continue
        before = sentence[max(0, match.start() - 10):match.start()]
        if word == "の口":
            if _CALQUE_MOUTH_REAL.search(sentence[max(0, match.start() - 6):match.end()]) \
                    or _CALQUE_MOUTH_IDIOM.match(sentence, match.start() + 1):
                continue
            if before.endswith(("向け", "用")):
                continue    # _CALQUE_PLACE_ALWAYS で数えた
            word = "口"
        elif _CALQUE_PLACE_REAL.search(before):
            continue
        if word == "窓口":
            if (_CALQUE_PLACE_ORG.search(before) or not _CALQUE_CODE.search(sentence)
                    or _calque_has_org(sentence)):
                continue
        else:
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech and not (doc_tech and word in ("入口", "入り口", "出口")
                                 and _CALQUE_ENTRY_FLOW.match(sentence, match.end())
                                 and 0 <= _entry_subject_end(sentence, cache) <= match.start()
                                 and not _CALQUE_PLACE_REAL_DOC.search(before)
                                 and not _CALQUE_ENTRY_WAIT.match(sentence, match.end())):
                continue
        words.append(word)
        found = True
    return found


def _calque_type3(sentence: str, words: list, doc_tech: bool = False) -> bool:
    """型3に当たれば True（当たった句の名前を words に足す）。doc_tech は技術の文書か（「全〇〇に響く」の拾い方に使う）。
    文ごとに決まる値（機械やシステムの語があるか など）は、句の一致ごとに文を読み直さず、文1つにつき1回だけ求める。"""
    if not _CALQUE_PHRASE_HEAD.search(sentence):
        return False
    found = False
    type1_here = None
    tech = None         # 文に機械やシステムの語（_CALQUE_TECH）があるか
    literal = None      # 文字どおりの音と心の「響く」（_CALQUE_HIBIKU_LITERAL）があるか
    hibiku = False      # この文で「に響く」を足したか
    for match in _CALQUE_PHRASE.finditer(sentence):
        name = next((name for name, each in _CALQUE_PHRASE_EACH if each.match(sentence, match.start())), match.group())
        if name in (_CALQUE_PHRASE_KIKU, "ときに効く") and _KIKU_RE["context"].search(sentence):
            continue
        if name == "ときに効く" and _CALQUE_ESTABLISHED_TYPE1_RE.search(sentence):
            continue
        if name == _CALQUE_PHRASE_MATTERS:
            verb_at = sentence.index("効", match.start())
            if (_KIKU_RE["literal_subject"].search(sentence[:verb_at]) or _CALQUE_MATTERS_FOCUS.match(sentence, match.end())
                    or _KIKU_RE["context_near"].search(sentence) or _KIKU_RE["timing"].search(sentence)):
                continue
        if name == "テーブルにある" and (not _CALQUE_TABLE_SUBJECT.search(sentence, 0, match.start())
                                       or _CALQUE_TABLE_ATTRIBUTIVE.match(sentence, match.end())):
            continue
        if name == "ときに効く" and not _CALQUE_KIKU_DECIDE.search(sentence):
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech:
                continue
        if name == "に響く":
            if literal is None:
                literal = bool(_CALQUE_HIBIKU_LITERAL.search(sentence))
            if literal:
                continue
            if match.group().startswith(_CALQUE_HIBIKU_COST):
                if tech is None:
                    tech = bool(_CALQUE_TECH.search(sentence))
                if not tech:
                    continue
        if name == "機械どうし" and not _CALQUE_MACHINE_TALK.search(sentence):
            continue
        if name == "書き込みが通る" and match.group().startswith("アクセス"):
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech:
                continue
        # 型1が同じ文で同じ動詞を当てたときは、対応表から足した形を重ねない（このキャッシュは、応答の速さに響きます）。
        # 同じ行のほかの文の型1とは比べない
        verb = _CALQUE_PHRASE_VERB.get(name)
        if verb:
            if type1_here is None:
                type1_here = []
                _calque_type1(sentence, type1_here)
            if verb in type1_here:
                continue
        # 「ターン」は、ゲームの手番でなく、指示や会話、モデルの呼び出しの話のときだけ
        if name == "ターン" and (not _CALQUE_TURN_CONTEXT.search(sentence) or _CALQUE_TURN_GAME.search(sentence)):
            continue
        words.append(name)
        found = True
        if name == "に響く":
            hibiku = True
    # 一覧にない「全〇〇に響く」は、技術の文書の、機械やシステムの語（「〜機」を含む）がある文だけ。一覧の形を含む
    # 「全〇〇」（全クライアントに響く、全費用に響く）は上で見たので外す。音や言葉の名詞が続く形（全社員に響く言葉）、
    # 響き渡る、響くほど、響くように、音や言葉が主語の文、全身の響き、文字どおりの音と心の響きは外す
    if doc_tech and not hibiku and "全" in sentence:
        subject_end = None    # 音や言葉の主語（_CALQUE_HIBIKU_ALL_LITERAL）のいちばん早い終わり。なければ -1
        for match in _CALQUE_HIBIKU_ALL.finditer(sentence):
            if _CALQUE_HIBIKU_LISTED.search(sentence, match.start(), match.end()) or match.group().startswith("全身"):
                continue
            if literal is None:
                literal = bool(_CALQUE_HIBIKU_LITERAL.search(sentence))
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if literal or not (tech or _CALQUE_HIBIKU_MACHINE.search(sentence)):
                break           # どれも文ごとに決まるので、ほかの一致も外れる
            after = match.end() + (1 if sentence.startswith("た", match.end()) else 0)
            if (_CALQUE_HIBIKU_ALL_NOUN.match(sentence, after) or sentence.startswith(("渡", "わた", "ほど", "よう"), after)
                    or sentence.startswith(("渡", "わた"), match.end())):
                continue
            if subject_end is None:
                first = _CALQUE_HIBIKU_ALL_LITERAL.search(sentence)
                subject_end = first.end() if first is not None else -1
            if 0 <= subject_end <= match.start():
                continue
            if type1_here is None:
                type1_here = []
                _calque_type1(sentence, type1_here)
            if "響く" in type1_here:
                break
            words.append("に響く")
            found = True
            break
    return found


def _calque_message(types: Sequence, word_types: Sequence) -> str:
    """calque の message。1行に1件なので、当たった言い方を並べる（同じ行の2つ目を読み落とさないため。置き換え先の語は出さない）。"""
    hit = tuple(dict.fromkeys(word for word, _ in word_types))
    shown = "。当たった言い方: " + "、".join(hit) if hit else ""
    return "直訳語（{}{}）{}".format("。".join(_CALQUE_TYPE_NAMES[number] for number in types), shown, _V220_MESSAGE_TAIL)


def _v220_word_findings(analysis: dict, findings: list) -> list[dict]:
    """calque、metaphor_label、katakana_term、thin_evaluation の候補。

    文書全体に一度だけ手掛かり（_V220_TRIGGER_LITERALS と2つの一覧の語）を当て、当たった行と、
    見出しと1行目のうちラベルになりうる行だけを見える文字で調べる。
    既存の規則の候補は findings から読む（同じ行に metaphor_verb があれば calque を出さない）。"""
    rows = analysis["lines"]
    if not rows:
        return []
    katakana_re, thin_re, thin_nouns, trigger = _v220_patterns()
    thin_noun_re = _V220_COMPILED.get("thin_nouns")
    text = analysis["text"]
    starts = None
    candidate_lines = set()
    for pattern in trigger:
        for match in pattern.finditer(text):
            if starts is None:
                starts = [row["start"] for row in rows]
            candidate_lines.add(bisect_right(starts, match.start()))
    # ラベルを見る行: 見出しの行と、文書の1行目（frontmatter と空行を除く）。伏せる前の文字でも長すぎる行は先に外す
    label_lines = set()
    for block in analysis["blocks"]:
        if block["kind"] == "heading":
            label_lines.update(row["line"] for row in block["lines"] if _label_may_fit(row))
    for row in rows:
        if row["kind"] in ("frontmatter", "blank"):
            continue
        if _label_may_fit(row):
            label_lines.add(row["line"])
        break
    if not candidate_lines and not label_lines:
        return []
    blocked_all = {finding["line"] for finding in findings if finding["rule"] == "metaphor_verb"}
    out = []
    doc_tech = None
    for line_no in sorted(candidate_lines | label_lines):
        row = rows[line_no - 1]
        if row["kind"] not in ("paragraph", "list", "heading", "table") or row["quote_depth"]:
            continue
        scan = _v220_scan_text(analysis, line_no)
        if not scan.strip():
            continue
        snippet = row["raw"].strip()
        label = _metaphor_label(analysis, row, scan) if line_no in label_lines else None
        if label is not None:
            out.append({"rule": "metaphor_label", "line": line_no, "severity": "info",
                        "message": "見出しか1行目の比喩のラベル" + _V220_MESSAGE_TAIL, "snippet": snippet,
                        "_words": (label,)})
        if line_no not in candidate_lines:
            continue
        # 伏せたあとの行に、規則ごとの手掛かりの語があるかを先に見る
        finders = []
        if line_no not in blocked_all:
            if _v220_has_verb_stem(scan) and _CALQUE_SUBJECT_WORD.search(scan):
                finders.append((1, _calque_type1))
            if label is None and _CALQUE_PLACE_HEAD.search(scan):
                if doc_tech is None:
                    doc_tech = _v220_doc_tech(text)
                # 見出しのラベルと同じ行の型2は metaphor_label だけを出す
                finders.append((2, functools.partial(_calque_type2, doc_tech=doc_tech)))
            if _CALQUE_PHRASE_HEAD.search(scan):
                if doc_tech is None:
                    doc_tech = _v220_doc_tech(text)
                finders.append((3, functools.partial(_calque_type3, doc_tech=doc_tech)))
        thin_possible = (thin_re is not None and thin_noun_re is not None
                         and thin_noun_re.search(scan) is not None)
        sentences = ()
        if finders or thin_possible:
            sentences = [part for part in (piece.strip() for piece in _V220_SENTENCE.findall(scan)) if part]
        types = []
        calque_words = []
        word_types = []
        for number, finder in finders:
            before = len(calque_words)
            if any([finder(sentence, calque_words) for sentence in sentences]):
                types.append(number)
                word_types.extend((word, number) for word in calque_words[before:])
        if types:
            out.append({"rule": "calque", "line": line_no, "severity": "info",
                        "message": _calque_message(types, word_types), "snippet": snippet,
                        "_words": tuple(dict.fromkeys(calque_words)), "_word_types": tuple(word_types)})
        if katakana_re is not None:
            katakana_words = katakana_re.findall(scan)
            if katakana_words:
                out.append({"rule": "katakana_term", "line": line_no, "severity": "info",
                            "message": "意味の薄くなりやすいカタカナ語" + _V220_MESSAGE_TAIL, "snippet": snippet,
                            "_words": tuple(dict.fromkeys(katakana_words))})
        if thin_possible:
            thin_words = []
            for sentence in sentences:
                match = _v220_thin_match(sentence)
                if match:
                    body = match.group("body")
                    thin_words.append(next((noun for noun in thin_nouns if body.startswith(noun)), body))
            if thin_words:
                out.append({"rule": "thin_evaluation", "line": line_no, "severity": "info",
                            "message": "中身の薄い評価の文" + _V220_MESSAGE_TAIL, "snippet": snippet,
                            "_words": tuple(dict.fromkeys(thin_words))})
    return out


_V230_RULES = ("renyo_noun",)
_RENYO_MESSAGE = "他動詞を1語だけ名詞にした語を「の」で受ける形（当たった言い方: {}）" + _V220_MESSAGE_TAIL
# 「の」の前は名詞の終わりになりうる字（漢字、仮名、英数字、閉じ括弧、半角の空白）。半角の空白は「API の確かめ」と、
# カギ括弧や識別子を空白に伏せた「「結果」の確かめ」「2.2.0 の確かめ」のため。
# 語のあとは助詞（が、を、は、に、で、も、と、や、へ、の、だけ、まで、など、から、より、こそ、さえ、しか、ばかり、くらい、
# ぐらい、ほど）か、句読点、括弧、・、／、：、表の区切りの |、空白、行の終わり。動詞に続く形（入れやすい、確かめにくさ、
# 決めがたそう）の「や」「に」「が」と、「探しもの」「入れもの」の「も」は外す。「か」（直しかた）と「だ」（探しだす）は入れない。
# 「計り」「量り」は道具の名前（キッチン用の計り）にもなるので一覧に入れない（人の文章で見つけた例）
_RENYO_BEFORE = r"(?<=[一-龥々〆ァ-ヴーぁ-んA-Za-z0-9０-９Ａ-Ｚａ-ｚ）」』\]) ])の"
_RENYO_AFTER = (r"(?=が(?!た[いかくけさそ])|を|は|に(?!く[いかくけさそ])|で|も(?!の)|と|や(?!す[いかくけさそ])|へ|の|だけ|まで"
                r"|など|から|より|こそ|さえ|しか|ばかり|くらい|ぐらい|ほど"
                r"|[、。，．）」』！？!?（(・／/:：|｜\s]|$)")
_RENYO_COMPILED = {}


def _renyo_pattern() -> tuple[re.Pattern[str] | None, re.Pattern[str] | None, dict[str, tuple[str, ...]]]:
    """一覧から組んだ正規表現（文書全体の絞り込み用と、行の見える文字用）と、語ごとに外す後ろの文字列のタプル。
    一覧ごとに1回だけ組む。一覧が空なら (None, None, {})。絞り込みは前後の先読みを持たず、「の」と語のあいだの「*」「_」
    を許す（太字の印 ** が「の」と語のそばにあっても、見える文字では消えるので、その行を見落とさないため）。"""
    items, source = _v220_load_list("renyo-nouns")
    key = (source, id(items))
    if _RENYO_COMPILED.get("key") == key:
        return _RENYO_COMPILED["value"]
    skip_after = {}
    words = []
    for item in items:
        word, _, after = item.partition("\t")
        word = word.strip()
        if not word:
            continue
        words.append(word)
        if after.strip():
            skip_after[word] = tuple(part for part in after.strip().split("|") if part)
    value = (None, None, {})
    if words:
        alternation = "|".join(map(re.escape, sorted(set(words), key=len, reverse=True)))
        value = (re.compile(_RENYO_BEFORE + "(" + alternation + ")" + _RENYO_AFTER),
                 re.compile("の[*_]*(?:" + alternation + ")"), skip_after)
    _RENYO_COMPILED["key"] = key
    _RENYO_COMPILED["value"] = value
    return value


# 2.4.0: スライドの見出しと1行の箇条の、外してよい読点（slide_comma。slides だけ。info で、点数に入れない）。
# 見出しは一目で読むので、地の文なら残す読点のうち、間を作るだけのものを外す。拾うのは、文頭のつなぎの語のあと（だから、それでも）、
# 文頭の決まった「〜ば」のあと（振り返れば、数字で言えば）、文頭の6字以上の時や場面の句のあと（その日のうちに）、文頭から15字以内の
# 主題のあと（〜には、〜は）、文頭から10字以内の主語のあと（名詞＋が）、目的語の「を」のあと（長い目的語も。見出しでは長い目的語のあとの
# 読点も外す）。逆接、条件、理由や目的、名詞の並び、短い時の句（その夜、）、長い主語のあとの読点は拾わない。
# 見るのは、1行で終わる60字以下の見出し、箇条、段落の行（続きの行がある項目と、複数行の段落の行は見ない）。行頭の箇条の印、「・」「①」
# 「(1)」の印、【】、「結論：」のようなラベルは外してから文頭を決める。カギ括弧と引用符の中、コード、リンク、英数字の識別子は「＿」に伏せて、
# 伏せた語のあとを文頭と取り違えないようにする。「も」で終わる逆接（ても、でも、けれども、ながらも、つつも、とも）、目的と条件の
# 「ためには」「するには」「以上は」「ては」「〜ときは」「〜場合は」は主題に数えない。主題の読点のあとに別の主語（担当者が、私たちが、部長は）が続く行は、
# 主題と主語を読み分ける読点なので拾わない（「〜がない」「〜がある」「〜が多い」のような、あるかないかや数を言う文の「が」は除く）。
# 主題の読点のあとに読点で区切った並びが続く形（〜のは、A、B、C）と、「Aを、Bを、」「Aが、Bが、」の並びも拾わない。1行に1件。
def _v230_renyo_findings(analysis: dict) -> list[dict]:
    """renyo_noun の候補。文書全体に一度だけ一覧の語を当て、当たった行を見える文字で調べる。"""
    pattern, prefilter, skip_after = _renyo_pattern()
    rows = analysis["lines"]
    if pattern is None or not rows:
        return []
    assert prefilter is not None
    text = analysis["text"]
    starts = None
    candidate_lines = set()
    for match in prefilter.finditer(text):
        if starts is None:
            starts = [row["start"] for row in rows]
        candidate_lines.add(bisect_right(starts, match.start()))
    out = []
    for line_no in sorted(candidate_lines):
        row = rows[line_no - 1]
        if row["kind"] not in ("paragraph", "list", "heading", "table") or row["quote_depth"]:
            continue
        scan = _v220_scan_text(analysis, line_no)
        words = []
        for match in pattern.finditer(scan):
            word = match.group(1)
            if any(scan.startswith(part, match.end()) for part in skip_after.get(word, ())):
                continue
            words.append(word)
        if words:
            words = tuple(dict.fromkeys(words))
            out.append({"rule": "renyo_noun", "line": line_no, "severity": "info",
                        "message": _RENYO_MESSAGE.format("、".join("の" + word for word in words)),
                        "snippet": row["raw"].strip(), "_words": words})
    return out
# 2.5.0: AI の文章によく出る言い回し（ai_phrase。info で、点数に入れない。allow.txt の語で外せる）。どれも、何が足りない文か
# （判断した人、潜むものの中身、何が起きるか）を確かめるための候補で、置き換え先の語は出さない。当てる形は次のとおり。
# - 見立てです: 文末の「（という|との|の）見立てです」「見立てだ」で、「見立て」より前に判断した人や組織の語（_AI_JUDGE。
#   「政府の見立てだ」の「の」も見る）がない文。「医師の見立てでは」「見立てどおり」「見立て違い」は文末の形でないので当たらない
# - 潜む: 「（リスク|問題|課題|罠|落とし穴|危険|本質|闇|バグ）が潜む」と、「〜に潜む」のすぐあと（各種の、様々な のような語を
#   挟んでよい）の同じ語。「潜む危険な動物」「潜むマダニの危険」のように、潜むものが動物、虫、人の文は当たらない
# - が招く: 「〜が招く」のすぐあとに名詞が続く形（油断が招く失敗）。人や組織が招く文（社長が招く客、母が招く客、県が招く講師）と
#   「〜を招く」は外す
# - 欠かせない存在: 「今や」と「欠かせない存在」が同じ文にある形と、「欠かせない存在となっています」。どちらかだけの文は外す
# - という挙動を排除: 「という挙動を（排除|防止|阻止）」
# - なんよ: 地の文の文末の「なんよ」「なんよね」。台詞の script と読み物の essay では外す
# - て形の体言止め: 段落の文で「〜して、〜を＋漢語の名詞。」で終わる形（見直して、速度を改善。）。見出し、箇条書き、表は見ない。
#   slides、minutes、promo、script では外す。「について、」「に応じて、」「にて、」「のせいで、」のような、動詞でない「て」「で」は数えない
# 見るのは新しい語の規則と同じ見える文字（カギ括弧と引用符の中、英数字の識別子を伏せた字）。引用（> の行）、コード、frontmatter、
# HTML は見ない。1行に1件で、当たった言い方を _words に並べる。
_V250_RULES = ("ai_phrase",)
_AI_PHRASE_MESSAGE = "AIの文章によく出る言い回し（当たった言い方: {}）" + _V220_MESSAGE_TAIL
_AI_PHRASE_HEAD = _V220Lazy(r"見立て|潜|招く|欠かせない存在|挙動を|なんよ|を[一-龥々]{2,}[。．]")
# 判断した人と招く人や組織の語。語のあとに「たち」「ら」「ども」「陣」「側」が付いてもよい
_AI_PERSON_WORDS = (r"人|者|員|士|医|さん|様|さま|氏|先生|医師|専門家|アナリスト|エコノミスト|記者|筆者|編集部|当社|弊社|同社|会社"
                    r"|政府|当局|警察|検察|日銀|銀行|気象台|省|庁|局|都|府|県|市|区|町|村|国|自治体|委員会|協会|機関|大学|研究所"
                    r"|チーム|部|課|業界|社長|会長|部長|課長|店長|院長|監督|代表|教授|首相|大臣|知事|市長|私|僕|わたし|ぼく|我々"
                    r"|われわれ|彼|彼女|あなた|皆さん")
_AI_PERSON_PLURAL = r"(?:たち|ら|ども|陣|側)?"
_AI_JUDGE = _V220Lazy(r"(?:" + _AI_PERSON_WORDS + r")" + _AI_PERSON_PLURAL + r"(?:は|が|も|の|では|によると|によれば|としては)")
_AI_HIDDEN = r"(?:リスク|問題|課題|罠|わな|落とし穴|危険性?|本質|闇|バグ)"
# 「〜に潜む」と潜むものの間に挟んでよい語
_AI_HIDDEN_BEFORE = r"(?:各種の|様々な|さまざまな|多くの|数々の|大きな|思わぬ|見えない|本当の|深刻な|重大な|新たな)?"
_AI_INVITER = _V220Lazy(r"(?:" + _AI_PERSON_WORDS + r"|上司|父|母|親|夫|妻|兄|姉|弟|妹|祖父|祖母|息子|娘|子ども|子供|家族|友人"
                        r"|知人|友達|先輩|後輩|同僚|店|当店|学校|団体|館|団|主催者|運営)" + _AI_PERSON_PLURAL + r"$")
_AI_PHRASE_FORMS = (
    ("見立てです", _V220Lazy(r"(?:という|との|の)見立て(?:です|でした|だ|だった|である)[。．！!]*$")),
    ("潜む", _V220Lazy(_AI_HIDDEN + r"(?:が|も|は)[、，,]?潜(?:む|ん[でだ]|み|ま|め)|に潜(?:む|んでいる|んでいた|んだ)"
                     + _AI_HIDDEN_BEFORE + _AI_HIDDEN + r"(?!な)")),
    ("が招く", _V220Lazy(r"が招く(?=[一-龥々ァ-ヴー])")),
    ("欠かせない存在", _V220Lazy(r"今や[^。]*?欠かせない存在|欠かせない存在と(?:なって|なりつつ)")),
    ("という挙動を排除", _V220Lazy(r"という挙動を(?:排除|防止|阻止)")),
    ("なんよ", _V220Lazy(r"なんよね?[。．！!？?]*$")),
    ("て形の体言止め", _V220Lazy(r"(?:[ぁ-ん]て|[んい]で|[一-龥々]て)[、，,][^。、，,]{1,20}?を[一-龥々]{2,}[。．]$")),
)


def _v250_ai_phrase_findings(analysis: dict, doc_type: str | None) -> list[dict]:
    """ai_phrase の候補。文書全体に一度だけ手掛かり（_AI_PHRASE_HEAD）を当て、当たった行を見える文字で調べる。"""
    rows = analysis["lines"]
    if not rows:
        return []
    text = analysis["text"]
    starts = None
    candidate_lines = set()
    for match in _AI_PHRASE_HEAD.finditer(text):
        if starts is None:
            starts = [row["start"] for row in rows]
        candidate_lines.add(bisect_right(starts, match.start()))
    out = []
    for line_no in sorted(candidate_lines):
        row = rows[line_no - 1]
        if row["kind"] not in ("paragraph", "list", "heading", "table") or row["quote_depth"]:
            continue
        scan = _v220_scan_text(analysis, line_no)
        words = []
        for sentence in (part.strip() for part in _V220_SENTENCE.findall(scan)):
            if not sentence:
                continue
            for name, pattern in _AI_PHRASE_FORMS:
                match = pattern.search(sentence)
                if match is None or name in words:
                    continue
                if name == "見立てです" and _AI_JUDGE.search(sentence, 0, sentence.index("見立て", match.start())):
                    continue
                if name == "が招く" and _AI_INVITER.search(sentence, 0, match.start()):
                    continue
                if name == "なんよ" and (doc_type in ("script", "essay") or row["kind"] not in ("paragraph", "list")):
                    continue
                if name == "て形の体言止め" and (doc_type in ("slides", "minutes", "promo", "script")
                                              or row["kind"] != "paragraph"
                                              or sentence[:match.start() + 2].endswith(_TE_NOT_VERB)):
                    continue
                words.append(name)
        if words:
            words = tuple(words)
            out.append({"rule": "ai_phrase", "line": line_no, "severity": "info",
                        "message": _AI_PHRASE_MESSAGE.format("、".join(words)), "snippet": row["raw"].strip(),
                        "_words": words})
    return out
# 2.2.0 の文の形の規則（say_hedge、copy_comma_noun、bare_verb_chain）。
# 既存の表（_PATTERN_LITERAL_HINTS）とは別に、行ごとに見える文字（_prose_visible_text）を見る。
# カギ括弧、二重カギ括弧、[ ]、引用符の中は伏せる。引用の行、表、コード、frontmatter、HTML は見ない。
_SHAPE_RULE_MESSAGES = {
    "say_hedge": "文末の「と言えるでしょう」の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。推量の「でしょう」は残します。ある区分に当たるかを判断する文（指摘の出ないもの）は直しません。",
    "copy_comma_noun": "修飾語と短い名詞の間に読点を打って名詞で終える、キャッチコピーの型の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。",
    "bare_verb_chain": "主語も目的語もない動詞を読点で並べて止める文の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。",
}
# 文書の元の文字で、3つの規則のどれかに当たりうる所（速さのための絞り込み）。当たった行だけを見える文字で調べる。
# 見える文字では「*」「_」が消えるので、読点と句点の前の「*」「_」は許す
_SHAPE_GATE_WORDS = ("えるでしょう",)
_SHAPE_COMMA_GATE = re.compile(
    r"[ないたのうくぐすつぬぶむるか][*_]*、(?:[^、。\n]{1,14}。|[^。\n]{0,30}、[^、。\n]{0,30}[うくぐすつぬぶむる][*_]*。)")
_SHAPE_HEADING_MARK = re.compile(r"^\s*#{1,6}(?:\s+|$)|\s+#+\s*$")
_SHAPE_QUOTE_MARKS = ("「", "『", "[", "“", '"')
_SHAPE_CURLY_QUOTED = re.compile(r"“[^“”]*”|\"[^\"]*\"")
_SHAPE_SENTENCE = re.compile(r"[^。！？!?]+(?:[。！？!?]+|$)")
# 文末の「と言えるでしょう」。問いの「でしょうか」は含めない
_SAY_HEDGE = re.compile(r"(.{0,4})と(?:言|い)えるでしょう[。！!]?$")
# 直前が体言（漢字かカタカナで終わる）なら、ある語に当たるかの判断（「契約と言えるでしょう」）として出さない
_SAY_HEDGE_NOUN_END = re.compile(r"[一-龯々〆ヵヶァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ]")
# ただし、形容動詞の語幹（「有効」「効果的」など）のあとは評価のぼかしとして出す（「有効と言えるでしょう」）
_SAY_HEDGE_NA_ADJECTIVE = re.compile(r"(?:的|重要|有効|必要|適切|十分|妥当|有用|大切|確実|可能|重大|有益|顕著|明確|"
                                     r"不可欠|理想|最適|容易|困難|安全|安心)$")
# 「〜に当たると言えるでしょう」も、ある区分に当たるかの判断として出さない
_SAY_HEDGE_JUDGE = re.compile(r"(?:に|へ)(?:当た|あた)る(?:と(?:言|い)えるでしょう)|に該当する(?:と(?:言|い)えるでしょう)")
# 「な、」「い、」「た、」「の、」のあとに6字以下の名詞（か名詞＋を）で「。」。名詞は漢字、仮名、英数字だけ
_COPY_COMMA_NOUN = re.compile(r"(?:^|、)([^、]+?[ないたの])、([一-龯々〆ヵヶぁ-ゖァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ]{1,7})。$")
# 読点の前の部分に助詞の「を」「は」「が」「で」があれば、修飾語ではなく節とみて出さない（「条件を残した、やや長い出力。」）
_COPY_MODIFIER_PARTICLE = re.compile(r"を|[はがで](?![ぁ-ゖ])")
# 読点の前が感動詞、接続詞、指示語なら出さない（「はい、了解。」「また、今度。」）
_COPY_NOT_MODIFIER = frozenset(("はい", "いいえ", "いい", "また", "まあ", "あの", "その", "この", "どの", "あのね",
                                "ええ", "いや", "おい", "なお", "ただ", "しかし", "ちなみ", "つまり", "さて", "では"))
# 名詞のほうが述語や助詞で終わるなら名詞ではない（「迷った、決めた。」「ある、です。」）。「の」を含む名詞句（「内部の誤り」）も外す
_COPY_I_NOUNS = frozenset(("思い", "想い", "願い", "違い", "匂い", "出会い", "味わい", "祝い", "誓い", "迷い", "笑い", "住まい",
                           "佇まい", "問い", "扱い", "装い", "幸い"))
_COPY_NOUN_NOT = re.compile(r"(?:[るたすだてでねよわかぞぜさうくぐつぬぶむずじ]|ない|ません|しい|たい)$|[はがにでの]")
# 終止形（う段の仮名）か「終止形＋か」で終わる部分
_BARE_VERB_PART = re.compile(r"[一-龯々ぁ-ゖァ-ヴー]*[うくぐすつぬぶむる]か?$")
_BARE_VERB_LAST = re.compile(r"[一-龯々ぁ-ゖァ-ヴー]*[うくぐすつぬぶむる]$")
_BARE_VERB_POLITE = re.compile(r"(?:ます|です|ません)か?$")
# 動詞ではないのに、う段の仮名で終わる部分（「一つ、二つ、三つ。」の数、「楽しく」の形容詞）
_BARE_VERB_NOT_VERB = re.compile(r"(?:^[一二三四五六七八九十百千0-9０-９いくひとふたみよ]+つ|しく)か?$")
# 助詞の「は」「が」「に」: 後ろが平仮名でない（漢字やカタカナの語が続く）ものを助詞とみる。「を」はいつも助詞
_BARE_VERB_PARTICLE = re.compile(r"を|[はがに](?![ぁ-ゖ])")


def _shape_visible_text(analysis: dict, row: dict) -> str:
    """形の規則で見る行の文字。見ない行は空の文字列。引用の中身は空白で伏せる。"""
    if row["kind"] not in ("paragraph", "list", "heading") or row["quote_depth"]:
        return ""
    text = _prose_visible_text(analysis, row["line"])
    text = text.replace("__", "").replace("*", "")
    if row["kind"] == "heading":
        text = _SHAPE_HEADING_MARK.sub("", text)
    if any(mark in text for mark in _SHAPE_QUOTE_MARKS):
        text = _mask_quoted_segments(text)
        if "“" in text or '"' in text:
            text = _SHAPE_CURLY_QUOTED.sub(lambda match: " " * len(match.group()), text)
    return text


def _say_hedge_sentence(sentence: str) -> bool:
    match = _SAY_HEDGE.search(sentence)
    if not match:
        return False
    head = match.group(1)
    if _SAY_HEDGE_JUDGE.search(sentence):
        return False
    if head and _SAY_HEDGE_NOUN_END.match(head[-1]) and not _SAY_HEDGE_NA_ADJECTIVE.search(head):
        return False
    return True


def _copy_comma_noun_sentence(sentence: str) -> bool:
    if len(sentence) > 20 or not sentence.endswith("。"):
        return False
    match = _COPY_COMMA_NOUN.search(sentence)
    if not match:
        return False
    modifier, noun = match.group(1).strip(), match.group(2)
    if noun.endswith("を"):
        noun = noun[:-1]
    if (not noun or len(noun) > 6 or len(modifier) < 2 or modifier in _COPY_NOT_MODIFIER
            or _COPY_MODIFIER_PARTICLE.search(modifier)):
        return False
    # 「暑い、暑い。」「疲れた、眠い。」のように形容詞で終わる文は、名詞で止める型ではない（「い」で終わる名詞は残す）
    if noun.endswith("い") and noun not in _COPY_I_NOUNS:
        return False
    return not _COPY_NOUN_NOT.search(noun)


def _bare_verb_chain_sentence(sentence: str) -> bool:
    if len(sentence) > 30 or not sentence.endswith("。"):
        return False
    parts = [part.strip() for part in sentence[:-1].split("、")]
    if len(parts) < 3 or _BARE_VERB_PARTICLE.search(sentence):
        return False
    for part in parts[:-1]:
        if (not _BARE_VERB_PART.fullmatch(part) or _BARE_VERB_POLITE.search(part)
                or _BARE_VERB_NOT_VERB.search(part)):
            return False
    last = parts[-1]
    return (bool(_BARE_VERB_LAST.fullmatch(last)) and not _BARE_VERB_POLITE.search(last)
            and not _BARE_VERB_NOT_VERB.search(last))


def _v220_shape_findings(analysis: dict, findings: list[dict], doc_type: str | None) -> list[dict]:
    """say_hedge、copy_comma_noun、bare_verb_chain の候補。findings は既存の規則の候補（読むだけ。いまは使わない）。

    1行に同じ規則の候補は1件まで。copy_comma_noun は promo では文書の中で2回目に当たったものから出す。
    中身のない「仕組み」（empty_shikumi）は、推敲の前後の比べで直せた文がなく、仕組みを説明している文を書き換えたので
    2.2.0 には入れなかった。"""
    result = []
    source = analysis["text"]
    positions = [match.start() for match in _SHAPE_COMMA_GATE.finditer(source)]
    for word in _SHAPE_GATE_WORDS:
        position = source.find(word)
        while position >= 0:
            positions.append(position)
            position = source.find(word, position + 1)
    if not positions:
        return result
    rows = analysis["lines"]
    starts = [row["start"] for row in rows]
    indexes = sorted({bisect_right(starts, position) - 1 for position in positions})
    copy_hits = 0
    for index in indexes:
        row = rows[index]
        text = _shape_visible_text(analysis, row)
        if not text:
            continue
        line_no = row["line"]
        found = set()
        for match in _SHAPE_SENTENCE.finditer(text):
            sentence = match.group().strip()
            if not sentence:
                continue
            if "say_hedge" not in found and "える" in sentence and _say_hedge_sentence(sentence):
                found.add("say_hedge")
            if "、" in sentence:
                if _copy_comma_noun_sentence(sentence):
                    copy_hits += 1
                    if doc_type != "promo" or copy_hits >= 2:
                        found.add("copy_comma_noun")
                if "bare_verb_chain" not in found and _bare_verb_chain_sentence(sentence):
                    found.add("bare_verb_chain")
        for rule in ("say_hedge", "copy_comma_noun", "bare_verb_chain"):
            if rule in found:
                result.append({"rule": rule, "line": line_no, "severity": "info",
                               "message": _SHAPE_RULE_MESSAGES[rule], "snippet": row["raw"].strip()})
    return result
# dialogue_period（script だけ）: 台詞が DIALOGUE_MIN 個以上あり、最後の字が「。」の台詞の割合が DIALOGUE_RATIO 以上なら
# 文書に1件。narrative_density（essay だけ）: 地の文が NARRATIVE_MIN_CHARS 字以上で、一人称が千字あたり
# FIRST_PERSON_MAX 未満、数字と箇条書きの項目の合計が千字あたり DENSITY_MIN 以上なら文書に1件。
# 値は tests/corpus（human、raw_ai）と自作の類例で測って決めた（2.2.0。根拠の数は CHANGELOG）
DIALOGUE_MIN = 10
DIALOGUE_RATIO = 0.5
FIRST_PERSON_MAX = 1.0
DENSITY_MIN = 8
NARRATIVE_MIN_CHARS = 1000
# 台詞と地の文を探さない行（見出し、コード、表、引用は数えない）
_DOCUMENT_SKIP_KINDS = frozenset(("code", "frontmatter", "html_block", "reference_definition", "heading",
                                  "heading_underline", "thematic_break", "table"))
_QUOTE_PAIRS = {"「": "」", "『": "』"}
_QUOTE_CLOSERS = frozenset(_QUOTE_PAIRS.values())
# 「名前：台詞」の行。名前は空白、句読点、括弧を含まない12字以下（全角と半角のコロン）
_SPEAKER_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)?([^\s：:「」『』（）()、。！？!?，,．.]{1,12})[ \t　]*[：:][ \t　]*(.+)$")
# 音と音楽の指示（SE、M、BGM）は台詞ではない。数字だけの名前（10:00）も外す
# コマ、ページ、場所や時間の柱、ト書きの見出しは話し手ではない（ナレーションは話し手として数える）
_NOT_SPEAKER = re.compile(r"^(?:SE|ＳＥ|M|Ｍ|BGM|ＢＧＭ|[0-9０-９]+|(?:[0-9０-９]+)?(?:コマ|ページ|P|Ｐ)目?[0-9０-９]*|場所|時間|時|"
                          r"人物|登場人物|柱|ト書き?|注|メモ|備考)$", re.I)
# 台詞の前後のト書き（「ハル：屁理屈（笑う）」の（笑う））
_EDGE_STAGE_NOTE = re.compile(r"^[（(][^（）()]*[）)]\s*|\s*[（(][^（）()]*[）)]$")
# 一人称（たち、ら、ども などの複数の形も同じ語として1回に数える）。仮名の語は、前が仮名でなく、動詞の続き
# （手わたします、おれた、など）でないときだけ。「私」は公私、私立、私鉄のような熟語を外す
_FIRST_PERSON = re.compile(
    r"(?<![公無])私(?![立鉄的物有服用語設費学道塾刑権財欲情事信案邸宅募企営益生淑書])"
    r"|(?<![ぁ-ゖ手受引見])(?:わたくし|わたし(?!て|た(?!ち)|ます|まし|ませ)|ぼく(?![じしさめ])|おれ(?!い|る|た(?!ち)|て|ま|ば|ず|ろ|そ))"
    r"|僕|俺|自分|筆者")
# 数字の続き（全角を含む。1,000 や 1.5 は1つ）。英字のすぐあとの数字（版の番号や見出しの記号）は識別子として数えない
_NARRATIVE_NUMBER = re.compile(r"(?<![A-Za-z_0-9０-９.,．，])[0-9０-９]+(?:[.,．，][0-9０-９]+)*(?![_0-9０-９])")
_ASCII_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?:[./][A-Za-z0-9_]+)+|(?<![A-Za-z])[A-Za-z]+_[A-Za-z0-9_]+")


def _top_quote_contents(text: str) -> list[str]:
    """1行の中の、いちばん外の「」と『』の中身。閉じていない括弧は数えない。"""
    contents = []
    stack = []
    for index, char in enumerate(text):
        if char in _QUOTE_PAIRS:
            stack.append((char, index))
        elif char in _QUOTE_CLOSERS and stack and _QUOTE_PAIRS[stack[-1][0]] == char:
            _, start = stack.pop()
            if not stack:
                contents.append(text[start + 1:index])
    return contents


def _dialogue_lines(analysis: dict) -> list[tuple[int, str]]:
    """台詞の (行番号, 中身) の並び。「」と『』の中身、「名前「…」」の行、「名前：…」の行の中身を数える。
    見出し、コード、表、引用（> の行）は数えない。「」が1つもない行だけ「名前：…」の形を見る。"""
    dialogue = []
    for row in analysis["lines"]:
        if row["kind"] in _DOCUMENT_SKIP_KINDS or row["quote_depth"] or row["kind"] == "quote":
            continue
        visible = _prose_visible_text(analysis, row["line"]).replace("__", "").replace("*", "")
        if not visible.strip():
            continue
        quoted = _top_quote_contents(visible) if ("「" in visible or "『" in visible) else []
        if not quoted:
            speaker = _SPEAKER_LINE.match(visible)
            if speaker is None or _NOT_SPEAKER.match(speaker.group(1)):
                continue
            quoted = [_EDGE_STAGE_NOTE.sub("", speaker.group(2).strip())]
        for content in quoted:
            content = content.strip(" \t　")
            if content:
                dialogue.append((row["line"], content))
    return dialogue


def _narrative_counts(analysis: dict) -> tuple[int, int, int, int, int | None]:
    """地の文の (字数, 一人称の数, 数字の数, 箇条書きの項目の数, 最初の行の番号)。
    見出し、コード、表、引用（> の行）、画像だけの行は数えない。字数は空白を除いた見える文字。一人称と数字は、
    カギ括弧の中と英数字の識別子を伏せてから数える。"""
    chars = first_person = numbers = bullets = 0
    first_line = None
    for row in analysis["lines"]:
        if row["kind"] in _DOCUMENT_SKIP_KINDS or row["quote_depth"] or row["kind"] == "quote":
            continue
        visible = _prose_visible_text(analysis, row["line"])
        if not visible.strip():
            continue
        # 画像だけの行（[![…](…)](…) のバッジ）は数えない（_metrics_and_list_gate と同じ判定の門）
        if row["raw"].lstrip().startswith("[![") and _image_only_row(analysis, row, visible):
            continue
        plain = visible.replace("__", "").replace("*", "")
        length = len("".join(plain.split()))
        if not length:
            continue
        if first_line is None:
            first_line = row["line"]
        chars += length
        if row["kind"] == "list" and _LIST_MARKER_LINE.match(row["raw"]):
            bullets += 1
        masked = _mask_quoted_segments_sparse(plain) if ("「" in plain or "『" in plain) else plain
        if "_" in masked or "." in masked or "/" in masked:
            masked = _ASCII_IDENTIFIER.sub(" ", masked)
        first_person += len(_FIRST_PERSON.findall(masked))
        numbers += len(_NARRATIVE_NUMBER.findall(masked))
    return chars, first_person, numbers, bullets, first_line


def _per_thousand(count: int, chars: int) -> float:
    return count * 1000 / chars if chars else 0.0


def _v220_document_findings(analysis: dict) -> list[dict]:
    """dialogue_period と narrative_density の候補（文書に1件ずつ）。

    --doc-type を持たないため、上流で種類を限っていた2規則を常に数える（info のみ）。"""
    findings = []
    dialogue = _dialogue_lines(analysis)
    ended = sum(1 for _, content in dialogue if content.endswith(("。", "｡")))
    if len(dialogue) >= DIALOGUE_MIN and ended >= DIALOGUE_RATIO * len(dialogue):
        line_no = dialogue[0][0]
        findings.append({
            "rule": "dialogue_period",
            "line": line_no,
            "severity": "info",
            "message": "台詞の最後の句点（台詞{}個のうち{}個、{}%が「。」で終わる）の候補です。文脈を見て、誰が何をどうするかを"
                       "書き直すか確かめてください。".format(len(dialogue), ended, round(ended * 100 / len(dialogue))),
            "snippet": analysis["lines"][line_no - 1]["raw"].strip()
        })
    chars, first_person, numbers, bullets, first_line = _narrative_counts(analysis)
    person_rate = _per_thousand(first_person, chars)
    density = _per_thousand(numbers + bullets, chars)
    if chars >= NARRATIVE_MIN_CHARS and person_rate < FIRST_PERSON_MAX and density >= DENSITY_MIN:
        assert first_line is not None
        findings.append({
            "rule": "narrative_density",
            "line": first_line,
            "severity": "info",
            "message": "読み物の一人称と数字（地の文{:,}字、一人称は千字あたり{:.1f}、数字と箇条書きは千字あたり{:.1f}）の候補です。"
                       "文脈を見て、誰が何をどうするかを書き直すか確かめてください。一人称と体験は足さず、数字も消しません。"
                       .format(chars, person_rate, density),
            "snippet": analysis["lines"][first_line - 1]["raw"].strip()
        })
    return findings


# 語の一覧の allow.txt の語で外す規則（規則ID の順。context.words.allow_removed の並び）
_ALLOW_RULES = ("ai_phrase", "calque", "katakana_term", "metaphor_label", "metaphor_verb", "project_term", "renyo_noun",
                "slop_vocabulary", "translated_term")
_LABEL_WORD = re.compile(r"「([^」]+)」")
# 語の一覧の flag.txt の語の message。その行に出た flag の語を「語の一覧（flag.txt）の語（依存先、承認）」のように並べる
_PROJECT_TERM_MESSAGE = "語の一覧（flag.txt）の語（{}）" + _V220_MESSAGE_TAIL
# 3.0.0: flag-patterns.txt のパターンに当たった行の message。パターンだけなら名前を、flag.txt の語と同じ行なら両方を並べる
_PROJECT_TERM_PATTERN_MESSAGE = "語の一覧（flag-patterns.txt）の語（{}）" + _V220_MESSAGE_TAIL
_PROJECT_TERM_BOTH_MESSAGE = "語の一覧（flag.txt、flag-patterns.txt）の語（{}）" + _V220_MESSAGE_TAIL


def _project_term_message(words: Sequence[str], pattern_names: Collection[str], flag_hits: Collection[str] | None = None,
                          replacements: dict[str, str] | None = None) -> str:
    """project_term の message。words は行の語（flag.txt の語とパターンの名前）、pattern_names はそのうちのパターンの名前、
    flag_hits はそのうちの flag.txt の語（None なら、パターンの名前でない語）。パターンの名前と flag.txt の語が同じ字でも、
    両方が当たった行では両方のファイルを並べる。replacements は flag.txt の語の使う語で、括弧の外の末尾に添え、
    check が読む括弧の中は変えない。"""
    from_patterns = any(word in pattern_names for word in words)
    flag_words = [word for word in words if word not in pattern_names] if flag_hits is None else [word for word in words if word in flag_hits]
    from_flag = bool(flag_words)
    if not from_patterns:
        message = _PROJECT_TERM_MESSAGE.format("、".join(words))
    elif not from_flag:
        message = _PROJECT_TERM_PATTERN_MESSAGE.format("、".join(words))
    else:
        message = _PROJECT_TERM_BOTH_MESSAGE.format("、".join(words))
    replacements = replacements or {}
    suggestions = ["{} → {}".format(word, replacements[word]) for word in flag_words if word in replacements]
    return message + ("使う語: " + "、".join(suggestions) + "。" if suggestions else "")
# 英数字で始まるか終わる語は、識別子（snake_case、camelCase、ドットや / を含む語）の一部では数えない
_WORD_ASCII = re.compile(r"[A-Za-z0-9_]")
_WORD_BEFORE = r"(?<![A-Za-z0-9_./\\-])"
_WORD_AFTER = r"(?![A-Za-z0-9_])(?![./\\-][A-Za-z0-9_])"
_WORD_KANJI_BEFORE = r"(?<![一-龥々〆ヵヶ])"
_WORD_KANJI_AFTER = r"(?![一-龥々〆ヵヶ])"


def _hit_words(label: str, match: re.Match[str] | None) -> tuple[str, ...]:
    """候補の内部の欄 _words の値。message に出る規則の表の語（label。「」があればその中身）、そこから「〜」と英語の
    注記を除いた語、当たった文字列（前後の空白を除く）を、重ねずにこの順で並べる。"""
    words = []
    quoted = _LABEL_WORD.search(label)
    shown = quoted.group(1) if quoted else label
    name = re.sub(r"[ 　]*[（(][^）)]*[）)]$", "", shown).strip("〜~ 　")
    for word in (shown, name, match.group(0).strip() if match is not None else ""):
        if word and word not in words:
            words.append(word)
    return tuple(words)


def _flag_pattern(flag: Iterable[str]) -> re.Pattern[str] | None:
    """flag.txt の語を1つの正規表現にする（長い語を先に。英数字の端には識別子の境目を付ける）。語がなければ None。"""
    words = sorted(set(flag), key=lambda word: (-len(word), word))
    if not words:
        return None
    parts = []
    for word in words:
        part = re.escape(word)
        if _WORD_ASCII.match(word[0]):
            part = _WORD_BEFORE + part
        if _WORD_ASCII.match(word[-1]):
            part += _WORD_AFTER
        # 3.0.0: 漢字と仮名を両方含む語（根の、の木）は、漢字の端の前後に漢字が続く所（大根の、の木構造）では数えない。
        # 漢字だけの語（公開鍵）と仮名だけの語は、今のとおり語の一部にも当たる
        if any(_v220_kanji(char) for char in word) and any(_v220_hiragana(char) or _v220_katakana(char) for char in word):
            if _v220_kanji(word[0]):
                part = _WORD_KANJI_BEFORE + part
            if _v220_kanji(word[-1]):
                part += _WORD_KANJI_AFTER
        parts.append(part)
    return re.compile("|".join(parts))


_REPLACEMENT_BEFORE = re.compile(_WORD_BEFORE)
_REPLACEMENT_AFTER = re.compile(_WORD_AFTER)


def _replacement_bounded(text: str, start: int, replacement: str) -> bool:
    """text の start にある使う語が、英数字の端で識別子や別の英単語（backend user の中の end user）の一部になって
    いないか。flag.txt の語の端（_flag_pattern）と同じ境目を、使う語の端にも当てる。日本語の字の端では見分けない。"""
    if _WORD_ASCII.match(replacement[0]) and not _REPLACEMENT_BEFORE.match(text, start):
        return False
    return not _WORD_ASCII.match(replacement[-1]) or bool(_REPLACEMENT_AFTER.match(text, start + len(replacement)))


def _in_replacement(text: str, match: re.Match[str], replacements: dict[str, str]) -> bool:
    """flag.txt の語の当たりが、その語の使う語の中に収まっているか。使う語が語を含む組（サーバ → サーバー、
    問い合わせ → お問い合わせ）で、もう使う語で書いてある所を数えないために使う。英数字で始まるか終わる使う語は、
    その端が語の境目にある所だけを使う語とみなす（_replacement_bounded）。"""
    word = match.group(0)
    replacement = replacements.get(word)
    if not replacement or word not in replacement:
        return False
    offset = replacement.find(word)
    while offset >= 0:
        start = match.start() - offset
        if start >= 0 and text.startswith(replacement, start) and _replacement_bounded(text, start, replacement):
            return True
        offset = replacement.find(word, offset + 1)
    return False


def _project_term_findings(analysis: dict, words: dict | None) -> list[dict]:
    """語の一覧の flag.txt の語の候補（project_term）。見える文字（コード、URL、リンク先、HTML、frontmatter を伏せた行）に
    flag の語が出る行に1件。引用（> の行）とカギ括弧・二重カギ括弧の中は数えない。_words にその行の flag の語。
    3.0.0: flag-patterns.txt のパターンも同じ所に当て、当たったパターンの名前を _words に足す（flag の語のあと）。
    パターンごとの当たった文字列は内部の欄 _pattern_matches に入れる（allow.txt で外すため）。パターンは、一番上の選択肢の
    どれかの必ず当たる字が全部ある行にだけ当てる。当たった flag.txt の語の使う語は内部の欄 _replacements に入れる
    （allow.txt で一部の語を外したときに message を作り直すため）。使う語が語を含む組では、使う語の中に収まる当たりは
    数えない（もう使う語で書いてある所に、同じ指摘を出さない）。"""
    if not words or not (words.get("flag") or words.get("flag_patterns")):
        return []
    pattern = _flag_pattern(words["flag"]) if words.get("flag") else None
    patterns = words.get("flag_patterns") or ()
    flag_replacements = words.get("flag_replacements") or {}
    found = []
    for row in analysis["lines"]:
        if row["kind"] in ("code", "frontmatter", "html_block", "reference_definition", "quote") or row["quote_depth"]:
            continue
        # 「」が行をまたぐときも中身を伏せるため、文書全体で対を取ったマスクを使う（_v220_masked_lines）
        masked = _v220_masked_lines(analysis)[row["line"]]
        if not masked.strip():
            continue
        hits = () if pattern is None else tuple(dict.fromkeys(
            match.group(0) for match in pattern.finditer(masked)
            if not (flag_replacements and _in_replacement(masked, match, flag_replacements))))
        matches = {}
        for name, _, compiled, required in patterns:
            if not any(all(literal in masked for literal in runs) for runs in required):
                continue
            strings = tuple(dict.fromkeys(match.group(0) for match in compiled.finditer(masked)))
            if strings:
                matches[name] = tuple(dict.fromkeys(matches.get(name, ()) + strings))
        if hits or matches:
            shown = tuple(dict.fromkeys(hits + tuple(matches)))
            replacements = {word: flag_replacements[word] for word in hits if word in flag_replacements}
            finding = {"rule": "project_term", "line": row["line"], "severity": "info",
                       "message": _project_term_message(shown, matches, hits, replacements),
                       "snippet": row["raw"].strip(),
                       "_words": shown}
            if replacements:
                finding["_replacements"] = replacements
            if matches:
                finding["_pattern_matches"] = matches
                finding["_flag_hits"] = hits
            found.append(finding)
    return found


_LABEL_WORD = re.compile(r"「([^」]+)」")


def _hit_words(label: str, match: re.Match[str] | None) -> tuple[str, ...]:
    """候補の内部の欄 _words の値。message に出る規則の表の語（label。「」があればその中身）、そこから「〜」と
    英語の注記を除いた語、当たった文字列（前後の空白を除く）を、重ねずにこの順で並べる。"""
    words = []
    quoted = _LABEL_WORD.search(label)
    shown = quoted.group(1) if quoted else label
    name = re.sub(r"[ 　]*[（(][^）)]*[）)]$", "", shown).strip("〜~ 　")
    for word in (shown, name, match.group(0).strip() if match is not None else ""):
        if word and word not in words:
            words.append(word)
    return tuple(words)


def _hit_words_all(label: str, pattern, text: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]] | None:
    """pattern の text での全一致について、(平らに重ねた _words, 一致ごとの _words) を返す。当たらなければ None。

    1行に同じ規則の候補は1件までだが、allow.txt で外すかは一致ごとに決めるため、
    一致ごとの語の並び（_word_groups）も一緒に返す。"""
    groups = tuple(_hit_words(label, match) for match in re.finditer(pattern, text))
    if not groups:
        return None
    flat = tuple(dict.fromkeys(word for group in groups for word in group))
    return flat, groups


def _apply_words(findings: list[dict], words: dict | None) -> tuple[list[dict], dict | None]:
    """語の一覧の allow.txt の語で候補を外す。(残った候補, context に入れる words の値か None) を返す。

    外すのは _ALLOW_RULES の規則の候補で、候補の _words のどれかが allow の語と同じもの。残った候補の順は変えない。
    1行に1件で語を並べる規則（_ALLOW_PARTIAL_RULES）は、許した語だけを除き、許していない語が残れば候補を残して
    message を作り直す（外した件数には数えない）。
    words が None（一覧を使わない）なら、候補をそのまま返し、context の値は None。"""
    if words is None:
        return findings, None
    allow = frozenset(words.get("allow") or ())
    removed = dict((rule, 0) for rule in _ALLOW_RULES)
    kept = findings
    if allow:
        kept = []
        for finding in findings:
            hit = finding.get("_words") or ()
            allowed = allow
            if finding.get("_pattern_matches"):
                # flag-patterns.txt のパターンは、名前が allow にあるか、その行で当たった文字列がどれも allow にあれば外す
                allowed = allow | frozenset(name for name, strings in finding["_pattern_matches"].items()
                                            if all(string in allow for string in strings))
            groups = finding.get("_word_groups")
            if groups is not None and finding["rule"] in removed:
                # 行に同じ規則の一致が複数ある候補は、一致ごとの語のどれかが許可されていればその一致は許可とし、
                # 全ての一致が許可されたときだけ候補を外す（未許可の一致が残れば候補を残す）
                if all(any(word in allowed for word in group) for group in groups):
                    removed[finding["rule"]] += 1
                else:
                    kept.append(finding)
                continue
            if finding["rule"] in removed and any(word in allowed for word in hit):
                rest = tuple(word for word in hit if word not in allowed)
                if finding["rule"] in _ALLOW_PARTIAL_RULES and rest:
                    kept.append(_finding_with_words(finding, rest))
                else:
                    removed[finding["rule"]] += 1
            else:
                kept.append(finding)
    context = words_context(words)
    context["allow_removed"] = removed
    return kept, context


# 1行に1件で、行の語を _words に並べる規則。allow.txt の語は語ごとに外す
_ALLOW_PARTIAL_RULES = ("ai_phrase", "calque", "katakana_term", "project_term", "renyo_noun")


def _finding_with_words(finding: dict, rest: tuple[str, ...]) -> dict:
    """許していない語（rest）だけを残した候補の写し。calque、project_term、renyo_noun、ai_phrase は message も作り直す。"""
    out = dict(finding, _words=rest)
    if finding["rule"] == "calque":
        word_types = tuple((word, number) for word, number in finding.get("_word_types") or () if word in rest)
        out["_word_types"] = word_types
        out["message"] = _calque_message(list(dict.fromkeys(number for _, number in word_types)), word_types)
    elif finding["rule"] == "project_term":
        out["message"] = _project_term_message(rest, finding.get("_pattern_matches") or {}, finding.get("_flag_hits"),
                                               finding.get("_replacements"))
    elif finding["rule"] == "renyo_noun":
        out["message"] = _RENYO_MESSAGE.format("、".join("の" + word for word in rest))
    elif finding["rule"] == "ai_phrase":
        out["message"] = _AI_PHRASE_MESSAGE.format("、".join(rest))
    return out


def _public_finding(finding: dict) -> dict:
    """候補の内部の欄（_ で始まるキー。_words など）を除いた写し。"""
    return {key: value for key, value in finding.items() if not key.startswith("_")}



def lint_text(text: str, *, words: dict | None = None) -> Dict[str, Any]:
    """文章全体を総合検査する"""
    findings = []
    analysis = analyze_markdown(text)
    rule9_context = _rule9_context(analysis)
    extra_negation_lines = _extra_negation_line_numbers(analysis)
    metrics, prose_chars = _metrics_from_analysis(analysis)
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
    negation_lines = []
    pause_lines = None
    # 文書にダッシュが一つもなければ行ごとのダッシュ検査を丸ごと省く
    dash_possible = (_dash_finding is not _DASH_FINDING_DEFAULT or _DASH_RUN is not _DASH_RUN_DEFAULT
                     or any(char in text for char in DASH_CHARS))

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
        plain_text = re.sub(r"\*\*|\*|__", "", mention_free)
        previous_sentence = plain_text

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

        # ダッシュ記号の検査(3ルール。区間・出典・引用・図罫線はマスクする。
        # 表示の1文書3件への制限は検査のあとで当て、点数には全部を数える)
        if dash_possible:
            dash = _dash_finding(plain_text, line_no, stripped)
            if dash:
                findings.append(dash)

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
            continue

        if _BOLD_LABEL_ITEM.match(line):
            bold_label_lines.append(line_no)
        line_sentences = [clean for part in _LINE_SENTENCE_BREAK.split(plain_text) if (clean := part.strip())]

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
        # 語の一覧の allow.txt で外すため、候補の内部の欄 _words に当たった語（型の語は、型の名前と当たった文字列）を入れる。
        # 型の語は1行に複数当たりうるので、全一致を一致ごとの並び（_word_groups）にも入れ、全て許可されたときだけ外せるようにする
        slop_hits: list[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...] | None]]
        if narrowed is None:
            slop_hits = [(word, (word,), None) for word in SLOP_WORDS if word in plain_text]
            for word, pattern in SLOP_WORD_PATTERNS:
                hit_groups = _hit_words_all(word, pattern, plain_text)
                if hit_groups:
                    slop_hits.append((word, hit_groups[0], hit_groups[1]))
        else:
            slop_hits = [(word, (word,), None) for word in slop_words if word in plain_text]
            for word, pattern, required in slop_patterns:
                if not _may_match_literals(required, plain_text):
                    continue
                hit_groups = _hit_words_all(word, pattern, plain_text)
                if hit_groups:
                    slop_hits.append((word, hit_groups[0], hit_groups[1]))
        for word, hit, groups in slop_hits:
            findings.append({
                "rule": "slop_vocabulary",
                "line": line_no,
                "severity": "warn",
                "message": f"AI 頻出語彙「{word}」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、具体的な客観表現に置き換えてください。",
                "snippet": line.strip(),
                "_words": hit,
                "_word_groups": groups,
            })

        # 比喩動詞パターン
        # 「壊れる」が1行に複数当たるときは全ての範囲を持ち、英語直訳の一致がいずれかに含まれるとき除外する
        kowareru_spans: tuple[tuple[int, int], ...] = ()
        for pattern, desc, required in metaphor_patterns:
            if not _may_match_literals(required, plain_text):
                continue
            if desc == "英語直訳「静かに壊れる (silently fail)」" and kowareru_spans:
                # 「Xが壊れる」と「静かに壊れる」が同一動詞に二重反応することを防止。
                # 1行に複数当たりうるので全一致を一致ごとの並び（_word_groups）に入れ、全て許可されたときだけ外せるようにする
                groups = []
                for m in pattern.finditer(plain_text):
                    span = (m.start(), m.end())
                    if any(start <= span[0] and span[1] <= end for start, end in kowareru_spans):
                        continue
                    groups.append(_hit_words(desc, m))
                if groups:
                    hit = tuple(dict.fromkeys(word for group in groups for word in group))
                    findings.append({
                        "rule": "metaphor_verb",
                        "line": line_no,
                        "severity": "warn",
                        "message": f"{desc}が検出されました。具体的な操作や状態変化に書き直してください。",
                        "snippet": line.strip(),
                        "_words": hit,
                        "_word_groups": tuple(groups)
                    })
                continue

            matches = list(pattern.finditer(plain_text))
            if matches:
                if desc == "比喩動詞「壊れる」":
                    kowareru_spans = tuple((match.start(), match.end()) for match in matches)
                groups = tuple(_hit_words(desc, m) for m in matches)
                hit = tuple(dict.fromkeys(word for group in groups for word in group))
                findings.append({
                    "rule": "metaphor_verb",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。具体的な操作や状態変化に書き直してください。",
                    "snippet": line.strip(),
                    "_words": hit,
                    "_word_groups": groups
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

        # AIへの指示残り(書き方や除外の予告)。読者のための範囲・対象読者・前提・参照先は残す
        if any(_has_instruction_residue(sentence, following)
               or _has_instruction_residue_core(sentence, following, _end_closers_for(analysis, line_no))
               for sentence, following in rule9_context.get(line_no, ())):
            findings.append({
                "rule": "instruction_residue",
                "line": line_no,
                "severity": "info",
                "message": "AIへの指示が本文に残る形(書き方や除外の予告)が検出されました。除外や書き方の指示を述べる文を削ってください。ただし、読者のための範囲・対象読者・前提・参照先・用語の定義を示す文は残してください。",
                "snippet": stripped
            })

        # 「〜のは、A、B、C。」で名詞を並べて述語を書かずに終える文(前提がなければ)
        if "のは、" in plain_text and _has_cleft_list_ending(
                analysis, line_no, rule9_context.get(line_no, ()), line_sentences, filler_patterns):
            findings.append({
                "rule": "cleft_list_ending",
                "line": line_no,
                "severity": "info",
                "message": "「〜のは、」のあとに名詞を並べ、述語を書かずに終える文(「〜で変わったのは、A、B、C。」)が検出されました。何かが変わった、何かを目指したといった前提を前の文や見出しで書いていなければ、「のは」の前の動詞を述語に戻し、「〜では、A、B、Cが変わった。」のように述語まで書いてください。前提が直前に書いてある場合や、見出し、結び、スライドの箇条で書き手が強調として選んだ形なら残してかまいません。",
                "snippet": stripped
            })

        # 短い主語・主題・目的語のすぐあとの読点(間を作るだけの読点)
        if pause_lines is None:
            pause_lines = _pause_comma_line_hits(analysis, objects=True)
        if line_no in pause_lines:
            pause_hits = pause_lines[line_no]
        else:
            pause_hits = _pause_comma_hits(plain_text)
            pause_hits = sorted(pause_hits + _pause_comma_object_hits(plain_text))
        if pause_hits:
            phrases = "".join("「{}{}、」".format(phrase, chunk) for _, chunk, phrase in pause_hits[:3])
            if len(pause_hits) > 3:
                phrases += "ほか{}か所".format(len(pause_hits) - 3)
            objects = tuple(phrase + "を" for _, chunk, phrase in pause_hits if chunk == "を")
            heads = len(objects) < len(pause_hits)
            where = "短い主語や主題、目的語" if objects else "短い主語や主題"
            findings.append({
                "rule": "pause_comma",
                "line": line_no,
                "severity": "info",
                "message": f"{where}のすぐあとに読点があります({phrases})。間を作るだけの読点は、AIの文章らしく見えます。読点のあとに別の主語が来る、条件や場面の枠を示す、並べている、外すと語がつながったり掛かり先が変わったりする、のどれにも当たらなければ、読点だけを外してください(語順と述語は変えません)。小説や随筆で書き手が間として置いた読点は残してかまいません。",
                "snippet": line.strip(),
                "_objects": objects,
                "_heads": heads
            })

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

        # ネガティブパラレリズム。「A ではなく B でもある」は反語的用法のため
        # 「ではなく」構文だけを免除し、同行の「でもない」「じゃない」検査は続ける
        negation_message = None
        if (_has_negative_parallelism(plain_text) and "ではなく" in plain_text
                and plain_text.count("ではなく") != len(_NEGATION_ALSO.findall(plain_text))):
            negation_message = "「A ではなく B」構文が検出されました。誤解を解くために残す場合は否定の根拠を一文添え、それ以外は肯定文で直接書けないか検討してください。"
        if (negation_message is None
                and (line_no in extra_negation_lines
                     or ("でもない。" in plain_text and _NEGATION_EXTRA.search(plain_text))
                     or ("じゃない、" in plain_text
                         and any(_NEGATION_JANAI.match(sentence) for sentence in line_sentences)))):
            negation_message = "否定を重ねてから言い切る構文(「AでもBでもない。Cだ。」「Aじゃない、Bです。」)が検出されました。否定している内容を誰も主張していないなら、言い切る文だけにしてください。読み手の思い込みを正す否定なら、一つの文にまとめて残してください。直前で挙げた二つ(問いなど)を両方とも打ち消すだけなら、「どちらでもない。」(敬体なら「どちらでもありません。」)と短く受けてもかまいません。打ち消すほかに、問いにない強めの語や限定、なぜ違うかの説明を含む否定は短くしないでください。"
        if negation_message:
            negation_lines.append(line_no)
            findings.append({
                "rule": "negative_parallelism",
                "line": line_no,
                "severity": "info",
                "message": negation_message,
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
    if len(negation_lines) >= 3:
        findings.append({
            "rule": "negative_parallelism_density",
            "line": negation_lines[2],
            "severity": "info",
            "message": f"否定の対比(「A ではなく B」など)が文書内に{len(negation_lines)}か所あります。1か所ずつの役割を確かめ、言い切れば足りる箇所だけを肯定文にしてください。",
            "snippet": f"行: {', '.join(str(n) for n in negation_lines[:5])}"
        })
    if len(bold_label_lines) >= 3:
        findings.append({
            "rule": "bold_label_list",
            "line": bold_label_lines[0],
            "severity": "info",
            "message": f"太字の見出し語とコロンで始まる箇条書きが{len(bold_label_lines)}行あります。値が日時や場所、担当、数値などの短い事実なら残してください。見出し語が抽象的で、値が一文の説明なら、地の文にするか、太字とコロンを外してください。並列関係が明確で読みやすい箇条書きは箇条書きのまま残し、項目の区別と数・順序は変えないでください。",
            "snippet": f"行: {', '.join(str(n) for n in bold_label_lines[:5])}"
        })

    # Phase 2: 上流 v3.0.0 の info 系規則(語彙・文の形・文書単位)
    findings.extend(_v220_word_findings(analysis, findings))
    findings.extend(_v230_renyo_findings(analysis))
    findings.extend(_v250_ai_phrase_findings(analysis, None))
    findings.extend(_v220_shape_findings(analysis, findings, None))
    findings.extend(_v220_document_findings(analysis))
    findings.extend(_project_term_findings(analysis, words))
    findings, words_context = _apply_words(findings, words)
    # ダッシュの候補は、語の一覧で外したあとに残ったものの初めから DASH_FINDING_LIMIT 件だけを出し、
    # 点数には全部を数える
    dash_hits = 0
    shown = []
    for finding in findings:
        if finding["rule"] in _DASH_RULES:
            dash_hits += 1
            if dash_hits > DASH_FINDING_LIMIT:
                continue
        shown.append(finding)
    findings = shown

    # 候補の重みを地の文1,000字あたりに直した x から、100 × 40 ÷ (40 + x) を丸める目安。品質の点数ではない。
    # info の見直し規則(上流 2.2.0 以降の規則)の候補は点数を計算する前に除く
    rule_penalty_score = _rule_penalty_score(
        [finding for finding in findings if finding["rule"] not in _SCORE_EXCLUDED_RULES],
        prose_chars, dash_hits)
    counts = {"error": 0, "warn": 0, "info": 0}
    for finding in findings:
        if finding["severity"] in counts:
            counts[finding["severity"]] += 1
    context = {}
    if words_context is not None:
        context["words"] = words_context

    return {
        "format": "yomiyasu-lint",
        "format_version": LINT_FORMAT_VERSION,
        "tool_version": __version__,
        "candidate_count": len(findings),
        "counts": counts,
        "no_rule_findings": len(findings) == 0,
        "rule_penalty_score": rule_penalty_score,
        "not_judged": ["meaning_preservation", "reader_comprehension"],
        "context": context,
        "metrics": metrics,
        "findings": [_public_finding(f) for f in findings]
    }


# ---- 人が読む出力 ----

_REPORT_HEADER = (
    "表現・書式の検査を実行しました。",
    "見直し候補: {count}件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
)


def render_findings(result: Dict[str, Any]) -> str:
    """内訳の行と候補の並びだけを返す（候補が0件なら空の文字列）。末尾に改行は付けない。

    候補は行番号の順に並べる（同じ行の中は findings の順のまま）。findings の順そのものは変えない。
    """
    findings = result["findings"]
    if not findings:
        return ""
    counts = result["counts"]
    blocks = ["内訳: error {}件、warn {}件、info {}件".format(counts["error"], counts["warn"], counts["info"])]
    for finding in sorted(findings, key=lambda item: item["line"]):
        lines = ["L{} [{}] {}: {}".format(finding["line"], finding["severity"].upper(), finding["rule"], finding["message"])]
        for snippet_line in str(finding["snippet"]).split("\n"):
            snippet_line = snippet_line.rstrip()
            if snippet_line:
                lines.append("  > " + snippet_line)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _words_line(result: dict) -> Optional[str]:
    """語の一覧を使ったときの行。使わないときは None。"""
    words = (result.get("context") or {}).get("words")
    if not isinstance(words, dict):
        return None
    return words_label(words) + "allow で外した候補 {}件。".format(sum((words.get("allow_removed") or {}).values()))


def render_report(result: Dict[str, Any]) -> str:
    """通常の出力の全体（1〜3行目、語の一覧を使ったときの行、候補があれば内訳と候補の並び）を返す。
    末尾に改行は付けない。"""
    header = "\n".join(_REPORT_HEADER).format(count=result["candidate_count"])
    words_line = _words_line(result)
    if words_line is not None:
        header += "\n" + words_line
    body = render_findings(result)
    return header + "\n\n" + body if body else header


# ---- CLI ----

# --strict と --fail-on の条件。値は (終了コード1の行に書く文, 当たったかを決める重さ)。
_FAIL_CONDITIONS = {
    "strict": ("--strict の条件（warn か error の候補が1件以上）", ("warn", "error")),
    "warn": ("--fail-on=warn の条件（warn か error の候補が1件以上）", ("warn", "error")),
    "error": ("--fail-on=error の条件（error の候補が1件以上）", ("error",)),
}
_MEANING_RISK_MESSAGE = (
    "--fail-on=meaning-risk は lint では使えません。lint は1つの文章だけを見るので、意味の変化は判定できません。"
    "意味リスクの判定は別計画で、現在はどのコマンドでも使えません。"
)
_PENALTY_HELP = """rule_penalty_score（--json の目安）:
  候補が0件なら100。候補があれば 100 × 40 ÷ (40 + x) を四捨五入し、1〜99に収めます。
  x は、行ごとの候補の重み（error 3、warn 2、info 1）を地の文1,000字あたりに直した数です。
  地の文はコード、表、引用、見出し、前置きの設定（frontmatter）、HTML、URL と空白を除いた字数で、
  1,000字に満たなければ1,000字として割ります。
  excess_bold と excess_list は1件で2、bold_label_list は1を x に足し、
  negative_parallelism_density は数えません。ダッシュの規則に当たった行は、候補に出さない4行目からも数えます。
  上流 2.2.0 以降で足した次の規則の候補も数えず、その候補だけのときは100です: calque、metaphor_label、
  say_hedge、thin_evaluation、katakana_term、dialogue_period、narrative_density、copy_comma_noun、
  bare_verb_chain、project_term、renyo_noun、ai_phrase。
  CI では --strict か --fail-on、または counts を使ってください。
"""
_EXIT_CODES = """終了コード:
  0  検査を最後まで実行し、--strict と --fail-on の条件に当たらなかった（候補の有無によらない）。-h も0
  1  --strict か --fail-on の条件に当たった
  2  使い方か入力の誤り（ファイルを開けない、作業フォルダの外や名前が点で始まる部分を含むパスを渡した、
     UTF-8 として読めない、標準入力を読めない、使えない --fail-on の値、語の一覧を読めない）
  3  予期しない内部の誤り（標準エラーにトレースバックを出す）か、出力先が閉じられて結果を最後まで書けなかった"""


class _ConditionAction(argparse.Action):
    """--strict と --fail-on を、指定した順に1つの並びに集める。"""

    def __call__(self, parser, namespace, values, option_string=None):
        conditions = list(getattr(namespace, "conditions", None) or [])
        conditions.append(("strict", option_string) if self.nargs == 0 else ("fail-on", values))
        setattr(namespace, "conditions", conditions)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slop_lint.py",
        description="日本語文章の AI っぽさ機械検査リンター",
        epilog=_PENALTY_HELP + "\n" + _EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", nargs="?",
                        help="検査対象の Markdown ファイルパス(指定なしまたは - の場合は標準入力)")
    parser.add_argument("--json", action="store_true",
                        help="結果を JSON(形式2)で出力します。日本語は \\uXXXX の形で出します。"
                             "rule_penalty_score は、候補の多さを地の文の長さで割った目安です(下の式)。合否には使わないでください。")
    parser.add_argument("--strict", action=_ConditionAction, nargs=0, dest="conditions",
                        help="warn か error の候補が1件でもあれば、終了コード1で終わります。"
                             "info の候補と点数は使いません(--fail-on=warn と同じです)。")
    parser.add_argument("--fail-on", action=_ConditionAction, dest="conditions", metavar="{warn,error}",
                        help="指定した中身の候補があれば、終了コード1で終わります。"
                             "warn: warn か error の候補。error: error の候補(太字が表示されない書き方)。"
                             "何度でも、カンマ区切りでも指定できます。点数は条件に使えません。"
                             "meaning-risk は意味リスクの判定が別計画のため lint では使えません。")
    parser.set_defaults(conditions=[])
    return parser


def _use_utf8(stream: object, **options: str) -> None:
    # 改行は OS によらず "\n" で書く(Windows の既定では "\r\n" になる)
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", newline="\n", **options)


def _error(message: str) -> None:
    """標準エラーに1行書く。標準エラーがないとき(pythonw など)は何もしない。"""
    stream = sys.stderr
    if stream is None:
        return
    try:
        _use_utf8(stream, errors="backslashreplace")
        print(message, file=stream)
    except (OSError, ValueError):
        # 標準エラーも閉じられているときは、書かずに終える。
        pass


def _conditions(raw: list) -> tuple:
    """--strict と --fail-on の並びを、条件の名前の並びにする。使えない値があれば誤りの文を返す。

    meaning-risk は、ほかの値と混ぜても、ほかの誤りより先に断る。
    """
    names = []
    unknown = []
    for kind, value in raw:
        if kind == "strict":
            names.append("strict")
            continue
        # 大文字と小文字、「_」と「-」は区別しない(WARN、meaning_risk も受ける)。
        pieces = [piece.strip().lower().replace("_", "-") for piece in value.split(",") if piece.strip()]
        if not pieces:
            # 空、空白だけ、カンマだけの値は、目に見えないので「(空)」と書く。
            unknown.append("（空）")
        for piece in pieces:
            if piece in ("warn", "error"):
                names.append(piece)
            elif piece == "meaning-risk":
                return None, _MEANING_RISK_MESSAGE
            else:
                unknown.append(piece)
    if unknown:
        return None, "--fail-on に使えない値です: {}。lint で使えるのは warn と error です。".format(unknown[0])
    return names, None


def _path_problem(path):
    """コマンドラインで渡されたファイルを読まないときの誤りの文か None"""
    reason = input_path_problem(path) if path is not None else None
    if reason is None:
        return None
    return "Error opening file {}: {}。このファイルを検査するときは、標準入力から渡してください（ファイルの名前の代わりに - を渡すか、省きます）".format(path, reason)


def _read_input(path):
    """ファイルか標準入力を読み、(文字列, None) か (None, 誤りの文) を返す"""
    if path is not None and path != "-":
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except (OSError, ValueError) as error:
            reason = getattr(error, "strerror", None) or error
            return None, "Error opening file {}: ファイルを開けません（{}）".format(path, reason)
        try:
            return decode_source(data)[0], None
        except UnicodeDecodeError:
            return None, "Error opening file {}: UTF-8 として読めません".format(path)
    stream = sys.stdin
    if stream is None:
        return None, "Error reading stdin: 標準入力を読めません（標準入力がありません）"
    try:
        buffer = getattr(stream, "buffer", None)
        data = buffer.read() if buffer is not None else stream.read()
    except UnicodeDecodeError:
        return None, "Error reading stdin: UTF-8 として読めません"
    except (OSError, ValueError) as error:
        reason = getattr(error, "strerror", None) or error
        return None, "Error reading stdin: 標準入力を読めません（{}）".format(reason)
    try:
        return decode_source(data)[0], None
    except UnicodeDecodeError:
        return None, "Error reading stdin: UTF-8 として読めません"


def _run(argv) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    conditions, problem = _conditions(args.conditions)
    if problem:
        _error(problem)
        return 2
    try:
        # .yomiyasu-words/(allow.txt、flag.txt、flag-patterns.txt)を作業ディレクトリから探す
        words = resolve_words(current_directory(), None, False)
    except WordsError as error:
        _error(str(error))
        return 2
    problem = _path_problem(args.file)
    if problem:
        _error(problem)
        return 2
    content, problem = _read_input(args.file)
    if problem:
        _error(problem)
        return 2

    result = lint_text(content, words=words)

    hit = []
    for name in conditions:
        text, severities = _FAIL_CONDITIONS[name]
        if text not in hit and any(result["counts"][severity] for severity in severities):
            hit.append(text)

    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        print(render_report(result))
        if hit:
            print()
            print("終了コード1: {}に当たりました（error {}件、warn {}件）。".format(
                "、".join(hit), result["counts"]["error"], result["counts"]["warn"]))
    # 書き出しの失敗(読む側が先に閉じたなど)を、ここで BrokenPipeError として受けられるようにする。
    if sys.stdout is not None:
        sys.stdout.flush()
    return 1 if hit else 0


def _closed_output_on_windows(error: Exception) -> bool:
    """Windows で、読む側が閉じたパイプに書いたときの例外か。Windows では BrokenPipeError ではなく、errno が EINVAL の
    OSError になる。ファイル名のある OSError(Windows で名前に使えない字を含むパスなど)と、POSIX では、ほかの誤りとして扱う。"""
    return (os.name == "nt" and type(error) is OSError and error.errno == errno.EINVAL
            and error.filename is None and error.filename2 is None)


def _silence_stdout() -> None:
    """標準出力を os.devnull に向け直す。インタプリタの終わりでもう一度書き出しに失敗しないようにする。"""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        pass


def main(argv=None) -> int:
    """CLI。終了コードを返す(0: 条件に当たらない、1: 条件に当たった、2: 使い方か入力の誤り、3: 内部の誤り)。"""
    try:
        _use_utf8(sys.stdout)
        return _run(argv)
    except BrokenPipeError:
        # 出力先(パイプの読む側)が先に閉じた。lint の不具合ではないので、トレースバックは出さない。
        # 結果を最後まで書けなかったので、終了コードは3にする。
        _silence_stdout()
        _error("slop_lint.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
        return 3
    except Exception as error:
        if _closed_output_on_windows(error):
            # Windows で出力先が閉じられた。上の BrokenPipeError と同じく扱う
            _silence_stdout()
            _error("slop_lint.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
            return 3
        _error("slop_lint.py: 内部エラー: {}: {}".format(type(error).__name__, error))
        _error(traceback.format_exc().rstrip("\n"))
        return 3


if __name__ == "__main__":
    sys.exit(main())
