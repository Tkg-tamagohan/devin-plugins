# 上流 yomiyasu v3.0.0 への移植計画

状態: 進行中

`skills/japanese-tech-writing/` が vendored している上流 nanaism/yomiyasu の移植版を、現行ベースの v1.1.1 から v3.0.0 へ更新するための計画である。
上流 v1.1.1 から v3.0.0 までの CHANGELOG 全項目、SKILL.md、scripts/ 配下、references/ 配下の差分を分析し、移植対象と採否を定める。
実装は本計画の要協議事項が確定してから、フェーズごとの独立した PR で行う。

## 前提と環境

- 移植先は devin-plugins リポジトリの `skills/japanese-tech-writing/`(shared-skills プラグインの一部)である。
- 上流は github.com/nanaism/yomiyasu である。
- 分析対象は v1.1.1..v3.0.0 の差分である。
- v3.0.0 は 2026-11-11 リリースである。
- 現行移植版は上流 v1.1.1 を基に、独自規範との衝突を避ける改変を加えた選択的移植である(決定記録 Y-01〜Y-13)。
- 検証は `scripts/test_slop_lint.py`、`scripts/test_slop_diff.py`、`scripts/test_catalog_consistency.py`、`scripts/test_new_entry.py`、`check_plugin.py`、および全 Markdown 一括 lint(`--strict`)で行う。
- CI の plugin-checks.yml が同じ一式を実行する。

## 採用方針

- Y-01〜Y-13 の選択的移植の枠組みを継続する。
- 上流の改善のうち移植版の規範と衝突しないものを採用し、独自規範を上書きする変更は要協議事項として扱う。
- 各フェーズは独立した PR とし、ブランチ名は `devin/$(date +%s)-yomiyasu-v3-p<N>` とする。
- lint の規則追加は、対応する `references/lists/` の一覧や `slop-catalog.md` の行を伴う場合にセットで移植する。
- 上流 v3.0.0 の SKILL.md 全面書き直し(46,311字から15,656字)は丸ごと採用しない。
- 採用した規則に対応する主題だけを現行 SKILL.md の構成に沿って取り込む方針を推奨する(要協議 7)。
- `yomiyasu_check.py`、`yomiyasu_hook.py`、`.codex-plugin/` などの上流パッケージング資材は、Devin プラグインの構造と合わないため原則対象外とし、採否は要協議事項で確定する。

## 構成

### 変更する既存ファイル(予定)

- `skills/japanese-tech-writing/scripts/slop_lint.py` は規則追加、出力形式、入力処理を更新する。
- `skills/japanese-tech-writing/scripts/slop_diff.py` は差分検査を拡張する(範囲は要協議 6 の確定に従う)。
- `skills/japanese-tech-writing/scripts/markdown_visibility.py` は上流 v3.0.0 相当へ同期する。
- `skills/japanese-tech-writing/scripts/markdown_bold.py` は上流の太字検査との整合を確認する。
- `skills/japanese-tech-writing/references/slop-catalog.md` は採用規則に対応する行を追補する。
- `skills/japanese-tech-writing/references/slop-lint-usage.md` は CLI 仕様の変更に追従する。
- `skills/japanese-tech-writing/SKILL.md` は採用規則に対応する節を更新する。
- `skills/japanese-tech-writing/scripts/test_slop_lint.py`、`test_slop_diff.py`、`test_catalog_consistency.py` は検出の追加と形式変更に追従する。

### 新規に入れるファイル(候補)

- `references/lists/*.txt` は、`katakana-terms`、`thin-evaluation`、`renyo-nouns` など、採用する規則が参照する一覧である。
- `references/calques.md` は、calque 規則を採用する場合の対応表である。
- `.yomiyasu-words/` の既定ファイルは、語彙リスト機構を採用する場合に置く(要協議 2)。

## 移植版で維持する独自規範

