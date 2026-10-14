"""The Phase 7 reconciliation counts (pure part of scripts/reconcile_epus_medisy.py). Fictional NIKs only."""
from scripts.reconcile_epus_medisy import reconcile_day


def visit(nik, *, ckg=True, shared=False):
    return {"visit_id": 1, "nik": nik, "nik_shared": shared, "is_ckg": ckg}


def test_counts_and_set_differences():
    legacy = [("A", True), ("B", False), ("C", True)]
    visits = [visit("A"), visit("D", ckg=False), visit(None), visit("00", shared=True), visit("00", shared=True)]
    r = reconcile_day(legacy, visits)
    assert (r["legacy_rows"], r["legacy_ckg"]) == (3, 2)
    assert (r["medisy_visits"], r["medisy_ckg"], r["medisy_with_nik"], r["medisy_no_nik"]) == (5, 4, 4, 1)
    assert r["medisy_shared_niks"] == 1                       # one number, flagged twice
    assert r["both"] == 1 and r["legacy_only"] == ["B", "C"] and r["medisy_only"] == ["D"]


def test_a_shared_nik_never_counts_as_a_match_or_as_medisy_only():
    r = reconcile_day([("00", False)], [visit("00", shared=True)])
    assert r["both"] == 0 and r["legacy_only"] == ["00"] and r["medisy_only"] == []


def test_an_empty_day():
    r = reconcile_day([], [])
    assert r["legacy_rows"] == 0 and r["medisy_visits"] == 0 and r["both"] == 0
