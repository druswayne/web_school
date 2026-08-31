from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import CONTENT_ROOT
from .content import get_catalog, get_course, render_markdown

KIND_MAP = {
    "определения": "definition",
    "аксиомы": "axiom",
    "свойства": "property",
    "теоремы": "theorem",
    "признаки": "feature",
    "следствия": "corollary",
    "правила и алгоритмы": "rule",
    "правила": "rule",
}
SKIP_SECTIONS = (
    "ключевые разобранные",
    "упражнения параграфа",
    "замечания учебника",
    "формулы",
)
KIND_LABELS = {
    "definition": "Определение",
    "axiom": "Аксиома",
    "property": "Свойство",
    "theorem": "Теорема",
    "feature": "Признак",
    "corollary": "Следствие",
    "rule": "Правило",
}
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
SUB_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
LATEX_RE = re.compile(r"\$\$.*?\$\$|\$(?!\$)(?:\\.|[^$\\])+\$", re.S)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
FIG_PAREN_RE = re.compile(
    r"\s*\(\s*(?:см\.\s*)?рис\.?\s*\d+(?:\s*[,;]\s*[а-яёa-z0-9]+)*\s*\)",
    re.I,
)
FIG_BARE_RE = re.compile(
    r"(?:(?<=\s)|(?<=^))(?:см\.\s*)?рис\.?\s*\d+(?:\s*[,;]\s*[а-яёa-z0-9]+)*\.?",
    re.I,
)


def _strip_figure_refs(text: str) -> str:
    t = FIG_PAREN_RE.sub("", text or "")
    t = FIG_BARE_RE.sub("", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r" {2,}", " ", t)
    t = re.sub(r"\s+([.,;:])", r"\1", t)
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"^\.\s*", "", t)
    return t.strip()


@dataclass
class TheoryCard:
    id: str
    course_id: str
    lesson_number: int
    kind: str
    term: str
    question: str
    answer_md: str
    hint_svg: str = ""
    hint_md: str = ""
    branch: str = ""
    lesson_title: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def answer_html(self) -> str:
        return render_markdown(_strip_figure_refs(self.answer_md))

    @property
    def hint_html(self) -> str:
        return render_markdown(self.hint_md) if self.hint_md else ""

    def to_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "lesson_number": str(self.lesson_number),
            "kind": self.kind,
            "kind_label": self.kind_label,
            "term": self.term,
            "question": self.question,
            "answer_html": self.answer_html,
            "hint_svg": self.hint_svg,
            "hint_html": self.hint_html,
            "branch": self.branch,
            "lesson_title": self.lesson_title,
        }


