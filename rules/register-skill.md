---
trigger: model_decision
description: 再利用可能なスキル(SKILL.md)を新規作成する、保存する、ほかのセッションやメンバーと共有したい、と判断したとき
---

# スキルの集約先は devin-plugins リポジトリ

再利用可能なスキル(SKILL.md)を作成したとき、またはスキルの保存・共有を求められたときは、必ず `Tkg-tamagohan/devin-plugins` リポジトリにも登録する。Devin 管理のプラグイン(Customize → Skills)への登録と併用してよいが、こちらのリポジトリが正規の管理場所である。

## 手順

1. リポジトリを取得する。未クローンなら `git clone https://github.com/Tkg-tamagohan/devin-plugins.git`、既存のクローンがあれば `git fetch` + 最新の main に追従する。
2. `skills/<skill名>/SKILL.md` にスキル本体を配置する。`<skill名>` は frontmatter の `name` と一致させる(小文字英数字と `-`・`.` のみ)。
3. `.devin-plugin/plugin.json` の `version` をパッチ上げする(例: `0.1.0` → `0.1.1`)。
4. ブランチを切って(例: `devin/add-skill-<skill名>`)コミットし、PR を作成する。
5. プラグインがインストール済みの環境に反映されるには再インデックスが必要なので、PR 作成後にその旨をユーザーへ伝える。

## 対象外

- 個人専用・使い捨てのスキル
- リポジトリ固有の手順を書くスキル(作業対象のリポジトリ内の `.devin/skills/` または `.agents/skills/` に置くべきもの)
