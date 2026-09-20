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

  const SOLUTION_RE =
    /^(?:[а-яёa-z]\s*[).]\s*)?решени[ея](?:\s*[.:]\s*|\s*[.:]?\s*$)/i;
  const ANSWER_RE = /^(?:[а-яёa-z]\s*[).]\s*)?ответ\b/i;
  const CONTINUE_RE = /^(ответ|дано|найти|проверк|пояснен|объяснен|шаг)\b/i;
  const STOP_RE =
    /^(условие|пример|мини-пример|мини-тема|определен|важно|ловушк|алгоритм|теорем|формул|свойств|признак|следстви|замечан|нельзя путать|сводка)\b/i;
  const EXAMPLE_HEAD_RE = /^(?:р\s*\d+|пример|мини-пример|мини-тема|задани)/i;
  const STEP_HEAD_RE =
    /^(?:[а-яёa-z]\s*[).]|[ivxlcdm]+\s*[).]|\d+\s*[.)]|шаг\b|первый\b|второй\b|третий\b)/i;

  const firstMeaningful = (el) => {
    for (const node of el.childNodes) {
      if (node.nodeType === 1) return node;
      if (node.nodeType === 3 && node.textContent.trim()) return node;
    }
    return null;
  };

  const leadLabel = (el) => {
    if (!el || el.nodeType !== 1) return "";
    if (el.classList.contains("theory-callout") || el.classList.contains("tbox-solve")) {
      const inner = el.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > p");
      return inner ? leadLabel(inner) : (el.textContent || "").trim();
    }
    if (/^H[1-6]$/.test(el.tagName)) return (el.textContent || "").trim();
    if (el.tagName !== "P" && !el.classList.contains("t-lead")) return "";
    const first = firstMeaningful(el);
    if (first && first.nodeType === 1 && (first.tagName === "STRONG" || first.tagName === "EM")) {
      return (first.textContent || "").trim();
    }
    if (first && first.nodeType === 3) return first.textContent.trim();
    return (el.textContent || "").trim();
  };

  const isAnswerNode = (el) =>
    Boolean(
      el.classList?.contains("t-lead-answer") ||
        el.classList?.contains("tbox-answer") ||
        ANSWER_RE.test(leadLabel(el)),
    );

  const isSolutionStart = (el) => {
    if (!el || el.nodeType !== 1 || el.classList.contains("theory-solution")) return false;
    if (
      el.classList.contains("is-solve") ||
      el.classList.contains("t-lead-solve") ||
      el.classList.contains("tbox-solve")
    ) {
      return true;
    }
    return SOLUTION_RE.test(leadLabel(el));
  };

  const isLabelOnly = (el) => {
    if (!el || el.nodeType !== 1) return false;
    const label = leadLabel(el);
    if (!label) return false;
    const rest = (el.textContent || "").trim().replace(label, "").trim();
    return rest.length < 2;
  };

  const shouldStop = (el) => {
    if (!el || el.nodeType !== 1) return true;
    if (el.classList.contains("theory-solution")) return true;
    if (el.tagName === "HR") return true;
    if (
      el.classList.contains("is-trap") ||
      el.classList.contains("tbox-trap") ||
      el.classList.contains("tbox-warn")
    ) {
      return true;
    }
    if (el.classList.contains("tbox-example") || el.classList.contains("tbox-examples")) return true;
    if (el.classList.contains("tbox-given") || el.classList.contains("t-lead-given")) return true;
    if (isSolutionStart(el)) return true;
    const label = leadLabel(el);
    if (CONTINUE_RE.test(label) || isAnswerNode(el)) return false;
    if (STOP_RE.test(label) || EXAMPLE_HEAD_RE.test(label)) return true;
    if (
      el.classList.contains("theory-callout") &&
      !el.classList.contains("is-solve") &&
      !el.classList.contains("tbox-solve")
    ) {
      return !isAnswerNode(el);
    }
    if (/^H[1-6]$/.test(el.tagName)) {
      if (CONTINUE_RE.test(label) || ANSWER_RE.test(label) || STEP_HEAD_RE.test(label)) return false;
      if (STOP_RE.test(label) || EXAMPLE_HEAD_RE.test(label)) return true;
      return /^H[12]$/.test(el.tagName);
    }
    return false;
  };

  const canRecurse = (el) => {
    if (!el || el.nodeType !== 1) return false;
    if (el.classList.contains("theory-solution") || el.classList.contains("t-math")) return false;
    if (el.classList.contains("is-solve") || el.classList.contains("tbox-solve")) return false;
    return el.tagName === "SECTION" || el.tagName === "ARTICLE" || el.tagName === "DIV";
  };

  const wrapSolution = (nodes) => {
    if (!nodes.length) return;
    if (nodes.length === 1 && isLabelOnly(nodes[0])) return;
    const details = document.createElement("details");
    details.className = "theory-solution";
    const summary = document.createElement("summary");
    summary.className = "theory-solution-toggle";
    const show = document.createElement("span");
    show.className = "theory-solution-show";
    show.textContent = "Посмотреть решение";
    const hide = document.createElement("span");
    hide.className = "theory-solution-hide";
    hide.textContent = "Скрыть решение";
    summary.append(show, hide);
    const body = document.createElement("div");
    body.className = "theory-solution-body";
    if (isLabelOnly(nodes[0]) && SOLUTION_RE.test(leadLabel(nodes[0]))) {
      nodes[0].classList.add("theory-solution-label");
    }
    nodes[0].before(details);
    details.append(summary, body);
    for (const node of nodes) body.append(node);
  };

  const foldIn = (parent) => {
    if (!parent) return;
    const kids = [...parent.children];
    for (let i = 0; i < kids.length; i += 1) {
      const el = kids[i];
      if (el.classList.contains("theory-solution")) continue;
      if (isSolutionStart(el)) {
        const nodes = [el];
        let j = i + 1;
        while (j < kids.length && !shouldStop(kids[j])) {
          nodes.push(kids[j]);
          j += 1;
        }
        wrapSolution(nodes);
        i = j - 1;
        continue;
      }
      if (canRecurse(el)) foldIn(el);
    }
  };

  const foldTheorySolutions = (root) => {
    if (!root) {
      document.querySelectorAll(".theory-article").forEach(foldIn);
      return;
    }
    foldIn(root);
  };

  window.foldTheorySolutions = foldTheorySolutions;

  document.addEventListener(
    "toggle",
    (e) => {
      if (e.target?.classList?.contains("theory-solution")) {
        window.dispatchEvent(new Event("resize"));
      }
    },
    true,
  );

  const bindToTop = () => {
    const buttons = document.querySelectorAll(".to-top");
    if (!buttons.length) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tick = () => {
      const on = window.scrollY > 240;
      buttons.forEach((btn) => {
        btn.classList.toggle("is-on", on);
        btn.classList.toggle("is-visible", on);
      });
    };
    window.addEventListener("scroll", tick, { passive: true });
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
      });
    });
    tick();
  };

  document.addEventListener("DOMContentLoaded", () => {
    foldTheorySolutions();
    renderMath();
    bindToTop();
  });
})();
