from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import markdown
from markupsafe import Markup

from .config import CONTENT_ROOT, COURSE_ORDER, COURSE_TITLES, LEVEL_BANDS

LATIN_OPT = {"a": "а", "b": "б", "c": "в", "d": "г", "e": "д"}
CYR_OPTS = ("а", "б", "в", "г", "д")
LEVEL_HEAD_RE = re.compile(
    r"^###\s+Уровень\s+(1[–-]2|3[–-]4|5[–-]6|7[–-]8|9[–-]10)\s+балл",
    re.M,
)
TASK_SPLIT_RE = re.compile(r"(?=\*\*[СД]\d+\.)")
TASK_HEAD_RE = re.compile(r"^\*\*([СД](\d+)\.(?:[^*]|\*(?!\*))*)\*\*\s*", re.S)
NUM_TASK_SPLIT_RE = re.compile(r"(?m)(?=^\d+\.\s)")
TEST_Q_RE = re.compile(r"^##\s+(Т(\d+))\.\s*(?:\*\((.+?)\)\*)?\s*$", re.M)
TEST_ANS_RE = re.compile(
    r"\*\*Т(\d+)\.\*\*\s*([а-джa-eа-яё,\s]+)",
    re.I,
)
PRAC_ANS_SPLIT_RE = re.compile(
    r"\*{0,2}([СД])(\d+)\.?\*{0,2}\s*[—–:-]?\s*",
)
ANS_LETTER = {"С": "C", "Д": "D"}
MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.S)
MATH_PAREN_RE = re.compile(r"\\\(.+?\\\)", re.S)
MATH_BRACK_RE = re.compile(r"\\\[.+?\\\]", re.S)
MATH_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(?:\\.|[^$\\])+\$")
_MATH_ATOM = (
    r"(?:\([^()]{0,100}\)"
    r"|[A-Za-z](?:_[A-Za-z0-9]+)?"
    r"|\d+)"
)
_MATH_POW = rf"{_MATH_ATOM}(?:\s*\^\s*{_MATH_ATOM})+"
_MATH_SEP = r"(?:\s*(?:=|:|·|/)\s*|\s+[+\-]\s+)"
PLAIN_MATH_RE = re.compile(
    rf"(?<![A-Za-z0-9@\\])(-?{_MATH_POW}(?:{_MATH_SEP}-?(?:{_MATH_POW}|{_MATH_ATOM}))*)"
)
PRACTICE_HEAD = "## Практические задания"
THEORY_HEAD = "## Теория к занятию"
CHECKLIST_HEAD = "## Чек-лист"
try:
    MD = markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "nl2br", "pymdownx.tilde"],
        output_format="html",
    )
except ImportError:
    MD = markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        output_format="html",
    )


def normalize_band(raw: str) -> str:
    t = (raw or "").replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", "", t)
    m = re.search(r"(1-2|3-4|5-6|7-8|9-10)", t)
    return m.group(1) if m else t


def normalize_opt(letter: str) -> str:
    s = (letter or "").strip().lower()
    return LATIN_OPT.get(s, s)


def parse_opt_list(raw: str) -> list[str]:
    parts = re.split(r"[,\s;]+", (raw or "").strip())
    out: list[str] = []
    for p in parts:
        p = re.sub(r"[^а-яa-zё]", "", p.lower())
        if not p:
            continue
        n = normalize_opt(p)
        if n and n not in out:
            out.append(n)
    return out


def _section_after(text: str, start: str, stops: list[str]) -> str:
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


def _protect_math(text: str) -> tuple[str, dict[str, str]]:
    store: dict[str, str] = {}

    def hold(m: re.Match[str]) -> str:
        key = f"@@MATH{len(store)}@@"
        store[key] = m.group(0)
        return key

    text = MATH_BLOCK_RE.sub(hold, text)
    text = MATH_PAREN_RE.sub(hold, text)
    text = MATH_BRACK_RE.sub(hold, text)
    text = MATH_INLINE_RE.sub(hold, text)
    return text, store


