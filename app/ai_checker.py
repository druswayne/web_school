from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image, ImageOps

from .config import PROJECT_ROOT, WEB_ROOT

load_dotenv(WEB_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты учитель школьной математики (Беларусь, 7–9 классы, алгебра и геометрия).
Тебе дают условие задачи и фотографию рукописного решения ученика.
Готового эталонного ответа нет — проверяй самостоятельно.

Сначала в режиме глубоких рассуждений (Think) сделай внутреннюю пошаговую проверку.
Эту таблицу и все внутренние поля ученик НЕ увидит — они только для тебя и для учителя.

Внутренняя проверка (обязательно, внимательно):
1. Разбери фото: перепиши ход решения так, как его записал ученик. Не додумывай пропущенные шаги.
   Запятая в рукописи — частая ловушка. В белорусской/русской записи 2,4 может быть десятичной дробью 2.4, но так же часто это перечисление целых. Если через запятую идут несколько чисел (особенно три и больше или со знаками), это СПИСОК, а не дроби: «2,4,6,-8» = 2, 4, 6 и −8, а НЕ 2.4, 6 и −8. Десятичная запятая вероятна только у одного числа с дробной частью (часто 1–2 цифры после запятой) и когда по условию нужен один ответ-величина. Если условие про корни, набор значений, координаты нескольких точек, перечисление — запятые разделяют элементы. При сомнении смотри контекст задачи и остальные шаги, не «склеивай» соседние целые в дробь.
2. Сам реши задачу по условию (независимо от ученика).
3. Проверь КАЖДЫЙ логический шаг ученика: действие → свой пересчёт → верно/неверно и почему.
   Смотри на арифметику, знаки, сокращение дробей, степени (в т.ч. нулевую), скобки, область определения, единицы, соответствие условию.
4. Итоговый ответ ученика сравни со СВОИМ независимым решением, учитывая эквивалентные формы (1,5 = 3/2 = 1 1/2; > и «больше» и т.п.). Снова не путай список «2, 4» с дробью 2,4.
5. Небольшой недочёт оформления при верном результате — это верно.
6. Если фото нечитаемое — verdict unclear, шаги можно не заполнять.

Правила для поля feedback (единственный текст, который увидит ученик):
- Не включай таблицу шагов, правильный ответ и готовое решение.
- Если верно: коротко подтверди. Можно дать совет по записи, без образцового решения.
- Если неверно: только подсказка по текущему уровню (см. сообщение пользователя). Не пиши правильный ответ и не исправляй шаг «как надо посчитать».
- По-русски, спокойно, 2–6 предложений.

Ответ — ТОЛЬКО JSON (без markdown-ограждений):
{
  "verdict": "correct" | "incorrect" | "unclear",
  "is_correct": true/false,
  "observed": "что разобрал на фото, кратко",
  "student_final_answer": "итоговый ответ ученика или пусто",
  "own_final_answer": "твой независимый ответ, кратко",
  "answers_match": true/false,
  "steps": [
    {
      "n": 1,
      "action": "действие ученика (как на фото)",
      "ok": true,
      "check": "внутренняя проверка: пересчёт и правило"
    }
  ],
  "first_error_step": null,
  "error_kind": "arithmetic|algebra|sign|fraction|power|logic|incomplete|other|",
  "error_detail": "точная внутренняя формулировка ошибки — не для ученика",
  "conclusion": "внутренний вывод для учителя",
  "feedback": "текст ученику по уровню подсказки"
}
"""

_HINT_LEVELS = {
    1: (
        "Уровень 1 — первая попытка. Не указывай конкретный шаг и не называй операцию. "
        "Скажи, что решение пока неверно, предложи внимательно перепроверить ход и вычисления."
    ),
    2: (
        "Уровень 2. Можно указать ПРИМЕРНУЮ область: начало / середина / конец решения "
        "или тип действия (дроби, степени, скобки, знак, подстановка), без правильного результата."
    ),
    3: (
        "Уровень 3. Укажи, какой шаг или переход пересмотреть, и какое правило проверить. "
        "Не подставляй верные числа вместо ошибочных и не давай готовый ответ."
    ),
    4: (
        "Уровень 4+. Можно точнее показать место ошибки (какой переход, какое действие) "
        "и напомнить правило. Всё ещё нельзя выписывать готовое верное решение."
    ),
}


def ai_configured() -> bool:
    return bool(
        os.getenv("OPENROUTER_API_KEY", "").strip()
        or os.getenv("TIMEWEB_API_KEY", "").strip()
    )


def _client():
    from openai import OpenAI

    api_key = (
        os.getenv("OPENROUTER_API_KEY", "").strip()
        or os.getenv("TIMEWEB_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("Нет OPENROUTER_API_KEY")
    base_url = (
        os.getenv("OPENROUTER_BASE_URL", "").strip()
        or os.getenv("TIMEWEB_BASE_URL", "").strip()
        or "https://openrouter.ai/api/v1"
    ).rstrip("/")
    headers: dict[str, str] = {}
    if os.getenv("OPENROUTER_HTTP_REFERER", "").strip():
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    if os.getenv("OPENROUTER_APP_TITLE", "").strip():
        headers["X-Title"] = os.getenv("OPENROUTER_APP_TITLE", "").strip()
    timeout = int(os.getenv("AI_CHECK_TIMEOUT") or os.getenv("REQUEST_TIMEOUT") or "240")
    retries = int(os.getenv("AI_CHECK_HTTP_RETRIES") or "2")
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max(0, retries),
        default_headers=headers or None,
    )


def _reasoning_extra(model: str) -> dict[str, Any] | None:
    """Включить Think. У Gemini на OpenRouter — бюджет токенов, не effort."""
    raw = (os.getenv("AI_REASONING_EFFORT") or "high").strip().lower()
    if raw in {"off", "none", "0", "false", "no"}:
        return None
    max_think = (os.getenv("AI_REASONING_MAX_TOKENS") or "").strip()
    name = (model or "").lower()
    effort = raw if raw in {"minimal", "low", "medium", "high", "xhigh", "max"} else "high"
    if "gemini" in name:
        budget = int(max_think) if re.fullmatch(r"-?\d+", max_think) else 8192
        return {"reasoning": {"max_tokens": budget}}
    reasoning: dict[str, Any] = {"effort": effort}
    if max_think.isdigit():
        reasoning["max_tokens"] = int(max_think)
    return {"reasoning": reasoning}


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                bits.append(str(part.get("text") or ""))
            else:
                bits.append(str(getattr(part, "text", None) or ""))
        return "".join(bits)
    return str(content)


def _api_error_text(resp: Any) -> str:
    """OpenRouter часто кладёт ошибку в тело 200 OK при choices=None."""
    err = getattr(resp, "error", None)
    if err is None:
        extra = getattr(resp, "model_extra", None)
        if isinstance(extra, dict):
            err = extra.get("error")
        elif extra is not None:
            err = getattr(extra, "error", None)
    if not err:
        return ""
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or err)
    return str(getattr(err, "message", None) or err)


def _message_text(resp: Any) -> str:
    if resp is None:
        raise RuntimeError("Пустой ответ API")
    api_err = _api_error_text(resp)
    choices = getattr(resp, "choices", None)
    if not choices:
        raise RuntimeError(api_err or "empty_choices")
    choice = choices[0]
    if choice is None:
        raise RuntimeError(api_err or "empty_choices")
    msg = getattr(choice, "message", None)
    if msg is None:
        text = _content_to_text(getattr(choice, "text", None)).strip()
        if text:
            return text
        raise RuntimeError(api_err or "empty_choices")
    text = _content_to_text(getattr(msg, "content", None)).strip()
    if text:
        return text
    for attr in ("reasoning", "reasoning_content"):
        extra = _content_to_text(getattr(msg, attr, None)).strip()
        if extra:
            return extra
    raise RuntimeError(api_err or "empty_content")


def prepare_photo(src: Path, dest: Path, max_side: int = 1600) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        gray = ImageOps.grayscale(im)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        w, h = gray.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1:
            gray = gray.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        gray.save(buf, format="JPEG", quality=82, optimize=True)
        dest.write_bytes(buf.getvalue())
    return dest


def _parse_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {
        "verdict": "error",
        "is_correct": False,
        "feedback": "Не удалось проверить решение. Попробуйте ещё раз чуть позже.",
        "observed": "",
        "steps": [],
        "_parse_failed": True,
    }


def _normalize_steps(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        n = item.get("n", i)
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = i
        out.append(
            {
                "n": n,
                "action": str(item.get("action") or "").strip(),
                "ok": bool(item.get("ok")),
                "check": str(item.get("check") or "").strip(),
            }
        )
    return out


def _hint_level(attempt_no: int) -> int:
    n = max(1, int(attempt_no or 1))
    return 4 if n >= 4 else n


_TRANSIENT_RE = re.compile(
    r"empty_choices|empty_content|nonetype|not subscriptable|timeout|timed out|"
    r"rate.?limit|429|502|503|504|overloaded|temporarily|connection|cloudflare|"
    r"try again|unavailable|gateway",
    re.I,
)
_PARAM_ERR_RE = re.compile(
    r"temperature|reasoning|extra_body|response_format|unsupported|"
    r"unknown parameter|unexpected keyword|max_tokens|max_completion_tokens",
    re.I,
)


def _is_transient(exc: BaseException) -> bool:
    return bool(_TRANSIENT_RE.search(str(exc)))


def _complete_once(
    client: Any,
    kwargs: dict[str, Any],
    model: str,
    *,
    use_reasoning: bool,
    json_mode: bool,
) -> str:
    payload = dict(kwargs)
    extra = dict(payload.pop("extra_body", {}) or {})
    if use_reasoning:
        reasoning = _reasoning_extra(model)
        if reasoning:
            extra.update(reasoning)
    if extra:
        payload["extra_body"] = extra
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**payload)
    return _message_text(resp)


def _request_model_text(client: Any, kwargs: dict[str, Any], model: str) -> str:
    """Think + JSON, затем упрощённые варианты при сбое провайдера."""
    variants = (
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    )
    last_err: Exception | None = None
    for use_reasoning, json_mode in variants:
        attempts = 2 if use_reasoning else 1
        for i in range(attempts):
            try:
                text = _complete_once(
                    client,
                    kwargs,
                    model,
                    use_reasoning=use_reasoning,
                    json_mode=json_mode,
                )
                if text.strip():
                    return text
                last_err = RuntimeError("empty_content")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                err = str(exc)
                log.warning("AI check request failed (reasoning=%s json=%s): %s", use_reasoning, json_mode, exc)
                if _PARAM_ERR_RE.search(err) and not _is_transient(exc):
                    break
                if i + 1 < attempts and _is_transient(exc):
                    time.sleep(1.2 * (i + 1))
                    continue
                if not _is_transient(exc) and not _PARAM_ERR_RE.search(err):
                    break
    if last_err:
        raise last_err
    raise RuntimeError("empty_content")


def check_solution(
    *,
    task_md: str,
    image_path: Path,
    model: str,
    attempt_no: int = 1,
    previous_feedback: list[str] | None = None,
) -> dict[str, Any]:
    if not ai_configured():
        return {
            "verdict": "error",
            "is_correct": False,
            "feedback": "Проверка ИИ не настроена. Администратору нужно указать OPENROUTER_API_KEY.",
            "observed": "",
            "raw": None,
        }
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    level = _hint_level(attempt_no)
    prev = [p.strip() for p in (previous_feedback or []) if (p or "").strip()]
    prev_block = ""
    if prev:
        numbered = "\n".join(f"- попытка {i}: {text}" for i, text in enumerate(prev, 1))
        prev_block = (
            "\n\nПодсказки, которые ученик уже получил (не повторяй их дословно, "
            f"сделай следующую конкретнее по уровню {level}):\n{numbered}"
        )
    user_text = (
        "Условие задачи (Markdown/LaTeX):\n"
        f"{task_md.strip()}\n\n"
        "На фото — рукописное решение ученика. Эталонного ответа нет: реши задачу сам и сверь ход ученика.\n"
        f"Это попытка №{max(1, int(attempt_no or 1))}.\n"
        f"{_HINT_LEVELS[level]}"
        f"{prev_block}\n\n"
        "Сначала глубоко проверь каждый шаг (Think), затем верни только JSON."
    )
    client = _client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ],
        "max_tokens": int(os.getenv("AI_CHECK_MAX_TOKENS") or "8192"),
    }
    low = model.lower()
    if "gemini" in low or "gpt-4" in low or ("flash" in low and "gpt-5" not in low):
        kwargs["temperature"] = 0.1
    try:
        content = _request_model_text(client, kwargs, model)
        parsed = _parse_json(content)
        if parsed.get("_parse_failed"):
            log.warning("AI check JSON parse failed, retrying once")
            time.sleep(0.8)
            content = _complete_once(
                client, kwargs, model, use_reasoning=True, json_mode=True
            )
            parsed = _parse_json(content)
        if parsed.get("_parse_failed"):
            return {
                "verdict": "error",
                "is_correct": False,
                "feedback": "Не удалось проверить решение. Попробуйте ещё раз чуть позже.",
                "observed": "",
                "raw": None,
            }
    except Exception:
        log.exception("AI check failed")
        return {
            "verdict": "error",
            "is_correct": False,
            "feedback": "Не удалось проверить решение. Попробуйте ещё раз чуть позже.",
            "observed": "",
            "raw": None,
        }
    verdict = str(parsed.get("verdict") or "").lower()
    is_correct = bool(parsed.get("is_correct"))
    if verdict == "correct":
        is_correct = True
    elif verdict in {"incorrect", "unclear", "error"}:
        is_correct = False
    steps = _normalize_steps(parsed.get("steps"))
    first_error = parsed.get("first_error_step")
    if first_error in {"", "null", "None"}:
        first_error = None
    if first_error is not None:
        try:
            first_error = int(first_error)
        except (TypeError, ValueError):
            first_error = None
    feedback = str(parsed.get("feedback") or "").strip()
    if not feedback:
        feedback = "Проверка выполнена, но текст подсказки пустой. Попробуйте ещё раз."
    raw = {
        **parsed,
        "steps": steps,
        "first_error_step": first_error,
        "hint_level": level,
        "attempt_no": max(1, int(attempt_no or 1)),
    }
    return {
        "verdict": verdict or ("correct" if is_correct else "incorrect"),
        "is_correct": is_correct,
        "feedback": feedback,
        "observed": str(parsed.get("observed") or ""),
        "raw": raw,
    }
