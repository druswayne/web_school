"""Фоновые ответы тьютора: HTTP сразу возвращается, модель работает в очереди."""

from __future__ import annotations

from datetime import timedelta

from flask import Flask

from .ai_jobs import submit
from .content import get_course
from .models import TheoryChatMessage, db, utcnow
from .theory_tutor import ask_tutor

PENDING = "pending"
READY = "ready"
ERROR = "error"
STALE_AFTER = timedelta(minutes=20)
ERROR_TEXT = "Не удалось получить ответ. Попробуйте ещё раз чуть позже."
PLACEHOLDER = "Думаю…"


def sweep_stale_tutor() -> None:
    cutoff = utcnow() - STALE_AFTER
    rows = TheoryChatMessage.query.filter(
        TheoryChatMessage.role == "assistant",
        TheoryChatMessage.status == PENDING,
        TheoryChatMessage.created_at < cutoff,
    ).all()
    if not rows:
        return
    for row in rows:
        row.status = ERROR
        row.content = ERROR_TEXT
    db.session.commit()


def pending_tutor_message(user_id: int, course_id: str, lesson_number: int) -> TheoryChatMessage | None:
    return (
        TheoryChatMessage.query.filter_by(
            user_id=user_id,
            course_id=course_id,
            lesson_number=lesson_number,
            role="assistant",
            status=PENDING,
        )
        .order_by(TheoryChatMessage.id.desc())
        .first()
    )


def start_tutor_reply(app: Flask, message_id: int) -> None:
    submit(_run_tutor_reply, app, message_id)


def resume_pending_tutor(app: Flask) -> None:
    sweep_stale_tutor()
    rows = (
        TheoryChatMessage.query.filter_by(role="assistant", status=PENDING)
        .order_by(TheoryChatMessage.id.asc())
        .all()
    )
    for row in rows:
        start_tutor_reply(app, row.id)


def _run_tutor_reply(app: Flask, message_id: int) -> None:
    with app.app_context():
        try:
            _answer_and_store(app, message_id)
        except Exception:
            app.logger.exception("background tutor reply crashed")
            row = db.session.get(TheoryChatMessage, message_id)
            if row is not None and row.status == PENDING:
                row.status = ERROR
                row.content = ERROR_TEXT
                db.session.commit()
        finally:
            db.session.remove()


def _answer_and_store(app: Flask, message_id: int) -> None:
    row = db.session.get(TheoryChatMessage, message_id)
    if row is None or row.status != PENDING or row.role != "assistant":
        return
    question_row = (
        TheoryChatMessage.query.filter(
            TheoryChatMessage.user_id == row.user_id,
            TheoryChatMessage.course_id == row.course_id,
            TheoryChatMessage.lesson_number == row.lesson_number,
            TheoryChatMessage.role == "user",
            TheoryChatMessage.id < row.id,
        )
        .order_by(TheoryChatMessage.id.desc())
        .first()
    )
    if question_row is None or not (question_row.content or "").strip():
        row.status = ERROR
        row.content = "Напишите вопрос по материалу занятия."
        db.session.commit()
        return
    skip_ids = {row.id, question_row.id}
    history = [
        {"role": item.role, "content": item.content}
        for item in TheoryChatMessage.query.filter_by(
            user_id=row.user_id,
            course_id=row.course_id,
            lesson_number=row.lesson_number,
        )
        .order_by(TheoryChatMessage.created_at.asc(), TheoryChatMessage.id.asc())
        .all()
        if item.id not in skip_ids and (item.status or READY) not in {PENDING, ERROR}
    ]
    try:
        lesson = get_course(row.course_id).get(row.lesson_number)
        course_title = get_course(row.course_id).title
        answer = ask_tutor(
            title=lesson.title,
            number=lesson.number,
            theory_md=lesson.theory_body,
            history=history,
            question=question_row.content,
            model=app.config["AI_MODEL"],
            course_title=course_title,
        )
    except Exception:
        app.logger.exception("background tutor reply failed")
        answer = ERROR_TEXT

    row = db.session.get(TheoryChatMessage, message_id)
    if row is None or row.status != PENDING:
        return
    text = (answer or "").strip() or ERROR_TEXT
    row.content = text
    row.status = READY
    db.session.commit()
