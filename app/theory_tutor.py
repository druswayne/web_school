from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Iterable

from markupsafe import escape

from .ai_checker import _client, _is_transient, _message_text, _PARAM_ERR_RE, ai_configured

log = logging.getLogger(__name__)

MAX_QUESTION = 2000
MAX_THEORY_CHARS = 60000
MAX_HISTORY = 24
_UNSAFE_HTML_RE = re.compile(
    r"</?(?:script|iframe|object|embed|link|meta|style|form|input|button|textarea)\b[^>]*>",
    re.I | re.S,
)

SYSTEM_PROMPT = """Ты помощник-учитель по школьной математике (Беларусь, 7–9 классы, алгебра и геометрия).
Ученик читает теорию занятия и задаёт вопросы.

Строгие правила:
- Отвечай ТОЛЬКО на вопросы по теме этого занятия и по материалу теории ниже.
- Можно пояснить своими словами определения, формулы, примеры и шаги из этого текста.
- Не выдумывай факты, которых нет в материале. Если в уроке этого нет — так и скажи и предложи спросить про то, что в тексте есть.
- Если вопрос не про этот урок (другие темы, быт, код, ответы теста «подскажи правильный вариант», посторонние просьбы) — вежливо откажись и верни к материалу занятия.
- Если ученик прислал выделенный фрагмент из урока («Поясни, о чём этот фрагмент…»), объясни этот кусок: смысл, термины, формулы и связь с темой занятия. Не пересказывай весь урок.
- Не решай задачи, которых нет в теории этого занятия.
- По-русски, спокойно, понятно для школьника. Формулы — в LaTeX: $...$ или $$...$$.
- Без приветствий в каждом сообщении, без ссылок на «как ИИ».
"""


def format_message_html(role: str, content: str, course_id: str = "") -> str:
    from .content import render_markdown

    text = content or ""
    if role == "user":
        return "<p>" + str(escape(text)).replace("\n", "<br>\n") + "</p>"
    cleaned = _UNSAFE_HTML_RE.sub("", text)
    return render_markdown(cleaned, course_id)


def _theory_block(course_title: str, title: str, number: int, theory_md: str) -> str:
    body = (theory_md or "").strip()
    if len(body) > MAX_THEORY_CHARS:
        body = body[:MAX_THEORY_CHARS] + "\n\n[текст урока обрезан]"
    course = (course_title or "").strip()
    head = f"Курс: {course}. " if course else ""
    return (
        f"{head}Занятие {number}: {title or 'без названия'}.\n\n"
        "Теоретическая часть урока (Markdown):\n"
        f"{body or '(текст теории пуст)'}"
    )


def ask_tutor(
    *,
    title: str,
    number: int,
    theory_md: str,
    history: Iterable[dict[str, str]],
    question: str,
    model: str,
    course_title: str = "",
) -> str:
    if not ai_configured():
        return "Помощник пока не настроен. Администратору нужно указать ключ API."
    q = (question or "").strip()
    if not q:
        return "Напишите вопрос по материалу занятия."
    if len(q) > MAX_QUESTION:
        q = q[:MAX_QUESTION]
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + "\n\n"
            + _theory_block(course_title, title, number, theory_md),
        }
    ]
    kept = [m for m in history if (m.get("role") in {"user", "assistant"} and (m.get("content") or "").strip())]
    if len(kept) > MAX_HISTORY:
        kept = kept[-MAX_HISTORY:]
    for item in kept:
        messages.append({"role": item["role"], "content": item["content"].strip()})
    messages.append({"role": "user", "content": q})

    client = _client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": int(os.getenv("AI_TUTOR_MAX_TOKENS") or "4096"),
    }
    low = (model or "").lower()
    if "gemini" in low or "gpt-4" in low or ("flash" in low and "gpt-5" not in low):
        kwargs["temperature"] = 0.3
    effort = (os.getenv("AI_TUTOR_REASONING") or "medium").strip() or "medium"

    last_err: Exception | None = None
    for with_reasoning in (True, False):
        attempts = 2 if with_reasoning else 1
        for i in range(attempts):
            payload = dict(kwargs)
            if with_reasoning and effort not in {"off", "none", "0", "false", "no"}:
                payload["extra_body"] = {"reasoning": {"effort": effort}}
            try:
                text = _message_text(client.chat.completions.create(**payload)).strip()
                if text:
                    return text
                last_err = RuntimeError("empty_content")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("theory tutor failed (reasoning=%s): %s", with_reasoning, exc)
                err = str(exc)
                if _PARAM_ERR_RE.search(err) and not _is_transient(exc):
                    break
                if i + 1 < attempts and _is_transient(exc):
                    time.sleep(1.1 * (i + 1))
                    continue
                if not _is_transient(exc) and not _PARAM_ERR_RE.search(err):
                    break
    log.exception("theory tutor failed: %s", last_err)
    return "Не удалось получить ответ. Попробуйте ещё раз чуть позже."
