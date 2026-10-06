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
| `cloudflare-cf-cli` | Cloudflare のリソースをコマンドラインで操作するとき、運用を自動化するとき |
| `cloudflare-pages-private-admin` | Cloudflare Pages の公開アプリに非公開の管理ツールを併設するとき |
| `library-license` | 外部ライブラリやパッケージを導入、更新、転用するとき |
| `merge-detected-sleep` | 自分が作成または監視する PR のマージイベントを検知したとき |
| `region-near-japan` | クラウドリソースのリージョンを選ぶとき |
| `register-to-devin-plugins` | 再利用可能なルールやスキルを作成したとき |
| `scoped-secret-provisioning` | ユーザーにシークレットの登録を依頼するとき |
| `session-phase-split` | 開発フェーズが切り替わるとき、セッションの作業が長期化したとき |
| `test-conventions` | テストコードの作成や修正、テスト結果の報告をするとき |
| `ui-mock-first` | ユーザー操作を伴う UI の開発やテストをするとき |
| `verify-file-writes` | マルチバイト文字を含むファイルの作成や文書編集のあと |

### スキル

`skills/<name>/SKILL.md` はスキル本体。
呼び出されたときに読まれる手順書や知識。

| スキル | 内容 |
| --- | --- |
| `cf-cli` | Cloudflare 公式 CLI `cf` の実行方法 |
| `cloudflare-access-setup` | Cloudflare Access でサイトを保護する設定手順 |
| `dev-server-foreground-shell` | Devin VM 上での開発サーバーの起動と維持 |
| `devin-review-triage` | Devin Review の指摘のトリアージと対応 |
| `japanese-tech-writing` | 日本語技術文書の文章規範と機械検査リンター |
| `output-format-escalation` | 説明や調査の成果物の出力形式の選択(制約付き文章、図、インタラクティブ HTML) |
| `parallel-child-implementation` | 改善群の子セッションへの並列分割と依頼方法 |
| `plugin-authoring` | このリポジトリへのルールやスキルの追加手順 |
| `repo-drift-audit` | 文書やテスト資産とコードの乖離の網羅監査 |
| `requirements-definition` | 要件定義や仕様確定の進め方 |
| `user-work-runbook` | ユーザーが手作業で行う運用の手順書作成 |
| `windows-blueprint` | Windows 向け blueprint の作成とデバッグ |

## 構成

```
.devin-plugin/plugin.json          # プラグインマニフェスト(name が /<plugin>:<skill> の名前空間になる)
AGENTS.md                          # 全セッションに常時適用される共通ルール
LICENSE                            # MIT License
.sloplintignore                    # 文書リントの検査対象から外すパス一覧
rules/<name>.md                    # トリガー付きルール(description に合う状況のセッションでのみ本文が読まれる)
skills/<name>/SKILL.md             # スキル本体(手順や知識。呼び出されたときに読まれる)
skills/plugin-authoring/           # このリポジトリ自体の編集手順、作成指針(guidelines.md)、テンプレート、生成スクリプト(scripts/new_entry.py)、構造チェック(scripts/check_plugin.py)
skills/japanese-tech-writing/scripts/    # スロップリンター(slop_lint.py)と回帰テスト
skills/japanese-tech-writing/references/ # 悪い表現の語彙カタログ(slop-catalog.md)
skills/repo-drift-audit/child-prompts.md # 監査で子セッションへ渡すプロンプトの定型
.github/workflows/plugin-checks.yml # リンターの回帰テストと文書リント、構造チェックを実行する CI
```

ルールやスキルをどこに置くか、どの粒度で分けるかの基準は `skills/plugin-authoring/guidelines.md` にまとめている。
新しく追加するときは、スキル `shared-skills:plugin-authoring` の手順に従う。
`rules/register-to-devin-plugins.md` により、セッション中に再利用可能なルールやスキルを作成した Devin はこのリポジトリへの追加 PR を自動で作る。
ルールやスキルの新規追加では `scripts/new_entry.py` が命名検査、テンプレートの複写、収録一覧への行追加、version バンプまでを担う(手順は `skills/plugin-authoring/SKILL.md`)。
PR では CI(`plugin-checks`) がスロップリンターと生成スクリプトの回帰テスト、全 Markdown への文書リント(`.sloplintignore` 対象を除く `slop_lint.py --strict`、warn で失敗)、`check_plugin.py` による構造チェック(命名、frontmatter、「対象外」の有無、行数、README との同期、plugin.json の version 更新)を実行する。

## インストール / 更新

Devin Web アプリの **Customize → Plugins → Add plugin → From repository** でこのリポジトリを Organization スコープとしてインストールする(要: 組織のプラグイン管理権限)。
インストール後、スキルは組織の全セッションで自動検出されるほか、`/shared-skills:<skill名>` でも呼び出せる。

内容を更新した場合は、このリポジトリに push したうえで Customize のプラグイン設定から再インデックスする。

## ライセンス

[MIT License](LICENSE)。

ただし `skills/japanese-tech-writing/` に含まれるスロップリンターと語彙カタログは、[nanaism/yomiyasu](https://github.com/nanaism/yomiyasu) を基に調整したもので、ライセンス条文は同ディレクトリの `LICENSE-yomiyasu` に同梱している。
