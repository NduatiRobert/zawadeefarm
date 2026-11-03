"""Kenyan statutory payroll calculations.

Defaults reflect rates in force from February 2026 (NSSF Year 4 limits). All
rates are editable under Admin > Settings so the farm can update them when KRA,
NSSF or SHA publish changes. Have the farm's accountant confirm before filing.
"""
from calendar import monthrange
from datetime import date

from .settings import get_float

PAYE_BANDS = [  # (monthly upper limit, rate)
    (24_000, 0.10),
    (32_333, 0.25),
    (500_000, 0.30),
    (800_000, 0.325),
    (float("inf"), 0.35),
]


def paye(taxable, relief):
    tax, lower = 0.0, 0.0
    for upper, rate in PAYE_BANDS:
        if taxable <= lower:
            break
        tax += (min(taxable, upper) - lower) * rate
        lower = upper
    return max(round(tax - relief, 2), 0.0)


def nssf(pensionable, lel, uel, rate):
    tier1 = min(pensionable, lel) * rate
    tier2 = max(min(pensionable, uel) - lel, 0) * rate
    return round(tier1 + tier2, 2)


def compute(basic, allowances=0.0, overtime=0.0, advances=0.0, other_deductions=0.0):
    rates = dict(
        lel=get_float("nssf_lel"), uel=get_float("nssf_uel"), nssf_rate=get_float("nssf_rate") / 100,
        shif_rate=get_float("shif_rate") / 100, shif_min=get_float("shif_min"),
        ahl_rate=get_float("housing_levy_rate") / 100, relief=get_float("personal_relief"),
    )
    gross = round(basic + allowances + overtime, 2)
    n = nssf(gross, rates["lel"], rates["uel"], rates["nssf_rate"]) if gross > 0 else 0
    s = round(max(gross * rates["shif_rate"], rates["shif_min"]), 2) if gross > 0 else 0
    h = round(gross * rates["ahl_rate"], 2)
    # Since Dec 2024 NSSF, SHIF and Housing Levy are deductible before PAYE.
    taxable = max(round(gross - n - s - h, 2), 0)
    p = paye(taxable, rates["relief"])
    net = round(gross - n - s - h - p - advances - other_deductions, 2)
    return dict(
        gross=gross, nssf=n, shif=s, housing_levy=h, taxable=taxable, paye=p, net=net,
        employer_nssf=n, employer_housing=h, advances=advances, other_deductions=other_deductions,
    )


def period_bounds(period):
    y, m = map(int, period.split("-"))
    return date(y, m, 1), date(y, m, monthrange(y, m)[1])
