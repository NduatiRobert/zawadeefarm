import os
import secrets
from datetime import date, datetime

import click
from flask import Flask, abort, render_template, request, session, url_for
from flask_login import current_user

from .extensions import db, login_manager


def build_nav():
    """Sidebar: (label, icon, endpoint-or-children, section)."""
    return [
        ("Dashboard", "speedometer2", "pages.dashboard", "dashboard"),
        ("Daily tasks", "list-task", "pages.daily", "tasks"),
        ("Livestock", "heart-pulse", [
            ("Dashboard", "clipboard-data", "pages.livestock_dashboard"),
            ("Groups", "collection", "crud.groups_list"),
            ("Animals", "tag", "crud.animals_list"),
            ("Activities", "heart-pulse", "crud.activities_list"),
            ("Breeding", "gender-ambiguous", "crud.breeding_list"),
            ("Production", "droplet", "crud.production_list"),
            ("Weights", "speedometer", "crud.weights_list"),
            ("Sales", "cash-stack", "pages.livestock_sales"),
        ], "livestock"),
        ("Store", "box-seam", [
            ("Suppliers", "shop", "crud.suppliers_list"),
            ("Store", "basket", "crud.items_list"),
            ("Input Purchases", "receipt", "crud.purchases_list"),
            ("Stock Requests", "clipboard-check", "crud.requests_list"),
            ("Input Usage", "box-arrow-up", "crud.usage_list"),
        ], "store"),
        ("Feed Mill", "gear-wide-connected", [
            ("Formulas", "journal-richtext", "crud.formulas_list"),
            ("Production batches", "gear", "crud.batches_list"),
        ], "feed"),
        ("Staff & Payroll", "people", [
            ("Employees", "person-badge", "crud.employees_list"),
            ("Attendance", "calendar-check", "crud.attendance_list"),
            ("Casual labour", "person-workspace", "crud.casuals_list"),
            ("Payroll", "wallet2", "payroll.runs"),
        ], "staff"),
        ("Sales & Accounts", "wallet", [
            ("Buyers", "person-check", "crud.buyers_list"),
            ("Buyer Invoices", "file-earmark-text", "crud.invoices_list"),
            ("Payments", "cash-coin", "crud.payments_list"),
            ("Expenses", "arrow-down-circle", "crud.expenses_list"),
        ], "sales"),
        ("Reports", "bar-chart-line", [
            ("Profit & Loss", "graph-up-arrow", "reports.profit_loss"),
            ("Enterprises", "trophy", "reports.enterprises"),
            ("Receivables", "hourglass-split", "reports.receivables"),
            ("Payables", "journal-minus", "reports.payables"),
            ("Stock & usage", "boxes", "reports.stock"),
            ("Payroll returns", "bank", "reports.payroll_summary"),
        ], "reports"),
    ]


def create_app(test_config=None):
    app = Flask(__name__)
    db_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "zawadee.db"))
    if db_url.startswith("postgres://"):  # Heroku/Render style URLs
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    if os.environ.get("DATABASE_URL") and not os.environ.get("SECRET_KEY"):
        raise RuntimeError("Set SECRET_KEY in the environment before running in production.")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or "dev-only-change-me",
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        REMEMBER_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from . import models  # noqa: F401
    from . import resources  # noqa: F401  (registers every CRUD resource)
    from .crud import bp as crud_bp, register_all
    from .views.auth import bp as auth_bp
    from .views.pages import bp as pages_bp
    from .views.payroll_views import bp as payroll_bp
    from .views.reports import bp as reports_bp

    register_all()
    for bp in (auth_bp, pages_bp, crud_bp, payroll_bp, reports_bp):
        app.register_blueprint(bp)

    @login_manager.user_loader
    def load_user(uid):
        return db.session.get(models.User, int(uid))

    # ---------------------------------------------------------------- CSRF
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
                abort(400, "Your session expired. Go back, refresh the page and try again.")

    # ---------------------------------------------------------------- template helpers
    from . import settings as S

    def money(v, cur=True):
        try:
            s = f"{float(v or 0):,.2f}"
        except (TypeError, ValueError):
            return v
        return f"{S.get('currency')} {s}" if cur else s

    def num(v, places=2):
        if v is None or v == "":
            return "–"
        s = f"{float(v):,.{places}f}"
        return s.rstrip("0").rstrip(".") if "." in s else s

    def dmy(v):
        return v.strftime("%d %b %Y") if isinstance(v, (date, datetime)) else (v or "")

    STATUS_TONES = {
        "Active": "success", "Paid": "success", "Issued": "success", "Done": "success", "Present": "success", "OK": "success",
        "Delivered": "success", "Weaned": "success", "Approved": "primary", "In progress": "primary", "Pregnant": "primary",
        "Pending": "warning", "Part paid": "warning", "Open": "warning", "Served": "warning", "Draft": "secondary",
        "Half day": "warning", "Leave": "info", "On leave": "info", "Sick": "info", "Unpaid": "secondary",
        "Overdue": "danger", "Rejected": "danger", "Low stock": "danger", "Dead": "danger", "Absent": "danger",
        "Failed": "danger", "Terminated": "dark", "Sold": "info", "Sold out": "info", "Closed": "secondary",
        "Culled": "dark", "High": "danger", "Normal": "secondary", "Low": "light",
    }

    def badge(v):
        return STATUS_TONES.get(str(v), "secondary")

    @app.context_processor
    def inject():
        nav = []
        if current_user.is_authenticated:
            for label, icon, target, section in build_nav():
                if current_user.can(section) or (section == "staff" and current_user.can("payroll")):
                    nav.append((label, icon, target, section))
        return dict(
            csrf_token=csrf_token, money=money, num=num, dmy=dmy, badge=badge, nav=nav, S=S,
            farm_name=S.get("farm_name"), today=date.today(), now=datetime.now(),
        )

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("pages/error.html", code=403, message="Your role does not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("pages/error.html", code=404, message="That page or record does not exist."), 404

    @app.errorhandler(400)
    def bad(e):
        return render_template("pages/error.html", code=400, message=e.description), 400

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    # ---------------------------------------------------------------- CLI
    @app.cli.command("init-db")
    def init_db():
        """Create all tables."""
        db.create_all()
        click.echo("Database ready.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option()
    def create_admin(email, name, password):
        """Create (or reset) an administrator account."""
        db.create_all()
        u = models.User.query.filter_by(email=email.lower()).first() or models.User(email=email.lower())
        u.name, u.role, u.is_active_user = name, "admin", True
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Admin {email} ready.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Load a realistic demo farm (pigs, layers, broilers, feed mill, staff)."""
        from .seed import seed

        db.create_all()
        seed()
        click.echo("Demo data loaded. Sign in as admin@zawadeefarm.co.ke / zawadee2026")

    with app.app_context():
        db.create_all()
        if os.environ.get("ADMIN_EMAIL") and os.environ.get("ADMIN_PASSWORD"):
            email = os.environ["ADMIN_EMAIL"].lower()
            if not models.User.query.filter_by(email=email).first():
                u = models.User(email=email, name=os.environ.get("ADMIN_NAME", "Administrator"), role="admin")
                u.set_password(os.environ["ADMIN_PASSWORD"])
                db.session.add(u)
                db.session.commit()

    return app
