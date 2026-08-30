"""Снимает вертикальный Reels 9:16 по школьным курсам 7–9."""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(WEB_ROOT))
os.chdir(WEB_ROOT)

from app import create_app
from app.config import CONTENT_ROOT, COURSE_ORDER
from app.content import get_catalog, parse_opt_list
from app.models import (
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
)
from app.progress import bootstrap_student
from reel_common import (
    card_html,
    click_scene,
    encode_mp4,
    go_scene,
    hold,
    make_solution_photo,
    move_click,
    open_browser,
    overlay,
    show_card,
    slow_scroll,
    slow_scroll_el,
    wait_http,
)

PORT = 5058
BASE = f"http://127.0.0.1:{PORT}"
USER = "reel"
PASSWORD = "reel123"
COURSE_ID = "algebra_7"
LESSON_N = 1
OUT_DIR = WEB_ROOT / "demo_reel"

TITLE_HTML = card_html(
    "Школьная<br>математика",
    "алгебра и геометрия · 7–9 класс",
)
END_HTML = card_html(
    "Пропустил тему<br>в школе?",
    "здесь разберёшься —<br>в своём темпе",
)


def load_test_answers() -> dict[str, list[str]]:
    path = CONTENT_ROOT / COURSE_ID / "lessons" / "01_test_answers.md"
    text = path.read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"\*\*Т(\d+)\.\*\*\s*([^\n]+)", text):
        out[f"T{int(m.group(1))}"] = parse_opt_list(m.group(2))
    return out


