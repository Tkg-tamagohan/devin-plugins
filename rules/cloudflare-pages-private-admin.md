---
trigger: model_decision
description: Cloudflare Pages の公開アプリに非公開の管理ツールやステージングを併設するとき、または Pages サイトのアクセス制御方式を決めるとき
---

# 非公開ツールは別 Pages プロジェクト＋Cloudflare Access で保護する

公開アプリと非公開ツールを同一の SPA（Blazor WASM 等）内でルート分離すると、クライアント側ルーティングで Cloudflare Access をすり抜けられる。
非公開にしたい対象は別の Pages プロジェクト（専用ドメイン）として切り出し、Cloudflare Access で丸ごと保護する。

## 手順

1. 保護対象を別 Pages プロジェクトとしてデプロイする。
2. スキル `shared-skills:cloudflare-access-setup` の手順で、Cloudflare Access（Self-hosted アプリケーション）を用いてそのドメインを保護する。

## 対象外

- サーバーサイドで認証判定を持つアプリ（SSR、API）
  - すり抜けはクライアント側ルーティングに起因する。
- IP 制限などネットワークレベルの制御で足りる場合。
