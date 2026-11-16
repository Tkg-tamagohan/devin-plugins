---
name: github-actions-ci
description: GitHub Actions における CI、リリース、定期セキュリティ監査ワークフローを設計または監査し、検証漏れや無駄をなくす手順と罠の回避策。必須チェックを壊さない変更判定スキップ、git diff のリネーム検出対策、node --check 等の複数引数や除外対象の盲点、権限最小化とロック固定、リリース前後検証、audit の定期分離を扱う。CI やリリースワークフローを構築、改善、レビューするときに使用する。並列監査の構成は repo-drift-audit、シークレット設定案内は scoped-secret-provisioning、テストの仕様準拠と ID 管理は test-conventions、外部ツール導入時のライセンス確認は library-license、Windows 環境のシェル罠は windows-cli-pitfalls に委ねる。
---

# GitHub Actions における CI とリリース基盤の設計

CI やリリースワークフローにおける未検査領域、暗黙の素通り、環境依存ドリフト、および文書変更時の不要ビルドを防ぐための標準構成を定める。
どの対策でも、既存の必須チェックを損なわず安全側へ倒す構成を採る。

## 責任範囲の境界

- **並列監査の構成**：複数のサブエージェントやワークスペースでリポジトリ全体を走査する進行は `repo-drift-audit` に委ねる。
- **テスト記述規約**：テストを仕様書から作成する原則と ID 採番表は `test-conventions` に委ねる。
- **新規パッケージ導入**：CI 改善のために Action 以外の外部パッケージやツールを導入するときは `library-license` に従う。
- **シークレット登録依頼**：署名鍵などの Secrets 登録をユーザーへ案内する手順は `scoped-secret-provisioning` に委ねる。
- **Windows ローカル検証のシェル罠**：PowerShell の引用規則や文字コード対策は `windows-cli-pitfalls` に委ねる。

## 必須チェックを壊さない変更ファイル別スキップ

ブランチ保護や Ruleset で必須ステータスチェックを指定しているワークフローへ `on.push.paths-ignore` や `on.pull_request.paths-ignore` を設定すると、ワークフロー自体が起動しない変更時に必須チェックが永久に Pending になりマージ不能になる。
ワークフローは全変更で起動したまま、先頭の `changes` ジョブで実行対象を判定し、末尾の集約ジョブ（`if: always()`）で結果を確定させる。

1. `changes` ジョブでは `actions/checkout` に `fetch-depth: 0` を指定し、`git diff` で変更ファイルを列挙する。
   - 差分取得の失敗、空リスト、または `push` 時の `before == 0000...`（新規ブランチや初回）では安全側へ倒して全ジョブ `true` を返す。
2. `git diff` には必ず `--no-renames` を指定する。
   - リネーム検出が有効なままだと、コードファイルを `docs/` 配下へ移した際に移動先パスだけが返り、コード側の削除を見落として「文書専用変更」と誤認する。
3. スキーマ仕様書や API 表のようにコード側テストが直接参照する文書（設計書の DDL 節など）が変更された場合は、対応する検証ジョブ（バックエンドテスト等）だけ `true` に残す。
4. 末尾の集約ジョブには `if: always()` を付け、無条件ジョブは `success`、条件付きジョブは `changes` の出力（`true` なら `success`、`false` なら `skipped`）と一致したときだけ成功にする。

```text
# NG（リネーム元の削除を見落とし、必須チェックの永久 Pending も招く）
on: { pull_request: { paths-ignore: ["docs/**"] } }
git diff -z --name-only "$BASE" "$HEAD"

# OK（集約チェックを維持しつつリネーム元削除も検出する）
git diff --no-renames -z --name-only "$BASE" "$HEAD"
```

```python
# 集約ジョブ（if: always()）で actual と expected を照合する例
for name, info in needs.items():
    actual = info.get("result")
    expected = (
        ("success" if outputs.get(flag_map[name]) == "true" else "skipped")
        if name in flag_map
        else "success"
    )
    if actual != expected:
        sys.exit(1)
```

## 検査範囲の空白地帯と CLI の罠

型検査や既定テストの設定外に置かれた資産が検証漏れを起こしやすい。