- `one_sentence_per_line`、`nakaguro_parallel`、`noun_chain`、`abstract_noun` の各検査は移植版独自の規範であり、上流変更で上書きしない。
- 「」で囲まれた言及(禁止表現の例示)を語彙と構文の検査から除外する扱いを維持する。
- `excess_bold` と `excess_list` の info 降格と独自の指摘文を維持する。
- 絵文字検査は現行 `EMOJI_PATTERN` を維持する(Y-06、Y-15 で継続確定)。
- SKILL.md の独自構成(k16shikano 系の章立て)を維持し、上流 SKILL.md の構成は全面的に採用しない。
- 文書種別の区別を行わない運用を基本とする。
- `--doc-type` の導入は要協議 4 で確定する。

## 上流差分の整理

### 現行移植版と上流 v3.0.0 の規模比較

- `slop_lint.py` は 1,284行で規則は19件である。
- 上流 `yomiyasu_lint.py` は 6,391行で規則は31件である。
- 上流にのみある規則は `ai_phrase`、`calque`、`cleft_list_ending`、`dialogue_period`、`heading_colon`、`instruction_residue`、`katakana_term`、`metaphor_label`、`narrative_density`、`pause_comma`、`project_term`、`renyo_noun`、`slide_comma`、`thin_evaluation`、`translated_term` の15件である。
- `slop_diff.py` は 483行で文末と語調の差分を扱う。
- 上流 `yomiyasu_diff.py` は 11,548行で、意味リスク、文体の硬化、勢い、許可や能力や保証の言い方比較などを扱う。
- `markdown_visibility.py` は 719行である。
- 上流は 1,429行で、語彙リスト機構(`.yomiyasu-words/`)と入力パス安全策(`input_path_problem`)が追加されている。
- 上流には `yomiyasu_check.py`(5,639行)と `yomiyasu_hook.py`(944行)があり、検査実行の記録と提出前照合の仕組みを提供する。
- 移植版には対応するものがない。

### v1.1.2(CHANGELOG 対象外、git 差分で確認)

- SKILL.md に文の種類(事実、意見と評価、依頼と決まり、例えと比喩、皮肉や冗談や反語、仮定と予測、引用と伝聞)の記録と照合が追加された。
- 比喩の含みの保持、仮置きの残り、定型導入の拡充も追加された。
- `yomiyasu_lint.py` は語彙と比喩動詞の走査を `_vocabulary_findings` へ整理した。
- 「時間を溶かす」の活用形、「ぜひ」締め、「に他なりません」の拡張(「ほかなりません」を含む)を修正した。
- `yomiyasu_diff.py` に文の種類の印(`type_marks`、`_type_changes`)による文種変化の検出が追加された。
- `slop-catalog.md` と `gemini-syntax.md` に微修正がある。

### v2.0.0〜v2.0.2

- `yomiyasu_check.py` を新設した。
- `run`/`verify`/`start`/`end`/`export` で lint と diff をまとめて実行し、`.yomiyasu/` に原稿と資料と最終稿のハッシュと検査結果を記録する。
- `--stdin`、`--replay`、`--source`、`--run-id`、`--since` などのオプションがある。
- `yomiyasu_hook.py` を新設した(Claude Code のフック連携用)。
- lint の JSON 形式が非互換で変更された。
- `score`/`is_clean` から `rule_penalty_score`/`no_rule_findings` へ改名し、`format`、`format_version`(2)、`tool_version`、`candidate_count`、`counts`、`not_judged`、`context`、`metrics` を追加した。
- 点数式も規則の重みを地の文 1,000字あたりに正規化する方式へ変わった。
- lint の通常出力から点数見出しと参考値を除き、終了コードを再定義した。
- 終了コード 1 は `--strict`/`--fail-on` 該当時、内部エラーは 3 である。
- lint の入力処理を整理した。
- `-` は標準入力、BOM 除去、改行の LF 統一、空パスは終了コード 2 とした。
- `<details>` 内の箇条書きを `excess_list` の比率から除外する。
- `instruction_residue`(info)と `meta_filler` の「過言」型(warn)を `--doc-type` なしでも出すようにした。
- diff を大規模拡張した。
- `meaning_risks`(数値、否定、入れ替え、文種、引用、確度、状態、約束など)、`full_diff`、`stiffness`、`tone`、`feeling`、`hedges`、`immutable`、`politeness`、`register`、`modality` を追加した。
- `--fail-on=meaning-risk` を新設した。
- 引数の検証を厳格化し、使い方の誤りは終了コード 2 とした。
- references を再編した。
- `doc-types/`(13件)、`lists/`(8件の語彙一覧)、`fact-recovery.md`、`fact-recovery-details.md`、`persona.md`、`rephrase-test.md`、`review-points.md`、`audience.md` を追加した。
- v2.0.1 は diff の照合を高速化した(出力不変)。
- v2.0.2 は太字検査の高速化、状態フォルダの `~` 展開、プラグイン設定の整理を行った。
- description を「名前を出して頼んだときだけ使う」形に変えた。

