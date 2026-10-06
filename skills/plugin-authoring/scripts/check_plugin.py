#!/usr/bin/env python3
"""
check_plugin.py - devin-plugins リポジトリの構造検査スクリプト

skills/plugin-authoring/guidelines.md のチェックリストのうち、機械化できる
項目を検査する。description が読むべき状況を特定しているか等の判断が要る
項目は対象外であり、引き続き目視で確認する。

検査項目:
- rules/*.md: 命名、frontmatter(trigger, description)、## 対象外、30 行以内
- skills/<name>/SKILL.md: 命名、frontmatter の name とディレクトリ名の一致、
  description、200 行以内
- AGENTS.md: ## 節の本文が 5 行以内
- README.md: 各ルール・スキル名がバッククォートつきで収録一覧に載っている
- .devin-plugin/plugin.json: name, version, description を持つ JSON
- --version-base <ref>: 指定した git ref の plugin.json と version が
  変わっていることを確認(PR でのバージョン更新忘れの検出用)

実行: `python3 skills/plugin-authoring/scripts/check_plugin.py` (リポジトリルートから)
違反があれば非ゼロで終了する。標準ライブラリのみで動作する。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
SEMVER_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RULE_LINE_LIMIT = 30
SKILL_LINE_LIMIT = 200
AGENTS_SECTION_LINE_LIMIT = 5
# version の意味づけ対象となるプラグイン中身のパス。これらの移動・改名・削除は
# guidelines.md の規約上マイナーバンプを要求する
VERSIONED_CONTENT_PATHS = ("rules", "skills", "AGENTS.md", "README.md")


def parse_frontmatter(text: str) -> Optional[dict]:
    """先頭の --- ブロックを簡易パースする。無ければ None"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return None


def check_rules() -> List[str]:
    errors = []
    rules_dir = REPO_ROOT / "rules"
    if not rules_dir.is_dir():
        return ["rules/ ディレクトリがありません"]
    for path in sorted(rules_dir.glob("*.md")):
        rel = path.relative_to(REPO_ROOT)
        if not NAME_PATTERN.match(path.stem):
            errors.append(f"{rel}: ファイル名が小文字英数字とハイフンのみではありません")
        # 末尾改行が空行として数えられて実際の行数を超過させないよう splitlines で数える
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(f"{rel}: frontmatter がありません")
        else:
            if not fm.get("trigger"):
                errors.append(f"{rel}: frontmatter に trigger がありません")
            if not fm.get("description"):
                errors.append(f"{rel}: frontmatter に description がありません")
        if len(lines) > RULE_LINE_LIMIT:
            errors.append(f"{rel}: {len(lines)} 行は上限 {RULE_LINE_LIMIT} 行を超えています")
        if not any(l.startswith("# ") for l in lines):
            errors.append(f"{rel}: 命令形の見出し(# ...)がありません")
        if not any(re.match(r"^##\s*対象外", l) for l in lines):
            errors.append(f"{rel}: 「## 対象外」節がありません")
    return errors


def check_skills() -> List[str]:
    errors = []
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.is_dir():
        return ["skills/ ディレクトリがありません"]
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        rel = skill_dir.relative_to(REPO_ROOT)
        if not NAME_PATTERN.match(skill_dir.name):
            errors.append(f"{rel}: ディレクトリ名が小文字英数字とハイフンのみではありません")
        if not skill_md.is_file():
            errors.append(f"{rel}: SKILL.md がありません")
            continue
        text = skill_md.read_text(encoding="utf-8")
        lines = text.splitlines()
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(f"{rel}/SKILL.md: frontmatter がありません")
        else:
            if fm.get("name") != skill_dir.name:
                errors.append(
                    f"{rel}/SKILL.md: frontmatter の name({fm.get('name')})が"
                    f"ディレクトリ名({skill_dir.name})と一致しません"
                )
            if not fm.get("description"):
                errors.append(f"{rel}/SKILL.md: frontmatter に description がありません")
        if len(lines) > SKILL_LINE_LIMIT:
            errors.append(
                f"{rel}/SKILL.md: {len(lines)} 行は上限 {SKILL_LINE_LIMIT} 行を超えています"
            )
    return errors


def check_agents() -> List[str]:
    errors = []
    path = REPO_ROOT / "AGENTS.md"
    if not path.is_file():
        return ["AGENTS.md がありません"]
    lines = path.read_text(encoding="utf-8").splitlines()
    section = None
    body_lines = 0
    for line in lines + ["## END"]:
        if line.startswith("## "):
            if section is not None and body_lines > AGENTS_SECTION_LINE_LIMIT:
                errors.append(
                    f"AGENTS.md: 節「{section}」の本文 {body_lines} 行は"
                    f"上限 {AGENTS_SECTION_LINE_LIMIT} 行を超えています"
                )
            section = line[3:].strip()
            body_lines = 0
        elif section is not None and line.strip():
            body_lines += 1
    return errors


