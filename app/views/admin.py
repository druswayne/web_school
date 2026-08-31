from __future__ import annotations

import logging
from pathlib import Path
import shutil

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from ..config import LEVEL_BANDS, LEVEL_LABELS, UPLOADS_DIR
from ..content import get_catalog, get_course, normalize_band, render_markdown
from ..content_edit import (
    questions_from_form,
    save_practice_band,
    save_test,
    save_theory,
    tasks_from_form,
)
from ..models import (
    ActivityLog,
    CourseAccess,
    LessonAccess,
    LessonProgress,
    PracticeAssignment,
    PracticeAttempt,
    TestAttempt,
    TheoryCardStat,
    User,
    db,
    utcnow,
)
from ..theory_cards import load_cards_for_selection, parse_selection, pick_next, picker_payload
from ..progress import (
    accessible_course_ids,
    bootstrap_student,
    is_course_unlocked,
    lesson_state,
    log_activity,
    refresh_practice_progress,
    set_access,
    set_course_access,
    sync_assignments_after_content_change,
    sync_student_courses,
)
from . import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")
log = logging.getLogger(__name__)

MIN_PASSWORD_LEN = 6


def _flash_save_error(label: str, exc: Exception) -> None:
    log.exception("не удалось сохранить %s", label)
    flash(f"Не удалось сохранить {label}: {exc}", "danger")


def _delete_student(user: User) -> Path | None:
    uid = user.id
    ActivityLog.query.filter(ActivityLog.actor_id == uid).update(
        {ActivityLog.actor_id: None}, synchronize_session=False
    )
    PracticeAttempt.query.filter_by(user_id=uid).delete(synchronize_session=False)
    db.session.delete(user)
    folder = UPLOADS_DIR / "practice" / str(uid)
    return folder if folder.is_dir() else None


def _change_admin_password() -> bool:
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("new_password2") or ""
    if not current_user.check_password(current):
        flash("Текущий пароль неверный.", "danger")
        return False
    if len(new) < MIN_PASSWORD_LEN:
        flash(f"Новый пароль — не короче {MIN_PASSWORD_LEN} символов.", "warning")
        return False
    if new != confirm:
        flash("Новый пароль и подтверждение не совпадают.", "warning")
        return False
    if current_user.check_password(new):
        flash("Новый пароль совпадает с текущим.", "warning")
        return False
    current_user.set_password(new)
    log_activity(current_user.id, "password_changed", actor_id=current_user.id)
    db.session.commit()
    flash("Пароль изменён.", "success")
    return True

ACTION_LABELS = {
    "login": "Вход на сайт",
    "lesson_open": "Открыл занятие",
    "theory_open": "Открыл теорию",
    "theory_complete": "Дочитал теорию",
    "test_start": "Начал тест",
    "test_submit": "Сдал тест",
    "practice_open": "Открыл практическую часть",
    "practice_submit": "Отправил решение",
    "practice_queued": "Отправил решение на проверку",
    "practice_admin_credit": "Учитель засчитал задание",
    "practice_admin_uncredit": "Учитель снял зачёт задания",
    "lesson_unlocked": "Занятие открыто",
    "lesson_locked": "Занятие закрыто",
    "course_unlocked": "Курс открыт",
    "course_locked": "Курс закрыт",
    "lesson_complete": "Занятие пройдено",
    "achievement": "Получено достижение",
    "profile_updated": "Профиль изменён",
    "student_created": "Ученик создан",
    "student_deleted": "Ученик удалён",
    "password_changed": "Пароль изменён",
    "content_theory": "Изменена теория занятия",
    "content_test": "Изменён тест занятия",
    "content_practice": "Изменена практика занятия",
}


def _form_courses() -> list[str]:
    catalog = get_catalog()
    chosen = request.form.getlist("courses")
    return [cid for cid in chosen if cid in catalog.courses]


@bp.route("/profile", methods=["GET", "POST"])
@admin_required
def profile():
    if request.method == "POST" and _change_admin_password():
        return redirect(url_for("admin.profile"))
    return render_template("admin/profile.html")


