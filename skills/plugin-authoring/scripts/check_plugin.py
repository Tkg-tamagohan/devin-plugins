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
- README.md: rules/ と skills/ が収録一覧と双方向で一致している
- docs/*.md: チェックリストを持つ計画書に `状態:` 行(進行中/完了/中断)がある、
  「進行中」なのに全項目チェック済みの矛盾がない
- .devin-plugin/plugin.json: name, version, description を持つ JSON。
  author, homepage, repository, license, keywords, platforms など公式仕様の
  フィールドについても型を検査する
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
PLUGIN_JSON_PATH = Path(".devin-plugin") / "plugin.json"
PLUGIN_JSON_LABEL = PLUGIN_JSON_PATH.as_posix()
README_PATH = Path("README.md")
README_HEADINGS = {"rule": "### ルール", "skill": "### スキル"}
PLUGIN_JSON_REQUIRED_STRING_FIELDS = ("name", "version", "description")
PLUGIN_JSON_OPTIONAL_STRING_FIELDS = ("homepage", "repository", "license", "logo")
PLUGIN_JSON_DEPENDENCY_LIST_FIELDS = ("requiredPlugins", "optionalPlugins", "forbiddenPlugins")
PLUGIN_JSON_ALLOWED_PLATFORMS = frozenset({"cloud", "local", "security"})


def run_git(root: Path, *args: str) -> str:
    """指定ディレクトリで git サブコマンドを実行し、標準出力を UTF-8 で返す。"""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def semver_tuple(version: str) -> Optional[Tuple[int, int, int]]:
    """X.Y.Z 形式の SemVer を整数タプルに変換する。不一致時は None を返す。"""
    if not isinstance(version, str):
        return None
    m = SEMVER_PATTERN.match(version)
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def version_at_ref(root: Path, ref: str) -> Tuple[Optional[str], Optional[str]]:
    """git ref 上の plugin.json の version と失敗時のエラーメッセージを返す。"""
    try:
        # Windows では str(Path) がバックスラッシュを返し git が
        # 「ref:path」のパス部を解決できないため posix に固定する
        text = run_git(root, "show", f"{ref}:{PLUGIN_JSON_PATH.as_posix()}")
    except subprocess.CalledProcessError as e:
        return None, f"{ref} の plugin.json を取得できません({e.stderr.strip()})"
    try:
        version = json.loads(text)["version"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return None, f"plugin.json の version を比較できません({e})"
    return version, None


def has_structural_changes(root: Path, base_ref: str) -> Tuple[Optional[bool], Optional[str]]:
    """base_ref との差分に削除・改名(D/R)が含まれるかと失敗時のエラー詳細を返す。

    base...HEAD はコミット済みの差分、HEAD は未コミット分(ローカル実行の網羅用)を見る。
    """
    diff_out = ""
    for diff_args in (
        ("diff", "--name-status", f"{base_ref}...HEAD", "--", *VERSIONED_CONTENT_PATHS),
        ("diff", "--name-status", "HEAD", "--", *VERSIONED_CONTENT_PATHS),
    ):
        try:
            diff_out += run_git(root, *diff_args)
        except subprocess.CalledProcessError as e:
            return None, e.stderr.strip()
    has_structural = any(
        line.split("\t", 1)[0].startswith(("D", "R"))
        for line in diff_out.splitlines()
        if line.strip()
    )
    return has_structural, None


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


def check_rules(root: Path = REPO_ROOT) -> List[str]:
    errors = []
    rules_dir = root / "rules"
    if not rules_dir.is_dir():
        return ["rules/ ディレクトリがありません"]
    for path in sorted(rules_dir.glob("*.md")):
        rel = path.relative_to(root).as_posix()
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


def check_skills(root: Path = REPO_ROOT) -> List[str]:
    errors = []
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return ["skills/ ディレクトリがありません"]
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        rel = skill_dir.relative_to(root).as_posix()
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


def check_agents(root: Path = REPO_ROOT) -> List[str]:
    errors = []
    path = root / "AGENTS.md"
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


def find_readme_table(
    readme: str, heading: str
) -> Tuple[List[str], List[Tuple[int, str]], Optional[int]]:
    """README の指定節(### 見出し)にある収録一覧の表を解析する。

    (全行リスト, [(行番号, バッククォート囲み名), ...], 表の最終行番号または None)
    を返す。収録一覧の表だけを対象にすることで、構成例や本文中の言及が
    一覧掲載済みと誤認されるのを防ぐ。
    """
    lines = readme.splitlines()
    in_section = False
    entries: List[Tuple[int, str]] = []
    last_table_idx: Optional[int] = None
    for i, line in enumerate(lines):
        # 見出しは階層を問わず節を切り替える。#### などの下位節にある表を
        # 収録一覧と取り違えないようにする
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
    return lines, entries, last_table_idx


def readme_table_names(readme: str, heading: str) -> set:
    """README の指定節にある表の第1列のバッククォート囲み名の集合を返す。"""
    _, entries, _ = find_readme_table(readme, heading)
    return {name for _, name in entries}


def check_readme(root: Path = REPO_ROOT) -> List[str]:
    """README.md の収録一覧と rules/・skills/ の双方向同期を検査する。"""
    errors = []
    path = root / README_PATH
    if not path.is_file():
        return ["README.md がありません"]
    readme = path.read_text(encoding="utf-8")

    rules_dir = root / "rules"
    actual_rules = (
        {f.stem for f in rules_dir.glob("*.md")} if rules_dir.is_dir() else set()
    )
    listed_rules = readme_table_names(readme, README_HEADINGS["rule"])
    for name in sorted(actual_rules - listed_rules):
        errors.append(f"README.md: ルール `{name}` が収録一覧の表にありません")
    for name in sorted(listed_rules - actual_rules):
        errors.append(
            f"README.md: 収録一覧のルール `{name}` に対応するファイルが rules/ にありません"
        )

    skills_dir = root / "skills"
    actual_skills = (
        {d.name for d in skills_dir.iterdir() if d.is_dir()}
        if skills_dir.is_dir()
        else set()
    )
    listed_skills = readme_table_names(readme, README_HEADINGS["skill"])
    for name in sorted(actual_skills - listed_skills):
        errors.append(f"README.md: スキル `{name}` が収録一覧の表にありません")
    for name in sorted(listed_skills - actual_skills):
        errors.append(
            f"README.md: 収録一覧のスキル `{name}` に対応するディレクトリが skills/ にありません"
        )
    return errors


DOC_STATUS_PATTERN = re.compile(r"^状態[:：]\s*(進行中|完了|中断)")
DOC_CHECKED_PATTERN = re.compile(r"^\s*[-*]\s+\[[xX]\]")
DOC_UNCHECKED_PATTERN = re.compile(r"^\s*[-*]\s+\[ \]")


def check_docs(root: Path = REPO_ROOT) -> List[str]:
    """docs/ の計画書(チェックリストを持つ Markdown)の状態行を検査する。

    計画書の完了後も陳腐化した現況記述が残る事例があったため、状態行の有無と
    「進行中だが全項目チェック済み」の矛盾を機械検出する。
    """
    errors = []
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return errors
    for path in sorted(docs_dir.glob("*.md")):
        rel = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        has_checklist = any(
            DOC_CHECKED_PATTERN.match(l) or DOC_UNCHECKED_PATTERN.match(l)
            for l in lines
        )
        if not has_checklist:
            continue
        status = next(
            (m for l in lines if (m := DOC_STATUS_PATTERN.match(l))), None
        )
        if status is None:
            errors.append(
                f"{rel}: チェックリストを持つ計画書に"
                "`状態:` 行(進行中/完了/中断)がありません"
            )
            continue
        if status.group(1) == "進行中" and not any(
            DOC_UNCHECKED_PATTERN.match(l) for l in lines
        ):
            errors.append(
                f"{rel}: 全項目がチェック済みですが `状態: 進行中` のままです。"
                "完了か中断へ更新してください"
            )
    return errors


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_plugin_json_mcp_servers(value: object, errors: List[str]) -> None:
    if _is_non_empty_string(value):
        return
    if isinstance(value, list):
        if all(_is_non_empty_string(item) for item in value):
            return
        errors.append(
            f"{PLUGIN_JSON_LABEL}: mcpServers は文字列、文字列の配列、"
            "paths/exclusive オブジェクト、サーバー定義のオブジェクトのいずれかである必要があります"
        )
        return
    if isinstance(value, dict):
        keys = set(value.keys())
        if keys & {"paths", "exclusive"}:
            paths = value.get("paths")
            if not isinstance(paths, list) or not all(
                _is_non_empty_string(path) for path in paths
            ):
                errors.append(
                    f"{PLUGIN_JSON_LABEL}: mcpServers.paths は文字列の配列である必要があります"
                )
            if "exclusive" in value and not isinstance(value["exclusive"], bool):
                errors.append(
                    f"{PLUGIN_JSON_LABEL}: mcpServers.exclusive は真偽値である必要があります"
                )
            if not keys <= {"paths", "exclusive"}:
                errors.append(
                    f"{PLUGIN_JSON_LABEL}: mcpServers の paths/exclusive 形式に未知のキーがあります"
                )
            return
        for name, server in value.items():
            if not isinstance(server, dict):
                errors.append(
                    f"{PLUGIN_JSON_LABEL}: mcpServers.{name} はオブジェクトである必要があります"
                )
        return
    errors.append(
        f"{PLUGIN_JSON_LABEL}: mcpServers は文字列、文字列の配列、"
        "paths/exclusive オブジェクト、サーバー定義のオブジェクトのいずれかである必要があります"
    )


def validate_plugin_json(data: object) -> List[str]:
    """plugin.json の必須項目と公式仕様フィールドの型を検査する"""
    errors: List[str] = []
    if not isinstance(data, dict):
        return [f"{PLUGIN_JSON_LABEL}: JSON のトップレベルがオブジェクトではありません"]

    for key in PLUGIN_JSON_REQUIRED_STRING_FIELDS:
        if key not in data:
            errors.append(f"{PLUGIN_JSON_LABEL}: {key} がありません")
            continue
        value = data[key]
        if not isinstance(value, str):
            errors.append(f"{PLUGIN_JSON_LABEL}: {key} は文字列である必要があります")
        elif not value.strip():
            errors.append(f"{PLUGIN_JSON_LABEL}: {key} がありません")

    for key in PLUGIN_JSON_OPTIONAL_STRING_FIELDS:
        if key not in data:
            continue
        if not _is_non_empty_string(data[key]):
            errors.append(
                f"{PLUGIN_JSON_LABEL}: {key} は空でない文字列である必要があります"
            )

    if "author" in data:
        author = data["author"]
        if not isinstance(author, dict):
            errors.append(f"{PLUGIN_JSON_LABEL}: author はオブジェクトである必要があります")
        else:
            for key in ("name", "email"):
                if key in author and not _is_non_empty_string(author[key]):
                    errors.append(
                        f"{PLUGIN_JSON_LABEL}: author.{key} は空でない文字列である必要があります"
                    )

    if "keywords" in data:
        keywords = data["keywords"]
        if not isinstance(keywords, list) or not all(
            _is_non_empty_string(keyword) for keyword in keywords
        ):
            errors.append(f"{PLUGIN_JSON_LABEL}: keywords は文字列の配列である必要があります")

    if "platforms" in data:
        platforms = data["platforms"]
        if not isinstance(platforms, list) or not all(
            _is_non_empty_string(platform) for platform in platforms
        ):
            errors.append(f"{PLUGIN_JSON_LABEL}: platforms は文字列の配列である必要があります")
        else:
            for platform in platforms:
                if platform not in PLUGIN_JSON_ALLOWED_PLATFORMS:
                    errors.append(
                        f"{PLUGIN_JSON_LABEL}: platforms に公式仕様外の値 {platform!r} があります"
                        "(cloud, local, security のいずれか)"
                    )

    if "skills" in data:
        skills = data["skills"]
        valid_skills = _is_non_empty_string(skills) or (
            isinstance(skills, list)
            and all(_is_non_empty_string(skill) for skill in skills)
        )
        if not valid_skills:
            errors.append(
                f"{PLUGIN_JSON_LABEL}: skills は空でない文字列または文字列の配列である必要があります"
            )

    for key in PLUGIN_JSON_DEPENDENCY_LIST_FIELDS:
        if key not in data:
            continue
        entries = data[key]
        if not isinstance(entries, list):
            errors.append(f"{PLUGIN_JSON_LABEL}: {key} は配列である必要があります")
            continue
        for index, entry in enumerate(entries):
            if _is_non_empty_string(entry):
                continue
            if isinstance(entry, dict):
                if not _is_non_empty_string(entry.get("source")):
                    errors.append(
                        f"{PLUGIN_JSON_LABEL}: {key}[{index}] は source を持つオブジェクトか"
                        "文字列である必要があります"
                    )
                continue
            errors.append(
                f"{PLUGIN_JSON_LABEL}: {key}[{index}] は文字列またはオブジェクトである必要があります"
            )

    if "mcpServers" in data:
        _check_plugin_json_mcp_servers(data["mcpServers"], errors)

    return errors


def check_plugin_json(root: Path = REPO_ROOT) -> List[str]:
    path = root / PLUGIN_JSON_PATH
    if not path.is_file():
        return [f"{PLUGIN_JSON_LABEL} がありません"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"{PLUGIN_JSON_LABEL}: JSON として解釈できません({e})"]
    return validate_plugin_json(data)


def check_version_bump(base_ref: str, root: Path = REPO_ROOT) -> List[str]:
    """base ref と version を比較し、規約通りのバンプかを検査する

    guidelines.md の規約: 追加と修正はパッチ、既存ファイルの移動・改名・削除を
    含む変更はマイナーを上げる。等しくないことだけの確認では降格や非 SemVer の
    任意文字列を通してしまうため、SemVer の単調増加と変更種別の整合を検査する。
    """
    base, base_err = version_at_ref(root, base_ref)
    if base_err is not None:
        return [base_err]
    path = root / PLUGIN_JSON_PATH
    try:
        current = json.loads(path.read_text(encoding="utf-8"))["version"]
    except (json.JSONDecodeError, KeyError, FileNotFoundError, TypeError) as e:
        return [f"plugin.json の version を比較できません({e})"]

    base_t = semver_tuple(base)
    current_t = semver_tuple(current)
    if base_t is None or current_t is None:
        return [
            f"plugin.json の version が SemVer ではありません({base} -> {current})。"
            "X.Y.Z 形式にしてください"
        ]
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
    has_structural, diff_err = has_structural_changes(root, base_ref)
    if diff_err is not None:
        return [f"差分を取得できません({diff_err})"]
    if has_structural and current_t[:2] <= base_t[:2]:
        return [
            f"plugin.json の version が規約に合いません({base} -> {current})。"
            "移動・改名・削除を含む変更はマイナー以上を上げてください"
        ]
    return []


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

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
        ("docs/*.md", check_docs()),
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