def _plain(text: str) -> str:
    def latex_to_text(match: re.Match) -> str:
        inner = match.group(0).strip("$")
        inner = re.sub(r"\\text\{([^}]*)\}", r"\1", inner)
        inner = re.sub(r"\\[a-zA-Z]+", " ", inner)
        inner = re.sub(r"[{}^_]", "", inner)
        return inner.strip() or " "

    t = LATEX_RE.sub(latex_to_text, text or "")
    t = BOLD_RE.sub(r"\1", t)
    t = re.sub(r"[*_`#]", "", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip(" ,;:")


def _upper_ru(text: str) -> str:
    return (text or "").upper().replace("Ё", "Е")


def _first_latex(text: str) -> str:
    m = LATEX_RE.search(text or "")
    return m.group(0).strip() if m else ""


def _latex_core(text: str) -> str:
    t = LATEX_RE.sub(lambda m: m.group(0).strip("$"), text or "")
    t = re.sub(r"\\underbrace\{(.+?)\}(?:_\{.*?\})?", r"\1", t)
    t = re.sub(r"\\text\{.*?\}", "", t)
    t = re.sub(r"[\s$]", "", t)
    return t


def _hint_spoils_answer(hint_md: str, answer_md: str) -> bool:
    h = _latex_core(hint_md)
    a = _latex_core(answer_md)
    return len(h) >= 6 and h in a


GENERIC_HEADINGS = {
    "свойство",
    "теорема",
    "следствие",
    "признак",
    "правило",
    "аксиома",
    "формула",
    "",
}


def _looks_like_statement(term: str) -> bool:
    t = (term or "").strip().lower()
    if not t or t in GENERIC_HEADINGS:
        return True
    if len(t.split()) >= 8:
        return True
    return t.startswith(
        ("при ", "если ", "через ", "для ", "когда ", "сумма ", "произведение ", "чтобы ")
    )


KIND_HEAD_RE = re.compile(
    r"^(Определение|Теорема|Свойство|Аксиома|Следствие|Признак|Правило|Формула)\.?\s*",
    re.I,
)


def _heading_statement(heading: str) -> str:
    """Full wording from ### line, if the heading itself is the definition/theorem."""
    rest = KIND_HEAD_RE.sub("", (heading or "").strip()).strip()
    rest = re.sub(r"^\((.+)\)$", r"\1", rest).strip()
    if not rest:
        return ""
    words = _plain(rest).split()
    if len(words) < 8 and not re.search(r"называется|называют|равна|равно\b", rest, re.I):
        return ""
    text = rest.rstrip(":").rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _answer_markdown(heading: str, body: str) -> str:
    stmt = _heading_statement(heading)
    body = (body or "").strip()
    if not stmt:
        return body
    if _plain(stmt).lower() in _plain(body).lower():
        return body
    return f"{stmt}\n\n{body}".strip()


def _question_from_heading(kind: str, heading: str, body: str) -> tuple[str, str]:
    raw = KIND_HEAD_RE.sub("", (heading or "").strip()).strip(" .")
    raw = re.sub(r"^\((.+)\)$", r"\1", raw)
    raw = re.split(r"\s+называется\b", raw, maxsplit=1, flags=re.I)[0]
    term = _plain(raw) if raw else ""
    words = term.split()
    if len(words) > 8:
        term = " ".join(words[:6])
    named = bool(term) and not _looks_like_statement(term)
    if named and kind == "definition":
        return term, f"{_upper_ru(term)} – ЭТО...?"
    if named and kind in {"theorem", "feature", "axiom"}:
        label = KIND_LABELS.get(kind, "").upper()
        return term, f"{label}: {_upper_ru(term)}...?"
    label = KIND_LABELS.get(kind, "Утверждение").upper()
    if kind == "definition":
        stem = _plain(body).split(".")[0]
        words = stem.split()[:6]
        hint = " ".join(words).strip()
        topic = _upper_ru(hint) if hint else label
        return term or hint, f"{topic} – ЭТО...?"
    return term or label.title(), f"КАК ЗВУЧИТ {label}...?"


def _split_sections(md: str) -> list[tuple[str, str]]:
    marks = list(SECTION_RE.finditer(md or ""))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        title = m.group(1).strip()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        out.append((title, md[start:end].strip()))
    return out


def _split_subs(block: str) -> list[tuple[str, str]]:
    marks = list(SUB_RE.finditer(block or ""))
    if not marks:
        return []
    out: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        title = m.group(1).strip()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
        body = block[start:end].strip()
        if body:
            out.append((title, body))
    return out


def _parse_examples(md: str) -> list[str]:
    examples: list[str] = []
    for title, body in _split_sections(md):
        if "ключевые разобранные" not in title.lower():
            continue
        for line in body.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            s = re.sub(r"^(\d+\.|###\s+Задани[ея].*?)\s*", "", s)
            s = s.strip(" —–-")
            if "$" in s or "показывает" in s.lower():
                examples.append(s.strip())
        for sub_title, sub_body in _split_subs(body):
            bit = (sub_body.split("\n")[0] or sub_title).strip()
            if bit:
                examples.append(bit)
    return examples[:20]


def _example_stem(ex: str) -> str:
    return re.split(r"\s+[—–-]\s+показывает", ex, maxsplit=1, flags=re.I)[0].strip()


def _match_example(body: str, examples: list[str], index: int = -1) -> str:
    latex = re.findall(r"\$([^$]+)\$", body or "")
    keys = [k.strip() for k in latex if len(k.strip()) >= 3]
    for ex in examples:
        for k in keys:
            if k in ex:
                return _example_stem(ex)
    if 0 <= index < len(examples):
        return _example_stem(examples[index])
    body_words = set(re.findall(r"[а-яё]{5,}", _plain(body).lower()))
    best = ""
    best_n = 1
    for ex in examples:
        n = len(body_words & set(re.findall(r"[а-яё]{5,}", _plain(ex).lower())))
        if n > best_n:
            best, best_n = ex, n
    if best:
        return _example_stem(best)
    return ""


def _svg_wrap(inner: str, vb: str = "0 0 360 180") -> str:
    return (
        f'<svg class="card-hint-svg" viewBox="{vb}" xmlns="http://www.w3.org/2000/svg" '
        'aria-hidden="true">'
        '<defs><radialGradient id="pt" cx="35%" cy="30%"><stop offset="0%" stop-color="#fff"/>'
        '<stop offset="100%" stop-color="#c5d4e8"/></radialGradient></defs>'
        f"{inner}</svg>"
    )


def _dot(x: float, y: float, label: str = "", lx: float | None = None, ly: float | None = None) -> str:
    lx = x if lx is None else lx
    ly = y - 18 if ly is None else ly
    lab = (
        f'<text x="{lx}" y="{ly}" fill="#fff" font-size="18" font-weight="700" '
        f'text-anchor="middle" font-family="Manrope,sans-serif">{label}</text>'
        if label
        else ""
    )
    return (
        f'<circle cx="{x}" cy="{y}" r="9" fill="url(#pt)" stroke="#fff" stroke-width="1.5"/>'
        f"{lab}"
    )


def _line(x1: float, y1: float, x2: float, y2: float, w: float = 6) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#fff" '
        f'stroke-width="{w}" stroke-linecap="round"/>'
    )


