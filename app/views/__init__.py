from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def student_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_student:
            flash("Этот раздел предназначен для учеников.", "info")
            return redirect(url_for("admin.dashboard"))
        if not current_user.is_active:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper
