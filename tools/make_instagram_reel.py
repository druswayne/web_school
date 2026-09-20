"""Снимает вертикальный Reels 9:16 по школьным курсам 5–9."""
from __future__ import annotations

import html
import http.cookiejar
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
    TheoryChatMessage,
    User,
    UserAchievement,
    db,
)
from app.progress import bootstrap_student, refresh_practice_progress
from reel_common import (
    card_html,
    encode_mp4,
    go_scene,
    hold,
    move_click,
    open_browser,
    overlay,
    show_card,
    slow_scroll,
    slow_scroll_el,
    slow_scroll_to_text,
    type_slow,
    wait_http,
)

PORT = 5058
BASE = f"http://127.0.0.1:{PORT}"
USER = "reel"
PASSWORD = "reel123"
COURSE_ID = "algebra_7"
COURSE_TITLE = "Алгебра 7"
LESSON_N = 1
OUT_DIR = WEB_ROOT / "demo_reel"

TITLE_HTML = card_html(
    "Школьная<br>математика",
    "5–9 класс · теория, тест, практика",
)
END_HTML = card_html(
    "Пропустил тему<br>в школе?",
    "здесь разберёшься —<br>в своём темпе",
)

CHAT_ANSWER_ASK = (
    "<p>Основание — число, которое умножают само на себя. "
    "Показатель говорит, сколько раз его берут множителем.</p>"
    "<p>Например, в 7⁴ основание 7, показатель 4: это 7·7·7·7.</p>"
)
CHAT_ANSWER_QUOTE = (
    "<p>Фрагмент говорит простыми словами: степень — короткая запись "
    "произведения одинаковых чисел.</p>"
    "<p>Вместо 4·4·4 пишут 4³. Так сразу видно, сколько множителей.</p>"
)
PRACTICE_FEEDBACK = (
    "Верно. Четыре множителя 7 — это степень 7⁴: основание 7, показатель 4."
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
            TheoryChatMessage.query.filter_by(user_id=user.id).delete()
        catalog = get_catalog()
        bootstrap_student(
            user,
            [c.course_id for c in catalog.all()],
            all_lessons=False,
        )
        db.session.commit()
        return len(list(catalog.all())) or len(COURSE_ORDER)


def login_cookies() -> list[dict]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    html_page = opener.open(f"{BASE}/login", timeout=15).read().decode("utf-8", "replace")
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html_page)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html_page)
    token = m.group(1) if m else ""
    data = urllib.parse.urlencode(
        {"username": USER, "password": PASSWORD, "csrf_token": token}
    ).encode()
    req = urllib.request.Request(f"{BASE}/login", data=data, method="POST")
    opener.open(req, timeout=15)
    return [{"name": c.name, "value": c.value, "url": BASE + "/"} for c in jar]


def make_notebook_photo(path: Path) -> None:
    img = Image.new("RGB", (1240, 1650), "#f6f0e2")
    draw = ImageDraw.Draw(img)
    for y in range(90, 1600, 52):
        draw.line((48, y, 1190, y), fill="#d7cdba", width=2)
    font_path = Path(r"C:\Windows\Fonts\segoepr.ttf")
    if not font_path.exists():
        font_path = Path(r"C:\Windows\Fonts\comic.ttf")
    if not font_path.exists():
        font_path = Path(r"C:\Windows\Fonts\calibri.ttf")
    font = ImageFont.truetype(str(font_path), 44)
    small = ImageFont.truetype(str(font_path), 36)
    draw.text((80, 110), "С1", font=small, fill="#0d6e6a")
    for y, text in (
        (190, "7 · 7 · 7 · 7 = 7^4"),
        (280, "основание 7"),
        (360, "показатель 4"),
        (460, "Ответ: 7^4"),
    ):
        draw.text((80, y), text, font=font, fill="#1b2a32")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=92)


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


def click_wait(page, locator, wait_sel: str | None = None, force: bool = False) -> None:
    move_click(page, locator, force=force)
    if wait_sel:
        page.wait_for_selector(wait_sel)
    page.wait_for_timeout(280)


