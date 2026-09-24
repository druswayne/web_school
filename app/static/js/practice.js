(() => {
  const input = document.getElementById("photoInput");
  const preview = document.getElementById("photoPreview");
  const wrap = document.getElementById("photoPreviewWrap");
  const form = document.getElementById("practiceForm");
  const btn = document.getElementById("sendBtn");
  const hint = document.getElementById("waitHint");
  const clearBtn = document.getElementById("photoClear");
  let objectUrl = "";
  let sending = false;
  let generation = 0;
  let prepareTask = null;
  const prepared = new WeakSet();
  const MAX_SIDE = 1600;
  const JPEG_QUALITY = 0.93;

  const toGrayJpeg = async (file) => {
    if (!file || prepared.has(file)) return file;
    if (!/^image\//.test(file.type) || typeof createImageBitmap !== "function") return file;
    let bitmap;
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch (_err) {
      return file;
    }
    try {
      const long = Math.max(bitmap.width, bitmap.height);
      const scale = Math.min(1, MAX_SIDE / long);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d", { alpha: false });
      if (!ctx) return file;
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const px = frame.data;
      for (let i = 0; i < px.length; i += 4) {
        const y = (px[i] * 77 + px[i + 1] * 150 + px[i + 2] * 29) >> 8;
        px[i] = px[i + 1] = px[i + 2] = y;
      }
      ctx.putImageData(frame, 0, 0);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
      if (!blob) return file;
      const base = (file.name || "solution").replace(/\.[^.]+$/i, "") || "solution";
      const gray = new File([blob], `${base}.jpg`, { type: "image/jpeg", lastModified: Date.now() });
      prepared.add(gray);
      return gray;
    } finally {
      bitmap.close();
    }
  };

  const usePrepared = (file) => {
    if (!input || !file || file === input.files[0]) return;
    const data = new DataTransfer();
    data.items.add(file);
    input.files = data.files;
    showPreview(file);
  };

  const showPreview = (file) => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    preview.src = objectUrl;
    preview.hidden = false;
    if (wrap) wrap.hidden = false;
  };

  const clearPhoto = () => {
    generation += 1;
    prepareTask = null;
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
      const token = ++generation;
      showPreview(file);
      prepareTask = toGrayJpeg(file).then((small) => {
        if (token !== generation) return small;
        usePrepared(small);
        return small;
      }).catch(() => file);
    });
  }

  if (clearBtn) clearBtn.addEventListener("click", clearPhoto);

  if (form && btn) {
    form.addEventListener("submit", async (event) => {
      if (sending) return;
      const file = input && input.files && input.files[0];
      if (!file) return;
      event.preventDefault();
      btn.disabled = true;
      btn.textContent = "Готовим фото…";
      if (hint) hint.hidden = false;
      try {
        const small = await (prepareTask || toGrayJpeg(file));
        usePrepared(small);
      } catch (_err) {
        /* уйдёт исходный файл */
      }
      sending = true;
      btn.textContent = "Отправляем…";
      form.submit();
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
