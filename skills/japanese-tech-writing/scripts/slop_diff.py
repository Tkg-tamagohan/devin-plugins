#!/usr/bin/env python3
"""
slop_diff.py - 元の文と書き直した文を比べ、語句・文末・構造の変化を見直す候補を出す。

nanaism/yomiyasu (MIT License, Copyright (c) 2026 nanaism) の
yomiyasu_diff.py を改名してベンダリングしたもの。
ライセンス条文はスキルディレクトリの LICENSE-yomiyasu を参照。

標準ライブラリだけで動く。モデルは呼ばない。
拾うのは「意味が変わりやすい」ものだけに絞る。
  1. 文末や言い回しの種類（依頼・勧誘・義務・評価・可能・推量・念押し・意志・条件・説明化・つなぎ）の数の増減
  2. 元の文にない語（漢字2字以上、カタカナ2字以上、英数字2字以上）と、書き直した文から消えた語
  3. 箇条書きをやめたかどうか、段落をまとめたかどうか
  4. 書き直した文の中で、つながりを確かめるべき場所（文頭のつなぎ、主題の「も」、予告だけの文、文頭の指示語）
  5. 文末の種類（勧め・依頼・動作の「〜します」・評価・常体など）と、文書の立場が混ざっている候補
  6. 書き直した文の中で、太字にならない書き方（GitHub などで ** がそのまま表示されることがある箇所）と、直し方の案
  7. 文の種類の印（伝聞・推量・意見・例え・依頼・決まり）が書き直しで消えた・増えた文
  8. 見出しの数・段・形の変化と、地の文の読点が増えた候補
言い換えかどうか、つながりが合っているか、文末が立場に合っているかの最終判断は、この結果を見たモデル（または人）がする。
"""
import re
import sys
import json
import difflib
from bisect import bisect_left, bisect_right
from fractions import Fraction
try:
    if __package__:
        from .markdown_bold import bold_problems
    else:
        from markdown_bold import bold_problems
except ModuleNotFoundError as error:
    # A direct spec_from_file_location loader need not put this file's directory
    # on sys.path. Resolve this internal resource beside the actual source file.
    expected = (__package__ + ".markdown_bold") if __package__ else "markdown_bold"
    parent = __package__.split(".")[0] if __package__ else "markdown_bold"
    if error.name not in (expected, parent):
        raise
    import importlib.util
    from pathlib import Path
    _bold_spec = importlib.util.spec_from_file_location(
        "_yomiyasu_markdown_bold", Path(__file__).with_name("markdown_bold.py"))
    _bold_module = importlib.util.module_from_spec(_bold_spec)
    _bold_spec.loader.exec_module(_bold_module)
    bold_problems = _bold_module.bold_problems
try:
    if __package__:
        from .markdown_visibility import analyze_markdown, decode_source, inline_protected_spans, input_path_problem
    else:
        from markdown_visibility import analyze_markdown, decode_source, inline_protected_spans, input_path_problem
except ModuleNotFoundError as error:
    # A direct spec_from_file_location loader need not put this file's directory
    # on sys.path. Resolve this internal resource beside the actual source file.
    expected = (__package__ + ".markdown_visibility") if __package__ else "markdown_visibility"
    parent = __package__.split(".")[0] if __package__ else "markdown_visibility"
    if error.name not in (expected, parent):
        raise
    import importlib.util
    from pathlib import Path
    _visibility_spec = importlib.util.spec_from_file_location(
        "_yomiyasu_markdown_visibility", Path(__file__).with_name("markdown_visibility.py"))
    _visibility_module = importlib.util.module_from_spec(_visibility_spec)
    _visibility_spec.loader.exec_module(_visibility_module)
    analyze_markdown = _visibility_module.analyze_markdown
    decode_source = _visibility_module.decode_source
    inline_protected_spans = _visibility_module.inline_protected_spans
    input_path_problem = _visibility_module.input_path_problem
from collections import Counter, OrderedDict

# 文末や言い回しの種類。数が増えた・減ったものを候補にする
MARKERS = {
    "依頼": r"(?:て|で)ください",
    "勧誘": r"ましょう",
    "義務": r"なければ(?:なりません|ならない)|なくては(?:なりません|ならない)|ねばならない|必要があ(?:ります|る)|べき",
    "評価": r"大切|重要|大事|不可欠|欠かせ|肝心|肝要",
    "可能": r"でき(?:ます|る|ません|ない)|(?<![しさ])(?:ら|れ)(?:ます|ません)(?=[。、がけし]|$)|(?<=[作使書読言防守残伝送続進])(?:れ|え|け|め|せ)(?:ます|る)(?=[。、がけし]|$)",
    "推量": r"でしょう|だろう|かもしれ|はず|と思(?:います|う)|ようです|らしい|おそれ|たいところ",
    "念押し": r"のです|んです|こそ|まさに|必ず|絶対|常に",
    "意志": r"(?:に|ように|ことに)し(?:ます|ている|ています)",
    "条件": r"(?<!例)(?<!たと)(?:れ|え|け|せ|て|ね|め|べ)ば(?![かり])|なら(?=[、。]|$|\s)|たら(?=[、。]|$|\s)|場合",
    "説明化": r"ことが挙げられ|ということ|ことです|ことになります",
    "つなぎ": r"まず|また(?!は)|そして|さらに|次に|最後に|ただし|しかし|つまり|そのため|ので(?!す)|によって|ことで|ことにより",
}

