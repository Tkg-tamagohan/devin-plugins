# shared-skills (Devin plugin)

組織横断で使う Devin スキルを管理するプラグインリポジトリ。

## 構成

```
.devin-plugin/plugin.json   # プラグインマニフェスト(name が /<plugin>:<skill> の名前空間になる)
skills/<name>/SKILL.md      # スキル本体(必要になったらこの下にディレクトリを追加)
```

## インストール / 更新

Devin Web アプリの **Customize → Plugins → Add plugin → From repository** でこのリポジトリを Organization スコープとしてインストールする(要: 組織のプラグイン管理権限)。
インストール後、スキルは組織の全セッションで自動検出されるほか、`/shared-skills:<skill名>` でも呼び出せる。

内容を更新した場合は、このリポジトリに push したうえで Customize のプラグイン設定から再インデックスする。