### v2.1.x

- diff に `modality`/`modality_review`、`meaning_risks` の kind 追加(choice、causality、number_qualifier)、見出し変化の structure 候補を追加した。
- lint に `cleft_list_ending`(info)を追加した。
- 「真理値」「装置」、瞬間に、版+出版物語、文末飾りスキップ、比喩「効く」副詞なしの修正、CR 改行 stdin 対応を行った。
- check に候補一覧の行を追加した。
- 確度の doc_type 別カウント(7種類)と、書き手に確かめたい点の上限3点を導入した。
- v2.1.2 と v2.1.3 は Windows 対応(CRLF、ロックファイル、権限、CI)である。

### v2.2.x

- 直訳語印システムを導入した。
- `calque` 型1〜3、`metaphor_label`、`say_hedge`、`thin_evaluation`、`katakana_term`、`dialogue_period`、`narrative_density`、`copy_comma_noun`、`bare_verb_chain`、`project_term`(いずれも主に info)を追加した。
- 文書種類 `script` を追加した。
- `.yomiyasu-words/`(`allow.txt`、`flag.txt`)の語彙リスト機構を導入した。
- `references/calques.md` と `references/review-points.md` を新設した。
- v2.2.1 は calque の入口と出口の検出を拡張し、check に `kept_marks` を追加した。
- v2.2.2 は diff の性能を修正した(出力不変)。

### v2.3.0〜v2.4.0

- `renyo_noun`(info)を追加し、`references/lists/renyo-nouns.txt`(48語)を同梱した。
- `calque` 型4(漢字1字名詞の「版」「印」「頭」、info)を追加した。
- `slide_comma`(`--doc-type slides` のみ info)を追加した。
- diff に `added_actors` 節と `--material` オプションを追加し、消えた文組み合わせの処理を高速化した。
- 出力言葉を統一し、自己回帰 lint を修正した。

### v2.5.0

- `ai_phrase`(info、7形)を追加した。
- `calque` 型1副詞の誤検出を修正(20語の一覧)し、型3の句を3つ追加した。
- 比喩「効く」の検出を改善した(ソフトウェア語窓の除外修正、「効くのが」型の追加)。
- `pause_comma` を修正した(店長形免除、短い目的語「を、」の検出)。
- diff/check に `heading_shapes` と `comma_increase` の節を追加した。
- SKILL.md に規則を追加した(コードやシステム文書の擬人化、否定で終わる定義文、漢語名詞の動作省略、依頼指定の見出し保持、読点を足さない決まり)。
- 「実行するコマンド」の節(python3→python→py -3 のフォールバック)、`allowed-tools` frontmatter、「ファイルに保存して `run --final`」の基本形を導入した。
- `slop-catalog.md` 第10章「2026年に見つかった言い回し」、`audience.md` 第11章、`domains/tech.md` 第2章を追加した。

### v3.0.0