# 文の種類を示す印。推敲の前後で対応する範囲を比べ、印が消えた・増えたものを候補にする。
# 種類と関係のない用法（様子の「降りそうだ」、目的の「使えるように」、「という名前」、「素晴らしい」、
# 受身の「見落とされた」、問いの「〜でしょうか」、評価の「驚くべき」など）は拾わない。
_END = r"(?=[。、！!？?よねがけのかし]|です|$)"
# 印の文字列を先頭に置き、直前の文字の確かめ（後読み）はその後ろに書く。正規表現が当たる見込みのない位置を飛ばせるので速い。
_TYPE_PATTERNS = (
    ("伝聞", r"そう(?:(?<=[るうくすつぬぶむぐ]そう)|(?<=だそう)|(?<=ったそう)|(?<=んだそう)|(?<=ないそう))"
           r"(?:(?:だ|です|でした|だった|で(?=、))(?=[。、！!よね]|$)|な(?=の(?:で|に|だ|です)))"
           r"|とされ(?<!落とされ)(?<!必要とされ)(?:る|ている|ています|ており|た|ます|ました|てきた)"
           r"|という(?=[。！!]|が、|$)|といいます(?<=[るうくすつぬぶむぐただ]といいます)(?=[。！!]|$)|とのこと(?<!あとのこと)(?<!後とのこと)"
           r"|によ(?<!場合によ)(?:ると|れば)|と(?:言|い)われ(?:る|ている|ています|ており|た|ます|ました|てきた)"
           r"|と聞(?<!かと聞)(?:いた|いて(?:いる|います|おり)|きました)"),
    ("推量", r"らし(?<=[るうくすつぬぶむぐいた]らし)(?:い|かった|く(?=、))" + _END
           # 名詞のあとの「らしい」は、文の終わりにあるときだけ推量と数える（「春らしい陽気」「素晴らしい」は除く）。
           + r"|らし(?<!素晴らし)(?<!すばらし)(?<!めずらし)(?<!わざとらし)(?<!可愛らし)(?<!かわいらし)(?<!憎らし)(?<!馬鹿らし)"
             r"(?<!ばからし)(?<!男らし)(?<!女らし)(?<!子供らし)(?<!子どもらし)(?<!いやらし)(?<!汚らし)(?<!春らし)(?<!夏らし)(?<!秋らし)"
             r"(?<!冬らし)(?<!彼らし)"
             # 「人間らしいが」「自分らしいけど」のような典型の言い方は、文末でないときだけ除く（「犯人は学生らしい。」は推量）。
             r"(?:い(?=[。！!]|です|でした|$|(?<!人間らしい)(?<!自分らしい)(?<!大人らしい)(?<!プロらしい)(?<!学生らしい)(?:が(?!ん)|けど|けれど))"
             r"|かった(?=[。！!]|です|でした|$|が(?!ん)|けど|けれど))"
           + r"|よう(?<!次のよう)(?<!以下のよう)(?<!下記のよう)(?<!上記のよう)(?<!左記のよう)(?<!このよう)(?<!そのよう)(?<!あのよう)(?<!どのよう)"
             r"(?:(?:だ|です|でした|だった|である|であった|で(?=、))" + _END + r"|な(?=の(?:で|に|だ|です)))"
           + r"|みたい(?:(?:だ|です|でした|だった)(?=[。！!よね]|$)|な(?=の(?:で|に|だ|です)))"
           r"|かも(?:しれ|知れ)(?:ない|ません|ず)|可能性があ(?:る|ります|った|りました)"
           r"|だろう(?<!でだろう)(?!か)|であろう|でしょう(?!か)|ではない(?:でしょう|だろう)か|はず(?:だ|です|で|でした|だった)"
           r"|と(?:見|み)られ(?:る|ている|ています|ており|た|ます)|と(?:思|おも)われ(?:る|ます|た)|と考えられ(?:る|ます|た)"),
    ("意見", r"と(?:(?:私|僕|筆者|我々|われわれ|当社|弊社|私たち)は)?(?:思|おも)(?:う|い(?:ます|ました|(?=、))|った|って(?:いる|います|いた|いました|おり))"
           r"|と(?:(?:私|僕|筆者|我々|われわれ|当社|弊社|私たち)は)?(?:考え|感じ)(?:る(?!と)|ます|ました|た|て(?:いる|います|いた|いました|おり)"
           # 「1日100件と考え、」のような数の見積もりの仮定は、連用の形のときだけ除く。
           r"|(?<![0-9０-９][件人円個回倍割%％]と考え)(?<![0-9０-９][件人円個回倍割%％]と感じ)(?=、))"
           r"|ように(?:思|感じ)(?:う|います|いました|られ)"),
    ("例え", r"まるで|あたかも|さながら|(?:ごと|如)(?<!前述のごと)(?<!上記のごと)(?<!周知のごと)(?<!以下のごと)(?<!次のごと)"
           r"(?<!前述の如)(?<!上記の如)(?<!周知の如)(?<!以下の如)(?<!次の如)[くき]"),
    ("依頼・決まり", r"(?:て|で)(?:ください|下さい)|を(?:ください|下さい)|(?:ご|お)[一-龥ぁ-んァ-ヴー]{1,8}(?:ください|下さい)"
                 r"|お願い(?<!よろしくお願い)(?<!宜しくお願い)(?:します|いたします|致します|申し上げます|できますか|できますでしょうか)"
                 r"|て(?:いただけ|もらえ)(?:ますか|ませんか)|てほしい|てもらいたい|ていただきたい"
                 r"|べき(?<!しかるべき)(?<!然るべき)(?<!驚くべき)(?<!恐るべき)(?<!来るべき)(?<!特筆すべき)(?<!注目すべき)(?!乗)"
                 r"|なければ(?:ならない|なりません|ならず|いけない|いけません)|なくては(?:ならない|なりません|ならず|いけない|いけません)"
                 r"|ないといけ(?:ない|ません)|(?:て|で)は(?:いけ|なら)(?:ない|ません)|ねばなら(?:ない|ず)"
                 r"|必要(?<!不必要)(?:があ(?:る|ります|り(?=、))|(?:です|だ)(?=[。！!]|$)"
                 r"|[にと]な(?:る(?!まで)|ります|り(?=、)|った(?!ら(?!し))|りました))"),
)
TYPE_MARKERS = OrderedDict((kind, re.compile(pattern, re.M)) for kind, pattern in _TYPE_PATTERNS)
# 種類ごとに、印の正規表現が当たるために必ず含まれる文字列。どれも含まない文章では、その種類の正規表現を当てない。
_TYPE_LITERALS = {
    "伝聞": ("そう", "とされ", "という", "といいます", "とのこと", "によると", "によれば", "われ", "と聞"),
    "推量": ("らし", "よう", "みたい", "かも", "可能性", "だろう", "であろう", "でしょう", "はず", "られ", "われ"),
    "意見": ("と思", "とおも", "と考え", "と感じ", "は思", "はおも", "は考え", "は感じ", "ように思", "ように感じ"),
    "例え": ("まるで", "あたかも", "さながら", "ごと", "如"),
    "依頼・決まり": ("ください", "下さい", "お願い", "いただけ", "もらえ", "ほしい", "もらいた", "いただきた", "べき", "なければ",
                 "なくては", "ないといけ", "はいけ", "はなら", "ねばなら", "必要"),
}
# 「まるで〜のようだ」の「よう」「みたい」は、推量ではなく例えの印として数える。
# 対にするのは、同じ文の中で「まるで」「あたかも」「さながら」のあとに最初に出てくる1つだけ。
_SIMILE_HEADS = ("まるで", "あたかも", "さながら")
_SIMILE_LIKE = re.compile(r"(?:よう|みたい)(?:であった|である|だった|でした|です|だ|な|に|で)?")
_STOPS = "。！？!?\n"
_STOP = re.compile("[" + _STOPS + "]")
# 文の中身の文字数を数えるときに除く文字（句読点・かっこ・空白）
_NOT_BODY = set("。、，！？!?「」『』（）() \n\u3000")
_SENTENCE_PIECE = re.compile(r"[^。！？!?\n]+[。！？!?]*[」』）)]*")


def _mark_positions(text: str):
    """文章全体に印の正規表現を1回ずつ当て、(開始位置, 種類, 印) を位置の順に返す。"""
    found = [(m.start(), kind, m.group(0)) for kind, pattern in TYPE_MARKERS.items()
             if any(literal in text for literal in _TYPE_LITERALS[kind]) for m in pattern.finditer(text)]
    heads = [(start, hit) for start, kind, hit in found if kind == "例え" and hit in _SIMILE_HEADS]
    if heads:
        guesses = {start: i for i, (start, kind, _) in enumerate(found) if kind == "推量"}
        paired = set()
        for start, hit in heads:
            stop = _STOP.search(text, start)
            like = _SIMILE_LIKE.search(text, start + len(hit), stop.start() if stop else len(text))
            if like and like.start() not in paired:
                paired.add(like.start())
                # 推量として拾った「ようだ」なら、その印のまま例えに移す。意見の「ように思う」などはそのまま残し、例えの印を別に足す。
                i = guesses.get(like.start())
                if i is None:
                    found.append((like.start(), "例え", like.group(0)))
                else:
                    found[i] = (like.start(), "例え", found[i][2])
    found.sort(key=lambda item: item[0])
    return found


def _marks_in(positions, spans):
    """範囲（開始, 終了）の中から始まる印を {種類: [印, ...]} にまとめる。"""
    keys = [item[0] for item in positions]
    marks = OrderedDict()
    for start, end in spans:
        for _, kind, hit in positions[bisect_left(keys, start):bisect_left(keys, end)]:
            hits = marks.setdefault(kind, [])
            if hit not in hits:
                hits.append(hit)
    return OrderedDict((kind, marks[kind]) for kind in TYPE_MARKERS if kind in marks)


def type_marks(sentence: str):
    """文や範囲に含まれる文の種類の印。{種類: [印の文字列, ...]}（同じ印は1回だけ）"""
    return _marks_in(_mark_positions(sentence), [(0, len(sentence))])


def _sentence_spans(t: str):
    """正規化した文章を文に分け、(開始, 終了) を返す。コードブロック(~~~含む)と表の行は飛ばす。"""
    kinds = {row["line"]: row["kind"] for row in analyze_markdown(t)["lines"]}
    spans, offset = [], 0
    for number, line in enumerate(t.split("\n"), 1):
        if kinds.get(number) not in ("code", "table"):
            for m in _SENTENCE_PIECE.finditer(line):
                if m.group(0).strip():
                    spans.append((offset + m.start(), offset + m.end()))
        offset += len(line) + 1
    return spans