- **`node --check` は先頭引数しか検査しない**：`node --check a.js b.js` は最初の `a.js` だけを構文検査し、`b.js` 以降は構文エラーがあっても素通りする。
  複数ファイルを検証するときは `node --check a.js && node --check b.js` のように 1 ファイルずつ呼ぶ。
- **`tsconfig.json` 除外資産の補完**：ブラウザ拡張やビルド設定ファイルなど型検査対象外の JS へは個別 `node --check` を回し、HTML の DOM ID やマニフェスト参照の実在を単体テストで押さえる。
- **補助スクリプトとテキスト健全性**：CI 用や開発用のスクリプト群にも `py_compile` と標準ライブラリでの単体テストを用意し、置換文字 `U+FFFD` や競合マーカーの残存、JSON と XML の構文エラー、多言語翻訳の余剰キー不在をあわせて検査する。

```json
// NG（2 番目のファイルに構文エラーがあっても終了コード 0 で通る）
"check:js": "node --check a.js b.js"

// OK（全ファイルを個別に構文検査する）
"check:js": "node --check a.js && node --check b.js"
```

## ワークフローの権限最小化と再現性固定

- **最小権限**：ワークフロートップレベルの `permissions` は `contents: read` に固定し、公開処理など書き込みが必要なジョブへだけ `contents: write` を付与する。
- **同時実行制御**：`concurrency.cancel-in-progress` は `${{ github.event_name == 'pull_request' }}` とし、既定ブランチへの連続 push が途中で打ち切られるのを防ぐ。
- **タイムアウト明示**：全ジョブへ妥当な `timeout-minutes` を設定し、ハングしたジョブによる長時間ランナー占有を防ぐ。
- **lockfile 強制**：`pnpm install --frozen-lockfile`、`cargo clippy --locked`、`cargo test --locked` を使い、依存解決の勝手な更新を禁止する。
  ラッパー CLI（`tauri build` 等）経由の場合は `--ci` と `-- --locked` で引数を引き渡す。

## リリースワークフローの事前検証と成果物検証

長時間のクロスプラットフォームビルドを始める前に明らかな不備を弾き、公開直前に配布物全体を検査する。

1. 先頭に `preflight` ジョブを置き、文書整合、タグ文字列と設定ファイルのバージョン一致（`--expect-tag`）、署名秘密鍵 Secrets の非空を数秒で確認する。
2. Linux と Windows が混在するビルドマトリクスでの共通スクリプト検査には `shell: bash` を明示し、環境差による構文エラーを避ける。
3. `gh release create` や `gh release upload` の直前で検証スクリプトを実行し、署名中間ファイル（`.sig` 等）や廃止拡張子の非残存、自動更新マニフェスト（`latest.json` 等）のバージョン一致と成果物実在、パッケージ内へのテスト混入なしを確認する。
4. 既存リリースのアセット削除では `for x in $names` による空白分割を避け、`while IFS= read -r name` で 1 行ずつ処理する。

## 脆弱性監査の定期分離と重大度管理

- `npm audit` や `pnpm audit` を通常 PR の必須条件に入れると、コード変更と無関係な外部アドバイザリの公開時に全 PR のマージが止まる。
- 依存パッケージの脆弱性監査は週次の `schedule` と `workflow_dispatch` を持つ独立ワークフロー（`security.yml`）へ分離する。
- 開発依存に低重大度や中重大度の未修正アドバイザリが残る現実を踏まえ、`--prod` と `--audit-level high` を失敗条件、`--ignore-registry-errors` を一時的なレジストリ障害耐性として設定し、全件サマリは `continue-on-error: true` でログ可視化に留める。

## 原則

- 必須ステータスチェックを守るため `paths-ignore` は使わず、`changes`（`fetch-depth: 0` と `--no-renames`）および集約ジョブ（`if: always()`）で安全側スキップを組み立てる。
- 差分取得不能時や仕様照合対象ドキュメントの変更時は、必ず関連ジョブを実行側へ倒す。
- `node --check` は 1 回の呼び出しにつき先頭 1 ファイルしか見ない仕様を踏まえ、ファイルごとに個別実行する。
- 全ワークフローへ最小 `permissions`、`timeout-minutes`、`pull_request` 限定のキャンセル制御、`--locked` を組み込む。
- リリースは `preflight` と公開直前検証の二段で守り、脆弱性監査は PR と分離して定期実行する。
