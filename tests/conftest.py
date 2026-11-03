import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farm import create_app  # noqa: E402
from farm.extensions import db  # noqa: E402


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}", "TESTING": True, "TESTING_NO_CSRF": True})
    with app.app_context():
        db.drop_all()
        db.create_all()
        from farm.seed import seed
        seed()
    return app


@pytest.fixture()
def client(app):
    c = app.test_client()
    r = c.post("/login", data={"email": "admin@zawadeefarm.co.ke", "password": "zawadee2026"})
    assert r.status_code == 302
    return c
