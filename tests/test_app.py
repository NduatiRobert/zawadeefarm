from datetime import date

from farm import ledger, payroll
from farm.crud import REGISTRY
from farm.extensions import db
from farm.finance import pnl
from farm.models import (
    Activity, GroupMovement, Invoice, InvoiceLine, LivestockGroup, StockItem, StockMovement, StockUsage, Buyer,
)


# ------------------------------------------------------------------ payroll maths
def test_paye_bands():
    assert payroll.paye(24_000, 2_400) == 0  # 2,400 tax fully relieved
    assert payroll.paye(32_333, 2_400) == round(2_400 + 8_333 * 0.25 - 2_400, 2)
    assert payroll.paye(100_000, 2_400) == round(2_400 + 8_333 * 0.25 + 67_667 * 0.30 - 2_400, 2)


def test_nssf_tiers():
    assert payroll.nssf(5_000, 9_000, 108_000, 0.06) == 300
    assert payroll.nssf(50_000, 9_000, 108_000, 0.06) == 3_000
    assert payroll.nssf(200_000, 9_000, 108_000, 0.06) == 6_480  # capped at UEL


def test_compute_payslip(app):
    with app.app_context():
        r = payroll.compute(50_000)
        assert r["nssf"] == 3_000 and r["shif"] == 1_375 and r["housing_levy"] == 750
        assert r["taxable"] == 44_875
        assert r["net"] == round(50_000 - 3_000 - 1_375 - 750 - r["paye"], 2)
        assert payroll.compute(8_000)["shif"] == 300  # SHIF minimum


# ------------------------------------------------------------------ ledgers
def test_stock_balance_equals_ledger(app):
    with app.app_context():
        for item in StockItem.query.all():
            total = sum(m.quantity for m in item.movements)
            assert abs(total - item.quantity) < 1e-6, item.name
            assert item.quantity >= -1e-6, f"{item.name} went negative"


def test_group_count_equals_ledger(app):
    with app.app_context():
        for g in LivestockGroup.query.all():
            moved = sum(m.quantity for m in g.count_movements)
            assert g.current_count == g.opening_count + moved, g.name


def test_usage_edit_and_delete_reverse_stock(app):
    with app.app_context():
        item = StockItem.query.filter_by(name="Layers mash").one()
        group = LivestockGroup.query.filter_by(name="Layers House 1").one()
        before = item.quantity
        u = StockUsage(date=date.today(), item_id=item.id, group_id=group.id, quantity=100)
        db.session.add(u); db.session.flush()
        REGISTRY["usage"].on_save(u, True)
        assert item.quantity == before - 100
        u.quantity = 40
        REGISTRY["usage"].on_save(u, False)  # edit re-posts, not double-posts
        assert item.quantity == before - 40
        REGISTRY["usage"].on_delete(u); db.session.delete(u); db.session.flush()
        assert item.quantity == before
        db.session.rollback()


def test_overdraw_is_refused(app):
    with app.app_context():
        item = StockItem.query.filter_by(name="Iron dextran").one()
        try:
            ledger.stock_out(item.id, item.quantity + 1, "test:x", date.today())
            assert False, "should refuse"
        except ledger.StockError:
            pass
        db.session.rollback()


def test_mortality_and_sale_reduce_head_count(app):
    with app.app_context():
        g = LivestockGroup.query.filter_by(name="Broiler Batch 07").one()
        start = g.current_count
        a = Activity(date=date.today(), activity_type="Mortality", group_id=g.id, affected_count=3)
        db.session.add(a); db.session.flush()
        REGISTRY["activities"].on_save(a, True)
        assert g.current_count == start - 3
        inv = Invoice(buyer_id=Buyer.query.first().id, date=date.today())
        inv.lines = [InvoiceLine(description="Live broilers", group_id=g.id, heads_sold=10, quantity=10, unit_price=550)]
        db.session.add(inv); db.session.flush()
        REGISTRY["invoices"].on_save(inv, True)
        assert g.current_count == start - 13
        assert inv.lines[0].enterprise == "Broilers"
        db.session.rollback()


def test_pnl_excludes_unused_purchases(app):
    with app.app_context():
        today = date.today()
        p = pnl(date(2000, 1, 1), today)
        usage_cost = -sum(m.total_cost for m in StockMovement.query.filter_by(kind="usage"))
        inputs = sum(v for (cat, _), v in p["costs"].items() if cat.endswith(" used"))
        assert abs(inputs - usage_cost) < 0.01
        assert p["total_income"] == round(sum(i.total for i in Invoice.query.all()), 2)


# ------------------------------------------------------------------ every page renders
def test_all_pages_render(app, client):
    urls = ["/", "/tasks/today", "/livestock", "/livestock/sales", "/store/ledger", "/payroll/",
            "/reports/", "/reports/pnl", "/reports/pnl?format=csv", "/reports/enterprises", "/reports/receivables",
            "/reports/payables", "/reports/stock", "/reports/payroll", "/staff/attendance/register",
            "/admin/users", "/admin/users/new", "/admin/settings", "/account", "/healthz"]
    for res in REGISTRY.values():
        urls += [res.path, res.path + "/new", res.path + "/export.csv", res.path + "?q=a&per_page=50",
                 res.path + "?from=2020-01-01&to=2030-01-01" if res.date_field else res.path]
        with app.app_context():
            first = res.model.query.first()
            if first:
                urls.append(f"{res.path}/{first.id}/edit")
    with app.app_context():
        g = LivestockGroup.query.first()
        urls += [f"/livestock/groups/{g.id}", f"/store/items/{StockItem.query.first().id}/history",
                 f"/store/items/{StockItem.query.first().id}/adjust", f"/sales/invoices/{Invoice.query.first().id}",
                 f"/sales/invoices/{Invoice.query.first().id}/print"]
        from farm.models import PayrollRun, Payslip
        urls += [f"/payroll/{PayrollRun.query.first().id}", f"/payroll/payslip/{Payslip.query.first().id}"]
    failures = []
    for u in urls:
        r = client.get(u)
        if r.status_code != 200:
            failures.append((u, r.status_code))
    assert not failures, failures


def test_create_purchase_through_form(app, client):
    with app.app_context():
        sup = __import__("farm.models", fromlist=["Supplier"]).Supplier.query.first().id
        item = StockItem.query.filter_by(name="Limestone").one()
        before = item.quantity
        iid = item.id
    r = client.post("/store/purchases/new", data={
        "supplier_id": sup, "date": date.today().isoformat(), "amount_paid": "0",
        "l_item_id": [str(iid), ""], "l_quantity": ["50", ""], "l_unit_price": ["15", ""]})
    assert r.status_code == 302, r.data[:500]
    with app.app_context():
        assert db.session.get(StockItem, iid).quantity == before + 50


def test_payroll_run_flow(app, client):
    r = client.post("/payroll/new", data={"period": "2031-01"})
    assert r.status_code == 302
    with app.app_context():
        from farm.models import PayrollRun
        run = PayrollRun.query.filter_by(period="2031-01").one()
        assert run.payslips and all(s.net <= s.gross for s in run.payslips)
        rid = run.id
    assert client.post(f"/payroll/{rid}", data={"action": "approve"}).status_code == 302


def test_roles_restrict_access(app):
    c = app.test_client()
    c.post("/login", data={"email": "store@zawadeefarm.co.ke", "password": "zawadee2026"})
    assert c.get("/store/items").status_code == 200
    assert c.get("/payroll/").status_code == 403
    assert c.get("/sales/invoices").status_code == 403
    assert c.get("/admin/users").status_code == 403


def test_login_required(app):
    assert app.test_client().get("/").status_code == 302
