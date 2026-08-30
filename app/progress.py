from __future__ import annotations

import math
from typing import Any

from flask import current_app

from .config import LEVEL_BANDS
from .content import get_catalog, get_course
from .models import (
    ActivityLog,
    CourseAccess,
    LessonAccess,
    LessonProgress,
    PracticeAssignment,
    PracticeAttempt,
    TestAttempt,
    User,
    UserAchievement,
    db,
    utcnow,
)


def log_activity(
    user_id: int,
    action: str,
    *,
    course_id: str | None = None,
    lesson_number: int | None = None,
    details: dict[str, Any] | None = None,
    actor_id: int | None = None,
) -> None:
    db.session.add(
        ActivityLog(
            user_id=user_id,
            actor_id=actor_id,
            course_id=course_id,
            lesson_number=lesson_number,
            action=action,
            details=details or {},
        )
    )


def meets_percent(correct: int, total: int, percent: float) -> bool:
    if total <= 0:
        return False
    need = max(1, int(round(total * percent / 100.0)))
    return correct >= need


def get_or_create_progress(user_id: int, course_id: str, lesson_number: int) -> LessonProgress:
    row = LessonProgress.query.filter_by(
        user_id=user_id, course_id=course_id, lesson_number=lesson_number
    ).first()
    if row:
        return row
    row = LessonProgress(user_id=user_id, course_id=course_id, lesson_number=lesson_number)
    db.session.add(row)
    db.session.flush()
    return row


def get_course_access(user_id: int, course_id: str) -> CourseAccess | None:
    return CourseAccess.query.filter_by(user_id=user_id, course_id=course_id).first()


def is_course_unlocked(user: User, course_id: str) -> bool:
    if user.is_admin:
        return True
    row = get_course_access(user.id, course_id)
    return bool(row and row.unlocked)


def set_course_access(
    user_id: int,
    course_id: str,
    unlocked: bool,
    actor_id: int | None = None,
) -> CourseAccess:
    row = get_course_access(user_id, course_id)
    if row is None:
        row = CourseAccess(user_id=user_id, course_id=course_id)
        db.session.add(row)
    row.unlocked = unlocked
    row.updated_at = utcnow()
    log_activity(
        user_id,
        "course_unlocked" if unlocked else "course_locked",
        course_id=course_id,
        details={"source": "admin"},
        actor_id=actor_id,
    )
    if unlocked:
        set_access(user_id, course_id, 1, True, source="progress", actor_id=actor_id)
    return row


def accessible_course_ids(user: User) -> list[str]:
    catalog = get_catalog()
    if user.is_admin:
        return [c.course_id for c in catalog.all()]
    rows = CourseAccess.query.filter_by(user_id=user.id, unlocked=True).all()
    have = {r.course_id for r in rows}
    return [c.course_id for c in catalog.all() if c.course_id in have]


def get_access(user_id: int, course_id: str, lesson_number: int) -> LessonAccess | None:
    return LessonAccess.query.filter_by(
        user_id=user_id, course_id=course_id, lesson_number=lesson_number
    ).first()


def is_unlocked(user: User, course_id: str, lesson_number: int) -> bool:
    if user.is_admin:
        return True
    if not is_course_unlocked(user, course_id):
        return False
    if lesson_number == 1:
        row = get_access(user.id, course_id, 1)
        if row is None:
            return True
        return bool(row.unlocked)
    row = get_access(user.id, course_id, lesson_number)
    return bool(row and row.unlocked)


def set_access(
    user_id: int,
    course_id: str,
    lesson_number: int,
    unlocked: bool,
    source: str = "admin",
    actor_id: int | None = None,
) -> LessonAccess:
    row = get_access(user_id, course_id, lesson_number)
    if row is None:
        row = LessonAccess(
            user_id=user_id, course_id=course_id, lesson_number=lesson_number
        )
        db.session.add(row)
    row.unlocked = unlocked
    row.source = source
    row.updated_at = utcnow()
    log_activity(
        user_id,
        "lesson_unlocked" if unlocked else "lesson_locked",
        course_id=course_id,
        lesson_number=lesson_number,
        details={"source": source},
        actor_id=actor_id,
    )
    return row


