"""Stock and head-count ledgers.

Every document that changes stock (purchase, usage, feed milling, activity) or
head counts (mortality, births, sales) posts movements tagged with a `ref` such
as "purchase:12". Editing a document first reverses its ref, then re-posts, so
balances always equal the sum of the ledger.
"""
from sqlalchemy import func

from .extensions import db
from .models import GroupMovement, LivestockGroup, StockItem, StockMovement


class StockError(ValueError):
    pass


# --------------------------------------------------------------------------- stock
def recalc_item(item_id):
    item = db.session.get(StockItem, item_id)
    if not item:
        return
    db.session.flush()
    qty = db.session.query(func.coalesce(func.sum(StockMovement.quantity), 0)).filter_by(item_id=item_id).scalar()
    ins = (
        db.session.query(
            func.coalesce(func.sum(StockMovement.quantity), 0),
            func.coalesce(func.sum(StockMovement.total_cost), 0),
        )
        .filter(StockMovement.item_id == item_id, StockMovement.quantity > 0)
        .one()
    )
    item.quantity = round(qty, 3)
    item.avg_cost = round(ins[1] / ins[0], 4) if ins[0] else (item.avg_cost or 0)


def reverse(ref):
    """Remove every movement posted under `ref` and refresh affected balances."""
    items = {m.item_id for m in StockMovement.query.filter_by(ref=ref)}
    groups = {m.group_id for m in GroupMovement.query.filter_by(ref=ref)}
    StockMovement.query.filter_by(ref=ref).delete()
    GroupMovement.query.filter_by(ref=ref).delete()
    db.session.flush()
    for i in items:
        recalc_item(i)
    for g in groups:
        recalc_group(g)


def stock_in(item_id, qty, unit_cost, ref, date, kind="purchase", notes=None):
    qty = float(qty or 0)
    if qty <= 0:
        return None
    m = StockMovement(
        item_id=item_id, quantity=qty, unit_cost=unit_cost or 0, total_cost=round(qty * (unit_cost or 0), 2),
        ref=ref, date=date, kind=kind, notes=notes,
    )
    db.session.add(m)
    recalc_item(item_id)
    return m


def stock_out(item_id, qty, ref, date, kind="usage", group=None, enterprise=None, notes=None, allow_negative=False):
    """Issue stock at current average cost. Returns the movement (cost is negative)."""
    qty = float(qty or 0)
    if qty <= 0:
        return None
    item = db.session.get(StockItem, item_id)
    db.session.flush()
    recalc_item(item_id)
    if not allow_negative and (item.quantity or 0) + 1e-9 < qty:
        raise StockError(f"Not enough {item.name} in store: {item.quantity:g} {item.unit} available, {qty:g} needed.")
    if group is not None and not enterprise:
        enterprise = group.ent
    m = StockMovement(
        item_id=item_id, quantity=-qty, unit_cost=item.avg_cost or 0,
        total_cost=-round(qty * (item.avg_cost or 0), 2), ref=ref, date=date, kind=kind,
        group_id=group.id if group is not None else None, enterprise=enterprise or "General", notes=notes,
    )
    db.session.add(m)
    recalc_item(item_id)
    return m


# --------------------------------------------------------------------------- head counts
def recalc_group(group_id):
    g = db.session.get(LivestockGroup, group_id)
    if not g:
        return
    db.session.flush()
    moved = db.session.query(func.coalesce(func.sum(GroupMovement.quantity), 0)).filter_by(group_id=group_id).scalar()
    g.current_count = int((g.opening_count or 0) + moved)
    if g.current_count <= 0 and g.status == "Active" and (g.opening_count or moved):
        g.status = "Sold out"
    elif g.current_count > 0 and g.status == "Sold out":
        g.status = "Active"


def head_change(group_id, qty, kind, ref, date, notes=None):
    if not group_id or not qty:
        return None
    m = GroupMovement(group_id=group_id, quantity=int(qty), kind=kind, ref=ref, date=date, notes=notes)
    db.session.add(m)
    recalc_group(group_id)
    return m
