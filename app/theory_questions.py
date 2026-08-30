from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .config import INSTANCE_DIR
from .ai_checker import ai_configured, _client

if TYPE_CHECKING:
    from .theory_cards import TheoryCard

log = logging.getLogger(__name__)

CACHE_PATH = INSTANCE_DIR / "theory_card_questions.json"
BATCH_SIZE = 8
KIND_PREFIX_RE = re.compile(
    r"^(ОПРЕДЕЛЕНИЕ|АКСИОМА|ТЕОРЕМА|СВОЙСТВО|ПРИЗНАК|СЛЕДСТВИЕ|ПРАВИЛО):\s*",
    re.I,
)
STEM_TAIL_RE = re.compile(r"(?:\s*[–—-]\s*ЭТО)?\s*\.{0,3}\s*\?\s*$", re.I)

SYSTEM_PROMPT = """Ты составляешь лицевую сторону карточек для повторения школьной математики (Беларусь, 7–9 классы).
Ученик сначала видит ВОПРОС и подсказку (рисунок или пример), сам вспоминает формулировку, потом смотрит ответ.

Правила вопроса:
- В вопросе НЕ должно быть готового ответа и нельзя копировать начало определения/свойства/аксиомы/теоремы, обрывая его многоточием.
- Плохо: «ЧЕРЕЗ ЛЮБЫЕ ДВЕ ТОЧКИ ПЛОСКОСТИ МОЖНО ПРОВЕСТИ ПРЯМУЮ...?» (это уже почти вся аксиома).
- Хорошо: «СКОЛЬКО ПРЯМЫХ МОЖНО ПРОВЕСТИ ЧЕРЕЗ ДВЕ ТОЧКИ ПЛОСКОСТИ...?» или «ЧТО УТВЕРЖДАЕТ АКСИОМА О ДВУХ ТОЧКАХ И ПРЯМОЙ...?»
- Для определения с названием термина оставь шаблон «ОКРУЖНОСТЬ – ЭТО...?», если термин короткий и сам по себе не раскрывает определение.
- Для свойств и правил спрашивай ДЕЙСТВИЕ, не результат: «КАК УМНОЖАЮТ СТЕПЕНИ С ОДИНАКОВЫМИ ОСНОВАНИЯМИ...?» — не «ОСНОВАНИЕ ОСТАЁТСЯ, А ПОКАЗАТЕЛИ СКЛАДЫВАЮТСЯ».
- Коротко, по-русски, заглавными буквами. Формулы оставляй в LaTeX $...$, их не делай капсом.
- Одна фраза, в конце «...?» или «– ЭТО...?». Без кавычек вокруг всего вопроса и без нумерации.

Верни ТОЛЬКО JSON вида:
{"items":[{"id":"...","question":"..."}]}
Для каждой входной карточки ровно один элемент с тем же id.
"""


def cache_path() -> Path:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_PATH


def _load_cache() -> dict[str, dict[str, str]]:
    path = cache_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(data: dict[str, dict[str, str]]) -> None:
    path = cache_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def answer_hash(answer_md: str) -> str:
    return hashlib.sha1((answer_md or "").encode("utf-8")).hexdigest()[:16]


def _question_stem(question: str) -> str:
    q = (question or "").upper().replace("Ё", "Е")
    q = KIND_PREFIX_RE.sub("", q)
    q = STEM_TAIL_RE.sub("", q)
    q = re.sub(r"\s+", " ", q).strip(" :,—–-")
    return q


def is_spoiler(question: str, answer_md: str) -> bool:
    """True if the question already states most of the answer."""
    stem = _question_stem(question)
    words = [w for w in re.findall(r"[A-ZА-Я0-9]+", stem) if len(w) > 2]
    if len(words) < 5:
        return False
    ans = (answer_md or "").upper().replace("Ё", "Е")
    ans = re.sub(r"\$\$?.+?\$\$?", " ", ans)
    ans = re.sub(r"[*_`#]", "", ans)
    ans = re.sub(r"\s+", " ", ans)
    chunk = " ".join(words[:10])
    if chunk and chunk in ans:
        return True
    first = ans.split(".")[0]
    hits = sum(1 for w in words if w in first)
    return hits / len(words) >= 0.72


