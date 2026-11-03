import csv
import io
from datetime import date

from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required

from .. import constants as K
from ..finance import monthly_series, pnl
from ..models import Invoice, PayrollRun, Purchase, StockItem, StockMovement
from ..payroll import period_bounds

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.before_request
@login_required
def guard():
    if not current_user.can("reports"):
        abort(403)


def date_range():
    today = date.today()
    try:
        start = date.fromisoformat(request.args.get("from") or today.replace(month=1, day=1).isoformat())
        end = date.fromisoformat(request.args.get("to") or today.isoformat())
    except ValueError:
        start, end = today.replace(month=1, day=1), today
    return start, end


@bp.route("/")
def index():
    return render_template("pages/reports_index.html")


@bp.route("/pnl")
def profit_loss():
    start, end = date_range()
    p = pnl(start, end)
    ents = list(p["by_enterprise"].keys())
    cats = list(p["by_category"].keys())
    matrix = {c: {e: p["costs"].get((c, e), 0) for e in ents} for c in cats}
    if request.args.get("format") == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Line"] + ents + ["Total"])
        w.writerow(["Income"] + [p["income"].get(e, 0) for e in ents] + [p["total_income"]])
        for c in cats:
            w.writerow([c] + [round(matrix[c][e], 2) for e in ents] + [round(p["by_category"][c], 2)])
        w.writerow(["Net profit / (loss)"] + [p["by_enterprise"][e]["net"] for e in ents] + [p["net"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=pnl-{start}-{end}.csv"})
    return render_template("pages/report_pnl.html", p=p, ents=ents, cats=cats, matrix=matrix, start=start, end=end,
                           series=monthly_series(12, end))


@bp.route("/receivables")
def receivables():
    today = date.today()
    rows = []
    for inv in Invoice.query.order_by(Invoice.date).all():
        if inv.balance <= 0:
            continue
        age = (today - (inv.due_date or inv.date)).days
        bucket = "Current" if age <= 0 else "1–30" if age <= 30 else "31–60" if age <= 60 else "61–90" if age <= 90 else "90+"
        rows.append((inv, age, bucket))
    buckets = ["Current", "1–30", "31–60", "61–90", "90+"]
    totals = {b: sum(i.balance for i, _, bb in rows if bb == b) for b in buckets}
    return render_template("pages/report_receivables.html", rows=rows, buckets=buckets, totals=totals)


@bp.route("/payables")
def payables():
    rows = [p for p in Purchase.query.order_by(Purchase.due_date).all() if p.balance > 0]
    by_supplier = {}
    for p in rows:
        by_supplier.setdefault(p.supplier.name if p.supplier else "—", 0)
        by_supplier[p.supplier.name if p.supplier else "—"] += p.balance
    return render_template("pages/report_payables.html", rows=rows, by_supplier=by_supplier)


@bp.route("/stock")
def stock():
    start, end = date_range()
    items = StockItem.query.order_by(StockItem.category, StockItem.name).all()
    by_cat = {}
    for i in items:
        by_cat[i.category] = by_cat.get(i.category, 0) + i.value
    usage = {}
    for m in StockMovement.query.filter(StockMovement.kind == "usage", StockMovement.date.between(start, end)):
        key = (m.enterprise or "General", m.item.name, m.item.unit)
        q, c = usage.get(key, (0, 0))
        usage[key] = (q - m.quantity, c - m.total_cost)
    return render_template("pages/report_stock.html", items=items, by_cat=by_cat, usage=sorted(usage.items()),
                           start=start, end=end)


@bp.route("/payroll")
def payroll_summary():
    runs = PayrollRun.query.order_by(PayrollRun.period.desc()).all()
    return render_template("pages/report_payroll.html", runs=runs)


@bp.route("/enterprises")
def enterprises():
    start, end = date_range()
    p = pnl(start, end)
    return render_template("pages/report_enterprises.html", p=p, start=start, end=end, all_ents=K.ENTERPRISES)
