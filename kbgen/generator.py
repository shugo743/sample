"""Core site generation logic for the knowledge base generator."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
from urllib.parse import quote

try:
    import markdown  # type: ignore
except ImportError as exc:  # pragma: no cover - 実行時に明示的なエラーメッセージを出す
    raise RuntimeError(
        "Markdown を HTML に変換するために 'markdown' パッケージが必要です。"
        "\n次のコマンドでインストールしてください: pip install markdown"
    ) from exc


MARKDOWN_EXTENSIONS = [
    "fenced_code",
    "tables",
    "toc",
]

LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ANCHOR_PATTERN = re.compile(r"href=\"([^\"]+)\"")


@dataclass
class Note:
    """Metadata and rendered content for a single note."""

    source_path: Path
    rel_path: Path
    slug: str
    title: str
    tags: List[str]
    content: str
    html_content: str
    excerpt: str
    outgoing_slugs: set[str] = field(default_factory=set)
    backlinks: list["NoteRef"] = field(default_factory=list)
    updated_at: datetime | None = None

    @property
    def html_path(self) -> Path:
        return self.rel_path.with_suffix(".html")


@dataclass
class NoteRef:
    slug: str
    title: str
    html_path: Path


def generate_site(
    source_dir: Path,
    output_dir: Path,
    site_title: str,
    base_url: str = "",
) -> None:
    source_dir = source_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    if not source_dir.exists():
        raise FileNotFoundError(f"source ディレクトリが存在しません: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"source はディレクトリではありません: {source_dir}")

    notes = _load_notes(source_dir)
    _attach_backlinks(notes)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    tag_map = _collect_tags(notes.values())
    tag_paths = _build_tag_paths(tag_map.keys())

    _write_assets(output_dir)
    _write_search_index(notes.values(), output_dir, base_url)

    _write_index_page(notes.values(), output_dir, site_title, tag_paths)
    _write_search_page(output_dir, site_title)
    _write_tag_pages(tag_map, tag_paths, output_dir, site_title)
    _write_notes(notes.values(), tag_paths, output_dir, site_title)


# ----------------------------------------------------------------------------
# Loading and metadata processing
# ----------------------------------------------------------------------------


def _load_notes(source_dir: Path) -> Dict[str, Note]:
    notes: Dict[str, Note] = {}
    for path in sorted(source_dir.rglob("*.md")):
        rel_path = path.relative_to(source_dir)
        slug = rel_path.with_suffix("").as_posix()
        note = _parse_note(path, rel_path, slug, source_dir)
        notes[slug] = note
    return notes


def _parse_note(path: Path, rel_path: Path, slug: str, root: Path) -> Note:
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_front_matter(text)
    title = metadata.get("title") or _extract_heading(body) or path.stem
    tags = metadata.get("tags", [])
    html_content = _render_markdown(body)
    html_content = _rewrite_internal_links(html_content)
    excerpt = _create_excerpt(body)
    outgoing = _extract_outgoing_slugs(body, path.parent, root)
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime)

    return Note(
        source_path=path,
        rel_path=rel_path,
        slug=slug,
        title=title,
        tags=tags,
        content=body,
        html_content=html_content,
        excerpt=excerpt,
        outgoing_slugs=outgoing,
        updated_at=updated_at,
    )


def _split_front_matter(text: str) -> tuple[dict[str, list[str] | str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    meta_lines: list[str] = []
    body_lines: list[str] = []
    inside_meta = True
    for line in lines[1:]:
        if inside_meta and line.strip() == "---":
            inside_meta = False
            continue
        if inside_meta:
            meta_lines.append(line)
        else:
            body_lines.append(line)

    metadata = _parse_metadata(meta_lines)
    body = "\n".join(body_lines).lstrip("\n")
    return metadata, body


def _parse_metadata(lines: Sequence[str]) -> dict[str, list[str] | str]:
    metadata: dict[str, list[str] | str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "tags":
            tags = [tag.strip() for tag in value.split(",") if tag.strip()]
            metadata[key] = tags
        else:
            metadata[key] = value
    return metadata


def _extract_heading(body: str) -> str | None:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("# ")
    return None


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)


def _rewrite_internal_links(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        href = match.group(1)
        if "://" in href or href.startswith("mailto:"):
            return match.group(0)
        if href.endswith(".md"):
            new_href = href[:-3] + ".html"
            return f'href="{new_href}"'
        return match.group(0)

    return ANCHOR_PATTERN.sub(replace, html)


def _create_excerpt(text: str, max_length: int = 160) -> str:
    without_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    without_links = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", without_code)
    without_markup = re.sub(r"[#*>`_~]", "", without_links)
    collapsed = " ".join(without_markup.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 1].rstrip() + "…"


def _extract_outgoing_slugs(
    body: str, current_dir: Path, root: Path
) -> set[str]:
    slugs: set[str] = set()
    for match in LINK_PATTERN.finditer(body):
        target = match.group(1)
        if not target or target.startswith("#") or "://" in target or target.startswith("mailto:"):
            continue
        cleaned = target.split("#", 1)[0]
        if not cleaned:
            continue
        candidate = Path(cleaned)
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".md")
        elif candidate.suffix != ".md":
            continue
        resolved = (current_dir / candidate).resolve()
        try:
            rel = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        slug = rel.with_suffix("").as_posix()
        slugs.add(slug)
    return slugs


def _attach_backlinks(notes: Dict[str, Note]) -> None:
    for note in notes.values():
        note.backlinks.clear()
    for note in notes.values():
        for slug in note.outgoing_slugs:
            target = notes.get(slug)
            if target is None:
                continue
            target.backlinks.append(NoteRef(slug=note.slug, title=note.title, html_path=note.html_path))
    for note in notes.values():
        note.backlinks.sort(key=lambda ref: ref.title.lower())


# ----------------------------------------------------------------------------
# Site writing helpers
# ----------------------------------------------------------------------------


def _collect_tags(notes: Iterable[Note]) -> dict[str, list[Note]]:
    tag_map: dict[str, list[Note]] = {}
    for note in notes:
        for tag in note.tags:
            tag_map.setdefault(tag, []).append(note)
    for notes_in_tag in tag_map.values():
        notes_in_tag.sort(key=lambda n: (n.title.lower(), n.slug))
    return dict(sorted(tag_map.items(), key=lambda item: item[0].lower()))


def _slugify_tag(tag: str) -> str:
    safe = re.sub(r"\s+", "-", tag.strip())
    safe = re.sub(r"[^0-9A-Za-z\-_.ぁ-んァ-ヴー一-龯ー]+", "", safe)
    if not safe:
        safe = quote(tag, safe="")
    return safe.lower()


def _build_tag_paths(tags: Iterable[str]) -> dict[str, Path]:
    used: set[str] = set()
    tag_paths: dict[str, Path] = {}
    for tag in sorted(tags, key=lambda t: t.lower()):
        base = _slugify_tag(tag)
        candidate = base
        counter = 1
        while candidate in used:
            counter += 1
            candidate = f"{base}-{counter}"
        used.add(candidate)
        tag_paths[tag] = Path("tags") / f"{candidate}.html"
    return tag_paths


def _write_assets(output_dir: Path) -> None:
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    style_path = assets_dir / "style.css"
    style_path.write_text(_STYLE_CSS, encoding="utf-8")

    search_js_path = assets_dir / "search.js"
    search_js_path.write_text(_SEARCH_JS, encoding="utf-8")


def _write_search_index(notes: Iterable[Note], output_dir: Path, base_url: str) -> None:
    index_path = output_dir / "search-index.json"
    records = []
    for note in sorted(notes, key=lambda n: (n.title.lower(), n.slug)):
        records.append(
            {
                "title": note.title,
                "url": _join_base_url(base_url, note.html_path.as_posix()),
                "tags": note.tags,
                "excerpt": note.excerpt,
                "content": _plain_text(note.content),
            }
        )
    index_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_index_page(
    notes: Iterable[Note],
    output_dir: Path,
    site_title: str,
    tag_paths: dict[str, Path],
) -> None:
    sorted_notes = sorted(notes, key=lambda n: (n.title.lower(), n.slug))
    items = []
    for note in sorted_notes:
        href = _relative_url(Path("index.html"), note.html_path)
        updated = (
            f"<time datetime=\"{note.updated_at.isoformat()}\">{note.updated_at.strftime('%Y-%m-%d')}</time>"
            if note.updated_at
            else ""
        )
        tags_html = ""
        if note.tags:
            tag_links = " ".join(
                f"<a class=\"tag\" href=\"{_relative_url(Path('index.html'), tag_paths[tag])}\">{escape(tag)}</a>"
                for tag in note.tags
                if tag in tag_paths
            )
            tags_html = f"<span class=\"tags\">{tag_links}</span>"
        items.append(
            f"<li><a class=\"note-link\" href=\"{href}\">{escape(note.title)}</a>"
            f"<div class=\"note-meta\">{updated}{tags_html}</div>"
            f"<p class=\"excerpt\">{escape(note.excerpt)}</p></li>"
        )
    if not items:
        items.append("<li>ノートが見つかりませんでした。Markdown ファイルを追加して再度ビルドしてください。</li>")

    content = """
    <section>
      <h1>ノート一覧</h1>
      <ul class="note-list">
        {items}
      </ul>
    </section>
    """.format(items="\n        ".join(items))

    html = _render_page(
        page_title=site_title,
        content=content,
        site_title=site_title,
        current_path=Path("index.html"),
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def _write_search_page(output_dir: Path, site_title: str) -> None:
    app_html = """
    <section>
      <h1>全文検索</h1>
      <div id="search-app" data-index-url="{index_url}">
        <input type="search" placeholder="キーワードを入力" aria-label="検索語">
        <div class="search-hint">タイトル・タグ・本文が対象です。</div>
        <ul class="search-results"></ul>
      </div>
    </section>
    """.format(index_url=_relative_url(Path("search.html"), Path("search-index.json")))

    html = _render_page(
        page_title="検索",
        content=app_html,
        site_title=site_title,
        current_path=Path("search.html"),
        extra_scripts=[Path("assets/search.js")],
    )
    (output_dir / "search.html").write_text(html, encoding="utf-8")


def _write_tag_pages(
    tag_map: dict[str, list[Note]],
    tag_paths: dict[str, Path],
    output_dir: Path,
    site_title: str,
) -> None:
    tags_dir = output_dir / "tags"
    tags_dir.mkdir(exist_ok=True)

    index_items = []
    for tag, notes in tag_map.items():
        path = tag_paths[tag]
        href = _relative_url(Path("tags/index.html"), path)
        index_items.append(
            f"<li><a href=\"{href}\">{escape(tag)}</a> ({len(notes)})</li>"
        )

        note_items = []
        for note in notes:
            note_href = _relative_url(path, note.html_path)
            note_items.append(
                f"<li><a class=\"note-link\" href=\"{note_href}\">{escape(note.title)}</a></li>"
            )
        content = """
        <section>
          <h1>タグ: {tag}</h1>
          <ul class="note-list">
            {items}
          </ul>
        </section>
        """.format(tag=escape(tag), items="\n            ".join(note_items))

        html = _render_page(
            page_title=f"タグ: {tag}",
            content=content,
            site_title=site_title,
            current_path=path,
        )
        (output_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (output_dir / path).write_text(html, encoding="utf-8")

    index_content = """
    <section>
      <h1>タグ一覧</h1>
      <ul class="tag-list">
        {items}
      </ul>
    </section>
    """.format(items="\n        ".join(index_items) if index_items else "<li>タグがありません。</li>")

    index_html = _render_page(
        page_title="タグ",
        content=index_content,
        site_title=site_title,
        current_path=Path("tags/index.html"),
    )
    (output_dir / "tags" / "index.html").write_text(index_html, encoding="utf-8")


def _write_notes(
    notes: Iterable[Note],
    tag_paths: dict[str, Path],
    output_dir: Path,
    site_title: str,
) -> None:
    for note in notes:
        tags_html = ""
        if note.tags:
            tag_links = " ".join(
                f"<a class=\"tag\" href=\"{_relative_url(note.html_path, tag_paths[tag])}\">{escape(tag)}</a>"
                for tag in note.tags
                if tag in tag_paths
            )
            tags_html = f"<div class=\"note-tags\">{tag_links}</div>"

        backlinks_html = ""
        if note.backlinks:
            items = "\n".join(
                f"<li><a href=\"{_relative_url(note.html_path, ref.html_path)}\">{escape(ref.title)}</a></li>"
                for ref in note.backlinks
            )
            backlinks_html = """
            <section class="backlinks">
              <h2>バックリンク</h2>
              <ul>
                {items}
              </ul>
            </section>
            """.format(items=items)

        updated_html = (
            f"<time datetime=\"{note.updated_at.isoformat()}\">{note.updated_at.strftime('%Y-%m-%d')}</time>"
            if note.updated_at
            else ""
        )

        content = """
        <article class="note">
          <header>
            <h1>{title}</h1>
            <div class="note-meta">{updated}{tags}</div>
          </header>
          <section class="note-body">{body}</section>
          {backlinks}
        </article>
        """.format(
            title=escape(note.title),
            updated=updated_html,
            tags=tags_html,
            body=note.html_content,
            backlinks=backlinks_html,
        )

        html = _render_page(
            page_title=note.title,
            content=content,
            site_title=site_title,
            current_path=note.html_path,
        )

        destination = output_dir / note.html_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(html, encoding="utf-8")


# ----------------------------------------------------------------------------
# Rendering helpers
# ----------------------------------------------------------------------------


def _render_page(
    *,
    page_title: str,
    content: str,
    site_title: str,
    current_path: Path,
    extra_scripts: Sequence[Path] | None = None,
) -> str:
    extra_scripts = extra_scripts or []
    style_href = _relative_url(current_path, Path("assets/style.css"))
    nav_links = [
        ("ホーム", Path("index.html")),
        ("タグ", Path("tags/index.html")),
        ("検索", Path("search.html")),
    ]
    nav_html = "".join(
        f"<a href=\"{_relative_url(current_path, target)}\">{label}</a>"
        for label, target in nav_links
    )
    scripts_html = "".join(
        f"<script src=\"{_relative_url(current_path, script)}\" defer></script>"
        for script in extra_scripts
    )

    return f"""<!DOCTYPE html>
