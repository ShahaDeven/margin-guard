from margin_guard.config import AS_OF


def test_counts(conn):
    count = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    assert count("SELECT COUNT(*) FROM materials") == 12
    assert count("SELECT COUNT(*) FROM parts") == 40
    assert count("SELECT COUNT(*) FROM customers") == 24
    assert count("SELECT COUNT(*) FROM quotes WHERE status = 'open'") == 150
    assert count("SELECT COUNT(*) FROM quotes WHERE status <> 'open'") == 120
    assert count("SELECT COUNT(*) FROM inbox_emails WHERE status = 'new'") == 15


def test_open_quotes_are_still_valid(conn):
    expired = conn.execute(
        "SELECT COUNT(*) FROM quotes WHERE status = 'open' AND valid_until < ?", (AS_OF.isoformat(),)
    ).fetchone()[0]
    assert expired == 0


def test_seed_is_deterministic(conn, tmp_path):
    from margin_guard import db, seed
    other = db.connect(tmp_path / "again.db")
    seed.build(other)
    q = "SELECT quote_id, part_id, qty, unit_price FROM quote_lines ORDER BY id"
    assert [tuple(r) for r in conn.execute(q)] == [tuple(r) for r in other.execute(q)]


def test_quotes_before_oct_1_use_old_epdm60_cost(conn):
    # EPDM 60 moved 1.98 -> 2.05 on Oct 1; quotes issued earlier carry the old basis.
    rows = conn.execute(
        """SELECT q.issued_date, ql.material_cost_basis FROM quote_lines ql
           JOIN quotes q ON q.id = ql.quote_id WHERE ql.part_id = 'P-1002'"""
    ).fetchall()
    assert rows, "expected at least one quote for the EPDM 60 window gasket"
    for r in rows:
        cost = 1.98 if r["issued_date"] < "2026-10-01" else 2.05
        assert r["material_cost_basis"] == round(0.18 * 1.05 * cost, 4)


def test_quoted_margins_are_sane(conn):
    for r in conn.execute("SELECT unit_price, material_cost_basis, conversion_cost FROM quote_lines"):
        margin = 1 - (r["material_cost_basis"] + r["conversion_cost"]) / r["unit_price"]
        assert 0.2 < margin < 0.36
