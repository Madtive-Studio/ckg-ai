"""Indonesian labels for enum values that appear inside user-facing messages (API errors, job logs).

The API and database keep their English enum values (`epus`, `failed`, ...); only the text a person reads is translated.
The clinic-record source is Medisy — never show "EPUS" to users.
"""

_STATUS = {
    "pending": "menunggu",
    "running": "berjalan",
    "success": "berhasil",
    "failed": "gagal",
    "cancelled": "dibatalkan",
    "covered": "tercakup",
    "no_data": "tidak ada data",
    "needs_review": "perlu ditinjau",
    "merged": "digabung",
    "pr_rejected": "PR ditolak",
    "changes_ready": "perubahan siap",
    "bad_creds": "kredensial salah",
}

_SOURCE = {"asik": "ASIK", "epus": "Medisy", "asik_sekolah": "CKG Sekolah"}


def status_label(value: str) -> str:
    return _STATUS.get(value, value)


def source_label(value: str) -> str:
    return _SOURCE.get(value, value)