<html lang=\"ja\">
  <head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>{escape(page_title)} | {escape(site_title)}</title>
    <link rel=\"stylesheet\" href=\"{style_href}\">
    {scripts_html}
  </head>
  <body>
    <header class=\"site-header\">
      <div class=\"site-title\">{escape(site_title)}</div>
      <nav class=\"site-nav\">{nav_html}</nav>
    </header>
    <main>
      {content}
    </main>
    <footer class=\"site-footer\">
      生成日: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </footer>
  </body>
</html>
"""


def _relative_url(from_path: Path, to_path: Path) -> str:
    from_dir = from_path.parent if from_path.suffix else from_path
    start = str(from_dir) if str(from_dir) != "." else "."
    rel = os.path.relpath(str(to_path), start=start)
    return rel.replace(os.sep, "/")


def _plain_text(text: str) -> str:
    without_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    without_links = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", without_code)
    without_markup = re.sub(r"[#*>`_~]", "", without_links)
    return " ".join(without_markup.split())


def _join_base_url(base_url: str, path: str) -> str:
    if not base_url:
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


_STYLE_CSS = """
:root {
  color-scheme: light dark;
  font-family: "Hiragino Sans", "Noto Sans JP", system-ui, sans-serif;
  line-height: 1.6;
  background-color: #f7f7f7;
  color: #222;
}

