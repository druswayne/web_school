from __future__ import annotations

from datetime import datetime, timezone
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import DeclarativeBase
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    course_access = db.relationship("CourseAccess", backref="user", cascade="all, delete-orphan")
    lesson_access = db.relationship("LessonAccess", backref="user", cascade="all, delete-orphan")
    lesson_progress = db.relationship("LessonProgress", backref="user", cascade="all, delete-orphan")
    test_attempts = db.relationship("TestAttempt", backref="user", cascade="all, delete-orphan")
    practice_assignments = db.relationship(
        "PracticeAssignment", backref="user", cascade="all, delete-orphan"
    )
    activities = db.relationship(
        "ActivityLog",
        backref="subject",
        foreign_keys="ActivityLog.user_id",
        cascade="all, delete-orphan",
    )
    achievements = db.relationship("UserAchievement", backref="user", cascade="all, delete-orphan")

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw, method="pbkdf2:sha256")

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @staticmethod
    def normalize_username(value: str) -> str:
        return (value or "").strip().casefold()

    @classmethod
    def find_by_username(cls, value: str) -> User | None:
        key = cls.normalize_username(value)
        if not key:
            return None
        matches = cls.query.filter(func.lower(cls.username) == key).all()
        if matches:
            return matches[0]
        return next((u for u in cls.query.all() if u.username.casefold() == key), None)

    @classmethod
    def username_taken(cls, value: str, exclude_id: int | None = None) -> bool:
        user = cls.find_by_username(value)
        return user is not None and user.id != exclude_id

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_student(self) -> bool:
        return self.role == "student"


class CourseAccess(db.Model):
    __tablename__ = "course_access"
    __table_args__ = (db.UniqueConstraint("user_id", "course_id", name="uq_access_user_course"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.String(40), nullable=False, index=True)
    unlocked = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class LessonAccess(db.Model):
    __tablename__ = "lesson_access"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "course_id", "lesson_number", name="uq_access_user_course_lesson"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.String(40), nullable=False, index=True)
    lesson_number = db.Column(db.Integer, nullable=False, index=True)
    unlocked = db.Column(db.Boolean, nullable=False, default=False)
    source = db.Column(db.String(20), nullable=False, default="progress")
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class LessonProgress(db.Model):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "course_id", "lesson_number", name="uq_progress_user_course_lesson"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.String(40), nullable=False, index=True)
    lesson_number = db.Column(db.Integer, nullable=False, index=True)
    theory_scroll_pct = db.Column(db.Integer, nullable=False, default=0)
    theory_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    theory_read_seconds = db.Column(db.Integer, nullable=False, default=0)
    test_best_score = db.Column(db.Float, nullable=True)
    test_passed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    practice_correct = db.Column(db.Integer, nullable=False, default=0)
    practice_total = db.Column(db.Integer, nullable=False, default=0)
    practice_band = db.Column(db.String(16), nullable=True)
    practice_passed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TestAttempt(db.Model):
    __tablename__ = "test_attempts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.String(40), nullable=False, index=True)
    lesson_number = db.Column(db.Integer, nullable=False, index=True)
    attempt_no = db.Column(db.Integer, nullable=False)
    answers = db.Column(db.JSON, nullable=False)
    details = db.Column(db.JSON, nullable=False)
    correct_count = db.Column(db.Integer, nullable=False)
    total_count = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Float, nullable=False)
    passed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PracticeAssignment(db.Model):
    __tablename__ = "practice_assignments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.String(40), nullable=False, index=True)
    lesson_number = db.Column(db.Integer, nullable=False, index=True)
    slot = db.Column(db.Integer, nullable=False)
    task_code = db.Column(db.String(16), nullable=False)
    level_band = db.Column(db.String(16), nullable=False)
    title = db.Column(db.Text, nullable=False, default="")
    task_md = db.Column(db.Text, nullable=False)
    answer_text = db.Column(db.Text, nullable=False, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    replaced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    attempts = db.relationship(
        "PracticeAttempt",
        backref="assignment",
        cascade="all, delete-orphan",
        order_by="PracticeAttempt.created_at",
    )


class PracticeAttempt(db.Model):
    __tablename__ = "practice_attempts"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey("practice_assignments.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    attempt_no = db.Column(db.Integer, nullable=False)
    photo_filename = db.Column(db.String(260), nullable=False)
    processed_filename = db.Column(db.String(260), nullable=True)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    ai_verdict = db.Column(db.String(32), nullable=False, default="error")
    ai_feedback = db.Column(db.Text, nullable=False, default="")
    ai_raw = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    course_id = db.Column(db.String(40), nullable=True, index=True)
    lesson_number = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(40), nullable=False, index=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class UserAchievement(db.Model):
    __tablename__ = "user_achievements"
    __table_args__ = (db.UniqueConstraint("user_id", "code", name="uq_user_achievement"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")
    earned_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class TheoryCardStat(db.Model):
    """How often a theory card was shown. Global for now; per-user can be added later."""

    __tablename__ = "theory_card_stats"

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.String(120), unique=True, nullable=False, index=True)
    shown_count = db.Column(db.Integer, nullable=False, default=0)
    last_shown_at = db.Column(db.DateTime(timezone=True), nullable=True)


def ensure_schema() -> None:
    inspector = inspect(db.engine)
    if "lesson_progress" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("lesson_progress")}
    statements: list[str] = []
    if "theory_read_seconds" not in cols:
        statements.append(
            "ALTER TABLE lesson_progress ADD COLUMN theory_read_seconds INTEGER DEFAULT 0"
        )
    if "practice_band" not in cols:
        statements.append("ALTER TABLE lesson_progress ADD COLUMN practice_band VARCHAR(16)")
    if statements:
        with db.engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))