def _slide_to_sentence_edges(opcodes, o: str, r: str):
    """文字単位の対応では、足した文や消した文が文の境目からずれることがある。
    句点1文字ぶん前にずれた「。足した文」や、次の文と同じ書き出しの分だけ後ろにずれた「消した文の後半。次の文の書き出し」の形である。
    前後の一致と同じ文字の分だけずらせるときは、句点や改行の直後から始まる位置に、ずらす量の少ないほうへずらす。"""
    ops = [list(op) for op in opcodes]
    for k in range(1, len(ops) - 1):
        tag, prev, nxt = ops[k][0], ops[k - 1], ops[k + 1]
        if tag not in ("insert", "delete") or prev[0] != "equal" or nxt[0] != "equal":
            continue
        if tag == "insert":
            text, a, b, left, right = r, ops[k][3], ops[k][4], prev[4] - prev[3], nxt[4] - nxt[3]
        else:
            text, a, b, left, right = o, ops[k][1], ops[k][2], prev[2] - prev[1], nxt[2] - nxt[1]
        if text[a - 1] in _STOPS:
            continue
        shifts = []
        step = 0
        while step < min(b - a, right - 1) and text[a + step] == text[b + step]:
            step += 1
            if text[a + step - 1] in _STOPS:
                shifts.append(step)
                break
        step = 0
        while step < min(b - a, left - 1) and text[a - 1 - step] == text[b - 1 - step]:
            step += 1
            if text[a - step - 1] in _STOPS:
                shifts.append(-step)
                break
        if shifts:
            shift = min(shifts, key=abs)
            prev[2] += shift
            prev[4] += shift
            ops[k][1:] = [ops[k][1] + shift, ops[k][2] + shift, ops[k][3] + shift, ops[k][4] + shift]
            nxt[1] += shift
            nxt[3] += shift
    return [tuple(op) for op in ops]


