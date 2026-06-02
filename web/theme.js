// 테마 토글 — 라이트/다크 전환. localStorage 저장 후 리로드(차트가 init 시 색을 읽으므로 재생성).
// FOUC 방지용 선설정은 각 페이지 <head> 인라인 스크립트가 담당.
(function () {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;

  const root = document.documentElement;
  const sync = () => {
    const dark = root.getAttribute("data-theme") === "dark";
    btn.setAttribute("aria-pressed", String(dark));
    btn.title = dark ? "라이트 모드로 전환" : "다크 모드로 전환";
  };
  sync();

  btn.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("ev-theme", next);
    } catch (e) {
      /* localStorage 차단 환경 — 세션 한정으로만 적용 */
    }
    root.setAttribute("data-theme", next);
    location.reload();
  });
})();