def unlock_next_if_needed(user: User, course_id: str, lesson_number: int) -> None:
    bank = get_course(course_id)
    nxt = lesson_number + 1
    if nxt not in bank.numbers:
        return
    existing = get_access(user.id, course_id, nxt)
    if existing and existing.unlocked:
        return
    if existing and not existing.unlocked and existing.source == "admin":
        return
    set_access(user.id, course_id, nxt, True, source="progress")


def bootstrap_student(user: User, course_ids: list[str] | None = None, *, all_lessons: bool = False) -> None:
    catalog = get_catalog()
    ids = course_ids if course_ids is not None else []
    for cid in ids:
        if cid not in catalog.courses:
            continue
        set_course_access(user.id, cid, True)
        bank = catalog.get(cid)
        if all_lessons:
            for n in bank.numbers:
                set_access(user.id, cid, n, True, source="progress")
        else:
            set_access(user.id, cid, 1, True, source="progress")


def sync_student_courses(
    user: User,
    course_ids: list[str],
    actor_id: int | None = None,
) -> None:
    wanted = set(course_ids)
    catalog = get_catalog()
    for bank in catalog.all():
        cid = bank.course_id
        should = cid in wanted
        row = get_course_access(user.id, cid)
        if should and (row is None or not row.unlocked):
            set_course_access(user.id, cid, True, actor_id=actor_id)
        elif not should and row and row.unlocked:
            set_course_access(user.id, cid, False, actor_id=actor_id)


def theory_done(progress: LessonProgress) -> bool:
    return progress.theory_completed_at is not None


def format_duration(seconds: int | None) -> str:
    n = int(seconds or 0)
    if n <= 0:
        return ""
    if n < 60:
        return f"{n} с"
    minutes = int(round(n / 60))
    if minutes < 60:
        return f"{minutes} мин"
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{hours} ч {minutes} мин"
    return f"{hours} ч"


_MAX_READ_TICK = 45


def test_done(progress: LessonProgress) -> bool:
    return progress.test_passed_at is not None


def practice_done(progress: LessonProgress) -> bool:
    return progress.practice_passed_at is not None


def mark_theory_progress(
    user: User,
    course_id: str,
    lesson_number: int,
    pct: int,
    completed: bool,
    seconds: int = 0,
) -> LessonProgress:
    progress = get_or_create_progress(user.id, course_id, lesson_number)
    pct = max(0, min(100, int(pct)))
    if pct > progress.theory_scroll_pct:
        progress.theory_scroll_pct = pct
    add = max(0, min(_MAX_READ_TICK, int(seconds or 0)))
    if add:
        progress.theory_read_seconds = int(progress.theory_read_seconds or 0) + add
    if completed and not progress.theory_completed_at:
        progress.theory_completed_at = utcnow()
        progress.theory_scroll_pct = 100
        log_activity(
            user.id,
            "theory_complete",
            course_id=course_id,
            lesson_number=lesson_number,
            details={"read_seconds": progress.theory_read_seconds or 0},
        )
        grant_achievements(user)
    progress.updated_at = utcnow()
    return progress


def record_test_attempt(
    user: User,
    course_id: str,
    lesson_number: int,
    answers: dict[str, list[str]],
) -> TestAttempt:
    lesson = get_course(course_id).get(lesson_number)
    percent = float(current_app.config.get("TEST_PASS_PERCENT") or 80)
    questions = lesson.test
    details = []
    correct = 0
    for q in questions:
        selected = sorted(answers.get(q.code) or [])
        expected = sorted(q.answers)
        ok = selected == expected and bool(expected)
        if ok:
            correct += 1
        details.append(
            {
                "code": q.code,
                "topic": q.topic,
                "selected": selected,
                "expected": expected,
                "correct": ok,
                "multi": q.multi,
            }
        )
    total = len(questions) or 1
    score = round(100.0 * correct / total, 1)
    passed = meets_percent(correct, total, percent)
    prev = (
        TestAttempt.query.filter_by(
            user_id=user.id, course_id=course_id, lesson_number=lesson_number
        )
        .order_by(TestAttempt.attempt_no.desc())
        .first()
    )
    attempt_no = (prev.attempt_no + 1) if prev else 1
    attempt = TestAttempt(
        user_id=user.id,
        course_id=course_id,
        lesson_number=lesson_number,
        attempt_no=attempt_no,
        answers=answers,
        details=details,
        correct_count=correct,
        total_count=total,
        score=score,
        passed=passed,
    )
    db.session.add(attempt)
    progress = get_or_create_progress(user.id, course_id, lesson_number)
    if progress.test_best_score is None or score > progress.test_best_score:
        progress.test_best_score = score
    if passed and not progress.test_passed_at:
        progress.test_passed_at = utcnow()
    progress.updated_at = utcnow()
    log_activity(
        user.id,
        "test_submit",
        course_id=course_id,
        lesson_number=lesson_number,
        details={"attempt": attempt_no, "score": score, "passed": passed},
    )
    grant_achievements(user)
    return attempt


