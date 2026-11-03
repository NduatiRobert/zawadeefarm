"""Demo data: a mixed pig + poultry farm with ~4 months of history.

All records go through the same hooks the web forms use, so stock ledgers,
head counts and P&L are internally consistent.
"""
import random
from datetime import date, timedelta

from . import resources as R
from . import settings as S
from .extensions import db
from .models import (
    Activity, Animal, Attendance, Breeding, Buyer, CasualLabour, Employee, Expense, FeedBatch, FeedFormula,
    FeedFormulaLine, Invoice, InvoiceLine, LivestockGroup, Payment, PayrollRun, Payslip, Production, Purchase,
    PurchaseLine, StockItem, StockRequest, StockUsage, Supplier, Task, User, WeightRecord,
)

T = date.today()


def ago(days):
    return T - timedelta(days=days)


def save(obj, hook=None):
    db.session.add(obj)
    db.session.flush()
    if hook:
        hook(obj, True)
    return obj


def seed():
    random.seed(7)
    if User.query.filter_by(email="admin@zawadeefarm.co.ke").first():
        print("Demo data already loaded.")
        return
    S.set_many({"farm_name": "Zawadee Farm", "farm_location": "Kiambu County, Kenya", "farm_phone": "+254 700 000 000",
                "farm_email": "info@zawadeefarm.co.ke"})

    for email, name, role in [("admin@zawadeefarm.co.ke", "Farm Admin", "admin"),
                              ("manager@zawadeefarm.co.ke", "Farm Manager", "manager"),
                              ("store@zawadeefarm.co.ke", "Storekeeper", "storekeeper")]:
        u = User(email=email, name=name, role=role)
        u.set_password("zawadee2026")
        db.session.add(u)

    # ------------------------------------------------------------ suppliers & items
    sup = {n: save(Supplier(name=n, supplier_type=t, phone=p, location=l)) for n, t, p, l in [
        ("Ruiru Feeds Ltd", "Feed supplier", "0711 000 101", "Ruiru"),
        ("Thika Grain Millers", "Ingredients", "0722 000 202", "Thika"),
        ("Kiambu Agrovet", "Agrovet", "0733 000 303", "Kiambu town"),
        ("Highland Hatchery", "Hatchery", "0744 000 404", "Limuru"),
    ]}
    item = {}
    for name, cat, unit, reorder in [
        ("Maize germ", "Feed Ingredient", "kg", 500), ("Wheat bran", "Feed Ingredient", "kg", 400),
        ("Soya meal", "Feed Ingredient", "kg", 200), ("Fish meal (omena)", "Feed Ingredient", "kg", 100),
        ("Limestone", "Feed Ingredient", "kg", 50), ("Pig premix", "Supplement", "kg", 40),
        ("Layers mash", "Feed", "kg", 1000), ("Broiler starter crumbs", "Feed", "kg", 100),
        ("Broiler finisher pellets", "Feed", "kg", 200), ("Sow & weaner meal", "Feed", "kg", 300),
        ("Pig finisher meal", "Feed", "kg", 400), ("Newcastle vaccine (Lasota)", "Vaccine", "dose", 500),
        ("Gumboro vaccine", "Vaccine", "dose", 500), ("Iron dextran", "Medicine", "ml", 20),
        ("Ivermectin 1%", "Medicine", "ml", 30), ("Wood shavings", "Bedding", "pack", 10),
        ("Egg trays", "Packaging", "piece", 200),
    ]:
        item[name] = save(StockItem(name=name, category=cat, unit=unit, reorder_level=reorder))

    def purchase(days, supplier, lines, paid_ratio=1.0, credit_days=None):
        p = Purchase(supplier=sup[supplier], date=ago(days), reference=f"INV{random.randint(1000, 9999)}",
                     due_date=ago(days - credit_days) if credit_days else None, payment_method="M-Pesa")
        p.lines = [PurchaseLine(item_id=item[n].id, quantity=q, unit_price=pr) for n, q, pr in lines]
        save(p)
        p.amount_paid = round(p.total * paid_ratio, 2)
        R._purchase_save(p, True)

    purchase(120, "Thika Grain Millers", [("Maize germ", 2000, 34), ("Wheat bran", 1500, 28), ("Soya meal", 600, 95),
                                          ("Fish meal (omena)", 250, 110), ("Limestone", 120, 15)])
    purchase(118, "Kiambu Agrovet", [("Pig premix", 320, 260), ("Newcastle vaccine (Lasota)", 2000, 2.5),
                                     ("Gumboro vaccine", 2000, 3), ("Iron dextran", 100, 18), ("Ivermectin 1%", 100, 25),
                                     ("Wood shavings", 40, 350), ("Egg trays", 1500, 9)])
    purchase(115, "Ruiru Feeds Ltd", [("Layers mash", 4500, 62), ("Pig finisher meal", 1200, 58)])
    purchase(70, "Ruiru Feeds Ltd", [("Layers mash", 5500, 63), ("Pig finisher meal", 3000, 59), ("Broiler starter crumbs", 800, 78),
                                     ("Broiler finisher pellets", 1400, 74)])
    purchase(60, "Thika Grain Millers", [("Maize germ", 1600, 36), ("Wheat bran", 1100, 29), ("Soya meal", 450, 98),
                                         ("Fish meal (omena)", 150, 112), ("Limestone", 80, 15)], 0.5, 30)
    purchase(20, "Ruiru Feeds Ltd", [("Layers mash", 3000, 64), ("Broiler starter crumbs", 300, 80),
                                     ("Broiler finisher pellets", 1000, 75)], 0.0, 30)
    purchase(10, "Kiambu Agrovet", [("Pig premix", 60, 265), ("Egg trays", 1000, 9)], 0.0, 14)

    # ------------------------------------------------------------ feed mill
    def formula(name, ent, output, lines):
        f = FeedFormula(name=name, enterprise=ent, output_item_id=item[output].id)
        f.lines = [FeedFormulaLine(item_id=item[n].id, quantity=q) for n, q in lines]
        return save(f)

    sw = formula("Sow & Weaner Meal (1 t)", "Pigs", "Sow & weaner meal", [
        ("Maize germ", 400), ("Wheat bran", 300), ("Soya meal", 150), ("Fish meal (omena)", 80),
        ("Limestone", 20), ("Pig premix", 50)])
    fin = formula("Pig Finisher Meal (1 t)", "Pigs", "Pig finisher meal", [
        ("Maize germ", 500), ("Wheat bran", 350), ("Soya meal", 100), ("Limestone", 20), ("Pig premix", 30)])
    for days, f, n, out in [(110, sw, 1, 985), (105, fin, 1, 990), (75, fin, 1, 992), (55, sw, 1, 988),
                            (40, fin, 1, 990), (25, sw, 1, 990), (12, fin, 1, 988)]:
        save(FeedBatch(date=ago(days), formula_id=f.id, batches=n, output_qty=out, produced_by="Peter Kamau"), R._batch_save)

    # ------------------------------------------------------------ livestock groups
    def group(name, typ, purpose, n, days, cost=0, market=None, status="Active", breed=None, loc=None):
        g = LivestockGroup(name=name, animal_type=typ, purpose=purpose, opening_count=n, placement_date=ago(days),
                           acquisition_cost=cost, target_market_date=(T + timedelta(days=market)) if market is not None else None,
                           status=status, breed=breed, location=loc)
        return save(g, R._group_save)

    G = {
        "breeders": group("Sows & Boars", "Pig", "Breeding", 0, 400, breed="Large White x Landrace", loc="Pig unit – breeding pens"),
        "farrow": group("Farrowing Pen 1", "Pig", "Farrowing", 0, 30, loc="Pig unit – farrowing house"),
        "weaners": group("Weaners Pen A", "Pig", "Weaners", 38, 60, loc="Pig unit – pen A"),
        "fatteners": group("Fatteners Pen B", "Pig", "Growers / Fatteners", 34, 125, market=12, loc="Pig unit – pen B"),
        "oldfat": group("Fatteners Pen C (2026 Q2)", "Pig", "Growers / Fatteners", 30, 200, loc="Pig unit – pen C"),
        "layers": group("Layers House 1", "Layer chicken", "Layers", 1000, 210, 330_000, breed="Isa Brown", loc="Poultry – house 1"),
        "b06": group("Broiler Batch 06", "Broiler chicken", "Broilers (meat)", 500, 85, 42_500, breed="Cobb 500", loc="Poultry – house 2"),
        "b07": group("Broiler Batch 07", "Broiler chicken", "Broilers (meat)", 500, 29, 45_000, market=6, breed="Cobb 500", loc="Poultry – house 2"),
        "kienyeji": group("Kienyeji Flock", "Kienyeji chicken", "Layers", 220, 300, 66_000, breed="Improved Kienyeji", loc="Free range run"),
    }
    # The breeding herd is individually registered.
    sows = []
    for i, name in enumerate(["Neema", "Baraka", "Zuri", "Imani", "Furaha", "Amani"], 1):
        sows.append(save(Animal(tag_number=f"S-{i:03d}", name=name, animal_type="Pig", group_id=G["breeders"].id,
                                breed="Large White x Landrace", sex="Female", source="Purchased", acquired_on=ago(400),
                                purchase_cost=0, current_weight=180 + i * 5, breeding_status="Open",
                                date_of_birth=ago(700 + i * 20))))
    boar = save(Animal(tag_number="B-001", name="Simba", animal_type="Pig", group_id=G["breeders"].id, breed="Duroc",
                       sex="Male", source="Purchased", acquired_on=ago(420), current_weight=240, date_of_birth=ago(800)))
    G["breeders"].opening_count = 7
    R._group_save(G["breeders"], False)

    def breed(sow, served, status, born=None, still=None, weaned=None, group_key="farrow"):
        b = Breeding(female_id=sow.id, male_id=boar.id, service_date=ago(served), status=status, born_alive=born,
                     stillborn=still, weaned_count=weaned, litter_group_id=G[group_key].id if born else None,
                     actual_date=ago(served - 114) if born else None,
                     weaning_date=ago(served - 114 - 28) if weaned is not None else None)
        return save(b, R._breeding_save)

    breed(sows[0], 134, "Delivered", 11, 1)
    breed(sows[1], 110, "Pregnant")
    breed(sows[2], 35, "Pregnant")
    breed(sows[3], 12, "Served")
    breed(sows[4], 190, "Weaned", 10, 0, 9, "weaners")
    breed(sows[5], 175, "Weaned", 12, 1, 11, "weaners")

    # ------------------------------------------------------------ activities
    def act(days, typ, gkey, desc, count=0, item_name=None, qty=0, cost=0, next_due=None, done=False, who="Grace Wanjiru"):
        a = Activity(date=ago(days), activity_type=typ, group_id=G[gkey].id, description=desc, affected_count=count,
                     stock_item_id=item[item_name].id if item_name else None, quantity_used=qty, cost=cost,
                     next_due_date=(T + timedelta(days=next_due)) if next_due is not None else None,
                     follow_up_done=done, performed_by=who)
        return save(a, R._activity_save)

    act(26, "Vaccination", "b07", "Gumboro – drinking water (day 3)", 500, "Gumboro vaccine", 500, done=True, next_due=-12)
    act(22, "Vaccination", "b07", "Newcastle (Lasota) – drinking water (day 7)", 498, "Newcastle vaccine (Lasota)", 500, done=True)
    act(14, "Vaccination", "b07", "Gumboro booster (day 14)", 495, "Gumboro vaccine", 500, done=True)
    act(80, "Vaccination", "b06", "Gumboro – day 3", 500, "Gumboro vaccine", 500, done=True)
    act(60, "Vaccination", "layers", "Newcastle booster – 3-monthly", 990, "Newcastle vaccine (Lasota)", 1000, next_due=2)
    act(28, "Iron injection", "farrow", "Iron dextran 1 ml per piglet, day 3", 11, "Iron dextran", 11, done=True)
    act(18, "Deworming", "fatteners", "Ivermectin 1 ml / 33 kg", 34, "Ivermectin 1%", 45, next_due=-3)
    act(5, "Vet visit", "fatteners", "Routine check; two pigs coughing – treated", 2, cost=3500, next_due=4,
        who="Dr. Otieno (vet)")
    act(1, "Castration", "farrow", "Male piglets castrated", 5, done=True)
    act(40, "Deworming", "weaners", "Ivermectin at weaning", 20, "Ivermectin 1%", 12, next_due=1)
    for d, gk, n, why in [(27, "b07", 4, "Brooding losses"), (20, "b07", 3, "Leg problems"), (9, "b07", 2, "Heat stress"),
                          (78, "b06", 8, "Brooding losses"), (60, "b06", 7, "Ascites"), (45, "b06", 5, "Unknown"),
                          (90, "layers", 6, "Peck injuries"), (40, "layers", 5, "Egg peritonitis"), (8, "layers", 3, "Unknown"),
                          (100, "fatteners", 1, "Pneumonia"), (25, "weaners", 1, "Scours"), (150, "oldfat", 1, "Crushed")]:
        act(d, "Mortality", gk, why, n)

    # ------------------------------------------------------------ feeding (weekly issues from store)
    def use(days, name, gkey, qty, purpose="Weekly feed issue"):
        save(StockUsage(date=ago(days), item_id=item[name].id, group_id=G[gkey].id, quantity=qty, purpose=purpose,
                        issued_by="Store"), R._usage_save)

    for w in range(1, 16):
        d = 112 - w * 7
        use(d, "Layers mash", "layers", 750)
        use(d, "Sow & weaner meal", "breeders", 100)
        if d <= 60:
            use(d, "Sow & weaner meal", "weaners", 110 + (60 - d) * 2)
        if d <= 120:
            use(d, "Pig finisher meal", "fatteners", min(150 + (125 - d) * 4, 600))
        if d >= 77:
            use(d, "Pig finisher meal", "oldfat", 200)
    for d, name, q in [(84, "Broiler starter crumbs", 220), (77, "Broiler starter crumbs", 300), (70, "Broiler finisher pellets", 450),
                       (63, "Broiler finisher pellets", 500), (56, "Broiler finisher pellets", 380)]:
        use(d, name, "b06", q)
    for d, name, q in [(28, "Broiler starter crumbs", 210), (21, "Broiler starter crumbs", 300), (14, "Broiler finisher pellets", 420),
                       (7, "Broiler finisher pellets", 500)]:
        use(d, name, "b07", q)
    use(30, "Wood shavings", "b07", 12, "Litter for new batch")
    use(15, "Egg trays", "layers", 900, "Packing eggs")

    # ------------------------------------------------------------ weights
    for d, w in [(28, 0.05), (21, 0.19), (14, 0.48), (7, 0.95), (0, 1.62)]:
        save(WeightRecord(date=ago(d), group_id=G["b07"].id, sample_size=30, avg_weight=w))
    for d, w in [(125, 24), (95, 38), (65, 55), (35, 72), (5, 88)]:
        save(WeightRecord(date=ago(d), group_id=G["fatteners"].id, sample_size=10, avg_weight=w))

    # ------------------------------------------------------------ eggs
    for d in range(75, -1, -1):
        hens = G["layers"].current_count
        laid = int(hens * random.uniform(0.80, 0.88))
        for grade, share, price in [("Large", .48, 14), ("Medium", .36, 13), ("Small", .11, 11), ("Cracked", .05, 6)]:
            db.session.add(Production(date=ago(d), group_id=G["layers"].id, product="Eggs", grade=grade,
                                      quantity=int(laid * share), unit_value=price, recorded_by="Grace Wanjiru"))
        if d <= 45:
            db.session.add(Production(date=ago(d), group_id=G["kienyeji"].id, product="Eggs", grade="Ungraded",
                                      quantity=random.randint(45, 70), unit_value=20, recorded_by="Grace Wanjiru"))
    for d in range(90, 0, -30):
        db.session.add(Production(date=ago(d), group_id=G["breeders"].id, product="Manure", quantity=40, unit_value=150,
                                  notes="Bagged pig manure"))

    # ------------------------------------------------------------ buyers & invoices
    B = {n: save(Buyer(name=n, buyer_type=t, phone=p, location=l)) for n, t, p, l in [
        ("Ruiru Pork Butchery", "Butchery", "0701 111 222", "Ruiru"),
        ("Kahawa Fresh Mart", "Supermarket", "0702 333 444", "Kahawa West"),
        ("Thika Road Hotel", "Hotel / Restaurant", "0703 555 666", "Thika Road"),
        ("Mama Wanjiku Eggs", "Retail shop", "0704 777 888", "Kiambu town"),
        ("Juja Wholesalers", "Wholesaler", "0705 999 000", "Juja"),
    ]}

    def invoice(days, buyer, lines, paid=1.0, terms=14):
        inv = Invoice(buyer_id=B[buyer].id, date=ago(days), due_date=ago(days - terms))
        inv.lines = [InvoiceLine(**l) for l in lines]
        save(inv, R._invoice_save)
        if paid:
            db.session.add(Payment(invoice_id=inv.id, date=ago(max(days - 7, 0)), amount=round(inv.total * paid, 2),
                                   method="M-Pesa", reference=f"SJ{random.randint(10000000, 99999999)}"))
        return inv

    for wk in range(15, -1, -1):
        d = wk * 7 + 2
        invoice(d, "Kahawa Fresh Mart", [dict(description="Eggs – large & medium (trays)", enterprise="Layers",
                                              quantity=random.randint(140, 160), unit="trays", unit_price=400)],
                paid=1.0 if wk > 1 else 0.0)
        invoice(d, "Mama Wanjiku Eggs", [dict(description="Eggs – small & cracked (trays)", enterprise="Layers",
                                             quantity=random.randint(25, 35), unit="trays", unit_price=280),
                                        dict(description="Kienyeji eggs (trays)", enterprise="Kienyeji Poultry",
                                             quantity=random.randint(8, 12), unit="trays", unit_price=600)],
                paid=1.0 if wk > 0 else 0.5, terms=7)
    invoice(45, "Thika Road Hotel", [dict(description="Live broilers", enterprise="Broilers", group_id=G["b06"].id,
                                          heads_sold=300, quantity=300, unit="birds", unit_price=560)])
    invoice(43, "Juja Wholesalers", [dict(description="Live broilers", enterprise="Broilers", group_id=G["b06"].id,
                                          heads_sold=180, quantity=180, unit="birds", unit_price=540)], paid=1.0)
    invoice(70, "Ruiru Pork Butchery", [dict(description="Finished pigs (live weight sale)", enterprise="Pigs",
                                             group_id=G["oldfat"].id, heads_sold=15, quantity=15, unit="pigs", unit_price=27_500)])
    invoice(63, "Ruiru Pork Butchery", [dict(description="Finished pigs (live weight sale)", enterprise="Pigs",
                                             group_id=G["oldfat"].id, heads_sold=14, quantity=14, unit="pigs", unit_price=28_000)],
            paid=0.6, terms=30)
    invoice(30, "Juja Wholesalers", [dict(description="Bagged pig manure", enterprise="Pigs", quantity=60, unit="bags",
                                          unit_price=150)], paid=0.0, terms=14)
    invoice(20, "Thika Road Hotel", [dict(description="Spent kienyeji hens", enterprise="Kienyeji Poultry",
                                          group_id=G["kienyeji"].id, heads_sold=20, quantity=20, unit="birds",
                                          unit_price=900)], paid=0.0, terms=10)

    # ------------------------------------------------------------ expenses
    for m in range(4):
        base = 30 * m + 3
        for cat, ent, desc, amt, payee in [
            ("Utilities (power & water)", "General", "KPLC electricity", 18_500 + m * 700, "KPLC"),
            ("Utilities (power & water)", "General", "Water bill", 4_200, "Ruiru Water Co."),
            ("Transport", "Layers", "Egg deliveries – fuel", 6_800, "Driver"),
            ("Security", "General", "Night security top-up", 3_000, "Guard"),
        ]:
            db.session.add(Expense(date=ago(base), category=cat, enterprise=ent, description=desc, amount=amt,
                                   payee=payee, payment_method="M-Pesa"))
    db.session.add(Expense(date=ago(50), category="Repairs & maintenance", enterprise="Pigs", description="Pen B floor repair",
                           amount=14_500, payee="Fundi Joseph", payment_method="Cash"))
    db.session.add(Expense(date=ago(33), category="Licences & permits", enterprise="General", description="County trade licence",
                           amount=7_500, payee="Kiambu County", payment_method="Bank transfer"))
    db.session.add(Expense(date=ago(12), category="Transport", enterprise="Pigs", description="Transport of pigs to butchery",
                           amount=5_000, payee="Lorry hire", payment_method="M-Pesa"))

    # ------------------------------------------------------------ staff
    E = []
    for no, name, pos, ent, basis, sal, daily, house in [
        ("ZF001", "Joseph Mwangi", "Farm manager", "General", "Monthly", 55_000, 0, 8_000),
        ("ZF002", "Grace Wanjiru", "Poultry attendant", "Layers", "Monthly", 18_000, 0, 2_000),
        ("ZF003", "Samuel Kiprono", "Pig attendant", "Pigs", "Monthly", 18_000, 0, 2_000),
        ("ZF004", "Mercy Achieng", "Pig attendant", "Pigs", "Monthly", 17_000, 0, 2_000),
        ("ZF005", "Peter Kamau", "Feed mill operator", "Feed Mill", "Daily", 0, 750, 0),
        ("ZF006", "David Ouma", "Broiler attendant", "Broilers", "Monthly", 16_500, 0, 1_500),
        ("ZF007", "John Njoroge", "Night guard", "General", "Monthly", 16_000, 0, 0),
    ]:
        E.append(save(Employee(staff_no=no, name=name, position=pos, enterprise=ent, pay_basis=basis, basic_salary=sal,
                               daily_rate=daily, house_allowance=house, employment_type="Permanent",
                               phone=f"07{random.randint(10000000, 99999999)}", date_joined=ago(random.randint(200, 900)),
                               account_details="M-Pesa")))
    for d in range(75, -1, -1):
        day = ago(d)
        if day.weekday() == 6:
            continue
        for e in E:
            r = random.random()
            status = "Present" if r < 0.9 else "Half day" if r < 0.95 else "Absent" if r < 0.98 else "Sick"
            db.session.add(Attendance(employee_id=e.id, date=day, status=status,
                                      overtime_hours=2 if (e.position == "Feed mill operator" and day.weekday() == 5) else 0))
    db.session.flush()

    from .views.payroll_views import fill_payslip
    first = T.replace(day=1)
    for back, status in [(2, "Paid"), (1, "Paid")]:
        m = first.month - back
        y = first.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        run = save(PayrollRun(period=f"{y}-{m:02d}", status=status, paid_on=date(y, m, 28)))
        for e in E:
            s = Payslip(run=run, employee=e, advances=2_000 if e.name == "Samuel Kiprono" and back == 1 else 0)
            db.session.add(s)
            fill_payslip(s)

    for d, who, task, ent, days, rate in [(64, "Kevin Mutua", "Offloading maize germ & bran", "Feed Mill", 1, 700),
                                          (50, "Kevin Mutua", "Pen B floor repair helper", "Pigs", 2, 700),
                                          (30, "Lucy Wairimu", "Cleaning broiler house 2 after batch 06", "Broilers", 3, 650),
                                          (6, "Kevin Mutua", "Grading & packing eggs", "Layers", 2, 650),
                                          (2, "Lucy Wairimu", "Cutting napier & cleaning", "Pigs", 1, 650)]:
        db.session.add(CasualLabour(date=ago(d), worker_name=who, task=task, enterprise=ent, days=days, rate=rate, paid=d > 5))

    # ------------------------------------------------------------ tasks & a stock request
    for title, due, emp, ent, pri, status in [
        ("Order 2 tonnes of layers mash", 0, E[0], "Layers", "High", "Open"),
        ("Book buyer for Fatteners Pen B (34 pigs)", 2, E[0], "Pigs", "High", "Open"),
        ("Prepare farrowing crate for Baraka (S-002)", 1, E[2], "Pigs", "Normal", "In progress"),
        ("Clean and disinfect broiler house 2 after Batch 07", 8, E[5], "Broilers", "Normal", "Open"),
        ("Collect payment from Ruiru Pork Butchery", -3, E[0], "Pigs", "High", "Open"),
        ("Service feed mill hammer screen", 5, E[4], "Feed Mill", "Low", "Open"),
    ]:
        db.session.add(Task(title=title, due_date=T + timedelta(days=due), assigned_to_id=emp.id, enterprise=ent,
                            priority=pri, status=status))
    req = save(StockRequest(
        item_id=item["Broiler finisher pellets"].id, group_id=G["b07"].id, enterprise="Broilers", requested_by="David Ouma",
        qty_requested=150, request_date=T, needed_by=T + timedelta(days=1), status="Pending"))
    R._request_save(req, True)

    db.session.commit()
    print("Seeded demo farm.")
