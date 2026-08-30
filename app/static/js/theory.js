(() => {
  const root = document.querySelector(".theory-progress");
  if (!root) return;
  const bar = document.getElementById("theoryBar");
  const pctLabel = document.getElementById("theoryPct");
  const cta = document.getElementById("theoryCta");
  const toTop = document.getElementById("theoryToTop");
  const article = document.querySelector(".theory-article");
  const url = root.dataset.progressUrl;
  let lastSent = Number(root.dataset.initial || 0);
  let done = root.dataset.done === "1";
  let lastBeat = Date.now();
  let lastActivity = Date.now();
  let pendingSeconds = 0;
  const IDLE_MS = 90000;

  const measure = () => {
    if (!article) return 100;
    const top = article.getBoundingClientRect().top + window.scrollY;
    const height = article.offsetHeight - window.innerHeight * 0.72;
    if (height <= 0) return 100;
    const y = window.scrollY - top + 40;
    return Math.max(0, Math.min(100, Math.round((y / height) * 100)));
  };

  const markActivity = () => {
    lastActivity = Date.now();
  };

  const takeSeconds = (opts = {}) => {
    const now = Date.now();
    const delta = Math.floor((now - lastBeat) / 1000);
    lastBeat = now;
    const visible = opts.ignoreHidden || document.visibilityState === "visible";
    if (!visible) return 0;
    if (now - lastActivity > IDLE_MS) return 0;
    if (delta <= 0 || delta > 45) return 0;
    return delta;
  };

  const send = async (pct, completed, seconds) => {
    if (!url) return;
    const body = { pct, completed, seconds: seconds || 0 };
    try {
      await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": window.csrfToken || "",
        },
        body: JSON.stringify(body),
        keepalive: true,
      });
    } catch (_) {
      /* сеть не должна ломать чтение */
    }
  };

  const flushTime = (opts = {}) => {
    pendingSeconds += takeSeconds(opts);
    if (pendingSeconds <= 0 && opts.forcePct == null) return;
    const pct = opts.forcePct == null ? measure() : opts.forcePct;
    const seconds = pendingSeconds;
    pendingSeconds = 0;
    send(pct, done || pct >= 98, seconds);
  };

  const tick = () => {
    markActivity();
    if (toTop) toTop.classList.toggle("is-on", window.scrollY > 240);
    const pct = measure();
    if (bar) bar.style.width = `${pct}%`;
    if (pctLabel) pctLabel.textContent = `${pct}%`;
    const completed = pct >= 98;
    if (completed && cta) cta.hidden = false;
    if (completed && !done) {
      done = true;
      pendingSeconds += takeSeconds();
      send(100, true, pendingSeconds);
      pendingSeconds = 0;
      lastSent = 100;
      return;
    }
    if (pct - lastSent >= 8) {
      lastSent = pct;
      pendingSeconds += takeSeconds();
      send(pct, false, pendingSeconds);
      pendingSeconds = 0;
    }
  };

  toTop?.addEventListener("click", () => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
  });
  window.addEventListener("scroll", tick, { passive: true });
  window.addEventListener("resize", tick);
  document.addEventListener("mousemove", markActivity, { passive: true });
  document.addEventListener("keydown", markActivity);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      flushTime({ ignoreHidden: true });
    } else {
      lastBeat = Date.now();
      lastActivity = Date.now();
    }
  });
  window.addEventListener("pagehide", () => flushTime({ ignoreHidden: true }));
  setInterval(() => flushTime(), 10000);
  document.addEventListener("DOMContentLoaded", () => {
    tick();
    if (measure() >= 98 && !done) {
      done = true;
      send(100, true, takeSeconds());
    }
  });
})();
