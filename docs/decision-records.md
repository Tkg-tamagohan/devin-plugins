# 決定記録

このリポジトリの実装計画（`docs/implementation-plan-*.md`）に関する確定済みの判断を記録する。
未決の項目は計画書の「要協議」節で管理し、確定したものから順に本表へ移す。

| ID | 項目 | 決定内容 |
|---|---|---|
| Y-01 | yomiyasu 更新の採用範囲 | 全改善項目を採用する。対象は比喩動詞パターン拡充、誤検出修正、差分検査ツール、太字非表示検査、構造解析への移行、語彙カタログ更新。上流の SKILL.md 新規節、検証コーパス、記事、ドメイン別ガイドは対象外。 |
| Y-02 | 計画書と決定記録の置き場所 | `docs/` を新設してリポジトリで管理する。yomiyasu 取り込み計画が配置先の初例であり、本 PR のマージをもって採用とする。 |
| Y-03 | Phase 5 の本体移行 | 実施する。`slop_lint.py` の行走査を `markdown_visibility.py` の構造解析へ置き換え、独自検査は等価動作に移植する。 |
| Y-04 | 文末連続の段落またぎ | 段落内のみに限定する。上流と同じく段落ブロックを判定単位とし、別段落をまたぐ誤検出を除く。 |
| Y-05 | カタログの追従範囲 | 部分導入とする。前書き、慣用句を残す条件、欠落行、含み保持の注意だけを補い、上流の詳細調への全面置換は行わない。 |
| Y-06 | 絵文字検査の方式 | 現行 `EMOJI_PATTERN` を維持し、可視テキスト化のみ対応する。上流の Unicode 派生機械とライセンス同梱は採用しない。 |
| Y-07 | v1.0.9 から v1.1.1 の採用範囲 | ダッシュ3ルール化、否定構文強化、info 系文パターン、フィラー拡充、`SLOP_WORD_PATTERNS`、リテラル絞り込み機械、基盤同期を採用する。Unicode 派生絵文字表、ドメイン別ガイド、コーパス、上流パッケージングは前回決定を踏襲して対象外。 |
| Y-08 | 新規 warn 検出の範囲 | `SLOP_WORD_PATTERNS`(「ゲート」「閉包」「台帳」「〜のOS」「本質を突く」)のみ採用し、「意思決定OS」は `SLOP_WORDS` からパターンへ移す。version 意味の「版」と regression 意味の「回帰」の `TRANSLATED_TERM_PATTERNS`、および「Xとは:Y」見出しの `heading_colon` は見送る。 |
| Y-09 | ダッシュ検査の置き換え | 現行 `dash_prohibited` を上流の3ルール(`dash_list_ending`/`dash_insertion`/`dash_decoration`)と引用や区間、出典、図罫線のマスク、1文書3件上限へ置き換える。検出は緩くなるが、SKILL.md が例外とする範囲と書誌、引用と一致する。 |
| Y-10 | 否定構文と info 系、フィラーの強化 | `_extra_negation_line_numbers`、`_NEGATION_EXTRA`、`_NEGATION_JANAI`、`_NEGATION_ALSO` 免除、`negative_parallelism_density`、`INFO_SENTENCE_PATTERNS`、`short_mochiron`、`fragment_run`、`bold_label_list`、`short_summary_heading`、フィラー追加分と `FILLER_NOTES` をすべて採用する。 |
| Y-11 | カタログの追従範囲 | 部分導入とする。lint 採用分に対応する行は整合上必須として追加し、見送った検出(「版」「回帰」)に対応する行は入れない。lint 非対応の参照行は規範との整合を見て採用する。 |
| Y-12 | SKILL.md への反映範囲 | 制限導入とする。採用した lint とカタログの変更に対応する主題だけを節ごとに取り込み、「Xとは:Y」見出しと議事録コロンは対象外とする。 |
| Y-13 | リテラル絞り込み機械 | 採用する。`_PATTERN_LITERAL_HINTS`、`_narrowed_document_rows`、`_may_match_literals` を移植し、検出結果を変えずに上流構造へ揃える。 |
| Y-14 | v3 移植計画の対象範囲 | 上流 v1.1.1 から v3.0.0 までの差分を分析対象とし、計画書を `docs/implementation-plan-yomiyasu-v3-port.md` に作成する。実装は要協議事項の確定後にフェーズ別の独立した PR で行う。 |
| Y-15 | 絵文字検査の方式(v3) | 上流 v3.0.0 も Unicode 18.0 固定の絵文字データを内蔵するため、Y-06 の判断を継続し現行 `EMOJI_PATTERN` を維持する。 |
| Y-16 | docs のみの変更の版管理 | CI の version-base チェック(`check_plugin.py --version-base`)は docs のみの変更でも plugin.json の version 差分を必須とするため、パッチバンプを行う。 |
| Y-17 | yomiyasu_check.py と yomiyasu_hook.py の移植 | 移植しない。状態記録と verify の仕組みは上流の対話的な推敲フローを前提としており、Devin スキルの運用とは目的が異なる。フックは Claude Code 固有で Devin には適用できない。 |
| Y-18 | .yomiyasu-words/ 語彙リスト機構 | 採用する。`markdown_visibility.py` の同期に伴い語彙リストの読み込み機構を取り込む。上流 v3.0.0 は既定ファイルを tracked していないため同梱ファイルはなく、文書への記載は最小限とする。 |
| Y-19 | lint の JSON 形式と通常出力 | 上流 v2 形式へ更新する。`format_version` で形式を判別でき、CI は `--strict` のみを使い JSON 出力に依存しない。`score` の廃止と終了コードの再定義は上流と揃える。 |
| Y-20 | --doc-type/--reader オプション | 導入しない。移植版 SKILL.md は文書種別を区別する運用を持たず、種別ごとの規則差分の効果が未検証のため。`calque` 型4 と `slide_comma` は doc-type 依存のため保留または info のみの常時検出とする。 |
| Y-21 | calque 型4、translated_term、heading_colon | Y-08 の見送りを継続する。「版」「印」「頭」の calque 型4、`translated_term`、`heading_colon` は採用せず、`calque` 型1〜3 のみ採用する。 |
| Y-22 | slop_diff の拡張範囲 | 段階的に移植する。まず v1.1.2 の文の種類の印と軽量な構造節(見出し、読点増加)を移植し、`meaning_risks` 全体系は別計画とする。 |
| Y-23 | SKILL.md の更新方針 | 部分反映とする。採用した規則に対応する主題だけを現行 SKILL.md の構成に沿って取り込み、上流 v3.0.0 の全面書き直しは採用しない(Y-01/Y-12 の方針継続)。 |
| Y-24 | references/ 新規ファイルの同梱範囲 | 採用規則が依存するもののみ同梱する。`calques.md` は calque 採用時、`lists/*.txt` は対応規則採用時に置く。`fact-recovery`、`persona`、`rephrase-test`、`audience`、`doc-types` は見送る。 |
| R-01 | requirements-definition と後発スキル・ルールの責任分界 | 実装 PR のレビュー指摘対応は devin-review-triage、複数トラックの子セッションへの並列分割は parallel-child-implementation、計画内のユーザー手作業手順書は user-work-runbook、要件定義と計画完了後の実装セッションへの切り替え誘導は session-phase-split に委ねる。requirements-definition が扱うレビュー指摘の二分は仕様と計画の文書に対するものに限定する。 |
| R-02 | 既存スキル間の双方向委譲と子プロンプトの統一 | windows-blueprint と windows-cli-pitfalls の相互委譲、cf-cli から cloudflare-access-setup と cloudflare-pages-private-admin への委譲、devin-review-triage から requirements-definition への委譲を補う。user-work-runbook、dev-server-foreground-shell、parallel-child-implementation に「責任範囲の境界」節を追加し、repo-drift-audit/child-prompts.md の PR 作成指示に gh pr create 時の --body-file 指定を併記する。 |
| R-03 | 実装計画書と決定記録の 2 文書構成と未決事項の管理 | 独立した要件定義書を作らず実装計画書から始める作業（改修、移植、リファクタリングなど）では、実装計画書と決定記録の 2 文書構成を許容する。未決事項は要件定義書または実装計画書の「要協議」節で管理し、確定した時点から決定記録へ移す。 |
| R-04 | 決定記録の ID 採番規則 | 協議中の提示では回答しやすい短い仮 ID（A, B, C など）を使い、docs/decision-records.md へ確定記録する際は、複数の計画で同一ファイルを共有できるよう主題プレフィックス付き連番（Y-01、R-01 など）または通し連番で採番する。 |
| R-05 | README 収録一覧の双方向同期検査 | check_plugin.py の check_readme() を双方向検査に拡張し、rules/*.md と skills/*/SKILL.md の記載漏れだけでなく、README.md の収録一覧表に実ファイルやディレクトリが存在しない孤立行が残っている場合もエラーにする。 |
