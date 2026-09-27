# shared-skills (Devin plugin)

組織横断で使う Devin のルールとスキルを管理するプラグインリポジトリ。

## 構成

```
.devin-plugin/plugin.json          # プラグインマニフェスト(name が /<plugin>:<skill> の名前空間になる)
AGENTS.md                          # 全セッションに常時適用される共通ルール(作業種別に依存しない短い制約のみ)
rules/<name>.md                    # トリガー付きルール(description に合う状況のセッションでのみ本文が読まれる)
skills/<name>/SKILL.md             # スキル本体(手順や知識。呼び出されたときに読まれる)
skills/plugin-authoring/           # このリポジトリ自体の編集手順、作成指針(guidelines.md)、テンプレート
```

ルールやスキルをどこに置くか、どの粒度で分けるかの基準は `skills/plugin-authoring/guidelines.md` にまとめている。
新しく追加するときは、スキル `shared-skills:plugin-authoring` の手順に従う。
`rules/register-to-devin-plugins.md` により、セッション中に再利用可能なルールやスキルを作成した Devin はこのリポジトリへの追加 PR を自動で作る。

## インストール / 更新

Devin Web アプリの **Customize → Plugins → Add plugin → From repository** でこのリポジトリを Organization スコープとしてインストールする(要: 組織のプラグイン管理権限)。
インストール後、スキルは組織の全セッションで自動検出されるほか、`/shared-skills:<skill名>` でも呼び出せる。

内容を更新した場合は、このリポジトリに push したうえで Customize のプラグイン設定から再インデックスする。
