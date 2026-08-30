from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from ..models import User, db, utcnow
from ..progress import log_activity

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("student.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.find_by_username(username)
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=True)
            user.last_login_at = utcnow()
            log_activity(user.id, "login")
            db.session.commit()
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("auth.index"))
        error = "Неверный логин или пароль."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    logout_user()
    flash("Вы вышли из аккаунта.", "info")
    return redirect(url_for("auth.login"))
