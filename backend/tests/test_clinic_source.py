"""clinic_source: one stored column holds Medisy bundles AND legacy EPUS blobs; consumers must get the right behaviour for each."""
from app.services import clinic_source as cs
from app.services.epus_to_asik import EPUS_BREADCRUMBS
from app.services.medisy_to_asik import MEDISY_BREADCRUMBS
from app.tasks import merge

MEDISY = {
    "api_version": 1,
    "visit": {"id": 1, "date": "2026-09-02", "room": {"id": 1, "name": "CKG"}},
    "patient": {"name": " Budi Fiktif ", "gender": "L", "age": {"years": 50, "months": 0, "days": 0},
                "identity": {"type": "NIK", "number": "3201000000000001"}, "phone": "081234567890",
                "address": {"text": "JL.  CONTOH\n NO 1"}, "marital_status": "SUDAH MENIKAH"},
    "anamnesis": {"vitals": {"systole": 120, "diastole": 80}},
}
EPUS = {"data_pasien": {"NIK": "3201000000000002", "Nama Pasien": "Siti EPUS", "Nama": "ignored", "No Telp / HP": "0812999",
                        "Alamat": "JL. LAMA   1", "Status Perkawinan": "Kawin", "Jenis Kelamin": "P", "Umur": "30 Tahun"},
        "tabs": {}}


def test_dispatch_picks_the_converter_by_the_shape_of_the_blob():
    assert cs.clinic_to_asik(MEDISY)["Tekanan Darah Dewasa Lansia"]["Tekanan Darah Sistolik"] == 120
    epus_out = cs.clinic_to_asik(EPUS)
    assert epus_out["identitas_pasien"]["Nama"] == "Siti EPUS"
    assert cs.clinic_to_asik(None) == {} and cs.clinic_to_asik({}) == {}


def test_breadcrumbs_follow_the_blob():
    assert cs.breadcrumbs_for(MEDISY) is MEDISY_BREADCRUMBS
    assert cs.breadcrumbs_for(EPUS) is EPUS_BREADCRUMBS and cs.breadcrumbs_for(None) is EPUS_BREADCRUMBS


def test_registration_fields_from_a_medisy_bundle():
    assert cs.clinic_name(MEDISY) == "Budi Fiktif"
    assert cs.clinic_phone(MEDISY) == "081234567890"
    assert cs.clinic_address(MEDISY) == "JL. CONTOH NO 1"
    assert cs.clinic_marital_status(MEDISY) == "Menikah"
    assert cs.clinic_is_disabled(MEDISY) is False                      # Medisy does not record it


def test_registration_fields_from_a_legacy_epus_blob_are_unchanged():
    assert cs.clinic_name(EPUS) == "Siti EPUS"                         # only "Nama Pasien", as before
    assert cs.clinic_phone(EPUS) == "0812999"
    assert cs.clinic_address(EPUS) == "JL. LAMA 1"
    assert cs.clinic_marital_status(EPUS) == "Menikah"
    assert cs.clinic_name({}) is None and cs.clinic_phone(None) is None and cs.clinic_address({}) is None


def test_the_merge_form_lookup_is_the_same_set_as_before_it_stopped_importing_the_epus_converter():
    assert set(merge._SLUG_TO_FORM.values()) == set(EPUS_BREADCRUMBS)


def test_merge_writes_the_source_path_of_the_right_converter():
    def merged():
        return {"sections": {merge._slugify_form("Tekanan Darah Dewasa Lansia"): [{"merged_key": "Tekanan Darah Sistolik"}]}}

    medisy_item = merge._overwrite_epus_questions(merged(), MEDISY_BREADCRUMBS)["sections"]
    assert "anamnesis.vitals.systole" in next(iter(medisy_item.values()))[0]["epus_question"]
    legacy_item = merge._overwrite_epus_questions(merged())["sections"]                 # default = the EPUS table, as before
    assert "Periksa Fisik" in next(iter(legacy_item.values()))[0]["epus_question"]
