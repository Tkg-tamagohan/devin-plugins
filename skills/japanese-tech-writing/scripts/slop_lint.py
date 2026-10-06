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

検出結果は機械的な見直し候補であり、SKILL.md の規範で正当な
記述と判断できるものはそのまま保持する。
標準ライブラリのみで動作する。
"""

import sys
import re
import argparse
import json
from typing import List, Dict, Any, Tuple, Optional

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
    (r"(地味に|よく|じわじわ)効[きくいた]", "比喩動詞「効く」の過剰使用"),
    (r"静かに(壊れ|落ち|失敗|沈黙)", "英語直訳「静かに壊れる (silently fail)」"),
    (r"黙って(無視|捨て|スキップ|破棄)", "英語直訳「黙って無視される」"),
    (r"側に倒[すしせ]", "判断を方向で表現する「〜側に倒す」"),
    (r"時間[をに]溶か[したす]", "比喩動詞「時間を溶かす」"),
    (r"(1つずつ|一つずつ)潰[していくす]", "比喩動詞「潰す」"),
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


CODE_FENCE_PATTERN = re.compile(r"^(`{3,}|~{3,})")
# 終了フェンスは info 文字列を持てない(記号と末尾の空白のみ)
CLOSING_FENCE_PATTERN = re.compile(r"^(`{3,}|~{3,})\s*$")


def update_code_fence(stripped: str, open_fence: Optional[str]) -> Optional[str]:
    """コードフェンスの状態を更新して返す

    Markdown では開いたフェンスと同じ種類の記号で、同じ長さ以上かつ
    info 文字列のない行のみがブロックを閉じる。別種のフェンス行や
    言語指定つきの行はブロック内の本文として扱う。
    open_fence は開いているフェンス記号(例: '```')、開いていなければ None。
    """
    if open_fence is None:
        m = CODE_FENCE_PATTERN.match(stripped)
        return m.group(1) if m else None
    m = CLOSING_FENCE_PATTERN.match(stripped)
    if m and m.group(1)[0] == open_fence[0] and len(m.group(1)) >= len(open_fence):
        return None
    return open_fence


def get_frontmatter_line_count(lines: List[str]) -> int:
    """YAML フロントマター(先頭の --- から次の --- まで)の行数を返す"""
    if not lines or lines[0].strip() != "---":
        return 0
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return idx + 1
    return 0


def extract_plain_sentences(text: str) -> List[Tuple[int, Optional[str]]]:
    """コードブロックや引用、箇条書きを除去し、地の文の段落文(行番号つき)を抽出する

    見出し行は (行番号, None) の境界マーカーとして残し、文末連続の
    判定が節をまたがないようにする。
    """
    lines = text.split("\n")
    sentences = []
    open_fence = None
    fm_lines = get_frontmatter_line_count(lines)

    for idx, line in enumerate(lines, 1):
        if idx <= fm_lines:
            continue
        stripped = line.strip()
        prev_fence = open_fence
        open_fence = update_code_fence(stripped, open_fence)
        if prev_fence is not None or open_fence is not None:
            continue
        # 見出しは節の境界として記録する
        if stripped.startswith("#"):
            sentences.append((idx, None))
            continue
        # 空行、表行、画像記法、HTML タグ、引用行、箇条書き行、インデントされたリスト継続行は地の文から除外
        if (
            not stripped
            or stripped.startswith("|")
            or stripped.startswith("![")
            or stripped.startswith("[![")
            or stripped.startswith("<")
            or stripped.startswith(">")
            or re.match(r"^[-*+]\s|^\d+\.\s", stripped)
            or line.startswith("  ")
            or line.startswith("\t")
        ):
            continue

        # 文の区切り(。！？または行末)
        raw_sents = re.split(r"(?<=[。！？])", stripped)
        for s in raw_sents:
            s_clean = s.strip()
            if s_clean and len(s_clean) > 3:
                sentences.append((idx, s_clean))

    return sentences


def check_sentence_end_repetitions(sentences: List[Tuple[int, Optional[str]]]) -> List[Dict[str, Any]]:
    """3 文以上連続する同一語尾の検知。見出しの境界マーカーで連続数を切り離す"""
    findings = []
    end_types = []

    for line_no, s in sentences:
        if s is None:
            end_types.append((line_no, s, "boundary"))
            continue
        clean = re.sub(r"[。！？\s]+$", "", s)
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

        if curr_type not in ("その他", "boundary") and curr_type == prev_type:
            count += 1
            if count == 3:
                findings.append({
                    "rule": "sentence_end_repetition",
                    "line": curr_line,
                    "severity": "warn",
                    "message": f"同一文末「{curr_type}」が3回以上連続しています。文末のリズムを調整してください。",
                    "snippet": curr_s
                })
        else:
            count = 1

    return findings


def analyze_markdown_metrics(text: str) -> Dict[str, Any]:
    """太字頻度、箇条書き比率などの構造メトリクスを算出(引用文やコードブロックは除外)"""
    lines = text.split("\n")
    plain_lines = []
    open_fence = None
    fm_lines = get_frontmatter_line_count(lines)
    for idx, l in enumerate(lines, 1):
        if idx <= fm_lines:
            continue
        stripped = l.strip()
        prev_fence = open_fence
        open_fence = update_code_fence(stripped, open_fence)
        if prev_fence is not None or open_fence is not None:
            continue
        if stripped.startswith(">") or stripped.startswith("|") or stripped.startswith("![") or stripped.startswith("[![") or stripped.startswith("<"):
            continue
        plain_lines.append(l)

    total_lines = len([l for l in plain_lines if l.strip()])
    list_lines = 0
    for l in plain_lines:
        if re.match(r"^\s*([-*+]|\d+\.)\s+", l):
            # 外部参照リンク(- [タイトル](http...))は並列データのため思考リストから除外
            if not re.search(r"[-*+]\s+\[.*?\]\(https?://", l):
                list_lines += 1

    plain_content = "\n".join(plain_lines)
    bold_matches = re.findall(r"\*\*[^*]+\*\*", plain_content)
    bold_count = len(bold_matches)
    char_count = len(re.sub(r"\s+", "", plain_content))

    bold_per_1000 = (bold_count / char_count * 1000) if char_count > 0 else 0
    list_ratio = (list_lines / total_lines) if total_lines > 0 else 0

    return {
        "char_count": char_count,
        "total_lines": total_lines,
        "list_lines": list_lines,
        "list_ratio": round(list_ratio, 3),
        "bold_count": bold_count,
        "bold_per_1000": round(bold_per_1000, 2),
    }


def lint_text(text: str) -> Dict[str, Any]:
    """文章全体を総合検査する"""
    findings = []
    metrics = analyze_markdown_metrics(text)
    sentences = extract_plain_sentences(text)

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
    findings.extend(check_sentence_end_repetitions(sentences))

    # 3. 語彙・構文パターン検査
    lines = text.split("\n")
    open_fence = None
    fm_lines = get_frontmatter_line_count(lines)
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        prev_fence = open_fence
        open_fence = update_code_fence(stripped, open_fence)
        if prev_fence is not None or open_fence is not None:
            continue

        # 記号だけで判定できる検査はフロントマター・見出し・表行を含む全行が対象。
        # 「」の言及とインラインコードは区切り(全角空白)に置き換えて誤検出を防ぐ。
        masked_text = re.sub(r"`[^`]+`", "　", stripped)
        masked_text = re.sub(r"「[^」]*」", "　", masked_text)
        masked_text = re.sub(r"\*\*|\*|__", "", masked_text)

        # 中黒による並列(本スキルの整形規範。固有名詞の内部は例外)
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

        if line_no <= fm_lines:
            continue

        # 一文一行(本スキルの整形規範)。引用・表・画像・HTML 行は対象外
        is_quote_or_table = stripped.startswith(">") or stripped.startswith("|") or stripped.startswith("![") or stripped.startswith("[![") or stripped.startswith("<")
        if not is_quote_or_table:
            sent_text = re.sub(r"`[^`]+`", "", stripped)
            sent_text = re.sub(r"「[^」]*」", "", sent_text)
            # 脚注参照は文の終端ではないため除去(「文。[^脚注]」は一文のまま)。
            # 文中の画像記法は代替テキストが表示文ではないため全体を除去する
            sent_text = re.sub(r"\[\^[^\]]*\]", "", sent_text)
            sent_text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", sent_text)
            # リンクは文言に文末記号があるときだけ文言を残し、記法と宛先を消す。
            # 文言まで消すと「文A。[文B。](url)」の二文目を漏らし、無条件に残すと
            # 「文。[参考](url)」の末尾参照名を二文と誤判定する
            sent_text = re.sub(
                r"\[([^\]]*)\]\([^)]*\)",
                lambda m: m.group(1) if re.search(r"[。！？]", m.group(1)) else "",
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

        # 絵文字検知(見出し・本文問わず禁止)
        emoji_matches = EMOJI_PATTERN.findall(line)
        if emoji_matches:
            findings.append({
                "rule": "emoji_prohibited",
                "line": line_no,
                "severity": "warn",
                "message": f"絵文字({' '.join(emoji_matches[:3])})が検出されました。装飾を排し、平文で記述してください。",
                "snippet": line.strip()
            })

        # インラインコード(`...`)を除去したテキストを作成
        scan_text = re.sub(r"`[^`]+`", "", stripped)
        # 「」で囲まれた言及は禁止表現の例示であることが多い。use と mention を
        # 区別するため、語彙・構文検査は言及を除いたテキストで行う。
        # 空文字で消すと前後が接合して誤検出するため中黒で置き換える。
        # 中黒は各検査パターンを跨げない区切りになる。「X」ではなく「Y」では
        # ではなく が残るので、実際の対比は引き続き検査できる
        mention_free = re.sub(r"「[^」]*」", "・", scan_text)
        # 太字や強調などの装飾記号(**、*、__)を除去した正規化テキストで語彙・比喩を検査
        plain_text = re.sub(r"\*\*|\*|__", "", mention_free)

        # 見出し行は補足カッコとダッシュのみ検査し、本文の語彙・構文検査はスキップ
        if stripped.startswith("#"):
            if re.search(r"（(素の出力|いわゆる|概要|詳細|感謝と設計への反映)）", stripped):
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

        # 引用ブロック(>)やテーブル行(|)、画像、HTML タグはアンチパターン例示等の可能性が高いため語彙スキャンをスキップ
        if stripped.startswith(">") or stripped.startswith("|") or stripped.startswith("![") or stripped.startswith("[![") or stripped.startswith("<"):
            continue

        # 箇条書きの記号部分を除き、行頭のフィラーなども検査できるようにする。
        # plain_text は箇条書き除去後の mention_free から作る(* が強調記号として
        # 先に除去されると行頭に空白が残り、行頭パターンに一致しなくなる)
        scan_text = re.sub(r"^[-*+]\s+|^\d+\.\s+", "", scan_text)
        mention_free = re.sub(r"^[-*+]\s+|^\d+\.\s+", "", mention_free)
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

        # 文末コロン(全角「:」または半角「:」)検知
        if re.search(r"[：:]$", scan_text) and not scan_text.startswith("http"):
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
        for pattern, desc in METAPHOR_VERB_PATTERNS:
            if re.search(pattern, plain_text):
                findings.append({
                    "rule": "metaphor_verb",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。具体的な操作や状態変化に書き直してください。",
                    "snippet": line.strip()
                })

        # フィラーパターン
        for pattern, desc in FILLER_PATTERNS:
            if re.search(pattern, plain_text):
                findings.append({
                    "rule": "meta_filler",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。前置きや定型文を削り、本題から直接書いてください。",
                    "snippet": line.strip()
                })

        # ネガティブパラレリズム
        if NEGATIVE_PARALLELISM_PATTERN.search(plain_text):
            if "ではなく" in plain_text:
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
