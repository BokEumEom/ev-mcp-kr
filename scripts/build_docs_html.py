"""docs/*.md → web/docs/*.html 셸 생성 스크립트.

각 마크다운 파일에 대해 정적 HTML 래퍼를 생성합니다. 마크다운 자체는
브라우저에서 ``web/docs/_shared.js`` (marked.js + DOMPurify) 가 fetch + 렌더링.

빌드 step 0 철학 유지 — 이 스크립트는 docs 가 추가/변경됐을 때만 수동으로
실행하면 됩니다. 모든 출력은 stdlib 만 사용.

사용법
------
::

    python scripts/build_docs_html.py
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DOCS = PROJECT_ROOT / "web" / "docs"


@dataclass(frozen=True)
class DocEntry:
    """한 markdown 파일 → 한 출력 HTML 의 매핑 단위."""

    md_path: Path
    """원본 markdown 절대 경로."""

    out_path: Path
    """출력 HTML 절대 경로 (web/docs/ 아래)."""

    title: str
    """페이지 타이틀 (H1 또는 파일명 폴백)."""

    description: str
    """index 카드에 노출할 요약 (첫 단락, 200자 cap)."""

    rel_md_from_out: str
    """out_path 기준의 md 상대 경로 (data-doc-src 에 들어감)."""

    rel_out_from_index: str
    """web/docs/index.html 기준의 출력 HTML 상대 경로."""

    category: str
    """index 페이지에서의 섹션 라벨."""


# ────────────────────────────────────────────────────────────
# 매핑 정의 — 어떤 .md 를 어떤 출력으로 변환할지.
# ────────────────────────────────────────────────────────────

# (md 상대경로 from project root, 출력 슬러그, 카테고리)
SOURCES: list[tuple[str, str, str]] = [
    # 핵심 진입 문서
    ("README.md", "readme", "프로젝트 개요"),
    ("docs/PLAN.md", "plan", "프로젝트 개요"),
    ("docs/ARCHITECTURE.md", "architecture", "프로젝트 개요"),
    ("docs/WORKFLOW.md", "workflow", "프로젝트 개요"),
    # Phase 보고서
    ("docs/PHASE1.md", "phase1", "Phase 보고서"),
    ("docs/PHASE2.md", "phase2", "Phase 보고서"),
    ("docs/PHASE3.md", "phase3", "Phase 보고서"),
    ("docs/PHASE4.md", "phase4", "Phase 보고서"),
    ("docs/PHASE5.md", "phase5", "Phase 보고서"),
    ("docs/PHASE6.md", "phase6", "Phase 보고서"),
    ("docs/PHASE7.md", "phase7", "Phase 보고서"),
    ("docs/PHASE9.md", "phase9", "Phase 보고서"),
    ("docs/PHASE10.md", "phase10", "Phase 보고서"),
    # 운영 / 정책
    ("docs/PRIVACY.md", "privacy", "운영 · 정책"),
    ("docs/SUPPORT.md", "support", "운영 · 정책"),
    # ADR
    ("docs/adr/README.md", "adr/index", "ADR (Architecture Decision Record)"),
    (
        "docs/adr/ADR-001-duckdb-analytics.md",
        "adr/adr-001-duckdb-analytics",
        "ADR (Architecture Decision Record)",
    ),
    # web 자체 문서
    ("web/README.md", "web-readme", "web 대시보드"),
    # workers
    ("workers/README.md", "workers-readme", "Cloudflare Workers"),
    ("workers/DEPLOY.md", "workers-deploy", "Cloudflare Workers"),
]


def extract_title_and_desc(md_text: str, fallback_title: str) -> tuple[str, str]:
    """첫 H1 을 타이틀로, 그 뒤 첫 단락을 설명으로 추출."""

    title = fallback_title
    desc = ""

    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            # 그 다음 비-빈 줄들 = 첫 단락
            buf: list[str] = []
            for follow in lines[i + 1 :]:
                t = follow.strip()
                if not t:
                    if buf:
                        break
                    continue
                if t.startswith("#"):
                    break
                buf.append(t)
            desc = " ".join(buf)
            break

    # 마크다운 마크업 가벼운 제거: 백틱, **, _, [..](..) 의 ".." 부분만 추출.
    desc = re.sub(r"`([^`]*)`", r"\1", desc)
    desc = re.sub(r"\*\*([^*]+)\*\*", r"\1", desc)
    desc = re.sub(r"\*([^*]+)\*", r"\1", desc)
    desc = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", desc)
    desc = desc.strip()
    if len(desc) > 200:
        desc = desc[:197].rstrip() + "…"

    return title, desc


def render_doc_page(entry: DocEntry, project_title: str) -> str:
    """한 문서 페이지 HTML 셸 렌더링."""

    # web/docs/<sub>.html 에서 _docs.css 와 _shared.js 까지 상대 경로.
    rel_root = relpath_to_web_docs_root(entry.out_path)
    css_href = f"{rel_root}_docs.css"
    js_src = f"{rel_root}_shared.js"
    index_href = f"{rel_root}index.html"
    dashboard_href = f"{rel_root}../index.html"

    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(entry.title)} — {html.escape(project_title)}</title>
    <link rel="stylesheet" href="{html.escape(css_href)}" />
  </head>
  <body>
    <header class="doc-header">
      <div class="doc-header-inner">
        <nav class="crumbs">
          <a href="{html.escape(dashboard_href)}">대시보드</a>
          <span class="sep">/</span>
          <a href="{html.escape(index_href)}">문서</a>
          <span class="sep">/</span>
          <span>{html.escape(entry.title)}</span>
        </nav>
        <div class="tools">
          <a href="{html.escape(entry.rel_md_from_out)}" download>원본 .md</a>
        </div>
      </div>
    </header>

    <main class="doc-main" data-doc-src="{html.escape(entry.rel_md_from_out)}">
      <div class="doc-status">문서 로드 중…</div>
      <article class="doc-body" hidden></article>
    </main>

    <script type="module" src="{html.escape(js_src)}"></script>
  </body>
</html>
"""


