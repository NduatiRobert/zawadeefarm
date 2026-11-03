"""Every register in the system, declared once."""
from datetime import date, timedelta

from flask import url_for
from sqlalchemy import func

from . import constants as K
from . import ledger
from . import settings as S
from .crud import C, F, Lines, Resource
from .extensions import db
from .models import (
    Activity, Animal, Attendance, Breeding, Buyer, CasualLabour, Employee, Expense, FeedBatch, FeedFormula,
    FeedFormulaLine, InvoiceLine, Invoice, LivestockGroup, Payment, Production, Purchase, PurchaseLine,
    StockItem, StockMovement, StockRequest, StockUsage, Supplier, Task, WeightRecord,
)


def get(model, id):
    return db.session.get(model, id) if id else None


def tile(label, value, tone="success", fmt="money", icon=None):
    return dict(label=label, value=value, tone=tone, fmt=fmt, icon=icon)


def month_start():
    return date.today().replace(day=1)


# Reusable foreign-key fields ------------------------------------------------
def fk_group(name="group_id", label="Herd / flock group", required=False, active_only=True):
    return F(name, label, "fk", required=required,
             fk=(LivestockGroup, lambda g: f"{g.name} · {g.animal_type} ({g.current_count})",
                 lambda q: q.order_by(LivestockGroup.status, LivestockGroup.name)))


def fk_item(name="item_id", label="Store item", required=True, categories=None):
    def q(query):
        if categories:
            query = query.filter(StockItem.category.in_(categories))
        return query.order_by(StockItem.name)
    return F(name, label, "fk", required=required,
             fk=(StockItem, lambda i: f"{i.name} – {i.quantity:g} {i.unit} in store", q))


def fk_animal(name, label, required=False, sex=None):
    def q(query):
        query = query.filter(Animal.status == "Active")
        if sex:
            query = query.filter(Animal.sex.in_(sex))
        return query.order_by(Animal.tag_number)
    return F(name, label, "fk", required=required, fk=(Animal, lambda a: f"{a} · {a.animal_type}", q))


def fk_employee(name="employee_id", label="Employee", required=True):
    return F(name, label, "fk", required=required,
             fk=(Employee, None, lambda q: q.filter(Employee.status != "Terminated").order_by(Employee.name)))


ENT = lambda default="General": F("enterprise", "Enterprise", "select", choices=K.ENTERPRISES, default=default)  # noqa: E731


# =========================================================================== STORE
Resource(
    "suppliers", Supplier, "Supplier Directory", "Supplier", "store", "/store/suppliers", icon="shop",
    fields=[
        F("name", "Name", required=True), F("phone", "Phone"), F("email", "Email", "email"),
        F("supplier_type", "Supplier type", "select", choices=K.SUPPLIER_TYPES),
        F("location", "Location"), F("notes", "Notes", "textarea", col=12),
    ],
    columns=["name", "phone", "supplier_type", "location",
             C("Balance owed", lambda s: sum(p.balance for p in s.purchases), "money")],
    filters=["supplier_type"], search=["name", "phone", "location"], order_by=Supplier.name,
)


def _items_stats(args):
    items = StockItem.query.all()
    return [
        tile("Current stock value", sum(i.value for i in items), icon="box-seam"),
        tile("Items in store", len(items), "primary", "int", "basket"),
        tile("Low-stock alerts", sum(1 for i in items if i.is_low), "danger", "int", "exclamation-triangle"),
        tile("Feed in store (kg)", sum(i.quantity for i in items if i.category == "Feed" and i.unit == "kg"),
             "warning", "number", "bucket"),
    ]