def _plain_expr_to_tex(expr: str) -> str:
    s = (expr or "").strip()
    s = s.replace("·", r" \cdot ")
    s = s.replace("×", r" \times ")
    s = s.replace("≠", r" \ne ")
    s = re.sub(r"\^\(([^)]+)\)", r"^{\1}", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _wrap_plain_math(text: str, store: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        tex = _plain_expr_to_tex(m.group(1))
        if not tex:
            return m.group(0)
        key = f"@@MATH{len(store)}@@"
        store[key] = f"${tex}$"
        return key

    return PLAIN_MATH_RE.sub(repl, text or "")


def render_markdown(
    source: str,
    course_id: str = "",
    *,
    decorate_theory: bool = False,
) -> str:
    if not (source or "").strip():
        return ""
    text = source
    if course_id:
        text = text.replace("](figures/", f"](/media/figures/{course_id}/")
    else:
        text = text.replace("](figures/", "](/media/figures/")
    text, store = _protect_math(text)
    text = _wrap_plain_math(text, store)
    MD.reset()
    html = MD.convert(text)
    for key, val in store.items():
        html = html.replace(key, val)
    if decorate_theory:
        html = decorate_theory_html(html)
    return html


HEAD_RE = re.compile(r"<h([2-4])(?:\s[^>]*)?>.*?</h\1>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
SKIP_HEAD_RE = re.compile(
    r"^(?:[а-яёa-z]\)|\d+[\.)]|первый\b|второй\b|третий\b)",
    re.I,
)
THEORY_H2_RE = re.compile(
    r"<h2(?:\s[^>]*)?>\s*Теория к занятию\s*</h2>\s*",
    re.I,
)
MATH_PARA_RE = re.compile(r"<p>\s*(\$\$(?:\\.|[^$])+\$\$)\s*</p>", re.S)
LEAD_P_RE = re.compile(
    r"<p>(\s*<strong>(Условие|Решение|Ответ|Дано)[:.]?\s*</strong>)",
    re.I,
)
KIND_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ловушк", re.I), "trap"),
    (re.compile(r"нельзя путать", re.I), "warn"),
    (re.compile(r"формул", re.I), "formula"),
    (re.compile(r"определен", re.I), "definition"),
    (re.compile(r"теорем", re.I), "theorem"),
    (re.compile(r"аксиом", re.I), "axiom"),
    (re.compile(r"свойств", re.I), "property"),
    (re.compile(r"признак", re.I), "feature"),
    (re.compile(r"следстви", re.I), "corollary"),
    (re.compile(r"алгоритм|построен", re.I), "algorithm"),
    (re.compile(r"правил", re.I), "rule"),
    (re.compile(r"простыми словами", re.I), "plain"),
    (re.compile(r"^факт", re.I), "fact"),
    (re.compile(r"замечан", re.I), "note"),
    (re.compile(r"доказательств", re.I), "proof"),
    (re.compile(r"^дано\b|^условие\b", re.I), "given"),
    (re.compile(r"^решение\b", re.I), "solve"),
    (re.compile(r"^ответ\b", re.I), "answer"),
    (re.compile(r"разбор ключевых|ключев\w+\s+задан", re.I), "examples"),
    (re.compile(r"самопроверк|мини-проверк|мини-практик", re.I), "check"),
    (re.compile(r"итог|памятк", re.I), "summary"),
    (re.compile(r"^как\b|^чтобы\b", re.I), "algorithm"),
    (re.compile(r"пример", re.I), "example"),
    (re.compile(r"^р\d+|^\s*задани", re.I), "example"),
]
LEAD_KIND = {
    "условие": "given",
    "дано": "given",
    "решение": "solve",
    "ответ": "answer",
}


def _plain_heading(html: str) -> str:
    inner = re.sub(r"^<h[2-4](?:\s[^>]*)?>|</h[2-4]>$", "", html.strip(), flags=re.I)
    text = TAG_RE.sub("", inner)
    return re.sub(r"\s+", " ", text).strip()


def classify_theory_heading(level: int, title: str) -> str | None:
    raw = (title or "").strip()
    if not raw:
        return None
    if level == 2 and raw.lower().startswith("теория"):
        return None
    for rx, kind in KIND_RULES:
        if rx.search(raw):
            return kind
    if level == 4 and not SKIP_HEAD_RE.match(raw):
        return "aside"
    return None


def decorate_theory_html(html: str) -> str:
    if not (html or "").strip():
        return html or ""
    html = THEORY_H2_RE.sub("", html, count=1)
    marks = list(HEAD_RE.finditer(html))
    headings: list[dict[str, Any]] = []
    for m in marks:
        level = int(m.group(1))
        title = _plain_heading(m.group(0))
        kind = classify_theory_heading(level, title)
        headings.append(
            {
                "start": m.start(),
                "level": level,
                "kind": kind,
            }
        )
    events: list[tuple[int, int, int, str, str]] = []
    for i, h in enumerate(headings):
        if not h["kind"]:
            continue
        wrap_end = len(html)
        for nxt in headings[i + 1 :]:
            if nxt["level"] <= h["level"]:
                wrap_end = nxt["start"]
                break
        events.append((h["start"], 1, h["level"], "open", h["kind"]))
        events.append((wrap_end, 0, -h["level"], "close", h["kind"]))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    out: list[str] = []
    last = 0
    for pos, _phase, _tie, action, kind in events:
        out.append(html[last:pos])
        if action == "open":
            out.append(f'<section class="tbox tbox-{kind}">')
        else:
            out.append("</section>")
        last = pos
    out.append(html[last:])
    html = "".join(out)
    html = MATH_PARA_RE.sub(r'<div class="t-math">\1</div>', html)

    def lead_class(m: re.Match[str]) -> str:
        kind = LEAD_KIND.get(m.group(2).lower(), "aside")
        return f'<p class="t-lead t-lead-{kind}">{m.group(1)}'

    return LEAD_P_RE.sub(lead_class, html)


MULTI_LEADIN_RE = re.compile(
    r"^Выберите все верные (?:ответы|утверждения|записи)\.?\s*",
    re.I,
)


def display_prompt(prompt_md: str, multi: bool) -> str:
    text = (prompt_md or "").strip()
    if multi:
        text = MULTI_LEADIN_RE.sub("", text).strip()
    return text


@dataclass
class PracticeTask:
    code: str
    slot: int
    title: str
    text_md: str
    answer: str = ""
    kind: str = "class"


@dataclass
class TestQuestion:
    code: str
    number: int
    topic: str
    prompt_md: str
    options: list[tuple[str, str]]
    answers: list[str] = field(default_factory=list)
    multi: bool = False


@dataclass
class LessonContent:
    number: int
    title: str
    section: str
    date_label: str
    goals: list[str]
    theory_md: str
    practice: dict[str, list[PracticeTask]]
    test: list[TestQuestion]
    checklist: list[str] = field(default_factory=list)
    subtopics: list[str] = field(default_factory=list)
    course_id: str = ""
    paragraph: str = ""

    @property
    def theory_html(self) -> Markup:
        return Markup(
            render_markdown(self.theory_md, self.course_id, decorate_theory=True)
        )

    @property
    def theory_body(self) -> str:
        text = self.theory_md or ""
        text = re.sub(r"^##\s+Теория к занятию\s*", "", text).strip()
        return text

    def practice_for(self, band: str | None = None) -> list[PracticeTask]:
        key = normalize_band(band or "")
        if key in self.practice:
            return self.practice[key]
        return self.practice.get("1-2") or []


BAND_GOAL_RE = re.compile(
    r"(?:^|\*\*)\s*(1-2|3-4|5-6|7-8|9-10)\s*балл",
    re.I,
)


def _is_level_choice_goal(text: str) -> bool:
    t = (text or "").lower().replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", " ", t).strip()
    if BAND_GOAL_RE.search(t):
        return True
    if any(t.startswith(p) for p in ("выбирай блок", "выбери блок", "выберите блок")):
        return True
    if "1-2" in t and any(x in t for x in ("3-4", "5-6", "7-8", "9-10")):
        return any(w in t for w in ("блок", "уровн", "выбир", "выбра"))
    return False


def _parse_goals(md: str) -> list[str]:
    block = _section_after(md, "## Цели занятия", [THEORY_HEAD, "## Тайминг", PRACTICE_HEAD])
    items: list[str] = []
    for line in block.splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        item = s[2:].strip()
        if _is_level_choice_goal(item):
            continue
        items.append(item)
    return items


def _parse_checklist(md: str) -> list[str]:
    block = _section_after(md, CHECKLIST_HEAD, ["## "])
    items: list[str] = []
    for line in block.splitlines():
        s = line.strip()
        m = re.match(r"^- \[[ xX]\]\s*(.+)$", s)
        if m:
            items.append(m.group(1).strip())
        elif s.startswith("- ") and "чек-лист" not in s.lower():
            items.append(s[2:].strip())
    return items


def _split_level_blocks(section: str) -> dict[str, str]:
    matches = list(LEVEL_HEAD_RE.finditer(section))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        band = normalize_band(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        out[band] = section[start:end].strip()
    return out


def _clean_task_body(body: str) -> str:
    body = re.sub(r"^---\s*$", "", (body or "").strip(), flags=re.M).strip()
    if body.endswith("---"):
        body = body[: -len("---")].strip()
    return body


def _parse_star_tasks(
    block: str, *, slot_base: int = 0, kind: str = "class"
) -> list[PracticeTask]:
    tasks: list[PracticeTask] = []
    for chunk in TASK_SPLIT_RE.split(block or ""):
        chunk = chunk.strip()
        if not (chunk.startswith("**С") or chunk.startswith("**Д")):
            continue
        hm = TASK_HEAD_RE.match(chunk)
        if not hm:
            continue
        num = int(hm.group(2))
        code_letter = "D" if hm.group(1).startswith("Д") else "C"
        task_kind = "homework" if code_letter == "D" else kind
        title = hm.group(1).strip()
        body = _clean_task_body(chunk[hm.end() :])
        tasks.append(
            PracticeTask(
                code=f"{code_letter}{num}",
                slot=slot_base + num,
                title=title,
                text_md=body,
                kind=task_kind,
            )
        )
    return tasks


def _parse_numbered_tasks(
    block: str,
    *,
    code_prefix: str = "C",
    slot_base: int = 0,
    kind: str = "class",
) -> list[PracticeTask]:
    tasks: list[PracticeTask] = []
    for chunk in NUM_TASK_SPLIT_RE.split(block or ""):
        chunk = chunk.strip()
        m = re.match(r"^(\d+)\.\s+(.*)$", chunk, re.S)
        if not m:
            continue
        num = int(m.group(1))
        rest = m.group(2).strip()
        title_m = re.match(r"^(\*[^*]+\*)\s*(.*)$", rest, re.S)
        if title_m:
            title = f"{code_prefix}{num}. {title_m.group(1).strip('*').strip()}"
            body = _clean_task_body(title_m.group(2))
        else:
            title = f"{code_prefix}{num}."
            body = _clean_task_body(rest)
        tasks.append(
            PracticeTask(
                code=f"{code_prefix}{num}",
                slot=slot_base + num,
                title=title,
                text_md=body,
                kind=kind,
            )
        )
    return tasks


def _parse_tasks(
    block: str,
    *,
    code_prefix: str = "C",
    slot_base: int = 0,
    kind: str = "class",
) -> list[PracticeTask]:
    starred = _parse_star_tasks(block, slot_base=slot_base, kind=kind)
    if starred:
        return starred
    return _parse_numbered_tasks(
        block, code_prefix=code_prefix, slot_base=slot_base, kind=kind
    )


def _parse_options(body: str) -> tuple[str, list[tuple[str, str]]]:
    matches = list(re.finditer(r"(?:^|\n)\s*([абвгдеabcde])\)\s*", body))
    if not matches:
        return body.strip(), []
    prompt = body[: matches[0].start()].strip()
    options: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        letter = normalize_opt(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        val = body[start:end].strip().rstrip(";.").strip()
        val = val.rstrip(";").strip()
        options.append((letter, val))
    return prompt, options


def _parse_test(test_md: str, answers_md: str) -> list[TestQuestion]:
    keys: dict[int, list[str]] = {}
    for m in TEST_ANS_RE.finditer(answers_md or ""):
        keys[int(m.group(1))] = parse_opt_list(m.group(2))
    questions: list[TestQuestion] = []
    marks = list(TEST_Q_RE.finditer(test_md or ""))
    for i, m in enumerate(marks):
        num = int(m.group(2))
        topic = (m.group(3) or "").strip()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(test_md)
        raw = test_md[start:end].strip()
        prompt, options = _parse_options(raw)
        answers = keys.get(num, [])
        low = (prompt + " " + raw).lower()
        multi = ("выберите все" in low) or (len(answers) > 1)
        questions.append(
            TestQuestion(
                code=f"T{num}",
                number=num,
                topic=topic,
                prompt_md=prompt,
                options=options,
                answers=answers,
                multi=multi,
            )
        )
    return questions


def _load_course_index(root: Path) -> dict[str, Any]:
    path = root / "course.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _practice_from_cache(root: Path, number: int) -> dict[str, list[PracticeTask]]:
    cache = root / "cache" / "lessons"
    out: dict[str, list[PracticeTask]] = {}
    for band in LEVEL_BANDS:
        path = cache / f"{number:02d}_practice_{band}.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        tasks = _parse_tasks(text, kind="class")
        if tasks:
            out[band] = tasks
    return out


def _practice_from_lesson_md(md: str) -> dict[str, list[PracticeTask]]:
    block = _section_after(md, PRACTICE_HEAD, [CHECKLIST_HEAD])
    if not block:
        return {}
    out: dict[str, list[PracticeTask]] = {}
    for band, text in _split_level_blocks(block).items():
        tasks = _parse_tasks(text, kind="class")
        if tasks:
            out[band] = tasks
    return out


def load_lesson(
    root: Path,
    number: int,
    meta: dict[str, Any] | None = None,
    course_id: str = "",
) -> LessonContent | None:
    path = root / "lessons" / f"{number:02d}.md"
    if not path.is_file():
        return None
    md = path.read_text(encoding="utf-8")
    title_m = re.match(r"#\s+Занятие\s+\d+\.\s*(.+)", md)
    title = (title_m.group(1).strip() if title_m else "") or (meta or {}).get(
        "title"
    ) or f"Занятие {number}"
    theory = _section_after(md, THEORY_HEAD, [PRACTICE_HEAD, CHECKLIST_HEAD])
    if theory:
        theory = THEORY_HEAD + "\n\n" + theory
    practice = _practice_from_cache(root, number)
    if not practice:
        practice = _practice_from_lesson_md(md)
    test_path = root / "lessons" / f"{number:02d}_test.md"
    test_ans_path = root / "lessons" / f"{number:02d}_test_answers.md"
    test_md = test_path.read_text(encoding="utf-8") if test_path.is_file() else ""
    test_ans = test_ans_path.read_text(encoding="utf-8") if test_ans_path.is_file() else ""
    meta = meta or {}
    section = str(meta.get("section") or meta.get("chapter") or "")
    return LessonContent(
        number=number,
        title=title,
        section=section,
        date_label="",
        goals=_parse_goals(md),
        theory_md=theory,
        practice=practice,
        test=_parse_test(test_md, test_ans),
        checklist=_parse_checklist(md),
        subtopics=[],
        course_id=course_id,
        paragraph=str(meta.get("paragraph") or ""),
    )


class CourseBank:
    def __init__(self, course_id: str, root: Path | None = None) -> None:
        self.course_id = course_id
        self.root = Path(root or (CONTENT_ROOT / course_id))
        self.lessons: dict[int, LessonContent] = {}
        self.title = COURSE_TITLES.get(course_id, course_id)
        self.grade = 0
        self.branch = ""
        self._numbers: list[int] = []
        self._meta: dict[int, dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        data = _load_course_index(self.root)
        if data.get("title"):
            self.title = str(data["title"])
        self.grade = int(data.get("grade") or 0)
        self.branch = str(data.get("branch") or "")
        items = data.get("lessons") or []
        numbers: list[int] = []
        meta_map: dict[int, dict[str, Any]] = {}
        for item in items:
            n = int(item.get("number") or 0)
            if not n:
                continue
            numbers.append(n)
            meta_map[n] = item
        if not numbers:
            ldir = self.root / "lessons"
            if ldir.is_dir():
                for path in sorted(ldir.glob("[0-9][0-9].md")):
                    numbers.append(int(path.stem))
        self._numbers = numbers
        self._meta = meta_map

    def _ensure(self, number: int) -> LessonContent | None:
        n = int(number)
        if n in self.lessons:
            return self.lessons[n]
        if n not in self._numbers:
            return None
        lesson = load_lesson(self.root, n, self._meta.get(n), course_id=self.course_id)
        if lesson:
            self.lessons[n] = lesson
        return lesson

    def get(self, number: int) -> LessonContent:
        lesson = self._ensure(int(number))
        if not lesson:
            raise KeyError(f"Нет занятия {number} в курсе {self.course_id}")
        return lesson

    def all(self) -> list[LessonContent]:
        out: list[LessonContent] = []
        for n in self._numbers:
            lesson = self._ensure(n)
            if lesson:
                out.append(lesson)
        return out

    @property
    def count(self) -> int:
        return len(self._numbers)

    @property
    def numbers(self) -> list[int]:
        return list(self._numbers)

    def figures_dir(self) -> Path:
        return self.root / "lessons" / "figures"

    def theory_path(self, number: int) -> Path:
        return self.root / "theory" / f"{int(number):02d}.md"

    def lesson_index(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in self._numbers:
            meta = self._meta.get(n) or {}
            out.append(
                {
                    "number": n,
                    "title": str(meta.get("title") or f"Занятие {n}"),
                    "section": str(meta.get("section") or meta.get("chapter") or ""),
                }
            )
        return out


class Catalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or CONTENT_ROOT)
        self.courses: dict[str, CourseBank] = {}
        self._load()

    def _load(self) -> None:
        ids = list(COURSE_ORDER)
        if self.root.is_dir():
            extra = sorted(
                p.name
                for p in self.root.iterdir()
                if p.is_dir() and (p / "course.json").is_file() and p.name not in ids
            )
            ids.extend(extra)
        for cid in ids:
            path = self.root / cid
            if not path.is_dir():
                continue
            bank = CourseBank(cid, path)
            if bank.count or (path / "course.json").is_file():
                self.courses[cid] = bank

    def get(self, course_id: str) -> CourseBank:
        bank = self.courses.get(course_id)
        if not bank:
            raise KeyError(f"Нет курса {course_id}")
        return bank

    def all(self) -> list[CourseBank]:
        order = {cid: i for i, cid in enumerate(COURSE_ORDER)}
        return sorted(self.courses.values(), key=lambda c: (order.get(c.course_id, 99), c.course_id))

    @property
    def count(self) -> int:
        return len(self.courses)

    @property
    def lesson_total(self) -> int:
        return sum(c.count for c in self.courses.values())


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog()


def reload_catalog() -> Catalog:
    get_catalog.cache_clear()
    return get_catalog()


def get_course(course_id: str) -> CourseBank:
    return get_catalog().get(course_id)
