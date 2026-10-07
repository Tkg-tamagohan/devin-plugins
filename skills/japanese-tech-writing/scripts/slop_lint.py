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

検出結果は機械的な見直し候補であり、SKILL.md の規範で正当な
記述と判断できるものはそのまま保持する。
標準ライブラリのみで動作する。
"""

import sys
import re
import argparse
import json
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
    "営み", "装置", "意思決定OS", "土台", "羅針盤", "起爆剤", "触媒",
    # 必殺技造語(体験の壮大化)
    "真理", "虚飾", "境地", "美学", "深淵", "冷徹", "禁欲的", "優美", "極致", "宿命",
    # 文脈によるが要点検の語
    "正本",
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
FILLER_PATTERNS = [
    (r"^(まず|ここで)?重要なのは、?", "前置フィラー「重要なのは」"),
    (r"^結論から言うと、?", "前置フィラー「結論から言うと」"),
    (r"^正直に言うと、?", "前置フィラー「正直に言うと」"),
    (r"^避けたいのは、?", "前置フィラー「避けたいのは」"),
    (r"いかがでした(でしょうか|か)?[？?。]?$", "定型クロージング「いかがでしたでしょうか」"),
    (r"ぜひ(参考|試し|活用)(に)?して(みて)?ください[！!。]?", "定型クロージング「ぜひ〜してみてください」"),
    (r"に他なり(ません|ない)", "過剰な自己ラベリング「〜に他ならない」"),
]

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
    sentence_records = _plain_sentence_records(analysis)
    sentences = [(line, visible) for line, visible, _, _ in sentence_records]
    source_sentences = [(line, source) for line, _, source, _ in sentence_records]
    paragraph_groups = [block_id for _, _, _, block_id in sentence_records]
    metaphor_patterns = [(re.compile(pattern), desc) for pattern, desc in METAPHOR_VERB_PATTERNS]
    filler_patterns = [(re.compile(pattern), desc) for pattern, desc in FILLER_PATTERNS]

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
            continue
        stripped = line.strip()
        scan_text = _prose_visible_text(analysis, line_no).strip()

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
            continue
        if not scan_text:
            continue

        # 「」で囲まれた言及は禁止表現の例示であることが多い。use と mention を
        # 区別するため、語彙・構文検査は言及を除いたテキストで行う。
        # 中黒は各検査パターンを跨げない区切りになる。「X」ではなく「Y」では
        # ではなく が残るので、実際の対比は引き続き検査できる
        mention_free = re.sub(r"「[^」]*」", "・", scan_text)

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
            continue

        # 見出し行は補足カッコとダッシュのみ検査し、本文の語彙・構文検査はスキップ
        if kind == "heading":
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
        for word in SLOP_WORDS:
            if word in plain_text:
                findings.append({
                    "rule": "slop_vocabulary",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"AI 頻出語彙「{word}」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、具体的な客観表現に置き換えてください。",
                    "snippet": line.strip()
                })

        # 比喩動詞パターン
        kowareru_span = None
        for pattern, desc in metaphor_patterns:
            # 「収斂」の先行確認。文境界またぎ防止ガード [^。！？!?]*? は
            # マッチしない行で全位置からの再試行を伴うため、対象語がなければ省く
            if pattern.pattern == r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂" and "収斂" not in plain_text:
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

        # フィラーパターン
        for pattern, desc in filler_patterns:
            if pattern.search(plain_text):
                findings.append({
                    "rule": "meta_filler",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。前置きや定型文を削り、本題から直接書いてください。",
                    "snippet": line.strip()
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
        content = sys.stdin.read()

    result = lint_text(content)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
