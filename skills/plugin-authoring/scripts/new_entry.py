#!/usr/bin/env python3
"""
new_entry.py - devin-plugins のルールとスキルの生成・記帳スクリプト

plugin-authoring の手順のうち、判断を要しない機械的な工程を担う。
置き場所の判断、description と本文の執筆、既存内容との重複の解釈は
モデルの仕事であり対象外である。構造の検査は check_plugin.py が担う。

できること:
- scaffold: `rule <name>` / `skill <name>` で命名規約と重複を検査し、
  テンプレートの複写、README 収録一覧への `--summary` の行の挿入、
  plugin.json の version バンプまでを行う
- bump: 指定した base ref との差分を見て version を規約どおりの水準に補正する
  (追加・修正だけならパッチ、移動・改名・削除を含むならマイナー)

実行:
  `python3 skills/plugin-authoring/scripts/new_entry.py rule <name> --summary "..."`
  `python3 skills/plugin-authoring/scripts/new_entry.py skill <name> --summary "..."`
  `python3 skills/plugin-authoring/scripts/new_entry.py bump [--base origin/main]`
標準ライブラリのみで動作する。命名や行数の規約は check_plugin.py と共有する。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from check_plugin import (
    NAME_PATTERN,
    SEMVER_PATTERN,
    VERSIONED_CONTENT_PATHS,
)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path("skills") / "plugin-authoring"
PLUGIN_JSON_PATH = Path(".devin-plugin") / "plugin.json"
README_PATH = Path("README.md")
README_HEADINGS = {"rule": "### ルール", "skill": "### スキル"}
BUMP_ORDER = ("patch", "minor")


class EntryError(Exception):
    """入力やリポジトリ状態の不整合を表す"""


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


# --- plugin.json の version ---

def read_version(root: Path) -> str:
    path = root / PLUGIN_JSON_PATH
    if not path.is_file():
        raise EntryError(f"{PLUGIN_JSON_PATH} がありません")
    try:
        return json.loads(path.read_text(encoding="utf-8"))["version"]
    except (json.JSONDecodeError, KeyError) as e:
        raise EntryError(f"{PLUGIN_JSON_PATH} の version を読めません({e})")


def write_version(root: Path, version: str) -> None:
    path = root / PLUGIN_JSON_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def version_at_ref(root: Path, ref: str) -> Optional[str]:
    """git ref 上の plugin.json の version。取得できなければ None"""
    try:
        text = git(root, "show", f"{ref}:{PLUGIN_JSON_PATH}")
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(text)["version"]
    except (json.JSONDecodeError, KeyError):
        return None


def semver_tuple(version: str) -> Tuple[int, int, int]:
    m = SEMVER_PATTERN.match(version)
    if not m:
        raise EntryError(f"version が SemVer ではありません({version})")
    return tuple(int(g) for g in m.groups())


def bumped(version: str, level: str) -> str:
    x, y, z = semver_tuple(version)
    if level == "minor":
        return f"{x}.{y + 1}.0"
    return f"{x}.{y}.{z + 1}"


def required_level(root: Path, base_ref: str) -> Optional[str]:
    """base との差分から必要なバンプ種別を返す。差分を取得できなければ None"""
    diff_out = ""
    for diff_args in (
        ["diff", "--name-status", f"{base_ref}...HEAD", "--", *VERSIONED_CONTENT_PATHS],
        ["diff", "--name-status", "HEAD", "--", *VERSIONED_CONTENT_PATHS],
    ):
        try:
            diff_out += git(root, *diff_args)
        except subprocess.CalledProcessError:
            return None
    for line in diff_out.splitlines():
        if line.strip() and line.split("\t", 1)[0].startswith(("D", "R")):
            return "minor"
    return "patch"


def sync_version(root: Path, base_ref: str, min_level: str = "patch") -> Tuple[str, Optional[str]]:
    """version を差分が要求する水準に合わせる。

    戻り値は (報告文, 警告文または None)。base が解決できないときは
    HEAD 上の version を基点にし、未バンプの場合だけ min_level で上げる。
    """
    level = required_level(root, base_ref)
    warn = None
    if level is None:
        warn = f"{base_ref} との差分を取得できなかったため {min_level} として扱います"
        level = min_level
    if BUMP_ORDER.index(min_level) > BUMP_ORDER.index(level):
        level = min_level

    current = read_version(root)
    base_v = version_at_ref(root, base_ref)
    if base_v is not None:
        target = bumped(base_v, level)
        if semver_tuple(current) < semver_tuple(target):
            write_version(root, target)
            return (f"plugin.json: version {current} -> {target}", warn)
        return (f"plugin.json: version {current} のまま(必要水準 {target} 以上)", warn)

    committed = version_at_ref(root, "HEAD")
    if committed is not None and semver_tuple(current) != semver_tuple(committed):
        return (
            f"plugin.json: version {current} のまま(HEAD から既に変更済み、base 未解決)",
            warn,
        )
    target = bumped(current, level)
    write_version(root, target)
    return (f"plugin.json: version {current} -> {target}(base 未解決のため現在値起点)", warn)


# --- README 収録一覧 ---

def find_readme_table(
    root: Path, kind: str
) -> Tuple[List[str], List[Tuple[int, str]], int]:
    """README の収録一覧の表を読み、行リスト・エントリ・表の末尾行を返す"""
    path = root / README_PATH
    if not path.is_file():
        raise EntryError(f"{README_PATH} がありません")
    lines = path.read_text(encoding="utf-8").splitlines()
    heading = README_HEADINGS[kind]

    in_section = False
    entries: List[Tuple[int, str]] = []
    last_table_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if re.match(r"^#+\s", line):
            if in_section and last_table_idx is not None:
                break
            in_section = line.strip().startswith(heading)
            continue
        if in_section and line.strip().startswith("|"):
            last_table_idx = i
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells:
                m = re.fullmatch(r"`([^`]+)`", cells[0])
                if m:
                    entries.append((i, m.group(1)))
    if last_table_idx is None:
        raise EntryError(f"{README_PATH}: 「{heading}」の収録一覧の表が見つかりません")
    return lines, entries, last_table_idx


def readme_has_name(root: Path, kind: str, name: str) -> bool:
    return any(n == name for _, n in find_readme_table(root, kind)[1])


def insert_readme_row(root: Path, kind: str, name: str, summary: str) -> str:
    """収録一覧の表に `| \`name\` | summary |` をアルファベット順で挿入する"""
    lines, entries, last_table_idx = find_readme_table(root, kind)
    if any(n == name for _, n in entries):
        raise EntryError(f"{README_PATH}: `{name}` の行が収録一覧に既にあります")

    pos = last_table_idx + 1
    for idx, existing in entries:
        if name < existing:
            pos = idx
            break
    lines.insert(pos, f"| `{name}` | {summary} |")
    (root / README_PATH).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"{README_PATH}: 「{README_HEADINGS[kind]}」の表に `{name}` の行を追加"


# --- scaffold ---

def validate_new_name(root: Path, name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise EntryError(f"`{name}` は小文字英数字と `-` だけを使う名前にしてください")
    if (root / "rules" / f"{name}.md").exists() or (root / "skills" / name).exists():
        raise EntryError(f"`{name}` は既に存在します")


def validate_summary(summary: str) -> None:
    if not summary or not summary.strip():
        raise EntryError("--summary が空です")
    if "|" in summary or "\n" in summary:
        raise EntryError("--summary に使えない文字(`|` または改行)があります")


def scaffold(root: Path, kind: str, name: str, summary: str, base_ref: str) -> List[str]:
    """テンプレート複写、README 行挿入、version バンプを行い、報告文を返す"""
    # 変更を加える前に検査をすべて済ませ、失敗時に中途半端な状態を残さない
    validate_new_name(root, name)
    validate_summary(summary)
    if readme_has_name(root, kind, name):
        raise EntryError(f"{README_PATH}: `{name}` の行が収録一覧に既にあります")

    template = root / TEMPLATES_DIR / f"{kind}-template.md"
    if not template.is_file():
        raise EntryError(f"テンプレート {TEMPLATES_DIR / (kind + '-template.md')} がありません")
    text = template.read_text(encoding="utf-8")

    messages = []
    if kind == "rule":
        dest = root / "rules" / f"{name}.md"
        dest.write_text(text, encoding="utf-8")
        messages.append(f"作成: rules/{name}.md")
    else:
        skill_dir = root / "skills" / name
        skill_dir.mkdir()
        text = re.sub(r"(?m)^name:.*$", f"name: {name}", text, count=1)
        dest = skill_dir / "SKILL.md"
        dest.write_text(text, encoding="utf-8")
        messages.append(f"作成: skills/{name}/SKILL.md")

    messages.append(insert_readme_row(root, kind, name, summary))
    version_msg, warn = sync_version(root, base_ref, "patch")
    messages.append(version_msg)
    if warn:
        messages.append(f"[WARN] {warn}")
    messages.append(
        "次に: 生成したファイルの description と本文を埋め、"
        "check_plugin.py で構造を確認してください"
    )
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(
        description="devin-plugins のルールとスキルの生成・記帳"
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_REPO_ROOT),
        help="対象リポジトリのルート(既定はスクリプトの位置から推定)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for kind in ("rule", "skill"):
        sp = sub.add_parser(kind, help=f"{kind} のファイルと記帳を生成")
        sp.add_argument("name", help="小文字英数字と `-` の名前")
        sp.add_argument(
            "--summary",
            required=True,
            help="README 収録一覧に載せる一文",
        )
        sp.add_argument(
            "--base",
            default="origin/main",
            help="version バンプの基準となる git ref(既定: origin/main)",
        )
    bp = sub.add_parser("bump", help="差分から version を規約どおりの水準に補正")
    bp.add_argument(
        "--base",
        default="origin/main",
        help="比較基準となる git ref(既定: origin/main)",
    )
    args = parser.parse_args()

    root = Path(args.root)
    try:
        if args.command == "bump":
            msg, warn = sync_version(root, args.base, "patch")
            print(msg)
            if warn:
                print(f"[WARN] {warn}", file=sys.stderr)
        else:
            for message in scaffold(root, args.command, args.name, args.summary, args.base):
                print(message)
    except EntryError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
