(() => {
  const renderMath = (root) => {
    if (!window.renderMathInElement) return;
    const scope = root || document;
    const nodes = scope.querySelectorAll
      ? scope.querySelectorAll(".md-body, .math-ready, .ai-feedback, .tcard-math")
      : [];
    nodes.forEach((el) => {
      window.renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
        ],
        throwOnError: false,
      });
    });
  };
  window.renderTheoryCardMath = renderMath;

  const picker = document.getElementById("theoryPickerModal");
  if (picker) {
    const openBtn = document.getElementById("openTheoryPicker");
    const closeBtn = document.getElementById("closeTheoryPicker");
    const selectAll = document.getElementById("pickerSelectAll");
    const countEl = document.getElementById("pickerCount");
    const form = document.getElementById("theoryPickerForm");
    const lessonBoxes = () =>
      [...picker.querySelectorAll('input[name="lessons"]')].filter((el) => !el.disabled);

    const show = () => {
      picker.hidden = false;
      window.scrollTo(0, window.scrollY);
      document.documentElement.style.overflow = "hidden";
      document.body.style.overflow = "hidden";
    };
    const hide = () => {
      picker.hidden = true;
      document.documentElement.style.overflow = "";
      document.body.style.overflow = "";
    };
    const syncCounts = () => {
      const boxes = lessonBoxes();
      const on = boxes.filter((el) => el.checked).length;
      if (countEl) countEl.textContent = `${on} занятий`;
      if (selectAll) {
        selectAll.checked = boxes.length > 0 && on === boxes.length;
        selectAll.indeterminate = on > 0 && on < boxes.length;
      }
      picker.querySelectorAll(".picker-course-toggle").forEach((toggle) => {
        const group = lessonBoxes().filter((el) => el.dataset.course === toggle.dataset.course);
        const n = group.filter((el) => el.checked).length;
        toggle.checked = group.length > 0 && n === group.length;
        toggle.indeterminate = n > 0 && n < group.length;
      });
    };

    if (openBtn) openBtn.addEventListener("click", show);
    if (closeBtn) closeBtn.addEventListener("click", hide);
    picker.addEventListener("click", (ev) => {
      if (ev.target === picker) hide();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !picker.hidden) hide();
    });
    if (selectAll) {
      selectAll.addEventListener("change", () => {
        lessonBoxes().forEach((el) => {
          el.checked = selectAll.checked;
        });
        syncCounts();
      });
    }
    picker.querySelectorAll(".picker-course-toggle").forEach((toggle) => {
      toggle.addEventListener("change", () => {
        lessonBoxes()
          .filter((el) => el.dataset.course === toggle.dataset.course)
          .forEach((el) => {
            el.checked = toggle.checked;
          });
        syncCounts();
      });
    });
    picker.querySelectorAll('input[name="lessons"]').forEach((el) => {
      el.addEventListener("change", syncCounts);
    });
    if (form) {
      form.addEventListener("submit", (ev) => {
        if (!lessonBoxes().some((el) => el.checked)) {
          ev.preventDefault();
          alert("Выберите хотя бы одно занятие.");
        }
      });
    }
    syncCounts();
  }

  const cardRoot = document.getElementById("theoryCard");
  if (!cardRoot) return;

  const qBox = document.getElementById("tcardQuestion");
  const aBox = document.getElementById("tcardAnswer");
  const qEl = document.getElementById("tcardQ");
  const aEl = document.getElementById("tcardA");
  const metaEl = document.getElementById("tcardMeta");
  const checkBtn = document.getElementById("tcardCheck");
  const nextBtn = document.getElementById("tcardNext");
  const progressRoot = document.getElementById("tcardProgress");
  const nextUrl = cardRoot.dataset.next || "";
  const seenUrl = cardRoot.dataset.seen || "";

  const applyProgress = (p) => {
    if (!progressRoot || !p) return;
    const done = Number(p.done || 0);
    const remaining = Number(p.remaining || 0);
    const total = Number(p.total || 0);
    const round = Number(p.round || 1);
    const doneLabel = document.getElementById("tcardDoneLabel");
    const leftLabel = document.getElementById("tcardLeftLabel");
    const frac = document.getElementById("tcardFrac");
    const bar = document.getElementById("tcardBarFill");
    if (doneLabel) doneLabel.textContent = `Пройдено ${done}`;
    if (leftLabel) leftLabel.textContent = `в колоде ${remaining}`;
    if (frac) {
      frac.textContent = total
        ? `${done} / ${total}${round > 1 ? ` · круг ${round}` : ""}`
        : "";
    }
    if (bar) bar.style.width = `${total ? Math.round((100 * done) / total) : 0}%`;
    progressRoot.dataset.done = String(done);
    progressRoot.dataset.remaining = String(remaining);
    progressRoot.dataset.total = String(total);
  };

  const markSeen = async () => {
    if (!seenUrl) return;
    try {
      const res = await fetch(seenUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": window.csrfToken || "",
        },
        body: JSON.stringify({ current_id: cardRoot.dataset.id || "" }),
      });
      const data = await res.json();
      if (data.ok && data.progress) applyProgress(data.progress);
    } catch (_) {
      /* прогресс не должен ломать проверку */
    }
  };

  const fitCardText = () => {
    const face = cardRoot.querySelector(".tcard-face:not([hidden])");
    if (!face) return;
    const isAnswer = face.classList.contains("is-answer");
    face.style.fontSize = "";
    face.style.overflow = "hidden";
    face.classList.remove("is-long");
    if (aEl) aEl.classList.remove("is-long");
    let scale = 1;
    const minScale = isAnswer ? 0.72 : 0.55;
    const shrink = () => {
      while (face.scrollHeight > face.clientHeight + 4 && scale > minScale) {
        scale -= 0.04;
        face.style.fontSize = `${Math.round(scale * 100)}%`;
      }
    };
    shrink();
    if (isAnswer) {
      const long =
        face.scrollHeight > face.clientHeight + 4 ||
        (aEl && (aEl.innerText || "").trim().length > 220);
      face.classList.toggle("is-long", Boolean(long));
      if (aEl) aEl.classList.toggle("is-long", Boolean(long));
      shrink();
      const overflows = face.scrollHeight > face.clientHeight + 4;
      face.style.overflow = overflows ? "auto" : "hidden";
      const updateFade = () => {
        const more = face.scrollHeight > face.clientHeight + face.scrollTop + 8;
        face.classList.toggle("is-scrollable", more);
      };
      face.onscroll = overflows ? updateFade : null;
      updateFade();
    } else {
      face.style.overflow = "hidden";
      face.onscroll = null;
      face.classList.remove("is-scrollable");
    }
  };
  const scheduleFit = () => {
    requestAnimationFrame(() => {
      fitCardText();
      requestAnimationFrame(fitCardText);
    });
  };

  const showQuestion = () => {
    cardRoot.classList.remove("show-answer");
    if (qBox) qBox.hidden = false;
    if (aBox) aBox.hidden = true;
    if (checkBtn) checkBtn.hidden = false;
    if (nextBtn) nextBtn.hidden = true;
    scheduleFit();
  };

  const showAnswer = () => {
    cardRoot.classList.add("show-answer");
    if (qBox) qBox.hidden = true;
    if (aBox) aBox.hidden = false;
    if (checkBtn) checkBtn.hidden = true;
    if (nextBtn) nextBtn.hidden = false;
    renderMath(cardRoot);
    scheduleFit();
    markSeen();
  };

  const applyCard = (card, progress) => {
    cardRoot.dataset.id = card.id || "";
    if (metaEl) {
      metaEl.textContent = `${card.kind_label || ""} · занятие ${card.lesson_number || ""}`.trim();
    }
    if (qEl) qEl.textContent = card.question || "";
    if (aEl) aEl.innerHTML = card.answer_html || "";
    if (progress) applyProgress(progress);
    showQuestion();
    renderMath(cardRoot);
    scheduleFit();
  };

  if (checkBtn) checkBtn.addEventListener("click", showAnswer);
  if (nextBtn) {
    nextBtn.addEventListener("click", async () => {
      nextBtn.disabled = true;
      try {
        const res = await fetch(nextUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": window.csrfToken || "",
          },
          body: JSON.stringify({ current_id: cardRoot.dataset.id || "" }),
        });
        const data = await res.json();
        if (!data.ok || !data.card) throw new Error("empty");
        applyCard(data.card, data.progress || data.card.progress);
      } catch (_) {
        window.location.href = `${window.location.pathname}?after=${encodeURIComponent(cardRoot.dataset.id || "")}`;
      } finally {
        nextBtn.disabled = false;
      }
    });
  }

  renderMath(cardRoot);
  scheduleFit();
  window.addEventListener("resize", scheduleFit);
})();
