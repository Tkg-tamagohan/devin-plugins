# shared-skills (Devin plugin)

組織横断で使う Devin のルールとスキルをまとめたプラグイン。
全セッションに常時適用される共通ルール、状況に応じて読み込まれるトリガー付きルール、手順や知識をまとめたスキルを、一つのパッケージとして配布する。

## 収録内容

### 共通ルール

`AGENTS.md` は全セッションに常時適用される共通ルール。
推測の明記、変更範囲の限定、検証結果と未検証の区別など、作業種別に依存しない短い制約を定める。

### ルール

`rules/<name>.md` はトリガー付きルール。
frontmatter の `description` に合う状況のセッションでのみ本文が読まれる。

| ルール | 読み込まれる状況 |
| --- | --- |
| `cloudflare-cf-cli` | Cloudflare のリソースをコマンドラインで操作・自動化するとき |
| `cloudflare-pages-private-admin` | Cloudflare Pages の公開アプリに非公開の管理ツールを併設するとき |
| `library-license` | 外部ライブラリやパッケージを導入・更新・転用するとき |
| `merge-detected-sleep` | 自分が作成した PR のマージイベントを検知したとき |
| `region-near-japan` | クラウドリソースのリージョンを選ぶとき |
| `register-to-devin-plugins` | 再利用可能なルールやスキルを作成したとき |
| `scoped-secret-provisioning` | ユーザーにシークレットの登録を依頼するとき |
| `session-phase-split` | 開発フェーズが切り替わるとき、セッションの作業が長期化したとき |
| `test-conventions` | テストコードを作成・修正するとき、テスト結果を報告するとき |
| `ui-mock-first` | ユーザー操作を伴う UI の開発・テストをするとき |
| `verify-file-writes` | マルチバイト文字を含むファイルの作成や文書編集のあと |

### スキル

`skills/<name>/SKILL.md` はスキル本体。
呼び出されたときに読まれる手順書・知識。

| スキル | 内容 |
| --- | --- |
| `cf-cli` | Cloudflare 公式 CLI `cf` の実行方法 |
| `cloudflare-access-setup` | Cloudflare Access でサイトを保護する設定手順 |
| `dev-server-foreground-shell` | Devin VM 上での開発サーバーの起動と維持 |
| `devin-review-triage` | Devin Review の指摘のトリアージと対応 |
| `japanese-tech-writing` | 日本語技術文書の文章規範と機械検査リンター |
| `parallel-child-implementation` | 改善群の子セッションへの並列分割と依頼方法 |
| `plugin-authoring` | このリポジトリへのルール・スキルの追加手順 |
| `repo-drift-audit` | 文書やテスト資産とコードの乖離の網羅監査 |
| `requirements-definition` | 要件定義・仕様確定の進め方 |
| `user-work-runbook` | ユーザーが手作業で行う運用の手順書作成 |
| `windows-blueprint` | Windows 向け blueprint の作成とデバッグ |

## 構成

```
.devin-plugin/plugin.json          # プラグインマニフェスト(name が /<plugin>:<skill> の名前空間になる)
AGENTS.md                          # 全セッションに常時適用される共通ルール
LICENSE                            # MIT License
rules/<name>.md                    # トリガー付きルール(description に合う状況のセッションでのみ本文が読まれる)
skills/<name>/SKILL.md             # スキル本体(手順や知識。呼び出されたときに読まれる)
skills/plugin-authoring/           # このリポジトリ自体の編集手順、作成指針(guidelines.md)、テンプレート
```

ルールやスキルをどこに置くか、どの粒度で分けるかの基準は `skills/plugin-authoring/guidelines.md` にまとめている。
新しく追加するときは、スキル `shared-skills:plugin-authoring` の手順に従う。
`rules/register-to-devin-plugins.md` により、セッション中に再利用可能なルールやスキルを作成した Devin はこのリポジトリへの追加 PR を自動で作る。

## インストール / 更新

Devin Web アプリの **Customize → Plugins → Add plugin → From repository** でこのリポジトリを Organization スコープとしてインストールする(要: 組織のプラグイン管理権限)。
インストール後、スキルは組織の全セッションで自動検出されるほか、`/shared-skills:<skill名>` でも呼び出せる。

内容を更新した場合は、このリポジトリに push したうえで Customize のプラグイン設定から再インデックスする。

## ライセンス

[MIT License](LICENSE)。

ただし `skills/japanese-tech-writing/` に含まれるスロップリンターと語彙カタログは、[nanaism/yomiyasu](https://github.com/nanaism/yomiyasu) を基に調整したもので、ライセンス条文は同ディレクトリの `LICENSE-yomiyasu` に同梱している。
