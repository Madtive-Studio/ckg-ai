"""Medisy records never get an invented measurement / clinical answer for a required ASIK question (owner decision 2026-10-14).

The legacy behaviour (EPUS lineage) is unchanged: the default map still fills required questions there.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


def test_only_a_medisy_record_turns_the_clinical_defaults_off():
    medisy = {"api_version": 1, "visit": {}}
    with patch.object(sync_task.patient_crud, "decrypt_field", return_value=medisy), patch.object(sync_task, "is_medisy_blob", return_value=True):
        assert sync_task._clinical_defaults_allowed(SimpleNamespace()) is False
    with patch.object(sync_task.patient_crud, "decrypt_field", return_value={"data_pasien": {}}):
        assert sync_task._clinical_defaults_allowed(SimpleNamespace()) is True
    with patch.object(sync_task.patient_crud, "decrypt_field", side_effect=ValueError("boom")):
        assert sync_task._clinical_defaults_allowed(SimpleNamespace()) is True