def _bigrams(text: str):
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _type_changes(o: str, r: str, opcodes):
    """元の各文が、文字単位の対応で書き直した文章のどの範囲に当たるかをたどり、範囲ごとに印を比べる。
    文を分けても、つないでも、範囲の中で比べるので、移っただけの印は変化として出ない。
    範囲が重なる元の文はまとめて比べる。丸ごと消えた文は比べない。丸ごと移した文は同じ文を探し、
    移したうえで書き換えた文は、字面の近い文を書き直した文章から探して比べる。"""
    if not opcodes:
        return []
    opcodes = _slide_to_sentence_edges(opcodes, o, r)
    starts = [op[1] for op in opcodes]

    def bare(op):
        """句点も改行も含まない挿入。文の頭や、句点のない文の末尾に足した語句として、その文に含める。"""
        return op[0] == "insert" and not any(ch in _STOPS for ch in r[op[3]:op[4]])

    def map_start(i):
        k = max(0, bisect_right(starts, i) - 1)
        tag, i1, i2, j1, j2 = opcodes[k]
        if i1 == i and k and opcodes[k - 1][1] == i and bare(opcodes[k - 1]):
            return opcodes[k - 1][3]
        if tag == "equal":
            return j1 + min(i - i1, j2 - j1)
        return j2 if tag == "insert" else j1

    def map_end(e):
        k = bisect_left(starts, e)
        if k < len(opcodes) and opcodes[k][1] == e and o[e - 1] not in _STOPS and bare(opcodes[k]):
            return opcodes[k][4]
        tag, i1, i2, j1, j2 = opcodes[max(0, k - 1)]
        return j1 + min(e - i1, j2 - j1) if tag == "equal" else j2

    def aligned(i, j):
        """元の [i, j) のうち、書き直した文章と対応する文字の数。句読点・かっこ・空白は数えない。
        置き換えの部分は、置き換え先が短いほど少なく数える（消した文を含む長い部分が、短い語句に置き換わった場合など）。"""
        k, count = max(0, bisect_right(starts, i) - 1), 0
        while k < len(opcodes) and opcodes[k][1] < j:
            tag, i1, i2, j1, j2 = opcodes[k]
            if tag in ("equal", "replace"):
                chars = sum(ch not in _NOT_BODY for ch in o[max(i, i1):min(j, i2)])
                count += chars if tag == "equal" else chars * min(1.0, (j2 - j1) / (i2 - i1))
            k += 1
        return count

    o_marks, r_marks = _mark_positions(o), _mark_positions(r)
    if not o_marks and not r_marks:
        return []
    r_spans = _sentence_spans(r)
    r_starts = [a for a, _ in r_spans]

    def owns_sentence(i, j):
        """元の [i, j) が対応する範囲が、それが入っている書き直した文の中身の6割以上を占めるか。"""
        a, b = map_start(i), map_end(j)
        k = bisect_right(r_starts, a) - 1
        if b <= a or k < 0 or r_spans[k][1] <= a:
            return False
        ra, rb = r_spans[k]
        whole = sum(ch not in _NOT_BODY for ch in r[ra:rb])
        part = sum(ch not in _NOT_BODY for ch in r[max(a, ra):min(b, rb)])
        return whole > 0 and part * 5 >= whole * 3
    # 丸ごと移した文は、書き直した文章の中で1文として見つかるものに限る（見出しなどの短い文が、別の文の一部に当たるのを除く）。
    whole = {}
    for a, b in r_spans:
        whole.setdefault(r[a:b].strip(), (a, b))
    groups, moved, gone, found = [], [], [], []
    for s, e in _sentence_spans(o):
        text = o[s:e].strip()
        body = sum(ch not in _NOT_BODY for ch in text)
        # 対応する文字が少なすぎる文は、残った文とみなさない。消した文の文末の数文字が、隣の文に足した印の中の文字と
        # 一致しただけの場合などで、その文を比べると、隣の文の印の変化をこの文の変化として出してしまう。
        # ただし、対応する範囲が書き直した文の大半を占めるときは、短く書き直した文として残った文とみなす。
        if aligned(s, e) < min(body, max(3, -(-body // 4))) and not owns_sentence(s, e):
            if text in whole:
                a, b = whole.pop(text)
                found.append((a, b))
                moved.append(([text], [(s, e)], a, b))
            else:
                gone.append((text, s, e))
            continue
        a, b = map_start(s), map_end(e)
        if b <= a or not r[a:b].strip("。！？!?、 \n"):
            continue
        if groups and a < groups[-1][3]:
            groups[-1][0].append(text)
            groups[-1][1].append((s, e))
            groups[-1][3] = max(groups[-1][3], b)
        else:
            groups.append([[text], [(s, e)], a, b])
    # 丸ごと移した文の位置に重なる範囲は、文字の対応がその文に引きずられたもの。移した文の部分を除き、残りの長いほうで比べる。
    for fa, fb in found:
        for g in groups:
            if g[2] < fb and fa < g[3]:
                left, right = r[g[2]:max(g[2], fa)], r[min(g[3], fb):g[3]]
                if len(left.strip("。！？!?、 \n")) >= len(right.strip("。！？!?、 \n")):
                    g[3] = max(g[2], fa)
                else:
                    g[2] = min(g[3], fb)
    groups = [g for g in groups if r[g[2]:g[3]].strip("。！？!?、 \n")]
    if gone:
        groups = _pair_gone_sentences(o, r, opcodes, groups, moved, gone, r_spans)
    _widen_to_sentences(groups, moved, r_spans)
    out = []
    for texts, spans, a, b in [tuple(g) for g in groups] + moved:
        before = _marks_in(o_marks, spans)
        after = _marks_in(r_marks, [(a, b)])
        lost = [{"kind": kind, "hits": hits} for kind, hits in before.items() if kind not in after]
        added = [{"kind": kind, "hits": hits} for kind, hits in after.items() if kind not in before]
        if lost or added:
            left = max(r.rfind(ch, 0, a) for ch in "。！？!?\n") + 1
            right = b if b and r[b - 1] in "。！？!?" else min([i for i in (r.find(ch, b) for ch in "。！？!?\n") if i != -1] + [len(r)])
            right = right + 1 if right < len(r) and r[right] in "。！？!?" else right
            out.append({"orig": "".join(texts), "rewrite": r[left:right].strip(), "lost": lost, "added": added})
    return out


def _pair_gone_sentences(o, r, opcodes, groups, moved, gone, r_spans):
    """比べずに飛ばした元の文（同じ文が書き直した文章にないもの）を、字面が重なる書き直した文と組にする。

    組にできるのは、次をどちらも満たすときだけ。消しただけの文を、残したほかの文と組にしないため。
    - 短いほうの文の2文字の組の半分以上（かつ4組以上。短いほうの組が6つ以下なら3組以上）が共通している。
    - 共通する組のうち同じ数以上が、その書き直した文に範囲が掛かっている元の文（そのまま残った文、丸ごと移した文）では説明できない。
    組は字面の近い順（Dice係数）に、どちらの文も1回だけ使って決める。
    書き直した文が1つの元の文の範囲だけでできていて、その元の文の字面が遠い（Dice係数0.6未満で、消えた文より遠い）ときは、その範囲は比べない。
    書き直した文が2文以上にまたがる範囲の端にあるときは、その範囲から外す。"""
    def dice(x, y):
        return 2 * len(x & y) / ((len(x) + len(y)) or 1)

    r_grams = [_bigrams(r[a:b].strip()) for a, b in r_spans]
    owners = [[g for g in groups if g[2] < b and a < g[3]] for a, b in r_spans]
    owner_grams = [set().union(*[_bigrams("".join(g[0])) for g in gs + [m for m in moved if m[2] < b and a < m[3]]])
                   for gs, (a, b) in zip(owners, r_spans)]
    candidates = []
    for gi, (text, _, _) in enumerate(gone):
        grams = _bigrams(text)
        for idx, (a, b) in enumerate(r_spans):
            shared = grams & r_grams[idx]
            least = 3 if min(len(grams), len(r_grams[idx])) <= 6 else 4
            if len(shared) < least or len(shared) < 0.5 * min(len(grams), len(r_grams[idx])):
                continue
            if len(shared - owner_grams[idx]) < least:
                continue
            candidates.append((dice(grams, r_grams[idx]), gi, idx))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_gone, used_r, drop = set(), {}, set()
    for score, gi, idx in candidates:
        if gi in used_gone:
            continue
        text, s, e = gone[gi]
        if idx in used_r:
            # 改行で折り返した文の前半と後半が同じ文の相手になるときは、まとめて比べる。前半は句点で終わっていない。
            entry = used_r[idx]
            first, last = entry[1][0], entry[1][-1]
            after = o[last[1]:s].strip() == "" and o[last[0]:last[1]].rstrip()[-1:] not in "。！？!?"
            before = o[e:first[0]].strip() == "" and text[-1:] not in "。！？!?"
            if not (after or before):
                continue
            used_gone.add(gi)
            entry[1].append((s, e))
            entry[1].sort()
            entry[0][:] = [o[x:y].strip() for x, y in entry[1]]
            continue
        used_gone.add(gi)
        a, b = r_spans[idx]
        moved.append(([text], [(s, e)], a, b))
        used_r[idx] = moved[-1]
        for g in owners[idx]:
            if a <= g[2] and g[3] <= b + 1:
                if dice(_bigrams("".join(g[0])), r_grams[idx]) < min(score, 0.6):
                    drop.add(id(g))
            elif g[2] < a < g[3] <= b + 1:
                g[3] = a
            elif a <= g[2] < b < g[3]:
                g[2] = b
    return [g for g in groups if id(g) not in drop]


def _widen_to_sentences(groups, moved, r_spans):
    """範囲を、それが入っている書き直した文の端まで広げる。ほかの元の文の範囲に掛かるところには広げない。
    消した文の文末の数文字に引きずられて、隣の文に足した印が範囲の外に出るのを防ぐ。"""
    if not groups:
        return
    r_starts, r_ends = [a for a, _ in r_spans], [b for _, b in r_spans]
    claimed = sorted([(g[2], g[3]) for g in groups] + [(m[2], m[3]) for m in moved])
    for g in groups:
        a, b = g[2], g[3]
        i = bisect_right(r_starts, a) - 1
        j = bisect_left(r_ends, b)
        left = r_starts[i] if 0 <= i < len(r_spans) and r_ends[i] > a else a
        right = r_ends[j] if j < len(r_spans) and r_starts[j] < b else b
        for ca, cb in claimed:
            if (ca, cb) == (a, b):
                continue
            if cb <= a:
                left = max(left, cb)
            elif ca >= b:
                right = min(right, ca)
        g[2], g[3] = min(a, left), max(b, right)


CONTENT = re.compile(r"[一-龥々〆ヵヶ]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9_.+#/-]+")


def normalize(t: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)          # 太字
    t = re.sub(r"(?m)^\s*(?:[*\-・]|\d+[.)])\s+", "", t)  # 箇条書きの印
    t = re.sub(r"(?m)^#+\s*", "", t)                 # 見出し
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def has_list(t: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:[*\-・]|\d+[.)])\s+\S", t))


def sentences(t: str):
    return [s for s in re.split(r"(?<=[。！？!?])|\n+", t) if s.strip()]


def paragraphs(t: str):
    """段落の数を数える。続いた箇条書きは1つの段落とみなす"""
    blocks, prev_list = [], False
    for line in t.split("\n"):
        if not line.strip():
            prev_list = False
            continue
        is_list = bool(re.match(r"\s*(?:[*\-・]|\d+[.)])\s+", line))
        if is_list and prev_list:
            continue
        blocks.append(line)
        prev_list = is_list
    return blocks


LOGIC = [
    ("文頭のつなぎ", re.compile(r"^(?:ただし|しかし|一方|また|さらに|つまり|そのため|したがって|だから|それでも|なお|そこで|ところが)")),
    ("主題の「も」", re.compile(r"^(?!それで)[^、。]{0,17}[^、。てでり]も、")),
    ("予告だけの文", re.compile(r"^.{0,28}(?:が|も)あります。$|次の(?:点|こと|とおり|通り)です|以下の(?:点|こと|とおり|通り)")),
    ("文頭の指示語", re.compile(r"^(?:これ|それ(?!でも|から)|こう(?:した|して|する|いう)|そう(?:した|して|する|いう)|この|その)(?!して)")),
]


def logic_points(t: str):
    pts = []
    for s in sentences(normalize(t)):
        s2 = s.strip()
        for name, pat in LOGIC:
            if pat.search(s2):
                pts.append({"kind": name, "sentence": s2})
    return pts


# ---- 文末の種類と、文書の立場 ----
# 立場は3つ。勧め = 読み手に勧める・頼む、決まり = 決まり・手順を伝える、説明 = 事実・結果・考えを伝える
STANCES = {"勧め": "勧め", "読み手に勧める": "勧め", "決まり": "決まり", "手順": "決まり", "説明": "説明", "報告": "説明", "体験": "説明"}

# 状態や性質を表す「〜ます」の語幹（動作ではないもの）
STATIVE = ("なり", "あり", "おり", "でき", "分かり", "わかり", "つながり", "変わり", "起き", "起こり", "生じ",
           "増え", "減り", "見え", "聞こえ", "残り", "続き", "終わり", "始まり", "決まり", "進み", "遅れ",
           "下回り", "上回り", "異なり", "違い", "限り", "足り", "合い", "当たり", "向き", "似", "伝わり",
           "高まり", "下がり", "上がり", "広がり", "強まり", "弱まり", "落ち", "壊れ", "崩れ", "外れ", "漏れ",
           "そろい", "揃い", "思え", "感じられ", "止まり", "消え", "困り", "迷い", "助かり")
# 可能の形（「防げます」など）。一段動詞と見分けられないので、よく出るものだけ並べる
POTENTIAL = ("防げ", "書け", "読め", "使え", "言え", "選べ", "話せ", "待て", "探せ", "直せ", "残せ", "減らせ", "増やせ",
             "守れ", "作れ", "取れ", "気づけ", "見つけられ", "続けられ", "避けられ", "変えられ", "決められ", "伝えられ")
EVAL_END = r"(?:重要|最重要|大切|大事|不可欠|肝心|肝要|欠かせません|鍵|カギ|最優先|必要)(?:です|でした|だ|である)?$"


def bare_end(s: str) -> str:
    """文末の判定に使う形。太字や記号、文末のかっこ書き（「〜」の例など）を外す"""
    t = re.sub(r"\*\*|`", "", s).strip().rstrip("。．.！!？?").strip()
    end = len(t)
    while end and t[end - 1] in "）)":
        start = end - 2
        while start >= 0 and t[start] not in "（）()":
            start -= 1
        if start < 0 or t[start] not in "（(":
            break
        end = start
        while end and t[end - 1].isspace():
            end -= 1
    return t[:end].rstrip("」』）)")


def register(s: str) -> str:
    """敬体か常体か。体言止めなどは空を返す"""
    t = bare_end(s)
    if re.search(r"(?:です|ます|ません|ました|でした|ましょう|ください|でしょう)$", t):
        return "敬体"
    if re.search(r"(?:だ|である|ではない|でない)$", t) or (re.search(r"[るうくすつぬぶむぐたい]$", t) and not re.search(r"[ァ-ヴー一-龥A-Za-z0-9]$", t)):
        return "常体"
    return ""


def ending_kind(s: str) -> str:
    t = bare_end(s)
    if not t:
        return ""
    if re.search(r"ください(?:ね)?$|(?:て|で)はいけません$|(?:て|で)はなりません$|ていただきます$|ていただけます$", t):
        return "依頼"
    if re.search(r"ましょう$|とよいです$|といいです$|をおすすめします$|をお勧めします$", t):
        return "勧め"
    if re.search(r"(?:でしょう|だろう|かもしれません|かもしれない|と思います|と考えます|と感じます|はずです|ようです|気がします)$", t):
        return "推量・考え"
    if re.search(r"(?:なければなりません|なくてはなりません|必要があります|べきです)$", t):
        return "義務"
    if re.search(EVAL_END, t):
        return "評価"
    if re.search(r"(?:ました|でした|ませんでした)$", t):
        return "過去"
    if re.search(r"(?:ます|ません)$", t):
        stem = re.sub(r"(?:ます|ません)$", "", t)
        if re.search(r"(?:て|で)い$", stem):
            return "説明（〜ています）"
        if re.search(r"(?:られ|[^しさ]れ)$", stem) or stem.endswith(STATIVE) or stem.endswith(POTENTIAL):
            return "説明（〜ます）"
        return "動作（〜します）"
    if re.search(r"です$", t):
        return "断定（〜です）"
    if re.search(r"(?:だ|である|ではない|でない)$", t):
        return "常体"
    if re.search(r"[るうくすつぬぶむぐたい]$", t) and not re.search(r"[ァ-ヴー一-龥A-Za-z0-9]$", t):
        return "常体"
    return "体言止めなど"


def ending_units(t: str, markdown: bool = False):
    """文末を見る単位。箇条書きの1項目も1文。ダッシュの前も1つの区切りとして見る。
    markdown=True のときは、コードブロック・先頭の設定部分・表の区切り行を飛ばし、表のセルは「表」として扱う"""
    out = []
    lines = t.split("\n")
    if markdown and lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            lines = lines[end + 1:]
        except ValueError:
            pass
    in_code = False
    for line in lines:
        l = line.strip()
        if markdown and l.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not l or l.startswith("#") or l == "---":
            continue
        if l.startswith("|"):
            if not markdown or set(l) <= set("|-: "):
                continue
            where, parts_src = "表", [c.strip() for c in l.strip("|").split("|")]
        elif re.match(r"^(?:[*\-・]|\d+[.)])\s+", l):
            where, parts_src = "箇条書き", [re.sub(r"^(?:[*\-・]|\d+[.)])\s+", "", l)]
        else:
            where, parts_src = "地の文", [l]
        for src in parts_src:
            for s in re.split(r"(?<=[。！？!?])", src):
                s = s.strip()
                if not s:
                    continue
                full = bool(re.search(r"[。！？!?]$", s))
                parts = [p.strip() for p in re.split(r"[—―]{1,2}", s)]
                for n, p in enumerate(parts):
                    if not p:
                        continue
                    k = ending_kind(p)
                    last = n == len(parts) - 1
                    if not k or (not last and k == "体言止めなど"):
                        continue
                    out.append({"where": where, "sentence": p, "kind": k, "full": full or not last})
    return out


def stance_flags(t: str, stance=None, markdown: bool = False):
    rows = ending_units(t, markdown)
    act = [r for r in rows if r["kind"] == "動作（〜します）" and r["where"] != "表"]
    ask = [r for r in rows if r["kind"] in ("勧め", "依頼") and r["where"] != "表"]
    rec = [r for r in ask if r["kind"] == "勧め"]
    ev = [r for r in rows if r["kind"] == "評価" and r["where"] != "表"]
    flags = []
    if stance == "勧め":
        if act:
            flags.append(("勧めの文書に、動作を表す「〜します」がある。書き手の予定や手順・道具の説明か、読み手への依頼かを原文と文脈から確認する", act))
    elif stance == "決まり":
        if rec or ev:
            flags.append(("決まり・手順の文書に、勧めや評価の文末がある。決まりそのものなら決まりの形（〜します）にする。決まりの理由や前提を述べる文なら残す。「〜してください」はそのままでよい", rec + ev))
    elif stance == "説明":
        body = [r for r in ask if r is not rows[-1]] if rows else ask
        if body:
            flags.append(("事実・結果・考えの文書に、読み手への勧めや頼みがある（最後の1文を除く）。立場が合っているか見る", body))
    else:
        if act and ask:
            flags.append(("動作の「〜します」と、勧め・依頼が同じ文章にある。「〜します」が書き手の側の予定・決まった手順なのか、読み手にしてほしい行動なのかを見る", act + ask))
        elif act and ev:
            flags.append(("動作の「〜します」と、評価（〜が重要です など）が同じ文章にある。各文の働きと原文の強さが保たれているか確認する", act + ev))
    # 敬体と常体。文として書かれた単位（。で終わるもの、ダッシュの前）だけを数える。表と、。のない箇条書きは数えない
    full = [r for r in rows if r["where"] != "表" and r["full"]]
    jotai = [r for r in full if register(r["sentence"]) == "常体"]
    keitai = [r for r in full if register(r["sentence"]) == "敬体"]
    if jotai and len(keitai) > len(jotai):
        flags.append(("敬体の文の中に、常体の文がある。そろえるときは「する → します」と形だけで変えず、立場に合う形にする", jotai))
    elif keitai and len(jotai) > len(keitai):
        flags.append(("常体の文の中に、敬体の文がある", keitai))
    return rows, flags


class _ExactSequenceMatcher(difflib.SequenceMatcher):
    """Exact whole-input containment shortcut; otherwise use the standard matcher."""

    def find_longest_match(self, alo=0, ahi=None, blo=0, bhi=None):
        if self.isjunk is not None or self.autojunk or not isinstance(self.a, str) or not isinstance(self.b, str):
            return super().find_longest_match(alo, ahi, blo, bhi)
        a, b = self.a, self.b
        ahi = len(a) if ahi is None else ahi
        bhi = len(b) if bhi is None else bhi
        if alo != 0 or blo != 0 or ahi != len(a) or bhi != len(b):
            return super().find_longest_match(alo, ahi, blo, bhi)
        a_len, b_len = ahi - alo, bhi - blo
        if not a_len or not b_len:
            return difflib.Match(alo, blo, 0)

        # Containment attains the maximum possible size; find preserves first ties.
        if a_len <= b_len:
            j = b.find(a[alo:ahi], blo, bhi)
            if j != -1:
                return difflib.Match(alo, j, a_len)
        else:
            i = a.find(b[blo:bhi], alo, ahi)
            if i != -1:
                return difflib.Match(i, blo, b_len)

        return super().find_longest_match(alo, ahi, blo, bhi)


def ending_changes(o: str, r: str):
    """書き直しで文末の種類が変わった文。似ている元の文と組にして比べる"""
    return _ending_changes_from_units(ending_units(o), ending_units(r))


def _ending_changes_from_units(ou, ru):
    """Reuse already parsed rows within diff; keep standalone parsing unchanged."""
    # 同じ文の最初の出現を保つ。同点では元の文の順番が優先される。
    originals = OrderedDict()
    for y in ou:
        originals.setdefault(y["sentence"], y)
    postings = None
    matches = {}
    changes = []
    for x in ru:
        sentence = x["sentence"]
        if sentence not in matches:
            best, score = None, 0.0
            if sentence in originals:
                # 完全一致の類似度は1。これより高い候補は存在しない。
                best, score = originals[sentence], 1.0
            else:
                matcher = difflib.SequenceMatcher(None, "", sentence, autojunk=False)
                if postings is None:
                    postings = {}
                    for i, original in enumerate(originals):
                        for ch, n in Counter(original).items():
                            postings.setdefault(ch, []).append((i, n))
                overlaps = [0] * len(originals)
                for ch, n in Counter(sentence).items():
                    for i, original_n in postings.get(ch, ()):
                        overlaps[i] += min(n, original_n)
                rewrite_len = len(sentence)
                for i, (original, y) in enumerate(originals.items()):
                    total_len = len(original) + rewrite_len
                    length_bound = 2.0 * min(len(original), rewrite_len) / total_len if total_len else 1.0
                    if length_bound < 0.45 or length_bound <= score:
                        continue
                    overlap_bound = 2.0 * overlaps[i] / total_len if total_len else 1.0
                    if overlap_bound < 0.45 or overlap_bound <= score:
                        continue
                    matcher.set_seq1(original)
                    sc = matcher.ratio()
                    if sc > score:
                        best, score = y, sc
            matches[sentence] = best, score
        best, score = matches[sentence]
        if best and score >= 0.45 and best["kind"] != x["kind"]:
            changes.append({"orig": best["sentence"], "orig_kind": best["kind"] + ("・箇条書き" if best["where"] == "箇条書き" else ""),
                            "rewrite": x["sentence"], "rewrite_kind": x["kind"]})
    return changes


# 太字の表示可否検査は markdown_bold.py へ切り出した

def count(pat: str, t: str) -> int:
    return len(re.findall(pat, t))


def context(t: str, i: int, j: int, width: int = 18) -> str:
    a, b = max(0, i - width), min(len(t), j + width)
    return t[a:i] + "［" + t[i:j] + "］" + t[j:b]


# ---- 見出しと読点の軽量な構造節 ----
# 上流 v2.5.0 の heading_shapes / comma_increase の軽量版。上流は全文差分の hunk と行の対応で文や行を組にするが、
# ここでは analyze_markdown の行の種類と、文字の似かただけで組にする簡略な対応にとどめる。

_SPACES = re.compile(r"[\s\ufeff]+")
_ATX = re.compile(r"^( {0,3})(#{1,6})((?:[ \t].*)?)$")
_ATX_MARKERS = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]+|$)|[ \t]+#+[ \t]*$")
_BOLD_ONLY_LINE = re.compile(r"^[ \t]{0,3}(?:\*\*|__)(?![ \t])(.+?)(?<![ \t])(?:\*\*|__)[ \t]*$")
_HEADING_SHOWN = 3          # 1つの文に挙げる行の組の数（ほかは「ほか N か所」）
_HEADING_REMOVED_SHOWN = 3  # 消えた見出しを挙げる数
_HEADING_LINE_WIDTH = 30    # 行を挙げるときの字数の上限（超えたら「…」で切る）
_HEADING_SHAPE_CHARS = 15   # 見出しの形の検査で見る長さの上限
_HEADING_PAIR_MIN = 0.2     # 組にする見出しの文字の似かた（2文字の組の重なり）の下限


