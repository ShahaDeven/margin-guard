"""Won orders whose material isn't bought yet: what they absorb, what buying now saves, buy-now and undo."""

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import PERFECT_EXTRACTIONS

from margin_guard import backlog, coordinator, importer, ingest, leakage
from margin_guard.config import AS_OF

TODAY = AS_OF.isoformat()


@pytest.fixture
def processed(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, POLICY_DECIDER)
    return conn


def _orders(conn):
    return {o["quote_id"]: o for o in backlog.analyze(conn)["orders"]}


def test_seeded_backlog_is_recent_won_orders_bought_after_today(conn):
    rows = conn.execute("SELECT status, ordered_date, material_buy_date FROM quotes"
                        " WHERE material_buy_date IS NOT NULL").fetchall()
    assert len(rows) >= 8
    assert all(r["status"] == "won" and r["ordered_date"] < TODAY < r["material_buy_date"] for r in rows)
    assert leakage.analyze(conn)["leaked_usd"] == pytest.approx(6151, abs=1)      # leakage doesn't move


def test_seed_alone_has_little_to_absorb(conn):
    assert backlog.analyze(conn)["absorbing_usd"] < 100   # before the inbox, only changes already in effect


def test_increases_on_file_land_on_the_backlog(processed):
    r = backlog.analyze(processed)
    assert r["absorbing_usd"] > 500                      # the November notices hit orders bought after Nov 1
    assert any(c["effective_date"] >= "2026-11-01" and c["absorbing_usd"] > 0
               for o in r["orders"] for c in o["changes"])
    o = max(r["orders"], key=lambda o: o["absorbing_usd"])
    assert o["buy_before"] and o["buy_before"] > TODAY
    assert o["margin_at_buy"] < o["margin_as_ordered"]
    assert sum(c["absorbing_usd"] for c in o["changes"]) == pytest.approx(o["absorbing_usd"], abs=0.05)
    assert sum(ln["absorbing_usd"] for ln in o["lines"]) == pytest.approx(o["absorbing_usd"], abs=0.05)


def test_an_increase_before_the_order_is_not_absorbed(processed):
    """Only changes that took effect after the order was placed come out of its margin."""
    for o in _orders(processed).values():
        assert all(c["effective_date"] > o["ordered_date"] for c in o["changes"])


def test_a_coming_decrease_is_never_a_reason_to_buy_early(processed):
    for o in _orders(processed).values():
        assert o["buy_now_saves_usd"] >= 0
        if o["buy_before"]:
            hit = [c for c in o["changes"] if c["effective_date"] == o["buy_before"]]
            assert hit and all(c["absorbing_usd"] > 0 for c in hit)
    r = backlog.analyze(processed)
    assert r["absorbing_usd"] >= 0 and r["gaining_usd"] >= 0


def test_buy_now_keeps_the_margin_and_undo_restores_it(processed):
    target = max(_orders(processed).values(), key=lambda o: o["buy_now_saves_usd"])
    saves = target["buy_now_saves_usd"]
    total = backlog.analyze(processed)
    backlog.buy_now(processed, target["quote_id"])

    after = backlog.analyze(processed)
    o = _orders(processed)[target["quote_id"]]
    assert o["material_bought_on"] == TODAY and o["buy_before"] is None and o["buy_now_saves_usd"] == 0
    assert o["saved_usd"] == pytest.approx(saves, abs=0.01)
    assert after["waiting"] == total["waiting"] - 1 and after["bought_early"] == 1
    assert after["saved_by_buying_early_usd"] == pytest.approx(saves, abs=0.01)
    assert after["absorbing_usd"] == pytest.approx(total["absorbing_usd"] - target["absorbing_usd"], abs=0.02)

    with pytest.raises(backlog.BacklogError, match="already bought"):
        backlog.buy_now(processed, target["quote_id"])
    backlog.undo_buy(processed, target["quote_id"])
    assert backlog.analyze(processed)["absorbing_usd"] == total["absorbing_usd"]
    with pytest.raises(backlog.BacklogError, match="no early purchase"):
        backlog.undo_buy(processed, target["quote_id"])


def test_buy_now_only_on_backlog_orders(conn):
    open_quote = conn.execute("SELECT id FROM quotes WHERE status = 'open' LIMIT 1").fetchone()["id"]
    with pytest.raises(backlog.BacklogError, match="isn't a won order"):
        backlog.buy_now(conn, open_quote)
    with pytest.raises(backlog.BacklogError, match="not found"):
        backlog.buy_now(conn, "Q-NOPE")
    q = conn.execute("SELECT id, material_buy_date FROM quotes WHERE material_buy_date IS NOT NULL"
                     " ORDER BY material_buy_date LIMIT 1").fetchone()
    with pytest.raises(backlog.BacklogError, match="no longer ahead"):
        backlog.buy_now(conn, q["id"], today=q["material_buy_date"])


# ------------------------------------------------------------------ CSV


def test_buy_dates_round_trip_through_the_csv(conn, tmp_path):
    from margin_guard import db
    importer.export(conn, tmp_path / "out")
    other = db.connect(tmp_path / "copy.db")
    importer.load(tmp_path / "out", other)
    assert backlog.analyze(other) == backlog.analyze(conn)


@pytest.mark.parametrize("status, buy, message", [
    ("open", "2026-12-01", "only for won quotes"),
    ("won", "2020-01-01", "before ordered_date"),
])
def test_buy_date_is_validated(conn, tmp_path, status, buy, message):
    folder = tmp_path / "shop"
    importer.export(conn, folder)
    path = folder / "quotes.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    i = next(n for n, ln in enumerate(lines[1:], start=1) if f",{'won' if status == 'won' else 'open'}," in ln)
    cells = lines[i].split(",")
    cells[header.index("material_buy_date")] = buy
    lines[i] = ",".join(cells)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, problems = importer.validate(folder)
    assert any(message in p for p in problems)


# ------------------------------------------------------------------ HTTP


@pytest.fixture
def client(processed, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", processed)
    with TestClient(api.app) as c:
        yield c


def test_backlog_over_http(client):
    r = client.get("/api/backlog").json()
    target = next(o for o in r["orders"] if o["buy_before"])
    assert client.post(f"/api/backlog/{target['quote_id']}/buy-now").json()["material_bought_on"] == TODAY
    again = client.post(f"/api/backlog/{target['quote_id']}/buy-now")
    assert again.status_code == 400 and "already bought" in again.json()["detail"]
    assert client.post(f"/api/backlog/{target['quote_id']}/undo-buy").json()["material_bought_on"] is None