- SKILL.md を全面書き直した(46,311字から15,656字)。
- 節名の変更と Step 1〜5 の再編を含む互換性のない変更である。
- 内容は gist 案と漢語対応のみである。
- 漢字と仮名が混在する語の境界ルールと、直訳語、漢語の詰まり、連用形名詞の扱いを追加した。
- `flag.txt` に「使わない語<TAB>使う語」の対応を書けるようにした。
- `flag-patterns.txt`(1行「名前<TAB>正規表現」、500個、重さ512上限)を新設した。
- lint/diff/check に入力パス安全策(`input_path_problem`)を追加し、作業フォルダ外やドットを含むパスを読まないようにした。
- check は `.yomiyasu/inputs/` の写し経由で検査する。
- 5つのスクリプトに型注釈と pathlib 移行を行い、`# -*- coding: utf-8 -*-` ヘッダで Python 3.9 に対応した。
- references の変更(calques.md、review-points.md など)と `--help` の更新を行った。

## フェーズ別タスク

### Phase 1: 構造解析基盤の同期

- [ ] `markdown_visibility.py` を上流 v3.0.0 相当へ更新する。
- [ ] `.yomiyasu-words/` 機構を含めるかは要協議 2 の確定に従う。
- [ ] lint/diff の入力処理を上流に揃える(BOM/CRLF の正規化、標準入力「-」、空パスの扱い、`input_path_problem`)。
- 受け入れ条件: 既存テストが通り、検出結果が変わらないこと(構造解析の等価性を確認する)。

### Phase 2: lint の info 系規則追加

- [ ] `ai_phrase`、`renyo_noun`、`project_term`、`thin_evaluation`、`katakana_term`、`metaphor_label`、`say_hedge`、`narrative_density`、`dialogue_period`、`copy_comma_noun`、`bare_verb_chain`、`cleft_list_ending`、`instruction_residue`、`pause_comma` を移植する。
- [ ] `references/lists/` の対応する一覧を同梱する。
- [ ] `slide_comma` は `--doc-type` 導入の確定(要協議 4)に連動する。
- 受け入れ条件: 各規則の検出と非検出のテストを追加し、info として出ること。

### Phase 3: lint の calque 系規則追加

- [ ] `calque` 型1〜4 と関連修正を移植する。
- [ ] 型4 と doc-type 依存の扱いは要協議 5 の確定に従う。
- [ ] `translated_term` と `heading_colon` の採否は Y-08 の再確認結果に従う。
- [ ] `references/calques.md` を同梱する。
- 受け入れ条件: calque 各型の検出テストと、allow/flag 語彙リストとの整合。

### Phase 4: lint の出力形式と CLI の更新

- [ ] JSON 形式を `format_version` 2 相当へ更新するかを要協議 3 の確定に従って実施する。
- [ ] `--doc-type`/`--reader` の導入可否は要協議 4 の確定に従う。
- [ ] 終了コード、`--strict`/`--fail-on`、通常出力の形式を更新する。
- 受け入れ条件: `test_slop_lint.py`、`slop-lint-usage.md`、CI の一括 lint が整合する。

### Phase 5: slop_diff の拡張

- [ ] v1.1.2 の文の種類の印(`type_marks` 系)を移植する。
- [ ] `meaning_risks`、`stiffness`、`tone`、`heading_shapes`、`comma_increase`、`added_actors` などの移植範囲は要協議 6 の確定に従う。
- 受け入れ条件: `test_slop_diff.py` の拡充と、既存の endings 系出力の非回帰。

### Phase 6: 文書の更新

- [ ] `slop-catalog.md` に採用規則に対応する行を追補する(Y-05/Y-11 の部分導入方針を継続)。
- [ ] SKILL.md に採用規則の主題を反映する(全面置換はせず、要協議 7 の確定に従う)。
- [ ] `slop-lint-usage.md` を CLI 仕様の変更に合わせて更新する。
- 受け入れ条件: `test_catalog_consistency.py` が通り、全 Markdown 一括 lint `--strict` が通る。

### 対象外(現時点)

- `yomiyasu_check.py`、`yomiyasu_hook.py`、`.codex-plugin/`、上流のベンチマークとコーパス用スクリプト、検証コーパス、記事、ドメイン別ガイドは、要協議事項で覆らない限り移植しない。

## 引き継ぎ手順

