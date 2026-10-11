from margin_guard.catalog import normalize_name, resolve_material


def test_normalize_strips_noise_words_and_splits_codes():
    assert normalize_name("EPDM 70 duro compound") == "epdm 70"
    assert normalize_name("EPDM70") == "epdm 70"
    assert normalize_name("N-550") == normalize_name("N550")


def test_exact_alias(conn):
    m = resolve_material(conn, "Buna-N 90")
    assert (m.material_id, m.method) == ("MAT-NBR-90", "exact")


def test_containment_picks_most_specific_alias(conn):
    m = resolve_material(conn, "C1018 cold rolled bar", vendor_id="V-BSS")
    assert m.material_id == "MAT-STL-1018"
    m = resolve_material(conn, "Neoprene 60 (CR 60)", vendor_id="V-GLE")
    assert m.material_id == "MAT-CR-60"


def test_vendor_narrows_shared_alias(conn):
    # "Black 70" is both EPDM 70 and NBR 70; Midwest only sells the EPDM.
    m = resolve_material(conn, "Black 70", vendor_id="V-MWP")
    assert m.material_id == "MAT-EPDM-70"


def test_shared_alias_from_distributor_is_ambiguous(conn):
    # Keystone sells both, so this must go to a person.
    m = resolve_material(conn, "Black 70", vendor_id="V-KRD")
    assert m.material_id is None
    assert m.method == "ambiguous"
    assert set(m.candidates) == {"MAT-EPDM-70", "MAT-NBR-70"}


def test_unknown_material(conn):
    m = resolve_material(conn, "polyurethane 95A")
    assert m.material_id is None
