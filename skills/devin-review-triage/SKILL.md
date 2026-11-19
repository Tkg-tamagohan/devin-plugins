---
name: devin-review-triage
description: Devin Review やレビュー bot、人間レビューが PR に投稿した指摘のトリアージと対応の手順。現行 HEAD のコード、仕様書、決定記録、コミット履歴、GitHub GraphQL スレッド、レビュー総評本文との実物照合、3 区分分類と意図的挙動や要確認の切り分け、一次照合完了時点での調査打ち切り、回帰テストの採番、既コミットと未コミットを分離した返信と push 後確定ハッシュ差し替え、スレッド返信と解決、日本語サマリコメント投稿、機械的事後検証を扱う。Devin Review やレビューコメントが付いた PR のトリアージ、修正、未解決スレッド整理を行うときに使用する。テストの作り方と同期要件や報告形式はルール test-conventions、未決の仕様判断と決定記録への保存は requirements-definition、別セッション移行と誤着工防止はルール session-phase-split、実装および PR 更新前の境界監査は systems-pre-pr-audit、文字化けと競合マーカーの検査はルール verify-file-writes、Windows での gh CLI と PowerShell の扱いは windows-cli-pitfalls に委ねる。
---

# Devin Review 指摘のトリアージと対応

Devin Review や他のレビュー bot、人間レビューが PR に投稿した指摘は、一覧をそのまま実装対象にせず、実コードと仕様、GitHub 上のスレッド状態を照合してから修正するか根拠を説明するかを一件ずつ判断する。
「指摘だから直す」と一律に扱わない。
意図的な挙動を仕様なしに変えると、レビューが仕様を上書きする形になる。
ゴールは、既対応指摘の二重作業を防ぎ、未解決スレッド 0 件（判断待ちを除く）かつ検証根拠が実コミットと一致した状態まで完了させることである。

## 責任範囲の境界

- **テストの作り方**：修正に添える回帰テストの ID 規約、同期要件、結果報告の形式はルール `test-conventions` に従う。
- **文書との矛盾**：実装と文書の扱いが食い違う指摘を含むとき、どちらを正とするかは `test-conventions` と AGENTS.md の「仕様や計画の文書がある作業ではそれを正とする」に従う。
- **未決の仕様判断**：ユーザーへ判断を仰ぐ際の選択肢提示、自動解決可否の確認形式、決定記録への保存は `requirements-definition` に従う。
- **別セッション移行と誤着工防止**：別セッション向け計画の承認扱いと移行手順はルール `session-phase-split` に委ねる。
- **常駐システムの境界監査**：実装および PR 更新前の周辺境界条件の網羅点検は `systems-pre-pr-audit` に委ね、トリアージ段階では実施しない。
- **文字化けと競合マーカーの検査**：日本語を含む編集や投稿本文の置換文字（`U+FFFD`）と競合マーカーの確認はルール `verify-file-writes` に委ねる。
- **Windows での CLI 引数**：PowerShell や `gh api graphql` へ日本語や引用を含む本文を渡す際の組み立て方は `windows-cli-pitfalls` に委ねる。

## 手順

1. **実物照合と全指摘の取得**：`git log`、現行 HEAD の実装とテストコード、仕様の正（要件定義書、決定記録、実装計画など）、および GitHub PR の状態を突き合わせる。
   - GraphQL `reviewThreads` から全スレッドの `id`、`isResolved`、`isOutdated`、対象パスと行、コメント本文を取得する。
   - あわせて `gh pr view <num> --json comments,reviews` も取得し、インラインスレッド外のレビュー総評本文に記載された diff 外指摘を見落とさない。
2. **3 区分と対応方針の分類**：各指摘を現行 HEAD での再現状態と仕様照合に基づいて整理し、根拠コミット、実在する行番号、回帰テスト ID、判断根拠を指摘ごとに一覧表へ記録する。
   - **現行 HEAD で再現する未修正**：再現箇所と修正方針を確定し、実バグは修正して回帰テストを ID 採番で追加し、文書の齟齬は文書側を修正する。
   - **主訴解消済みだが残存リスク追補**：既対応コミットと残存箇所を切り分けて追補する。
   - **現行 HEAD で完全解消済み**：対応コミットと既存回帰テスト ID を特定し、修正せず検証結果だけを返信して閉じる。
   - **意図的挙動**：その挙動を選んだ根拠（仕様決定の ID、トレードオフの説明）をスレッドに返信して閉じる。
   - **要確認**：修正すべきか意図的か判断できない指摘、ユーザーの指示と矛盾する指摘（直すと指示を巻き戻すもの）、仕様方針の選択、および未解決スレッドの自動返信と解決の可否は自分で決めずにユーザーへ判断を仰ぐ。
3. **一次照合完了時点での調査打ち切り**：新規または未対応の指摘について、指摘が直接参照する関数、呼び出し元、対応する既存テストの確認と修正方針の根拠が揃った時点でトリアージ調査を打ち切り、結果と方針を先に提示する。
   - 無関係な周辺ファイルへの連鎖的な精読を行わない。
   - 調査中に気付いた近接リスクや改善候補は、その場で精査を広げず範囲外の候補として箇条書きで添え、実装フェーズや PR 更新前の `systems-pre-pr-audit` へ委ねる。
