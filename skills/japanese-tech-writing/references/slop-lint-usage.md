# スロップリンターの運用手順

`scripts/slop_lint.py` の実行方法と検出結果の読み方をまとめる。
単一ファイルの検査は SKILL.md の機械検査節に記したコマンドを使う。

## 一括検査

本節の `.sloplintignore` と検査対象の説明は、執筆時点の devin-plugins リポジトリの構成を対象とする。
複数の文書を一括検査するときは、リポジトリ直下の `.sloplintignore` が検査対象の除外を管理する（gitignore 形式のパス一覧で、1 行 1 件で足すか削る）。
検査対象は `git ls-files '*.md'` から `.sloplintignore` に一致するものだけを除いた集合であり、`references/slop-catalog.md` は言及自体が規範抵触として検出されるため恒久除外としている。
次のコマンドは、除外を適用して全対象を検査し、途中の失敗を集計して終了コードを非ゼロにする。

```bash
status=0
excluded=$(mktemp); trap 'rm -f "$excluded"' EXIT
git ls-files -z -c -i -X .sloplintignore -- '*.md' > "$excluded"
while IFS= read -r -d '' f; do
  grep -qzxF -- "$f" "$excluded" && continue
  python3 skills/japanese-tech-writing/scripts/slop_lint.py "$f" || status=1
done < <(git ls-files -z -- '*.md')
exit $status
```

## 検出結果の読み方

- 検出結果は機械的な見直し候補であり、本規範で正当な記述（定義語の太字、定義列挙の箇条書き、「」による言及、必要な推量表現、文脈上正当な専門用語など）に対する指摘は本規範を優先して保持する。
- 太字頻度と箇条書き比率の指摘は情報（info）として出るため、文書全体の装飾傾向を把握する目安として使い、本規範が許容する記法で閾値を超えているだけなら修正しない。
- 修正の試行は最大二回までとし、警告を消すためだけの過剰な言い換えループを避ける。
- 語彙の判断には `references/slop-catalog.md` を参照する。
