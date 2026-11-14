# プラグイン横断リファクタリング実装計画

状態: 進行中

`shared-skills` プラグイン全体を対象に、`requirements-definition` と後発スキル群の責任分界の整備、既存スキル間の双方向委譲の補完、決定記録の運用整合、および `skills/plugin-authoring/scripts/` の整理を行う計画。
確定した判断は `docs/decision-records.md` の R-01 から R-05 に記録した。

## 前提と環境

- 変更対象は `docs/`、`skills/requirements-definition/`、各既存スキルの `SKILL.md`、`skills/repo-drift-audit/child-prompts.md`、および `skills/plugin-authoring/scripts/`。
- 全作業は Python 3 標準ライブラリのみで完結し、外部サービスや秘密情報は要らない。
- 検証はリポジトリの CI(plugin-checks)と同じコマンドをローカルで実行する。

## 採用方針

ユーザーの承認により、論点 A〜E の推奨案と自律適用項目を採用する(決定記録 R-01〜R-05)。
作業は 3 つのフェーズに分け、フェーズごとに独立した積み上げ PR として作成する。

## 構成

### 新規に入れるファイル

- `docs/implementation-plan-plugin-refactoring.md`: 本リファクタリングの実装計画書。

### 変更する既存ファイル

- Phase 1: `docs/decision-records.md`、`skills/requirements-definition/SKILL.md`、`.devin-plugin/plugin.json`
- Phase 2: `docs/implementation-plan-plugin-refactoring.md`、`skills/windows-blueprint/SKILL.md`、`skills/windows-cli-pitfalls/SKILL.md`、`skills/parallel-child-implementation/SKILL.md`、`skills/repo-drift-audit/child-prompts.md`、`skills/user-work-runbook/SKILL.md`、`skills/dev-server-foreground-shell/SKILL.md`、`skills/cf-cli/SKILL.md`、`skills/devin-review-triage/SKILL.md`、`.devin-plugin/plugin.json`
- Phase 3: `docs/implementation-plan-plugin-refactoring.md`、`skills/plugin-authoring/scripts/check_plugin.py`、`skills/plugin-authoring/scripts/new_entry.py`、`skills/plugin-authoring/scripts/test_check_plugin.py`、`.devin-plugin/plugin.json`

## フェーズ別タスク

各フェーズは独立した積み上げ PR とする。
チェック済みの項目は対応するフェーズのブランチで実装と検証が終わったことを示し、マージ済みを意味しない。
PR 作成前に `plugin.json` のバージョンを順にパッチバンプし、各フェーズでコードと論理観点のセルフレビューを行う。

### Phase 1: requirements-definition スキルと docs/ 文書の整合化

- [x] `docs/decision-records.md` の対象説明を更新し、決定記録 R-01〜R-05 を追加する。
- [x] `skills/requirements-definition/SKILL.md` に後発のスキルとルール(`devin-review-triage`、`parallel-child-implementation`、`user-work-runbook`、`session-phase-split`)への委譲を明記する。
- [x] `skills/requirements-definition/SKILL.md` に 2 文書構成の許容、仮 ID と確定 ID の採番規則、計画書の状態行およびチェックリスト `[x]` の意味づけ規約を反映する。
- [x] `docs/implementation-plan-plugin-refactoring.md` を作成し、`.devin-plugin/plugin.json` を 0.2.46 へ更新する。

受け入れ条件として、`check_plugin.py --version-base origin/main` と全 Markdown 一括 `--strict` リントおよび全回帰テストが通ることとする。

### Phase 2: 関連スキル群の責任範囲の境界と相互委譲の整備

- [x] `windows-blueprint` と `windows-cli-pitfalls` に「責任範囲の境界」節と相互委譲を追加する。
- [x] `parallel-child-implementation` に「責任範囲の境界」節と `child-prompts.md` 参照を補い、`repo-drift-audit/child-prompts.md` に `gh pr create` 時の `--body-file` 指定を併記する。
- [x] `user-work-runbook` と `dev-server-foreground-shell` に「責任範囲の境界」節と委譲先を追加する。
- [x] `cf-cli` に `cloudflare-access-setup` と `cloudflare-pages-private-admin` への委譲を追加し、`devin-review-triage` に `requirements-definition` への委譲を追加する。
- [x] 各スキルが上限 200 行以内かつ `--strict` リントを通ることを確認し、`.devin-plugin/plugin.json` を 0.2.47 へ更新する。

受け入れ条件として、変更した全スキルと全 Markdown が `slop_lint.py --strict` と `check_plugin.py` を通過することとする。

### Phase 3: plugin-authoring/scripts/ の重複排除、UTF-8 安全化、回帰テスト拡充

- [ ] `check_plugin.py` に共有ヘルパ(`run_git`、`semver_tuple`、`version_at_ref`、`has_structural_changes`、`find_readme_table`)を実装し、各 `check_*` 関数を `root: Path = REPO_ROOT` でパラメータ化してパス表記を POSIX 形式に統一する。
- [ ] `check_plugin.py` の `check_readme()` に `README.md` 収録一覧の孤立行を検出する双方向同期検査を実装する。
- [ ] `new_entry.py` の重複ロジックを `check_plugin.py` からの import へ置き換え、既存の公開 API と `test_new_entry.py` 全 16 ケースの後方互換を保つ。
- [ ] `test_check_plugin.py` に `CP-13`〜`CP-22` を追加して構造検査、状態行検査、双方向 README 検査、バンプ検査を検証し、本計画書の状態行を `状態: 完了` に、`.devin-plugin/plugin.json` を 0.2.48 へ更新する。

受け入れ条件として、`test_new_entry.py` と `test_check_plugin.py` の全件、および CI(`plugin-checks.yml`)と同等の全検査コマンドが通ることとする。

## 引き継ぎ手順

- 現在地は本書のチェックリストと、該当 PR(Phase 1〜3)の状態から確認する。
- ブランチは Phase 1 が `origin/main` 起点、Phase 2 と Phase 3 は前 Phase ブランチを起点とする積み上げ構成とし、PR のマージは Phase 1 から順番に行う。
- ローカル検証の一式は `test_slop_lint.py`、`test_catalog_consistency.py`、`test_slop_diff.py`、`test_new_entry.py`、`test_check_plugin.py`、`check_plugin.py --version-base <base>`、および全 Markdown の一括 `--strict` リントである。

## 要協議(全件確定済み)

論点 A〜E はすべてユーザー承認により推奨案で確定し、`docs/decision-records.md` の R-01〜R-05 へ移した。
確定内容は以下の通り。

- A: `requirements-definition` と後発スキル・ルールの責任分界を明記する(R-01)。
- B: 既存スキル間の双方向委譲と子プロンプトの PR 作成指示を統一する(R-02)。
- C: 実装計画書と決定記録の 2 文書構成と未決事項の管理場所を明文化する(R-03)。
- D: 協議中の仮 ID と決定記録ファイルの主題プレフィックス付き採番規則を定める(R-04)。
- E: `check_plugin.py` の `check_readme()` で収録一覧の双方向同期検査を行う(R-05)。
