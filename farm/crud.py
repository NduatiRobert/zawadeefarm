"""A small declarative CRUD engine.

Each register in the system (suppliers, animals, expenses...) is described by a
`Resource`. The engine gives it a list page with filters, search, pagination,
CSV export and print, plus add/edit/delete forms. Business rules (stock
postings, head counts) live in `on_save` / `on_delete` hooks.
"""
import csv
import io
from datetime import date, datetime

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .extensions import db
from .ledger import StockError

bp = Blueprint("crud", __name__)
REGISTRY = {}


class F:
    """A form field / column definition."""

    def __init__(self, name, label, type="text", required=False, choices=None, fk=None, help=None,
                 col=6, default=None, step=None, list_label=None, show_in_form=True):
        self.name, self.label, self.type = name, label, type
        self.required, self._choices, self.fk, self.help = required, choices, fk, help
        self.col, self.default, self.step = col, default, step
        self.list_label = list_label or label
        self.show_in_form = show_in_form

    @property
    def choices(self):
        c = self._choices() if callable(self._choices) else self._choices
        return c or []

    def fk_options(self):
        model, label_fn, query_fn = self.fk
        q = query_fn(model.query) if query_fn else model.query
        return [(o.id, label_fn(o) if label_fn else str(o)) for o in q.all()]

    def initial(self):
        return self.default() if callable(self.default) else self.default

    def parse(self, raw):
        raw = (raw or "").strip() if isinstance(raw, str) else raw
        if self.type == "bool":
            return bool(raw)
        if raw in ("", None):
            if self.required:
                raise ValueError(f"{self.label} is required.")
            return 0 if self.type in ("money",) else None
        if self.type in ("number", "money"):
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                raise ValueError(f"{self.label} must be a number.")
        if self.type == "int":
            try:
                return int(float(raw.replace(",", "")))
            except ValueError:
                raise ValueError(f"{self.label} must be a whole number.")
        if self.type == "fk":
            return int(raw)
        if self.type == "date":
            try:
                return date.fromisoformat(raw)
            except ValueError:
                raise ValueError(f"{self.label} must be a valid date.")
        return raw


class C:
    """A computed list column: label + getter + display format."""

    def __init__(self, label, getter, fmt="text", align=None):
        self.label, self.getter, self.fmt = label, getter, fmt
        self.align = align or ("end" if fmt in ("money", "number", "int") else None)

    def value(self, obj):
        return self.getter(obj)


class Lines:
    def __init__(self, model, attr, fields, title="Items", total=None):
        self.model, self.attr, self.fields, self.title, self.total = model, attr, fields, title, total


class Resource:
    def __init__(self, key, model, title, singular, section, path, fields, columns, icon="table",
                 filters=(), search=(), order_by=None, date_field=None, lines=None, on_save=None,
                 on_delete=None, stats=None, actions=(), row_actions=(), note=None, editable=True,
                 addable=True, form_title=None, after_save_url=None, subtitle=None, prefill=None):
        self.key, self.model, self.title, self.singular = key, model, title, singular
        self.section, self.path, self.icon = section, path, icon
        self.fields = fields
        self.field_map = {f.name: f for f in fields}
        self.columns = [self._col(c) for c in columns]
        self.filters = [self.field_map[f] for f in filters]
        self.search = search
        self.order_by = order_by
        self.date_field = date_field
        self.lines = lines
        self.on_save, self.on_delete, self.stats = on_save, on_delete, stats
        self.actions, self.row_actions = actions, row_actions
        self.note, self.editable, self.addable = note, editable, addable
        self.form_title = form_title
        self.after_save_url = after_save_url
        self.subtitle = subtitle
        self.prefill = prefill
        REGISTRY[key] = self

    def _col(self, c):
        if isinstance(c, C):
            return c
        f = self.field_map[c]
        if f.type == "fk":
            return C(f.list_label, lambda o, n=c: getattr(o, n.removesuffix("_id"), None), "text")
        fmt = {"money": "money", "number": "number", "int": "int", "date": "date", "bool": "bool"}.get(f.type, "text")
        if f.name in ("status",):
            fmt = "badge"
        return C(f.list_label, lambda o, n=c: getattr(o, n, None), fmt)

    def url(self, action="list", **kw):
        return url_for(f"crud.{self.key}_{action}", **kw)

    # ------------------------------------------------------------- query
    def query(self, args):
        q = self.model.query
        text = (args.get("q") or "").strip()
        if text and self.search:
            q = q.filter(or_(*[getattr(self.model, s).ilike(f"%{text}%") for s in self.search]))
        for f in self.filters:
            v = args.get(f.name)
            if v not in (None, ""):
                if f.type == "fk":
                    v = int(v)
                elif f.type == "bool":
                    v = v == "1"
                q = q.filter(getattr(self.model, f.name) == v)
        if self.date_field:
            col = getattr(self.model, self.date_field)
            if args.get("from"):
                q = q.filter(col >= date.fromisoformat(args["from"]))
            if args.get("to"):
                q = q.filter(col <= date.fromisoformat(args["to"]))
        if self.order_by is not None:
            q = q.order_by(*self.order_by(self.model)) if callable(self.order_by) else q.order_by(self.order_by)
        else:
            q = q.order_by(self.model.id.desc())
        return q


def fmt_value(value, fmt):
    if value is None or value == "":
        return ""
    if fmt == "money":
        return f"{value:,.2f}"
    if fmt == "number":
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if fmt == "int":
        return f"{int(value):,}"
    if fmt == "date":
        return value.strftime("%d %b %Y") if isinstance(value, (date, datetime)) else value
    if fmt == "bool":
        return "Yes" if value else "No"
    return str(value)


