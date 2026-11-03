# Zawadee Farm – Livestock Management System

A cloud web app for running Zawadee Farm: pigs, layers, broilers, kienyeji and other
livestock, the store and the on-farm feed mill, invoicing, payroll, expenses, and profit and loss
per enterprise.

Built with Flask, SQLAlchemy (PostgreSQL in the cloud, SQLite locally) and Bootstrap 5. All
CSS, JS and icons are bundled in `farm/static/vendor`, so the app never depends on a CDN.

## Modules

| Menu | What it does |
|---|---|
| **Dashboard** | Month net, best enterprise, biggest cost area, stock alerts, attendance, receivables, and a 6-month income vs costs chart |
| **Daily tasks** | Today's agenda: tasks, vaccinations and follow-ups due, farrowings due, pending stock requests, groups due for market. Quick buttons for eggs, feed, mortality and attendance |
| **Livestock** | Dashboard with a pig unit section (sows, litter size, pre-weaning mortality, farrowings due) and a poultry section (mortality, egg trays, laying rate, broiler FCR) · Groups (pens/flocks with live head counts) · Animals (breeding-stock register with dam/sire) · Activities (vaccination, treatment, mortality…) · Breeding & farrowing (114-day due date) · Production (eggs by grade, milk, manure) · Weights · Sales |
| **Store** | Suppliers · Store items with stock balance, average cost and re-order alerts · Input purchases (credit and part-payments) · Stock requests (approve, issue) · Input usage · Stock ledger and per-item stock card · Stock-count adjustments |
| **Feed Mill** | Feed formulas (ingredients per batch, estimated cost/kg) · Production batches: ingredients leave the store and finished feed comes in at its true cost per kg |
| **Staff & Payroll** | Employees (monthly or daily-paid) · Attendance register · Casual labour · Payroll runs with Kenyan PAYE, NSSF, SHIF and Housing Levy, advances, approval workflow and printable payslips |
| **Sales & Accounts** | Buyers · Invoices (selling live animals reduces the group's head count) · Payments (M-Pesa codes) · Expenses |
| **Reports** | Profit & loss by enterprise (CSV export) · Enterprise ranking · Receivables ageing · Payables · Stock valuation and usage · Monthly payroll returns (KRA, NSSF, SHA) |
| **Admin** | Users with roles (Admin, Manager, Accountant, Storekeeper, Livestock supervisor) · Farm settings and statutory rates |

Every list has filters, search, CSV export, print and pagination.

### How the money adds up (no double counting)

* **Income** comes from invoice lines, tagged by enterprise.
* **Costs** come from:
  * store items *used*, at weighted average cost, charged to the group's enterprise;
  * expenses;
  * vet fees recorded on activities;
  * approved payroll (gross pay plus employer NSSF and Housing Levy), charged to each employee's enterprise;
  * casual labour;
  * livestock bought.
* Buying stock is **not** a cost until it is used. Milling feed is an internal transfer: the
  finished feed's cost becomes an expense when it is fed to animals.
* Stock balances and head counts are **ledgers**. Every purchase, issue, milling batch, death,
  birth or sale posts movements that are reversed when the record is edited or deleted, so the
  balances always reconcile.

## Run locally

```bash
pip install -r requirements.txt
```

```bash
FLASK_APP=wsgi flask seed-demo     # optional: loads a realistic demo farm
```

```bash
FLASK_APP=wsgi flask run --debug
```

Open http://127.0.0.1:5000 and sign in with **admin@zawadeefarm.co.ke / zawadee2026** (demo only).

For a clean install, skip `seed-demo` and create the first administrator instead:

```bash
FLASK_APP=wsgi flask create-admin
```

Run the tests:

```bash
python -m pytest -q
```

## Deploy to the cloud

The app is a standard WSGI app (`wsgi:app`) and needs PostgreSQL plus these environment variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | Long random string (the app refuses to start without it when `DATABASE_URL` is set) |
| `SESSION_COOKIE_SECURE=1` | Cookies only over HTTPS |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | First administrator, created on first start |

* **Render**: push to GitHub and create a Blueprint from `render.yaml` (web service plus Postgres).
* **Docker** (any VPS, e.g. a Safaricom Cloud or DigitalOcean droplet): `docker build -t zawadeefarm .`,
  then run it with the variables above behind an HTTPS proxy (Caddy or nginx).
* **Heroku / Railway**: `Procfile` is included.

Tables are created automatically on start. Back up the database daily: the hosting provider's
automatic Postgres backups are the simplest option.

## Customising

* Choice lists (enterprises, animal types, activity types, expense categories, stock categories)
  are in `farm/constants.py`.
* Registers are declared once in `farm/resources.py`. Add a field there and to `farm/models.py`.
* Statutory payroll rates are editable under **Admin → Settings**. The defaults follow rates in force
  from February 2026: PAYE bands 10/25/30/32.5/35%, personal relief KES 2,400, NSSF 6% between
  KES 9,000 and KES 108,000, SHIF 2.75% (minimum KES 300) and Housing Levy 1.5%. NSSF, SHIF and the
  Housing Levy are deducted before PAYE. **Have the farm's accountant confirm before filing.**
