# yomiyasu v1.0.9 から v1.1.1 の取り込み実装計画

上流 [nanaism/yomiyasu](https://github.com/nanaism/yomiyasu) の v1.0.8 から v1.1.1 までの更新を、スキル `shared-skills:japanese-tech-writing` へ取り込む計画。
確定した判断は `docs/decision-records.md` の Y-07 以降に記録した。

## 前提と環境

- 変更対象は `skills/japanese-tech-writing/` 配下のリンター、語彙カタログ、SKILL.md。
- v1.0.9 はパッケージングと README のみの更新で、取り込むコード差分は v1.1.0 と v1.1.1 にある。
- 上流差分の確認元は v1.1.1 タグに対する `v1.0.8..v1.1.1` の diff である。
- 全作業は Python 3 標準ライブラリのみで完結し、外部サービスや秘密情報は要らない。
- 検証はリポジトリの CI(plugin-checks)と同じコマンドをローカルで実行する。

## 採用方針

ユーザーの決定により、差分のうち検出強化と基盤同期を採用し、直訳語検査と見出しコロン検査は見送る(決定記録 Y-07 から Y-13)。
上流の SKILL.md の推敲指針編集は制限導入とし、カタログは前回と同じ部分導入とする。

## 構成

### 変更する既存ファイル

- `skills/japanese-tech-writing/scripts/markdown_visibility.py`: v1.1.1 へ再ベンダリングする。
  性能改善と、表ヘッダ行を持つブロックの除去で先頭の等価要素を誤って消し得た `blocks.remove(current)` の `blocks.pop()` への修正を含む。
- `skills/japanese-tech-writing/scripts/slop_diff.py`: `bare_end` の書き直し、`sys.stdout.reconfigure(encoding="utf-8")`、`read_text` ヘルパを移植する。
- `skills/japanese-tech-writing/scripts/slop_lint.py`: 標準入出力の UTF-8 化、新規検出テーブル、ダッシュ検査の3ルール化、否定構文の強化、リテラル絞り込み機械を移植する。
- `skills/japanese-tech-writing/scripts/test_slop_lint.py`、`test_slop_diff.py`、`test_catalog_consistency.py`
- `skills/japanese-tech-writing/references/slop-catalog.md`
- `skills/japanese-tech-writing/SKILL.md`

### 新規に入れるファイル

なし(上流の新規検出は既存 `slop_lint.py` への移植で完結する)。

## 移植版で維持する独自規範

上流との差異として以下を保つ。

- `one_sentence_per_line`、`nakaguro_parallel`、`noun_chain`、`abstract_noun` の各検査。
- 「」で囲まれた言及を語彙と構文の検査対象から外す除外。
- `excess_bold` と `excess_list` の info への降格と、移植版独自の指摘文。

## フェーズ別タスク

各フェーズは独立した PR とする。
プラグイン中身の修正だけを含む PR はパッチバンプとし、PR 前に `new_entry.py bump` で差分から水準を確定する。

### Phase 1: 基盤同期

- [ ] `markdown_visibility.py` を v1.1.1 へ再ベンダリングし、出典ヘッダを維持する。
- [ ] `slop_diff.py` に `bare_end` の書き直し、stdout の UTF-8 再構成、`read_text` ヘルパを移植する。
- [ ] `slop_lint.py` に stdin/stdout の UTF-8 再構成と、stdin 読み取り時の UnicodeDecodeError を終了コード 2 で扱う処理を移植する。
- [ ] `test_slop_lint.py` と `test_slop_diff.py` に上流 `test_stdio_encoding.py` 相当のケースを移植する。

受け入れ条件として、既存テストがすべて通り、検出結果に変化がないこととする。

### Phase 2: 検出強化(語彙パターンとフィラー、info 系、性能機械)

- [ ] `SLOP_WORD_PATTERNS` を導入し、「ゲート」「閉包」「台帳」「〜のOS」「本質を突く」を除外条件つきで検出する。
  「意思決定OS」は `SLOP_WORDS` からパターンへ移す。
- [ ] `FILLER_PATTERNS` を上流の追加分で拡充し、残してよい条件を補足する `FILLER_NOTES` を導入する。
- [ ] info 系の `INFO_SENTENCE_PATTERNS`、`short_mochiron`(問い文脈の免除判定一式を含む)、`fragment_run`、`bold_label_list`、`short_summary_heading` を配線する。
- [ ] リテラル絞り込み機械(`_PATTERN_LITERAL_HINTS`、`_narrowed_document_rows`、`_may_match_literals`)を配線する。
- [ ] `test_slop_lint.py` に上流 `test_v111_*` 系と `test_dash_and_vocabulary.py` 相当の検出と非検出のケースを移植する。

受け入れ条件として、新ルールの検出と非対象例の非検出を示すテストが通り、既存テストがすべて通ることとする。

### Phase 3: ダッシュ3ルール化と否定構文強化

- [ ] `dash_prohibited` を上流の `_dash_finding` 一式へ置き換え、`dash_list_ending`、`dash_insertion`、`dash_decoration` の3ルールと引用や区間、出典、図罫線のマスク、1文書3件上限を導入する。
- [ ] `DASH_PATTERN` を廃止し、見出しと本文の双方で同じ `_dash_finding` を使う。
- [ ] 否定構文として `_extra_negation_line_numbers`、`_NEGATION_EXTRA`、`_NEGATION_JANAI`、`_NEGATION_ALSO` の免除、`negative_parallelism_density` を移植する。
- [ ] `test_catalog_consistency.py` の機械読み取り契約を更新し、`DASH_PATTERN` 廃止と新テーブル(`SLOP_WORD_PATTERNS`、INFO 系、拡充したフィラー)を方向2の担保へ追加する。

受け入れ条件として、上流 `test_v111_dash_regressions.py` と `test_v111_filler_negation_regressions.py` 相当のケースの移植と通過、および全 Markdown 一括リントの通過とする。

### Phase 4: カタログの部分追従

- [ ] lint 採用分に対応する行として、節 5 に `ゲート` `台帳` `思考のOS`、節 6 に新規フィラーと定型導入、数の宣言、チャット応答の名残、言い直しの締めの行を追加する。
- [ ] 上流の新行のうち lint 非対応で本スキルの規範と整合する参照行(「逃がす」「粒度」「余白」「軸」「言語化」「落とし込む」「紐解く」「これは強い」など)と、上流節 7「硬い漢語と決まり文句」を検討して採用し、免除が必要な項目は `EXEMPTIONS` に理由つきで登録する。
- [ ] 見送った検出(「版」「回帰」)に対応する上流の行と、既存行と重複する行は入れない。

受け入れ条件として、`test_catalog_consistency.py` が通ることとする。

### Phase 5: SKILL.md の制限導入

- [ ] 採用した lint とカタログの変更に対応する主題だけを節ごとに反映する。
  対象候補は、ダッシュ記号の例外(区間、出典、図罫線)の明確化、否定構文の「でもある」の保持と「どちらでもない」の短い受け、数の宣言と言い直しの締め、文頭の「もちろん、」の短い文、定型導入とチャット応答の名残、出典のない「〜という声」、確認手順の「ゲート」と記録の「台帳」、評価だけの短い文の連打とする。
- [ ] 「Xとは:Y」見出しと議事録ラベルのコロンは、見出しコロン検査の見送りに伴い対象外とする。
- [ ] 節ごとの採否を本書に記録する。

受け入れ条件として、全 Markdown の `--strict` 一括リントが通ることとする。

## 引き継ぎ手順

- 現在地は本書のチェックリストと、devin-plugins でマージ済みの該当 PR から確認する。
- ブランチは `devin/$(date +%s)-yomiyasu-v111-p<N>` とし、フェーズごとに PR を分ける。
- ローカル検証の一式は `test_slop_lint.py`、`test_catalog_consistency.py`、`test_slop_diff.py`、`test_new_entry.py`、`check_plugin.py`、全 Markdown の一括リント(`--strict`)である。
- 上流ファイルの差分確認は `git clone` した yomiyasu リポジトリで行う。
- ライセンス関係の新規同梱物が出た場合は `rules/library-license` の手順に従う。

## 要協議(全件確定済み)

論点はすべてユーザー承認により確定し、`docs/decision-records.md` の Y-07 から Y-13 へ移した。
確定内容は以下の通り。

- A: 新規 warn 検出は `SLOP_WORD_PATTERNS` のみ採用とし、version 意味の「版」と regression 意味の「回帰」の検査、「Xとは:Y」見出しの検査は見送る。
- B: ダッシュ検査は上流の3ルール化とマスク機構へ置き換える。
- C: 否定構文の強化を採用する。
- D: info 系文パターンの新設を採用する。
- E: フィラー拡充を採用する。
- F: カタログは部分導入とし、見送った検出に対応する行は入れない。
- G: SKILL.md は制限導入とする。
- H: リテラル絞り込み性能機械を採用する。
