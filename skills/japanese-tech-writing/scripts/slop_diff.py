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
言い換えかどうか、つながりが合っているか、文末が立場に合っているかの最終判断は、この結果を見たモデル（または人）がする。
"""
import re
import sys
import json
import difflib
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


def diff(orig_raw: str, rw_raw: str, stance=None) -> dict:
    o, r = normalize(orig_raw), normalize(rw_raw)
    out = {"markers": [], "new_words": [], "lost_words": [], "structure": [], "spans": [], "logic": logic_points(rw_raw),
           "bold": bold_problems(rw_raw)}
    rw_units, flags = stance_flags(rw_raw, stance)
    orig_units, orig_flags = stance_flags(orig_raw, stance)
    out["endings"] = {"stance": stance, "changes": _ending_changes_from_units(orig_units, rw_units),
                      "flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in flags],
                      "orig_flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in orig_flags]}

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

    # 4. 足した部分（文字単位の差分）。種類か新しい語に当たるものだけ残す
    if o != r:
        sm = _ExactSequenceMatcher(None, o, r, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
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
    return "\n".join(lines) if lines else "（候補なし）"


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


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
        t = read_text(args[0])
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
    o = read_text(args[0])
    r = read_text(args[1])
    d = diff(o, r, stance)
    print(json.dumps(d, ensure_ascii=True, indent=1) if "--json" in sys.argv else report(d))
