---
name: chrome-extension-real-input-testing
description: MV3 Chrome 拡張を実 UI(trusted イベント)で検証するときに使用する。拡張 reload 後の content script 再注入、YouTube ボットウォール下での DOM レベル検証、isolated world でのプロパティ偽装不可、ミニプレイヤー検証、オーバーレイ位置の座標系、修飾キー付きホイールの xdotool 送出、広告ブロッカー常駐環境での障害を扱う。未パッケージ読み込みや i18n、サービスワーカー起床、CDP アタッチなどのセットアップ手順自体は対象外。
---

# Chrome 拡張(MV3)を実 UI で検証する際のノウハウ

unpacked load した拡張を実スクロールや実クリック(trusted イベント)で検証するテストセッション向け。
合成イベントでは届かない環境差異(拡張 reload、実行 world、ボットウォール)への対処をまとめる。

## 責任範囲の境界

- 未パッケージ読み込みや言語プロファイル、SW 起床、CDP アタッチなどのセットアップ手順は、拡張読み込み系のスキル(環境に chrome-mv3-testing 等があればそちら)に委ねる。
- 本スキルはその先の「実イベントを対象に届ける」部分だけを扱う。

## 拡張 reload 後はテスト対象タブを必ずリロードする

`chrome.runtime.reload()` や chrome://extensions のリロードボタンで拡張を更新しても、開いているタブの content script は再注入されない。
古い isolated world のコードが残り、DOM 上の成果物(注入済みオーバーレイ要素等)だけが残存する。
「オーバーレイ DOM はあるのにイベントが効かない」が典型症状であり、検証前に各タブで F5 してから調べる。
`chrome.runtime.id` を拾う eval が失敗する、または注入要素の有無と実動作が乖離していたら stale を疑う。

## YouTube のボットウォール環境での検証(DOM レベル代替)

未ログインやクリーンな環境では watch ページに "Sign in to confirm you're not a bot" が出て、video が `readyState 0 / duration NaN / currentSrc なし` になる。
Shorts ページは実データが来ることが多い。
watch を DOM レベルで検証する手順は次のとおり。

1. `#movie_player` 全体が `visibility:hidden` になる。
2. `yt-player-interstitial-renderer`(ボットウォール)がプレイヤー全面を覆い `pointer-events` を吸うため、wheel イベントがコンテナへ届かなくなる。
3. この原因は覆い層による環境要因であり、拡張側の問題ではない。
4. 回避するにはボットウォール層 `yt-playability-error-supported-renderers, yt-player-interstitial-renderer` に `display:none`(視覚)と `pointer-events:none`(ヒットテスト)を付ける。
5. あわせて `#movie_player` とその子孫に `visibility:visible` を強制する。
6. `document.elementFromPoint()` で wheel の届き先が `.html5-video-player` 内になったことを確認してから実スクロールする。
7. 同じボットウォールでも動画によっては interstitial が出ないページがあり、その場合は `elementFromPoint` が最初から player 内を指す。
8. まず interstitial の有無を確認し、不要なら回避策を挟まない。

## isolated world: ページコンソールからの JS プロパティ偽装は届かない

`browser_console` や devtools の eval はページの main world で走る一方、content script は isolated world で走る。
DOM 要素は共有だが JS ラッパーは別物なので、main world で `Object.defineProperty(video, 'paused', ...)` しても拡張側の `video.paused` は実値のままになる。
`classList.add('ad-showing')` 等の DOM 属性変更は全 world で共有され、クラスベースのガード判定に使える。
一方 `paused`/`duration`/`currentTime` などのプロパティ偽装は届かない。
これらのガード判定は「実状態を作る」(別ページで実再生してから一時停止する等)か、content script 側の world を直接評価できる手段(CDP で isolated world コンテキストを選ぶ等)に任せる。

## 修飾キー付きホイールは xdotool で送出する

`computer` ツールの `scroll` アクションに `key: "shift"` を渡しても、生成される wheel イベントは `shiftKey=false` のまま届く(2026-10 時点の Devin VM / Chrome 137 で実測)。
Shift+スクロール等の修飾キー判定を検証するときは `xdotool` で修飾キーを押したままホイールを打つ。

```bash
# カーソルは computer ツールの mouse_move で対象要素上に置いてから実行
DISPLAY=:0 xdotool keydown Shift sleep 0.3 click 4 sleep 0.2 keyup Shift   # Shift+上スクロール
DISPLAY=:0 xdotool keydown ctrl sleep 0.3 click 4 sleep 0.2 keyup ctrl    # Ctrl+上スクロール
```

- `click 4` が上スクロール、`click 5` が下スクロール。
  1 クリックあたり `deltaY=±120` で届いた。
- Ctrl+スクロール捕捉を検証する際は、ブラウザのページズームが発生しないこと(`devicePixelRatio` 不変)も合わせて確認すると preventDefault の証拠になる。
- 効いたかどうかは、対象ページ側に `document.addEventListener('wheel', e => ..., true)` を capture 相で貼り `e.shiftKey/ctrlKey` を記録して判定する。

## 広告ブロッカー常駐環境での障害

メインプロファイルに uBlock Origin 等が常駐している場合、`chrome-extension://<id>/options/options.html` への直接遷移が `ERR_BLOCKED_BY_CLIENT` で遮断されることがある(2026-10 時点の Devin VM / Chrome 137 + uBlock Origin で実測)。
`chrome://extensions` → 詳細 →「拡張機能のオプション」経由なら開ける。
広告表示中の挙動など実広告が要る検証はブロッカー未搭載の別プロファイルで行う。

## ミニプレイヤー検証

- watch ページで `i` キーを押すとプレイヤーが `ytd-miniplayer` 配下に移り、ページがフィード(home 等)へ遷移する。
- 拡張の wheel リスナーが `#movie_player`(=コンテナ)に付いているなら、要素ごと移動して追従するか確認できる。
- ミニプレイヤー上の実 wheel をコンテナに届けるには、`ytSpecTouchFeedbackShapeFill` や info-bar 系オーバーレイが覆う分の `pointer-events:none` が要る場合がある。
- 対象コンテナの祖先と子孫以外の全子孫に適用し、`elementFromPoint` で確認する。

## 座標系の注意

スクリーンショットとクリックの座標は 1024×768 スケールだが、`getBoundingClientRect()` や `elementFromPoint()` は実 CSS px を返す(VM により約 1.5 倍超)。
zoom 領域を DOM 座標から計算するときは除算して画面内に収める(上限超過でエラーになる)。

## 挙動メモ(yt-frame-scrub 系検証で得たもの)

- オーバーレイの表示寿命は操作停止から約 3 秒のため、スクロール直後に即スクリーンショットを取らないとフェードして「見えない」判定を誤る。
- Shorts フィード遷移は同一 video 要素を使い回すことがある。
- 遷移後の状態リセット検証は、オーバーレイの F や時刻が新動画先頭相当になるか、旧 fps 確定値を引きずらないかで見る。
- 拡張が `yt-frame-scrub:step` のような CustomEvent を `document` 上で発行するなら、そのイベントとオーバーレイの opacity を数値証拠として記録すると録画の視認性が上がる。
- ボットウォールが出ない環境では未ログインでも実動画が読み込まれることがある。
  interstitial が出た場合のみ回避策を挟む。

## 原則

- 拡張を reload したらタブもリロードし、stale な content script のまま検証しない。
- イベントが届かないときは、まず覆いや visibility の環境要因と拡張の不具合を切り分ける。
- main world の偽装は isolated world に届かないため、検証には DOM 属性か実状態を使う。
