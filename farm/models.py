from datetime import date, datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import ANIMAL_ENTERPRISE, ROLE_SECTIONS, ROLES
from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today():
    return date.today()


class Base(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- admin
class User(UserMixin, Base):
    __tablename__ = "users"
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(30), default="manager", nullable=False)
    is_active_user = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)

    @property
    def is_active(self):
        return bool(self.is_active_user)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role)

    def can(self, section):
        allowed = ROLE_SECTIONS.get(self.role, set())
        return "*" in allowed or section in allowed

    def __str__(self):
        return self.name


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text)


# --------------------------------------------------------------------------- store
class Supplier(Base):
    __tablename__ = "suppliers"
    name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(140))
    supplier_type = db.Column(db.String(60))
    location = db.Column(db.String(140))
    notes = db.Column(db.Text)

    def __str__(self):
        return self.name


class StockItem(Base):
    __tablename__ = "stock_items"
    name = db.Column(db.String(140), nullable=False)
    category = db.Column(db.String(60), default="Feed")
    unit = db.Column(db.String(30), default="kg")
    reorder_level = db.Column(db.Float, default=0)
    # Maintained by ledger.recalc_item from the movement ledger.
    quantity = db.Column(db.Float, default=0)
    avg_cost = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)

    movements = db.relationship("StockMovement", backref="item", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def value(self):
        return round((self.quantity or 0) * (self.avg_cost or 0), 2)

    @property
    def is_low(self):
        return (self.reorder_level or 0) > 0 and (self.quantity or 0) <= self.reorder_level

    def __str__(self):
        return f"{self.name} ({self.unit})"


class StockMovement(Base):
    """Every change to stock quantity. Positive = into store, negative = out."""

    __tablename__ = "stock_movements"
    item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"), nullable=False, index=True)
    date = db.Column(db.Date, default=today, index=True)
    kind = db.Column(db.String(30), nullable=False)  # opening, purchase, usage, mill_in, mill_out, adjustment
    quantity = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    enterprise = db.Column(db.String(60))
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    ref = db.Column(db.String(60), index=True)  # e.g. "purchase:4" so postings can be reversed
    notes = db.Column(db.String(255))

    group = db.relationship("LivestockGroup")


class Purchase(Base):
    __tablename__ = "purchases"
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    date = db.Column(db.Date, default=today)
    reference = db.Column(db.String(60))
    due_date = db.Column(db.Date)
    amount_paid = db.Column(db.Float, default=0)
    payment_method = db.Column(db.String(40))
    notes = db.Column(db.Text)

    supplier = db.relationship("Supplier", backref="purchases")
    lines = db.relationship("PurchaseLine", backref="purchase", cascade="all, delete-orphan")

    @property
    def total(self):
        return round(sum(l.amount for l in self.lines), 2)

    @property
    def balance(self):
        return round(self.total - (self.amount_paid or 0), 2)

    @property
    def status(self):
        if self.total and self.balance <= 0:
            return "Paid"
        if self.due_date and self.due_date < date.today():
            return "Overdue"
        return "Part paid" if (self.amount_paid or 0) > 0 else "Unpaid"

    def __str__(self):
        return f"PO-{self.id:04d}"


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"), nullable=False)
    quantity = db.Column(db.Float, default=0)
    unit_price = db.Column(db.Float, default=0)

    item = db.relationship("StockItem")

    @property
    def amount(self):
        return round((self.quantity or 0) * (self.unit_price or 0), 2)


class StockRequest(Base):
    __tablename__ = "stock_requests"
    item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    enterprise = db.Column(db.String(60))
    requested_by = db.Column(db.String(120))
    qty_requested = db.Column(db.Float, default=0)
    qty_issued = db.Column(db.Float, default=0)
    request_date = db.Column(db.Date, default=today)
    needed_by = db.Column(db.Date)
    status = db.Column(db.String(20), default="Pending")
    notes = db.Column(db.Text)

    item = db.relationship("StockItem")
    group = db.relationship("LivestockGroup")

    @property
    def number(self):
        return f"SR-{self.id:04d}" if self.id else "New"


class StockUsage(Base):
    """Direct issue of stock to a group / enterprise (feeding, medicine, bedding...)."""

    __tablename__ = "stock_usage"
    date = db.Column(db.Date, default=today)
    item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    enterprise = db.Column(db.String(60))
    quantity = db.Column(db.Float, default=0)
    purpose = db.Column(db.String(140))
    issued_by = db.Column(db.String(120))

    item = db.relationship("StockItem")
    group = db.relationship("LivestockGroup")

    @property
    def cost(self):
        m = StockMovement.query.filter_by(ref=f"usage:{self.id}").first()
        return -m.total_cost if m else 0


# --------------------------------------------------------------------------- feed mill
class FeedFormula(Base):
    __tablename__ = "feed_formulas"
    name = db.Column(db.String(140), nullable=False)
    enterprise = db.Column(db.String(60), default="Pigs")
    output_item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"), nullable=False)
    notes = db.Column(db.Text)

    output_item = db.relationship("StockItem")
    lines = db.relationship("FeedFormulaLine", backref="formula", cascade="all, delete-orphan")

    @property
    def batch_size(self):
        return round(sum(l.quantity or 0 for l in self.lines), 2)

    @property
    def est_cost(self):
        return round(sum((l.quantity or 0) * (l.item.avg_cost or 0) for l in self.lines if l.item), 2)

    @property
    def est_cost_per_kg(self):
        return round(self.est_cost / self.batch_size, 2) if self.batch_size else 0

    def __str__(self):
        return self.name


class FeedFormulaLine(Base):
    __tablename__ = "feed_formula_lines"
    formula_id = db.Column(db.Integer, db.ForeignKey("feed_formulas.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"), nullable=False)
    quantity = db.Column(db.Float, default=0)  # kg per batch

    item = db.relationship("StockItem")


class FeedBatch(Base):
    __tablename__ = "feed_batches"
    date = db.Column(db.Date, default=today)
    formula_id = db.Column(db.Integer, db.ForeignKey("feed_formulas.id"), nullable=False)
    batches = db.Column(db.Float, default=1)
    output_qty = db.Column(db.Float, default=0)  # kg actually produced (after milling loss)
    total_cost = db.Column(db.Float, default=0)
    produced_by = db.Column(db.String(120))
    notes = db.Column(db.Text)

    formula = db.relationship("FeedFormula")

    @property
    def number(self):
        return f"MB-{self.id:04d}" if self.id else "New"

    @property
    def cost_per_unit(self):
        return round(self.total_cost / self.output_qty, 2) if self.output_qty else 0


# --------------------------------------------------------------------------- livestock
class LivestockGroup(Base):
    __tablename__ = "livestock_groups"
    name = db.Column(db.String(120), nullable=False)
    animal_type = db.Column(db.String(40), nullable=False)
    enterprise = db.Column(db.String(60))
    purpose = db.Column(db.String(60))
    breed = db.Column(db.String(80))
    opening_count = db.Column(db.Integer, default=0)
    # Maintained by ledger.recalc_group: opening_count + all head-count movements.
    current_count = db.Column(db.Integer, default=0)
    placement_date = db.Column(db.Date, default=today)
    target_market_date = db.Column(db.Date)
    acquisition_cost = db.Column(db.Float, default=0)
    location = db.Column(db.String(80))
    status = db.Column(db.String(20), default="Active")
    notes = db.Column(db.Text)

    count_movements = db.relationship("GroupMovement", backref="group", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def ent(self):
        return self.enterprise or ANIMAL_ENTERPRISE.get(self.animal_type, "General")

    @property
    def age_weeks(self):
        if not self.placement_date:
            return None
        return (date.today() - self.placement_date).days // 7

    @property
    def deaths(self):
        return -sum(m.quantity for m in self.count_movements.filter_by(kind="death"))

    @property
    def mortality_pct(self):
        base = self.opening_count or 0
        base += sum(m.quantity for m in self.count_movements.filter(GroupMovement.quantity > 0))
        return round(self.deaths * 100 / base, 1) if base else 0

    def __str__(self):
        return self.name


class GroupMovement(Base):
    """Head-count changes for a group: births, deaths, sales, culls, adjustments."""

    __tablename__ = "group_movements"
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"), nullable=False, index=True)
    date = db.Column(db.Date, default=today)
    kind = db.Column(db.String(20), nullable=False)  # birth, death, sale, cull, adjustment
    quantity = db.Column(db.Integer, nullable=False)
    ref = db.Column(db.String(60), index=True)
    notes = db.Column(db.String(255))


class Animal(Base):
    __tablename__ = "animals"
    tag_number = db.Column(db.String(40), nullable=False, index=True)
    name = db.Column(db.String(80))
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    animal_type = db.Column(db.String(40), nullable=False)
    breed = db.Column(db.String(80))
    sex = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date)
    acquired_on = db.Column(db.Date)
    source = db.Column(db.String(40))
    purchase_cost = db.Column(db.Float, default=0)
    current_weight = db.Column(db.Float)
    status = db.Column(db.String(20), default="Active")
    breeding_status = db.Column(db.String(30), default="Not applicable")
    dam_id = db.Column(db.Integer, db.ForeignKey("animals.id"))
    sire_id = db.Column(db.Integer, db.ForeignKey("animals.id"))
    notes = db.Column(db.Text)

    group = db.relationship("LivestockGroup", backref="animals")
    dam = db.relationship("Animal", remote_side="Animal.id", foreign_keys=[dam_id])
    sire = db.relationship("Animal", remote_side="Animal.id", foreign_keys=[sire_id])

    @property
    def offspring_count(self):
        return Animal.query.filter((Animal.dam_id == self.id) | (Animal.sire_id == self.id)).count()

    def __str__(self):
        return f"{self.tag_number}" + (f" – {self.name}" if self.name else "")


class Activity(Base):
    __tablename__ = "activities"
    date = db.Column(db.Date, default=today, index=True)
    activity_type = db.Column(db.String(40), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    animal_id = db.Column(db.Integer, db.ForeignKey("animals.id"))
    affected_count = db.Column(db.Integer, default=0)
    stock_item_id = db.Column(db.Integer, db.ForeignKey("stock_items.id"))
    quantity_used = db.Column(db.Float, default=0)
    description = db.Column(db.String(255))
    cost = db.Column(db.Float, default=0)  # extra cash cost, e.g. vet fee
    next_due_date = db.Column(db.Date)
    follow_up_done = db.Column(db.Boolean, default=False)
    performed_by = db.Column(db.String(120))

    group = db.relationship("LivestockGroup")
    animal = db.relationship("Animal")
    stock_item = db.relationship("StockItem")


class Breeding(Base):
    __tablename__ = "breeding"
    female_id = db.Column(db.Integer, db.ForeignKey("animals.id"), nullable=False)
    male_id = db.Column(db.Integer, db.ForeignKey("animals.id"))
    method = db.Column(db.String(20), default="Natural")
    service_date = db.Column(db.Date, default=today)
    expected_date = db.Column(db.Date)
    actual_date = db.Column(db.Date)
    born_alive = db.Column(db.Integer)
    stillborn = db.Column(db.Integer)
    weaned_count = db.Column(db.Integer)
    weaning_date = db.Column(db.Date)
    litter_group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    status = db.Column(db.String(20), default="Served")
    notes = db.Column(db.Text)

    female = db.relationship("Animal", foreign_keys=[female_id])
    male = db.relationship("Animal", foreign_keys=[male_id])
    litter_group = db.relationship("LivestockGroup")


class Production(Base):
    __tablename__ = "production"
    date = db.Column(db.Date, default=today, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    product = db.Column(db.String(40), default="Eggs")
    grade = db.Column(db.String(30))
    quantity = db.Column(db.Float, default=0)
    unit_value = db.Column(db.Float, default=0)
    recorded_by = db.Column(db.String(120))
    notes = db.Column(db.String(255))

    group = db.relationship("LivestockGroup")

    @property
    def value(self):
        return round((self.quantity or 0) * (self.unit_value or 0), 2)

    @property
    def trays(self):
        return round((self.quantity or 0) / 30, 2) if self.product == "Eggs" else None


class WeightRecord(Base):
    __tablename__ = "weights"
    date = db.Column(db.Date, default=today)
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    animal_id = db.Column(db.Integer, db.ForeignKey("animals.id"))
    sample_size = db.Column(db.Integer, default=1)
    avg_weight = db.Column(db.Float, nullable=False)  # kg
    notes = db.Column(db.String(255))

    group = db.relationship("LivestockGroup")
    animal = db.relationship("Animal")


# --------------------------------------------------------------------------- sales
class Buyer(Base):
    __tablename__ = "buyers"
    name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(140))
    buyer_type = db.Column(db.String(60))
    location = db.Column(db.String(140))
    kra_pin = db.Column(db.String(30))
    notes = db.Column(db.Text)

    def __str__(self):
        return self.name


class Invoice(Base):
    __tablename__ = "invoices"
    buyer_id = db.Column(db.Integer, db.ForeignKey("buyers.id"), nullable=False)
    date = db.Column(db.Date, default=today, index=True)
    due_date = db.Column(db.Date)
    notes = db.Column(db.Text)

    buyer = db.relationship("Buyer", backref="invoices")
    lines = db.relationship("InvoiceLine", backref="invoice", cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="invoice", cascade="all, delete-orphan")

    @property
    def number(self):
        return f"INV-{self.id:05d}" if self.id else "New"

    @property
    def total(self):
        return round(sum(l.amount for l in self.lines), 2)

    @property
    def paid(self):
        return round(sum(p.amount or 0 for p in self.payments), 2)

    @property
    def balance(self):
        return round(self.total - self.paid, 2)

    @property
    def status(self):
        if self.total and self.balance <= 0:
            return "Paid"
        if self.due_date and self.due_date < date.today():
            return "Overdue"
        return "Part paid" if self.paid > 0 else "Unpaid"

    def __str__(self):
        return f"{self.number} – {self.buyer}"


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    enterprise = db.Column(db.String(60))
    group_id = db.Column(db.Integer, db.ForeignKey("livestock_groups.id"))
    heads_sold = db.Column(db.Integer, default=0)  # live animals leaving the group
    quantity = db.Column(db.Float, default=1)
    unit = db.Column(db.String(30))
    unit_price = db.Column(db.Float, default=0)

    group = db.relationship("LivestockGroup")

    @property
    def amount(self):
        return round((self.quantity or 0) * (self.unit_price or 0), 2)


class Payment(Base):
    __tablename__ = "payments"
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    date = db.Column(db.Date, default=today)
    amount = db.Column(db.Float, default=0)
    method = db.Column(db.String(40), default="M-Pesa")
    reference = db.Column(db.String(80))


class Expense(Base):
    __tablename__ = "expenses"
    date = db.Column(db.Date, default=today, index=True)
    category = db.Column(db.String(60), nullable=False)
    enterprise = db.Column(db.String(60), default="General")
    description = db.Column(db.String(255))
    amount = db.Column(db.Float, default=0)
    payee = db.Column(db.String(140))
    payment_method = db.Column(db.String(40))
    reference = db.Column(db.String(80))


# --------------------------------------------------------------------------- staff & payroll
class Employee(Base):
    __tablename__ = "employees"
    staff_no = db.Column(db.String(20))
    name = db.Column(db.String(140), nullable=False)
    national_id = db.Column(db.String(30))
    kra_pin = db.Column(db.String(30))
    nssf_no = db.Column(db.String(30))
    shif_no = db.Column(db.String(30))
    phone = db.Column(db.String(40))
    position = db.Column(db.String(80))
    enterprise = db.Column(db.String(60), default="General")
    employment_type = db.Column(db.String(20), default="Permanent")
    pay_basis = db.Column(db.String(20), default="Monthly")
    basic_salary = db.Column(db.Float, default=0)
    daily_rate = db.Column(db.Float, default=0)
    house_allowance = db.Column(db.Float, default=0)
    other_allowance = db.Column(db.Float, default=0)
    payment_method = db.Column(db.String(40), default="M-Pesa")
    account_details = db.Column(db.String(140))
    date_joined = db.Column(db.Date)
    status = db.Column(db.String(20), default="Active")

    def __str__(self):
        return self.name


class Attendance(Base):
    __tablename__ = "attendance"
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    date = db.Column(db.Date, default=today, index=True)
    status = db.Column(db.String(20), default="Present")
    overtime_hours = db.Column(db.Float, default=0)
    notes = db.Column(db.String(255))

    employee = db.relationship("Employee", backref="attendance")


class CasualLabour(Base):
    __tablename__ = "casual_labour"
    date = db.Column(db.Date, default=today, index=True)
    worker_name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40))
    task = db.Column(db.String(200))
    enterprise = db.Column(db.String(60), default="General")
    days = db.Column(db.Float, default=1)
    rate = db.Column(db.Float, default=0)
    paid = db.Column(db.Boolean, default=True)
    payment_method = db.Column(db.String(40), default="M-Pesa")

    @property
    def amount(self):
        return round((self.days or 0) * (self.rate or 0), 2)


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    period = db.Column(db.String(7), nullable=False, unique=True)  # YYYY-MM
    status = db.Column(db.String(20), default="Draft")  # Draft, Approved, Paid
    paid_on = db.Column(db.Date)
    notes = db.Column(db.Text)

    payslips = db.relationship("Payslip", backref="run", cascade="all, delete-orphan")

    def total(self, attr):
        return round(sum(getattr(p, attr) or 0 for p in self.payslips), 2)


