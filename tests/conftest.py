import json

import pytest

from margin_guard import db, seed
from margin_guard.config import EMAILS_PATH


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    seed.build(c)
    yield c
    c.close()


@pytest.fixture(scope="session")
def gold():
    return {e["id"]: e for e in json.loads(EMAILS_PATH.read_text(encoding="utf-8"))}
