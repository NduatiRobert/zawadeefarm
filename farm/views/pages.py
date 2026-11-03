from datetime import date, timedelta
from uuid import uuid4

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import constants as K
from .. import ledger
from .. import settings as S
from ..extensions import db
from ..finance import monthly_series, pnl
from ..models import (
    Activity, Animal, Attendance, Breeding, Employee, GroupMovement, Invoice, InvoiceLine, LivestockGroup, Payment,
    Production, Purchase, PurchaseLine, StockItem, StockMovement, StockRequest, Task, WeightRecord,
)

bp = Blueprint("pages", __name__)

KG_PER_UNIT = {"kg": 1, "bag (70kg)": 70, "bag (50kg)": 50}


def need(section):
    if not current_user.can(section):
        abort(403)


def month_start(d=None):
    return (d or date.today()).replace(day=1)


# =========================================================================== main dashboard
@bp.route("/")
@login_required
def dashboard():
    today = date.today()
    ms = month_start()
    month = pnl(ms, today)
    best = max(month["by_enterprise"].items(), key=lambda kv: kv[1]["income"], default=None)
    best = best if best and best[1]["income"] > 0 else None
    biggest = next(iter(month["by_category"].items()), None)
    items = StockItem.query.all()
    low = [i for i in items if i.is_low]
    purchases = Purchase.query.all()
    open_invoices = [i for i in Invoice.query.all() if i.balance > 0]
    groups = LivestockGroup.query.filter_by(status="Active").all()
    eggs_today = db.session.query(func.coalesce(func.sum(Production.quantity), 0)).filter(
        Production.product == "Eggs", Production.date == today).scalar()
    present = Attendance.query.filter(Attendance.date == today, Attendance.status.in_(["Present", "Half day"])).count()
    staff = Employee.query.filter_by(status="Active").count()
    ctx = dict(
        month=month, best=best, biggest=biggest, low=low,
        inputs_month=sum(p.total for p in purchases if p.date and p.date >= ms),
        supplier_balance=sum(p.balance for p in purchases),
        credits_due=[p for p in purchases if p.balance > 0 and p.due_date and p.due_date <= today + timedelta(days=7)],
        stock_value=sum(i.value for i in items),
        receivables=sum(i.balance for i in open_invoices),
        overdue_invoices=[i for i in open_invoices if i.status == "Overdue"],
        heads=sum(g.current_count for g in groups),
        pigs=sum(g.current_count for g in groups if g.animal_type == "Pig"),
        birds=sum(g.current_count for g in groups if g.animal_type in K.POULTRY_TYPES),
        eggs_today=eggs_today, present=present, staff=staff,
        series=monthly_series(6),
        tasks=Task.query.filter(Task.status != "Done", Task.due_date <= today + timedelta(days=2)).order_by(Task.due_date).limit(6).all(),
        farrowings=Breeding.query.filter(Breeding.status.in_(["Served", "Pregnant"]),
                                         Breeding.expected_date <= today + timedelta(days=21)).order_by(Breeding.expected_date).all(),
    )
    return render_template("pages/dashboard.html", **ctx)


# =========================================================================== daily agenda
@bp.route("/tasks/today", methods=["GET", "POST"])
@login_required
def daily():
    need("tasks")
    today = date.today()
    if request.method == "POST":
        kind, id = request.form.get("kind"), int(request.form.get("id", 0))
        if kind == "task":
            t = db.get_or_404(Task, id)
            t.status = "Done"
        elif kind == "followup":
            a = db.get_or_404(Activity, id)
            a.follow_up_done = True
        db.session.commit()
        flash("Marked as done.", "success")
        return redirect(url_for("pages.daily"))
    horizon = today + timedelta(days=3)
    ctx = dict(
        today=today,
        tasks=Task.query.filter(Task.status != "Done", Task.due_date <= horizon).order_by(Task.due_date, Task.priority).all(),
        followups=Activity.query.filter(Activity.next_due_date.isnot(None), Activity.next_due_date <= today + timedelta(days=7),
                                        Activity.follow_up_done.is_(False)).order_by(Activity.next_due_date).all(),
        farrowings=Breeding.query.filter(Breeding.status.in_(["Served", "Pregnant"]),
                                         Breeding.expected_date <= today + timedelta(days=7)).order_by(Breeding.expected_date).all(),
        requests=StockRequest.query.filter(StockRequest.status.in_(["Pending", "Approved"])).order_by(StockRequest.needed_by).all(),
        low=[i for i in StockItem.query.order_by(StockItem.name) if i.is_low],
        markets=LivestockGroup.query.filter(LivestockGroup.status == "Active", LivestockGroup.target_market_date.isnot(None),
                                            LivestockGroup.target_market_date <= today + timedelta(days=14)).all(),
        recorded_eggs=Production.query.filter_by(date=today, product="Eggs").count(),
        attendance_taken=Attendance.query.filter_by(date=today).count(),
    )
    return render_template("pages/daily.html", **ctx)


