# yomiyasu 更新の取り込み実装計画

上流 [nanaism/yomiyasu](https://github.com/nanaism/yomiyasu) の v1.0.8 までの更新を、スキル `shared-skills:japanese-tech-writing` へ取り込む計画。
確定した判断は `docs/decision-records.md` へ記録し、論点 A〜E はすべて推奨案で確定済みである。

## 前提と環境

- 変更対象は `skills/japanese-tech-writing/` 配下のリンター、語彙カタログ、SKILL.md。
- 取り込み元は MIT License で、条文は `skills/japanese-tech-writing/LICENSE-yomiyasu` に同梱済み。
- 前回の取り込みは 2026-10-01 時点の上流であり、その後 v1.0.8 まで更新が進んだ。
- 全作業は Linux VM と Python 3 標準ライブラリのみで完結し、外部サービスや秘密情報は要らない。
- 検証はリポジトリの CI(plugin-checks)と同じコマンドをローカルで実行する。

## 採用方針

ユーザーの決定により全改善項目を採用する(決定記録 Y-01)。
上流の SKILL.md 新規節、検証コーパス、記事、ドメイン別ガイドは対象外とし、いずれも本スキルの規範と重複するか用途が合わないためである。

## 構成

### 新規に入れるファイル

- `skills/japanese-tech-writing/scripts/markdown_visibility.py`: 上流の同名ファイルをベンダリングする共有モジュールで、Markdown のブロック種別や引用深度、参照リンク定義、インライン保護範囲の解析を担う。
- `skills/japanese-tech-writing/scripts/slop_diff.py`: 上流 `yomiyasu_diff.py` を改名してベンダリングする差分検査ツールで、原文と推敲文を比較して文末の種類の増減、消えた語、構造変化、文末の立場の混在、太字の非表示を候補として出す。
- `skills/japanese-tech-writing/scripts/markdown_bold.py`: 上流の太字判定機械(`_bold_*` 系)を共有モジュールとして切り出したもので、`slop_lint.py` と `slop_diff.py` の双方から利用して上流にある複製を解消する。
- `skills/japanese-tech-writing/scripts/test_slop_diff.py`: 差分検査ツールの回帰テスト。

ベンダリングする各ファイルは、既存 `slop_lint.py` と同じく先頭の docstring に出典とライセンスを記す。

### 変更する既存ファイル

- `skills/japanese-tech-writing/scripts/slop_lint.py`
- `skills/japanese-tech-writing/scripts/test_slop_lint.py`
- `skills/japanese-tech-writing/references/slop-catalog.md`
- `skills/japanese-tech-writing/SKILL.md`

## フェーズ別タスク

各フェーズは独立した PR とする。
プラグイン中身の追加と修正のみの PR はパッチバンプ、移動や改名を含む PR はマイナーバンプとし、PR 前に `new_entry.py bump` で差分から水準を確定する。

### Phase 1: 比喩動詞パターンの拡充と誤検出の修正

- [x] `METAPHOR_VERB_PATTERNS` に `Xが壊れる`、`踏み込む`、`引き返す`、`添える`、`収斂`(文境界をまたがない上限つき)の 5 件を追加する。
- [x] `Xが壊れる` と `静かに壊れる` が同一動詞に二重反応しないよう上流の重複排除を移植する。
- [x] 「効く」の語尾を `効[かきくけいた]` へ広げる。
- [x] 絵文字検査の対象を生の行から可視テキストへ変え、インラインコードと URL 内の絵文字を誤検出から除く。
- [x] 文末連続の判定を段落ブロック内に限定する方式へ変更する。
- [x] `negative_parallelism` を上流の正確な判定へ置き換える。

受け入れ条件として、新パターンの検出と非対象例の非検出を示すテストを `test_slop_lint.py` へ追加し、既存テストが全て通ることとする。

### Phase 2: 語彙カタログの部分更新

- [ ] 冒頭に、一覧を機械的な置換表として使わず、意味の同一が確定できる場合だけ使う旨を追記する。
- [ ] 定着した慣用句は残す条件を節 1 へ追記する。
- [ ] 欠落している行として、ルールを指す「契約」のような役割の大げさ呼称と、「仕組み」「境界」のような指す内容が曖昧な名詞の 2 行を追加する。
- [ ] 既存行に含み保持の注意を反映し、「壊れる」は同じ広さの語へ、「地味に効く」は目立たなさの含みを残す向きとする。

受け入れ条件として、カタログとリンターの整合テストが通ることとする。
追従範囲は部分導入で確定しており、上流の詳細調への全面置換は行わない(決定記録 Y-05)。
対象ファイルは `.sloplintignore` で文書リントから恒久除外されている。

### Phase 3: 差分検査ツールの導入

- [ ] `markdown_visibility.py` と `slop_diff.py` をベンダリングし、出典ヘッダを記す。
- [ ] `slop_diff.py` の入出力(原文ファイルと推敲ファイルの 2 引数、`--json` と `--endings` オプション)を固定する回帰テスト `test_slop_diff.py` を新設する。
- [ ] `.github/workflows/plugin-checks.yml` の回帰テストステップと、本書「引き継ぎ手順」の検証一覧へ `test_slop_diff.py` を加える。
- [ ] SKILL.md の「既存文章の解体と再構築」節に推敲後の差分検査の手順を追記し、実行例を「機械検査」節の既存手順に倣う形で示す。

受け入れ条件として、依頼文を動作文へ書き換えたサンプルで文末種別のずれが検出されること、CI が通ることとする。

### Phase 4: 太字非表示の検査

- [ ] 上流の太字判定機械を `markdown_bold.py` へ切り出し、`slop_lint.py` へ新ルール `bold_not_rendered`(error)として配線する。
- [ ] 上流 `test_bold_multiline.py` の主要ケースを `test_slop_lint.py` へ移植し、複数行にまたがる正常な太字、ブロック境界またぎ、かっこの内外の対象を含める。

受け入れ条件として、「`**「例」**`」の形が修正案つきで検出され、正常な太字は無指摘であることとする。

### Phase 5: slop_lint 本体の構造解析への移行

- [ ] `lint_text` の行走査を `analyze_markdown` の結果へ置き換える。
- [ ] 独自検査の一文一行、中黒並列、ダッシュ、名詞連結、言及除外、フロントマター扱いを、新しい解析結果の上で等価動作に移植する。
- [ ] 参照リンク定義、setext 見出し、HTML ブロック、入れ子の引用で期待する扱いをテストで固定する。

受け入れ条件として、既存テスト全件の通過に加え、リポジトリ全 Markdown の一括リント結果が移行前と一致するか改善していることとする。

### Phase 6: Unicode 派生の絵文字検査機械(不採用)

上流の Unicode 派生絵文字表は採用せず、現行 `EMOJI_PATTERN` を維持する(決定記録 Y-06)。
コードや URL 内の絵文字の誤検出は Phase 1 の可視テキスト化で対処済みのため、本フェーズは実施しない。

## 引き継ぎ手順

- 現在地は本書のチェックリストと、devin-plugins でマージ済みの該当 PR から確認する。
- ブランチは `devin/$(date +%s)-yomiyasu-port-p<N>` とし、フェーズごとに PR を分ける。
- ローカル検証の一式は `test_slop_lint.py`、`test_catalog_consistency.py`、`test_new_entry.py`、`check_plugin.py`(`--version-base origin/main`、事前に `git fetch origin main`)、全 Markdown の一括リント(`--strict`)である。
- 上流ファイルの差分確認は `git clone` した yomiyasu リポジトリで行う。
- ライセンス関係の新規同梱物が出た場合は `rules/library-license` の手順に従う。

## 要協議(全件確定済み)

論点 A〜E はすべてユーザー承認により推奨案で確定し、`docs/decision-records.md` の Y-02〜Y-06 へ移した。
確定内容は以下の通り。

- A: `docs/` を新設してリポジトリで管理する(本 PR のマージをもって採用)。
- B: Phase 5 の本体移行を実施する。
- C: 文末連続は段落内のみに限定する。
- D: カタログは部分導入とし、上流の詳細調への全面置換は行わない。
- E: 絵文字検査は現行パターンを維持し、可視テキスト化のみ対応する。