def check_section(res):
    if not current_user.can(res.section):
        abort(403)


def apply_form(res, obj, form):
    errors = []
    for f in res.fields:
        if not f.show_in_form:
            continue
        try:
            setattr(obj, f.name, f.parse(form.get(f.name)))
        except ValueError as e:
            errors.append(str(e))
    if res.lines:
        new_lines = []
        cols = {f.name: form.getlist(f"l_{f.name}") for f in res.lines.fields}
        n = max((len(v) for v in cols.values()), default=0)
        for i in range(n):
            raw = {k: (v[i] if i < len(v) else "") for k, v in cols.items()}
            if not any(str(x).strip() for x in raw.values() if x not in ("0",)):
                continue
            line = res.lines.model()
            for f in res.lines.fields:
                try:
                    setattr(line, f.name, f.parse(raw[f.name]))
                except ValueError as e:
                    errors.append(f"Line {i + 1}: {e}")
            new_lines.append(line)
        if not new_lines and not errors:
            errors.append(f"Add at least one line to {res.lines.title.lower()}.")
        getattr(obj, res.lines.attr)[:] = new_lines
    return errors


def make_views(res):
    def list_view():
        check_section(res)
        try:
            per_page = min(int(request.args.get("per_page", 15)), 500)
            page = max(int(request.args.get("page", 1)), 1)
        except ValueError:
            per_page, page = 15, 1
        q = res.query(request.args)
        pg = q.paginate(page=page, per_page=per_page, error_out=False)
        filters_active = any(request.args.get(k) for k in ["q", "from", "to"] + [f.name for f in res.filters])
        return render_template(
            "crud/list.html", res=res, pg=pg, fmt_value=fmt_value, per_page=per_page,
            filters_active=filters_active, stats=res.stats(request.args) if res.stats else None,
        )

    def form_view(id=None):
        check_section(res)
        obj = db.get_or_404(res.model, id) if id else res.model()
        if id and not res.editable:
            abort(404)
        if request.method == "POST":
            errors = apply_form(res, obj, request.form)
            if not errors:
                try:
                    if not id:
                        db.session.add(obj)
                    db.session.flush()
                    if res.on_save:
                        res.on_save(obj, id is None)
                    db.session.commit()
                    flash(f"{res.singular} saved.", "success")
                    if request.form.get("_next") == "add":
                        return redirect(res.url("new"))
                    if res.after_save_url:
                        return redirect(res.after_save_url(obj))
                    return redirect(res.url())
                except (StockError, ValueError) as e:
                    db.session.rollback()
                    errors.append(str(e))
            db.session.rollback() if id else None
            for e in errors:
                flash(e, "danger")
            values = request.form
            line_rows = _posted_lines(res)
        else:
            if id:
                values = {f.name: _form_value(getattr(obj, f.name), f) for f in res.fields}
            else:
                values = {f.name: _form_value(f.initial(), f) for f in res.fields}
                if res.prefill:
                    values.update({k: _form_value(v, res.field_map.get(k)) for k, v in res.prefill(request.args).items()})
                for f in res.fields:
                    if request.args.get(f.name):
                        values[f.name] = request.args[f.name]
            line_rows = []
            if res.lines and id:
                for l in getattr(obj, res.lines.attr):
                    line_rows.append({f.name: _form_value(getattr(l, f.name), f) for f in res.lines.fields})
        return render_template("crud/form.html", res=res, obj=obj, values=values, line_rows=line_rows, is_new=id is None)

    def delete_view(id):
        check_section(res)
        obj = db.get_or_404(res.model, id)
        try:
            if res.on_delete:
                res.on_delete(obj)
            db.session.delete(obj)
            db.session.commit()
            flash(f"{res.singular} deleted.", "success")
        except Exception as e:  # noqa: BLE001 - surface integrity problems to the user
            db.session.rollback()
            flash(f"Could not delete: {e}", "danger")
        return redirect(request.referrer or res.url())

    def export_view():
        check_section(res)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([c.label for c in res.columns])
        for o in res.query(request.args).all():
            w.writerow([fmt_value(c.value(o), c.fmt if c.fmt != "money" else "number") for c in res.columns])
        return Response(
            out.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={res.key}-{date.today()}.csv"},
        )

    for name, fn, rule, methods in [
        ("list", list_view, res.path, ["GET"]),
        ("new", form_view, res.path + "/new", ["GET", "POST"]),
        ("edit", form_view, res.path + "/<int:id>/edit", ["GET", "POST"]),
        ("delete", delete_view, res.path + "/<int:id>/delete", ["POST"]),
        ("export", export_view, res.path + "/export.csv", ["GET"]),
    ]:
        bp.add_url_rule(rule, f"{res.key}_{name}", login_required(fn), methods=methods)


def _form_value(v, f):
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v


def _posted_lines(res):
    if not res.lines:
        return []
    cols = {f.name: request.form.getlist(f"l_{f.name}") for f in res.lines.fields}
    n = max((len(v) for v in cols.values()), default=0)
    return [{k: (v[i] if i < len(v) else "") for k, v in cols.items()} for i in range(n)]


_registered = False


def register_all():
    global _registered
    if _registered:  # blueprint rules are global; only add them once per process
        return
    for res in REGISTRY.values():
        make_views(res)
    _registered = True