# =========================================================================== livestock dashboard
def group_feed_kg(group_id):
    rows = (StockMovement.query.join(StockItem)
            .filter(StockMovement.group_id == group_id, StockMovement.kind == "usage", StockItem.category == "Feed")
            .with_entities(StockMovement.quantity, StockItem.unit).all())
    return round(sum(-q * KG_PER_UNIT.get(u, 1) for q, u in rows), 2)


def group_fcr(g):
    feed = group_feed_kg(g.id)
    weights = WeightRecord.query.filter_by(group_id=g.id).order_by(WeightRecord.date).all()
    if not feed or not weights:
        return None
    start_w = weights[0].avg_weight * (g.opening_count or 0) if len(weights) > 1 else 0
    gain = weights[-1].avg_weight * (g.current_count or 0) - start_w
    return round(feed / gain, 2) if gain > 0 else None


@bp.route("/livestock")
@login_required
def livestock_dashboard():
    need("livestock")
    today = date.today()
    ms = month_start()
    groups = LivestockGroup.query.filter_by(status="Active").order_by(LivestockGroup.name).all()
    loose = Animal.query.filter(Animal.status == "Active", Animal.group_id.is_(None)).count()
    poultry = [g for g in groups if g.animal_type in K.POULTRY_TYPES]
    layers = [g for g in poultry if g.animal_type == "Layer chicken"]
    pig_groups = [g for g in groups if g.animal_type == "Pig"]

    week_ago = today - timedelta(days=6)
    # Laying rate covers commercial layer flocks only (kienyeji lay far less and would skew it).
    eggs_7d = db.session.query(func.coalesce(func.sum(Production.quantity), 0)).filter(
        Production.product == "Eggs", Production.date >= week_ago,
        Production.group_id.in_([g.id for g in layers] or [0])).scalar()
    hens = sum(g.current_count for g in layers)
    eggs_month = db.session.query(func.coalesce(func.sum(Production.quantity), 0)).filter(
        Production.product == "Eggs", Production.date >= ms).scalar()
    per_tray = S.get_float("eggs_per_tray") or 30
    grades = (db.session.query(Production.grade, func.sum(Production.quantity))
              .filter(Production.product == "Eggs", Production.date >= ms).group_by(Production.grade).all())
    prod_value = sum(p.value for p in Production.query.filter(Production.date >= ms))
    livestock_ents = [e for e in K.ENTERPRISES if e not in ("Feed Mill", "General")]
    sales_value = sum(l.amount for l in InvoiceLine.query.join(Invoice)
                      .filter(Invoice.date >= ms, InvoiceLine.enterprise.in_(livestock_ents)))

    six_months = today - timedelta(days=183)
    litters = Breeding.query.filter(Breeding.actual_date >= six_months, Breeding.born_alive > 0).all()
    born = sum(b.born_alive for b in litters)
    weaned_litters = [b for b in litters if b.weaned_count is not None]
    prewean = (sum(b.born_alive - b.weaned_count for b in weaned_litters) * 100 / sum(b.born_alive for b in weaned_litters)
               if weaned_litters else None)
    broilers = [g for g in poultry if g.animal_type == "Broiler chicken"]
    fcrs = [f for f in (group_fcr(g) for g in broilers) if f]

    ctx = dict(
        active=sum(g.current_count for g in groups) + loose,
        followups=Activity.query.filter(Activity.next_due_date <= today + timedelta(days=7),
                                        Activity.follow_up_done.is_(False)).count(),
        prod_value=prod_value, sales_value=sales_value,
        sows=Animal.query.filter_by(animal_type="Pig", sex="Female", status="Active").count(),
        boars=Animal.query.filter_by(animal_type="Pig", sex="Male", status="Active").count(),
        pigs=sum(g.current_count for g in pig_groups) + Animal.query.filter(
            Animal.animal_type == "Pig", Animal.status == "Active", Animal.group_id.is_(None)).count(),
        farrow_due=Breeding.query.filter(Breeding.status.in_(["Served", "Pregnant"]),
                                         Breeding.expected_date <= today + timedelta(days=30)).order_by(Breeding.expected_date).all(),
        avg_litter=round(born / len(litters), 1) if litters else None,
        prewean=round(prewean, 1) if prewean is not None else None,
        pig_groups=pig_groups,
        birds=sum(g.current_count for g in poultry),
        poultry_mortality=round(sum(g.deaths for g in poultry) * 100 / max(sum(g.opening_count or 0 for g in poultry), 1), 1),
        egg_trays=eggs_month / per_tray, eggs_month=eggs_month,
        lay_rate=round(eggs_7d * 100 / (hens * 7), 1) if hens else None,
        fcr=round(sum(fcrs) / len(fcrs), 2) if fcrs else None,
        poultry=poultry, grades=grades, per_tray=per_tray, soon=today + timedelta(days=7),
        schedule=Activity.query.filter(Activity.next_due_date.isnot(None), Activity.follow_up_done.is_(False))
        .order_by(Activity.next_due_date).limit(8).all(),
    )
    return render_template("pages/livestock_dashboard.html", **ctx)


