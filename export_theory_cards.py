"""Выгрузить вопросы и ответы карточек теории: один markdown-файл на класс."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.content import get_catalog  # noqa: E402
from app.theory_cards import (  # noqa: E402
    _strip_figure_refs,
    parse_theory_file,
)
from app.theory_questions import apply_question_overrides  # noqa: E402

OUT_DIR = ROOT / "theory_cards_export"


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
    apply_question_overrides(cards)
    return cards


def _md_escape_heading(text: str) -> str:
    return (text or "").replace("\n", " ").strip()


def render_grade(grade: int, cards) -> str:
    cards = sorted(
        cards,
        key=lambda c: (
            0 if (c.branch or "").startswith("algebra") else 1,
            c.course_id,
            c.lesson_number,
            c.kind,
            c.term,
            c.id,
        ),
    )
    lines: list[str] = [
        f"# Карточки теории — {grade} класс",
        "",
        f"Всего карточек: **{len(cards)}**.",
        "",
    ]
    prev_course = None
    prev_lesson = None
    n = 0
    for card in cards:
        if card.course_id != prev_course:
            title = {
                "math_5": "Математика 5 класс",
                "math_6": "Математика 6 класс",
                "algebra_7": "Алгебра 7 класс",
                "algebra_8": "Алгебра 8 класс",
                "algebra_9": "Алгебра 9 класс",
                "geometry_7": "Геометрия 7 класс",
                "geometry_8": "Геометрия 8 класс",
                "geometry_9": "Геометрия 9 класс",
            }.get(card.course_id, card.course_id)
            lines.append(f"## {title}")
            lines.append("")
            prev_course = card.course_id
            prev_lesson = None
        if card.lesson_number != prev_lesson:
            lesson_title = _md_escape_heading(card.lesson_title) or f"Занятие {card.lesson_number}"
            lines.append(f"### Занятие {card.lesson_number}. {lesson_title}")
            lines.append("")
            prev_lesson = card.lesson_number
        n += 1
        answer = _strip_figure_refs(card.answer_md).strip()
        lines.append(f"**{n}. {card.kind_label}.** {card.question}")
        lines.append("")
        lines.append("**Ответ.**")
        lines.append("")
        lines.append(answer)
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    cards = all_theory_cards()
    by_grade: dict[int, list] = defaultdict(list)
    unknown = 0
    for card in cards:
        grade = 0
        for part in (card.course_id or "").split("_"):
            if part.isdigit():
                grade = int(part)
                break
        if grade:
            by_grade[grade].append(card)
        else:
            unknown += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Всего карточек: {len(cards)}")
    for grade in sorted(by_grade):
        group = by_grade[grade]
        path = OUT_DIR / f"{grade}_klass.md"
        path.write_text(render_grade(grade, group), encoding="utf-8")
        print(f"  {grade} klass: {len(group)} -> {path.name}")
    if unknown:
        print(f"  без класса: {unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