def geometry_svg(term: str, body: str) -> str:
    t = f"{term} {body}".lower()
    if "окружност" in t or "круг" in t:
        extra = ""
        if "радиус" in t:
            extra = _line(180, 100, 180 + 62, 100, 4) + _dot(180, 100, "O", 180, 78) + _dot(242, 100, "", 252, 88)
        elif "диаметр" in t:
            extra = _line(118, 100, 242, 100, 4) + _dot(180, 100, "O", 180, 78)
        elif "хорд" in t:
            extra = _line(130, 70, 240, 130, 4)
        else:
            extra = _dot(180, 100, "O", 180, 78)
        return _svg_wrap(
            f'<circle cx="180" cy="100" r="62" fill="none" stroke="#fff" stroke-width="5"/>{extra}'
        )
    if "равнобедрен" in t:
        return _svg_wrap(
            _line(180, 36, 70, 150) + _line(180, 36, 290, 150) + _line(70, 150, 290, 150)
            + _dot(180, 36, "A") + _dot(70, 150, "B", 70, 172) + _dot(290, 150, "C", 290, 172)
        )
    if "прямоугольн" in t and "треугольн" in t:
        return _svg_wrap(
            _line(90, 40, 90, 150) + _line(90, 150, 280, 150) + _line(90, 40, 280, 150)
            + '<rect x="90" y="132" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"/>'
            + _dot(90, 40, "A", 70, 44) + _dot(90, 150, "C", 70, 168) + _dot(280, 150, "B", 300, 168)
        )
    if "равносторон" in t:
        return _svg_wrap(
            _line(180, 40, 70, 150) + _line(180, 40, 290, 150) + _line(70, 150, 290, 150)
            + _dot(180, 40, "A") + _dot(70, 150, "B", 70, 172) + _dot(290, 150, "C", 290, 172)
        )
    if "треугольн" in t:
        return _svg_wrap(
            _line(80, 150, 180, 38) + _line(180, 38, 300, 150) + _line(80, 150, 300, 150)
            + _dot(180, 38, "A") + _dot(80, 150, "B", 70, 172) + _dot(300, 150, "C", 310, 172)
        )
    if "параллелограмм" in t:
        return _svg_wrap(
            _line(90, 50, 250, 50) + _line(60, 140, 220, 140) + _line(90, 50, 60, 140) + _line(250, 50, 220, 140)
            + _dot(90, 50, "A") + _dot(250, 50, "B") + _dot(220, 140, "C", 230, 168) + _dot(60, 140, "D", 50, 168)
        )
    if "ромб" in t:
        return _svg_wrap(
            _line(180, 30, 300, 100) + _line(300, 100, 180, 170) + _line(180, 170, 60, 100) + _line(60, 100, 180, 30)
        )
    if "трапец" in t:
        return _svg_wrap(
            _line(120, 50, 240, 50) + _line(70, 150, 290, 150) + _line(120, 50, 70, 150) + _line(240, 50, 290, 150)
        )
    if "прямоугольник" in t or "квадрат" in t:
        return _svg_wrap(
            '<rect x="90" y="40" width="180" height="120" fill="none" stroke="#fff" stroke-width="6" rx="4"/>'
        )
    if "параллельн" in t:
        return _svg_wrap(
            _line(40, 60, 320, 60) + _line(40, 130, 320, 130)
            + '<text x="330" y="66" fill="#fff" font-size="22">a</text>'
            + '<text x="330" y="136" fill="#fff" font-size="22">b</text>'
        )
    if "перпендикуляр" in t:
        return _svg_wrap(
            _line(40, 140, 320, 140) + _line(180, 40, 180, 140)
            + '<rect x="180" y="122" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"/>'
        )
    if "развернут" in t:
        return _svg_wrap(_line(40, 100, 320, 100) + _dot(180, 100, "O", 180, 78))
    if "прямой угол" in t or "прямым" in t:
        return _svg_wrap(
            _line(80, 40, 80, 140) + _line(80, 140, 260, 140)
            + '<rect x="80" y="122" width="18" height="18" fill="none" stroke="#fff" stroke-width="3"/>'
        )
    if "тупой" in t:
        return _svg_wrap(
            _line(180, 100, 60, 40) + _line(180, 100, 300, 130) + _dot(180, 100, "O")
        )
    if "остр" in t and "угол" in t:
        return _svg_wrap(
            _line(80, 150, 200, 40) + _line(80, 150, 300, 150) + _dot(80, 150, "A", 70, 172)
        )
    if "угол" in t or "биссектрис" in t:
        extra = ""
        if "биссектрис" in t:
            extra = _line(80, 150, 210, 70, 3)
        return _svg_wrap(
            _line(80, 150, 160, 40) + _line(80, 150, 300, 150) + extra + _dot(80, 150, "A", 64, 172)
        )
    if "луч" in t:
        return _svg_wrap(
            _line(70, 120, 310, 60) + _dot(110, 112, "A", 110, 90)
            + '<polygon points="318,58 292,48 296,72" fill="#fff"/>'
        )
    if "прямая" in t or "плоскост" in t:
        return _svg_wrap(
            _line(30, 130, 330, 50) + _dot(120, 108, "A") + _dot(240, 78, "B")
        )
    if "отрезок" in t or "точка" in t:
        return _svg_wrap(
            _line(50, 130, 310, 55) + _dot(110, 114, "A", 110, 92) + _dot(250, 72, "B", 250, 50)
        )
    if "пирамид" in t:
        return _svg_wrap(
            _line(180, 30, 70, 150) + _line(180, 30, 290, 150) + _line(180, 30, 200, 160)
            + _line(70, 150, 200, 160) + _line(200, 160, 290, 150) + _line(70, 150, 290, 150, 3)
        )
    if "куб" in t or "параллелепипед" in t:
        return _svg_wrap(
            '<rect x="70" y="60" width="140" height="100" fill="none" stroke="#fff" stroke-width="5"/>'
            '<rect x="130" y="30" width="140" height="100" fill="none" stroke="#fff" stroke-width="4"/>'
            + _line(70, 60, 130, 30, 4) + _line(210, 60, 270, 30, 4)
            + _line(70, 160, 130, 130, 4) + _line(210, 160, 270, 130, 4)
        )
    if "высот" in t:
        return _svg_wrap(
            _line(80, 150, 180, 38) + _line(180, 38, 300, 150) + _line(80, 150, 300, 150)
            + _line(180, 38, 180, 150, 3)
            + '<rect x="180" y="132" width="16" height="16" fill="none" stroke="#fff" stroke-width="3"/>'
        )
    if "медиан" in t:
        return _svg_wrap(
            _line(80, 150, 180, 38) + _line(180, 38, 300, 150) + _line(80, 150, 300, 150)
            + _line(180, 38, 190, 150, 3) + _dot(190, 150, "M", 190, 172)
        )
    return _svg_wrap(
        _line(50, 130, 310, 55) + _dot(110, 114, "A", 110, 92) + _dot(250, 72, "B", 250, 50)
    )