@bp.route("/livestock/groups/<int:id>")
@login_required
def group_detail(id):
    need("livestock")
    g = db.get_or_404(LivestockGroup, id)
    usage = (StockMovement.query.filter_by(group_id=g.id, kind="usage").order_by(StockMovement.date.desc()).all())
    activities = Activity.query.filter_by(group_id=g.id).order_by(Activity.date.desc()).all()
    sales = InvoiceLine.query.filter_by(group_id=g.id).join(Invoice).order_by(Invoice.date.desc()).all()
    production = Production.query.filter_by(group_id=g.id).order_by(Production.date.desc()).limit(30).all()
    weights = WeightRecord.query.filter_by(group_id=g.id).order_by(WeightRecord.date).all()
    input_cost = sum(-m.total_cost for m in usage)
    vet_cost = sum(a.cost or 0 for a in activities)
    income = sum(l.amount for l in sales)
    total_cost = input_cost + vet_cost + (g.acquisition_cost or 0)
    adg = None
    if len(weights) > 1:
        days = (weights[-1].date - weights[0].date).days
        adg = round((weights[-1].avg_weight - weights[0].avg_weight) * 1000 / days, 0) if days else None
    return render_template(
        "pages/group_detail.html", g=g, usage=usage, activities=activities, sales=sales, production=production,
        weights=weights, movements=g.count_movements.order_by(GroupMovement.date.desc()).all(),
        feed_kg=group_feed_kg(g.id), fcr=group_fcr(g), adg=adg, input_cost=input_cost, vet_cost=vet_cost,
        income=income, total_cost=total_cost, production_value=sum(p.value for p in production),
        cost_per_head=round(total_cost / g.current_count, 2) if g.current_count else None,
    )


@bp.route("/livestock/sales")
@login_required
def livestock_sales():
    need("sales")
    ents = [e for e in K.ENTERPRISES if e not in ("Feed Mill", "General")]
    lines = (InvoiceLine.query.join(Invoice).filter(InvoiceLine.enterprise.in_(ents))
             .order_by(Invoice.date.desc()).limit(300).all())
    return render_template("pages/livestock_sales.html", lines=lines,
                           total=sum(l.amount for l in lines), heads=sum(l.heads_sold or 0 for l in lines))


# =========================================================================== store tools
@bp.route("/store/items/<int:id>/history")
@login_required
def item_history(id):
    need("store")
    item = db.get_or_404(StockItem, id)
    moves = item.movements.order_by(StockMovement.date, StockMovement.id).all()
    running, rows = 0, []
    for m in moves:
        running += m.quantity
        rows.append((m, running))
    return render_template("pages/item_history.html", item=item, rows=list(reversed(rows)))


