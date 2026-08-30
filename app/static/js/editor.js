(() => {
  const LETTERS = ["а", "б", "в", "г", "д"];
  const csrf = window.csrfToken || "";

  const mathOpts = {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
  };

  const paintMath = (el) => {
    if (!el || !window.renderMathInElement) return;
    window.renderMathInElement(el, mathOpts);
  };

  const bindPreview = () => {
    document.querySelectorAll("[data-preview-target]").forEach((src) => {
      const target = document.getElementById(src.dataset.previewTarget);
      if (!target) return;
      const url = src.dataset.previewUrl || "/admin/preview";
      let timer = 0;
      const run = () => {
        fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
          body: JSON.stringify({
            source: src.value || "",
            decorate_theory: src.dataset.previewMode === "theory",
          }),
        })
          .then((res) => res.json())
          .then((data) => {
            target.innerHTML = data.html || "";
            paintMath(target);
          })
          .catch(() => {
            target.textContent = "Не удалось обновить предпросмотр.";
          });
      };
      src.addEventListener("input", () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(run, 400);
      });
      run();
    });
  };

  const reindexQuestions = () => {
    const form = document.getElementById("testEditor");
    if (!form) return;
    const cards = [...form.querySelectorAll(".q-edit")];
    const count = document.getElementById("qCount");
    if (count) count.value = String(cards.length);
    cards.forEach((card, i) => {
      const n = i + 1;
      const label = card.querySelector(".q-idx-label");
      if (label) label.textContent = "Т" + n;
      card.querySelectorAll("[data-name]").forEach((el) => {
        el.name = el.dataset.name.replace("#", String(n));
      });
      [...card.querySelectorAll(".opt-edit")].forEach((opt, j) => {
        const letter = LETTERS[j] || "";
        const mark = opt.querySelector(".opt-letter");
        if (mark) mark.textContent = letter + ")";
        const ans = opt.querySelector("[data-ans]");
        const inp = opt.querySelector("[data-opt]");
        if (ans) {
          ans.name = `q${n}_ans`;
          ans.value = letter;
        }
        if (inp) inp.name = `q${n}_opt`;
      });
    });
  };

  const reindexTaskList = (list) => {
    if (!list) return;
    const prefix = list.dataset.prefix;
    const letter = list.dataset.letter || "";
    const cards = [...list.querySelectorAll(".task-edit")];
    const countId = prefix === "hw" ? "hwCount" : `${prefix}Count`;
    const count = document.getElementById(countId);
    if (count) count.value = String(cards.length);
    cards.forEach((card, i) => {
      const n = i + 1;
      const label = card.querySelector(".task-idx-label");
      if (label) label.textContent = letter + n;
      card.querySelectorAll("[data-field]").forEach((el) => {
        el.name = `${prefix}${n}_${el.dataset.field}`;
      });
    });
  };

  const reindexPractice = () => {
    document.querySelectorAll(".task-edit-list").forEach(reindexTaskList);
  };

  const optionRow = (letter) => {
    const row = document.createElement("div");
    row.className = "opt-edit";
    row.innerHTML = `
      <label class="check">
        <input type="checkbox" data-ans="1" value="${letter}">
        <b class="opt-letter">${letter})</b>
      </label>
      <input type="text" data-opt="1" value="">
      <button class="btn btn-ghost btn-sm btn-remove-opt" type="button" title="Убрать вариант">×</button>
    `;
    return row;
  };

  const bindTestEditor = () => {
    const form = document.getElementById("testEditor");
    if (!form) return;
    const list = document.getElementById("questionList");
    const tpl = document.getElementById("questionTpl");

    form.addEventListener("click", (ev) => {
      const addQ = ev.target.closest("#addQuestion");
      if (addQ) {
        const node = tpl.content.firstElementChild.cloneNode(true);
        list.appendChild(node);
        reindexQuestions();
        return;
      }
      const addOpt = ev.target.closest(".btn-add-opt");
      if (addOpt) {
        const card = addOpt.closest(".q-edit");
        const box = card.querySelector(".opt-edit-list");
        if (box.children.length >= LETTERS.length) return;
        box.appendChild(optionRow(LETTERS[box.children.length]));
        reindexQuestions();
        return;
      }
      const rmQ = ev.target.closest(".btn-remove-q");
      if (rmQ) {
        const cards = list.querySelectorAll(".q-edit");
        if (cards.length <= 1) return;
        rmQ.closest(".q-edit").remove();
        reindexQuestions();
        return;
      }
      const rmOpt = ev.target.closest(".btn-remove-opt");
      if (rmOpt) {
        const box = rmOpt.closest(".opt-edit-list");
        if (box.querySelectorAll(".opt-edit").length <= 2) return;
        rmOpt.closest(".opt-edit").remove();
        reindexQuestions();
      }
    });

    form.addEventListener("submit", reindexQuestions);
    reindexQuestions();
  };

  const bindPracticeEditor = () => {
    const form = document.getElementById("practiceEditor");
    if (!form) return;

    form.addEventListener("click", (ev) => {
      const add = ev.target.closest("[data-add-task]");
      if (add) {
        const prefix = add.getAttribute("data-add-task");
        const list = document.getElementById(prefix === "hw" ? "hwList" : "classList");
        const tpl = document.getElementById(prefix === "hw" ? "hwTaskTpl" : "classTaskTpl");
        list.appendChild(tpl.content.firstElementChild.cloneNode(true));
        reindexTaskList(list);
        return;
      }
      const rm = ev.target.closest(".btn-remove-task");
      if (rm) {
        const list = rm.closest(".task-edit-list");
        if (list.querySelectorAll(".task-edit").length <= 1) {
          const card = rm.closest(".task-edit");
          card.querySelectorAll("input, textarea").forEach((el) => {
            el.value = "";
          });
          reindexTaskList(list);
          return;
        }
        rm.closest(".task-edit").remove();
        reindexTaskList(list);
      }
    });

    form.addEventListener("submit", reindexPractice);
    reindexPractice();
  };

  document.addEventListener("DOMContentLoaded", () => {
    bindPreview();
    bindTestEditor();
    bindPracticeEditor();
  });
})();