@bp.route("/")
@admin_required
def dashboard():
    catalog = get_catalog()
    students = User.query.filter_by(role="student").order_by(User.full_name).all()
    cards = []
    lesson_total = catalog.lesson_total
    for s in students:
        open_ids = accessible_course_ids(s)
        total = sum(catalog.get(cid).count for cid in open_ids if cid in catalog.courses)
        done = LessonProgress.query.filter(
            LessonProgress.user_id == s.id, LessonProgress.completed_at.isnot(None)
        ).count()
        cards.append(
            {
                "user": s,
                "done": done,
                "total": total,
                "pct": round(100 * done / total) if total else 0,
                "courses": len(open_ids),
                "last": s.last_login_at,
            }
        )
    recent = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(20).all()
    users = {u.id: u for u in User.query.all()}
    return render_template(
        "admin/dashboard.html",
        cards=cards,
        recent=recent,
        users=users,
        action_labels=ACTION_LABELS,
        student_count=len(students),
        lesson_total=lesson_total,
        course_count=catalog.count,
        theory_picker=picker_payload(),
    )


@bp.route("/students")
@admin_required
def students():
    q = (request.args.get("q") or "").strip()
    query = User.query.filter_by(role="student")
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.full_name.ilike(like), User.username.ilike(like)))
    rows = query.order_by(User.full_name).all()
    catalog = get_catalog()
    data = []
    for s in rows:
        open_ids = accessible_course_ids(s)
        total = sum(catalog.get(cid).count for cid in open_ids if cid in catalog.courses)
        done = LessonProgress.query.filter(
            LessonProgress.user_id == s.id, LessonProgress.completed_at.isnot(None)
        ).count()
        data.append({"user": s, "done": done, "total": total, "courses": len(open_ids)})
    return render_template("admin/students.html", rows=data, q=q)


