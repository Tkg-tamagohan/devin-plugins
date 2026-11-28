---
name: windows-cli-pitfalls
description: Windows 上のシェル（Git Bash と PowerShell 5.1）でマルチバイト文字、環境変数、バックスラッシュ、gh CLI、git、curl を扱うときの罠と回避策。PowerShell 5.1 の環境変数設定、&& 非対応と curl エイリアス、ExecutionPolicy による .ps1 拒否（pnpm.cmd）とワイルドカード非展開（scripts/*.py）、Python の cp932 ロケールによる UnicodeDecodeError とパイプ $OutputEncoding 文字化け、gh CLI や git commit -F への BOM なし UTF-8 本文渡し、シングルクォート内を含む外部コマンド引数の引用符剥離と $ 展開、Select-Object -First による上流コマンドの非ゼロ終了、引用でのバックスラッシュ消失、Git Bash と Windows で異なる $TEMP を扱う。Windows マシンでシェルコマンドやスクリプトを組み立てるときに使用する。blueprint YAML の記述や $ENVRC への環境変数登録、スナップショットビルドの調査は windows-blueprint に委ねる。
---

# Windows CLI の文字コードとシェルの罠

Windows 上の Devin セッションでは Git Bash 系のシェル経由でコマンドを実行するが、Windows PowerShell 5.1 を呼び出したり併用したりする場面も多い。
PowerShell 5.1 の構文差異、既定の文字コードが cp932 の Python、シェルの引用規則、Git Bash と Windows プロセス間のパス差異が重なり、日本語や環境変数、バックスラッシュを含む操作で特有の失敗を起こす。
対処は場面ごとに決まっているため、症状から原因へ辿れる形でまとめる。

## 責任範囲の境界

- **blueprint とビルド調査**：blueprint の `run` ステップでの実行モデル、`powershell -File` の制約、`$ENVRC` の記述、スナップショットビルド失敗の調査は `windows-blueprint` に委ねる。
  - 本スキルはセッション中のシェル実行（Git Bash と PowerShell）とスクリプト呼び出しだけを扱う。

## PowerShell の環境変数、演算子、エイリアス

PowerShell では Bash 形式の `VAR=val command` が構文エラーやコマンド認識失敗になるため、セミコロンで区切って `$env:VAR` を設定する。
Windows 標準の PowerShell 5.1 ではコマンド連結演算子 `&&` が使えず構文エラーになるため、`;` で区切るか、成功時だけ続行したい処理は `if ($LASTEXITCODE -eq 0)` で分岐する。
また、`curl` は PowerShell では `Invoke-WebRequest` のエイリアスに割り当てられているため、HTTP クライアントとして curl を呼ぶときは `curl.exe` を明示する。

```powershell
# NG（Bash 形式、PowerShell 5.1 非対応の &&、エイリアス展開される curl）
CLOUDFLARE_ACCOUNT_ID=123 npx -y cf@1.0.0-beta.29 pages list
git status && curl -s https://example.com

# OK（$env:VAR の設定、; 区切りまたは $LASTEXITCODE 判定、curl.exe 明示）
$env:CLOUDFLARE_ACCOUNT_ID="123"; npx -y cf@1.0.0-beta.29 pages list
git status; if ($LASTEXITCODE -eq 0) { curl.exe -s https://example.com }
```

## ExecutionPolicy とワイルドカード非展開

Windows の PowerShell セッションや `powershell -Command` 経由で `pnpm` のように同名の `.ps1` ラッパーを持つ CLI をそのまま呼ぶと、実行ポリシーが `Restricted` などの環境では `pnpm.ps1 cannot be loaded because running scripts is disabled on this system`（`UnauthorizedAccess`）で失敗する。
バッチシム側（`.cmd`）を明示して実行する。

```powershell
# NG（pnpm.ps1 が実行ポリシーで拒否される環境がある）
pnpm check; pnpm test

# OK（.cmd を明示する）
pnpm.cmd check; pnpm.cmd test
```

また、POSIX シェル（bash や zsh）とは異なり、PowerShell は `python.exe` などの外部コマンドへ渡す引数中のワイルドカード（`scripts/*.py` 等）を展開しない。
`python -m py_compile scripts/*.py` をそのまま実行すると、リテラル文字列 `scripts/*.py` を開こうとして `[Errno 22] Invalid argument` で失敗する。
`Get-ChildItem` でファイルパス列を展開してから渡すか、`unittest discover` のようにコマンド側の探索機能を使う。

```powershell
# NG（リテラルの "scripts/*.py" がそのまま python.exe へ渡る）
python -m py_compile scripts/*.py

# OK（Get-ChildItem で展開した配列を渡す）
$pyFiles = Get-ChildItem scripts\*.py | Select-Object -ExpandProperty FullName
python -m py_compile $pyFiles
```

## Python の既定文字コードとパイプ出力

Windows の Python はロケールが cp932 のままだと、UTF-8 ファイルの `read_text()` で `UnicodeDecodeError` になる。
スクリプトを直す必要はなく、環境変数で UTF-8 モードにする。

```bash
# Git Bash
PYTHONUTF8=1 python scripts/some_script.py
```

```powershell
# PowerShell
$env:PYTHONUTF8="1"; python scripts/some_script.py
```

同様に、stdout へ日本語や絵文字を出すと `UnicodeEncodeError` になることがある。
環境変数 `PYTHONIOENCODING` を `utf-8` に設定するか、スクリプト内で `sys.stdout.reconfigure(encoding="utf-8")` する。
また、PowerShell 5.1 はパイプラインへ文字列を渡す際に `$OutputEncoding`（既定は US-ASCII）でエンコードするため、日本語を含むファイルをパイプで渡すと文字化けする。
Python スクリプトの標準入力へ UTF-8 テキストを渡すときはパイプを使わず、Python 側の `subprocess.run(..., input=..., encoding="utf-8")` で渡す。

## gh CLI と git へのマルチバイト本文渡し

`gh api graphql -f query='...日本語...'` の形で日本語本文を渡すと UTF-8 が壊れ、`Bad unicode escape` というエラーで失敗する。
また、`gh pr create` などで PowerShell やシェルの引数にバッククォートを含む文字列を直接渡すと展開されて本文が欠落する。
PR や Issue の本文は一時ファイルに書き出して `--body-file` で渡し、GraphQL ミューテーションは Python から `subprocess.run` で呼び、`json.dumps` で本文を JSON 文字列化して渡す。
`git commit -F <temp_file>` や `gh pr comment --body-file <temp_file>` へ渡す日本語一時ファイルはリポジトリ外（`$env:TEMP` など）へ UTF-8（BOM なし）で作成し、実行後に削除する。
PowerShell 5.1 の `Set-Content -Encoding UTF8` と `Out-File -Encoding UTF8` は先頭へ BOM（`\ufeff`）を付与するため使わず、Python の `encoding="utf-8"` または `[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))` で書き出す。

```python
import json, subprocess

body = "日本語の返信本文"
q = ("mutation { addPullRequestReviewThreadReply(input: "
     "{pullRequestReviewThreadId: \"%s\", body: %s}) { comment { id } } }"
     % (tid, json.dumps(body, ensure_ascii=False)))
r = subprocess.run(
    ["gh", "api", "graphql", "-f", "query=" + q],
    capture_output=True, text=True, encoding="utf-8",
)
print(r.stdout)
```

```powershell
# NG（Set-Content -Encoding UTF8 は BOM \ufeff を付与し、作業ツリーへ一時ファイルが残り得る）
"日本語コミットメッセージ" | Set-Content -Path commit_msg.txt -Encoding UTF8; git commit -F commit_msg.txt

# OK（リポジトリ外へ BOM なし UTF-8 で書き出し、実行後に削除する）
$msg = Join-Path $env:TEMP "commit_msg.txt"
[System.IO.File]::WriteAllText($msg, "日本語コミットメッセージ", [System.Text.UTF8Encoding]::new($false))
git commit -F $msg; Remove-Item $msg
```

## 外部コマンド引数の引用符剥離と $ 展開

Windows PowerShell 5.1 はネイティブ実行ファイル（`gh.exe`、`python.exe` 等）へ引数を渡す際に文字列中の `"` を再エスケープしないため、**シングルクォート `'...'` の内側であっても**引数から `"` が剥離する。
この挙動により、`gh ... --jq '... split("\n") ...'` は `unexpected token "\\"` で失敗し、`python -c '... read_text("utf-8") ...'` は `"` が消えて `SyntaxError` になる。
また、PowerShell のエスケープ文字はバックスラッシュではなくバッククォートであるため、二重引用 `"..."` の内側に `\$owner` のような GraphQL 変数や `\"` を書いても PowerShell が解釈し、`Variable reference is not valid` や `SyntaxError: unterminated string literal` を起こす。
短いワンライナーでは外側を二重引用 `"`、内側を単一引用 `'` にして `"` の剥離を防ぐ。
`--jq` の複雑な整形や二重引用を含む処理、あるいは `$` や正規表現のバックスラッシュ、バッククォートを含む処理はリポジトリ外（`$env:TEMP` 等）へ `.py` ファイルとして保存し（Git Bash ならシングルクォートヒアドキュメントも可）、`gh ... --json` の出力を `json.loads` で処理する。

```powershell
# NG（シングルクォート内でも " が剥離し、二重引用内では $ と \" が崩れる）
gh pr view 5 --json body --jq '.body | split("\n")'
python -c 'import pathlib; print(pathlib.Path("a.txt").read_text("utf-8"))'
gh api graphql -f query="query(\$num: Int!) { ... }"

# OK（短いワンライナーは外側を二重引用、内側を単一引用にし、複雑な処理は一時 .py ファイルへ保存する）
python -c "import pathlib; print(pathlib.Path('a.txt').read_text('utf-8'))"
$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"; python (Join-Path $env:TEMP "inspect_pr.py")
```

```python
# $env:TEMP\inspect_pr.py（--jq の複雑な整形を避け json.loads で処理する）
import json, subprocess

r = subprocess.run(["gh", "pr", "view", "5", "--json", "body"], capture_output=True, text=True, encoding="utf-8", check=True)
print(json.loads(r.stdout)["body"].splitlines())
```

## Select-Object -First による上流コマンドの非ゼロ終了

`git diff | Select-Object -First 50` のように上流のネイティブコマンド出力を `Select-Object -First N` で途中打ち切りすると、パイプ閉鎖により上流側が書き込み失敗を起こして終了コード `1` を返すことがある。
大きな差分を確認するときはパイプで打ち切らず、リポジトリ外（`$env:TEMP` 等）の一時 `.patch` ファイルへ書き出してから行範囲を指定して読み込み、確認後に削除する。

```powershell
# NG（パイプ閉鎖により git diff が終了コード 1 を返し得る）
git diff main..HEAD | Select-Object -First 50

# OK（一時 .patch ファイルへ書き出して行範囲を指定して確認し、確認後に削除する）
$patch = Join-Path $env:TEMP "review.patch"
git -c core.quotePath=false diff --output="$patch" main..HEAD
# 行範囲を指定して $patch を確認後、Remove-Item $patch
```

## バックスラッシュを含む引数と $TEMP の差異

`\\.\pipe\<name>` のような named pipe 名や Windows の絶対パスをコマンド列の多段引用の中に書くと、エスケープ処理でバックスラッシュが潰れる。
対処は、対象の処理をスクリプトファイル（`.ps1` や `.py`）として書き出してからそのファイルを実行すること。

```powershell
# list_pipes.ps1（ファイルに保存してから実行する）
Get-ChildItem \\.\pipe\ | Where-Object Name -like 'prefix-*'
```

Git Bash と Windows プロセスを併用する場合、Git Bash では `$TEMP` が `/tmp` 系へ解決され、Windows 側の `%TEMP%`（`C:\Users\<user>\AppData\Local\Temp`）と別の場所を指すことがある。
`gh release download -O` のような出力先指定やプロセス間の一時ファイル受け渡しでは、カレントディレクトリ配下など両側で一意に解決できる絶対パスを明示する。

## 原則

- PowerShell 5.1 では環境変数を `$env:VAR="val"; ...` で設定し、`&&` を使わず `;` や `$LASTEXITCODE` 判定に分け、`curl` ではなく `curl.exe` を使う。
- `git diff` 等のネイティブコマンド出力を `Select-Object -First` で途中打ち切りせず、大きな差分は一時 `.patch` ファイルへ書き出して行範囲を指定して確認し、確認後に削除する。
- PowerShell で `.ps1` ラッパーが実行ポリシーで拒否されるコマンドは `.cmd`（例: `pnpm.cmd`）を明示し、外部コマンドへのワイルドカード引数（`*.py` 等）は `Get-ChildItem` で展開する。
- 文字化けや `Bad unicode escape` はシェル引数やパイプの文字コードを疑い、`--body-file` や `git commit -F` にはリポジトリ外へ作成した BOM なし UTF-8 一時ファイルを渡して実行後に削除し、GraphQL ミューテーションは Python の `subprocess.run` へ逃がす。
- 短いワンライナーは外側を二重引用、内側を単一引用にし、シングルクォート内に二重引用符を含む `--jq` 式や `$`、`\"`、バックスラッシュを含む処理は一時 `.py` ファイルへ保存して `json.loads` 等で処理する。
- Python 由来の decode と encode のエラーは `PYTHONUTF8=1`（PowerShell では `$env:PYTHONUTF8="1"`）と `PYTHONIOENCODING=utf-8` で環境側を直す（共有スクリプト自体に環境依存の差分を入れない）。