def readme_table_names(readme: str, heading: str) -> set:
    """README の指定節(### 見出し)にある表の第1列のバッククォート囲み名を集める。

    収録一覧の表だけを対象にすることで、構成例や本文中の言及が
    一覧掲載済みと誤認されるのを防ぐ。
    """
    names = set()
    in_section = False
    for line in readme.splitlines():
        # 見出しは階層を問わず節を切り替える。#### などの下位節にある表を
        # 収録一覧と取り違えないようにする
        if re.match(r"^#+\s", line):
            in_section = line.strip().startswith(heading)
            continue
        if in_section and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells:
                m = re.fullmatch(r"`([^`]+)`", cells[0])
                if m:
                    names.add(m.group(1))
    return names


def check_readme() -> List[str]:
    errors = []
    path = REPO_ROOT / "README.md"
    if not path.is_file():
        return ["README.md がありません"]
    readme = path.read_text(encoding="utf-8")
    rules_dir = REPO_ROOT / "rules"
    if rules_dir.is_dir():
        listed = readme_table_names(readme, "### ルール")
        for f in sorted(rules_dir.glob("*.md")):
            if f.stem not in listed:
                errors.append(f"README.md: ルール `{f.stem}` が収録一覧の表にありません")
    skills_dir = REPO_ROOT / "skills"
    if skills_dir.is_dir():
        listed = readme_table_names(readme, "### スキル")
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            if d.name not in listed:
                errors.append(f"README.md: スキル `{d.name}` が収録一覧の表にありません")
    return errors


def check_plugin_json() -> List[str]:
    errors = []
    path = REPO_ROOT / ".devin-plugin" / "plugin.json"
    if not path.is_file():
        return [".devin-plugin/plugin.json がありません"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f".devin-plugin/plugin.json: JSON として解釈できません({e})"]
    for key in ("name", "version", "description"):
        if not data.get(key):
            errors.append(f".devin-plugin/plugin.json: {key} がありません")
    return errors


def check_version_bump(base_ref: str) -> List[str]:
    """base ref と version を比較し、規約通りのバンプかを検査する

    guidelines.md の規約: 追加と修正はパッチ、既存ファイルの移動・改名・削除を
    含む変更はマイナーを上げる。等しくないことだけの確認では降格や非 SemVer の
    任意文字列を通してしまうため、SemVer の単調増加と変更種別の整合を検査する。
    """
    path = REPO_ROOT / ".devin-plugin" / "plugin.json"
    try:
        base_text = subprocess.run(
            ["git", "show", f"{base_ref}:.devin-plugin/plugin.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        return [f"{base_ref} の plugin.json を取得できません({e.stderr.strip()})"]
    try:
        current = json.loads(path.read_text(encoding="utf-8"))["version"]
        base = json.loads(base_text)["version"]
    except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
        return [f"plugin.json の version を比較できません({e})"]

    base_m = SEMVER_PATTERN.match(base)
    current_m = SEMVER_PATTERN.match(current)
    if not base_m or not current_m:
        return [
            f"plugin.json の version が SemVer ではありません({base} -> {current})。"
            "X.Y.Z 形式にしてください"
        ]
    base_t = tuple(int(g) for g in base_m.groups())
    current_t = tuple(int(g) for g in current_m.groups())
    if current_t == base_t:
        return [
            f"plugin.json の version が {base_ref} から変わっていません({base})。"
            "追加・修正はパッチ、移動・改名・削除を含む変更はマイナーを上げてください"
        ]
    if current_t < base_t:
        return [
            f"plugin.json の version が {base_ref} より下がっています({base} -> {current})。"
            "version は単調増加させてください"
        ]

    # プラグイン中身の移動・改名・削除(D/R)があればマイナー以上のバンプを要求する。
    # base...HEAD はコミット済みの差分、HEAD は未コミット分(ローカル実行の網羅用)
    diff_out = ""
    for diff_args in (
        ["git", "diff", "--name-status", f"{base_ref}...HEAD", "--", *VERSIONED_CONTENT_PATHS],
        ["git", "diff", "--name-status", "HEAD", "--", *VERSIONED_CONTENT_PATHS],
    ):
        try:
            diff_out += subprocess.run(
                diff_args,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError as e:
            return [f"差分を取得できません({e.stderr.strip()})"]
    has_structural = any(
        line.split("\t", 1)[0].startswith(("D", "R"))
        for line in diff_out.splitlines()
        if line.strip()
    )
    if has_structural and current_t[:2] <= base_t[:2]:
        return [
            f"plugin.json の version が規約に合いません({base} -> {current})。"
            "移動・改名・削除を含む変更はマイナー以上を上げてください"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="devin-plugins の構造検査")
    parser.add_argument(
        "--version-base",
        metavar="REF",
        help="指定した git ref の plugin.json と version を比較し、変更がなければエラーにする",
    )
    args = parser.parse_args()

    checks: List[Tuple[str, List[str]]] = [
        ("rules/*.md", check_rules()),
        ("skills/*/SKILL.md", check_skills()),
        ("AGENTS.md", check_agents()),
        ("README.md", check_readme()),
        ("plugin.json", check_plugin_json()),
    ]
    if args.version_base:
        checks.append(("version bump", check_version_bump(args.version_base)))

    total = 0
    for label, errors in checks:
        if errors:
            total += len(errors)
            for e in errors:
                print(f"[FAIL] {e}")
        else:
            print(f"[PASS] {label}")
    if total:
        print(f"\n{total} 件の違反があります")
        return 1
    print("\nすべての構造検査を通過しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
