---
trigger: model_decision
description: Cloudflare のリソースをコマンドラインから作成、参照、変更するとき、または Cloudflare 関連の運用を自動化するとき
---

# Cloudflare の操作は `cf` CLI を使う

Cloudflare のリソースを CLI から操作するときは、REST API を curl で組み立てず、`npx cf` を使う。
`cf` は Cloudflare の OpenAPI スキーマから生成される CLI で、wrangler の約 280 操作に対して API 全体の 3,000 以上の操作をカバーし、Pages、Zero Trust/Access、DNS などを一つのツールで扱える。

## 手順

1. `npx -y cf cli search "<やりたいこと>"` で対応するコマンドを探す。
2. 認証、出力形式、バージョンの固定、wrangler との使い分けはスキル `shared-skills:cf-cli` に従う。

## 対象外

- 稼働中の CI/CD パイプライン(`cloudflare/wrangler-action`、`wrangler pages deploy` など)
  - `cf` はオープンベータのため、動いているデプロイ経路は置き換えない。
- Cloudflare のダッシュボードで完結する一度きりの作業。
- Cloudflare に関係しない作業。
