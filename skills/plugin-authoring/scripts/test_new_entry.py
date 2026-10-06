"""new_entry.py の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は NE-<連番>。

fixture として一時ディレクトリに最小のプラグイン構成(rules/、skills/、
テンプレート、plugin.json、README.md)を作り、git タグ `base` を
バンプ判定の基準にする。

実行: `python3 test_new_entry.py`(同ディレクトリから)
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import new_entry

SKILL_DIR = Path(__file__).resolve().parents[1]

README_FIXTURE = """# test plugin

## 収録内容

### ルール

| ルール | 読み込まれる状況 |
| --- | --- |
| `aaa-rule` | 説明A |
| `bbb-rule` | 説明B(ファイルなし) |
| `zzz-rule` | 説明Z |

### スキル

| スキル | 内容 |
| --- | --- |
| `aaa-skill` | 説明A |
"""


def make_fixture() -> Path:
    """最小のプラグイン構成を持つ一時リポジトリを作り、base タグを打つ"""
    root = Path(tempfile.mkdtemp(prefix="new-entry-test-"))
    (root / "rules").mkdir()
    (root / ".devin-plugin").mkdir()
    (root / "skills" / "plugin-authoring").mkdir(parents=True)
    for name in ("rule-template.md", "skill-template.md"):
        shutil.copy(SKILL_DIR / name, root / "skills" / "plugin-authoring" / name)
    (root / "rules" / "aaa-rule.md").write_text("# fixture\n", encoding="utf-8")
    (root / "rules" / "zzz-rule.md").write_text("# fixture\n", encoding="utf-8")
    (root / "skills" / "aaa-skill").mkdir()
    (root / "skills" / "aaa-skill" / "SKILL.md").write_text("# fixture\n", encoding="utf-8")
    (root / ".devin-plugin" / "plugin.json").write_text(
        json.dumps(
            {"name": "shared-skills", "version": "1.2.3", "description": "test"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(README_FIXTURE, encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "test"],
        ["add", "-A"],
        ["commit", "-qm", "init"],
        ["tag", "base"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def read_version(root: Path) -> str:
    return json.loads(
        (root / ".devin-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]


class TestScaffoldRule(unittest.TestCase):
    """rule の scaffold(NE-01〜NE-05、NE-15、NE-16)"""

    def setUp(self):
        self.root = make_fixture()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_ne_01_rule_ファイルと記帳が生成される(self):
        messages = new_entry.scaffold(self.root, "rule", "my-rule", "説明M", "base")
        dest = self.root / "rules" / "my-rule.md"
        self.assertTrue(dest.is_file())
        self.assertIn("## 対象外", dest.read_text(encoding="utf-8"))
        self.assertEqual("1.2.4", read_version(self.root))
        self.assertTrue(any("my-rule" in m for m in messages))

    def test_ne_02_readme_行がアルファベット順に挿入される(self):
        new_entry.scaffold(self.root, "rule", "my-rule", "説明M", "base")
        lines = (self.root / "README.md").read_text(encoding="utf-8").splitlines()
        rows = [l for l in lines if l.startswith("| `")]
        rule_rows = [r for r in rows if "説明" in r]
        self.assertEqual(
            [
                "| `aaa-rule` | 説明A |",
                "| `bbb-rule` | 説明B(ファイルなし) |",
                "| `my-rule` | 説明M |",
                "| `zzz-rule` | 説明Z |",
            ],
            rule_rows[:4],
        )

    def test_ne_03_末尾への挿入(self):
        new_entry.scaffold(self.root, "rule", "zzzz-rule", "説明W", "base")
        lines = (self.root / "README.md").read_text(encoding="utf-8").splitlines()
        idx = lines.index("| `zzzz-rule` | 説明W |")
        self.assertEqual("| `zzz-rule` | 説明Z |", lines[idx - 1])

    def test_ne_04_命名規約違反はエラー(self):
        for bad in ("My-Rule", "my_rule", "my.rule", ""):
            with self.assertRaises(new_entry.EntryError):
                new_entry.scaffold(self.root, "rule", bad, "説明", "base")

    def test_ne_05_重複と別種同名はエラー(self):
        with self.assertRaises(new_entry.EntryError):
            new_entry.scaffold(self.root, "rule", "aaa-rule", "説明", "base")
        # rules/ 側の新規作成でも skills/aaa-skill と衝突する
        with self.assertRaises(new_entry.EntryError):
            new_entry.scaffold(self.root, "rule", "aaa-skill", "説明", "base")

    def test_ne_15_base未解決でも生成は行いversionは据え置く(self):
        messages = new_entry.scaffold(self.root, "rule", "nb-rule", "説明", "no-such-ref")
        self.assertTrue((self.root / "rules" / "nb-rule.md").is_file())
        self.assertEqual("1.2.3", read_version(self.root))
        self.assertTrue(any("WARN" in m for m in messages))

    def test_ne_16_version不正なら変更を残さない(self):
        bad = {"name": "shared-skills", "version": "0.2.x", "description": "t"}
        (self.root / ".devin-plugin" / "plugin.json").write_text(
            json.dumps(bad, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaises(new_entry.EntryError):
            new_entry.scaffold(self.root, "rule", "bad-ver", "説明", "base")
        self.assertFalse((self.root / "rules" / "bad-ver.md").exists())
        self.assertNotIn(
            "bad-ver",
            (self.root / "README.md").read_text(encoding="utf-8"),
        )


class TestScaffoldSkill(unittest.TestCase):
    """skill の scaffold(NE-06..NE-07)"""

    def setUp(self):
        self.root = make_fixture()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_ne_06_skill_の雛形に名前が入る(self):
        new_entry.scaffold(self.root, "skill", "my-skill", "説明M", "base")
        dest = self.root / "skills" / "my-skill" / "SKILL.md"
        self.assertTrue(dest.is_file())
        text = dest.read_text(encoding="utf-8")
        self.assertIn("name: my-skill", text)
        self.assertNotIn("name: (ディレクトリ名", text)
        lines = (self.root / "README.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("| `my-skill` | 説明M |", lines)
        self.assertEqual("1.2.4", read_version(self.root))

    def test_ne_07_二度目のscaffoldでversionが二重に上がらない(self):
        new_entry.scaffold(self.root, "rule", "r-one", "1", "base")
        new_entry.scaffold(self.root, "rule", "r-two", "2", "base")
        self.assertEqual("1.2.4", read_version(self.root))


class TestReadmeGuards(unittest.TestCase):
    """README・summary の入力検査(NE-08..NE-10)"""

    def setUp(self):
        self.root = make_fixture()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_ne_08_readme掲載済み名はエラー(self):
        # bbb-rule は一覧に載っているがファイルがない = README 側の重複検出を見る
        with self.assertRaises(new_entry.EntryError):
            new_entry.scaffold(self.root, "rule", "bbb-rule", "説明", "base")

    def test_ne_09_summaryに使えない文字はエラー(self):
        for bad in ("a|b", "a\nb", "  "):
            with self.assertRaises(new_entry.EntryError):
                new_entry.scaffold(self.root, "rule", "ng-rule", bad, "base")

    def test_ne_10_失敗時に中途半端な状態を残さない(self):
        with self.assertRaises(new_entry.EntryError):
            new_entry.scaffold(self.root, "rule", "bbb-rule", "説明", "base")
        self.assertFalse((self.root / "rules" / "bbb-rule.md").exists())


class TestVersionBump(unittest.TestCase):
    """version バンプの差分判定(NE-11..NE-14)"""

    def setUp(self):
        self.root = make_fixture()
        self.addCleanup(shutil.rmtree, self.root, True)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def test_ne_11_追加だけならパッチ(self):
        (self.root / "rules" / "new-one.md").write_text("# x\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "add")
        msg, warn = new_entry.sync_version(self.root, "base")
        self.assertIsNone(warn)
        self.assertEqual("1.2.4", read_version(self.root))

    def test_ne_12_削除を含むならマイナー(self):
        self.git("rm", "-q", "rules/zzz-rule.md")
        self.git("commit", "-qm", "del")
        msg, warn = new_entry.sync_version(self.root, "base")
        self.assertIsNone(warn)
        self.assertEqual("1.3.0", read_version(self.root))

    def test_ne_13_既に十分なバンプなら据え置く(self):
        data = json.loads(
            (self.root / ".devin-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        data["version"] = "1.2.4"
        (self.root / ".devin-plugin" / "plugin.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
        msg, warn = new_entry.sync_version(self.root, "base")
        self.assertEqual("1.2.4", read_version(self.root))
        self.assertIn("のまま", msg)

    def test_ne_14_base未解決はエラー(self):
        with self.assertRaises(new_entry.EntryError):
            new_entry.sync_version(self.root, "no-such-ref")
        self.assertEqual("1.2.3", read_version(self.root))


if __name__ == "__main__":
    unittest.main()