body {
  margin: 0;
}

main {
  max-width: 860px;
  margin: 0 auto;
  padding: 2rem 1rem 4rem;
  background: #fff;
}

.site-header,
.site-footer {
  background: #222;
  color: #fff;
  padding: 1rem;
}

.site-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.site-title {
  font-size: 1.4rem;
  font-weight: bold;
}

.site-nav a {
  color: #f5f5f5;
  text-decoration: none;
  margin-right: 1rem;
}

.site-nav a:hover {
  text-decoration: underline;
}

.note-list,
.search-results,
.tag-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.note-list li,
.search-results li,
.tag-list li {
  margin-bottom: 1.2rem;
  padding-bottom: 1.2rem;
  border-bottom: 1px solid #eee;
}

.note-list li:last-child,
.search-results li:last-child,
.tag-list li:last-child {
  border-bottom: none;
}

.note-link {
  font-size: 1.1rem;
  font-weight: bold;
  color: #222;
  text-decoration: none;
}

.note-link:hover {
  text-decoration: underline;
}

.note-meta {
  font-size: 0.9rem;
  color: #666;
  margin: 0.4rem 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.note-tags .tag,
.tags .tag {
  background: #f0f4ff;
  color: #1a3a8c;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  text-decoration: none;
  font-size: 0.8rem;
}

.note-body {
  margin-top: 2rem;
}

.note-body pre {
  background: #2e3440;
  color: #f1f5f9;
  padding: 1rem;
  overflow-x: auto;
  border-radius: 6px;
}

.note-body code {
  background: #f3f4f6;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}

.backlinks {
  margin-top: 3rem;
}

.backlinks ul {
  list-style: disc;
  margin-left: 1.5rem;
}

.search-hint {
  font-size: 0.85rem;
  color: #666;
  margin: 0.5rem 0 1rem;
}

input[type="search"] {
  width: 100%;
  padding: 0.6rem;
  font-size: 1rem;
  border: 1px solid #ccc;
  border-radius: 6px;
  box-sizing: border-box;
}

.search-results a {
  text-decoration: none;
  color: #1a3a8c;
}

.search-results .excerpt {
  margin: 0.4rem 0 0;
  font-size: 0.9rem;
  color: #444;
}

@media (prefers-color-scheme: dark) {
  :root {
    background: #111;
    color: #f5f5f5;
  }

  main {
    background: #1c1c1c;
  }

  .site-header,
  .site-footer {
    background: #111;
  }

  .note-link {
    color: #fafafa;
  }

  .note-body code {
    background: #2d2d2d;
  }

  input[type="search"] {
    background: #111;
    color: #f5f5f5;
    border-color: #333;
  }
}
"""


_SEARCH_JS = """
async function loadIndex(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`インデックスの取得に失敗しました: ${response.status}`);
  }
  return response.json();
}

