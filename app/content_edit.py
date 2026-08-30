from __future__ import annotations

import re
from pathlib import Path

from .config import CONTENT_ROOT, LEVEL_BANDS, LEVEL_LABELS
from .content import (
    CYR_OPTS,
    LEVEL_HEAD_RE,
    PRACTICE_HEAD,
    TEST_Q_RE,
    THEORY_HEAD,
    CHECKLIST_HEAD,
    PracticeTask,
    TestQuestion,
    get_course,
    normalize_band,
    normalize_opt,
    reload_catalog,
)

CODE_PREFIX_RE = re.compile(r"^[СДCDсд]\d+\.?\s*")


def course_root(course_id: str, root: Path | None = None) -> Path:
    base = Path(root or CONTENT_ROOT)
    return base / course_id


def lesson_dir(course_id: str, root: Path | None = None) -> Path:
    return course_root(course_id, root) / "lessons"


def lesson_paths(course_id: str, number: int, root: Path | None = None) -> dict[str, Path]:
    d = lesson_dir(course_id, root)
    nn = f"{number:02d}"
    cache = course_root(course_id, root) / "cache" / "lessons"
    return {
        "md": d / f"{nn}.md",
        "test": d / f"{nn}_test.md",
        "test_answers": d / f"{nn}_test_answers.md",
        "practice_cache": cache,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n").rstrip() + "\n", encoding="utf-8")


def _finish_save() -> None:
    reload_catalog()


def _replace_section(text: str, heading: str, stops: list[str], new_body: str) -> str:
    idx = text.find(heading)
    body = (new_body or "").strip()
    if idx < 0:
        extra = f"\n\n{heading}\n\n{body}\n" if body else f"\n\n{heading}\n"
        return text.rstrip() + extra
    rest = text[idx + len(heading) :]
    cut = len(rest)
    for stop in stops:
        j = rest.find("\n" + stop)
        if j >= 0:
            cut = min(cut, j)
    return text[:idx] + heading + "\n\n" + body + "\n" + rest[cut:]


def _level_heading(band: str) -> str:
    return f"### Уровень {LEVEL_LABELS.get(band, band)}"


def _replace_level_block(section: str, band: str, new_block: str) -> str:
    heading = _level_heading(band)
    block = heading + "\n\n" + (new_block or "").strip() + "\n"
    matches = list(LEVEL_HEAD_RE.finditer(section or ""))
    for i, m in enumerate(matches):
        if normalize_band(m.group(1)) != band:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        return section[:start] + block + section[end:]
    if not (section or "").strip():
        return block
    return section.rstrip() + "\n\n" + block


def _preamble_before_questions(text: str) -> str:
    if not (text or "").strip():
        return ""
    starts: list[int] = []
    level = LEVEL_HEAD_RE.search(text)
    if level:
        starts.append(level.start())
    question = TEST_Q_RE.search(text)
    if question:
        starts.append(question.start())
    if not starts:
        return text.strip()
    return text[: min(starts)].strip()


def _strip_task_code(title: str) -> str:
    t = (title or "").strip().strip("*").strip()
    return CODE_PREFIX_RE.sub("", t).strip()


def format_practice_block(tasks: list[PracticeTask], letter: str) -> str:
    parts: list[str] = []
    for i, task in enumerate(tasks, start=1):
        code = f"{letter}{i}"
        rest = _strip_task_code(task.title)
        head = f"**{code}. {rest}**" if rest else f"**{code}.**"
        body = (task.text_md or "").strip()
        parts.append(f"{head}\n\n{body}".rstrip() if body else head)
    return "\n\n".join(parts)


def format_questions_md(questions: list[TestQuestion]) -> str:
    parts: list[str] = []
    for q in questions:
        head = f"## Т{q.number}."
        if q.topic:
            head += f" *({q.topic})*"
        lines = [head, "", (q.prompt_md or "").strip(), ""]
        for letter, text in q.options:
            lines.append(f"{letter}) {text}".rstrip())
        parts.append("\n".join(lines).strip())
    return "\n\n".join(parts)


def format_test_answers_md(questions: list[TestQuestion]) -> str:
    lines: list[str] = []
    for q in questions:
        letters = ", ".join(q.answers)
        if letters:
            lines.append(f"**Т{q.number}.** {letters}")
        else:
            lines.append(f"**Т{q.number}.**")
    return "\n".join(lines)


def tasks_from_form(form, prefix: str, *, kind: str, letter: str, slot_base: int) -> list[PracticeTask]:
    count = int(form.get(f"{prefix}_count") or 0)
    tasks: list[PracticeTask] = []
    n = 0
    for i in range(1, count + 1):
        title = (form.get(f"{prefix}{i}_title") or "").strip()
        text = (form.get(f"{prefix}{i}_text") or "").strip()
        answer = (form.get(f"{prefix}{i}_answer") or "").strip()
        if not title and not text and not answer:
            continue
        n += 1
        code = f"{letter}{n}"
        rest = _strip_task_code(title)
        full_title = f"{code}. {rest}" if rest else f"{code}."
        tasks.append(
            PracticeTask(
                code=code,
                slot=slot_base + n,
                title=full_title,
                text_md=text,
                answer=answer,
                kind=kind,
            )
        )
    return tasks


def questions_from_form(form) -> list[TestQuestion]:
    count = int(form.get("q_count") or 0)
    questions: list[TestQuestion] = []
    n = 0
    for i in range(1, count + 1):
        prompt = (form.get(f"q{i}_prompt") or "").strip()
        topic = (form.get(f"q{i}_topic") or "").strip()
        option_vals = [(v or "").strip() for v in form.getlist(f"q{i}_opt")]
        option_vals = [v for v in option_vals if v]
        answers_raw = form.getlist(f"q{i}_ans")
        if not prompt and not option_vals and not topic:
            continue
        n += 1
        options: list[tuple[str, str]] = []
        for letter, val in zip(CYR_OPTS, option_vals):
            options.append((letter, val))
        allowed = {o[0] for o in options}
        answers = []
        for raw in answers_raw:
            letter = normalize_opt(raw)
            if letter in allowed and letter not in answers:
                answers.append(letter)
        multi = form.get(f"q{i}_multi") == "1" or len(answers) > 1
        questions.append(
            TestQuestion(
                code=f"T{n}",
                number=n,
                topic=topic,
                prompt_md=prompt,
                options=options,
                answers=answers,
                multi=multi,
            )
        )
    return questions


def save_theory(course_id: str, number: int, body: str, root: Path | None = None) -> None:
    paths = lesson_paths(course_id, number, root)
    if not paths["md"].is_file():
        raise FileNotFoundError(f"Нет файла занятия {number}")
    text = paths["md"].read_text(encoding="utf-8")
    text = _replace_section(text, THEORY_HEAD, [PRACTICE_HEAD, CHECKLIST_HEAD], body)
    _write(paths["md"], text)
    _finish_save()


def save_test(course_id: str, number: int, questions: list[TestQuestion], root: Path | None = None) -> None:
    paths = lesson_paths(course_id, number, root)
    lesson = get_course(course_id).get(number)
    test_md = paths["test"].read_text(encoding="utf-8") if paths["test"].is_file() else ""
    ans_md = paths["test_answers"].read_text(encoding="utf-8") if paths["test_answers"].is_file() else ""
    preamble = _preamble_before_questions(test_md)
    if not preamble:
        preamble = (
            f"# Тест по теории. Занятие {number}. {lesson.title}\n\n"
            f"**Заданий:** {len(questions)}\n"
            "**Формат:** 4 варианта ответа (а–г). Верных может быть один или несколько. "
            "Если в условии сказано «Выберите все верные ответы» — отметьте все подходящие; иначе верный один."
        )
    else:
        preamble = re.sub(
            r"\*\*Заданий:\*\*\s*\d+",
            f"**Заданий:** {len(questions)}",
            preamble,
            count=1,
        )
    ans_preamble = _preamble_before_questions(ans_md)
    if not ans_preamble:
        ans_preamble = f"# Ответы к тесту по теории. Занятие {number}. {lesson.title}"
    _write(paths["test"], preamble.rstrip() + "\n\n" + format_questions_md(questions) + "\n")
    _write(
        paths["test_answers"],
        ans_preamble.rstrip() + "\n\n" + format_test_answers_md(questions) + "\n",
    )
    _finish_save()


def save_practice_band(
    course_id: str,
    number: int,
    band: str,
    tasks: list[PracticeTask],
    root: Path | None = None,
) -> None:
    band = normalize_band(band)
    if band not in LEVEL_BANDS:
        raise ValueError("Неизвестный уровень")
    paths = lesson_paths(course_id, number, root)
    if not paths["md"].is_file():
        raise FileNotFoundError(f"Нет файла занятия {number}")
    body = format_practice_block(tasks, "С")
    cache_path = paths["practice_cache"] / f"{number:02d}_practice_{band}.md"
    _write(cache_path, body)

    md = paths["md"].read_text(encoding="utf-8")
    section = _section_inner(md, PRACTICE_HEAD, [CHECKLIST_HEAD])
    section = _replace_level_block(section, band, body)
    md = _replace_section(md, PRACTICE_HEAD, [CHECKLIST_HEAD], section)
    _write(paths["md"], md)
    _finish_save()


def _section_inner(text: str, start: str, stops: list[str]) -> str:
    idx = text.find(start)
    if idx < 0:
        return ""
    rest = text[idx + len(start) :]
    cut = len(rest)
    for stop in stops:
        j = rest.find("\n" + stop)
        if j >= 0:
            cut = min(cut, j)
    return rest[:cut].strip()
