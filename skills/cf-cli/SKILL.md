---
name: cf-cli
description: Cloudflare の公式 CLI `cf` の実行方法、認証、コマンドの探し方、wrangler との使い分けを扱う。Cloudflare のリソースをコマンドラインから操作するとき、Pages や Access などの設定を確認または変更するときに使用する。リージョンの選定は region-near-japan に委ねる。
---

# Cloudflare CLI `cf`

`cf` は Cloudflare が公開するエージェント向けの公式 CLI で、OpenAPI スキーマから生成されたコマンド群を持つ。
wrangler がカバーしない Zero Trust/Access などを含め、Cloudflare API 全体を一つのツールで扱える。
Cloudflare の運用を、REST API を個別に組み立てることなく完結させることがゴールである。

## 責任範囲の境界

- **リージョン選定**：リソースの作成や移行でリージョンを選ぶ判断は `region-near-japan` に委ねる。
  - 本スキルは CLI の使い方だけを扱う。

## 実行方法

`cf` は npm パッケージとして配布され、グローバルインストールはせず `npx` でバージョンを指定して実行する。

```bash
npx -y cf@1.0.0-beta.5 <command>
```

オープンベータの段階にあるため、スクリプトや CI に組み込むときは特にバージョンを固定する。
アカウント ID は `--account-id` 系のフラグではなく環境変数 `CLOUDFLARE_ACCOUNT_ID` で渡す。

## 認証

環境変数 `CLOUDFLARE_API_TOKEN` と `CLOUDFLARE_ACCOUNT_ID` を読む。
wrangler と同じ環境変数なので、wrangler 用に発行済みの API トークンがそのまま使える(実機で確認済み)。
対話的なブラウザログインは `cf auth login`、状態の確認は `cf auth whoami` で行う。

## コマンドの探し方

操作は約 3,000 あるため、コマンド名を調べてから実行するのではなく、自然言語で検索する。

```bash
npx -y cf cli search "list pages projects"
# [{"command": "cf pages projects list", "summary": "Get projects"}, ...]
```

引数は `<command> --help` で確認する。
位置パラメータを取るコマンドが多く、API ドキュメントのフィールド名をそのまま `--xxx` で渡すと Unknown argument になることがある。

## 出力の扱い

出力は既定で JSON なので、`jq` で必要な項目だけを取り出す。

```bash
CLOUDFLARE_ACCOUNT_ID=<id> npx -y cf pages projects list | jq '.[].name'
```

## 主なコマンド

```bash
cf pages projects list                      # Pages プロジェクトと最新デプロイの一覧
cf pages projects deployments list          # デプロイ履歴
cf pages deploy <dir>                       # 静的サイトの直接アップロード
cf zero-trust access applications get <id>  # Access アプリケーションとポリシーの参照
```

D1、R2、DNS なども同様にサブコマンドで扱う。
ここでは頻出の入口だけを挙げ、詳細は `cf cli search` と `--help` に委ねる。

## wrangler との使い分け

- ad-hoc な運用、参照、設定変更：`cf` を使う。
- 稼働中のデプロイパイプライン(`cloudflare/wrangler-action`、`wrangler pages deploy` など)：wrangler のまま維持する。
  - `cf` が stable になった時点で移行を検討する。
- `cloudflare.config.ts` と Vite 連携は Worker 向けの機能であり、静的サイトだけを Pages に置く構成では現時点で恩恵が薄い。

## 原則

- Cloudflare の操作は curl や wrangler の限定的なコマンドではなく `cf` で行う。
- コマンドは `cf cli search` で探し、引数は `--help` で確かめる。
- beta 版と割り切ってバージョンをピンして使い、既存のデプロイ経路は置き換えない。
