# スロップリンターの運用手順

`scripts/slop_lint.py` の実行方法と検出結果の読み方をまとめる。
単一ファイルの検査は SKILL.md の機械検査節に記したコマンドを使う。

## CLI の仕様

使い方は `python3 scripts/slop_lint.py [ファイル] [--json] [--strict] [--fail-on {warn,error}]` で、ファイルを省略するか `-` を渡すと標準入力を読む。
詳しい説明は `--help` で表示する。

- `--json` は結果を JSON(形式2)で出力する。
- JSON の主なキーは `format`(`yomiyasu-lint`)、`format_version`(2)、`tool_version`、`candidate_count`、`counts`(error、warn、info の件数)、`no_rule_findings`、`rule_penalty_score`、`not_judged`、`context`、`metrics`、`findings`。
- `--strict` は warn か error の候補が1件でもあれば終了コード1で終わる。
- `--fail-on` は指定した重さの候補があれば終了コード1で終わる。
- `--fail-on` には `warn`(warn か error の候補)と `error` を、カンマ区切りまたは繰り返しで指定できる。
- `meaning-risk` は意味リスクの判定が別計画のため lint では使えない(判定には2つの文章の比較が必要で、現在はどのコマンドでも使えない)。
- 点数(`rule_penalty_score`)は `--strict` と `--fail-on` の条件に使えない。

終了コードの意味は次のとおり。

- 0 は検査を最後まで実行して `--strict` と `--fail-on` の条件に当たらなかった場合で、候補の有無によらない。
- 1 は `--strict` か `--fail-on` の条件に当たった場合。
- 2 は使い方か入力の誤り(ファイルを開けない、作業フォルダの外や名前が点で始まる部分を含むパス、UTF-8 として読めない、使えない `--fail-on` の値、語の一覧の誤り)。
- 3 は予期しない内部エラーか、出力先が閉じられて結果を最後まで書けなかった場合。

通常出力(`--json` なし)は見出し3行を出し、候補があれば内訳(error、warn、info の件数)と行番号順の候補の並びを続ける。
条件に当たったときは末尾に終了コード1の内訳を足す。
語の一覧は作業ディレクトリから上へたどった git の最上位の `.yomiyasu-words/`(allow.txt、flag.txt、flag-patterns.txt)を自動で探し、使ったときは出力に1行足す。

`rule_penalty_score` は候補の多さを地の文の長さで割った目安で、品質や合否の点数ではない。
CI では `--strict` か `counts` を使う。

## 一括検査

本節の `.sloplintignore` と検査対象の説明は、執筆時点の devin-plugins リポジトリの構成を対象とする。
複数の文書を一括検査するときは、リポジトリ直下の `.sloplintignore` が検査対象の除外を管理する（gitignore 形式のパス一覧で、1 行 1 件で足すか削る）。
検査対象は `git ls-files '*.md'` から `.sloplintignore` に一致するものだけを除いた集合であり、`references/slop-catalog.md` は言及自体が規範抵触として検出されるため恒久除外としている。
次のコマンドは除外を適用して全対象を `--strict` で検査し、warn か error の候補が見つかった文書があれば終了コードを非ゼロにする（CI の文書リントと同じ手順）。

```bash
status=0
excluded=$(mktemp); trap 'rm -f "$excluded"' EXIT
git ls-files -z -c -i -X .sloplintignore -- '*.md' > "$excluded"
while IFS= read -r -d '' f; do
  grep -qzxF -- "$f" "$excluded" && continue
  python3 skills/japanese-tech-writing/scripts/slop_lint.py --strict "$f" || status=1
done < <(git ls-files -z -- '*.md')
exit $status
```

## 検出結果の読み方

- 検出結果は機械的な見直し候補であり、本規範で正当な記述（定義語の太字、定義列挙の箇条書き、「」による言及、必要な推量表現、文脈上正当な専門用語など）に対する指摘は本規範を優先して保持する。
- 太字頻度と箇条書き比率の指摘は情報（info）として出るため、文書全体の装飾傾向を把握する目安として使い、本規範が許容する記法で閾値を超えているだけなら修正しない。
- 修正の試行は最大二回までとし、警告を消すためだけの過剰な言い換えループを避ける。
- 語彙の判断には `references/slop-catalog.md` を参照する。
