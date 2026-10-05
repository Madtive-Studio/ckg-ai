"""Coverage hunt-list engine: bucket assignment invariants.

A wrong bucket here fails silently in production — a mapped question that
re-appears as open wastes every run's hunting on it, and a sourceless question
marked mapped silently stops being hunted. These tests pin the bucketing
against the repo's real mapping json, MEDISY_BREADCRUMBS and ledger (all
offline, deterministic). The ledger's sourceless / lead entries describe ePuskesmas
(``"source": "epus"``) and are ignored for the Medisy hunt; the tests that pin
those buckets pass ``ledger_source="epus"``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.coverage_hunt import build, render_markdown  # noqa: E402


def _open_labels(result) -> set[str]:
    return {
        q["label"]
        for form in result["open_by_form"]
        for q in form["questions"]
    }


def test_totals_reconcile():
    result = build()
    assert sum(result["totals"].values()) == result["total_questions"]
    assert result["total_questions"] == 565


def test_mapped_question_is_never_open():
    from app.services.medisy_to_asik import MEDISY_BREADCRUMBS

    result = build()
    open_pairs = {
        (form["form"].strip().casefold(), q["label"].strip().casefold())
        for form in result["open_by_form"]
        for q in form["questions"]
    }
    for form_key, fmap in MEDISY_BREADCRUMBS.items():
        if form_key == "identitas_pasien":
            continue
        for label, path in fmap.items():
            if not path:
                continue
            pair = (form_key.strip().casefold(), label.strip().casefold())
            assert pair not in open_pairs, (
                f"{label!r} has a breadcrumb under {form_key!r} but that "
                "(form, question) sits in the open list — the matcher is "
                "missing its mapped bucket"
            )


def test_known_sourceless_stays_out_of_open():
    result = build(ledger_source="epus")
    open_labels = _open_labels(result)
    for marker in ("KPSP", "M-CHAT"):
        assert not any(marker.lower() in lbl.lower() for lbl in open_labels), (
            f"a {marker} question is open but its family is documented sourceless"
        )
    assert result["totals"]["documented_sourceless"] > 0


def test_spec_only_alternate_not_open():
    result = build()
    assert not any(
        "riwayat hipertensi" in form["form"].lower()
        for form in result["open_by_form"]
    )


def test_lead_stays_open_and_is_annotated():
    result = build(ledger_source="epus")
    open_labels = _open_labels(result)
    pjb = [f for f in result["open_by_form"] if f["form"] == "Pemeriksaan PJB"]
    assert pjb, "PJB questions must stay open — a lead never removes a question"
    assert all(q["label"] in open_labels for f in pjb for q in f["questions"])
    lead_ids = {lead["id"] for lead in result["leads"]}
    assert "lead-pjb-pulse-ox" in lead_ids


def test_ledger_tokens_match_any_not_all():
    result = build(ledger_source="epus")
    open_labels = _open_labels(result)
    for marker in ("KPSP", "GPPH", "KMPE"):
        assert not any(
            marker.lower() in lbl.lower() for lbl in open_labels
        ), f"{marker} matched by a different single token of the same entry"


def test_deleted_questions_are_counted_not_hunted():
    result = build()
    assert result["totals"]["deleted"] > 0


def test_epus_era_entries_do_not_hide_questions_from_the_medisy_hunt():
    result = build()
    assert result["totals"]["documented_sourceless"] == 0 and not result["leads"]
    assert any("kpsp" in lbl.lower() or "m-chat" in lbl.lower() for lbl in _open_labels(result)), (
        "a question documented as sourceless for ePuskesmas must be hunted again for Medisy"
    )


def test_render_markdown_sections():
    text = render_markdown(build(ledger_source="epus"))
    assert "## OPEN questions" in text
    assert "## Known leads" in text
    assert "OPEN — hunt these" in text


def test_committed_mapping_json_agrees_with_the_hunt_list_on_what_is_mapped():
    """The mapping page and the hunt list read the same breadcrumbs: ``build_mapping.py --refresh`` keeps them in step."""
    import json

    from app.services.coverage_hunt import MAPPING_PATH

    forms = json.loads(MAPPING_PATH.read_text())["forms"]
    covered = sum(q["covered_by_converter"] for f in forms for q in f["questions"] if q.get("status_2026") != "Dihapus")
    assert covered == build()["totals"]["mapped"], "run: python backend/app/data/build_mapping.py --refresh"
