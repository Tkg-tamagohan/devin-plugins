---
name: windows-cli-pitfalls
description: Windows 上のシェルでマルチバイト文字、バックスラッシュ、gh CLI の引数を扱うときの罠と回避策。Python の cp932 ロケールによる UnicodeDecodeError、gh api graphql への日本語本文で Bad unicode escape、exec 引用でのバックスラッシュ消失、Git Bash と Windows で異なる $TEMP を扱う。Windows マシンでシェルコマンドやスクリプトを組み立てるときに使用する。
---

# Windows CLI の文字コードとエスケープの罠

Windows 上の Devin セッションでは Git Bash 系のシェル経由でコマンドを実行するが、既定の文字コードが cp932 の Python、シェルの引用規則、Git Bash と Windows プロセス間のパス差異が重なり、日本語やバックスラッシュを含む操作で特有の失敗を起こす。
対処は場面ごとに決まっているため、症状から原因へ辿れる形でまとめる。

## Python の既定文字コード

Windows の Python はロケールが cp932 のままだと、UTF-8 ファイルの `read_text()` で `UnicodeDecodeError` になる。
スクリプトを直す必要はなく、環境変数で UTF-8 モードにする。

```bash
PYTHONUTF8=1 python scripts/some_script.py
```

同様に、stdout へ日本語や絵文字を出すと `UnicodeEncodeError` になることがある。
環境変数 `PYTHONIOENCODING=utf-8` を付けるか、スクリプト内で `sys.stdout.reconfigure(encoding="utf-8")` する。

## gh api graphql へのマルチバイト本文

`gh api graphql -f query='...日本語...'` の形で日本語本文を渡すと UTF-8 が壊れ、`Bad unicode escape` というエラーで失敗する。
ミューテーションや長いクエリはシェル引数に直接埋め込まず、Python から `subprocess` で呼び、`json.dumps` で本文を JSON 文字列化して渡す。

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

同じ回避策は `gh pr comment`、`gh issue create` の本文など、JSON 以外の `-f` 引数に日本語を渡す場面でも有効である。

## バックスラッシュを含む引数

`\\.\pipe\<name>` のような named pipe 名や Windows の絶対パスを `exec` のコマンド列に書くと、シェルの引用処理でバックスラッシュが潰れる。
対処は、対象の処理をスクリプトファイル（`.ps1` や `.py`）に書き出してからそのファイルを実行すること。

```powershell
# list_pipes.ps1（ファイルに保存してから実行する）
Get-ChildItem \\.\pipe\ | Where-Object Name -like 'prefix-*'
```

ヒアドキュメントやワンライナーでもよいが、引用の階層が深くなるほど潰れ方が読みにくくなるため、再利用するものはファイル化が確実である。

## Git Bash と Windows の $TEMP の差異

Git Bash では `$TEMP` が `/tmp` 系へ解決されることがあり、Windows 側のプロセスが見る `%TEMP%`（`C:\Users\<user>\AppData\Local\Temp`）と同じ場所を指さない。
スクリプトから一時ファイルを受け渡すときは、カレントディレクトリに置くか、両側で確実に同じになる Windows 形式の絶対パスを明示する。
`gh release download -O` のような出力先指定も同じ問題を踏むため、リポジトリルートなど Git Bash と Windows の両方で一意に解決できる場所を使う。

## 原則

- 文字化けや `Bad unicode escape` はシェル引数の経路を疑い、英数字だけで通るかを先に切り分ける。
- 引用の階層が二段を超えたらスクリプトファイルへ逃がす。
- Python 由来の decode/encode エラーは `PYTHONUTF8=1` と `PYTHONIOENCODING=utf-8` で環境側を直す（スクリプト自体は共有物なので環境依存の差分を入れない）。