function filterDocuments(documents, query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return [];
  }
  return documents
    .filter((doc) => {
      return (
        doc.title.toLowerCase().includes(normalized) ||
        doc.excerpt.toLowerCase().includes(normalized) ||
        doc.tags.join(" ").toLowerCase().includes(normalized) ||
        doc.content.toLowerCase().includes(normalized)
      );
    })
    .slice(0, 30);
}

function renderResults(container, results) {
  const list = container.querySelector('.search-results');
  list.innerHTML = '';
  if (results.length === 0) {
    return;
  }
  for (const result of results) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = result.url;
    link.textContent = result.title;

    const excerpt = document.createElement('div');
    excerpt.className = 'excerpt';
    excerpt.textContent = result.excerpt;

    item.appendChild(link);
    item.appendChild(excerpt);
    list.appendChild(item);
  }
}

async function setupSearch() {
  const container = document.getElementById('search-app');
  if (!container) {
    return;
  }
  const indexUrl = container.dataset.indexUrl;
  const input = container.querySelector('input[type="search"]');
  const documents = await loadIndex(indexUrl);
  let timeoutId = null;

  input.addEventListener('input', () => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => {
      const results = filterDocuments(documents, input.value);
      renderResults(container, results);
    }, 120);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setupSearch().catch((error) => {
    console.error(error);
  });
});
"""