def active_assignments(
    user_id: int,
    course_id: str,
    lesson_number: int,
    band: str | None = None,
) -> list[PracticeAssignment]:
    q = PracticeAssignment.query.filter_by(
        user_id=user_id,
        course_id=course_id,
        lesson_number=lesson_number,
        is_active=True,
    )
    if band:
        q = q.filter_by(level_band=band)
    return q.order_by(PracticeAssignment.slot).all()


def ensure_assignments(
    user: User, course_id: str, lesson_number: int, band: str
) -> list[PracticeAssignment]:
    existing = active_assignments(user.id, course_id, lesson_number, band)
    lesson = get_course(course_id).get(lesson_number)
    tasks = lesson.practice.get(band) or []
    have = {r.task_code for r in existing}
    added = False
    for task in tasks:
        if task.code in have:
            continue
        db.session.add(
            PracticeAssignment(
                user_id=user.id,
                course_id=course_id,
                lesson_number=lesson_number,
                slot=task.slot,
                task_code=task.code,
                level_band=band,
                title=task.title,
                task_md=task.text_md,
                answer_text=task.answer,
                is_active=True,
            )
        )
        added = True
    if added:
        db.session.flush()
        return active_assignments(user.id, course_id, lesson_number, band)
    return existing


def band_practice_stats(
    user_id: int, course_id: str, lesson_number: int
) -> dict[str, dict[str, int | bool | str]]:
    percent = float(current_app.config.get("PRACTICE_PASS_PERCENT") or 80)
    out: dict[str, dict[str, int | bool | str]] = {}
    for band in LEVEL_BANDS:
        rows = active_assignments(user_id, course_id, lesson_number, band)
        total = len(rows)
        correct = sum(1 for r in rows if r.is_correct)
        out[band] = {
            "correct": correct,
            "total": total,
            "pct": int(round(100 * correct / total)) if total else 0,
            "passed": bool(total and meets_percent(correct, total, percent)),
            "started": total > 0,
        }
    return out


def sync_assignments_after_content_change(course_id: str, lesson_number: int, band: str) -> None:
    lesson = get_course(course_id).get(lesson_number)
    tasks = lesson.practice.get(band) or []
    by_code = {t.code: t for t in tasks}
    rows = PracticeAssignment.query.filter_by(
        course_id=course_id, lesson_number=lesson_number, level_band=band, is_active=True
    ).all()
    by_user: dict[int, list[PracticeAssignment]] = {}
    for row in rows:
        by_user.setdefault(row.user_id, []).append(row)
    for user_id, user_rows in by_user.items():
        user = db.session.get(User, user_id)
        if user is None:
            continue
        progress = get_or_create_progress(user_id, course_id, lesson_number)
        if progress.practice_passed_at:
            continue
        active_codes: set[str] = set()
        for row in user_rows:
            if row.is_correct:
                active_codes.add(row.task_code)
                continue
            task = by_code.get(row.task_code)
            if task is None:
                row.is_active = False
                row.replaced_at = utcnow()
                continue
            row.title = task.title
            row.task_md = task.text_md
            row.answer_text = task.answer
            row.slot = task.slot
            active_codes.add(row.task_code)
        for task in tasks:
            if task.code in active_codes:
                continue
            db.session.add(
                PracticeAssignment(
                    user_id=user_id,
                    course_id=course_id,
                    lesson_number=lesson_number,
                    slot=task.slot,
                    task_code=task.code,
                    level_band=band,
                    title=task.title,
                    task_md=task.text_md,
                    answer_text=task.answer,
                    is_active=True,
                )
            )
        db.session.flush()
        refresh_practice_progress(user, course_id, lesson_number)