def reset_reel_user(app) -> int:
    with app.app_context():
        user = User.find_by_username(USER)
        if user is None:
            user = User(
                username=USER,
                full_name="Иван Петров",
                role="student",
                is_active=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
        else:
            PracticeAttempt.query.filter_by(user_id=user.id).delete()
            PracticeAssignment.query.filter_by(user_id=user.id).delete()
            TestAttempt.query.filter_by(user_id=user.id).delete()
            LessonProgress.query.filter_by(user_id=user.id).delete()
            LessonAccess.query.filter_by(user_id=user.id).delete()
            CourseAccess.query.filter_by(user_id=user.id).delete()
            UserAchievement.query.filter_by(user_id=user.id).delete()
            ActivityLog.query.filter_by(user_id=user.id).delete()
        catalog = get_catalog()
        bootstrap_student(
            user,
            [c.course_id for c in catalog.all()],
            all_lessons=True,
        )
        db.session.commit()
        return len(list(catalog.all())) or len(COURSE_ORDER)


def login_session(page) -> None:
    html = page.request.get(f"{BASE}/login").text()
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    token = m.group(1) if m else ""
    page.request.post(
        f"{BASE}/login",
        form={
            "username": USER,
            "password": PASSWORD,
            "csrf_token": token,
        },
    )


def click_option(page, code: str, letter: str) -> None:
    label = page.locator(f'fieldset[aria-labelledby="qhead-{code}"] label.opt').filter(
        has=page.locator(f'input[value="{letter}"]')
    )
    move_click(page, label.first)


def fill_remaining_answers(page, answers: dict[str, list[str]]) -> None:
    page.evaluate(
        """(answers) => {
          for (const [code, letters] of Object.entries(answers)) {
            for (const letter of letters) {
              const input = document.querySelector(
                `fieldset[aria-labelledby="qhead-${code}"] input[value="${letter}"]`
              );
              if (input) input.checked = true;
            }
          }
        }""",
        answers,
    )


def record_reel(photo: Path, course_n: int) -> Path:
    answers = load_test_answers()
    pw, browser, context, page = open_browser(OUT_DIR)
    page.set_default_timeout(40000)
    try:
        show_card(page, TITLE_HTML)
        hold(page, 3000)

        login_session(page)
        go_scene(page, f"{BASE}/cabinet", ".lesson-grid")
        slow_scroll_el(page, ".lesson-grid", 1600, "start")
        hold(page, 2200, f"{course_n} курсов для 7–9 класса:<br>алгебра и геометрия")
        if page.locator("a.lesson-tile").count() > 3:
            slow_scroll_el(page, "a.lesson-tile:nth-child(4)", 1600, "center")
            hold(page, 1400, "Можно вернуться к теме,<br>которую не успели разобрать")
        slow_scroll_el(page, "a.lesson-tile", 1300, "center")
        hold(page, 400)

        click_scene(
            page,
            page.locator("a.lesson-tile").first,
            ".lesson-grid",
            "Каждый курс состоит<br>из занятий",
        )
        hold(page, 2000)
        slow_scroll_el(page, ".lesson-grid", 1600, "start")
        hold(page, 1400)

        click_scene(
            page,
            page.locator("a.lesson-tile").first,
            ".path-card",
            "Внутри занятия — три шага",
        )
        hold(page, 1800)
        slow_scroll_el(page, ".path", 1500, "start")
        hold(page, 2000, "теория · тест · практика")

        click_scene(
            page,
            page.locator("a.path-card", has_text="Теория"),
            ".theory-article, .paper.theory-article, .theory-progress",
            "Основная теория занятия.<br>Её нужно разобрать",
        )
        hold(page, 1500)
        y1 = page.evaluate("window.scrollY + window.innerHeight * 0.42")
        slow_scroll(page, y1)
        hold(page, 600)
        y2 = page.evaluate("window.scrollY + window.innerHeight * 0.48")
        slow_scroll(page, y2)
        hold(page, 600, "Формулы и объяснения —<br>в своём темпе")
        page.evaluate(
            """async () => {
              const csrf = document.querySelector('meta[name=csrf-token]')?.content || window.csrfToken;
              const url = document.querySelector('.theory-progress')?.dataset.progressUrl;
              if (!url) return;
              await fetch(url, {
                method: 'POST',
                headers: {'Content-Type':'application/json','X-CSRFToken': csrf},
                body: JSON.stringify({pct:100, completed:true, seconds:12})
              });
              const cta = document.getElementById('theoryCta');
              if (cta) cta.hidden = false;
            }"""
        )
        overlay(page, "Теория разобрана —<br>открывается тест")
        slow_scroll_el(page, "#theoryCta", None, "center")
        hold(page, 2200)
        click_scene(
            page,
            page.locator("#theoryCta a.btn-primary"),
            "form.quiz",
        )
        overlay(page, "")
        hold(page, 2200, "Нужно 80%, чтобы<br>открыть практику")
        for letter in answers.get("T1", []):
            click_option(page, "T1", letter)
            hold(page, 300)
        if page.locator(".q-card").count() >= 2:
            slow_scroll_el(page, ".q-card:nth-of-type(2)", 1200, "center")
            hold(page, 280)
            for letter in answers.get("T2", []):
                click_option(page, "T2", letter)
                hold(page, 240)
        fill_remaining_answers(page, answers)
        hold(page, 350)
        slow_scroll_el(page, "form.quiz .sticky-actions", 1400, "end")
        click_scene(
            page,
            page.locator("form.quiz .sticky-actions button[type=submit]"),
            ".result-list, .hero-card h1",
            "Порог 80% пройден —<br>практика открылась",
        )
        hold(page, 2000)

        practice_btn = page.locator("a.btn-primary", has_text="практическ")
        if practice_btn.count() == 0:
            practice_btn = page.locator("a.btn-primary", has_text="практик")
        if practice_btn.count():
            click_scene(
                page,
                practice_btn.first,
                ".band-grid, .modal-card, .paper",
                "Практика разделена<br>на уровни",
            )
        else:
            go_scene(
                page,
                f"{BASE}/courses/{COURSE_ID}/lessons/{LESSON_N}?pick=1",
                ".band-grid, .modal-card",
                "Практика разделена<br>на уровни",
            )
        hold(page, 2000, "Каждый подберёт уровень<br>под себя")
        band = page.locator("a.band-card")
        if band.count() >= 2:
            click_scene(page, band.nth(1), ".paper", "Выбрали свой уровень —<br>можно решать")
        elif band.count():
            click_scene(page, band.first, ".paper", "Выбрали свой уровень —<br>можно решать")
        hold(page, 1600)
        slow_scroll_el(page, ".paper", 1400, "start")
        hold(page, 800)
        slow_scroll_el(page, ".upload-form, .drop, .tips", 1600, "center")
        hold(page, 1600, "Решаете в тетради<br>и фотографируете")
        file_input = page.locator("#photoInput")
        if file_input.count():
            file_input.set_input_files(str(photo))
            hold(page, 1800)
            send = page.locator("#sendBtn")
            if send.count() and send.is_enabled():
                overlay(page, "")
                move_click(page, send)
                page.wait_for_selector("#pendingCard, .wait-card", timeout=25000)
                hold(page, 1400)
                hold(page, 4200, "Решение проверяет ИИ")
                hold(page, 2600, "Разберёт ваш ход<br>и укажет на ошибки")
            else:
                hold(page, 4200, "Решение проверяет ИИ")
        else:
            hold(page, 4200, "Решение проверяет ИИ")

        show_card(page, END_HTML)
        hold(page, 3400)

        video = page.video
        context.close()
        browser.close()
        return Path(video.path())
    finally:
        try:
            pw.stop()
        except Exception:
            pass


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    photo = OUT_DIR / "solution.jpg"
    make_solution_photo(photo)

    app = create_app()
    course_n = reset_reel_user(app)

    def run() -> None:
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)

    threading.Thread(target=run, daemon=True).start()
    wait_http(f"{BASE}/login")

    webm = record_reel(photo, course_n)
    mp4 = OUT_DIR / "instagram_demo.mp4"
    encode_mp4(webm, mp4)
    print(f"READY {mp4} size={mp4.stat().st_size}")


if __name__ == "__main__":
    main()