class Payslip(Base):
    __tablename__ = "payslips"
    run_id = db.Column(db.Integer, db.ForeignKey("payroll_runs.id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    days_worked = db.Column(db.Float, default=0)
    basic = db.Column(db.Float, default=0)
    allowances = db.Column(db.Float, default=0)
    overtime = db.Column(db.Float, default=0)
    gross = db.Column(db.Float, default=0)
    nssf = db.Column(db.Float, default=0)
    shif = db.Column(db.Float, default=0)
    housing_levy = db.Column(db.Float, default=0)
    taxable = db.Column(db.Float, default=0)
    paye = db.Column(db.Float, default=0)
    advances = db.Column(db.Float, default=0)
    other_deductions = db.Column(db.Float, default=0)
    net = db.Column(db.Float, default=0)
    employer_nssf = db.Column(db.Float, default=0)
    employer_housing = db.Column(db.Float, default=0)

    employee = db.relationship("Employee")

    @property
    def total_deductions(self):
        return round(self.gross - self.net, 2)

    @property
    def employer_cost(self):
        return round((self.gross or 0) + (self.employer_nssf or 0) + (self.employer_housing or 0), 2)


class Task(Base):
    __tablename__ = "tasks"
    title = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date, default=today)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    enterprise = db.Column(db.String(60))
    priority = db.Column(db.String(10), default="Normal")
    status = db.Column(db.String(20), default="Open")
    notes = db.Column(db.Text)

    assigned_to = db.relationship("Employee")