def install_chat_mock(context) -> None:
    state = {"n": 1, "msgs": [], "ready_at": 0.0, "answer": ""}

    def answer_for(question: str) -> str:
        q = (question or "").lower()
        if "фрагмент" in q or "короткая запись" in q:
            return CHAT_ANSWER_QUOTE
        return CHAT_ANSWER_ASK

    def handle(route) -> None:
        req = route.request
        if req.method == "GET":
            msgs = list(state["msgs"])
            if msgs and msgs[-1]["role"] == "assistant" and msgs[-1]["pending"]:
                if time.time() >= state["ready_at"]:
                    msgs[-1]["pending"] = False
                    msgs[-1]["html"] = state["answer"]
                    state["msgs"] = msgs
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps({"ok": True, "messages": state["msgs"]}, ensure_ascii=False),
            )
            return
        if req.method == "POST":
            data = req.post_data_json or {}
            question = str(data.get("message") or "")
            uid, aid = state["n"], state["n"] + 1
            state["n"] += 2
            escaped = html.escape(question).replace("\n", "<br>\n")
            user = {"id": uid, "role": "user", "html": f"<p>{escaped}</p>", "pending": False}
            bot = {
                "id": aid,
                "role": "assistant",
                "html": "<p>Думаю…</p>",
                "pending": True,
            }
            state["msgs"].extend([user, bot])
            state["ready_at"] = time.time() + 1.15
            state["answer"] = answer_for(question)
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(
                    {"ok": True, "pending": True, "user": user, "assistant": bot},
                    ensure_ascii=False,
                ),
            )
            return
        route.fallback()

    context.route("**/lessons/*/theory/chat", handle)


def wait_tutor_answer(page, timeout_ms: int = 12000) -> None:
    page.wait_for_function(
        """() => {
          const rows = [...document.querySelectorAll('.tutor-msg-assistant')];
          const last = rows[rows.length - 1];
          if (!last || last.classList.contains('is-typing')) return false;
          const t = (last.innerText || '').trim();
          return t.length > 12 && !t.startsWith('Думаю');
        }""",
        timeout=timeout_ms,
    )


def close_tutor(page) -> None:
    btn = page.locator(".tutor-sheet [data-tutor-close]").last
    if btn.count():
        move_click(page, btn)
        page.wait_for_timeout(350)


def select_theory_fragment(page, needle: str) -> None:
    loc = page.locator(".theory-source p").filter(has_text=needle).first
    loc.wait_for(state="visible")
    box = loc.bounding_box()
    if not box:
        raise RuntimeError("не найден фрагмент теории для выделения")
    y = box["y"] + min(18, box["height"] / 2)
    page.mouse.move(box["x"] + 10, y, steps=18)
    page.wait_for_timeout(160)
    page.mouse.down()
    page.mouse.move(box["x"] + min(box["width"] - 10, 300), y, steps=30)
    page.mouse.up()
    page.wait_for_selector("#tutorAskSel:not([hidden])", timeout=5000)


def finish_practice_feedback(app) -> None:
    with app.app_context():
        attempt = (
            PracticeAttempt.query.filter_by(ai_verdict="pending")
            .order_by(PracticeAttempt.id.desc())
            .first()
        )
        if attempt is None:
            return
        assignment = db.session.get(PracticeAssignment, attempt.assignment_id)
        attempt.is_correct = True
        attempt.ai_verdict = "correct"
        attempt.ai_feedback = PRACTICE_FEEDBACK
        if assignment is not None:
            assignment.is_correct = True
            user = db.session.get(User, attempt.user_id)
            if user is not None:
                refresh_practice_progress(
                    user, assignment.course_id, assignment.lesson_number
                )
        db.session.commit()


def mark_theory_done(page) -> None:
    page.evaluate(
        """async () => {
          const csrf = document.querySelector('meta[name=csrf-token]')?.content || window.csrfToken;
          const url = document.querySelector('.theory-progress')?.dataset.progressUrl;
          if (url) {
            await fetch(url, {
              method: 'POST',
              headers: {'Content-Type':'application/json','X-CSRFToken': csrf},
              body: JSON.stringify({pct:100, completed:true, seconds:20})
            });
          }
          const cta = document.getElementById('theoryCta');
          if (cta) cta.hidden = false;
        }"""
    )


