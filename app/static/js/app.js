(() => {
  const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
  window.csrfToken = token || "";

  const protectDecimalDots = (math) =>
    String(math || "").replace(/\{,\}/g, ".").replace(/(\d)\.(\d)/g, "$1{.}$2");

  window.katexAutoOpts = {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
    preProcess: protectDecimalDots,
  };

  const renderMath = () => {
    if (!window.renderMathInElement) return;
    document.querySelectorAll(".md-body, .math-ready, .ai-feedback, .tcard-math").forEach((el) => {
      window.renderMathInElement(el, window.katexAutoOpts);
    });
  };

  document.addEventListener("DOMContentLoaded", renderMath);
})();
