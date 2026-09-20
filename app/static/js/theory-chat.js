(() => {
  const root = document.getElementById("tutorRoot");
  if (!root) return;

  const fab = document.getElementById("tutorFab");
  const layer = document.getElementById("tutorLayer");
  const logEl = document.getElementById("tutorLog");
  const form = document.getElementById("tutorForm");
  const input = document.getElementById("tutorInput");
  const sendBtn = document.getElementById("tutorSend");
  const askSel = document.getElementById("tutorAskSel");
  const article = document.querySelector(".theory-source") || document.querySelector(".theory-article");
  const chatUrl = root.dataset.chatUrl || "";
  const clearUrl = root.dataset.clearUrl || "";
  let loaded = false;
  let loadPromise = null;
  let sending = false;
  let quoteText = "";
  let placeTimer = 0;
  let pollToken = 0;

  const csrfHeaders = () => ({
    "Content-Type": "application/json",
    Accept: "application/json",
    "X-CSRFToken": window.csrfToken || "",
  });

  const renderMath = (el) => {
    if (el && window.renderMathInElement && window.katexAutoOpts) {
      window.renderMathInElement(el, window.katexAutoOpts);
    }
  };

  const emptyHint = () => {
    const p = document.createElement("p");
    p.className = "tutor-empty";
    p.textContent = "Спросите, что непонятно в этом уроке: определение, формулу или пример.";
    return p;
  };

  const escapeHtml = (value) =>
    String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const appendMsg = (role, html, { typing = false, id = null } = {}) => {
    if (!logEl) return null;
    const hint = logEl.querySelector(".tutor-empty");
    if (hint) hint.remove();
    const row = document.createElement("article");
    row.className = `tutor-msg tutor-msg-${role}${typing ? " is-typing" : ""}`;
    if (id != null) row.dataset.id = String(id);
    const label = document.createElement("span");
    label.className = "tutor-msg-who";
    label.textContent = role === "user" ? "Вы" : "Помощник";
    const body = document.createElement("div");
    body.className = "tutor-msg-body md-body";
    body.innerHTML = html;
    row.append(label, body);
    logEl.append(row);
    renderMath(body);
    logEl.scrollTop = logEl.scrollHeight;
    return row;
  };

  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const fillAssistantRow = (row, html) => {
    if (!row) return;
    row.classList.remove("is-typing");
    const body = row.querySelector(".tutor-msg-body");
    if (body) {
      body.innerHTML = html || "";
      renderMath(body);
    }
    if (logEl) logEl.scrollTop = logEl.scrollHeight;
  };

  const pollAssistant = async (id, waitRow) => {
    const token = ++pollToken;
    const deadline = Date.now() + 4 * 60 * 1000;
    while (Date.now() < deadline) {
      await sleep(2000);
      if (token !== pollToken) return;
      try {
        const res = await fetch(chatUrl, { headers: { Accept: "application/json" } });
        const data = await res.json().catch(() => ({}));
        const messages = Array.isArray(data.messages) ? data.messages : [];
        const msg = messages.find((item) => Number(item.id) === Number(id));
        if (!msg) return;
        if (!msg.pending) {
          fillAssistantRow(waitRow, msg.html || "");
          return;
        }
      } catch (_) {
        /* сеть могла моргнуть — следующий тик повторит */
      }
    }
    if (token !== pollToken) return;
    fillAssistantRow(
      waitRow,
      "<p>Ответ задерживается. Откройте чат чуть позже — он появится в переписке.</p>",
    );
  };

  const setSending = (on) => {
    sending = on;
    if (sendBtn) sendBtn.disabled = on;
  };

  const loadHistory = () => {
    if (loadPromise) return loadPromise;
    loaded = true;
    loadPromise = (async () => {
      if (!logEl || !chatUrl) return;
      logEl.innerHTML = "";
      try {
        const res = await fetch(chatUrl, { headers: { Accept: "application/json" } });
        const data = await res.json();
        const messages = Array.isArray(data.messages) ? data.messages : [];
        if (!messages.length) {
          logEl.append(emptyHint());
          return;
        }
        let pendingId = null;
        let pendingRow = null;
        messages.forEach((msg) => {
          const row = appendMsg(msg.role, msg.html || "", {
            typing: Boolean(msg.pending),
            id: msg.id,
          });
          if (msg.pending && msg.role === "assistant") {
            pendingId = msg.id;
            pendingRow = row;
          }
        });
        if (pendingId && pendingRow) {
          setSending(true);
          try {
            await pollAssistant(pendingId, pendingRow);
          } finally {
            setSending(false);
          }
        }
      } catch (_) {
        logEl.append(emptyHint());
      }
    })();
    return loadPromise;
  };

  const hideAsk = () => {
    quoteText = "";
    if (askSel) askSel.hidden = true;
  };

  const tutorReady = () => Boolean(fab && !fab.hidden && !document.body.classList.contains("tutor-open"));

  const isChrome = (el) =>
    Boolean(
      el?.closest?.(
        "button, a, summary, .eyebrow, .theory-progress, .tutor-ask-sel, .tutor-fab, .tutor-layer, .to-top",
      ),
    );

  const overlapsRange = (range, node) => {
    try {
      return range.intersectsNode(node);
    } catch (_) {
      return false;
    }
  };

  const katexSource = (katexEl) => {
    const ann = katexEl.querySelector('annotation[encoding="application/x-tex"]');
    let tex = (ann?.textContent || "").trim().replace(/\{\.\}/g, ".");
    if (!tex) return "";
    return katexEl.closest(".katex-display") ? `$$${tex}$$` : `$${tex}$`;
  };

  const sliceTextNode = (node, range) => {
    let text = node.textContent || "";
    if (node === range.startContainer && node === range.endContainer) {
      text = text.slice(range.startOffset, range.endOffset);
    } else if (node === range.startContainer) {
      text = text.slice(range.startOffset);
    } else if (node === range.endContainer) {
      text = text.slice(0, range.endOffset);
    }
    return text;
  };

  const selectedQuote = () => {
    if (!article || !tutorReady()) return "";
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return "";
    const range = sel.getRangeAt(0);
    if (!overlapsRange(range, article)) return "";
    const bits = [];
    const seenKatex = new Set();
    const walker = document.createTreeWalker(
      article,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    );
    let node = walker.currentNode;
    while (node) {
      if (node.nodeType === 1) {
        if (
          node.classList?.contains("katex") &&
          !isChrome(node) &&
          overlapsRange(range, node) &&
          !seenKatex.has(node)
        ) {
          seenKatex.add(node);
          const src = katexSource(node);
          if (src) bits.push(src);
        }
      } else if (node.nodeType === 3) {
        const parent = node.parentElement;
        if (
          parent &&
          !parent.closest(".katex") &&
          !isChrome(parent) &&
          overlapsRange(range, node)
        ) {
          bits.push(sliceTextNode(node, range));
        }
      }
      node = walker.nextNode();
    }
    return bits
      .join("")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/[ \t]{2,}/g, " ")
      .trim();
  };

  const placeAsk = () => {
    if (!askSel) return;
    const text = selectedQuote();
    if (text.length < 2) {
      hideAsk();
      return;
    }
    quoteText = text.slice(0, 1800);
    const range = window.getSelection().getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (!rect.width && !rect.height) {
      hideAsk();
      return;
    }
    askSel.hidden = false;
    const btnW = askSel.offsetWidth || 108;
    const btnH = askSel.offsetHeight || 36;
    const gap = 8;
    let top = rect.top - btnH - gap;
    if (top < 8) top = rect.bottom + gap;
    let left = rect.left + rect.width / 2 - btnW / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - btnW - 8));
    askSel.style.top = `${top}px`;
    askSel.style.left = `${left}px`;
  };

  const schedulePlace = () => {
    window.clearTimeout(placeTimer);
    placeTimer = window.setTimeout(placeAsk, 50);
  };

  const setOpen = async (open) => {
    if (!layer) return;
    layer.hidden = !open;
    document.body.classList.toggle("tutor-open", open);
    fab?.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      hideAsk();
      if (!loaded) await loadHistory();
      requestAnimationFrame(() => input?.focus());
    }
  };

  const send = async (preset) => {
    if (sending || !chatUrl || !input) return;
    const text = String(preset || input.value || "").trim();
    if (!text) return;
    setSending(true);
    if (!preset) input.value = "";
    const userRow = appendMsg("user", `<p>${escapeHtml(text).replace(/\n/g, "<br>\n")}</p>`);
    const wait = appendMsg("assistant", "<p>Думаю…</p>", { typing: true });
    try {
      const res = await fetch(chatUrl, {
        method: "POST",
        headers: csrfHeaders(),
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        userRow?.remove();
        wait?.remove();
        appendMsg(
          "assistant",
          `<p>${escapeHtml(data.error || "Не удалось получить ответ. Попробуйте ещё раз.")}</p>`,
        );
        return;
      }
      const assistantId = data.assistant && data.assistant.id;
      if (assistantId && wait) wait.dataset.id = String(assistantId);
      if (data.pending && assistantId) {
        await pollAssistant(assistantId, wait);
      } else if (data.assistant) {
        fillAssistantRow(wait, data.assistant.html || "");
      } else {
        wait?.remove();
      }
    } catch (_) {
      wait?.remove();
      appendMsg("assistant", "<p>Нет связи. Проверьте интернет и спросите ещё раз.</p>");
    } finally {
      setSending(false);
      input?.focus();
    }
  };

  const askAboutQuote = async () => {
    const quote = quoteText || selectedQuote();
    if (quote.length < 2) return;
    hideAsk();
    window.getSelection()?.removeAllRanges();
    await setOpen(true);
    await send(`Поясни, о чём этот фрагмент из урока:\n\n«${quote}»`);
  };

  fab?.addEventListener("click", () => setOpen(true));
  layer?.querySelectorAll("[data-tutor-close]").forEach((el) => {
    el.addEventListener("click", () => setOpen(false));
  });
  document.getElementById("tutorClear")?.addEventListener("click", async () => {
    if (!clearUrl || !window.confirm("Очистить переписку по этому занятию?")) return;
    try {
      const res = await fetch(clearUrl, { method: "POST", headers: csrfHeaders(), body: "{}" });
      if (!res.ok) return;
      pollToken += 1;
      setSending(false);
      loaded = true;
      loadPromise = Promise.resolve();
      if (logEl) {
        logEl.innerHTML = "";
        logEl.append(emptyHint());
      }
    } catch (_) {
      /* ignore */
    }
  });
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    send();
  });
  input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("tutor-open")) {
      setOpen(false);
    }
  });

  askSel?.addEventListener("mousedown", (e) => e.preventDefault());
  askSel?.addEventListener("pointerdown", (e) => e.preventDefault());
  askSel?.addEventListener("click", (e) => {
    e.preventDefault();
    askAboutQuote();
  });
  document.addEventListener("selectionchange", schedulePlace);
  document.addEventListener("mouseup", schedulePlace);
  document.addEventListener("keyup", schedulePlace);
  window.addEventListener("scroll", hideAsk, { passive: true });
  window.addEventListener("resize", hideAsk);
})();
