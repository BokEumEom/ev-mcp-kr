// web/docs/_shared.js — markdown 뷰어 공용 모듈.
// 각 *.html 페이지는 <main data-doc-src="..."> 으로 자기가 가리키는 .md 를 선언.
// 이 모듈이 fetch + marked + DOMPurify 로 안전하게 렌더링한다.

import { marked } from "https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.esm.js";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.0.11/+esm";

marked.setOptions({
  gfm: true,
  breaks: false,
  headerIds: true,
  mangle: false,
});

/**
 * data-doc-src 어트리뷰트 또는 인자로 받은 경로의 MD 파일을
 * 가져와 .doc-body 요소에 렌더링한다. (XSS 방지: DOMPurify 로 sanitize)
 *
 * @param {string} [srcOverride] - 명시적 경로 (예: "../../docs/PHASE1.md")
 */
export async function renderDoc(srcOverride) {
  const main = document.querySelector("main.doc-main");
  const body = main?.querySelector(".doc-body");
  const status = main?.querySelector(".doc-status");
  if (!main || !body || !status) return;

  const src = srcOverride || main.dataset.docSrc;
  if (!src) {
    status.textContent = "data-doc-src 가 비어 있습니다.";
    status.classList.add("error");
    return;
  }

  try {
    status.textContent = "문서 로드 중…";
    const res = await fetch(src, { cache: "no-cache" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} — ${src}`);
    }
    const md = await res.text();
    const rawHtml = marked.parse(md);
    const safeHtml = DOMPurify.sanitize(rawHtml);

    // sanitize 된 HTML 을 fragment 로 변환해 삽입 (innerHTML 직접 대입 회피).
    body.replaceChildren();
    const range = document.createRange();
    range.selectNodeContents(body);
    const frag = range.createContextualFragment(safeHtml);
    body.appendChild(frag);

    // 본문 안의 상대 .md 링크 → .html 로 치환.
    rewriteRelativeMdLinks(body);

    status.hidden = true;
    body.hidden = false;

    // 페이지 타이틀: H1 이 있으면 그것으로 갱신.
    const h1 = body.querySelector("h1");
    if (h1) {
      const project = document.title.split(" — ").pop() || "ev-mcp";
      document.title = `${h1.textContent.trim()} — ${project}`;
    }
  } catch (err) {
    console.error(err);
    status.textContent = `로드 실패: ${err.message}`;
    status.classList.add("error");
  }
}

/**
 * 본문 안의 ./SOMETHING.md, ../adr/X.md 같은 링크를
 * 같은 디렉터리 구조의 .html 로 치환한다. 절대 URL/외부 링크/앵커는 건너뜀.
 * build_docs_html.py 가 같은 폴더 레이아웃으로 .html 을 뿌리므로 1:1 일치.
 */
function rewriteRelativeMdLinks(root) {
  for (const a of root.querySelectorAll("a[href]")) {
    const href = a.getAttribute("href");
    if (!href) continue;
    if (/^([a-z]+:)?\/\//i.test(href)) continue;
    if (href.startsWith("#") || href.startsWith("mailto:")) continue;
    if (!href.toLowerCase().includes(".md")) continue;

    const replaced = href.replace(/\.md(\?.*)?$/i, ".html$1");
    a.setAttribute("href", replaced);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => renderDoc());
} else {
  renderDoc();
}