- 実装は本計画の要協議事項が確定したあと、別セッションでフェーズごとに行う。
- 各フェーズの冒頭で対応する上流タグの差分を再確認し、計画書との差異があれば計画書を先に更新する。
- 決定が確定した項目は `docs/decision-records.md` に Y-17 以降で追記する。

## 要協議事項(未確定)

1. **yomiyasu_check.py と yomiyasu_hook.py の移植可否**
   - a. 見送る(推奨)。
   - 状態記録と verify の仕組みは上流の対話的な推敲フロー(SKILL.md の Step 3〜5)を前提としており、Devin スキルの運用(SKILL.md の指示に従い lint/diff を直接実行)とは目的が異なる。
   - フックは Claude Code 固有で Devin には適用できない。
   - b. check.py のみ移植。
   - 検査実行の記録と verify を取り込みたい場合。
   - c. 両方移植。
   - 上流の検査ワークフローを再現する場合。

2. **.yomiyasu-words/(allow.txt、flag.txt、flag-patterns.txt)の語彙リスト機構**
   - a. markdown_visibility.py の同期に伴い一体で取り込む(推奨)。
   - 機構が同ファイル内に組み込まれており、分離すると保守が複雑になる。
   - 既定ファイルは同梱し、文書への記載は最小限にする。
   - b. 見送る。
   - プロジェクト固有語の誤検出需要が確認できてから導入する。

3. **lint の JSON 形式と通常出力の非互換変更への追従**
   - a. 上流 v2 形式へ更新する(推奨)。
   - `format_version` で形式を判別でき、CI は `--strict` のみを使い JSON 出力に依存しない。
   - `score` の廃止と終了コードの再定義は上流と揃える。
   - b. 現行形式を維持。
   - `score` と `[PASS]`/`[NOTICE]` 出力を残し、上流形式は採用しない。

4. **--doc-type/--reader オプションの導入**
   - a. 導入しない(推奨)。
   - 移植版 SKILL.md は文書種別を区別する運用を持たず、種別ごとの規則差分の効果が未検証。
   - `calque` 型4 と `slide_comma` は doc-type 依存のため、導入まで保留するか info のみの常時検出とする。
   - b. 導入する。
   - 上流と同じ文書種別体系を移植版にも持ち込む。

5. **calque 型4、translated_term、heading_colon の採否**
   - a. Y-08 の見送りを継続する(推奨)。
   - 「版」「印」「頭」の calque 型4、`translated_term`、`heading_colon` は採用しない。
   - `calque` 型1〜3 のみ採用する。
   - b. 再検討して採用。
   - 上流の検出が改善されているため、誤検出率を確認のうえ採用する。

6. **slop_diff の拡張範囲**
   - a. 段階的に移植する(推奨)。
   - まず v1.1.2 の文の種類の印と軽量な構造節(見出し、読点増加)を移植し、`meaning_risks` 全体系は別計画とする。
   - b. 上流 diff を全面同期。
   - `yomiyasu_diff.py` を基盤ごと移植し、`slop_diff.py` を置き換える。
- 規模が大きいため独立計画を推奨する。
   - c. 現状維持。
   - endings/register 系の差分のみを継続する。

7. **SKILL.md の更新方針**
   - a. 部分反映(推奨)。
   - 採用した規則に対応する主題だけを現行 SKILL.md の構成に沿って取り込み、上流 v3.0.0 の全面書き直しは採用しない(Y-01/Y-12 の方針継続)。
   - b. 上流 SKILL.md の構成を取り込む。
   - Step 1〜5 と出力フォーマットを移植版にも適用し、独自規範との整合調整が必要になる。

8. **references/ 新規ファイルの同梱範囲**
   - a. 採用規則が依存するもののみ同梱(推奨)。
   - `calques.md` は calque 採用時、`lists/*.txt` は対応規則採用時に置く。
   - `fact-recovery`、`persona`、`rephrase-test`、`audience`、`doc-types` は見送る。
   - b. 参照文書を広く同梱。
   - 上流の references をほぼそのまま取り込む。
