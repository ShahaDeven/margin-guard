"""Margin leakage on won jobs: the numbers add up, gaps are flagged, not guessed."""

import pytest

from margin_guard import leakage
from margin_guard.config import AS_OF
from margin_guard.money import D


@pytest.fixture
def report(conn):
    return leakage.analyze(conn)


def _won_job_with(conn, material_id):
    """A won quote with a single-material part using `material_id`."""
    row = conn.execute(
        """SELECT q.id, ql.part_id FROM quotes q JOIN quote_lines ql ON ql.quote_id = q.id
           JOIN part_materials pm ON pm.part_id = ql.part_id
           WHERE q.status = 'won' AND pm.material_id = ?
             AND (SELECT COUNT(*) FROM part_materials x WHERE x.part_id = ql.part_id) = 1
           ORDER BY q.id LIMIT 1""", (material_id,)).fetchone()
    assert row, f"seed needs a won quote with a {material_id}-only part"
    return row["id"]


def test_every_won_job_is_analyzed(conn, report):
    won = conn.execute("SELECT COUNT(*) FROM quotes WHERE status = 'won'").fetchone()[0]
    assert report["won_jobs"] == won and not report["skipped_jobs"]
    for j in report["jobs"]:
        assert j["issued_date"] <= j["ordered_date"] < AS_OF.isoformat()


def test_the_seeded_shop_leaks_margin(report):
    assert report["leaked_usd"] > 0 and report["jobs_leaked"] > 0
    assert report["margin_realized"] < report["margin_quoted"]


def test_totals_add_up(report):
    jobs = report["jobs"]
    assert D(report["leaked_usd"]) - D(report["gained_usd"]) == D(report["net_leaked_usd"])
    assert abs(sum(D(j["leak_usd"]) for j in jobs) - D(report["net_leaked_usd"])) <= D("0.01") * len(jobs)
    by_material = sum(D(m["leak_usd"]) for m in report["by_material"])
    residual = sum(D(j["basis_difference_usd"]) for j in jobs)
    assert abs(by_material + residual - D(report["net_leaked_usd"])) <= D("0.01") * len(jobs)
    assert sum(D(m["leak_usd"]) for m in report["by_month"]) == pytest.approx(D(report["net_leaked_usd"]),
                                                                                abs=D("0.01") * len(jobs))


def test_no_cost_move_means_no_leak(conn):
    qid = _won_job_with(conn, "MAT-FKM-75")
    conn.execute("UPDATE quotes SET ordered_date = issued_date WHERE id = ?", (qid,))
    j = next(j for j in leakage.analyze(conn)["jobs"] if j["quote_id"] == qid)
    assert abs(j["leak_usd"]) <= 0.01 and not j["by_material"]


def test_leak_is_quantity_times_the_cost_move(conn):
    qid = _won_job_with(conn, "MAT-FKM-75")
    q = conn.execute("SELECT issued_date FROM quotes WHERE id = ?", (qid,)).fetchone()
    # Order 10 days after the quote, with a $1.00/lb increase in between.
    conn.execute("UPDATE quotes SET ordered_date = date(issued_date, '+10 days') WHERE id = ?", (qid,))
    before = conn.execute("SELECT cost_per_lb FROM material_price_history WHERE material_id = 'MAT-FKM-75'"
                          " AND effective_date <= ? ORDER BY effective_date DESC LIMIT 1", (q[0],)).fetchone()[0]
    conn.execute("DELETE FROM material_price_history WHERE material_id = 'MAT-FKM-75'"
                 " AND effective_date > ? AND effective_date <= date(?, '+10 days')", (q[0], q[0]))
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-FKM-75', 'V-FLT', ?, date(?, '+5 days'))", (before + 1.0, q[0]))
    j = next(j for j in leakage.analyze(conn)["jobs"] if j["quote_id"] == qid)
    expected = sum(D(r["qty"]) * D(r["lb_per_unit"]) * (1 + D(r["scrap_rate"])) for r in conn.execute(
        """SELECT ql.qty, pm.lb_per_unit, pm.scrap_rate FROM quote_lines ql
           JOIN part_materials pm ON pm.part_id = ql.part_id
           WHERE ql.quote_id = ? AND pm.material_id = 'MAT-FKM-75'""", (qid,)))
    assert D(j["by_material"]["MAT-FKM-75"]) == pytest.approx(expected, abs=D("0.01"))


def test_decreases_count_as_gains(conn):
    qid = _won_job_with(conn, "MAT-FKM-75")
    q = conn.execute("SELECT issued_date FROM quotes WHERE id = ?", (qid,)).fetchone()
    conn.execute("UPDATE quotes SET ordered_date = date(issued_date, '+10 days') WHERE id = ?", (qid,))
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-FKM-75', 'V-FLT', 1.00, date(?, '+5 days'))", (q[0],))
    r = leakage.analyze(conn)
    j = next(j for j in r["jobs"] if j["quote_id"] == qid)
    assert j["leak_usd"] < 0 and r["gained_usd"] >= -j["leak_usd"]


def test_below_floor_means_pushed_below_by_the_cost_move(report):
    for j in report["jobs"]:
        assert j["below_floor"] == (j["margin_realized"] < j["margin_floor"] <= j["margin_quoted"])


def test_alternate_supplier_prices_do_not_leak(conn):
    qid = _won_job_with(conn, "MAT-EPDM-70")
    before = next(j for j in leakage.analyze(conn)["jobs"] if j["quote_id"] == qid)
    q = conn.execute("SELECT issued_date FROM quotes WHERE id = ?", (qid,)).fetchone()
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-EPDM-70', 'V-KRD', 9.99, date(?, '+1 day'))", (q[0],))
    after = next(j for j in leakage.analyze(conn)["jobs"] if j["quote_id"] == qid)
    assert after["leak_usd"] == before["leak_usd"]


def test_missing_history_is_flagged_not_guessed(conn):
    conn.execute("DELETE FROM material_price_history WHERE material_id = 'MAT-FKM-75'")
    r = leakage.analyze(conn)
    skipped = {s["quote_id"] for s in r["skipped_jobs"]}
    assert skipped and all("MAT-FKM-75" in s["materials"] for s in r["skipped_jobs"])
    assert not skipped & {j["quote_id"] for j in r["jobs"]}


def test_lost_and_open_quotes_are_not_jobs(conn, report):
    ids = {j["quote_id"] for j in report["jobs"]}
    other = {r[0] for r in conn.execute("SELECT id FROM quotes WHERE status <> 'won'")}
    assert not ids & other


def test_report_prints_on_a_windows_console(report):
    leakage.report_markdown(report).encode("cp1252")


def test_api_serves_the_report(conn, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", conn)
    with TestClient(api.app) as c:
        body = c.get("/api/leakage").json()
    assert body["won_jobs"] > 0 and "assumption" in body