def record_reel(photo: Path, cookies: list[dict], app) -> Path:
    answers = load_test_answers()
    pw, browser, context, page = open_browser(OUT_DIR)
    page.set_default_timeout(40000)
    install_chat_mock(context)
    try:
        if cookies:
            context.add_cookies(cookies)
        show_card(page, TITLE_HTML)
        hold(page, 2000)

        go_scene(page, f"{BASE}/cabinet", ".lesson-grid")
        slow_scroll_el(page, ".lesson-grid", None, "start")
        hold(page, 2800, "Личный кабинет —<br>ваши курсы")
        if page.locator("a.lesson-tile").count() > 3:
            y0 = page.evaluate("window.scrollY + window.innerHeight * 0.28")
            slow_scroll(page, y0)
            hold(page, 900)
        course_tile = page.locator("a.lesson-tile", has_text=COURSE_TITLE)
        if course_tile.count() == 0:
            course_tile = page.locator("a.lesson-tile").first
        slow_scroll_el(page, "a.lesson-tile", None, "center")
        hold(page, 400)
        overlay(page, "")
        click_wait(page, course_tile.first, ".lesson-grid")

        overlay(page, "")
        slow_scroll_el(page, ".lesson-grid", None, "start")
        hold(page, 2200, "Курс состоит<br>из занятий")
        hold(page, 500)
        overlay(page, "")
        click_wait(page, page.locator("a.lesson-tile").first, ".path-card")

        overlay(page, "")
        slow_scroll_el(page, ".path", None, "start")
        hold(page, 3200, "Занятие: теория,<br>тест и практика")
        hold(page, 700)
        overlay(page, "")
        click_wait(
            page,
            page.locator("a.path-card", has_text="Теория"),
            ".theory-article",
        )

        overlay(page, "")
        page.wait_for_timeout(500)
        slow_scroll_el(page, ".theory-article", None, "start")
        hold(page, 2400, "Теория: читаем<br>в своём темпе")
        y1 = page.evaluate("window.scrollY + window.innerHeight * 0.42")
        slow_scroll(page, y1)
        hold(page, 1100)
        y2 = page.evaluate("window.scrollY + window.innerHeight * 0.42")
        slow_scroll(page, y2)
        hold(page, 900)
        overlay(page, "")
        if not slow_scroll_to_text(page, ".theory-article", "Разбор ключевых"):
            y3 = page.evaluate("window.scrollY + window.innerHeight * 0.5")
            slow_scroll(page, y3)
        hold(page, 2200, "Примеры задач")
        page.wait_for_selector(".theory-solution", timeout=8000)
        slow_scroll_el(page, ".theory-solution", None, "center")
        hold(page, 700)
        overlay(page, "")
        click_wait(page, page.locator(".theory-solution summary").first)
        hold(page, 2800, "Решение открывается<br>по нажатию")
        hold(page, 600)

        overlay(page, "")
        slow_scroll_el(page, "#tutorFab", None, "end")
        hold(page, 1800, "Непонятно?<br>спросите помощника")
        overlay(page, "")
        click_wait(page, page.locator("#tutorFab"), "#tutorLayer:not([hidden])", force=True)
        hold(page, 700)
        type_slow(page.locator("#tutorInput"), "Что такое основание и показатель степени?", 70)
        hold(page, 450)
        click_wait(page, page.locator("#tutorSend"))
        wait_tutor_answer(page)
        hold(page, 3800)
        close_tutor(page)
        hold(page, 400)

        if not slow_scroll_to_text(page, ".theory-source", "короткая запись произведения"):
            slow_scroll_el(page, ".theory-source", None, "start")
        hold(page, 1600, "Или выделите фрагмент")
        overlay(page, "")
        select_theory_fragment(page, "короткая запись произведения")
        hold(page, 1400)
        click_wait(page, page.locator("#tutorAskSel"), "#tutorLayer:not([hidden])")
        wait_tutor_answer(page)
        hold(page, 3800)
        close_tutor(page)
        hold(page, 350)

        overlay(page, "Дальше — тест по теории")
        mark_theory_done(page)
        slow_scroll_el(page, "#theoryCta", None, "center")
        hold(page, 1500)
        overlay(page, "")
        click_wait(page, page.locator("#theoryCta a.btn-primary"), "form.quiz")

        hold(page, 2600, "Нужно 80%, чтобы<br>открыть практику")
        overlay(page, "")
        for letter in answers.get("T1", []):
            click_option(page, "T1", letter)
            hold(page, 240)
        for letter in answers.get("T2", []):
            click_option(page, "T2", letter)
            hold(page, 240)
        fill_remaining_answers(page, answers)
        hold(page, 280)
        slow_scroll_el(page, "form.quiz .sticky-actions", None, "end")
        click_wait(
            page,
            page.locator("form.quiz .sticky-actions button[type=submit]"),
            ".result-list, .hero-card h1",
        )
        hold(page, 2600, "Больше 80% —<br>практика открыта")
        overlay(page, "")

        practice_btn = page.locator("a.btn-primary", has_text="практическ")
        if practice_btn.count() == 0:
            practice_btn = page.locator("a.btn-primary", has_text="практик")
        if practice_btn.count():
            click_wait(page, practice_btn.first, ".band-grid, .modal-card, .paper")
        else:
            go_scene(
                page,
                f"{BASE}/courses/{COURSE_ID}/lessons/{LESSON_N}?pick=1",
                ".band-grid, .modal-card",
            )

        hold(page, 2800, "Сложность практики<br>выбираете сами")
        overlay(page, "")
        band = page.locator("a.band-card")
        if band.count() >= 2:
            click_wait(page, band.nth(1), ".paper")
        elif band.count():
            click_wait(page, band.first, ".paper")

        slow_scroll_el(page, ".paper", None, "start")
        hold(page, 1600, "Задание решают<br>в тетради")
        overlay(page, "")
        slow_scroll_el(page, ".tips", None, "center")
        hold(page, 2400, "Потом фотографируют<br>решение")
        overlay(page, "")
        slow_scroll_el(page, ".upload-form, .drop", None, "center")
        hold(page, 900)
        file_input = page.locator("#photoInput")
        if file_input.count():
            overlay(page, "")
            file_input.set_input_files(str(photo))
            page.wait_for_selector("#photoPreviewWrap:not([hidden]) #photoPreview", timeout=8000)
            slow_scroll_el(page, "#photoPreviewWrap, .upload-form", None, "center")
            hold(page, 2400)
            hold(page, 1600, "Фото прикрепляют<br>к заданию")
            send = page.locator("#sendBtn")
            if send.count() and send.is_enabled():
                overlay(page, "")
                move_click(page, send)
                page.wait_for_selector("#pendingCard, .wait-card", timeout=25000)
                hold(page, 2200)
                hold(page, 2800, "ИИ проверяет решение")
                overlay(page, "")
                finish_practice_feedback(app)
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector(".ok-card, .attempt-feed .ai-feedback", timeout=15000)
                slow_scroll_el(page, ".ok-card, .attempt-feed", None, "start")
                hold(page, 1800)
                if page.locator(".attempt-feed").count():
                    slow_scroll_el(page, ".attempt-feed", None, "center")
                hold(page, 2600, "ИИ даёт обратную связь")
                overlay(page, "")
                hold(page, 4200)
            else:
                hold(page, 2800, "ИИ проверяет решение")
        else:
            hold(page, 2800, "ИИ проверяет решение")

        show_card(page, END_HTML)
        hold(page, 3200)

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
    make_notebook_photo(photo)

    app = create_app()
    reset_reel_user(app)

    def run() -> None:
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)

    threading.Thread(target=run, daemon=True).start()
    wait_http(f"{BASE}/login")
    cookies = login_cookies()

    webm = record_reel(photo, cookies, app)
    mp4 = OUT_DIR / "instagram_demo.mp4"
    encode_mp4(webm, mp4)
    print(f"READY {mp4} size={mp4.stat().st_size}")


if __name__ == "__main__":
    main()
