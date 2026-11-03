"""Profit & loss, built from source records so nothing is entered twice.

Income  = invoice lines (by invoice date).
Costs   = store items *used* (at average cost), expenses, activity cash costs,
          payroll (gross + employer NSSF & housing levy), casual labour, and
          livestock bought (group acquisition cost / animal purchase cost).
Stock purchases are NOT costs until used; feed milling is an internal transfer.
"""
from collections import defaultdict
from datetime import date, timedelta

from .models import (
    Activity, Animal, CasualLabour, Expense, Invoice, InvoiceLine, LivestockGroup, PayrollRun, StockItem,
    StockMovement,
)
from .constants import ANIMAL_ENTERPRISE
from .payroll import period_bounds


def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def month_end(d):
    return add_months(d, 1) - timedelta(days=1)


def pnl(start, end):
    income = defaultdict(float)  # enterprise -> amount
    costs = defaultdict(float)  # (category, enterprise) -> amount

    for line, inv_date in (
        InvoiceLine.query.join(Invoice).filter(Invoice.date.between(start, end))
        .with_entities(InvoiceLine, Invoice.date).all()
    ):
        income[line.enterprise or "General"] += line.amount

    for m, cat in (
        StockMovement.query.join(StockItem).filter(StockMovement.kind == "usage", StockMovement.date.between(start, end))
        .with_entities(StockMovement, StockItem.category).all()
    ):
        costs[(f"{cat} used", m.enterprise or "General")] += -(m.total_cost or 0)

    for e in Expense.query.filter(Expense.date.between(start, end)):
        costs[(e.category, e.enterprise or "General")] += e.amount or 0

    for a in Activity.query.filter(Activity.date.between(start, end), Activity.cost > 0):
        ent = a.group.ent if a.group else "General"
        costs[("Veterinary", ent)] += a.cost

    for run in PayrollRun.query.filter(PayrollRun.status != "Draft"):
        p_start, _ = period_bounds(run.period)
        if start <= p_start <= end:
            for s in run.payslips:
                costs[("Salaries & wages", s.employee.enterprise or "General")] += s.employer_cost

    for c in CasualLabour.query.filter(CasualLabour.date.between(start, end)):
        costs[("Casual labour", c.enterprise or "General")] += c.amount

    for g in LivestockGroup.query.filter(LivestockGroup.placement_date.between(start, end), LivestockGroup.acquisition_cost > 0):
        costs[("Livestock purchased", g.ent)] += g.acquisition_cost
    for a in Animal.query.filter(Animal.acquired_on.between(start, end), Animal.purchase_cost > 0):
        costs[("Livestock purchased", a.group.ent if a.group else ANIMAL_ENTERPRISE.get(a.animal_type, "General"))] += a.purchase_cost

    enterprises = sorted({*income.keys(), *(e for _, e in costs.keys())})
    by_ent = {}
    for e in enterprises:
        c = sum(v for (cat, ent), v in costs.items() if ent == e)
        by_ent[e] = dict(income=round(income.get(e, 0), 2), costs=round(c, 2), net=round(income.get(e, 0) - c, 2))
    by_cat = defaultdict(float)
    for (cat, _), v in costs.items():
        by_cat[cat] += v
    total_income = round(sum(income.values()), 2)
    total_costs = round(sum(costs.values()), 2)
    return dict(
        start=start, end=end, income=dict(income), costs=dict(costs), by_enterprise=by_ent,
        by_category=dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        total_income=total_income, total_costs=total_costs, net=round(total_income - total_costs, 2),
    )


def monthly_series(months=6, ending=None):
    ending = ending or date.today()
    first = add_months(ending.replace(day=1), -(months - 1))
    out = []
    for i in range(months):
        s = add_months(first, i)
        p = pnl(s, month_end(s))
        out.append(dict(label=s.strftime("%b %Y"), income=p["total_income"], costs=p["total_costs"], net=p["net"]))
    return out
