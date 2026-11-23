"""Safe defaults for required ASIK questions with no data.

Since 2026-11-23 every record (Medisy, EPUS lineage, ASIK-only) gets the same default fills (owner decision: one rule for
all clinic sources). The scraper's `clinical=False` mode (free-text placeholder only) is kept but no longer selected.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SCRAPER_SESSION_DIR", "/tmp/_asik_sync_test_session")
ROOT = Path(__file__).resolve().parents[2] / "scrapers"
sys.path.insert(0, str(ROOT / "asik"))
sys.path.insert(0, str(ROOT / "asik_sync"))

import sync  # noqa: E402

from app.tasks import sync as sync_task  # noqa: E402

NUMBER = {"label": "Berat Badan", "kind": "number", "dataName": "q1"}
RADIO = {"label": "Apakah Anda merokok?", "kind": "radio", "options": ["Ya", "Tidak"], "dataName": "q2"}
DROPDOWN = {"label": "Pilih satu", "kind": "dropdown", "options": ["Normal", "Abnormal"], "dataName": "q3"}
TEXT = {"label": "Catatan", "kind": "text", "dataName": "q4"}
DEFAULTS = {"berat badan": {"value": 60, "kind": "number"}}


def test_legacy_mode_still_defaults_a_measurement_and_an_option():
    assert sync._resolve_default(NUMBER, DEFAULTS) == 60
    assert sync._resolve_default(RADIO, DEFAULTS) == "Tidak"


def test_medisy_mode_never_invents_a_measurement_or_an_answer():
    for q in (NUMBER, RADIO, DROPDOWN):
        assert sync._resolve_default(q, DEFAULTS, clinical=False) is None


def test_medisy_mode_still_fills_a_free_text_placeholder():
    assert sync._resolve_default(TEXT, DEFAULTS, clinical=False) == "-"


def test_every_record_gets_the_same_default_fills():
    cfg = sync_task._build_config(
        asik_creds={}, base_url="https://a", nik="1", merged_data={}, captcha_solver={},
    )
    assert cfg.get("clinical_defaults", True) is True  # the scraper reads a missing key as True