def needs_rewrite(question: str, answer_md: str, kind: str = "") -> bool:
    if is_spoiler(question, answer_md):
        return True
    q = (question or "").upper()
    return "КАК ЗВУЧИТ" in q


def apply_question_overrides(cards: Iterable[TheoryCard]) -> None:
    cache = _load_cache()
    if not cache:
        return
    for card in cards:
        row = cache.get(card.id)
        if not isinstance(row, dict):
            continue
        if row.get("hash") != answer_hash(card.answer_md):
            continue
        q = (row.get("question") or "").strip()
        if q:
            card.question = q


def _parse_items(text: str) -> list[dict[str, str]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [x for x in data["items"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _complete_questions(payload: list[dict[str, str]]) -> list[dict[str, str]]:
    from .config import Config

    client = _client()
    model = Config.AI_MODEL
    user = json.dumps({"cards": payload}, ensure_ascii=False)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    last_err: Exception | None = None
    for json_mode in (True, False):
        try:
            body = dict(kwargs)
            extra: dict[str, Any] = {"reasoning": {"effort": "low"}}
            body["extra_body"] = extra
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**body)
            choice = resp.choices[0].message if resp.choices else None
            text = (choice.content or "") if choice else ""
            items = _parse_items(text)
            if items:
                return items
            last_err = RuntimeError("empty items")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning("question rewrite failed (json_mode=%s): %s", json_mode, exc)
            time.sleep(0.8)
    if last_err:
        raise last_err
    return []


def rewrite_spoiler_questions(cards: list[TheoryCard], *, force: bool = False) -> dict[str, int]:
    """Rewrite spoiler questions via AI and save to cache. Returns stats."""
    if not ai_configured():
        raise RuntimeError("Нет OPENROUTER_API_KEY — нельзя прогнать вопросы через ИИ.")
    cache = _load_cache()
    todo: list[TheoryCard] = []
    skipped = 0
    for card in cards:
        row = cache.get(card.id) if isinstance(cache.get(card.id), dict) else None
        fresh = row and row.get("hash") == answer_hash(card.answer_md) and (row.get("question") or "").strip()
        if fresh and not force:
            skipped += 1
            continue
        if force or needs_rewrite(card.question, card.answer_md, card.kind):
            todo.append(card)
        else:
            skipped += 1
    updated = 0
    failed = 0
    for i in range(0, len(todo), BATCH_SIZE):
        chunk = todo[i : i + BATCH_SIZE]
        payload = [
            {
                "id": c.id,
                "kind": c.kind_label,
                "heading_term": c.term,
                "current_question": c.question,
                "answer": (c.answer_md or "")[:900],
            }
            for c in chunk
        ]
        try:
            items = _complete_questions(payload)
            by_id = {str(x.get("id") or ""): str(x.get("question") or "").strip() for x in items}
            for card in chunk:
                q = by_id.get(card.id)
                if not q:
                    failed += 1
                    continue
                q = re.sub(r'^["«]|["»]$', "", q).strip()
                cache[card.id] = {"question": q, "hash": answer_hash(card.answer_md)}
                card.question = q
                updated += 1
            _save_cache(cache)
            log.info("rewrote %s / %s spoiler questions", min(i + BATCH_SIZE, len(todo)), len(todo))
        except Exception as exc:  # noqa: BLE001
            log.warning("batch failed at %s: %s", i, exc)
            failed += len(chunk)
            time.sleep(1.5)
    _save_cache(cache)
    return {"todo": len(todo), "updated": updated, "skipped": skipped, "failed": failed}
