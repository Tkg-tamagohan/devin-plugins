---
name: chrome-extension-real-input-testing
description: MV3 Chrome 拡張を実 UI(trusted イベント)で検証するときに使用する。拡張 reload 後の content script 再注入、YouTube ボットウォール下での DOM レベル検証、isolated world でのプロパティ偽装不可、ミニプレイヤー検証、オーバーレイ位置の座標系を扱う。未パッケージ読み込み・i18n・サービスワーカー起床・CDP アタッチなどのセットアップ手順自体は対象外。
---

# Chrome 拡張(MV3)を実 UI で検証する際のノウハウ

unpacked load した拡張を実スクロール・実クリック(trusted イベント)で検証するテストセッション向け。
合成イベントでは届かない環境差異(拡張 reload、実行 world、ボットウォール)への対処をまとめる。

## 責任範囲の境界

- **セットアップ手順**(未パッケージ読み込み・言語プロファイル・SW 起床・CDP アタッチ): 拡張読み込み系のスキル(環境に chrome-mv3-testing 等があればそちら)に委ねる。本スキルはその先の「実イベントを対象に届ける」部分だけを扱う。

## 拡張 reload 後はテスト対象タブを必ずリロードする

- `chrome.runtime.reload()` や chrome://extensions のリロードボタンで拡張を更新しても、開いているタブの content script は再注入されない。古い isolated world のコードが残り、DOM 上の成果物(注入済みオーバーレイ要素等)だけが残存する。
- 「オーバーレイ DOM はあるのにイベントが効かない」が典型症状。検証前に各タブで F5 してから調べる。
- `chrome.runtime.id` を拾う eval が失敗する、または注入要素の有無と実動作が乖離していたら stale を疑う。

## YouTube のボットウォール環境での検証(DOM レベル代替)

未ログイン・クリーン環境では watch ページに "Sign in to confirm you're not a bot" が出て video が `readyState 0 / duration NaN / currentSrc なし` になる(Shorts ページは実データが来ることが多い)。watch を DOM レベルで検証する手順:

1. `#movie_player` 全体が `visibility:hidden` かつ `yt-player-interstitial-renderer`(ボットウォール)がプレイヤー全面を覆い `pointer-events` を吸う。wheel イベントがコンテナに届かないのは拡張の不具合ではなく環境要因。
2. 回避: ボットウォール層 `yt-playability-error-supported-renderers, yt-player-interstitial-renderer` に `display:none`(視覚) + `pointer-events:none`(ヒットテスト)を付け、`#movie_player` とその子孫に `visibility:visible` を強制。`document.elementFromPoint()` で wheel の届き先が `.html5-video-player` 内になったことを確認してから実スクロールする。
3. 同じボットウォールでも動画によっては interstitial が出ないページがある(`elementFromPoint` が最初から player 内を指す)。まず interstitial の有無を確認し、不要なら回避策を挟まない。

## isolated world: ページコンソールからの JS プロパティ偽装は届かない

- `browser_console` / devtools の eval はページの main world で走る。content script は isolated world。DOM 要素は共有だが JS ラッパーは別物なので、`Object.defineProperty(video, 'paused', ...)` を main world でやっても拡張側の `video.paused` は実値のまま。
- 効くもの: `classList.add('ad-showing')` 等の DOM 属性の変更は全 world で共有。クラスベースのゲート検証は使える。
- 効かないもの: `paused`/`duration`/`currentTime` などのプロパティ偽装。これらのゲートは「実状態を作る」(別ページで実再生→一時停止等)か、content script 側の world を直接評価できる手段(CDP で isolated world コンテキストを選ぶ等)に任せる。

## ミニプレイヤー検証

- watch ページで `i` キーを押すとプレイヤーが `ytd-miniplayer` 配下に移り、ページがフィード(home 等)へ遷移する。拡張の wheel リスナーが `#movie_player`(=コンテナ)に付いているなら、要素ごと移動して追従するか確認できる。
- ミニプレイヤー上の実 wheel をコンテナに届けるには、`ytSpecTouchFeedbackShapeFill` や info-bar 系オーバーレイが覆う分だけ `pointer-events:none` が要る場合がある(対象コンテナの祖先・子孫以外の全子孫に適用し、`elementFromPoint` で確認)。

## 座標系の注意

- スクリーンショット・クリック座標は 1024×768 スケールだが、`getBoundingClientRect()` / `elementFromPoint()` は実 CSS px(VM により約 1.5 倍超)。zoom 領域を DOM 座標から計算するときは除算して画面内に収めること(上限超過でエラーになる)。

## ショートカット・挙動メモ(yt-frame-scrub 系検証で得たもの)

- オーバーレイの表示寿命は操作停止から約 3 秒。スクロール直後に即スクリーンショットを取らないとフェードして「見えない」判定を誤る。
- Shorts フィード遷移は同一 video 要素を使い回すことがある。遷移後の状態リセット検証は「オーバーレイの F/時刻が新動画先頭相当になるか」「旧 fps 確定値を引きずらないか」で見る。

## 原則

- 拡張を reload したらタブもリロード。stale content script が残ったまま検証しない。
- イベントが届かないときは、まず環境要因(覆い・visibility)と拡張の不具合を切り分ける。
- main world の偽装は isolated world に届かない。検証には DOM 属性か実状態を使う。