@bp.route("/students/new", methods=["GET", "POST"])
@admin_required
def student_new():
    catalog = get_catalog()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        full_name = (request.form.get("full_name") or "").strip()
        courses = _form_courses()
        if not username or not password or not full_name:
            flash("Заполните логин, пароль и имя.", "warning")
            return render_template(
                "admin/student_form.html", user=None, selected=set(courses)
            )
        if User.username_taken(username):
            flash("Такой логин уже занят.", "danger")
            return render_template(
                "admin/student_form.html", user=None, selected=set(courses)
            )
        user = User(
            username=username,
            full_name=full_name,
            role="student",
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        bootstrap_student(user, courses)
        log_activity(
            user.id,
            "student_created",
            actor_id=current_user.id,
            details={"courses": courses},
        )
        db.session.commit()
        flash("Ученик создан.", "success")
        return redirect(url_for("admin.student_detail", user_id=user.id))
    return render_template("admin/student_form.html", user=None, selected=set())


@bp.route("/students/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def student_edit(user_id: int):
    user = User.query.filter_by(id=user_id, role="student").first_or_404()
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        is_active = request.form.get("is_active") == "1"
        courses = _form_courses()
        if not full_name or not username:
            flash("Имя и логин обязательны.", "warning")
            return render_template(
                "admin/student_form.html", user=user, selected=set(courses)
            )
        if User.username_taken(username, exclude_id=user.id):
            flash("Такой логин уже занят.", "danger")
            return render_template(
                "admin/student_form.html", user=user, selected=set(courses)
            )
        user.full_name = full_name
        user.username = username
        user.is_active = is_active
        if password:
            user.set_password(password)
        sync_student_courses(user, courses, actor_id=current_user.id)
        log_activity(
            user.id,
            "profile_updated",
            actor_id=current_user.id,
            details={"courses": courses},
        )
        db.session.commit()
        flash("Профиль сохранён.", "success")
        return redirect(url_for("admin.student_detail", user_id=user.id))
    selected = set(accessible_course_ids(user))
    return render_template("admin/student_form.html", user=user, selected=selected)


@bp.route("/students/<int:user_id>/delete", methods=["POST"])
@admin_required
def student_delete(user_id: int):
    user = User.query.filter_by(id=user_id, role="student").first_or_404()
    name = user.full_name
    username = user.username
    log_activity(
        current_user.id,
        "student_deleted",
        actor_id=current_user.id,
        details={"username": username, "full_name": name, "id": user.id},
    )
    upload_dir = _delete_student(user)
    db.session.commit()
    if upload_dir is not None:
        shutil.rmtree(upload_dir, ignore_errors=True)
    flash(f"Аккаунт «{name}» удалён.", "success")
    return redirect(url_for("admin.students"))


@bp.route("/students/<int:user_id>")
@admin_required
def student_detail(user_id: int):
    user = User.query.filter_by(id=user_id, role="student").first_or_404()
    catalog = get_catalog()
    open_ids = set(accessible_course_ids(user))
    courses = []
    for bank in catalog.all():
        lessons = []
        for lsn in bank.all():
            st = lesson_state(user, bank.course_id, lsn.number)
            tests = (
                TestAttempt.query.filter_by(
                    user_id=user.id, course_id=bank.course_id, lesson_number=lsn.number
                )
                .order_by(TestAttempt.created_at.desc())
                .all()
            )
            assignments = (
                PracticeAssignment.query.filter_by(
                    user_id=user.id, course_id=bank.course_id, lesson_number=lsn.number
                )
                .order_by(
                    PracticeAssignment.level_band,
                    PracticeAssignment.is_active.desc(),
                    PracticeAssignment.slot,
                )
                .all()
            )
            lessons.append(
                {
                    "lesson": lsn,
                    "state": st,
                    "tests": tests,
                    "assignments": assignments,
                }
            )
        courses.append(
            {
                "course": bank,
                "open": bank.course_id in open_ids,
                "lessons": lessons,
            }
        )
    activities = (
        ActivityLog.query.filter_by(user_id=user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(80)
        .all()
    )
    return render_template(
        "admin/student_detail.html",
        student=user,
        courses=courses,
        activities=activities,
        action_labels=ACTION_LABELS,
    )


@bp.route("/students/<int:user_id>/access", methods=["POST"])
@admin_required
def student_access(user_id: int):
    user = User.query.filter_by(id=user_id, role="student").first_or_404()
    kind = request.form.get("kind") or "lesson"
    course_id = request.form.get("course_id") or ""
    unlocked = request.form.get("unlocked") == "1"
    if kind == "course" and course_id:
        set_course_access(user.id, course_id, unlocked, actor_id=current_user.id)
        db.session.commit()
        flash(
            f"Курс {'открыт' if unlocked else 'закрыт'} для {user.full_name}.",
            "success",
        )
        return redirect(url_for("admin.student_detail", user_id=user.id))
    number = int(request.form.get("lesson_number") or 0)
    if course_id and number:
        set_access(
            user.id, course_id, number, unlocked, source="admin", actor_id=current_user.id
        )
        db.session.commit()
        flash(
            f"Занятие {number} {'открыто' if unlocked else 'закрыто'} для {user.full_name}.",
            "success",
        )
    return redirect(url_for("admin.student_detail", user_id=user.id))


@bp.route("/courses")
@admin_required
def courses():
    catalog = get_catalog()
    students = User.query.filter_by(role="student").all()
    rows = []
    for bank in catalog.all():
        open_n = CourseAccess.query.filter_by(course_id=bank.course_id, unlocked=True).count()
        rows.append({"course": bank, "open_n": open_n, "total": len(students)})
    return render_template("admin/courses.html", rows=rows)


@bp.route("/courses/<course_id>/lessons")
@admin_required
def lessons(course_id: str):
    bank = _admin_course(course_id)
    students = User.query.filter_by(role="student").all()
    rows = []
    for lsn in bank.all():
        open_n = LessonAccess.query.filter_by(
            course_id=course_id, lesson_number=lsn.number, unlocked=True
        ).count()
        if lsn.number == 1:
            open_n = max(open_n, CourseAccess.query.filter_by(course_id=course_id, unlocked=True).count())
        rows.append({"lesson": lsn, "open_n": open_n, "total": len(students)})
    return render_template("admin/lessons.html", course=bank, rows=rows)


@bp.route("/courses/<course_id>/lessons/<int:number>/access", methods=["POST"])
@admin_required
def lessons_access(course_id: str, number: int):
    _admin_course(course_id)
    action = request.form.get("action")
    students = User.query.filter_by(role="student").all()
    unlocked = action == "open"
    for s in students:
        if not is_course_unlocked(s, course_id) and unlocked:
            continue
        set_access(s.id, course_id, number, unlocked, source="admin", actor_id=current_user.id)
    db.session.commit()
    flash(
        f"Занятие {number} {'открыто' if unlocked else 'закрыто'} для учеников с доступом к курсу.",
        "success",
    )
    if request.form.get("next") == "detail":
        return redirect(url_for("admin.lesson_detail", course_id=course_id, number=number))
    return redirect(url_for("admin.lessons", course_id=course_id))


def _admin_course(course_id: str):
    try:
        return get_course(course_id)
    except KeyError:
        abort(404)


def _admin_lesson(course_id: str, number: int):
    try:
        return get_course(course_id).get(number)
    except KeyError:
        abort(404)


def _admin_band(band: str) -> str:
    key = normalize_band(band)
    if key not in LEVEL_BANDS:
        abort(404)
    return key


@bp.route("/courses/<course_id>/lessons/<int:number>")
@admin_required
def lesson_detail(course_id: str, number: int):
    lsn = _admin_lesson(course_id, number)
    return render_template(
        "admin/lesson_detail.html",
        course=_admin_course(course_id),
        lesson=lsn,
        test_count=len(lsn.test),
        practice_counts={b: len(lsn.practice.get(b) or []) for b in LEVEL_BANDS},
        theory_chars=len(lsn.theory_body),
    )


@bp.route("/courses/<course_id>/lessons/<int:number>/theory", methods=["GET", "POST"])
@admin_required
def lesson_theory(course_id: str, number: int):
    lsn = _admin_lesson(course_id, number)
    course = _admin_course(course_id)
    if request.method == "POST":
        body = request.form.get("theory_md") or ""
        try:
            save_theory(course_id, number, body)
        except Exception as exc:
            _flash_save_error("файл занятия", exc)
            return render_template(
                "admin/lesson_theory.html", course=course, lesson=lsn, theory_md=body
            )
        log_activity(
            current_user.id,
            "content_theory",
            course_id=course_id,
            lesson_number=number,
            actor_id=current_user.id,
        )
        db.session.commit()
        flash("Теория сохранена.", "success")
        return redirect(url_for("admin.lesson_detail", course_id=course_id, number=number))
    return render_template(
        "admin/lesson_theory.html", course=course, lesson=lsn, theory_md=lsn.theory_body
    )


@bp.route("/courses/<course_id>/lessons/<int:number>/test", methods=["GET", "POST"])
@admin_required
def lesson_test_edit(course_id: str, number: int):
    lsn = _admin_lesson(course_id, number)
    course = _admin_course(course_id)
    if request.method == "POST":
        questions = questions_from_form(request.form)
        if not questions:
            flash("Добавьте хотя бы один вопрос.", "warning")
            return render_template(
                "admin/lesson_test_edit.html",
                course=course,
                lesson=lsn,
                questions=questions,
            )
        missing = [q.code for q in questions if not q.prompt_md or len(q.options) < 2 or not q.answers]
        if missing:
            flash(
                "У каждого вопроса нужны формулировка, минимум два варианта и хотя бы один верный ответ.",
                "warning",
            )
            return render_template(
                "admin/lesson_test_edit.html",
                course=course,
                lesson=lsn,
                questions=questions,
            )
        try:
            save_test(course_id, number, questions)
        except Exception as exc:
            _flash_save_error("файлы теста", exc)
            return render_template(
                "admin/lesson_test_edit.html",
                course=course,
                lesson=lsn,
                questions=questions,
            )
        log_activity(
            current_user.id,
            "content_test",
            course_id=course_id,
            lesson_number=number,
            actor_id=current_user.id,
            details={"questions": len(questions)},
        )
        db.session.commit()
        flash("Тест сохранён.", "success")
        return redirect(url_for("admin.lesson_detail", course_id=course_id, number=number))
    return render_template(
        "admin/lesson_test_edit.html",
        course=course,
        lesson=lsn,
        questions=lsn.test,
    )


@bp.route("/courses/<course_id>/lessons/<int:number>/practice")
@admin_required
def lesson_practice_pick(course_id: str, number: int):
    lsn = _admin_lesson(course_id, number)
    counts = {b: len(lsn.practice.get(b) or []) for b in LEVEL_BANDS}
    return render_template(
        "admin/lesson_band_pick.html",
        course=_admin_course(course_id),
        lesson=lsn,
        kind="practice",
        kind_title="Практические задания",
        kind_hint="Выберите уровень сложности. Ученик сам выбирает, какой блок решать.",
        counts=counts,
        count_unit="заданий",
        edit_endpoint="admin.lesson_practice_edit",
    )


@bp.route("/courses/<course_id>/lessons/<int:number>/practice/<band>", methods=["GET", "POST"])
@admin_required
def lesson_practice_edit(course_id: str, number: int, band: str):
    lsn = _admin_lesson(course_id, number)
    course = _admin_course(course_id)
    band = _admin_band(band)
    if request.method == "POST":
        class_tasks = tasks_from_form(
            request.form, "class", kind="class", letter="C", slot_base=0
        )
        if not class_tasks:
            flash("Добавьте хотя бы одно задание.", "warning")
            return render_template(
                "admin/lesson_practice_edit.html",
                course=course,
                lesson=lsn,
                band=band,
                class_tasks=class_tasks,
            )
        try:
            save_practice_band(course_id, number, band, class_tasks)
        except Exception as exc:
            _flash_save_error("файлы практики", exc)
            return render_template(
                "admin/lesson_practice_edit.html",
                course=course,
                lesson=lsn,
                band=band,
                class_tasks=class_tasks,
            )
        sync_assignments_after_content_change(course_id, number, band)
        log_activity(
            current_user.id,
            "content_practice",
            course_id=course_id,
            lesson_number=number,
            actor_id=current_user.id,
            details={"band": band, "tasks": len(class_tasks)},
        )
        db.session.commit()
        flash(f"Практика уровня {LEVEL_LABELS[band]} сохранена.", "success")
        return redirect(url_for("admin.lesson_detail", course_id=course_id, number=number))
    class_tasks = lsn.practice.get(band) or []
    return render_template(
        "admin/lesson_practice_edit.html",
        course=course,
        lesson=lsn,
        band=band,
        class_tasks=class_tasks,
    )


@bp.route("/preview", methods=["POST"])
@admin_required
def markdown_preview():
    course_id = ""
    source = ""
    decorate = False
    if request.is_json:
        data = request.get_json(silent=True) or {}
        source = data.get("source") or ""
        course_id = data.get("course_id") or ""
        decorate = bool(data.get("decorate_theory"))
    else:
        source = request.form.get("source") or ""
        course_id = request.form.get("course_id") or ""
        decorate = (request.form.get("decorate_theory") or "").strip() in {
            "1",
            "true",
            "True",
        }
    return jsonify(
        {
            "html": render_markdown(
                source, course_id=course_id, decorate_theory=decorate
            )
        }
    )


@bp.route("/attempts/test/<int:attempt_id>")
@admin_required
def test_attempt(attempt_id: int):
    attempt = TestAttempt.query.get_or_404(attempt_id)
    student = db.session.get(User, attempt.user_id)
    lsn = get_course(attempt.course_id).get(attempt.lesson_number)
    questions = {q.code: q for q in lsn.test}
    rows = []
    for item in attempt.details or []:
        q = questions.get(item.get("code"))
        rows.append(
            {
                "item": item,
                "prompt": render_markdown(q.prompt_md, attempt.course_id) if q else "",
                "options": q.options if q else [],
            }
        )
    return render_template(
        "admin/test_attempt.html",
        attempt=attempt,
        student=student,
        course=get_course(attempt.course_id),
        lesson=lsn,
        rows=rows,
    )


@bp.route("/attempts/practice/<int:assignment_id>")
@admin_required
def practice_attempts(assignment_id: int):
    assignment = PracticeAssignment.query.get_or_404(assignment_id)
    student = db.session.get(User, assignment.user_id)
    lsn = get_course(assignment.course_id).get(assignment.lesson_number)
    attempts = (
        PracticeAttempt.query.filter_by(assignment_id=assignment.id)
        .order_by(PracticeAttempt.created_at.desc())
        .all()
    )
    return render_template(
        "admin/practice_attempts.html",
        assignment=assignment,
        student=student,
        course=get_course(assignment.course_id),
        lesson=lsn,
        attempts=attempts,
        task_html=render_markdown(
            f"**{assignment.title}**\n\n{assignment.task_md}", assignment.course_id
        ),
    )


@bp.route("/attempts/practice/<int:assignment_id>/credit", methods=["POST"])
@admin_required
def practice_credit(assignment_id: int):
    assignment = PracticeAssignment.query.get_or_404(assignment_id)
    student = db.session.get(User, assignment.user_id)
    credit = request.form.get("credit") == "1"
    if credit:
        assignment.is_correct = True
        latest = (
            PracticeAttempt.query.filter_by(assignment_id=assignment.id)
            .filter(PracticeAttempt.ai_verdict != "pending")
            .order_by(PracticeAttempt.created_at.desc())
            .first()
        )
        if latest is not None:
            latest.is_correct = True
            raw = dict(latest.ai_raw) if isinstance(latest.ai_raw, dict) else {}
            raw["admin_override"] = True
            raw["admin_override_by"] = current_user.id
            latest.ai_raw = raw
            note = "Учитель засчитал это решение."
            if note not in (latest.ai_feedback or ""):
                extra = f"\n\n{note}" if (latest.ai_feedback or "").strip() else note
                latest.ai_feedback = (latest.ai_feedback or "") + extra
        log_activity(
            assignment.user_id,
            "practice_admin_credit",
            course_id=assignment.course_id,
            lesson_number=assignment.lesson_number,
            details={"task": assignment.task_code, "band": assignment.level_band},
            actor_id=current_user.id,
        )
        flash(f"Задание {assignment.task_code} засчитано для {student.full_name}.", "success")
    else:
        assignment.is_correct = False
        for att in PracticeAttempt.query.filter_by(assignment_id=assignment.id).all():
            raw = att.ai_raw if isinstance(att.ai_raw, dict) else {}
            if raw.get("admin_override"):
                att.is_correct = att.ai_verdict == "correct"
                raw = dict(raw)
                raw.pop("admin_override", None)
                raw.pop("admin_override_by", None)
                att.ai_raw = raw
                att.ai_feedback = (att.ai_feedback or "").replace(
                    "\n\nУчитель засчитал это решение.", ""
                ).replace("Учитель засчитал это решение.", "").strip()
        log_activity(
            assignment.user_id,
            "practice_admin_uncredit",
            course_id=assignment.course_id,
            lesson_number=assignment.lesson_number,
            details={"task": assignment.task_code, "band": assignment.level_band},
            actor_id=current_user.id,
        )
        flash(f"Зачёт задания {assignment.task_code} снят.", "info")
    if student is not None:
        refresh_practice_progress(student, assignment.course_id, assignment.lesson_number)
    db.session.commit()
    return redirect(url_for("admin.practice_attempts", assignment_id=assignment.id))


def _theory_counts(cards) -> dict[str, tuple[int, object]]:
    ids = [c.id for c in cards]
    if not ids:
        return {}
    rows = TheoryCardStat.query.filter(TheoryCardStat.card_id.in_(ids)).all()
    return {r.card_id: (int(r.shown_count or 0), r.last_shown_at) for r in rows}


def _mark_card_shown(card_id: str) -> None:
    row = TheoryCardStat.query.filter_by(card_id=card_id).first()
    if row is None:
        row = TheoryCardStat(card_id=card_id, shown_count=0)
        db.session.add(row)
    row.shown_count = int(row.shown_count or 0) + 1
    row.last_shown_at = utcnow()


def _theory_progress(total: int, *, mark_id: str | None = None, reset_round: bool = False) -> dict:
    done = [x for x in (session.get("theory_done_ids") or []) if x]
    if mark_id and mark_id not in done:
        done.append(mark_id)
    if reset_round and total and len(done) >= total:
        session["theory_round"] = int(session.get("theory_round") or 1) + 1
        done = []
    session["theory_done_ids"] = done
    n = len(done)
    remaining = max(0, int(total) - n)
    return {
        "done": n,
        "remaining": remaining,
        "total": int(total),
        "round": int(session.get("theory_round") or 1),
    }


def _pick_session_card(cards, exclude_id: str | None = None):
    done = session.get("theory_done_ids") or []
    return pick_next(cards, _theory_counts(cards), exclude_id, skip_ids=done)


@bp.route("/theory-cards/start", methods=["POST"])
@admin_required
def theory_cards_start():
    keys = parse_selection(request.form.getlist("lessons"))
    if not keys:
        flash("Выберите хотя бы одно занятие.", "info")
        return redirect(url_for("admin.dashboard"))
    session["theory_selection"] = keys
    session["theory_done_ids"] = []
    session["theory_round"] = 1
    return redirect(url_for("admin.theory_cards_play"))


@bp.route("/theory-cards")
@admin_required
def theory_cards_play():
    keys = session.get("theory_selection") or []
    cards = load_cards_for_selection(keys)
    if not keys:
        flash("Сначала выберите курсы и занятия.", "info")
        return redirect(url_for("admin.dashboard"))
    if not cards:
        flash("В выбранных занятиях нет карточек теории.", "info")
        return redirect(url_for("admin.dashboard"))
    after = (request.args.get("after") or "").strip()
    total = len(cards)
    if after:
        _theory_progress(total, mark_id=after, reset_round=True)
    card = _pick_session_card(cards, after or None)
    if card is None:
        flash("В выбранных занятиях нет карточек теории.", "info")
        return redirect(url_for("admin.dashboard"))
    _mark_card_shown(card.id)
    db.session.commit()
    progress = _theory_progress(total)
    return render_template(
        "admin/theory_cards.html",
        card=card,
        total=total,
        progress=progress,
        next_url=url_for("admin.theory_cards_next"),
        seen_url=url_for("admin.theory_cards_seen"),
        hide_nav=True,
    )


@bp.route("/theory-cards/seen", methods=["POST"])
@admin_required
def theory_cards_seen():
    data = request.get_json(silent=True) or {}
    card_id = (data.get("current_id") or request.form.get("current_id") or "").strip()
    keys = session.get("theory_selection") or []
    total = len(load_cards_for_selection(keys))
    if not card_id or not total:
        return jsonify({"ok": False, "error": "empty"}), 400
    progress = _theory_progress(total, mark_id=card_id)
    return jsonify({"ok": True, "progress": progress})


@bp.route("/theory-cards/next", methods=["POST"])
@admin_required
def theory_cards_next():
    data = request.get_json(silent=True) or {}
    after = (data.get("current_id") or request.form.get("current_id") or "").strip()
    keys = session.get("theory_selection") or []
    cards = load_cards_for_selection(keys)
    if not cards:
        return jsonify({"ok": False, "error": "empty"}), 400
    total = len(cards)
    _theory_progress(total, mark_id=after, reset_round=True)
    card = _pick_session_card(cards, after or None)
    if card is None:
        return jsonify({"ok": False, "error": "empty"}), 400
    _mark_card_shown(card.id)
    db.session.commit()
    payload = card.to_json()
    payload["total"] = total
    payload["progress"] = _theory_progress(total)
    return jsonify({"ok": True, "card": payload, "progress": payload["progress"]})
