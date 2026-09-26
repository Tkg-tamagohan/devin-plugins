---
name: windows-blueprint
description: Windows プラットフォーム向け blueprint の作成とデバッグの手順。Git Bash での実行モデル、PowerShell 呼び出しのパターン、$ENVRC への環境変数登録、スナップショットビルド失敗の調査を扱う。Windows 用の blueprint を書く、直す、またはスナップショットビルドの失敗を調査するときに使用する。
---

# Windows blueprint の作成とデバッグ

Windows プラットフォーム向けの blueprint を書く・直すとき、およびスナップショットビルドの失敗を調査するときは、以下の知識に従う。

## ステップは Git Bash で実行される

`runs-on: windows` のブロックも含め、blueprint の `run` ステップは Windows 上では Git Bash で実行される。
PowerShell や cmd の構文をそのまま書くと意図どおりに動かない。
PowerShell が必要な処理は、Git Bash から `powershell -NoProfile -Command ...` で呼ぶ。

YAML のブロックスカラー(`|`)の中身はリテラル文字列だが、実行時には bash のクォート規則が挟まる。
`\$` は `$`、`\"` は `"` に戻されてから powershell.exe に渡る。
「YAML に書いた文字列」と「PowerShell が受け取る文字列」が一致しない点を常に意識する。

## PowerShell スクリプトの呼び出し

`powershell -File` は、引数のスクリプトパス中の環境変数を展開しない。
`$env:TEMP` などを含むパスを渡すとリテラル文字列がパスとして解釈され、「The given path's format is not supported」(exit 127) で失敗する。

環境変数を含むパスを渡すときは `-Command "& ..."` 形式にして、PowerShell 側で展開させる。

```yaml
# NG: -File は $env:TEMP を展開しない
- run: powershell -NoProfile -ExecutionPolicy Bypass -File "\$env:TEMP\dotnet-install.ps1" -Channel 8.0 -InstallDir "C:\dotnet"

# OK: PowerShell 側で $env:TEMP を展開させる
- run: powershell -NoProfile -ExecutionPolicy Bypass -Command "& \"\$env:TEMP\dotnet-install.ps1\" -Channel 8.0 -InstallDir 'C:\dotnet'"
```

## $ENVRC への環境変数の登録

後続のステップやセッションのシェルに環境変数を引き継ぐには、`$ENVRC` が指すファイルへ `VAR=value` 形式の行を追記する。
このファイルは後で bash スクリプトとして source されるため、各行は bash として妥当な代入でなければならない。

```yaml
# NG: $PATH が書き込み時に展開され、空白を含む値がクォートなしで書かれる
- run: echo "PATH=/c/dotnet:$PATH" >> $ENVRC

# OK: シングルクォートで囲んで $PATH を書き込み時ではなく source 時に展開させ、値はダブルクォートで保護する
- run: |
    echo 'PATH="/c/dotnet:$PATH"' >> $ENVRC
    echo 'DOTNET_ROOT="C:\dotnet"' >> $ENVRC
```

NG 例の行は、書き込み時点の PATH 全体を展開して書き込む。
PATH には `/c/Program Files/...` のような空白を含むパスが並ぶため、envrc を source する後続ステップが「No such file or directory」のパースエラーで失敗し、PATH が反映されず `dotnet: command not found` の形で表面化する。

バックスラッシュを含む Windows 形式パスもクォートが必須である。
クォートなしの `DOTNET_ROOT=C:\dotnet` は bash がバックスラッシュを消去して `C:dotnet` になる。

PATH 系の値には Git Bash 形式(`/c/dotnet`)、ツールやアプリが読む変数には Windows 形式(`C:\dotnet`)を使い分ける。

## スナップショットビルド失敗の調査

1. `read_build_logs` でビルドジョブ一覧を見るか、`sbj-...` 形式のジョブ ID を渡してログを取得する。完全な JSONL ログがマシン上のファイルに保存される。
2. ログから失敗したステップとコマンド、exit code を特定する。
3. セッション VM が同じプラットフォームなら、失敗したコマンドを再現し、修正版コマンドをその場で検証する。
4. `read_environment_config` で現在の blueprint を取得し、`update_environment_config` で修正案を提案する。
5. 提案が approve されると自動で再ビルドが走る。新しいビルドジョブの status を `read_build_logs` で確認する。

修正後の再ビルドが再度 partial になることがある。
先のセクションが失敗すると後続セクションは実行されないため、initialize を直すと maintenance にあった別の既存バグが初めて表面化する、という順序で不具合が一つずつ出る場合がある。
再び失敗したら、ログで失敗箇所が移動したかを確認して「前の修正の退行」か「別バグの顕在化」かを切り分ける。

blueprint に書くコマンドは、VM 上で実際に実行して成功を確認してから提案する。
スナップショットビルドは無人で実行されるため、未検証のコマンドの失敗は次のビルドまで分からない。
