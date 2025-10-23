# KBGen — Markdown ノートから静的ナレッジベースを生成

KBGen は、Markdown ファイルで管理している個人ノートを読み込み、タグ・検索・バックリンク付きの静的サイトとして書き出す CLI ツールです。GitHub Pages などのホスティングに配置すれば、ブラウザから快適にナレッジを閲覧できます。

## 主な機能

- Front Matter（YAML 風の簡易記法）によるタイトル・タグ管理
- Markdown → HTML 変換（コードブロックやテーブルも対応）
- ノート同士のリンクを解析し、バックリンクを自動生成
- タグ一覧・タグ別ページの自動生成
- クライアントサイド全文検索（タイトル・タグ・本文を対象）
- テーマはライト／ダークモード両対応のシンプルなデザイン

## セットアップ

Python 3.10 以上を想定しています。まずは依存パッケージとして [Python-Markdown](https://python-markdown.github.io/) をインストールしてください。

```bash
pip install markdown
```

必要に応じて仮想環境を利用すると便利です。

## ノートの書き方

各 Markdown ファイルは任意の階層に配置できます。ファイル冒頭に以下のような Front Matter を付けると、メタデータとして利用されます。

```markdown
---
title: サンプルノート
tags: python, ツール
---

# 見出し
本文...
```

- `title` はページタイトルとして利用されます。省略すると最初の見出し、もしくはファイル名が使われます。
- `tags` はカンマ区切りで指定します。タグページや検索のフィルタ対象になります。

ノート間リンクは通常の Markdown 記法で記述します。相対パスで `.md` ファイルを参照すると、生成後は自動的に `.html` に変換され、バックリンクの解析対象にもなります。

```markdown
[関連ノート](../ideas/next-step.md)
```

## 使い方

```bash
python -m kbgen <ノートディレクトリ> <出力ディレクトリ> \
  --site-title "My Knowledge Base" \
  --base-url /notes
```

- `--site-title` は全ページ共通のヘッダーに表示されます。
- `--base-url` は GitHub Pages のプロジェクトサイトなど、サブパスでホストする場合に設定します（例: `/notes`）。

出力先ディレクトリには、`index.html`（一覧）、`search.html`（検索 UI）、`tags/` 以下のタグページ、各ノートに対応する HTML が生成されます。`assets/` 以下に CSS と検索スクリプトが書き出されるため、公開時はディレクトリごと配置してください。

`examples/notes/` ディレクトリに簡単なサンプルノートを用意しています。試しに次のように実行して挙動を確認できます。

```bash
python -m kbgen examples/notes dist
```

出力された `dist/` フォルダをブラウザで開くと、実際の生成結果をチェックできます。

## 自動化のヒント

- Git リポジトリにノートを保存している場合は、`post-commit` フックなどで `python -m kbgen` を実行し、最新の静的サイトを常に更新する運用が便利です。
- GitHub Actions から `gh-pages` ブランチへ出力ディレクトリをデプロイすることで、完全自動の公開フローを構築できます。

## 開発メモ

- コードは `kbgen/` 以下にまとまっています。`kbgen.cli` が CLI エントリーポイント、`kbgen.generator` がメインロジックです。
- 現在は Python-Markdown を利用しているため、追加の Markdown 拡張を使いたい場合は `MARKDOWN_EXTENSIONS` に追記してください。

不具合や改善案があれば Issue や PR で気軽に知らせてください！
