(() => {
  const input = document.getElementById("photoInput");
  const preview = document.getElementById("photoPreview");
  const wrap = document.getElementById("photoPreviewWrap");
  const form = document.getElementById("practiceForm");
  const btn = document.getElementById("sendBtn");
  const hint = document.getElementById("waitHint");
  const clearBtn = document.getElementById("photoClear");
  let objectUrl = "";

  const showPreview = (file) => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    preview.src = objectUrl;
    preview.hidden = false;
    if (wrap) wrap.hidden = false;
  };

  const clearPhoto = () => {
    if (!input) return;
    input.value = "";
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = "";
    }
    preview.removeAttribute("src");
    preview.hidden = true;
    if (wrap) wrap.hidden = true;
  };

  if (input && preview) {
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) {
        clearPhoto();
        return;
      }
      showPreview(file);
    });
  }

  if (clearBtn) clearBtn.addEventListener("click", clearPhoto);

  if (form && btn) {
    form.addEventListener("submit", () => {
      btn.disabled = true;
      btn.textContent = "Отправляем…";
      if (hint) hint.hidden = false;
    });
  }

  const script = document.currentScript;
  const statusUrl = script && script.dataset.statusUrl;
  const watchPending = script && script.dataset.pending === "1";
  if (!statusUrl || !watchPending) return;

  let currentWasPending = Boolean(document.getElementById("pendingCard"));
  const tick = async () => {
    try {
      const res = await fetch(statusUrl, { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      const pending = new Set(data.pending_ids || []);
      const correct = new Set(data.correct_ids || []);
      document.querySelectorAll(".task-dots a[data-id]").forEach((a) => {
        const id = Number(a.dataset.id);
        a.classList.toggle("wait", pending.has(id));
        a.classList.toggle("ok", correct.has(id));
      });
      if (currentWasPending && !data.current_pending) {
        window.location.reload();
      }
      currentWasPending = Boolean(data.current_pending);
    } catch (_err) {
      /* сеть могла моргнуть — следующий тик повторит */
    }
  };
  setInterval(tick, 4000);
})();
