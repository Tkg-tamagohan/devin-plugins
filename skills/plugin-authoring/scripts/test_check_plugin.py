"""check_plugin.py の plugin.json 検査の回帰テスト

テストケースの ID 採番と報告は rule `test-conventions` に従う。
ID は CP-<連番>。

実行: `python3 test_check_plugin.py`(同ディレクトリから)
"""

import copy
import unittest

import check_plugin

BASE_MANIFEST = {
    "name": "shared-skills",
    "version": "0.2.44",
    "description": "test plugin",
}


def valid_manifest(**overrides):
    data = copy.deepcopy(BASE_MANIFEST)
    data.update(overrides)
    return data


class TestPluginJsonValidation(unittest.TestCase):
    """plugin.json の型検査(CP-01〜CP-12)"""

    def assert_valid(self, data):
        self.assertEqual([], check_plugin.validate_plugin_json(data))

    def assert_invalid(self, data, *needles):
        errors = check_plugin.validate_plugin_json(data)
        self.assertTrue(errors)
        for needle in needles:
            self.assertTrue(
                any(needle in error for error in errors),
                f"{needle!r} を含むエラーがありません: {errors}",
            )

    def test_cp_01_必須項目だけのmanifestは有効(self):
        self.assert_valid(BASE_MANIFEST)

    def test_cp_02_公式仕様のメタデータと依存を含むmanifestは有効(self):
        self.assert_valid(
            valid_manifest(
                author={"name": "Tkg-tamagohan", "email": "test@example.com"},
                homepage="https://github.com/Tkg-tamagohan/devin-plugins",
                repository="https://github.com/Tkg-tamagohan/devin-plugins",
                license="MIT",
                keywords=["devin", "plugin", "rules", "skills"],
                platforms=["cloud", "local"],
                logo="assets/logo.png",
                skills=["skills", "extra/skills"],
                requiredPlugins=[
                    "owner/repo",
                    {"source": "github", "repo": "owner/repo", "sha": "3f2a9c1"},
                ],
                optionalPlugins=[
                    {"source": "url", "url": "https://gitlab.com/team/plugin.git"}
                ],
                forbiddenPlugins=["sketchy-org/*"],
                mcpServers={"paths": ["config/mcp.json"], "exclusive": True},
            )
        )

    def test_cp_03_mcpServersの各形式は有効(self):
        variants = [
            "config/mcp.json",
            ["config/mcp.json", "config/extra.json"],
            {"paths": ["config/mcp.json"], "exclusive": True},
            {"linear": {"command": "npx", "args": ["-y", "linear-mcp"]}},
            [],
            {},
        ]
        for variant in variants:
            with self.subTest(mcpServers=variant):
                self.assert_valid(valid_manifest(mcpServers=variant))

    def test_cp_04_必須項目の欠落を検出する(self):
        for key in ("name", "version", "description"):
            with self.subTest(key=key):
                data = copy.deepcopy(BASE_MANIFEST)
                del data[key]
                self.assert_invalid(data, f"{key} がありません")

    def test_cp_05_必須項目の型違反を検出する(self):
        for key in ("name", "version", "description"):
            with self.subTest(key=key):
                self.assert_invalid(
                    valid_manifest(**{key: 123}), f"{key} は文字列である必要があります"
                )

    def test_cp_06_authorの型違反を検出する(self):
        self.assert_invalid(
            valid_manifest(author="Tkg-tamagohan"), "author はオブジェクトである必要があります"
        )
        self.assert_invalid(
            valid_manifest(author={"name": 123}), "author.name は空でない文字列である必要があります"
        )
        self.assert_invalid(
            valid_manifest(author={"email": ""}), "author.email は空でない文字列である必要があります"
        )

    def test_cp_07_文字列メタデータの型違反を検出する(self):
        for key in ("homepage", "repository", "license", "logo"):
            for bad in (123, ""):
                with self.subTest(key=key, value=bad):
                    self.assert_invalid(
                        valid_manifest(**{key: bad}),
                        f"{key} は空でない文字列である必要があります",
                    )

    def test_cp_08_keywordsとplatformsの型違反を検出する(self):
        self.assert_invalid(
            valid_manifest(keywords="devin"), "keywords は文字列の配列である必要があります"
        )
        self.assert_invalid(
            valid_manifest(keywords=["devin", 123]),
            "keywords は文字列の配列である必要があります",
        )
        self.assert_invalid(
            valid_manifest(platforms="cloud"), "platforms は文字列の配列である必要があります"
        )
        self.assert_invalid(
            valid_manifest(platforms=["cloud", 123]),
            "platforms は文字列の配列である必要があります",
        )
        self.assert_invalid(
            valid_manifest(platforms=["clouds"]), "platforms に公式仕様外の値"
        )

    def test_cp_09_skillsの型違反を検出する(self):
        self.assert_valid(valid_manifest(skills="custom-skills"))
        self.assert_valid(valid_manifest(skills=[]))
        self.assert_invalid(
            valid_manifest(skills=123),
            "skills は空でない文字列または文字列の配列である必要があります",
        )
        self.assert_invalid(
            valid_manifest(skills=["skills", 123]),
            "skills は空でない文字列または文字列の配列である必要があります",
        )

    def test_cp_10_依存リストの型違反を検出する(self):
        self.assert_invalid(
            valid_manifest(requiredPlugins="owner/repo"), "requiredPlugins は配列である必要があります"
        )
        self.assert_invalid(
            valid_manifest(requiredPlugins=[123]),
            "requiredPlugins[0] は文字列またはオブジェクトである必要があります",
        )
        self.assert_invalid(
            valid_manifest(optionalPlugins=[{"repo": "owner/repo"}]),
            "optionalPlugins[0] は source を持つオブジェクトか文字列である必要があります",
        )
        self.assert_invalid(
            valid_manifest(forbiddenPlugins={"plugin": "owner/repo"}),
            "forbiddenPlugins は配列である必要があります",
        )

    def test_cp_11_mcpServersの型違反を検出する(self):
        self.assert_invalid(
            valid_manifest(mcpServers=123), "mcpServers は文字列、文字列の配列"
        )
        self.assert_invalid(
            valid_manifest(mcpServers=["config/mcp.json", 123]),
            "mcpServers は文字列、文字列の配列",
        )
        self.assert_invalid(
            valid_manifest(mcpServers={"paths": "config/mcp.json"}),
            "mcpServers.paths は文字列の配列である必要があります",
        )
        self.assert_invalid(
            valid_manifest(mcpServers={"paths": ["config/mcp.json"], "exclusive": "yes"}),
            "mcpServers.exclusive は真偽値である必要があります",
        )
        self.assert_invalid(
            valid_manifest(mcpServers={"linear": "npx"}),
            "mcpServers.linear はオブジェクトである必要があります",
        )

    def test_cp_12_トップレベルがオブジェクトでない場合を検出する(self):
        for data in ([], "plugin.json", None):
            with self.subTest(data=data):
                self.assert_invalid(data, "JSON のトップレベルがオブジェクトではありません")


if __name__ == "__main__":
    unittest.main()
