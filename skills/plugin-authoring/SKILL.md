---
name: plugin-authoring
description: devin-plugins(shared-skills プラグイン)にルールやスキルを追加または変更する手順。置き場所(AGENTS.md、rules/、skills/)の判断、粒度と構成の指針、テンプレートからの作成、plugin.json のバージョン更新、PR 作成を扱う。共有すべきルールやスキルを新規作成する、既存のものを統合または分離する、または devin-plugins リポジトリを編集するときに使用する。日本語の文体規範は japanese-tech-writing に委ねる。
---

# devin-plugins へのルールとスキルの追加と変更

`Tkg-tamagohan/devin-plugins` にルールやスキルを追加または変更するときは、以下の手順で進める。
ゴールは、追加した内容が他のファイルと重複せず、読み込まれるべき状況でだけ読み込まれる状態にすることである。

置き場所と粒度の判断基準は同じディレクトリの `guidelines.md` に、ファイルの型は `rule-template.md` と `skill-template.md` にある。
判断に迷ったら本文で推測せず、`guidelines.md` の判断表に戻る。

## 責任範囲の境界

- **文章の文体**：日本語の本文は `japanese-tech-writing` に従う。
  - 本スキルは文体を定めない。
- **リポジトリ固有の手順**：作業対象リポジトリにしか関係しない手順は本スキルの対象外とし、そのリポジトリの `.devin/skills/` または `.agents/skills/` に置く。
- **生成と記帳の機械化**：命名規約の検査、テンプレートの複写、README 収録一覧への行追加、`plugin.json` の version バンプは `scripts/new_entry.py` が担う。
  - 置き場所と粒度の判断、description と本文の執筆だけがモデルの仕事である。

## 手順

1. リポジトリを取得する。
   - 未クローンなら `git clone https://github.com/Tkg-tamagohan/devin-plugins.git`、既存のクローンがあれば `git fetch` して最新の main に追従する。
2. `guidelines.md` の判断表で置き場所を決める（AGENTS.md の節、`rules/<name>.md`、`skills/<name>/SKILL.md` のいずれかになる）。
3. `rg` でキーワードを検索して既存の内容と重複しないか確認し、同じ状況を扱うファイルがあれば新規作成ではなくそのファイルの修正か統合にする。
4. `scripts/new_entry.py` でファイルと記帳を生成する。
   - `python3 skills/plugin-authoring/scripts/new_entry.py rule <name> --summary "<README の収録一覧に載せる一文>"` を実行する。
   - skill の場合は `skill` を指定する。
   - 命名規約と重複の検査、テンプレート(`rule-template.md`、`skill-template.md`)の複写、README 収録一覧への行追加、`plugin.json` の version バンプ(追加なのでパッチ)までをスクリプトが行う。
   - 生成されたファイルの description と本文はモデルが埋める。
5. 作成した内容を `guidelines.md` のチェックリストで点検する。
   - 特に description は、モデルが読むかどうかを決める唯一の材料なので、読み込むべき状況が一文で特定できることを確認する。
   - 機械化できる項目は `scripts/check_plugin.py` の実行でも確認できる。
   - description の状況特定など判断が要る項目は引き続き目視で確認する。
6. 追加や修正だけの変更では手順 4 の生成時に version が上がっている。
   - 移動、改名、削除を含む変更では、PR を出す前に `new_entry.py bump` で差分から規約どおりの水準(マイナー)へ補正する。
7. `README.md` の収録一覧は手順 4 で `--summary` の文による行が追加済みである。
   - 構成の説明に影響する変更(ディレクトリ追加、ファイルの改名など)は引き続き手で追随させる。
8. ブランチを切って(例: `devin/$(date +%s)-<slug>`)コミットし、PR を作成する。
   - PR 本文には置き場所と粒度の判断理由を書く。
   - PR では CI の `plugin-checks` がテストと構造チェックを実行する。
9. PR 作成後、マージとプラグインの再インデックスが済むまで他のセッションから使えないことをユーザーへ伝える。

## 既存のルールやスキルを見直すとき

統合や分離を判断するときも `guidelines.md` の基準に従う。
改名や移動を含む変更では、README、他ファイルからの参照(`shared-skills:<name>` の記述など)、`plugin.json` のバージョンを同じ PR で更新する。
