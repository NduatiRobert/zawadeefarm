from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import settings as S
from ..constants import ROLES
from ..extensions import db
from ..models import User, utcnow

bp = Blueprint("auth", __name__)


def safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("pages.dashboard")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("pages.dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user and user.is_active and user.check_password(request.form.get("password") or ""):
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login = utcnow()
            db.session.commit()
            return redirect(safe_next(request.args.get("next")))
        flash("Wrong email or password.", "danger")
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        if not current_user.check_password(request.form.get("current") or ""):
            flash("Current password is wrong.", "danger")
        elif len(request.form.get("new") or "") < 8:
            flash("New password must be at least 8 characters.", "danger")
        elif request.form.get("new") != request.form.get("confirm"):
            flash("New passwords do not match.", "danger")
        else:
            current_user.set_password(request.form["new"])
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("pages.dashboard"))
    return render_template("auth/account.html")


# --------------------------------------------------------------------------- admin
def admin_only():
    if not current_user.can("admin"):
        abort(403)


@bp.route("/admin/users")
@login_required
def users():
    admin_only()
    return render_template("auth/users.html", users=User.query.order_by(User.name).all(), roles=ROLES)


@bp.route("/admin/users/new", methods=["GET", "POST"])
@bp.route("/admin/users/<int:id>", methods=["GET", "POST"])
@login_required
def user_form(id=None):
    admin_only()
    user = db.get_or_404(User, id) if id else User()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        clash = User.query.filter(User.email == email, User.id != (user.id or 0)).first()
        if not request.form.get("name") or not email:
            flash("Name and email are required.", "danger")
        elif clash:
            flash("Another user already has that email.", "danger")
        elif not id and len(pw) < 8:
            flash("Set a password of at least 8 characters.", "danger")
        elif id and pw and len(pw) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif user.id == current_user.id and (request.form.get("role") != "admin" or not request.form.get("active")):
            flash("You cannot remove your own admin access.", "danger")
        else:
            user.name, user.email = request.form["name"].strip(), email
            user.role = request.form.get("role") if request.form.get("role") in ROLES else "manager"
            user.is_active_user = bool(request.form.get("active"))
            if pw:
                user.set_password(pw)
            db.session.add(user)
            db.session.commit()
            flash("User saved.", "success")
            return redirect(url_for("auth.users"))
    return render_template("auth/user_form.html", user=user, roles=ROLES)


@bp.route("/admin/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    admin_only()
    if request.method == "POST":
        S.set_many({k: (request.form.get(k) or "").strip() for k in S.DEFAULTS})
        flash("Settings saved.", "success")
        return redirect(url_for("auth.settings_page"))
    return render_template("auth/settings.html", values={k: S.get(k) for k in S.DEFAULTS}, labels=S.LABELS)
