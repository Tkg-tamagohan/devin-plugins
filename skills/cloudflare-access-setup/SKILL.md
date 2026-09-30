---
name: cloudflare-access-setup
description: Cloudflare Pages などのサイトを Cloudflare Access（Zero Trust）で保護する設定手順。Zero Trust 組織の作成、アプリケーションとポリシーの API での設定、メール OTP（IdP）の有効化、遮断と拒否の実機確認を扱う。公開サイトに非公開の管理ツールを併設するとき、Access の設定・確認を求められたときに使用する。CLI の一般作法は cf-cli、公開/非公開の構成判断は cloudflare-pages-private-admin に委ねる。
---

# Cloudflare Access の設定

Pages サイトを Access で保護する作業は、ダッシュボードでしかできない一手順と、API で完結できる残りに分かれる。
ユーザーの手作業が必要な部分を先に切り出して依頼し、API で済む部分はまとめてこちらで設定する。

## 責任範囲の境界

- **CLI・API の使い方**：コマンドは `cloudflare-cf-cli` ルールどおり `cf` で探して使う（スキル `cf-cli`）。本スキルは Access に固有の手順と落とし穴だけを扱う。
- **保護する構成の判断**：公開アプリと非公開ツールをどう分けるかは `cloudflare-pages-private-admin` に委ねる。

## 手順

1. Zero Trust 組織の有無を確認する。組織の初回作成はダッシュボード（one.dash.cloudflare.com）でしかできない。未作成なら、チーム名の入力と無料プランの選択だけをユーザーに依頼する。
2. API トークンに Zero Trust/Access 系の Edit 権限が要る。不足している場合は既存トークンへの権限追加をユーザーに依頼する。GitHub Actions 用のデプロイトークンとは別物である旨を伝える。
3. Self-hosted アプリケーションを保護対象のホスト名で作成し、ポリシーは Allow + Include: Emails = <許可するメール> で作る。
4. ログイン方法はメール OTP（One-time PIN）にする。新しい組織では OTP がログイン方法に自動追加されず、IdP として作成する方式に変わっている。旧手順（Settings → Authentication → Login methods のチェック）が API に無くても、IdP の追加は API でできる。
5. 設定後、未認証アクセスが `<team>.cloudflareaccess.com` へ 302 されること、非許可メールでは OTP が届かず先へ進めないことを実機で確認する。
6. 許可メール側の OTP ログインは Devin がメールを受け取れないため確認できない。最後の受け入れ確認としてユーザーに依頼する。

## 原則

- ユーザーに依頼するのはダッシュボードでしかできない操作と自分のメールでの確認だけに絞り、残りは API でまとめて済ませる。
- 公式の UI 手順は変わりうる。記憶の手順と画面が違ったら最新の公式手順を調べ直す。
