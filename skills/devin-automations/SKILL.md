---
name: devin-automations
description: Devin Automations のオーガニゼーション固有の運用知見。オートメーション起動セッションでの公開リポジトリ git clone 403 と公開経路フォールバック、自己 sleep によるスロット解放と自動起床、lite モードと net_policy の最小許可、run_as の選択、message_session と start_session の使い分け、読み取り専用の監査系オートメーションの型を扱う。オートメーションの作成や既存オートメーションの設定変更、起動されるセッションのプロンプト設計をするときに使用する。トリガーやアクション、上限の一般作法は builtin の managing-automations に委ねる。
---

# Devin Automations の org 固有運用知見

この組織で運用しているオートメーションの実践知のうち、builtin の managing-automations が扱わない部分をまとめる。
2026-10 から 2026-11 の運用実績と、公式ドキュメントおよび devin_automation_manage のスキーマに基づく。

## 責任範囲の境界

- **オートメーションの一般作法**：トリガー種別、アクション種別、ACU 上限、キューイング、ネットワークポリシーの意味は builtin の managing-automations と公式ドキュメントに委ねる。
  - 本スキルはこの組織で実際に踏んだ落とし穴と、検証済みの設定値だけを扱う。
- **対象リポジトリの手順**：各リポジトリの同期処理や監査の中身は、対象リポジトリ側の文書に委ねる。

## オートメーション起動セッションの git 403

- オートメーションが起動したセッションでは、git-manager.devin.ai 経由の git clone や fetch が公開リポジトリでも HTTP 403 になる。
  - 2026-10 時点で devin-plugins と Aseprite-APNG(いずれも公開リポジトリ)について、run_as=organization と run_as=creator の両方で発生を確認した。
  - 手動起動のセッションでは同じ URL で成功する。
- 原因は未検証である。
  - オートメーション起動セッションの git 認可が GitHub 接続のインストール対象リポジトリに限定される可能性がある。
  - 恒久対応はユーザー側で Settings → Integrations → GitHub の対象範囲を確認し、必要なら拡大する作業になる。
- 回避策は公開経路の利用である。
  - api.github.com と codeload.github.com の tarball 取得で公開リポジトリの main を読める。
    - これらのホストは net_policy で許可する必要がある。
  - プラグインとしてインストール済みのリポジトリなら /opt/.devin/plugins/cache/ のキャッシュを監査対象にできる。
    - キャッシュはインストール時点の版なので main とずれうる。
    - 使った対象と制約は成果物に明記する。
- 書き込みが要る作業では、git proxy が使えない場合の代替として gh や api.github.com の REST をプロンプトに書いておく。
  - Git References API で refs を作成し、Contents API でファイルを更新し、Pulls API で PR 作成とマージができる。
  - 全経路が失敗したときの退避として、生成物を attachments で共有して終了する指示も有効である。
- 新しいオートメーションでは、対象リポジトリを読む必要があるなら公開経路の許可とフォールバック指示をプロンプトに入れておく。

## 自己 sleep と自動起床

- 起動されたセッションは、作業の最後に `devin_session_interact(action="sleep", session_id=<自分の devin_id>)` を呼んで suspend する。
  - suspend によりセッションは同時実行の枠を占有しなくなる。
  - 次にメッセージが届くと自動で復帰する。
- この自己 sleep はこの組織のスケジュール系オートメーションのプロンプトに定型として入れている。
  - 日次メモリー同期と週次ドリフト監査の両方で、最終行動として sleep を呼ぶ指示を確認済みである。
- message_session 型では suspend 中の対象セッションがメッセージで自動復帰するため、常駐デーモンとして使える。

## lite モードと net_policy

- この組織の定期タスク系オートメーションは `session_settings.devin_mode="lite"` で運用している。
  - 対象は日次のメモリー同期と週次のドリフト監査である。
- `net_policy` は起動されるセッションの外向き通信を絞る。
  - Git Manager の既定の開始ポリシーは git-manager.devin.ai のみの許可であり、明示的に含める。
  - この組織では git-manager.devin.ai に加えて github.com、api.github.com、codeload.github.com を許可している。
  - net_policy はセキュリティプロファイルとの積集合であり、オートメーション側から権限を広げることはできない。

## run_as の選択

- `run_as` は作成時に必須であり、既定値はない。
  - organization は組織の既定サービスユーザーとして動く。
  - creator は作成者の権限で動く個人オートメーションで、作成者と組織管理者にだけ見える。
  - service_user は指定したサービスユーザーの権限で動く。
- この組織のオートメーションは run_as=creator で運用している。
- service_user を選ぶ場合はサービスユーザー ID が要る。
  - devin_automation_manage ではサービスユーザーを一覧できないため、ユーザーに ID を尋ねる。
  - service-user-created のオートメーションでは run_as=creator は拒否される。
- run_as=organization の下では `tools.mcp_servers` に org スコープの MCP サーバーだけを指定できる。
  - user スコープのサーバーは各ユーザーの認証情報を使うため組織 ID では動かない。

## message_session と start_session の使い分け

- start_session は起動ごとに新しいセッションを作る。
  - 監査や一回限りのタスクなど、実行ごとに独立した作業単位がよい場合に向く。
- message_session は既存の長時間セッションへメッセージを送る。
  - 状態を持ち越す常駐セッションにイベントを逐次処理させたい場合に向く。
  - 対象セッションは suspend 中でもメッセージで自動復帰する。
- message_session には auto_create=true で初回発火時にセッションを作る選択肢があるが、この組織では使っていない。
  - オートメーション起動のセッションは Memory Drive を読み書きできないため、メモリーが要る常駐セッションは webapp や CLI など非オートメーション経路で一度起動しておく。
- この組織の実例では、日次メモリー同期が message_session で常駐デーモンセッションを起こし、週次ドリフト監査が start_session で毎回新しいセッションを起こす構成になっている。

## 監査系オートメーションの型

- 読み取りと分析に留める監査系は、プロンプトで変更禁止を明示する。
  - リポジトリへの変更、ブランチ作成、PR 作成を行わない。
  - 子セッションへの振り分けも行わず、深掘りと実装はユーザーが候補を採択したあと別セッションで行う。
  - 成果物はリポジトリ外に置き、attachments で共有する。
- 監査が古いプラグインキャッシュを対象にした場合、採択項目を適用する側で現行 main に対して再検証する。
  - キャッシュはインストール時点の版であり、監査時点の main とずれうる。
- 失敗時は即時リトライせず、報告して終了し、次回の定期実行に任せる。
  - メール通知は when=dispatch_failed(失敗時のみ)に絞り、成功のたびに通知が飛ばないようにする。

## 原則

- オートメーション起動セッションは git proxy が 403 になり Memory Drive にも触れないため、公開経路と非オートメーション起動の常駐セッションで設計する。
- 作業の終わりに自己 sleep を呼ぶ指示をプロンプトへ入れ、同時実行枠を解放して次回メッセージでの自動起床に任せる。
- lite、最小の net_policy、run_as=creator、失敗時のみの通知で、定期タスクのコストと露出を抑える。