@bp.route("/store/items/<int:id>/adjust", methods=["GET", "POST"])
@login_required
def item_adjust(id):
    need("store")
    item = db.get_or_404(StockItem, id)
    if request.method == "POST":
        try:
            counted = float(request.form["counted"])
            cost = float(request.form.get("unit_cost") or item.avg_cost or 0)
            when = date.fromisoformat(request.form.get("date") or date.today().isoformat())
        except ValueError:
            flash("Enter a valid quantity, cost and date.", "danger")
            return redirect(request.url)
        reason = request.form.get("reason") or "Stock count adjustment"
        diff = round(counted - (item.quantity or 0), 4)
        if diff == 0:
            flash("No change – the count matches the system balance.", "info")
            return redirect(url_for("crud.items_list"))
        ref = f"adjust:{item.id}:{uuid4().hex[:12]}"
        kind = "opening" if not item.movements.count() else "adjustment"
        if diff > 0:
            ledger.stock_in(item.id, diff, cost, ref, when, kind, reason)
        else:
            ledger.stock_out(item.id, -diff, ref, when, "adjustment", enterprise="General", notes=reason)
        db.session.commit()
        flash(f"{item.name} adjusted by {diff:+g} {item.unit}.", "success")
        return redirect(url_for("crud.items_list"))
    return render_template("pages/item_adjust.html", item=item, today=date.today())


@bp.route("/store/ledger")
@login_required
def stock_ledger():
    need("store")
    q = StockMovement.query.join(StockItem)
    kind = request.args.get("kind")
    if kind:
        q = q.filter(StockMovement.kind == kind)
    if request.args.get("item"):
        q = q.filter(StockMovement.item_id == int(request.args["item"]))
    moves = q.order_by(StockMovement.date.desc(), StockMovement.id.desc()).limit(500).all()
    return render_template("pages/stock_ledger.html", moves=moves, items=StockItem.query.order_by(StockItem.name).all(),
                           kinds=["opening", "purchase", "usage", "mill_out", "mill_in", "adjustment"])


# =========================================================================== invoice view
@bp.route("/sales/invoices/<int:id>", methods=["GET", "POST"])
@login_required
def invoice_view(id):
    need("sales")
    inv = db.get_or_404(Invoice, id)
    if request.method == "POST":
        try:
            amt = float(request.form["amount"])
            if amt <= 0:
                raise ValueError
        except ValueError:
            flash("Enter a valid payment amount.", "danger")
            return redirect(request.url)
        db.session.add(Payment(invoice_id=inv.id, amount=amt,
                               date=date.fromisoformat(request.form.get("date") or date.today().isoformat()),
                               method=request.form.get("method"), reference=request.form.get("reference")))
        db.session.commit()
        flash("Payment recorded.", "success")
        return redirect(request.url)
    return render_template("pages/invoice_view.html", inv=inv, today=date.today(), methods=K.PAYMENT_METHODS)


@bp.route("/sales/invoices/<int:id>/print")
@login_required
def invoice_print(id):
    need("sales")
    return render_template("print/invoice.html", inv=db.get_or_404(Invoice, id))


# =========================================================================== attendance register
@bp.route("/staff/attendance/register", methods=["GET", "POST"])
@login_required
def attendance_register():
    need("staff")
    try:
        day = date.fromisoformat(request.values.get("date") or date.today().isoformat())
    except ValueError:
        day = date.today()
    staff = Employee.query.filter(Employee.status != "Terminated").order_by(Employee.name).all()
    existing = {a.employee_id: a for a in Attendance.query.filter_by(date=day)}
    if request.method == "POST":
        for e in staff:
            status = request.form.get(f"s_{e.id}")
            if not status:
                continue
            a = existing.get(e.id) or Attendance(employee_id=e.id, date=day)
            a.status = status
            try:
                a.overtime_hours = float(request.form.get(f"ot_{e.id}") or 0)
            except ValueError:
                a.overtime_hours = 0
            db.session.add(a)
        db.session.commit()
        flash(f"Attendance saved for {day:%d %b %Y}.", "success")
        return redirect(url_for("pages.attendance_register", date=day.isoformat()))
    return render_template("pages/attendance_register.html", day=day, staff=staff, existing=existing,
                           statuses=K.ATTENDANCE_STATUSES)
