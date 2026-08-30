"""Фоновая проверка практики, чтобы ученик мог перейти к другой задаче."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from threading import Thread

from flask import Flask

from .ai_checker import check_solution
from .config import UPLOADS_DIR
from .models import PracticeAssignment, PracticeAttempt, User, db, utcnow
from .progress import log_activity, refresh_practice_progress

PENDING = "pending"
STALE_AFTER = timedelta(minutes=20)


def _unlink(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _attempt_files(attempt: PracticeAttempt) -> list[Path]:
    names = [attempt.photo_filename, attempt.processed_filename]
    return [UPLOADS_DIR / name for name in names if name]


def _delete_attempt(attempt: PracticeAttempt) -> None:
    for path in _attempt_files(attempt):
        _unlink(path)
    db.session.delete(attempt)


def sweep_stale_pending() -> None:
    cutoff = utcnow() - STALE_AFTER
    rows = PracticeAttempt.query.filter(
        PracticeAttempt.ai_verdict == PENDING,
        PracticeAttempt.created_at < cutoff,
    ).all()
    if not rows:
        return
    for row in rows:
        _delete_attempt(row)
    db.session.commit()


def pending_assignment_ids(assignment_ids: list[int]) -> set[int]:
    if not assignment_ids:
        return set()
    rows = PracticeAttempt.query.filter(
        PracticeAttempt.assignment_id.in_(assignment_ids),
        PracticeAttempt.ai_verdict == PENDING,
    ).all()
    return {row.assignment_id for row in rows}


def start_practice_check(app: Flask, attempt_id: int) -> None:
    Thread(target=_run_practice_check, args=(app, attempt_id), daemon=True).start()


def _run_practice_check(app: Flask, attempt_id: int) -> None:
    with app.app_context():
        try:
            _check_and_store(app, attempt_id)
        except Exception:
            app.logger.exception("background practice check crashed")
            attempt = db.session.get(PracticeAttempt, attempt_id)
            if attempt is not None and attempt.ai_verdict == PENDING:
                _delete_attempt(attempt)
                db.session.commit()
        finally:
            db.session.remove()


def _check_and_store(app: Flask, attempt_id: int) -> None:
    attempt = db.session.get(PracticeAttempt, attempt_id)
    if attempt is None or attempt.ai_verdict != PENDING:
        return
    assignment = db.session.get(PracticeAssignment, attempt.assignment_id)
    if assignment is None:
        _delete_attempt(attempt)
        db.session.commit()
        return
    rel = attempt.processed_filename or attempt.photo_filename
    image = UPLOADS_DIR / rel
    if not image.is_file():
        image = UPLOADS_DIR / attempt.photo_filename
    stored = (attempt.ai_raw or {}).get("previous_feedback") if isinstance(attempt.ai_raw, dict) else None
    previous_feedback = stored if isinstance(stored, list) else [
        a.ai_feedback
        for a in PracticeAttempt.query.filter_by(assignment_id=assignment.id)
        .order_by(PracticeAttempt.attempt_no.asc())
        .all()
        if a.id != attempt.id
        and (a.ai_feedback or "").strip()
        and a.ai_verdict not in {"unclear", "error", PENDING}
    ]
    try:
        result = check_solution(
            task_md=f"{assignment.title}\n\n{assignment.task_md}",
            image_path=image if image.is_file() else UPLOADS_DIR / attempt.photo_filename,
            model=app.config["AI_MODEL"],
            attempt_no=attempt.attempt_no,
            previous_feedback=previous_feedback,
        )
    except Exception:
        app.logger.exception("background practice check failed")
        result = {"verdict": "error", "is_correct": False, "feedback": "", "raw": None}

    attempt = db.session.get(PracticeAttempt, attempt_id)
    if attempt is None or attempt.ai_verdict != PENDING:
        return
    assignment = db.session.get(PracticeAssignment, attempt.assignment_id)
    verdict = str(result.get("verdict") or "").lower()
    if verdict == "error":
        _delete_attempt(attempt)
        db.session.commit()
        return
    attempt.is_correct = bool(result.get("is_correct"))
    if verdict == "correct":
        attempt.is_correct = True
    attempt.ai_verdict = verdict or ("correct" if attempt.is_correct else "incorrect")
    attempt.ai_feedback = str(result.get("feedback") or "").strip()
    attempt.ai_raw = result.get("raw")
    if attempt.is_correct and assignment is not None:
        assignment.is_correct = True
    if assignment is not None:
        user = db.session.get(User, attempt.user_id)
        if user is not None:
            refresh_practice_progress(user, assignment.course_id, assignment.lesson_number)
        log_activity(
            attempt.user_id,
            "practice_submit",
            course_id=assignment.course_id,
            lesson_number=assignment.lesson_number,
            details={
                "task": assignment.task_code,
                "attempt": attempt.attempt_no,
                "correct": attempt.is_correct,
                "verdict": attempt.ai_verdict,
                "band": assignment.level_band,
            },
        )
    db.session.commit()