def relpath_to_web_docs_root(out_path: Path) -> str:
    """out_path 가 web/docs 아래 몇 단계 깊이인지에 따라 ``../`` 누적."""

    rel = out_path.relative_to(WEB_DOCS)
    depth = len(rel.parts) - 1
    return "../" * depth if depth > 0 else "./"


def render_index_page(entries: list[DocEntry], project_title: str) -> str:
    """문서 포털 index — 카테고리별 카드 그리드."""

    # 카테고리 순서 보존 (SOURCES 순서대로 첫 등장 기준).
    seen: dict[str, list[DocEntry]] = {}
    for e in entries:
        seen.setdefault(e.category, []).append(e)

    sections: list[str] = []
    for category, items in seen.items():
        cards = "\n".join(
            (
                f"""        <a class="doc-card" href="{html.escape(e.rel_out_from_index)}">
          <div class="doc-card-title">{html.escape(e.title)}</div>
          <div class="doc-card-desc">{html.escape(e.description) or "—"}</div>
        </a>"""
            )
            for e in items
        )
        sections.append(
            f"""      <h2 class="doc-section-title">{html.escape(category)}</h2>
      <div class="doc-index-grid">
{cards}
      </div>"""
        )

    body = "\n".join(sections)

    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>문서 — {html.escape(project_title)}</title>
    <link rel="stylesheet" href="./_docs.css" />
  </head>
  <body>
    <header class="doc-header">
      <div class="doc-header-inner">
        <nav class="crumbs">
          <a href="../index.html">대시보드</a>
          <span class="sep">/</span>
          <span>문서</span>
        </nav>
        <div class="tools">
          <a href="https://github.com" rel="noopener" hidden>저장소</a>
        </div>
      </div>
    </header>

    <main class="doc-main">
      <article class="doc-body" style="display:block">
        <h1>{html.escape(project_title)} 문서 포털</h1>
        <p>
          한국환경공단 EV 충전소 OpenAPI v1.23 을 Claude 원격 MCP 커넥터로 노출하는
          프로젝트. 각 문서는 원본 markdown 을 브라우저에서 직접 렌더링합니다 —
          서버 빌드 step 0.
        </p>
{body}
      </article>
    </main>
  </body>
</html>
"""


def build_entries() -> list[DocEntry]:
    """SOURCES 정의를 DocEntry 리스트로 펼침."""

    entries: list[DocEntry] = []
    for md_rel, slug, category in SOURCES:
        md_path = PROJECT_ROOT / md_rel
        if not md_path.exists():
            print(f"  skip (not found): {md_rel}")
            continue

        out_path = WEB_DOCS / f"{slug}.html"
        md_text = md_path.read_text(encoding="utf-8")
        fallback = md_rel.split("/")[-1].rsplit(".", 1)[0]
        title, desc = extract_title_and_desc(md_text, fallback)

        # md 까지의 상대 경로 (out_path 기준)
        rel_md = relative_path(out_path.parent, md_path)
        # index.html 기준 out 상대 경로
        rel_out = relative_path(WEB_DOCS, out_path)

        entries.append(
            DocEntry(
                md_path=md_path,
                out_path=out_path,
                title=title,
                description=desc,
                rel_md_from_out=rel_md,
                rel_out_from_index=rel_out,
                category=category,
            )
        )

    return entries


def relative_path(from_dir: Path, to_path: Path) -> str:
    """POSIX 스타일 ../ 누적 상대 경로."""

    from_dir = from_dir.resolve()
    to_path = to_path.resolve()

    from_parts = from_dir.parts
    to_parts = to_path.parts

    # 공통 prefix 찾기
    i = 0
    while i < len(from_parts) and i < len(to_parts) and from_parts[i] == to_parts[i]:
        i += 1

    up = [".."] * (len(from_parts) - i)
    down = list(to_parts[i:])
    parts = up + down
    return "/".join(parts) if parts else "."


def main() -> int:
    project_title = "ev-mcp"

    WEB_DOCS.mkdir(parents=True, exist_ok=True)
    (WEB_DOCS / "adr").mkdir(exist_ok=True)

    entries = build_entries()
    if not entries:
        print("No documents found.")
        return 1

    for e in entries:
        e.out_path.parent.mkdir(parents=True, exist_ok=True)
        e.out_path.write_text(render_doc_page(e, project_title), encoding="utf-8")
        print(f"  wrote {e.out_path.relative_to(PROJECT_ROOT)}  ({e.title})")

    index_html = render_index_page(entries, project_title)
    (WEB_DOCS / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  wrote {(WEB_DOCS / 'index.html').relative_to(PROJECT_ROOT)}  (index)")

    print(f"\n✔ {len(entries)} document(s) + index generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