def _card_id(course_id: str, number: int, kind: str, heading: str, body: str) -> str:
    raw = f"{course_id}:{number}:{kind}:{heading}:{body[:180]}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{course_id}:{number:02d}:{kind}:{digest}"


def parse_theory_file(
    path: Path,
    course_id: str,
    number: int,
    *,
    branch: str = "",
    lesson_title: str = "",
) -> list[TheoryCard]:
    if not path.is_file():
        return []
    md = path.read_text(encoding="utf-8")
    examples = _parse_examples(md)
    cards: list[TheoryCard] = []
    for title, body in _split_sections(md):
        low = title.lower()
        if any(s in low for s in SKIP_SECTIONS):
            continue
        kind = KIND_MAP.get(low)
        if not kind:
            continue
        subs = _split_subs(body)
        if not subs:
            continue
        for i, (heading, sub) in enumerate(subs):
            if len(_plain(sub)) < 8 and not LATEX_RE.search(sub):
                continue
            term, question = _question_from_heading(kind, heading, sub)
            hint_svg = ""
            hint_md = ""
            if (branch or "").startswith("geometry") or branch == "geometry":
                hint_svg = geometry_svg(term, sub)
            elif kind == "definition":
                hint_md = _match_example(sub, examples, index=-1)
            else:
                hint_md = _match_example(sub, examples, index=i) or _first_latex(sub)
            if hint_md and _hint_spoils_answer(hint_md, sub):
                hint_md = ""
            cards.append(
                TheoryCard(
                    id=_card_id(course_id, number, kind, heading, sub),
                    course_id=course_id,
                    lesson_number=number,
                    kind=kind,
                    term=term,
                    question=question,
                    answer_md=_answer_markdown(heading, sub),
                    hint_svg=hint_svg,
                    hint_md=hint_md,
                    branch=branch,
                    lesson_title=lesson_title,
                )
            )
    return cards


