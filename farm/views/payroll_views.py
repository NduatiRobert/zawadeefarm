from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import payroll as P
from ..extensions import db
from ..models import Attendance, Employee, PayrollRun, Payslip

bp = Blueprint("payroll", __name__, url_prefix="/payroll")


@bp.before_request
@login_required
def guard():
    if not current_user.can("payroll"):
        abort(403)


def days_worked(emp, start, end):
    rows = Attendance.query.filter(Attendance.employee_id == emp.id, Attendance.date.between(start, end)).all()
    days = sum(1 if r.status == "Present" else 0.5 if r.status == "Half day" else 0 for r in rows)
    ot = sum(r.overtime_hours or 0 for r in rows)
    return days, ot


def fill_payslip(slip):
    """(Re)compute a payslip from the employee record, attendance and statutory rates."""
    emp = slip.employee or db.session.get(Employee, slip.employee_id)
    start, end = P.period_bounds(slip.run.period)
    days, ot_hours = days_worked(emp, start, end)
    slip.days_worked = days
    if emp.pay_basis == "Daily":
        slip.basic = round(days * (emp.daily_rate or 0), 2)
        hourly = (emp.daily_rate or 0) / 8
    else:
        slip.basic = emp.basic_salary or 0
        hourly = (emp.basic_salary or 0) / 225  # ~ 26 days x 8.65h; adjust to farm policy
    slip.allowances = round((emp.house_allowance or 0) + (emp.other_allowance or 0), 2)
    slip.overtime = round(ot_hours * hourly * 1.5, 2)
    calc = P.compute(slip.basic, slip.allowances, slip.overtime, slip.advances or 0, slip.other_deductions or 0)
    for k, v in calc.items():
        setattr(slip, k, v)


@bp.route("/")
def runs():
    runs = PayrollRun.query.order_by(PayrollRun.period.desc()).all()
    return render_template("pages/payroll_runs.html", runs=runs, default_period=date.today().strftime("%Y-%m"))


@bp.route("/new", methods=["POST"])
def new_run():
    period = request.form.get("period", "")
    try:
        P.period_bounds(period)
    except (ValueError, TypeError):
        flash("Choose a valid month.", "danger")
        return redirect(url_for("payroll.runs"))
    if PayrollRun.query.filter_by(period=period).first():
        flash(f"A payroll for {period} already exists.", "warning")
        return redirect(url_for("payroll.runs"))
    run = PayrollRun(period=period)
    db.session.add(run)
    db.session.flush()
    staff = Employee.query.filter(Employee.status != "Terminated", Employee.employment_type != "Casual").all()
    for e in staff:
        slip = Payslip(run=run, employee=e)
        db.session.add(slip)
        fill_payslip(slip)
    db.session.commit()
    flash(f"Payroll for {period} drafted with {len(staff)} payslips. Review deductions, then approve.", "success")
    return redirect(url_for("payroll.run_detail", id=run.id))


@bp.route("/<int:id>", methods=["GET", "POST"])
def run_detail(id):
    run = db.get_or_404(PayrollRun, id)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "recalc" and run.status == "Draft":
            for s in run.payslips:
                try:
                    s.advances = float(request.form.get(f"adv_{s.id}") or 0)
                    s.other_deductions = float(request.form.get(f"oth_{s.id}") or 0)
                except ValueError:
                    flash(f"Invalid deduction for {s.employee.name}.", "danger")
                    return redirect(request.url)
                fill_payslip(s)
            flash("Payslips recalculated.", "success")
        elif action == "approve" and run.status == "Draft":
            run.status = "Approved"
            flash("Payroll approved. Salaries now appear in profit and loss.", "success")
        elif action == "paid" and run.status == "Approved":
            run.status, run.paid_on = "Paid", date.today()
            flash("Payroll marked as paid.", "success")
        elif action == "reopen" and run.status == "Approved":
            run.status = "Draft"
        elif action == "delete" and run.status == "Draft":
            db.session.delete(run)
            db.session.commit()
            flash("Draft payroll deleted.", "success")
            return redirect(url_for("payroll.runs"))
        db.session.commit()
        return redirect(request.url)
    slips = sorted(run.payslips, key=lambda s: s.employee.name)
    return render_template("pages/payroll_run.html", run=run, slips=slips)


@bp.route("/payslip/<int:id>")
def payslip(id):
    return render_template("print/payslip.html", s=db.get_or_404(Payslip, id))
