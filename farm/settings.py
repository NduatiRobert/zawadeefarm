from flask import g, has_app_context

from .extensions import db
from .models import Setting

DEFAULTS = {
    "farm_name": "Zawadee Farm",
    "farm_tagline": "Livestock management",
    "farm_location": "Kenya",
    "farm_phone": "",
    "farm_email": "",
    "farm_kra_pin": "",
    "currency": "KES",
    "invoice_terms_days": "14",
    "payment_instructions": "Pay via M-Pesa or bank transfer. Quote the invoice number.",
    "eggs_per_tray": "30",
    # Statutory payroll (see farm/payroll.py)
    "personal_relief": "2400",
    "nssf_rate": "6",
    "nssf_lel": "9000",
    "nssf_uel": "108000",
    "shif_rate": "2.75",
    "shif_min": "300",
    "housing_levy_rate": "1.5",
}

LABELS = {
    "farm_name": "Farm name",
    "farm_tagline": "Tagline",
    "farm_location": "Location / address",
    "farm_phone": "Phone",
    "farm_email": "Email",
    "farm_kra_pin": "KRA PIN",
    "currency": "Currency code",
    "invoice_terms_days": "Default invoice terms (days)",
    "payment_instructions": "Payment instructions on invoices",
    "eggs_per_tray": "Eggs per tray",
    "personal_relief": "PAYE personal relief (monthly)",
    "nssf_rate": "NSSF rate % (employee & employer)",
    "nssf_lel": "NSSF lower earnings limit",
    "nssf_uel": "NSSF upper earnings limit",
    "shif_rate": "SHIF rate %",
    "shif_min": "SHIF minimum contribution",
    "housing_levy_rate": "Affordable Housing Levy rate %",
}

def _cache():
    # Per-request cache so several web workers never serve stale settings.
    if has_app_context():
        if "settings_cache" not in g:
            g.settings_cache = {}
        return g.settings_cache
    return {}


def get(key):
    cache = _cache()
    if key in cache:
        return cache[key]
    row = db.session.get(Setting, key)
    val = row.value if row and row.value is not None else DEFAULTS.get(key, "")
    cache[key] = val
    return val


def get_float(key):
    try:
        return float(get(key) or 0)
    except ValueError:
        return float(DEFAULTS.get(key) or 0)


def set_many(values):
    for k, v in values.items():
        row = db.session.get(Setting, k) or Setting(key=k)
        row.value = v
        db.session.add(row)
    db.session.commit()
    _cache().clear()