_CARD_CACHE: dict[str, tuple[float, list[TheoryCard]]] = {}
PARSER_VERSION = 3


def load_cards_for_selection(keys: list[str]) -> list[TheoryCard]:
    from .theory_questions import apply_question_overrides, cache_path

    catalog = get_catalog()
    stamp = 0.0
    qpath = cache_path()
    if qpath.is_file():
        stamp = max(stamp, qpath.stat().st_mtime)
    for key in keys:
        cid, _, num_s = key.partition(":")
        if not num_s.isdigit() or cid not in catalog.courses:
            continue
        path = get_course(cid).theory_path(int(num_s))
        if path.is_file():
            stamp = max(stamp, path.stat().st_mtime)
    cache_key = f"{PARSER_VERSION}|{'|'.join(keys)}"
    hit = _CARD_CACHE.get(cache_key)
    if hit and hit[0] == stamp:
        return hit[1]
    cards: list[TheoryCard] = []
    seen: set[str] = set()
    for key in keys:
        if ":" not in key:
            continue
        cid, _, num_s = key.partition(":")
        try:
            number = int(num_s)
        except ValueError:
            continue
        if cid not in catalog.courses:
            continue
        bank = get_course(cid)
        title = next((x["title"] for x in bank.lesson_index() if x["number"] == number), f"Занятие {number}")
        path = bank.theory_path(number)
        for card in parse_theory_file(
            path, cid, number, branch=bank.branch, lesson_title=title
        ):
            if card.id in seen:
                continue
            seen.add(card.id)
            cards.append(card)
    apply_question_overrides(cards)
    _CARD_CACHE[cache_key] = (stamp, cards)
    return cards


def parse_selection(form_list: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in form_list:
        key = (raw or "").strip()
        if not key or ":" not in key or key in seen:
            continue
        cid, _, num_s = key.partition(":")
        if not cid or not num_s.isdigit():
            continue
        seen.add(key)
        out.append(key)
    return out


def picker_payload() -> list[dict]:
    catalog = get_catalog()
    rows = []
    for bank in catalog.all():
        lessons = []
        for item in bank.lesson_index():
            lessons.append({**item, "has_theory": bank.theory_path(item["number"]).is_file()})
        rows.append(
            {
                "id": bank.course_id,
                "title": bank.title,
                "grade": bank.grade,
                "branch": bank.branch,
                "lessons": lessons,
                "theory_n": sum(1 for x in lessons if x["has_theory"]),
            }
        )
    return rows


def pick_next(
    cards: list[TheoryCard],
    counts: dict[str, tuple[int, datetime | None]],
    exclude_id: str | None = None,
    skip_ids: list[str] | set[str] | None = None,
) -> TheoryCard | None:
    if not cards:
        return None
    skip = set(skip_ids or ())
    pool = [c for c in cards if c.id != exclude_id]
    preferred = [c for c in pool if c.id not in skip]
    pool = preferred or pool or list(cards)
    min_ts = datetime.min.replace(tzinfo=timezone.utc)

    def sort_key(card: TheoryCard) -> tuple:
        n, ts = counts.get(card.id, (0, None))
        shown_at = ts or min_ts
        if shown_at.tzinfo is None:
            shown_at = shown_at.replace(tzinfo=timezone.utc)
        return (int(n or 0), ts is not None, shown_at, card.id)

    pool.sort(key=sort_key)
    return pool[0]


def theory_file_exists(root: Path | None, course_id: str, number: int) -> bool:
    base = Path(root or CONTENT_ROOT)
    return (base / course_id / "theory" / f"{int(number):02d}.md").is_file()