def refresh_practice_progress(user: User, course_id: str, lesson_number: int) -> LessonProgress:
    stats = band_practice_stats(user.id, course_id, lesson_number)
    progress = get_or_create_progress(user.id, course_id, lesson_number)
    passed_bands = [b for b, s in stats.items() if s["passed"]]
    show = None
    if passed_bands:
        show = passed_bands[-1]
    else:
        started = [b for b, s in stats.items() if s["started"]]
        if started:
            show = max(started, key=lambda b: int(stats[b]["pct"]))
    if show:
        progress.practice_correct = int(stats[show]["correct"])
        progress.practice_total = int(stats[show]["total"])
        progress.practice_band = show
    else:
        progress.practice_correct = 0
        progress.practice_total = 0
    if passed_bands and not progress.practice_passed_at:
        progress.practice_passed_at = utcnow()
        progress.completed_at = utcnow()
        unlock_next_if_needed(user, course_id, lesson_number)
        log_activity(
            user.id,
            "lesson_complete",
            course_id=course_id,
            lesson_number=lesson_number,
            details={
                "correct": progress.practice_correct,
                "total": progress.practice_total,
                "band": progress.practice_band,
            },
        )
    progress.updated_at = utcnow()
    grant_achievements(user)
    return progress


def lesson_state(user: User, course_id: str, lesson_number: int) -> dict[str, Any]:
    progress = get_or_create_progress(user.id, course_id, lesson_number)
    unlocked = is_unlocked(user, course_id, lesson_number)
    theory = theory_done(progress)
    test = test_done(progress)
    practice = practice_done(progress)
    if not unlocked:
        stage = "locked"
    elif practice:
        stage = "done"
    elif test:
        stage = "practice"
    elif theory:
        stage = "test"
    else:
        stage = "theory"
    return {
        "unlocked": unlocked,
        "stage": stage,
        "progress": progress,
        "theory": theory,
        "test": test,
        "practice": practice,
        "bands": band_practice_stats(user.id, course_id, lesson_number),
    }


_SKIP_VERDICTS = ("pending", "error", "unclear")


def lesson_success_map(user_id: int, course_id: str | None = None) -> dict[tuple[str, int], dict[str, int]]:
    buckets: dict[tuple[str, int], list[int]] = {}

    def _bump(cid: str, lesson_number: int, ok: bool) -> None:
        row = buckets.setdefault((cid, lesson_number), [0, 0])
        if ok:
            row[0] += 1
        else:
            row[1] += 1

    tq = TestAttempt.query.filter_by(user_id=user_id)
    if course_id:
        tq = tq.filter_by(course_id=course_id)
    for t in tq.all():
        _bump(t.course_id, t.lesson_number, bool(t.passed))

    pq = (
        db.session.query(
            PracticeAttempt.is_correct,
            PracticeAssignment.course_id,
            PracticeAssignment.lesson_number,
        )
        .join(PracticeAssignment, PracticeAttempt.assignment_id == PracticeAssignment.id)
        .filter(
            PracticeAttempt.user_id == user_id,
            PracticeAttempt.ai_verdict.notin_(_SKIP_VERDICTS),
        )
    )
    if course_id:
        pq = pq.filter(PracticeAssignment.course_id == course_id)
    for is_correct, cid, lesson_number in pq.all():
        _bump(cid, lesson_number, bool(is_correct))

    out: dict[tuple[str, int], dict[str, int]] = {}
    for key, (ok, fail) in buckets.items():
        total = ok + fail
        if not total:
            continue
        out[key] = {
            "ok": ok,
            "fail": fail,
            "total": total,
            "pct": int(round(100 * ok / total)),
        }
    return out


def course_success_map(user_id: int) -> dict[str, dict[str, int]]:
    lessons = lesson_success_map(user_id)
    buckets: dict[str, list[int]] = {}
    for (cid, _n), data in lessons.items():
        row = buckets.setdefault(cid, [0, 0])
        row[0] += data["ok"]
        row[1] += data["fail"]
    out: dict[str, dict[str, int]] = {}
    for cid, (ok, fail) in buckets.items():
        total = ok + fail
        if not total:
            continue
        out[cid] = {
            "ok": ok,
            "fail": fail,
            "total": total,
            "pct": int(round(100 * ok / total)),
        }
    return out


