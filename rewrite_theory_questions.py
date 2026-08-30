"""Прогнать вопросы карточек теории через ИИ и сохранить формулировки без спойлеров."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.content import get_catalog  # noqa: E402
from app.theory_cards import parse_theory_file  # noqa: E402
from app.theory_questions import needs_rewrite, rewrite_spoiler_questions  # noqa: E402


def all_theory_cards():
    catalog = get_catalog()
    cards = []
    for bank in catalog.all():
        for item in bank.lesson_index():
            path = bank.theory_path(item["number"])
            cards.extend(
                parse_theory_file(
                    path,
                    bank.course_id,
                    item["number"],
                    branch=bank.branch,
                    lesson_title=item["title"],
                )
            )
    return cards


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cards = all_theory_cards()
    spoilers = [c for c in cards if needs_rewrite(c.question, c.answer_md, c.kind)]
    print(f"Всего карточек: {len(cards)}")
    print(f"С подозрением на ответ в вопросе: {len(spoilers)}")
    if spoilers:
        print("Примеры:")
        for c in spoilers[:8]:
            print(f"  [{c.kind_label}] {c.question}")
    stats = rewrite_spoiler_questions(cards)
    print(f"Обновлено: {stats['updated']}, пропущено: {stats['skipped']}, ошибок: {stats['failed']}")
    return 0 if stats["failed"] == 0 or stats["updated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
