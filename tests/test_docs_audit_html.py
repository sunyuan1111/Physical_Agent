from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_MD = ROOT / "docs" / "current-architecture-audit.md"
AUDIT_HTML = ROOT / "docs" / "current-architecture-audit.html"


def test_current_architecture_audit_html_embeds_current_markdown() -> None:
    markdown = AUDIT_MD.read_text(encoding="utf-8")
    html = AUDIT_HTML.read_text(encoding="utf-8")

    match = re.search(r"window\.__AUDIT_MARKDOWN__ = (.*?);\n", html, re.DOTALL)

    assert match is not None
    assert json.loads(match.group(1)) == markdown


def test_current_architecture_audit_html_exposes_source_hash() -> None:
    markdown = AUDIT_MD.read_text(encoding="utf-8")
    html = AUDIT_HTML.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    assert f'<meta name="source-sha256" content="{source_hash}" />' in html
    assert f'window.__AUDIT_SOURCE_SHA256__ = "{source_hash}";' in html


def test_current_architecture_audit_html_is_standalone_reader() -> None:
    html = AUDIT_HTML.read_text(encoding="utf-8")

    assert '<article id="audit-article"' in html
    assert 'id="audit-toc"' in html
    assert "function renderMarkdown(markdown)" in html
    assert "fetch(" not in html
    assert "https://" not in html