def course_progress_pct(user: User, course_id: str) -> int:
    bank = get_course(course_id)
    if not bank.count:
        return 0
    total = 0
    for n in bank.numbers:
        st = lesson_state(user, course_id, n)
        p = st["progress"]
        th = 100 if st["theory"] else (p.theory_scroll_pct or 0)
        te = 100 if st["test"] else 0
        pok = p.practice_correct or 0
        pall = p.practice_total or 0
        pr = 100 if st["practice"] else ((100 * pok / pall) if pall else 0)
        total += (th + te + pr) / 3
    return int(round(total / bank.count))


def best_practice_band(user: User, course_id: str) -> str | None:
    order = {b: i for i, b in enumerate(LEVEL_BANDS)}
    best: str | None = None
    rows = LessonProgress.query.filter_by(user_id=user.id, course_id=course_id).all()
    for p in rows:
        if not p.practice_passed_at or not p.practice_band:
            continue
        if best is None or order.get(p.practice_band, -1) > order.get(best, -1):
            best = p.practice_band
    return best


ACHIEVEMENTS = [
    ("first_theory", "Первая теория", "Прочитана теория первого занятия"),
    ("first_test", "Теоретик", "Сдан первый тест на 80% и выше"),
    ("first_practice", "Практик", "Засчитано первое задание практической части"),
    ("perfect_test", "Без ошибок", "Тест сдан на 100%"),
    ("three_lessons", "Разгон", "Завершены 3 занятия"),
    ("half_way", "Половина пути", "Пройдена половина доступных занятий"),
    ("finish", "Курсы пройдены", "Завершены все доступные занятия"),
    ("persistent", "Упорство", "Тест сдан с пятой попытки или позже"),
    ("photo_ten", "Тетрадь в деле", "Отправлено 10 фото решений"),
    ("streak_five", "Серия", "5 занятий подряд завершены в одном курсе"),
]


def grant_achievements(user: User) -> None:
    if not user.is_student:
        return
    have = {a.code for a in UserAchievement.query.filter_by(user_id=user.id).all()}
    progresses = LessonProgress.query.filter_by(user_id=user.id).all()
    done = [p for p in progresses if p.completed_at]
    tests = TestAttempt.query.filter_by(user_id=user.id).all()
    photos = PracticeAttempt.query.filter_by(user_id=user.id).count()
    correct_practice = PracticeAssignment.query.filter_by(user_id=user.id, is_correct=True).count()
    open_ids = accessible_course_ids(user)
    catalog = get_catalog()
    total_open = sum(catalog.get(cid).count for cid in open_ids if cid in catalog.courses)

    def add(code: str) -> None:
        if code in have:
            return
        meta = next((x for x in ACHIEVEMENTS if x[0] == code), None)
        if not meta:
            return
        db.session.add(
            UserAchievement(
                user_id=user.id,
                code=code,
                title=meta[1],
                description=meta[2],
            )
        )
        have.add(code)
        log_activity(user.id, "achievement", details={"code": code, "title": meta[1]})

    if any(p.theory_completed_at for p in progresses):
        add("first_theory")
    if any(p.test_passed_at for p in progresses):
        add("first_test")
    if correct_practice:
        add("first_practice")
    if any(t.score >= 99.9 for t in tests):
        add("perfect_test")
    if len(done) >= 3:
        add("three_lessons")
    if total_open and len(done) >= math.ceil(total_open / 2):
        add("half_way")
    if total_open and len(done) >= total_open:
        add("finish")
    if any(t.passed and t.attempt_no >= 5 for t in tests):
        add("persistent")
    if photos >= 10:
        add("photo_ten")
    by_course: dict[str, list[int]] = {}
    for p in done:
        by_course.setdefault(p.course_id, []).append(p.lesson_number)
    best = 0
    for nums in by_course.values():
        streak = 0
        prev = 0
        for n in sorted(nums):
            if prev and n == prev + 1:
                streak += 1
            else:
                streak = 1
            best = max(best, streak)
            prev = n
    if best >= 5:
        add("streak_five")
