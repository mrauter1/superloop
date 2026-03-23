from __future__ import annotations

import bleach
from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark", {"breaks": True, "html": False})

_ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "p",
    "pre",
    "code",
    "hr",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
]


def render_markdown_to_html(markdown_text: str) -> str:
    rendered = _MARKDOWN.render(markdown_text)
    return bleach.clean(rendered, tags=_ALLOWED_TAGS, strip=True)
