from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

WEB_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = WEB_ROOT.parent
load_dotenv(WEB_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")
INSTANCE_DIR = WEB_ROOT / "instance"
UPLOADS_DIR = WEB_ROOT / "uploads"
CONTENT_ROOT = Path(
    os.getenv("SCHOOL_COURSES_DIR")
    or (PROJECT_ROOT / "school_courses_out")
).resolve()

LEVEL_BANDS = ("1-2", "3-4", "5-6", "7-8", "9-10")
LEVEL_LABELS = {
    "1-2": "1–2 балла",
    "3-4": "3–4 балла",
    "5-6": "5–6 баллов",
    "7-8": "7–8 баллов",
    "9-10": "9–10 баллов",
}

COURSE_ORDER = (
    "algebra_7",
    "algebra_8",
    "algebra_9",
    "geometry_7",
    "geometry_8",
    "geometry_9",
)
COURSE_TITLES = {
    "algebra_7": "Алгебра 7 класс",
    "algebra_8": "Алгебра 8 класс",
    "algebra_9": "Алгебра 9 класс",
    "geometry_7": "Геометрия 7 класс",
    "geometry_8": "Геометрия 8 класс",
    "geometry_9": "Геометрия 9 класс",
}


def _secret_key() -> str:
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    path = INSTANCE_DIR / "secret.key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    return key


def _database_uri() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        if raw.startswith("postgres://"):
            raw = "postgresql+psycopg2://" + raw[len("postgres://") :]
        elif raw.startswith("postgresql://") and "+psycopg2" not in raw:
            raw = "postgresql+psycopg2://" + raw[len("postgresql://") :]
        if raw.startswith("sqlite:///") and not raw.startswith("sqlite:////"):
            rel = raw[len("sqlite:///") :]
            path = Path(rel)
            if not path.is_absolute():
                path = (WEB_ROOT / path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return "sqlite:///" + path.as_posix()
        return raw
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + (INSTANCE_DIR / "school.db").resolve().as_posix()


class Config:
    SECRET_KEY = _secret_key()
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    if SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = {"check_same_thread": False}

    WTF_CSRF_TIME_LIMIT = None
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024
    JSON_AS_ASCII = False

    CONTENT_ROOT = CONTENT_ROOT
    UPLOADS_DIR = UPLOADS_DIR
    PROJECT_ROOT = PROJECT_ROOT

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme").strip() or "changeme"
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Администратор").strip() or "Администратор"

    DEMO_SEED = os.getenv("DEMO_SEED", "1").strip() not in {"0", "false", "False"}
    DEMO_USERNAME = os.getenv("DEMO_USERNAME", "ivan").strip() or "ivan"
    DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "ivan123").strip() or "ivan123"
    DEMO_NAME = os.getenv("DEMO_NAME", "Иван Петров").strip() or "Иван Петров"

    AI_MODEL = (
        os.getenv("AI_MODEL")
        or os.getenv("MODEL")
        or "openai/gpt-5.6-luna-pro"
    )
    AI_REASONING_EFFORT = (os.getenv("AI_REASONING_EFFORT") or "high").strip() or "high"
    TEST_PASS_PERCENT = float(os.getenv("TEST_PASS_PERCENT", "80"))
    PRACTICE_PASS_PERCENT = float(os.getenv("PRACTICE_PASS_PERCENT", "80"))
