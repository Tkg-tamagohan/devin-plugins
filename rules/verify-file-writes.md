---
trigger: model_decision
description: write/edit ツールで日本語などマルチバイト文字を含むファイルを新規作成や大幅な更新をしたとき、または文書ファイルの編集やレビューをするとき
---

# ファイルの作成や編集の後は文字化けと競合マーカーの混入を確認する

write ツールでマルチバイト文字を含む大きなファイルを出力すると、置換文字（U+FFFD）の混入による文字化けが起きることがある。
また、文書ファイルにはマージ競合マーカーが残ったままコミットされることがある。
コミット前に grep で両方を確認する。

## 手順

1. `grep -n $'\ufffd' <file>` で置換文字の混入を確認し、見つけたら修正してからコミットする。
   - Windows PowerShell 環境では `python -c "import pathlib,sys; p=pathlib.Path(sys.argv[1]); b=[i+1 for i,l in enumerate(p.read_text('utf-8').splitlines()) if chr(0xFFFD) in l]; print(b); sys.exit(bool(b))" <file>` で確認する。
   - PowerShell 5.1 ではシングルクォート内でも外部コマンド引数の二重引用符が剥がれるため、上記のように外側を二重引用符、内側を単一引用符に保つかスクリプトファイル経由で実行する（詳細はスキル `shared-skills:windows-cli-pitfalls` 参照）。
2. 文書ファイルの編集やレビューをするときは `grep -rn '^<<<<<<<\|^=======$\|^>>>>>>>' <dir>` で競合マーカーの残存を確認する。
   - `=======` を行頭アンカーなしで grep すると、文中の区切り線を誤検出する。

## 対象外

- ASCII のみの小さなコード片への追記
- 既存の文字化けを直す作業そのもの（検査ではなく修正を依頼された場合）
- 対象リポジトリの pre-commit フックや CI が同じ検査を既に行っている場合
