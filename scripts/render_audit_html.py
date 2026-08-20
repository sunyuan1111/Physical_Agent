from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "current-architecture-audit.md"
TARGET = ROOT / "docs" / "current-architecture-audit.html"


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="source-sha256" content="__SOURCE_SHA256__" />
  <title>Current Architecture Audit | Physical Agent</title>
  <style>
    :root {
      --paper: #f6f1e8;
      --paper-strong: #fffaf0;
      --ink: #1d252b;
      --muted: #66737d;
      --line: #d8d0c3;
      --line-strong: #b8afa1;
      --nav: #151c22;
      --nav-soft: #222b32;
      --teal: #0f766e;
      --blue: #2f6690;
      --amber: #b56a15;
      --red: #a3362f;
      --code: #111820;
      --code-line: #2f3b46;
      --mark: #ffe08a;
    }

    * {
      box-sizing: border-box;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
    }

    a {
      color: inherit;
    }

    .audit-shell {
      min-height: 100svh;
      display: grid;
      grid-template-columns: minmax(248px, 300px) minmax(0, 1fr);
    }

    .audit-nav {
      position: sticky;
      top: 0;
      height: 100svh;
      display: flex;
      flex-direction: column;
      gap: 24px;
      padding: 28px 24px;
      overflow: auto;
      color: #edf4f1;
      background: var(--nav);
      border-right: 1px solid #0e1317;
    }

    .brand {
      padding-bottom: 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    }

    .brand-kicker {
      margin: 0 0 7px;
      color: #91c8c2;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .brand-title {
      margin: 0;
      font-size: 24px;
      line-height: 1.15;
      font-weight: 760;
    }

    .brand-meta {
      margin: 14px 0 0;
      color: #aebdc6;
      font-size: 13px;
    }

    .search-field {
      width: 100%;
      min-height: 40px;
      padding: 10px 12px;
      color: #f7fbfa;
      background: var(--nav-soft);
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 8px;
      font: inherit;
      outline: none;
    }

    .search-field:focus {
      border-color: #8bd5cb;
      box-shadow: 0 0 0 3px rgba(139, 213, 203, 0.16);
    }

    .nav-section-title {
      margin: 0 0 10px;
      color: #96a6af;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .toc {
      display: grid;
      gap: 6px;
    }

    .toc a {
      display: block;
      padding: 8px 10px;
      color: #d6e0df;
      text-decoration: none;
      border-left: 2px solid transparent;
      border-radius: 0 8px 8px 0;
      font-size: 13px;
      line-height: 1.35;
      transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
    }

    .toc a:hover,
    .toc a.active {
      color: #ffffff;
      background: rgba(255, 255, 255, 0.08);
      border-color: #8bd5cb;
    }

    .source-note {
      margin-top: auto;
      color: #95a4ad;
      font-size: 12px;
    }

    .audit-main {
      min-width: 0;
    }

    .audit-hero {
      min-height: 72svh;
      display: grid;
      align-content: end;
      padding: 54px clamp(24px, 6vw, 78px) 34px;
      border-bottom: 1px solid var(--line);
      background: var(--paper-strong);
    }

    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 430px);
      gap: clamp(28px, 5vw, 62px);
      align-items: end;
      max-width: 1180px;
    }

    .eyebrow {
      margin: 0 0 16px;
      color: var(--teal);
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .audit-hero h1 {
      max-width: 820px;
      margin: 0;
      font-size: clamp(44px, 8vw, 92px);
      line-height: 0.94;
      font-weight: 820;
      letter-spacing: 0;
    }

    .hero-summary {
      max-width: 710px;
      margin: 22px 0 0;
      color: #42505a;
      font-size: 18px;
    }

    .signal-stack {
      display: grid;
      border-top: 1px solid var(--line-strong);
      border-bottom: 1px solid var(--line-strong);
    }

    .signal {
      display: grid;
      grid-template-columns: 84px 1fr;
      gap: 16px;
      padding: 17px 0;
      border-bottom: 1px solid var(--line);
    }

    .signal:last-child {
      border-bottom: 0;
    }

    .signal-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .signal strong {
      display: block;
      margin: -2px 0 2px;
      font-size: 16px;
    }

    .signal span {
      color: #56636d;
      font-size: 13px;
    }

    .audit-content {
      max-width: 1080px;
      padding: 42px clamp(22px, 6vw, 78px) 84px;
    }

    .audit-article {
      display: grid;
      gap: 42px;
    }

    .doc-intro,
    .doc-section {
      min-width: 0;
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }

    .doc-section[hidden] {
      display: none;
    }

    .doc-intro h1,
    .doc-section h2,
    .doc-section h3,
    .doc-section h4 {
      color: var(--ink);
      line-height: 1.18;
      letter-spacing: 0;
    }

    .doc-intro h1 {
      margin: 0 0 12px;
      font-size: 34px;
    }

    .doc-section h2 {
      margin: 0 0 18px;
      font-size: 30px;
      font-weight: 780;
    }

    .doc-section h3 {
      margin: 30px 0 12px;
      font-size: 21px;
      font-weight: 740;
    }

    .doc-section h4 {
      margin: 24px 0 10px;
      font-size: 17px;
      font-weight: 720;
    }

    p {
      margin: 0 0 16px;
    }

    strong {
      color: #111820;
      font-weight: 780;
    }

    code {
      padding: 2px 5px;
      color: #103b36;
      background: rgba(15, 118, 110, 0.11);
      border: 1px solid rgba(15, 118, 110, 0.16);
      border-radius: 5px;
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 0.92em;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    pre {
      margin: 18px 0 24px;
      padding: 18px;
      overflow: auto;
      color: #e5edf0;
      background: var(--code);
      border: 1px solid var(--code-line);
      border-radius: 8px;
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
      line-height: 1.58;
    }

    pre code {
      padding: 0;
      color: inherit;
      background: transparent;
      border: 0;
      border-radius: 0;
      font-size: inherit;
    }

    .table-wrap {
      width: 100%;
      margin: 18px 0 24px;
      overflow-x: auto;
      border-top: 1px solid var(--line-strong);
      border-bottom: 1px solid var(--line-strong);
    }

    table {
      width: 100%;
      min-width: 680px;
      border-collapse: collapse;
      font-size: 14px;
    }

    th,
    td {
      padding: 12px 14px;
      text-align: left;
      vertical-align: top;
      border-bottom: 1px solid var(--line);
    }

    th {
      color: #27323a;
      background: rgba(47, 102, 144, 0.08);
      font-weight: 780;
    }

    tr:last-child td {
      border-bottom: 0;
    }

    ul,
    ol {
      margin: 0 0 22px;
      padding-left: 22px;
    }

    li {
      margin: 8px 0;
    }

    mark {
      padding: 0 2px;
      color: #1d252b;
      background: var(--mark);
      border-radius: 4px;
    }

    .empty-state {
      display: none;
      padding: 24px 0;
      color: var(--red);
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      font-weight: 700;
    }

    .empty-state.visible {
      display: block;
    }

    @media (max-width: 900px) {
      .audit-shell {
        display: block;
      }

      .audit-nav {
        position: relative;
        height: auto;
        max-height: none;
        padding: 22px;
      }

      .toc {
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      }

      .source-note {
        margin-top: 0;
      }

      .audit-hero {
        min-height: auto;
        padding: 42px 22px 28px;
      }

      .hero-grid {
        grid-template-columns: 1fr;
      }

      .audit-hero h1 {
        font-size: 48px;
        line-height: 1;
      }

      .signal {
        grid-template-columns: 1fr;
        gap: 5px;
      }

      .audit-content {
        padding: 30px 22px 58px;
      }

      table {
        min-width: 0;
        table-layout: fixed;
      }

      th,
      td {
        padding: 10px 8px;
        overflow-wrap: anywhere;
      }

      pre {
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }

      pre code {
        white-space: inherit;
      }
    }

    @media print {
      body {
        background: white;
      }

      .audit-shell {
        display: block;
      }

      .audit-nav {
        display: none;
      }

      .audit-hero {
        min-height: auto;
        padding: 0 0 24px;
      }

      .audit-content {
        max-width: none;
        padding: 0;
      }

      pre,
      .table-wrap {
        break-inside: avoid;
      }
    }
  </style>
</head>
<body>
  <div class="audit-shell">
    <aside class="audit-nav" aria-label="审计文档导航">
      <div class="brand">
        <p class="brand-kicker">Physical Agent</p>
        <p class="brand-title">Architecture Audit</p>
        <p class="brand-meta">Source: docs/current-architecture-audit.md</p>
      </div>

      <input id="audit-search" class="search-field" type="search" placeholder="搜索审计内容" aria-label="搜索审计内容" />

      <div>
        <p class="nav-section-title">目录</p>
        <nav id="audit-toc" class="toc"></nav>
      </div>

      <p class="source-note">SHA-256: <span id="source-sha">__SHORT_SHA__</span></p>
    </aside>

    <main class="audit-main">
      <section class="audit-hero" aria-labelledby="page-title">
        <div class="hero-grid">
          <div>
            <p class="eyebrow">2026-07-08 · Current Architecture Audit</p>
            <h1 id="page-title">Current Architecture Audit</h1>
            <p class="hero-summary">以代码为准的架构审计阅读页，聚焦提案链路、唯一执行面、SafetyGate、状态模型与下一轮重构路线。</p>
          </div>

          <div class="signal-stack" aria-label="关键审计线索">
            <div class="signal">
              <span class="signal-label">Safety</span>
              <div><strong>watch 是唯一真实执行循环</strong><span>请求侧只提案，执行前必须重新过 SafetyGate。</span></div>
            </div>
            <div class="signal">
              <span class="signal-label">State</span>
              <div><strong>SQLite 是当前状态黑板</strong><span>audit export 与 LOG 镜像保留人类可读性。</span></div>
            </div>
            <div class="signal">
              <span class="signal-label">Next</span>
              <div><strong>Capability / Action contract 优先</strong><span>审计建议先锁 metadata 与能力来源。</span></div>
            </div>
          </div>
        </div>
      </section>

      <section class="audit-content">
        <div id="empty-state" class="empty-state">没有匹配的审计章节。</div>
        <article id="audit-article" class="audit-article"></article>
      </section>
    </main>
  </div>

  <script>
    window.__AUDIT_MARKDOWN__ = __AUDIT_MARKDOWN_JSON__;
    window.__AUDIT_SOURCE_SHA256__ = "__SOURCE_SHA256__";

    const source = window.__AUDIT_MARKDOWN__;
    const article = document.querySelector("#audit-article");
    const toc = document.querySelector("#audit-toc");
    const search = document.querySelector("#audit-search");
    const emptyState = document.querySelector("#empty-state");

    const slugCounts = new Map();

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function inlineFormat(value) {
      return escapeHtml(value)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    }

    function isHeading(line) {
      return /^#{1,6}\s+/.test(line);
    }

    function isFence(line) {
      return /^```/.test(line.trim());
    }

    function isList(line) {
      return /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line);
    }

    function isTableStart(lines, index) {
      const current = lines[index] || "";
      const next = lines[index + 1] || "";
      return current.trim().startsWith("|") && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(next);
    }

    function isSpecial(lines, index) {
      const line = lines[index] || "";
      return isHeading(line) || isFence(line) || isList(line) || isTableStart(lines, index);
    }

    function slugify(text) {
      const base = text
        .replace(/`([^`]+)`/g, "$1")
        .toLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, "-")
        .replace(/^-+|-+$/g, "") || "section";
      const count = slugCounts.get(base) || 0;
      slugCounts.set(base, count + 1);
      return count ? `${base}-${count + 1}` : base;
    }

    function splitTableRow(row) {
      return row
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => inlineFormat(cell.trim()));
    }

    function renderTable(rows) {
      const header = splitTableRow(rows[0]);
      const bodyRows = rows.slice(2).map(splitTableRow);
      return `<div class="table-wrap"><table><thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${bodyRows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }

    function renderMarkdown(markdown) {
      const lines = markdown.split(/\r?\n/);
      const html = [];
      const headings = [];
      let sectionOpen = false;
      let introOpen = false;

      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];

        if (!line.trim()) {
          continue;
        }

        if (isFence(line)) {
          const lang = line.trim().slice(3).trim();
          const code = [];
          index += 1;
          while (index < lines.length && !isFence(lines[index])) {
            code.push(lines[index]);
            index += 1;
          }
          html.push(`<pre data-lang="${escapeHtml(lang || "text")}"><code>${escapeHtml(code.join("\n"))}</code></pre>`);
          continue;
        }

        if (isTableStart(lines, index)) {
          const rows = [];
          while (index < lines.length && lines[index].trim().startsWith("|")) {
            rows.push(lines[index]);
            index += 1;
          }
          index -= 1;
          html.push(renderTable(rows));
          continue;
        }

        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
          const level = heading[1].length;
          const rawText = heading[2].trim();
          const id = slugify(rawText);
          const headingHtml = `<h${level} id="${id}">${inlineFormat(rawText)}</h${level}>`;

          if (level === 1) {
            if (sectionOpen) {
              html.push("</section>");
              sectionOpen = false;
            }
            if (introOpen) {
              html.push("</section>");
            }
            html.push(`<section class="doc-intro" aria-labelledby="${id}">${headingHtml}`);
            introOpen = true;
          } else if (level === 2) {
            if (introOpen) {
              html.push("</section>");
              introOpen = false;
            }
            if (sectionOpen) {
              html.push("</section>");
            }
            html.push(`<section class="doc-section" data-section aria-labelledby="${id}">${headingHtml}`);
            sectionOpen = true;
            headings.push({ id, text: rawText });
          } else {
            html.push(headingHtml);
          }
          continue;
        }

        if (isList(line)) {
          const ordered = /^\s*\d+\.\s+/.test(line);
          const items = [];
          while (index < lines.length && lines[index].trim() && isList(lines[index]) === true) {
            const item = lines[index].replace(/^\s*(?:[-*]|\d+\.)\s+/, "");
            items.push(`<li>${inlineFormat(item)}</li>`);
            index += 1;
          }
          index -= 1;
          html.push(`<${ordered ? "ol" : "ul"}>${items.join("")}</${ordered ? "ol" : "ul"}>`);
          continue;
        }

        const paragraph = [line.trim()];
        while (index + 1 < lines.length && lines[index + 1].trim() && !isSpecial(lines, index + 1)) {
          paragraph.push(lines[index + 1].trim());
          index += 1;
        }
        html.push(`<p>${inlineFormat(paragraph.join(" "))}</p>`);
      }

      if (introOpen || sectionOpen) {
        html.push("</section>");
      }

      return { html: html.join("\n"), headings };
    }

    function buildToc(headings) {
      toc.innerHTML = headings
        .map((heading) => `<a href="#${heading.id}" data-target="${heading.id}">${inlineFormat(heading.text)}</a>`)
        .join("");
    }

    function applySearch(query) {
      const normalized = query.trim().toLowerCase();
      let visibleCount = 0;
      document.querySelectorAll("[data-section]").forEach((section) => {
        const visible = !normalized || section.textContent.toLowerCase().includes(normalized);
        section.hidden = !visible;
        if (visible) visibleCount += 1;
      });
      emptyState.classList.toggle("visible", normalized.length > 0 && visibleCount === 0);
    }

    function observeHeadings() {
      const links = new Map(Array.from(toc.querySelectorAll("a")).map((link) => [link.dataset.target, link]));
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          const id = entry.target.id;
          const link = links.get(id);
          if (!link) return;
          if (entry.isIntersecting) {
            toc.querySelectorAll("a").forEach((item) => item.classList.remove("active"));
            link.classList.add("active");
          }
        });
      }, { rootMargin: "-20% 0px -70% 0px", threshold: 0.01 });

      document.querySelectorAll(".doc-section > h2").forEach((heading) => observer.observe(heading));
    }

    const rendered = renderMarkdown(source);
    article.innerHTML = rendered.html;
    buildToc(rendered.headings);
    observeHeadings();
    search.addEventListener("input", (event) => applySearch(event.target.value));
  </script>
</body>
</html>
"""


def render() -> str:
    markdown = SOURCE.read_text(encoding="utf-8")
    source_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    markdown_json = json.dumps(markdown, ensure_ascii=False).replace("</", "<\\/")
    return (
        TEMPLATE.replace("__AUDIT_MARKDOWN_JSON__", markdown_json)
        .replace("__SOURCE_SHA256__", source_sha)
        .replace("__SHORT_SHA__", source_sha[:12])
    )


def main() -> None:
    TARGET.write_text(render(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