Resource(
    "items", StockItem, "Store", "Store item", "store", "/store/items", icon="basket",
    fields=[
        F("name", "Item name", required=True),
        F("category", "Category", "select", choices=K.STOCK_CATEGORIES, required=True),
        F("unit", "Unit of measure", "select", choices=K.UNITS, default="kg"),
        F("reorder_level", "Re-order level", "number", help="You get a low-stock alert at or below this quantity."),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=["name", "category", C("Stock balance", lambda i: i.quantity, "number"), "unit",
             C("Avg unit cost", lambda i: i.avg_cost, "money"), C("Stock value", lambda i: i.value, "money"),
             C("Re-order at", lambda i: i.reorder_level, "number"),
             C("Status", lambda i: "Low stock" if i.is_low else "OK", "badge")],
    filters=["category"], search=["name"], order_by=lambda m: (m.category, m.name), stats=_items_stats,
    note="Stock balances come from purchases, usage, feed milling and adjustments. Use “Adjust” on a row to "
         "enter opening stock or correct a physical count.",
    actions=[("Input Purchases", "receipt", lambda: url_for("crud.purchases_list")),
             ("Stock Ledger", "journal-text", lambda: url_for("pages.stock_ledger"))],
    row_actions=[("History", "clock-history", lambda o: url_for("pages.item_history", id=o.id)),
                 ("Adjust", "sliders", lambda o: url_for("pages.item_adjust", id=o.id))],
)


def _purchase_save(p, is_new):
    ref = f"purchase:{p.id}"
    ledger.reverse(ref)
    for l in p.lines:
        ledger.stock_in(l.item_id, l.quantity, l.unit_price, ref, p.date, "purchase", f"From {get(Supplier, p.supplier_id) or 'supplier'}")
    if (p.amount_paid or 0) > p.total + 0.005:
        raise ValueError("Amount paid cannot be more than the purchase total.")


def _purchase_stats(args):
    from .crud import REGISTRY
    rows = REGISTRY["purchases"].query(args).all()
    return [
        tile("Total purchases", sum(p.total for p in rows)),
        tile("Amount paid", sum(p.amount_paid or 0 for p in rows)),
        tile("Outstanding balance", sum(p.balance for p in rows), "danger"),
        tile("Overdue credit purchases", sum(1 for p in rows if p.status == "Overdue"), "warning", "int"),
    ]


Resource(
    "purchases", Purchase, "Input Purchases", "Purchase", "store", "/store/purchases", icon="receipt",
    fields=[
        F("supplier_id", "Supplier", "fk", required=True, fk=(Supplier, None, lambda q: q.order_by(Supplier.name))),
        F("date", "Purchase date", "date", required=True, default=date.today, col=3),
        F("due_date", "Payment due", "date", col=3, help="Leave blank for cash purchases."),
        F("reference", "Supplier invoice / receipt no."),
        F("amount_paid", "Amount paid", "money", col=3),
        F("payment_method", "Payment method", "select", choices=K.PAYMENT_METHODS, col=3),
        F("notes", "Notes", "textarea", col=12),
    ],
    lines=Lines(PurchaseLine, "lines", [
        fk_item(label="Item"),
        F("quantity", "Quantity", "number", required=True, step="any"),
        F("unit_price", "Unit price", "money", required=True),
    ], title="Items received", total=("quantity", "unit_price")),
    columns=[C("Purchase", lambda p: str(p)), "date", "supplier_id", "reference",
             C("Items", lambda p: ", ".join(l.item.name for l in p.lines if l.item)),
             C("Total", lambda p: p.total, "money"), C("Paid", lambda p: p.amount_paid, "money"),
             C("Balance", lambda p: p.balance, "money"), "due_date", C("Status", lambda p: p.status, "badge")],
    filters=["supplier_id"], date_field="date", search=["reference"],
    order_by=lambda m: (m.date.desc(), m.id.desc()), on_save=_purchase_save,
    on_delete=lambda p: ledger.reverse(f"purchase:{p.id}"), stats=_purchase_stats, form_title="New Purchase",
    note="Received items go straight into the store at the price paid. They count as a cost when they are used.",
)


def _request_save(r, is_new):
    ref = f"request:{r.id}"
    ledger.reverse(ref)
    if r.status == "Issued":
        if not r.qty_issued:
            r.qty_issued = r.qty_requested
        ledger.stock_out(r.item_id, r.qty_issued, ref, date.today(), "usage", group=get(LivestockGroup, r.group_id),
                         enterprise=r.enterprise, notes=f"Stock request {r.number}")
    elif r.status != "Issued":
        r.qty_issued = 0 if r.status in ("Pending", "Rejected") else r.qty_issued


Resource(
    "requests", StockRequest, "Stock Requests", "Stock request", "store", "/store/requests", icon="clipboard-check",
    fields=[
        fk_item(), fk_group(label="For group (flock / pen)"), ENT(),
        F("requested_by", "Requested by"),
        F("qty_requested", "Quantity requested", "number", required=True, col=3),
        F("qty_issued", "Quantity issued", "number", col=3, help="Filled when issued; defaults to quantity requested."),
        F("request_date", "Request date", "date", default=date.today, col=3),
        F("needed_by", "Needed by", "date", col=3),
        F("status", "Status", "select", choices=K.REQUEST_STATUSES, default="Pending",
          help="Setting status to Issued takes the stock out of the store and charges it to the group."),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=[C("Request #", lambda r: r.number), "item_id", "group_id", "enterprise", "requested_by",
             "qty_requested", "qty_issued", "request_date", "needed_by", "status"],
    filters=["status", "enterprise", "item_id"], date_field="request_date", search=["requested_by"],
    on_save=_request_save, on_delete=lambda r: ledger.reverse(f"request:{r.id}"),
)


def _usage_save(u, is_new):
    ref = f"usage:{u.id}"
    ledger.reverse(ref)
    group = get(LivestockGroup, u.group_id)
    if group and not u.enterprise:
        u.enterprise = group.ent
    ledger.stock_out(u.item_id, u.quantity, ref, u.date, "usage", group=group, enterprise=u.enterprise,
                     notes=u.purpose)


Resource(
    "usage", StockUsage, "Input Usage", "Usage record", "store", "/store/usage", icon="box-arrow-up",
    fields=[
        F("date", "Date", "date", default=date.today, required=True, col=4), fk_item(),
        F("quantity", "Quantity used", "number", required=True, col=4),
        fk_group(label="Used on group"), F("enterprise", "Enterprise", "select", choices=K.ENTERPRISES,
                                           help="Leave blank to use the group's enterprise."),
        F("purpose", "Purpose", help="e.g. Daily feeding, bedding, disinfection"), F("issued_by", "Issued by"),
    ],
    columns=["date", "item_id", "quantity", C("Unit", lambda u: u.item.unit if u.item else ""), "group_id",
             "enterprise", "purpose", C("Cost", lambda u: u.cost, "money"), "issued_by"],
    filters=["item_id", "group_id", "enterprise"], date_field="date", search=["purpose", "issued_by"],
    order_by=lambda m: (m.date.desc(), m.id.desc()), on_save=_usage_save,
    on_delete=lambda u: ledger.reverse(f"usage:{u.id}"),
    note="Each usage takes stock out at the average cost and charges it to the group's enterprise. "
         "That cost shows up in profit and loss.",
)

# =========================================================================== FEED MILL
Resource(
    "formulas", FeedFormula, "Feed Formulas", "Feed formula", "feed", "/feed/formulas", icon="journal-richtext",
    fields=[
        F("name", "Formula name", required=True, help="e.g. Sow & Weaner Meal, Layers Mash"),
        ENT("Pigs"),
        fk_item("output_item_id", "Finished feed item (in store)", categories=["Feed"]),
        F("notes", "Notes / mixing instructions", "textarea", col=12),
    ],
    lines=Lines(FeedFormulaLine, "lines", [
        fk_item(label="Ingredient", categories=["Feed Ingredient", "Supplement", "Medicine", "Feed"]),
        F("quantity", "Kg per batch", "number", required=True, step="any"),
    ], title="Ingredients per batch"),
    columns=["name", "enterprise", "output_item_id", C("Batch size (kg)", lambda f: f.batch_size, "number"),
             C("Est. cost / batch", lambda f: f.est_cost, "money"),
             C("Est. cost / kg", lambda f: f.est_cost_per_kg, "money")],
    filters=["enterprise"], search=["name"], order_by=FeedFormula.name,
    actions=[("Produce batch", "gear-wide-connected", lambda: url_for("crud.batches_new"))],
    note="Estimated costs use the current average cost of each ingredient in store.",
)


def _batch_save(b, is_new):
    ref = f"mill:{b.id}"
    ledger.reverse(ref)
    f = get(FeedFormula, b.formula_id)
    if not f.lines:
        raise ValueError("This formula has no ingredients.")
    total = 0.0
    for l in f.lines:
        m = ledger.stock_out(l.item_id, (l.quantity or 0) * (b.batches or 0), ref, b.date, "mill_out",
                             enterprise="Feed Mill", notes=f"Milled into {f.name}")
        total += -(m.total_cost if m else 0)
    if not b.output_qty:
        b.output_qty = round(f.batch_size * (b.batches or 0), 2)
    b.total_cost = round(total, 2)
    ledger.stock_in(f.output_item_id, b.output_qty, total / b.output_qty if b.output_qty else 0, ref, b.date,
                    "mill_in", f"Batch {b.number}")


Resource(
    "batches", FeedBatch, "Feed Production", "Production batch", "feed", "/feed/batches", icon="gear-wide-connected",
    fields=[
        F("date", "Production date", "date", default=date.today, required=True, col=4),
        F("formula_id", "Formula", "fk", required=True, fk=(FeedFormula, None, lambda q: q.order_by(FeedFormula.name))),
        F("batches", "Number of batches", "number", default=1, required=True, col=4, step="any"),
        F("output_qty", "Actual output (kg)", "number", col=4,
          help="Leave blank to use the formula batch size × batches. Enter the weighed output to capture milling loss."),
        F("produced_by", "Produced by", col=4),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=[C("Batch", lambda b: b.number), "date", "formula_id", "batches", "output_qty",
             C("Ingredient cost", lambda b: b.total_cost, "money"), C("Cost / kg", lambda b: b.cost_per_unit, "money"),
             "produced_by"],
    filters=["formula_id"], date_field="date", order_by=lambda m: (m.date.desc(), m.id.desc()),
    on_save=_batch_save, on_delete=lambda b: ledger.reverse(f"mill:{b.id}"),
    note="Saving a batch takes the ingredients out of the store and adds the finished feed at its true cost per kg.",
)

# =========================================================================== LIVESTOCK
def _group_save(g, is_new):
    if not g.enterprise:
        g.enterprise = K.ANIMAL_ENTERPRISE.get(g.animal_type, "General")
    ledger.recalc_group(g.id)


def _group_stats(args):
    groups = LivestockGroup.query.filter_by(status="Active").all()
    pigs = sum(g.current_count for g in groups if g.animal_type == "Pig")
    birds = sum(g.current_count for g in groups if g.animal_type in K.POULTRY_TYPES)
    return [
        tile("Active groups", len(groups), "success", "int", "collection"),
        tile("Pigs on farm", pigs, "warning", "int", "piggy-bank"),
        tile("Birds on farm", birds, "primary", "int", "egg"),
        tile("Other animals", sum(g.current_count for g in groups) - pigs - birds, "secondary", "int", "heart-pulse"),
    ]


Resource(
    "groups", LivestockGroup, "Herd / Flock Groups", "Group", "livestock", "/livestock/groups", icon="collection",
    fields=[
        F("name", "Group name", required=True, help="e.g. Layers House 1, Fatteners Pen 3, Sows"),
        F("animal_type", "Animal type", "select", choices=K.ANIMAL_TYPES, required=True),
        F("enterprise", "Enterprise", "select", choices=K.ENTERPRISES, help="Defaults from the animal type."),
        F("purpose", "Purpose", "select", choices=K.GROUP_PURPOSES), F("breed", "Breed / strain"),
        F("opening_count", "Number placed (opening count)", "int", required=True,
          help="Head count when the group was set up. Deaths, births and sales adjust the current count automatically."),
        F("placement_date", "Placement date", "date", default=date.today, col=3),
        F("target_market_date", "Target market date", "date", col=3),
        F("acquisition_cost", "Acquisition cost (chicks / piglets bought)", "money"),
        F("location", "Location / pen / house"),
        F("status", "Status", "select", choices=K.GROUP_STATUSES, default="Active"),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=[C("Group name", lambda g: g.name), "animal_type", "purpose", "opening_count",
             C("Current count", lambda g: g.current_count, "int"), "placement_date",
             C("Age (wks)", lambda g: g.age_weeks, "int"), "target_market_date", "location", "status"],
    filters=["animal_type", "status", "enterprise"], search=["name", "location", "breed"],
    order_by=lambda m: (m.status, m.name), on_save=_group_save, stats=_group_stats,
    row_actions=[("Open", "eye", lambda o: url_for("pages.group_detail", id=o.id))],
    after_save_url=lambda g: url_for("pages.group_detail", id=g.id),
)

Resource(
    "animals", Animal, "Livestock Records", "Animal", "livestock", "/livestock/animals", icon="tag",
    fields=[
        F("tag_number", "Tag / ear number", required=True), F("name", "Name"),
        F("animal_type", "Animal type", "select", choices=K.ANIMAL_TYPES, required=True, default="Pig"),
        fk_group(), F("breed", "Breed"), F("sex", "Sex", "select", choices=K.SEXES),
        F("date_of_birth", "Date of birth", "date", col=3), F("acquired_on", "Acquired on", "date", col=3),
        F("source", "Source", "select", choices=["Born on farm", "Purchased", "Gift / transfer"]),
        F("purchase_cost", "Purchase cost", "money", help="Leave blank if already included in the group's acquisition cost."),
        F("current_weight", "Current weight (kg)", "number"),
        F("status", "Status", "select", choices=K.ANIMAL_STATUSES, default="Active"),
        F("breeding_status", "Breeding status", "select", choices=K.BREEDING_STATUSES, default="Not applicable"),
        F("dam_id", "Dam (mother)", "fk", fk=(Animal, None, lambda q: q.filter(Animal.sex == "Female").order_by(Animal.tag_number))),
        F("sire_id", "Sire (father)", "fk", fk=(Animal, None, lambda q: q.filter(Animal.sex == "Male").order_by(Animal.tag_number))),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=["group_id", "tag_number", "name", "animal_type", "breed", "sex", "acquired_on", "purchase_cost",
             "current_weight", "status", "breeding_status", C("Offspring", lambda a: a.offspring_count, "int")],
    filters=["animal_type", "sex", "status", "breeding_status", "group_id"], search=["tag_number", "name", "breed"],
    order_by=lambda m: (m.status, m.tag_number),
    note="Register breeding stock (sows, boars, cows, does) individually. Flocks and fattener batches are "
         "tracked by head count in Groups.",
)


def _activity_save(a, is_new):
    ref = f"activity:{a.id}"
    ledger.reverse(ref)
    animal = get(Animal, a.animal_id)
    if animal and not a.group_id:
        a.group_id = animal.group_id
    group = get(LivestockGroup, a.group_id)
    if animal and not a.affected_count:
        a.affected_count = 1
    if a.stock_item_id and a.quantity_used:
        ent = group.ent if group else (K.ANIMAL_ENTERPRISE.get(animal.animal_type) if animal else "General")
        ledger.stock_out(a.stock_item_id, a.quantity_used, ref, a.date, "usage", group=group, enterprise=ent,
                         notes=f"{a.activity_type}: {a.description or ''}")
    if a.activity_type in ("Mortality", "Culling") and a.affected_count:
        kind = "death" if a.activity_type == "Mortality" else "cull"
        if group:
            ledger.head_change(group.id, -a.affected_count, kind, ref, a.date, a.description)
        if animal:
            animal.status = "Dead" if kind == "death" else "Culled"


Resource(
    "activities", Activity, "Livestock Activities", "Activity", "livestock", "/livestock/activities", icon="heart-pulse",
    fields=[
        F("date", "Activity date", "date", default=date.today, required=True, col=3),
        F("activity_type", "Activity type", "select", choices=K.ACTIVITY_TYPES, required=True, col=3),
        fk_group(), fk_animal("animal_id", "Individual animal (optional)"),
        F("affected_count", "Affected count", "int", col=3, help="For Mortality/Culling this reduces the group count."),
        fk_item("stock_item_id", "Store stock item used", required=False),
        F("quantity_used", "Quantity used from store", "number", col=3, step="any"),
        F("description", "Description", col=6, help="e.g. Newcastle (Lasota) – drinking water; cause of death"),
        F("cost", "Extra cash cost (vet fee etc.)", "money", col=3,
          help="Counted as a veterinary cost in profit and loss, so do not also enter it as an expense."),
        F("next_due_date", "Next due date / follow-up", "date", col=3),
        F("follow_up_done", "Follow-up done", "bool", col=3),
        F("performed_by", "Performed by", col=3),
    ],
    columns=["animal_id", "group_id", "date", "activity_type", "affected_count", "stock_item_id", "quantity_used",
             "description", "cost", "next_due_date", "follow_up_done"],
    filters=["activity_type", "group_id"], date_field="date", search=["description", "performed_by"],
    order_by=lambda m: (m.date.desc(), m.id.desc()), on_save=_activity_save,
    on_delete=lambda a: ledger.reverse(f"activity:{a.id}"),
)


def _breeding_save(b, is_new):
    ref = f"breeding:{b.id}"
    ledger.reverse(ref)
    female = get(Animal, b.female_id)
    if not b.expected_date and b.service_date and female:
        days = K.GESTATION_DAYS.get(female.animal_type)
        if days:
            b.expected_date = b.service_date + timedelta(days=days)
    female.breeding_status = {"Served": "Served", "Pregnant": "Pregnant", "Delivered": "Lactating",
                              "Weaned": "Weaned", "Failed": "Open"}.get(b.status, female.breeding_status)
    if b.status in ("Delivered", "Weaned") and not b.actual_date:
        b.actual_date = date.today()
    if b.litter_group_id and b.born_alive:
        ledger.head_change(b.litter_group_id, b.born_alive, "birth", ref, b.actual_date or b.service_date,
                           f"Born to {female}")
        if b.weaned_count is not None and b.weaned_count < b.born_alive:
            ledger.head_change(b.litter_group_id, b.weaned_count - b.born_alive, "death", ref,
                               b.weaning_date or b.actual_date, "Pre-weaning losses")


Resource(
    "breeding", Breeding, "Breeding & Farrowing", "Breeding record", "livestock", "/livestock/breeding",
    icon="gender-ambiguous",
    fields=[
        fk_animal("female_id", "Sow / dam", required=True, sex=["Female"]),
        fk_animal("male_id", "Boar / sire", sex=["Male"]),
        F("method", "Method", "select", choices=["Natural", "AI"], default="Natural", col=3),
        F("service_date", "Service date", "date", default=date.today, required=True, col=3),
        F("expected_date", "Expected farrowing / birth", "date", col=3,
          help="Auto-calculated (pigs 114 days) if left blank."),
        F("status", "Status", "select", choices=["Served", "Pregnant", "Delivered", "Weaned", "Failed"], default="Served", col=3),
        F("actual_date", "Actual farrowing date", "date", col=3),
        F("born_alive", "Born alive", "int", col=3), F("stillborn", "Stillborn", "int", col=3),
        F("litter_group_id", "Add piglets to group", "fk",
          fk=(LivestockGroup, None, lambda q: q.filter(LivestockGroup.status == "Active").order_by(LivestockGroup.name)),
          help="Live births are added to this group's head count."),
        F("weaned_count", "Weaned count", "int", col=3), F("weaning_date", "Weaning date", "date", col=3),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=["female_id", "male_id", "method", "service_date", "expected_date", "actual_date", "born_alive",
             "stillborn", "weaned_count",
             C("Pre-wean loss %", lambda b: round((b.born_alive - b.weaned_count) * 100 / b.born_alive, 1)
               if b.born_alive and b.weaned_count is not None else None, "number"), "status"],
    filters=["status"], date_field="service_date", order_by=lambda m: (m.expected_date.desc(), m.id.desc()),
    on_save=_breeding_save, on_delete=lambda b: ledger.reverse(f"breeding:{b.id}"),
)


def _prod_stats(args):
    from .crud import REGISTRY
    rows = REGISTRY["production"].query(args).all()
    eggs = sum(r.quantity for r in rows if r.product == "Eggs")
    per_tray = S.get_float("eggs_per_tray") or 30
    return [
        tile("Eggs (filtered)", eggs, "warning", "int", "egg"),
        tile("Egg trays", eggs / per_tray, "success", "number", "grid-3x3-gap"),
        tile("Milk (litres)", sum(r.quantity for r in rows if r.product == "Milk"), "primary", "number", "droplet"),
        tile("Production value", sum(r.value for r in rows), "success", "money", "cash-stack"),
    ]


Resource(
    "production", Production, "Livestock Production", "Production record", "livestock", "/livestock/production",
    icon="droplet",
    fields=[
        F("date", "Date", "date", default=date.today, required=True, col=3), fk_group(required=True),
        F("product", "Product", "select", choices=K.PRODUCTS, default="Eggs", col=3),
        F("grade", "Grade", "select", choices=K.EGG_GRADES, col=3),
        F("quantity", "Quantity (eggs / litres / bags)", "number", required=True, col=3),
        F("unit_value", "Value per unit", "money", col=3, help="Estimated farm-gate price, e.g. KES 15 per egg."),
        F("recorded_by", "Recorded by", col=3), F("notes", "Notes", col=6),
    ],
    columns=["date", "group_id", "product", "grade", "quantity",
             C("Trays", lambda p: p.trays, "number"), "unit_value", C("Value", lambda p: p.value, "money"), "recorded_by"],
    filters=["product", "group_id", "grade"], date_field="date", order_by=lambda m: (m.date.desc(), m.id.desc()),
    stats=_prod_stats,
)

Resource(
    "weights", WeightRecord, "Weight Records", "Weight record", "livestock", "/livestock/weights", icon="speedometer",
    fields=[
        F("date", "Date weighed", "date", default=date.today, required=True, col=3), fk_group(),
        fk_animal("animal_id", "Individual animal"),
        F("sample_size", "Animals weighed", "int", default=1, col=3),
        F("avg_weight", "Average weight (kg)", "number", required=True, col=3, step="any"),
        F("notes", "Notes", col=12),
    ],
    columns=["date", "group_id", "animal_id", "sample_size", "avg_weight", "notes"],
    filters=["group_id"], date_field="date", order_by=lambda m: (m.date.desc(), m.id.desc()),
    on_save=lambda w, n: setattr(get(Animal, w.animal_id), "current_weight", w.avg_weight) if w.animal_id else None,
    note="Regular weighing gives you average daily gain and feed conversion (FCR) on the group page.",
)

# =========================================================================== SALES & ACCOUNTS
Resource(
    "buyers", Buyer, "Buyer Directory", "Buyer", "sales", "/sales/buyers", icon="person-check",
    fields=[
        F("name", "Name", required=True), F("phone", "Phone"), F("email", "Email", "email"),
        F("buyer_type", "Buyer type", "select", choices=K.BUYER_TYPES), F("location", "Location"),
        F("kra_pin", "KRA PIN"), F("notes", "Notes", "textarea", col=12),
    ],
    columns=["name", "phone", "buyer_type", "location",
             C("Balance due", lambda b: sum(i.balance for i in b.invoices), "money")],
    filters=["buyer_type"], search=["name", "phone", "location"], order_by=Buyer.name,
)


def _invoice_save(inv, is_new):
    ref = f"invoice:{inv.id}"
    ledger.reverse(ref)
    if not inv.due_date:
        inv.due_date = inv.date + timedelta(days=int(S.get_float("invoice_terms_days")))
    for l in inv.lines:
        if not l.group_id:
            l.enterprise = l.enterprise or "General"
        else:
            g = db.session.get(LivestockGroup, l.group_id)
            if not l.enterprise:
                l.enterprise = g.ent
            if l.heads_sold:
                if l.heads_sold > g.current_count:
                    raise ValueError(f"{g.name} only has {g.current_count} head; cannot sell {l.heads_sold}.")
                ledger.head_change(g.id, -l.heads_sold, "sale", ref, inv.date, f"Sold on {inv.number}")


def _invoice_stats(args):
    from .crud import REGISTRY
    rows = REGISTRY["invoices"].query(args).all()
    return [
        tile("Total invoiced", sum(i.total for i in rows)),
        tile("Received", sum(i.paid for i in rows)),
        tile("Outstanding", sum(i.balance for i in rows), "danger"),
        tile("Overdue invoices", sum(1 for i in rows if i.status == "Overdue"), "warning", "int"),
    ]


Resource(
    "invoices", Invoice, "Buyer Invoices", "Invoice", "sales", "/sales/invoices", icon="file-earmark-text",
    fields=[
        F("buyer_id", "Buyer", "fk", required=True, fk=(Buyer, None, lambda q: q.order_by(Buyer.name))),
        F("date", "Invoice date", "date", default=date.today, required=True, col=3),
        F("due_date", "Due date", "date", col=3, help="Defaults to the invoice terms in Settings."),
        F("notes", "Notes shown on invoice", "textarea", col=12),
    ],
    lines=Lines(InvoiceLine, "lines", [
        F("description", "Description", required=True, help="e.g. Live pigs, Pork, Eggs (trays)"),
        F("enterprise", "Enterprise", "select", choices=K.ENTERPRISES, help="Blank = the group's enterprise"),
        fk_group(label="From group"),
        F("heads_sold", "Live heads sold", "int"),
        F("quantity", "Qty", "number", required=True, step="any"),
        F("unit", "Unit"),
        F("unit_price", "Unit price", "money", required=True),
    ], title="Invoice lines", total=("quantity", "unit_price")),
    columns=[C("Invoice", lambda i: i.number), "date", "buyer_id",
             C("Items", lambda i: ", ".join(l.description for l in i.lines)),
             C("Total", lambda i: i.total, "money"), C("Paid", lambda i: i.paid, "money"),
             C("Balance", lambda i: i.balance, "money"), "due_date", C("Status", lambda i: i.status, "badge")],
    filters=["buyer_id"], date_field="date", order_by=lambda m: (m.date.desc(), m.id.desc()),
    on_save=_invoice_save, on_delete=lambda i: ledger.reverse(f"invoice:{i.id}"), stats=_invoice_stats,
    row_actions=[("View / Print", "printer", lambda o: url_for("pages.invoice_view", id=o.id))],
    after_save_url=lambda i: url_for("pages.invoice_view", id=i.id),
    note="To sell live animals, choose the group and enter the heads sold. The group's count drops automatically.",
)

Resource(
    "payments", Payment, "Payments Received", "Payment", "sales", "/sales/payments", icon="cash-coin",
    fields=[
        F("invoice_id", "Invoice", "fk", required=True, fk=(Invoice, lambda i: f"{i} · bal {i.balance:,.2f}",
                                                            lambda q: q.order_by(Invoice.id.desc()))),
        F("date", "Date received", "date", default=date.today, required=True, col=3),
        F("amount", "Amount", "money", required=True, col=3),
        F("method", "Method", "select", choices=K.PAYMENT_METHODS, default="M-Pesa", col=3),
        F("reference", "Reference (M-Pesa code)", col=3),
    ],
    columns=["date", "invoice_id", C("Buyer", lambda p: p.invoice.buyer), "amount", "method", "reference"],
    filters=["method"], date_field="date", search=["reference"], order_by=lambda m: (m.date.desc(), m.id.desc()),
)


def _expense_stats(args):
    from .crud import REGISTRY
    rows = REGISTRY["expenses"].query(args).all()
    ms = month_start()
    month = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(Expense.date >= ms).scalar()
    by_cat = {}
    for r in rows:
        by_cat[r.category] = by_cat.get(r.category, 0) + (r.amount or 0)
    top = max(by_cat.items(), key=lambda kv: kv[1]) if by_cat else ("–", 0)
    return [
        tile("Expenses (filtered)", sum(r.amount or 0 for r in rows), "danger"),
        tile("This month", month, "warning"),
        tile("Biggest category", top[0], "secondary", "text"),
        tile("Records", len(rows), "primary", "int"),
    ]


Resource(
    "expenses", Expense, "Expenses", "Expense", "sales", "/sales/expenses", icon="arrow-down-circle",
    fields=[
        F("date", "Date", "date", default=date.today, required=True, col=3),
        F("category", "Category", "select", choices=K.EXPENSE_CATEGORIES, required=True, col=3), ENT(),
        F("description", "Description", col=12), F("amount", "Amount", "money", required=True, col=3),
        F("payee", "Paid to", col=3), F("payment_method", "Method", "select", choices=K.PAYMENT_METHODS, col=3),
        F("reference", "Reference", col=3),
    ],
    columns=["date", "category", "enterprise", "description", "payee", "payment_method", "reference", "amount"],
    filters=["category", "enterprise", "payment_method"], date_field="date", search=["description", "payee", "reference"],
    order_by=lambda m: (m.date.desc(), m.id.desc()), stats=_expense_stats,
    note="Record running costs here. Leave out feed and drugs bought into the store (they are costed when used) "
         "and staff salaries (they come from payroll).",
)

# =========================================================================== STAFF
Resource(
    "employees", Employee, "Employees", "Employee", "staff", "/staff/employees", icon="people",
    fields=[
        F("staff_no", "Staff no.", col=3), F("name", "Full name", required=True, col=5),
        F("phone", "Phone", col=4), F("national_id", "National ID", col=3), F("kra_pin", "KRA PIN", col=3),
        F("nssf_no", "NSSF no.", col=3), F("shif_no", "SHA / SHIF no.", col=3),
        F("position", "Position", col=4, help="e.g. Pig attendant, Poultry attendant, Feed mill operator"),
        F("enterprise", "Works in", "select", choices=K.ENTERPRISES, default="General", col=4,
          help="Salary is charged to this enterprise in profit and loss."),
        F("employment_type", "Employment type", "select", choices=K.EMPLOYMENT_TYPES, default="Permanent", col=4),
        F("pay_basis", "Pay basis", "select", choices=K.PAY_BASIS, default="Monthly", col=3,
          help="Daily-paid staff are paid for days marked Present (half days count 0.5) in attendance."),
        F("basic_salary", "Basic salary (monthly)", "money", col=3), F("daily_rate", "Daily rate", "money", col=3),
        F("house_allowance", "House allowance", "money", col=3), F("other_allowance", "Other allowances", "money", col=3),
        F("payment_method", "Paid via", "select", choices=K.PAYMENT_METHODS, default="M-Pesa", col=3),
        F("account_details", "M-Pesa no. / bank account", col=6),
        F("date_joined", "Date joined", "date", col=3), F("status", "Status", "select", choices=K.EMPLOYEE_STATUSES, default="Active", col=3),
    ],
    columns=["staff_no", "name", "position", "enterprise", "employment_type", "pay_basis", "basic_salary", "daily_rate",
             "phone", "status"],
    filters=["enterprise", "employment_type", "status"], search=["name", "staff_no", "phone", "national_id"],
    order_by=Employee.name,
)

Resource(
    "attendance", Attendance, "Attendance", "Attendance record", "staff", "/staff/attendance", icon="calendar-check",
    fields=[
        fk_employee(), F("date", "Date", "date", default=date.today, required=True, col=3),
        F("status", "Status", "select", choices=K.ATTENDANCE_STATUSES, default="Present", col=3),
        F("overtime_hours", "Overtime hours", "number", col=3), F("notes", "Notes", col=9),
    ],
    columns=["date", "employee_id", "status", "overtime_hours", "notes"],
    filters=["employee_id", "status"], date_field="date", order_by=lambda m: (m.date.desc(), m.id.desc()),
    actions=[("Daily register", "list-check", lambda: url_for("pages.attendance_register"))],
)


def _casual_stats(args):
    from .crud import REGISTRY
    rows = REGISTRY["casuals"].query(args).all()
    return [
        tile("Casual labour (filtered)", sum(r.amount for r in rows), "warning"),
        tile("Unpaid", sum(r.amount for r in rows if not r.paid), "danger"),
        tile("Worker-days", sum(r.days or 0 for r in rows), "primary", "number"),
        tile("Workers", len({r.worker_name for r in rows}), "secondary", "int"),
    ]


Resource(
    "casuals", CasualLabour, "Casual Labour", "Casual labour entry", "staff", "/staff/casuals", icon="person-workspace",
    fields=[
        F("date", "Date", "date", default=date.today, required=True, col=3),
        F("worker_name", "Worker name", required=True, col=5), F("phone", "Phone", col=4),
        F("task", "Task", col=6, help="e.g. Cleaning pig pens, Offloading feed"), ENT(),
        F("days", "Days", "number", default=1, col=3), F("rate", "Rate per day", "money", required=True, col=3),
        F("payment_method", "Paid via", "select", choices=K.PAYMENT_METHODS, default="M-Pesa", col=3),
        F("paid", "Paid", "bool", default=True, col=3),
    ],
    columns=["date", "worker_name", "task", "enterprise", "days", "rate", C("Amount", lambda c: c.amount, "money"), "paid"],
    filters=["enterprise", "paid"], date_field="date", search=["worker_name", "task"],
    order_by=lambda m: (m.date.desc(), m.id.desc()), stats=_casual_stats,
)

Resource(
    "tasks", Task, "Tasks", "Task", "tasks", "/tasks", icon="list-check",
    fields=[
        F("title", "Task", required=True, col=12), F("due_date", "Due date", "date", default=date.today, col=3),
        fk_employee("assigned_to_id", "Assigned to", required=False),
        F("enterprise", "Enterprise", "select", choices=K.ENTERPRISES, col=3),
        F("priority", "Priority", "select", choices=K.TASK_PRIORITIES, default="Normal", col=3),
        F("status", "Status", "select", choices=K.TASK_STATUSES, default="Open", col=3),
        F("notes", "Notes", "textarea", col=12),
    ],
    columns=["due_date", "title", "assigned_to_id", "enterprise", "priority", "status"],
    filters=["status", "priority", "enterprise"], date_field="due_date", search=["title"],
    order_by=lambda m: (m.status, m.due_date),
    actions=[("Today's agenda", "calendar-day", lambda: url_for("pages.daily"))],
)
