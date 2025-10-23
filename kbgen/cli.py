"""Command line interface for the knowledge base generator."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .generator import generate_site


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kbgen",
        description=(
            "Markdown ノートのディレクトリを解析し、タグ・検索・バックリンク付きの"
            "静的サイトを生成します。"
        ),
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Markdown ノートが保存されているディレクトリ",
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="生成されたサイトを書き出すディレクトリ",
    )
    parser.add_argument(
        "--site-title",
        dest="site_title",
        default="My Knowledge Base",
        help="サイト全体のタイトル",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default="",
        help=(
            "生成されるリンクの先頭に付与するベース URL。GitHub Pages などサブパスで"
            "公開する場合に設定してください (例: /notes)。"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        generate_site(
            source_dir=args.source,
            output_dir=args.destination,
            site_title=args.site_title,
            base_url=args.base_url,
        )
    except Exception as exc:  # noqa: BLE001 - 表示をわかりやすくするため
        parser.error(str(exc))
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