def _bold_only(content: str):
    """段落の行の全体が1つの太字なら、その中の文字。そうでなければ None（「**a** と **b**」は1つの太字でない）"""
    match = _BOLD_ONLY_LINE.match(content)
    if match and "**" not in match.group(1) and "__" not in match.group(1):
        return match.group(1)
    return None


def _heading_key(text: str) -> str:
    """見出しを比べる文字（見出しの #、全体の太字、空白、末尾のコロンを除く）"""
    text = _ATX_MARKERS.sub("", text.strip())
    inner = _bold_only(text)
    return _SPACES.sub("", inner if inner is not None else text).rstrip("：:")


def _heading_shown(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _HEADING_LINE_WIDTH else text[:_HEADING_LINE_WIDTH] + "…"


def _heading_text(content: str, cut: bool = True) -> str:
    """見出しの行から、ATX の # を除いた文字"""
    text = _ATX_MARKERS.sub("", content.strip())
    return _heading_shown(text) if cut else text


def _heading_shape_like(key: str) -> bool:
    """見出しの形の検査で見る元の見出しか（句点で終わる、読点を含む、15字を超える）"""
    return key.endswith(("。", "．")) or "、" in key or "，" in key or len(key) > _HEADING_SHAPE_CHARS


def _heading_bigrams(key: str):
    return frozenset(key[k:k + 2] for k in range(len(key) - 1)) or frozenset((key,))


def _jaccard(left, right) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _heading_rows(text: str):
    """見出しを {"line", "level", "key", "shown", "full"} の並びで返す。
    段は ATX なら # の数、setext なら = は1、- は2。"""
    analysis = analyze_markdown(text)
    rows = analysis["lines"]
    heads = []
    for block in analysis["blocks"]:
        if block["kind"] != "heading":
            continue
        first = block["lines"][0]
        match = _ATX.match(first["content"]) if len(block["lines"]) == 1 else None
        if match:
            level = len(match.group(2))
        else:
            level = 0
            after = block["lines"][-1]["line"]
            if after < len(rows) and rows[after]["kind"] == "heading_underline" \
                    and rows[after]["content_start"] - rows[after]["start"] >= first["content_start"] - first["start"]:
                # 箇条書きの項目のあとの、字下げのない「-」「---」は次の項目か区切り線で、下線ではない
                level = 1 if rows[after]["content"].strip().startswith("=") else 2
        if not level:
            continue
        joined = "".join(row["content"] for row in block["lines"])
        heads.append({"line": first["line"], "level": level, "key": _heading_key(joined),
                      "shown": _heading_text(joined), "full": _heading_text(joined, cut=False)})
    return heads


def _heading_pairs(old_heads, new_heads):
    """見出しの組。(元の番号, 後の番号) の並び。同じ比べる文字のものを先に順に組にし、
    残りは文字の似かたが近いものどうしを組にする。比べる文字のない見出しは組にしない。"""
    pairs, used_new, leftover_old = [], set(), []
    pool = {}
    for j, head in enumerate(new_heads):
        if head["key"]:
            pool.setdefault(head["key"], []).append(j)
    for i, head in enumerate(old_heads):
        if not head["key"]:
            continue
        queue = pool.get(head["key"])
        if queue:
            j = queue.pop(0)
            used_new.add(j)
            pairs.append((i, j))
        else:
            leftover_old.append(i)
    leftover_new = [j for j in range(len(new_heads)) if j not in used_new and new_heads[j]["key"]]
    grams_old = {i: _heading_bigrams(old_heads[i]["key"]) for i in leftover_old}
    grams_new = {j: _heading_bigrams(new_heads[j]["key"]) for j in leftover_new}
    candidates = []
    for i in leftover_old:
        for j in leftover_new:
            score = _jaccard(grams_old[i], grams_new[j])
            if score >= _HEADING_PAIR_MIN:
                candidates.append((score, i, j))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_old = set()
    for _, i, j in candidates:
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        pairs.append((i, j))
    return sorted(pairs)


def _heading_changes(orig_raw: str, rw_raw: str):
    """見出しの変化を、「構造」の見直し候補の文と、見出しの形の変化の並びにする"""
    old_heads = _heading_rows(orig_raw)
    new_heads = _heading_rows(rw_raw)
    strings, shapes = [], []
    if not old_heads and not new_heads:
        return strings, shapes
    pairs = _heading_pairs(old_heads, new_heads)
    if len(old_heads) != len(new_heads):
        strings.append("見出しの数が変わった（{} → {}）。節の分け方が元と同じでよいか見る".format(len(old_heads), len(new_heads)))
        kept = {i for i, _ in pairs}
        new_keys = {head["key"] for head in new_heads}
        removed = [head["shown"] for i, head in enumerate(old_heads)
                   if i not in kept and head["key"] and head["key"] not in new_keys]
        if removed:
            shown = "、".join(removed[:_HEADING_REMOVED_SHOWN])
            if len(removed) > _HEADING_REMOVED_SHOWN:
                shown += "ほか{}件".format(len(removed) - _HEADING_REMOVED_SHOWN)
            strings[0] += "（消えた見出し: {}）".format(shown)
    levels = []
    for i, j in pairs:
        old_head, new_head = old_heads[i], new_heads[j]
        if old_head["level"] != new_head["level"]:
            levels.append("元{}行目 レベル{}「{}」→ 後{}行目 レベル{}「{}」".format(
                old_head["line"], old_head["level"], old_head["shown"], new_head["line"], new_head["level"], new_head["shown"]))
        if old_head["key"] != new_head["key"] and _heading_shape_like(old_head["key"]):
            shapes.append({"old_line": old_head["line"], "new_line": new_head["line"],
                           "old": old_head["full"], "new": new_head["full"]})
    if levels:
        shown = "、".join(levels[:_HEADING_SHOWN])
        if len(levels) > _HEADING_SHOWN:
            shown += "、ほか{}か所".format(len(levels) - _HEADING_SHOWN)
        strings.append("見出しのレベルを変えた（{}）".format(shown))
    return strings, shapes


# 読点の数え方。上流と同じく、地の文の「、」「，」だけを数え、コード、表、見出し、引用、HTML、
# カギ括弧と二重カギ括弧の中、URL、インラインのコードの中は数えない。
_COMMA_MARKS = re.compile(r"[、，]")
_COMMA_MIN_ADDED = 3
_COMMA_MIN_RATE = Fraction(3, 10)
_COMMA_SENTENCE_ADDED = 2
_COMMA_SHOWN = 5
_COMMA_PAIR_MIN = 0.45     # 文を組にする文字の似かたの下限（文末の種類の検査と同じ）
_COMMA_PAIR_LIMIT = 200_000  # 文の組を探す組み合わせの上限（超えたら件数の比較だけ出す）
_PROSE_KINDS = ("paragraph", "list")
_QUOTE_CLOSE = {"「": "」", "『": "』"}
_COMMA_SENTENCE_PIECE = re.compile(r"(?:[^。！？!?．.\n]|\.(?![ \t]|$))+(?:[。！？!?．]+|\.+(?=[ \t]|$))?[」』）)]*")


def _quote_spans(text: str):
    """かぎかっこ（「」『』）の、いちばん外側のかっこの範囲の並びを返す。
    文の句点や改行をまたぐ会話も1つとして取る。閉じないかっこは見ない。"""
    stack, tops = [], []
    for position, char in enumerate(text):
        if char in _QUOTE_CLOSE:
            stack.append((position, char))
        elif char in "」』":
            depth = len(stack) - 1
            while depth >= 0 and _QUOTE_CLOSE[stack[depth][1]] != char:
                depth -= 1
            if depth < 0:
                continue
            start = stack[depth][0]
            del stack[depth:]
            if not stack:
                tops.append((start, position + 1))
    return tops


def _comma_units(text: str):
    """地の文の文ごとの読点の数。{ "line", "text", "commas" } の並びを返す。
    段落と箇条書きの項目では、ソフト改行で折り返された行をつないでから文を区切り、各文に先頭の行番号を持たせる。
    コード、表、見出し、引用、HTML のブロックは数えない。カギ括弧と二重カギ括弧の中、URL、インラインのコードの中の読点も数えない。"""
    units = []
    for block in analyze_markdown(text)["blocks"]:
        if block["kind"] not in _PROSE_KINDS:
            continue
        parts, line_starts, line_numbers = [], [], []
        offset = 0
        for row in block["lines"]:
            line_starts.append(offset)
            line_numbers.append(row["line"])
            parts.append(row["content"])
            offset += len(row["content"])
        joined = "".join(parts)
        if not joined.strip():
            continue
        masked = list(joined)
        for left, right, _kind in inline_protected_spans(joined):
            for k in range(left, right):
                masked[k] = " "
        masked_text = "".join(masked)
        for left, right in _quote_spans(masked_text):
            for k in range(left, right):
                masked[k] = " "
        masked = "".join(masked)
        for match in _COMMA_SENTENCE_PIECE.finditer(masked):
            piece = match.group(0)
            if not piece.strip():
                continue
            display = joined[match.start():match.end()].strip()
            if not display:
                continue
            index = max(0, bisect_right(line_starts, match.start()) - 1)
            units.append({"line": line_numbers[index], "text": display, "commas": len(_COMMA_MARKS.findall(piece))})
    return units


def _comma_increase(orig_raw: str, rw_raw: str):
    """読点が増えた候補（JSON の comma_increase）。最終稿の地の文の読点が原文より3個以上多く、
    1文あたり0.3個以上増えたときに、読点が2個以上増えた文を元の近い文と並べて最大5文まで出す。
    当たらなければ None。"""
    if orig_raw == rw_raw:
        return None
    old_units = _comma_units(orig_raw)
    new_units = _comma_units(rw_raw)
    old_commas = sum(unit["commas"] for unit in old_units)
    new_commas = sum(unit["commas"] for unit in new_units)
    old_rate = Fraction(old_commas, len(old_units)) if old_units else Fraction(0)
    new_rate = Fraction(new_commas, len(new_units)) if new_units else Fraction(0)
    if new_commas - old_commas < _COMMA_MIN_ADDED or new_rate - old_rate < _COMMA_MIN_RATE:
        return None
    listed, used = [], set()
    old_grams = [_bigrams(unit["text"]) for unit in old_units]
    if len(old_units) * len(new_units) <= _COMMA_PAIR_LIMIT:
        for unit in new_units:
            if len(listed) >= _COMMA_SHOWN:
                break
            if unit["commas"] < _COMMA_SENTENCE_ADDED:
                continue
            grams = _bigrams(unit["text"])
            best_index, score = None, 0.0
            for index, old_unit in enumerate(old_units):
                if index in used or not (grams & old_grams[index]):
                    continue
                ratio = difflib.SequenceMatcher(None, old_unit["text"], unit["text"], autojunk=False).ratio()
                if ratio > score:
                    best_index, score = index, ratio
            if best_index is None or score < _COMMA_PAIR_MIN:
                continue
            old_unit = old_units[best_index]
            if unit["commas"] - old_unit["commas"] < _COMMA_SENTENCE_ADDED:
                continue
            used.add(best_index)
            listed.append({"old_line": old_unit["line"], "new_line": unit["line"],
                           "old": old_unit["text"], "new": unit["text"],
                           "old_count": old_unit["commas"], "new_count": unit["commas"]})
    return {"old_count": old_commas, "new_count": new_commas,
            "old_sentences": len(old_units), "new_sentences": len(new_units),
            "sentences": listed}


def _where(old_line, new_line):
    """行番号の表示（上流の _where と同じ形）"""
    if old_line is not None and new_line is not None:
        return "（{}行目）".format(old_line) if old_line == new_line else "（元{}行目 → 後{}行目）".format(old_line, new_line)
    if old_line is not None:
        return "（元{}行目）".format(old_line)
    if new_line is not None:
        return "（後{}行目）".format(new_line)
    return ""


def diff(orig_raw: str, rw_raw: str, stance=None) -> dict:
    o, r = normalize(orig_raw), normalize(rw_raw)
    out = {"markers": [], "new_words": [], "lost_words": [], "structure": [], "spans": [], "logic": logic_points(rw_raw),
           "bold": bold_problems(rw_raw)}
    rw_units, flags = stance_flags(rw_raw, stance)
    orig_units, orig_flags = stance_flags(orig_raw, stance)
    out["endings"] = {"stance": stance, "changes": _ending_changes_from_units(orig_units, rw_units),
                      "flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in flags],
                      "orig_flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in orig_flags]}
    opcodes = _ExactSequenceMatcher(None, o, r, autojunk=False).get_opcodes() if o != r else []
    out["type_changes"] = _type_changes(o, r, opcodes)

    # 1. 種類ごとの数の増減
    for name, pat in MARKERS.items():
        a, b = count(pat, o), count(pat, r)
        if a != b:
            hits_r = [m.group(0) for m in re.finditer(pat, r)]
            hits_o = [m.group(0) for m in re.finditer(pat, o)]
            out["markers"].append({"kind": name, "orig": a, "rewrite": b,
                                   "orig_hits": hits_o, "rewrite_hits": hits_r})

    # 2. 元にない語・消えた語（語の単位で、文のどこかに出てくるかを見る）
    o_words = set(CONTENT.findall(o))
    r_words = set(CONTENT.findall(r))
    out["new_words"] = sorted(w for w in r_words if w not in o)
    out["lost_words"] = sorted(w for w in o_words if w not in r)

    # 3. 構造
    if has_list(orig_raw) and not has_list(rw_raw):
        out["structure"].append("箇条書きを地の文にした。各項目の文末（指示・説明・評価）が元と同じか見る")
    po, pr = len(paragraphs(orig_raw)), len(paragraphs(rw_raw))
    if pr < po:
        out["structure"].append(f"段落をまとめた（{po} → {pr}）。まとめた段落の話題が1つか見る")
    if len(sentences(r)) != len(sentences(o)):
        out["structure"].append(f"文の数が変わった（{len(sentences(o))} → {len(sentences(r))}）")
    heading_strings, shapes = _heading_changes(orig_raw, rw_raw)
    out["structure"].extend(heading_strings)
    out["heading_shapes"] = shapes
    out["comma_increase"] = _comma_increase(orig_raw, rw_raw)

    # 4. 足した部分（文字単位の差分）。種類か新しい語に当たるものだけ残す
    if o != r:
        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("insert", "replace"):
                seg = r[j1:j2]
                kinds = [n for n, p in MARKERS.items() if re.search(p, r[max(0, j1 - 3):j2 + 3])]
                words = [w for w in CONTENT.findall(seg) if w not in o]
                if kinds or words:
                    out["spans"].append({"added": seg, "was": o[i1:i2], "kinds": kinds, "new_words": words,
                                         "where": context(r, j1, j2)})
    return out


def bold_head(where: str = "") -> str:
    return f"■ 太字にならない書き方（{where}GitHub などで ** がそのまま表示されることがある。表示可否と案の範囲を確認して直す）"


def bold_lines(problems):
    return [f"- {p['line']}行目: {p['found']} → {p['suggest'] or '（手で直す）'}（{p['how']}）" for p in problems]


def report(d: dict) -> str:
    lines = []
    if d["markers"]:
        lines.append("■ 言い回しの種類の増減（意味が変わりやすいところ）")
        for m in d["markers"]:
            lines.append(f"- {m['kind']}: {m['orig']} → {m['rewrite']}（元: {'、'.join(m['orig_hits']) or 'なし'}／後: {'、'.join(m['rewrite_hits']) or 'なし'}）")
    if d["new_words"]:
        lines.append("■ 元の文にない語: " + "、".join(d["new_words"]))
    if d["lost_words"]:
        lines.append("■ 消えた語: " + "、".join(d["lost_words"]))
    for s in d["structure"]:
        lines.append("■ " + s)
    if d.get("logic"):
        lines.append("■ つながりを確かめる場所（書き直した文。何と何をつないでいるか言えるか）")
        for p in d["logic"]:
            sent = p["sentence"] if len(p["sentence"]) <= 44 else p["sentence"][:44] + "…"
            lines.append(f"- {p['kind']}: {sent}")
    e = d.get("endings") or {}
    if e.get("changes"):
        lines.append("■ 文末の種類が変わった文（立場に合う向きか見る）")
        for c in e["changes"]:
            sent = c["rewrite"] if len(c["rewrite"]) <= 44 else c["rewrite"][:44] + "…"
            lines.append(f"- {c['orig_kind']} → {c['rewrite_kind']}: {sent}")
    if d.get("type_changes"):
        lines.append("■ 文の種類の印が変わった文（伝聞・推量・意見・例え・依頼が、元の文と同じか見る）")
        for c in d["type_changes"]:
            lines.append(f"- 元: {c['orig'] if len(c['orig']) <= 60 else c['orig'][:60] + '…'}")
            lines.append(f"  後: {c['rewrite'] if len(c['rewrite']) <= 60 else c['rewrite'][:60] + '…'}")
            for label, side in (("消えた印", "lost"), ("増えた印", "added")):
                if c[side]:
                    lines.append(f"  {label}: " + "、".join(f"{m['kind']}（{'、'.join(m['hits'])}）" for m in c[side]))
    if e.get("flags"):
        head = f"■ 文末の立場（{e['stance']}の文書として見た）" if e.get("stance") else "■ 文末の立場が混ざっている候補（立場を決めてから見る）"
        lines.append(head)
        for f in e["flags"]:
            lines.append(f"- {f['note']}")
            for s in f["sentences"]:
                lines.append(f"  ・{s if len(s) <= 44 else s[:44] + '…'}")
    if d.get("bold"):
        lines.append(bold_head("書き直した文。"))
        lines.extend(bold_lines(d["bold"]))
    shapes = d.get("heading_shapes") or []
    if shapes:
        lines.append("■ 見出しの形が変わった（{}件。依頼で見出しの形や長さを指定されていれば、元の形に戻す）".format(len(shapes)))
        for item in shapes:
            lines.append("- 見出しを書き換えました" + _where(item["old_line"], item["new_line"]))
            lines.append("  元: " + item["old"])
            lines.append("  後: " + item["new"])
    ci = d.get("comma_increase")
    if ci:
        old_rate = ci["old_count"] / ci["old_sentences"] if ci["old_sentences"] else 0.0
        new_rate = ci["new_count"] / ci["new_sentences"] if ci["new_sentences"] else 0.0
        lines.append("■ 読点が増えた（{}個 → {}個。1文あたり {:.2f}個 → {:.2f}個。足した読点が、誤読を防ぐ所、長い修飾や節の切れ目、"
                     "並べ、条件・逆接・理由の切れ目、主題のあとに別の動作主が続く所のどれかに当たるか確かめる。当たらなければ外す）".format(
                         ci["old_count"], ci["new_count"], old_rate, new_rate))
        for sentence in ci["sentences"]:
            lines.append("- 読点が{}個から{}個に増えました{}".format(sentence["old_count"], sentence["new_count"],
                                                                   _where(sentence["old_line"], sentence["new_line"])))
            lines.append("  元: " + sentence["old"])
            lines.append("  後: " + sentence["new"])
    return "\n".join(lines) if lines else "（候補なし）"


def _path_problem(path):
    """コマンドラインで渡されたファイルを読まないときの誤りの文か None"""
    reason = input_path_problem(path)
    if reason is None:
        return None
    return "Error opening file {}: {}。このファイルを渡すときは、標準入力から渡してください（ファイルの名前の代わりに - を渡します。1か所だけ）".format(path, reason)


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


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stance = None
    for a in sys.argv[1:]:
        if a.startswith("--stance="):
            stance = STANCES.get(a.split("=", 1)[1])
    if "--endings" in sys.argv and args:
        # 1つのファイルの文末だけを見る（マークダウンのコードブロックや表の区切りは飛ばす）
        problem = _path_problem(args[0])
        if problem:
            print(problem, file=sys.stderr)
            sys.exit(2)
        t, problem = _read_input(args[0])
        if problem:
            print(problem, file=sys.stderr)
            sys.exit(2)
        rows, flags = stance_flags(t, stance, markdown=True)
        from collections import Counter
        c = Counter(r["kind"] for r in rows if r["where"] != "表")
        print("■ 文末の種類（表を除く）: " + "、".join(f"{k} {v}" for k, v in c.most_common()))
        for n, fr in flags:
            print(f"■ {n}")
            for r in fr:
                print(f"  ・{r['sentence'] if len(r['sentence']) <= 60 else r['sentence'][:60] + '…'}")
        bp = bold_problems(t)
        if bp:
            print(bold_head())
            print("\n".join(bold_lines(bp)))
        sys.exit(0)
    if len(args) < 2:
        print("使い方: python3 slop_diff.py 元の文.txt 書き直した文.txt [--stance=勧め|決まり|説明] [--json]")
        print("　　　  python3 slop_diff.py --endings ファイル [--stance=勧め|決まり|説明]")
        sys.exit(1)
    if args[:2].count("-") > 1:
        print("標準入力（-）は1か所だけに使えます", file=sys.stderr)
        sys.exit(2)
    for path in args[:2]:
        problem = _path_problem(path)
        if problem:
            print(problem, file=sys.stderr)
            sys.exit(2)
    o, problem = _read_input(args[0])
    if problem:
        print(problem, file=sys.stderr)
        sys.exit(2)
    r, problem = _read_input(args[1])
    if problem:
        print(problem, file=sys.stderr)
        sys.exit(2)
    d = diff(o, r, stance)
    print(json.dumps(d, ensure_ascii=True, indent=1) if "--json" in sys.argv else report(d))
