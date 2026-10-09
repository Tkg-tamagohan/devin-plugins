# 決定記録

実装計画 `docs/implementation-plan-yomiyasu-port.md` と `docs/implementation-plan-yomiyasu-v111-port.md` に関する確定済みの判断を記録する。
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