4. **返信ドラフトの分離、修正、コミットと push**：コミットと push の前に作成する返信ドラフトでは、「既コミット分のみで完結する本文」と「未コミット変更を push した後に確定ハッシュへ差し替えて追記する本文」を厳密に区別する。
   - 修正はテストが緑になってから、対象ブランチと変更ファイル集合を確認して対象ファイルのみをステージし、無関係な変更を混ぜずに `Devin Review 対応: <要約>` の形式でコミットする。
   - 通常 `git push` で新コミットハッシュを確定させ、force push と既定ブランチへの直接 push は行わない。
5. **スレッド返信、解決、および日本語サマリコメント投稿**：修正または説明が完了した指摘に限り、push 後の確定ハッシュを差し替えた本文で各スレッドへ `git_comment_on_pr`（または GraphQL `addPullRequestReviewThreadReply`）で返信し、`resolve_thread_id`（または GraphQL `resolveReviewThread`）で解決する。
   - 説明だけで閉じる指摘にも返信を残し、判断待ちの指摘はユーザーの回答と対応が終わるまで解決しない。
   - 複数指摘や diff 外総評指摘を含む一括対応では、新コミットハッシュ、対応指摘（diff 外指摘を含む）、追加または改訂したテスト ID 一覧、標準検証コマンドの実測結果、および未検証範囲をまとめた日本語サマリコメントを `gh pr comment --body-file` で投稿する。
6. **機械的事後検証**：反映完了後、次の 3 点を機械的に確認して結果を表で報告する。
   - GraphQL で PR の `headRefOid` と全 `reviewThreads` を再取得し、`headRefOid` が push 済みコミットと一致すること、および未解決スレッドが 0 件（判断待ちとして意図的に残したものを除く）であることを確認する。
   - 投稿した全スレッド返信と PR サマリコメントに置換文字（`U+FFFD`）や文字化けがないことを確認する。
   - `git status -sb` がクリーンであること、および一時ファイルが残存していないことを確認する。

## 原則

- 貼られた指摘一覧を鵜呑みにせず、現行 HEAD のコード、テスト、`git log`、GraphQL スレッド、レビュー総評本文の 5 点で実物照合する。
- 指摘の分類（修正／説明／要確認）を一覧できる形にし、ユーザーが分類を覆せるようにする。
- 指摘は基準となったコミットに付着するため、対応前に現行ブランチでの再現を確認する。
- 現行コードで既に解消済みの指摘は修正せず、検証結果だけを返信して閉じる。
- バグ以外の種別(解析や確認依頼)の指摘にも、実質的なテスト不足や実機検証の要求が含まれうるため、種別だけで対応不要と判断しない。
- トリアージ段階の責務は再現確認と方針決定にとどめ、一次照合を終えたあとの周辺境界監査は実装フェーズや `systems-pre-pr-audit` へ分離する。
- 未 push の変更を既確定の対応として PR 返信へ記載せず、push 後に確定ハッシュを差し替えて投稿し、GraphQL 再取得で事後検証する。
- 返信は指摘ごとのスレッドに対して行い、まとめて一件のコメントで済ませない（日本語サマリコメントは個別スレッド返信と併用する）。
- 実機や実環境で未検証の挙動は検証済みとして返信せず、未検証である旨とその扱い(実機 E2E の対象にする、スレッドを未解決のまま残す、など)を返信に明記する。
- 低重大度の nit や大掛かりな対応が要る非クリティカルな指摘は、勝手に大きな変更で応えず、対応要否をユーザーに確認する。
- 指摘は修正 push のたびに新スレッドや同一スレッドへの再掲(「Edited to」形式)で複数ラウンド追加されうる。
- 新ラウンドの投稿は push から遅れて届くことがある(2026-11 時点の複数 PR で 5 分から 10 分程度を実測)ため、終了判定の前に時間を置いて未解決数を再確認する。
- 再掲が解決済みスレッドに付いても未解決数は増えないため、再確認では直近のコメントや編集の有無も見る。
- push 後に Devin Review のチェックが pending のまま残ることがあるが、required でなければ表示ラグなので、マージ可否の判断には使わない。

## gh CLI でのスレッド操作

手順 5 の `git_comment_on_pr` と `resolve_thread_id` は環境依存のツール名である。
`gh` が使える環境では、スレッドへの返信と解決は GraphQL の `addPullRequestReviewThreadReply` と `resolveReviewThread` が等価の操作になる。

スレッドの列挙、未解決の抽出、事後検証の `headRefOid` 確認、およびインライン外のレビュー総評取得は次のとおり。
クエリの `first:50` は先頭 50 件までしか取得しない。
終了判定に使うときは件数が上限に達していないことを確認し、達している場合は `pageInfo` の `endCursor` で後続ページを取得する。

```bash
gh api graphql -f query='{ repository(owner:"<owner>",name:"<repo>"){ pullRequest(number:<PR>){ headRefOid reviewThreads(first:50){ pageInfo{ hasNextPage endCursor } nodes{ id isResolved isOutdated comments(first:1){ nodes{ path line body } } } } } } }' \
  --jq '{headRefOid: .data.repository.pullRequest.headRefOid, pageInfo: .data.repository.pullRequest.reviewThreads.pageInfo, unresolved: [.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false)]}'
gh pr view <PR> --json comments,reviews
```

返信と解決は次のミューテーションで行う。

```bash
gh api graphql -f query='mutation { addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: "<PRRT_...>", body: "<本文>"}) { comment { id } } }'
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<PRRT_...>"}) { thread { isResolved } } }'
```

本文に日本語などマルチバイトを含むときは `-f` のインライン引数が壊れるため、Python の `subprocess` から `json.dumps` で組み立てて渡す（組み立て方は `windows-cli-pitfalls` を参照）。
