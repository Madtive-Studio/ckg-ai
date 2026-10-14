# Medisy → ASIK Conversion Rules

Reference for `medisy_to_asik.py` (the deterministic converter for the clinic-record source after the ePuskesmas → Medisy migration; see `MEDISY_MIGRATION.md`). Input: one stored Medisy visit bundle (`scraped_epus_data`, shape from himed-app `GET /medisy_api/ckg/visits/{id}` / `/visits/batch`). Output: `{asik_form: {asik_label: value}}`.

> **Validation status (2026-10-05) — read before relying on it.**
> - Verified: 0 form/label drift against the canonical mapping (`audit_coverage.py --source medisy`), 0 converter exceptions and 0 emitted fields without a breadcrumb over 786 real UAT bundles, 51 converter test functions.
> - **Not verified:** value-for-value agreement with what ASIK actually holds for the same patient (`verify_converter.py`). It needs patients that have BOTH a Medisy blob and an ASIK blob, and none exist yet (the UAT Medisy data is not in ASIK). Run `verify_converter.py --source medisy --column scraped_epus_data` once real matched patients exist.
> - The ASIK label list (`asik_form_labels.py`) was generated from the repo's canonical mapping, not from a fresh live ASIK dump (no ASIK access during this work).
> - UAT data is thin: most screenings are empty, so the screening mappings (PUMA, SKILAS, Barthel, SPPB, MNA, kanker paru…) are exercised mainly by synthetic bundles built from Medisy's own templates, not by real answers.

## 1. Gating (which forms are emitted)

Same klaster logic as the EPUS converter, read from `patient.gender` (1 = Laki-laki, 2 = Perempuan) and `patient.age.years`.

| Condition | Result |
|---|---|
| bundle has no identity | `{}` |
| gender or age missing | `identitas_pasien` only |
| age < 18 | pediatric battery only (+ identitas) |
| every adult | Tekanan Darah, Gula Darah, Gizi (by sex), Demografi (by sex/age), Telinga & Mata (18-39 / ≥40), TB risk + exam, HIV, Sifilis, Hepatitis, dental, shells for forms Medisy cannot fill |
| ≥ 40 | PUMA, lab forms (lipid, kidney, albuminuria, SGOT/trombosit) |
| ≥ 45 | kanker paru, EKG, kanker usus shells |
| < 45 with HT/DM | EKG |
| ≥ 60 | SKILAS ×4, Barthel, Mini-Cog, SPPB, MNA-SF (+ shells for AD-8, depression follow-up) |
| female ≥ 30 | HPV-DNA shell; Kanker Leher Rahim and Skrining Kanker Payudara (filled when Medisy has the answers) |
| female (adult) | catin Hb, tetanus |

An eligible form that Medisy cannot fill is an empty `{}` shell so the convert preview still shows it; the merge keeps the ASIK value.

## 2. Global rules

- **Zero hallucination.** Every emitted value traces to a bundle field (`MEDISY_BREADCRUMBS`). Not captured = absent (blank), never a default.
- **R-ZERO.** Medisy's int-coded screenings (PUMA …) are NULLABLE with DEFAULT 0, so 0 means "No" *or* "never answered". A 1 is always trusted. A 0 becomes "Tidak" only when the same row has at least one positive answer; an all-zero row emits nothing. Text-coded answers have no such problem.
- **R-UNIFORM.** The hipertensi / diabetes / risiko-jantung questionnaires have a "check to all" button. A row whose answers (≥ 4) are all identical is untrusted for single-question mappings (history of hypertension / diabetes).
- **R-DIAG.** A diagnosis only turns a result ON (HIV/hepatitis/syphilis → "Reaktif", TB, DM). Absence of a diagnosis is never turned into "Non Reaktif" / "Tidak". A lab result, when present, wins over the diagnosis.
- **R-NOMATCH.** No mapping where the two systems ask different questions (see §4).
- Latest screening entry wins (by `performed_at`).
- Numbers: decimal comma/dot tolerated; option text matched after folding case, whitespace, dashes and commas — wording is never fuzzed.
- NIK: `type_identitas` ∈ {1, KTP, NIK} and non-empty; no format validation (ASIK validates). Untyped numbers are not NIKs.

## 3. Per-form notes

See the generated table in §6 for the field-by-field source. Rules that need explaining:

- **Tekanan Darah / Gula Darah (adult):** BP and GDS/GDP from `anamnesis.vitals` first, the screening row as fallback. "History of hypertension/diabetes" comes from the hipertensi / diabetes questionnaire (R-UNIFORM applies).
- **PUMA:** questions from `screenings[puma]`; smoking pack-years bucketed to ASIK's options; R-ZERO, with one addition (sign-off 2026-10-05): an all-zero row whose `updated_at` is later than its `performed_at` (saved again after it was created) counts as answered and becomes "Tidak". On UAT that is 9 of 1,727 rows; the other all-zero rows stay blank.
- **Telinga:** the hearing phase of the PTM program (`programs.ptm.fase_pendengaran`).
- **Mata** (`screenings[ptm_mata]`, the "Pemeriksaan Fisik" eye card): visus is entered as a Snellen fraction (`visus_<side>` / `visus_<side>_denominator`). The ratio decides: 6/12 (0.5) or better in every measured eye = Normal; worse in any eye = Curiga. Pupil: only Medisy's "Suspek Katarak" (`OV000393`) becomes "Curiga Katarak"; any other pupil entry or none stays blank (R-DIAG: no "Normal" is invented).
- **PTM risk-factor questionnaire** (`programs.ptm_questionnaire`; the "Faktor Risiko Penyakit Tidak Menular" modal; SATUSEHAT Q0013 / Q0019 / Q0020, matched by answer CODE, the text is only a fallback): smoking status (1.4 Smoker → Ya, Non-smoker → Tidak; an ex-smoker counts as a non-smoker, as in the ePuskesmas converter; with no status, "never smoked" 1.1 = 0 → Tidak), exposure to smoke (1.5), lung-cancer questionnaire (Q0019 → the screening form, the table `screenings[kanker_paru]` wins on conflict, and 4 questions of "Penapisan Risiko Kanker Paru"), colorectal family history (Q0020 1.1), physical activity (1.10, **inherited rule**: insufficient → no moderate / vigorous exercise, sufficient → moderate "Ya", exactly what the ePuskesmas converter did with the same PTM question).
- **TB:** cough "Tidak" → "Tidak batuk"; cough "Ya" → "Ya, lebih dari 2 minggu" (clinical sign-off 2026-10-05: Medisy has no duration column and a "Ya" means more than 2 weeks). Contact: only "Tidak Ada" is placed. The adult X-Ray form also takes BB turun, demam, berkeringat and the radiograph question.
- **HIV / Sifilis / Hepatitis:** lab result first (`ANTI HIV`, `sifilis`, `HBsAg`, `Anti HCV`), else the ICD code → "Reaktif" (R-DIAG).
- **Lab forms (≥ 40):** lipid, kidney (creatinine, urea, eGFR), microalbuminuria, SGOT + platelets; Hb only for the female catin form.
- **Kanker paru:** `screenings[kanker_paru]` answers; option q5 only where the meaning is identical.
- **EKG:** `risiko_jantung.kardiovaskular_ekg`.
- **SKILAS malnutrition:** SKILAS's own answers first; Medisy's nutrition screening (`screenings[gizi]`) fills the two matching questions only where unambiguous (sign-off 2026-10-05): weight loss none → Tidak, "not sure (clothes loose)" / 6 kg or more → Ya, "1-5 kg" blank (straddles the 3 kg line; Medisy asks about 6 months, SKILAS about 3); reduced intake from lack of appetite Ya → Ya, Tidak stays blank (SKILAS also asks about difficulty eating).
- **SKILAS / Barthel / Mini-Cog / SPPB / MNA-SF:** each from its own Medisy table; Barthel maps the item score to the ASIK option; SPPB and MNA-SF map option text through explicit tables.
- **Tetanus:** only T2 or higher → "minimal dua kali". Below T2 stays blank (ASIK has no "belum" option).
- **Dental:** `gigi_dewasa` question 3 / 4 → caries / missing-tooth. Periodontal: see the next bullet.
- **ASIK CKG columns** (added in Medisy by `db/2026/20261013-add-ilp-screening-fields`; every column is NULL until a nurse answers, so a missing value is never sent and a `0` is never trusted, except exhaled CO where 0 ppm is a real reading):
  - Blood pressure: `hipertensi.sistole_2` / `diastole_2` → second reading; `lama_hipertensi_bulan` → months since diagnosis **only when the history answer is Ya** (ASIK reveals it only then).
  - Glucose: `diabetes_melitus.gds_2` → GDS 2; `gula_darah_2jam_pp` → 2-hour PP; `lama_diabetes_bulan` → months (only when the history answer is Ya).
  - TB: `tbc.pembesaran_kgb` Ya/Tidak → lymph-node question of the adult X-Ray form; `metode_pemeriksaan_tb` → "TCM" or "BTA" (BTA Mikroskopis). "Foto Toraks" and "Pemeriksaan Klinis" have no ASIK option and are not sent.
  - Periodontal form: `gigi_goyang` Ya/Tidak; `penyakit_periodontal` Tidak Ada → Tidak, Gingivitis / Periodontitis → Ya (the ePuskesmas converter reads gum inflammation the same way). Adult screening first, elderly screening as fallback.
  - Lung: `kanker_paru.riwayat_merokok_15th` and `gejala_kanker_paru` → the two matching questions of "Penapisan Risiko Kanker Paru"; `kadar_co` → "Kadar CO Pernapasan".
  - Breast (women ≥ 30): `risiko_kanker_payudara.checkup_result1` → SADANIS (Tidak ada benjolan → Normal, Benjolan → Ditemukan benjolan, Curiga Kanker → Curiga kanker); `hasil_usg_payudara` → USG (Normal, Kista Simpleks → Simple cyst; "Tumor Jinak (Fibroadenoma)" and "Curiga Keganasan" have no ASIK option and are not sent). "Pemeriksaan yang dilakukan" names SADANIS first, then USG, like the ePuskesmas converter.
  - Cervical (women ≥ 30): `kanker_serviks.pernah_hubungan_seksual` Ya/Tidak.
  - Mental health (PHQ-4): the adult (`kategori_usia` = Dewasa) form of `kesehatan_jiwa` is PHQ-2 (`question1-2`) + GAD-2 (`question3-4`) with the same four options as ASIK, so no new column was needed (an earlier version of this doc said Medisy had no PHQ-4: wrong).
  - Inspekulo / IVA (women ≥ 30): `kanker_serviks.result_of_inspekulo_checkup` (SNOMED 395100000 → Normal, 315266007 → Curiga kanker) only when `is_inspekulo_performed` = 1, and `result_of_iva_checkup` (id 1/5 → Negatif, 2/6 → Positif; servisitis and suspected cancer have no ASIK option) only when `is_iva_performed` = 1. The form pre-selects a result and the controller writes IVA id 5 after a normal speculum exam, so the performed flag is the only trustworthy signal.
  - Mini-Cog follow-up: `pemeriksaan_cog.clock_drawing_test` (else `kk_skilas`) Normal → "Benar", Abnormal → "Salah".
- **Pediatric:** vitals-driven growth, BP, GDS; TB-child from the tbc screening; syphilis only on an A50-A53 diagnosis.

## 4. Deliberately not mapped (R-NOMATCH) and Medisy gaps

| ASIK form / field | Why blank |
|---|---|
| Perilaku Merokok: type, years, cigarettes/day, ex-smoker details | not on the live ASIK form (2 questions); the school-student smoking table is not the adult survey |
| Tingkat Aktivitas Fisik: the other 4 questions | Medisy has one yes/no (insufficient activity) |
| HPV-DNA, kanker usus, AD-8, skin diseases, disabilitas | no Medisy source |
| Kesehatan Jiwa for pregnant adults (EPDS), children and teenagers (SDQ) | different instruments; only the adult PHQ-2 + GAD-2 is PHQ-4 |
| Payudara: breast USG "Tumor Jinak" / "Curiga Keganasan"; TB method "Foto Toraks" / "Klinis" | no matching ASIK option |
| Second BP, GDS 2, months since diagnosis | mapped, but only filled where nurses record them (new Medisy columns, NULL by default) |
| KPSP, KMPE, GPPH, M-CHAT, imunisasi balita, talasemia, birth weight | no Medisy source |
| SKILAS malnutrisi LiLA question | no Medisy source (the `gizi` screening covers the other two, see §3) |

`kk_ckg_log` is ignored (decision D3). Visit-level data with no ASIK target (spo2, heart rate, temperature, prescriptions, procedures, religion, occupation, education, blood type) is unused.

## 5. Clinical sign-off questions

1. ~~Smoking status~~ **Resolved 2026-10-05** — the "Faktor Risiko PTM" modal (questionnaire Q0013) holds it; mapped.
2. ~~Eyes~~ **Resolved 2026-10-05** — the eye card stores Snellen fractions and a coded pupil; mapped (ratio rule + suspected cataract only). Still to confirm: nothing in UAT proves the numerator/denominator order of real entries (the 4 UAT rows look like test data); the rule assumes a correct `6 / 12` entry.
3. ~~TB "Ya" cough~~ **Resolved 2026-10-05** — "Ya" means more than 2 weeks → "Ya, lebih dari 2 minggu".
4. ~~PUMA evidence rule~~ **Resolved 2026-10-05** — keep R-ZERO, plus: an all-zero row saved again after creation counts as answered.
5. ~~Medisy `gizi` screening → SKILAS malnutrisi~~ **Resolved 2026-10-05** — unambiguous answers only (see §3).
6. ~~Dashboard "tertatalaksana" flags~~ **Resolved 2026-10-05** — still PROXIES, with the education part pinned to Medisy's education form (`edukasi_term` select or `edukasi` text, `tambah_tindakan_tpl.php`): drug = an antihypertensive / antidiabetic / lipid-lowering drug was prescribed at the visit; education = that form is filled.
7. ~~Newborn registry (bayi)~~ **Resolved 2026-10-05** — PJB "Gagal" is a positive screen and `saturasi_tangan` is taken as the right hand; ikterus from the child (MTBM) rows; the external-referral destination from `visit.referral`.
8. ~~Shared / placeholder NIK~~ **Resolved** — decision D13 in `MEDISY_MIGRATION.md`: the API flags `shared`, ckg-ai skips those visits.

9. **Open sign-offs for the ASIK CKG columns (2026-10-14):** (a) periodontal: gingivitis / periodontitis → "Ya"; (b) clock drawing Normal / Abnormal → "Benar" / "Salah"; (c) breast USG options without an ASIK equivalent stay unsent; (d) months since diagnosis are sent only after a "Ya" history answer. Until a clinician confirms (a) and (b), review the first real sends by hand.

Still open: the numerator/denominator order of real eye entries (Q2), and the questions beyond the converter (unmapped ASIK forms with no Medisy table found yet) which the loop agent hunts.

## 6. Field-by-field source (generated)

Generated from `MEDISY_BREADCRUMBS` (invariants in `tests/test_medisy_to_asik.py`); regenerate it when a mapping changes.

### identitas_pasien

| ASIK field | Medisy source |
|---|---|
| NIK | `patient.identity.number (type KTP/NIK, non-empty)` |
| Nama | `patient.name` |
| Tanggal Lahir | `patient.date_of_birth` |
| Tempat Lahir | `patient.place_of_birth` |
| Jenis Kelamin | `patient.gender (1=L, 2=P)` |
| Alamat Domisili | `patient.address.text` |

### Kesehatan Jiwa

| ASIK field | Medisy source |
|---|---|
| Dalam 2 minggu terakhir, seberapa sering anda kurang/ tidak bersemangat dalam melakukan ke | `screenings[kesehatan_jiwa].question1 (kategori_usia Dewasa, PHQ-2)` |
| Dalam 2 minggu terakhir, seberapa sering anda merasa murung, tertekan, atau putus asa? | `screenings[kesehatan_jiwa].question2 (kategori_usia Dewasa, PHQ-2)` |
| Dalam 2 minggu terakhir, seberapa sering anda merasa gugup, cemas, atau gelisah? | `screenings[kesehatan_jiwa].question3 (kategori_usia Dewasa, GAD-2)` |
| Dalam 2 minggu terakhir, seberapa sering anda tidak mampu mengendalikan rasa khawatir? | `screenings[kesehatan_jiwa].question4 (kategori_usia Dewasa, GAD-2)` |

### SKILAS Pemeriksaan Gejala Depresi - Lansia

| ASIK field | Medisy source |
|---|---|
| Apakah dalam 2 minggu terakhir Anda merasa sedih, tertekan, atau putus asa? | `screenings[skilas].question6a` |
| Apakah dalam 2 minggu terakhir Anda sedikit minat atau kesenangan dalam melakukan sesuatu? | `screenings[skilas].question6b` |

### SKILAS Malnutrisi

| ASIK field | Medisy source |
|---|---|
| Apakah berat badan Anda berkurang >3 kg dalam 3 bulan terakhir atau pakaian menjadi lebih  | `screenings[skilas].question3a / screenings[gizi].penurunan_bb (unambiguous answers only)` |
| Apakah Anda hilang nafsu makan Atau mengalami kesulitan makan (misal batuk atau tersedak s | `screenings[skilas].question3b / screenings[gizi].asupan_makanan (Ya only)` |
| Apakah ukuran lingkar lengan atas (LiLA) <21 cm? | `screenings[skilas].question3c` |

### SKILAS Mobilisasi - Lansia

| ASIK field | Medisy source |
|---|---|
| Tes Berdiri di kursi: Berdiri dari kursi lima kali tanpa bantuan tangan. Apakah orang ters | `screenings[skilas].question2` |

### SKILAS Penurunan Kognitif - Lansia

| ASIK field | Medisy source |
|---|---|
| Apakah dapat mengingat tiga kata: bunga, pintu, nasi (contoh)? | `screenings[skilas].question1 (recall outcome)` |
| Tanggal berapakah hari ini secara lengkap (tanggal/bulan/tahun)? atau- Dimanakah Anda saat | `screenings[skilas].question1 (orientation outcome)` |
| Apakah peserta dapat mengingat tiga kata sebelumnya? | `screenings[skilas].question1 (recall outcome)` |

### Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia

| ASIK field | Medisy source |
|---|---|
| Dapat mengendalikan rangsang buang air besar (BAB)? | `screenings[activity_living].question1` |
| Dapat mengendalikan rangsang berkemih/buar air kecil (BAK)? | `screenings[activity_living].question2` |
| Membersihkan diri (seka wajah, sisir rambut, sikat gigi)? | `screenings[activity_living].question3` |
| Penggunaan jamban (keluar masuk jamban, melepas/memakai celana, membersihkan, menyiram)? | `screenings[activity_living].question4` |
| Makan dan Minum (jika makan harus berupa potongan, dianggap dibantu) | `screenings[activity_living].question5` |
| Berubah sikap dari berbaring ke duduk | `screenings[activity_living].question6` |
| Berpindah/berjalan | `screenings[activity_living].question7` |
| Memakai baju | `screenings[activity_living].question8` |
| Naik turun tangga | `screenings[activity_living].question9` |
| Mandi | `screenings[activity_living].question10` |

### Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun

| ASIK field | Medisy source |
|---|---|
| Berat Badan Balita | `anamnesis.vitals.weight_kg` |
| Pengukuran Tinggi Badan (cm) | `anamnesis.vitals.height_cm` |

### Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun

| ASIK field | Medisy source |
|---|---|
| Pengukuran Tinggi Badan (cm) | `anamnesis.vitals.height_cm` |

### Gizi Anak Sekolah

| ASIK field | Medisy source |
|---|---|
| Berat Badan | `anamnesis.vitals.weight_kg` |
| Tinggi Badan | `anamnesis.vitals.height_cm` |

### Tekanan Darah Anak dan Remaja

| ASIK field | Medisy source |
|---|---|
| Tekanan Darah Sistol | `anamnesis.vitals.systole` |
| Tekanan Darah Diastol | `anamnesis.vitals.diastole` |

### Pemeriksaan Gula Darah Anak

| ASIK field | Medisy source |
|---|---|
| Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter? | `diagnoses / history.diagnoses ICD E10-E14 (R-DIAG: only turns 'Ya' on)` |
| Gula Darah Sewaktu (GDS) | `anamnesis.vitals.gds` |

### Pemeriksaan Gula Darah Remaja

| ASIK field | Medisy source |
|---|---|
| Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter? | `diagnoses / history.diagnoses ICD E10-E14 (R-DIAG: only turns 'Ya' on)` |
| Gula Darah Sewaktu (GDS) | `anamnesis.vitals.gds` |

### Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)

| ASIK field | Medisy source |
|---|---|
| Apakah berat badan anak Anda turun tanpa penyebab jelas/ BB tidak naik dalam 2 bulan sebel | `screenings[tbc].bb_turun` |
| Apakah anak anda mengalami demam hilang timbul tanpa sebab yang jelas lebih dari 2 minggu? | `screenings[tbc].demam` |
| Apakah dilakukan pemeriksaan radiografi toraks? | `screenings[tbc].pemeriksaan_foto_toraks / abnormalitas_tbc` |

### Pemeriksaan Tuberkulosis Anak

| ASIK field | Medisy source |
|---|---|
| Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)? | `screenings[tbc].kontak_tbc (only 'Tidak Ada')` |

### Berat Lahir

| ASIK field | Medisy source |
|---|---|
| Berat Badan Saat Ini (usia >24 jam) | `anamnesis.vitals.weight_kg (birth weight has no Medisy source)` |

### Penapisan dan Pemeriksaan Sifilis Anak

| ASIK field | Medisy source |
|---|---|
| Hasil Pemeriksaan Rapid Test Sifilis | `diagnoses / history.diagnoses ICD A50-A53 (R-DIAG)` |

### Tekanan Darah Dewasa Lansia

| ASIK field | Medisy source |
|---|---|
| Apakah Anda pernah dinyatakan tekanan darah tinggi? | `screenings[hipertensi].question1_anamnesis (R-UNIFORM)` |
| Tekanan Darah Sistolik | `anamnesis.vitals.systole (fallback screenings[hipertensi].sistole)` |
| Tekanan darah diastolik | `anamnesis.vitals.diastole (fallback screenings[hipertensi].diastole)` |
| Tekanan Darah Sistolik Ke-2 | `screenings[hipertensi].sistole_2` |
| Tekanan darah diastolik ke-2 | `screenings[hipertensi].diastole_2` |
| Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter? Isi Total Bulan Sejak didiagno | `screenings[hipertensi].lama_hipertensi_bulan (only when the history answer is Ya)` |

### Pemeriksaan Gula Darah Dewasa Lansia

| ASIK field | Medisy source |
|---|---|
| Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter? | `screenings[diabetes_melitus].question5_anamnesis (R-UNIFORM)` |
| Gula Darah Sewaktu (GDS) (mg/dl) | `anamnesis.vitals.gds (fallback screenings[diabetes_melitus].gds_hasil)` |
| Gula Darah Sewaktu Kedua (GDS 2). Lakukan jika hasil GDS 1 Prediabetes (≥140-199mg/dl) ata | `screenings[diabetes_melitus].gds_2` |
| Gula Darah Puasa (GDP) (mg/dl) | `anamnesis.vitals.gdp (fallback screenings[diabetes_melitus].gdp_hasil)` |
| Gula Darah 2 Jam PP (mg/dl) | `screenings[diabetes_melitus].gula_darah_2jam_pp` |
| Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter? Isi Total Bulan Sejak di | `screenings[diabetes_melitus].lama_diabetes_bulan (only when the history answer is Ya)` |

### Gizi (BB - TB - Lingkar Perut) Laki-laki

| ASIK field | Medisy source |
|---|---|
| Berat Badan (Kg) | `anamnesis.vitals.weight_kg (fallback screenings[diabetes_melitus].bb)` |
| Pengukuran Tinggi Badan (cm) | `anamnesis.vitals.height_cm (fallback screenings[diabetes_melitus].tb)` |
| Pengukuran Lingkar Perut | `anamnesis.vitals.waist_cm (fallback screenings[diabetes_melitus].lingkar_perut)` |

### Gizi (BB - TB - Lingkar Perut) Perempuan

| ASIK field | Medisy source |
|---|---|
| Berat Badan (Kg) | `anamnesis.vitals.weight_kg (fallback screenings[diabetes_melitus].bb)` |
| Pengukuran Tinggi Badan (cm) | `anamnesis.vitals.height_cm (fallback screenings[diabetes_melitus].tb)` |
| Pengukuran Lingkar Perut | `anamnesis.vitals.waist_cm (fallback screenings[diabetes_melitus].lingkar_perut)` |

### Pemeriksaan PPOK (Skrining PUMA)

| ASIK field | Medisy source |
|---|---|
| Apakah anda sedang/mempunyai riwayat merokok? | `screenings[puma].question_child_3_* (R-ZERO)` |
| Apakah Anda pernah merasa napas pendek ketika berjalan lebih cepat pada jalan yang datar a | `screenings[puma].question4 (R-ZERO)` |
| Apakah Anda biasanya mempunyai dahak yang berasal dari paru atau kesulitan mengeluarkan da | `screenings[puma].question5 (R-ZERO)` |
| Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu? | `screenings[puma].question6 (R-ZERO)` |
| Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk melakukan pemeriksaan sp | `screenings[puma].question7 (R-ZERO)` |
| Jika Perokok Aktif, berapa bungkus per tahun? | `screenings[puma].question_child_3_3 (smokers only)` |

### Demografi Dewasa Perempuan

| ASIK field | Medisy source |
|---|---|
| Status Perkawinan | `patient.marital_status` |
| Apakah Anda sedang hamil? | `programs.kia.hamil (an active record turns it on; absence is not 'Tidak')` |

### Demografi Dewasa Laki-Laki

| ASIK field | Medisy source |
|---|---|
| Status Perkawinan | `patient.marital_status` |

### Demografi Lansia

| ASIK field | Medisy source |
|---|---|
| Status Perkawinan | `patient.marital_status` |

### Pemeriksaan Inspekulo dan IVA

| ASIK field | Medisy source |
|---|---|
| Pemeriksaan Inspekulo | `screenings[kanker_serviks].result_of_inspekulo_checkup (only when is_inspekulo_performed = 1)` |
| Pemeriksaan Inspeksi Visual Asam Asetat (IVA) | `screenings[kanker_serviks].result_of_iva_checkup (only when is_iva_performed = 1; Negatif / Positif)` |

### Kanker Leher Rahim

| ASIK field | Medisy source |
|---|---|
| Apakah pernah melakukan hubungan intim/seksual? | `screenings[kanker_serviks].pernah_hubungan_seksual` |

### Skrining Kanker Payudara

| ASIK field | Medisy source |
|---|---|
| Pemeriksaan yang dilakukan | `screenings[risiko_kanker_payudara].checkup_result1 / hasil_usg_payudara (SADANIS first)` |
| Hasil pemeriksaan SADANIS | `screenings[risiko_kanker_payudara].checkup_result1 (Tidak ada benjolan -> Normal; Benjolan; Curiga Kanker)` |
| Hasil pemeriksaan USG Payudara | `screenings[risiko_kanker_payudara].hasil_usg_payudara (Normal; Kista Simpleks -> Simple cyst)` |

### Skrining Telinga dan Mata (=>40 tahun)

| ASIK field | Medisy source |
|---|---|
| Apa hasil skrining tajam penglihatan? | `screenings[ptm_mata].visus_kanan/visus_kiri over *_denominator (Snellen ratio, 6/12 = Normal boundary)` |
| Hasil pemeriksaan tajam pendengaran | `programs.ptm.fase_pendengaran.tajam_pendengaran_right/left` |
| Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)? | `programs.ptm.fase_pendengaran.serumen_impeksi_right/left` |
| Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)? | `programs.ptm.fase_pendengaran.omsk_congek_right_ear/left_ear` |
| Hasil pemeriksaan pupil | `screenings[ptm_mata].pupil_kanan/pupil_kiri (only OV000393 Suspek Katarak -> Curiga Katarak)` |

### Skrining Telinga dan Mata (18-39 tahun)

| ASIK field | Medisy source |
|---|---|
| Apa hasil skrining tajam penglihatan? | `screenings[ptm_mata].visus_kanan/visus_kiri over *_denominator (Snellen ratio, 6/12 = Normal boundary)` |
| Hasil pemeriksaan tajam pendengaran | `programs.ptm.fase_pendengaran.tajam_pendengaran_right/left` |
| Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)? | `programs.ptm.fase_pendengaran.serumen_impeksi_right/left` |
| Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)? | `programs.ptm.fase_pendengaran.omsk_congek_right_ear/left_ear` |

### Faktor Risiko TB - Dewasa & Lansia

| ASIK field | Medisy source |
|---|---|
| Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh? | `screenings[tbc].batuk (Tidak -> no cough; Ya -> '> 2 weeks' by clinical sign-off: Medisy has no duration)` |

### Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)

| ASIK field | Medisy source |
|---|---|
| Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh? | `screenings[tbc].batuk (Tidak -> no cough; Ya -> '> 2 weeks' by clinical sign-off: Medisy has no duration)` |
| Apakah berat badan Anda turun tanpa penyebab jelas/ BB tidak naik/ nafsu makan turun? | `screenings[tbc].bb_turun` |
| Apakah Anda mengalami demam hilang timbul tanpa sebab yang jelas? | `screenings[tbc].demam` |
| Apakah Anda mengalami berkeringat di malam hari tanpa kegiatan? | `screenings[tbc].berkeringat_malam` |
| Apakah pasien memiliki pembesaran kelenjar getah bening? | `screenings[tbc].pembesaran_kgb` |
| Apakah dilakukan pemeriksaan radiografi toraks? | `screenings[tbc].pemeriksaan_foto_toraks / abnormalitas_tbc` |

### Pemeriksaan Tuberkulosis (Dewasa & Lansia)

| ASIK field | Medisy source |
|---|---|
| Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)? | `screenings[tbc].kontak_tbc (only 'Tidak Ada')` |
| Metode Pemeriksaan (untuk terduga TB) | `screenings[tbc].metode_pemeriksaan_tb (TCM, BTA Mikroskopis only; Foto Toraks / Klinis have no ASIK option)` |

### Hasil Pemeriksaan - Skrining Jantung

| ASIK field | Medisy source |
|---|---|
| Hasil Pemeriksaan EKG | `screenings[risiko_jantung].kardiovaskular_ekg` |

### Pemeriksaan HIV

| ASIK field | Medisy source |
|---|---|
| Hasil Pemeriksaan Rapid Test HIV | `lab[ANTI HIV].result (R-DIAG: or diagnoses B20-B24 -> Reaktif)` |

### Pemeriksaan Sifilis

| ASIK field | Medisy source |
|---|---|
| Hasil Pemeriksaan Rapid Test Sifilis | `lab[sifilis].result (R-DIAG: or diagnoses A50-A53 -> Reaktif)` |

### Pemeriksaan Hepatitis

| ASIK field | Medisy source |
|---|---|
| Hasil Rapid Test Hepatitis B | `lab[HBsAg].result (R-DIAG: or diagnoses B16/B18.0/B18.1 -> Reaktif)` |
| Hasil Rapid Test Hepatitis C | `lab[Anti HCV].result (R-DIAG: or diagnoses B17.1/B18.2 -> Reaktif)` |

### Perilaku Merokok

| ASIK field | Medisy source |
|---|---|
| Apakah Anda merokok dalam setahun terakhir ini? | `programs.ptm_questionnaire[Q0013 1.4 Status merokok] (1.1 = 0 when never smoked)` |
| Apakah Anda terpapar asap rokok atau menghirup asap rokok dari orang lain dalam sebulan te | `programs.ptm_questionnaire[Q0013 1.5]` |

### Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)

| ASIK field | Medisy source |
|---|---|
| Kadar CO Pernapasan | `screenings[kanker_paru].kadar_co` |

### Tingkat Aktivitas Fisik (sedang dan berat)

| ASIK field | Medisy source |
|---|---|
| Apakah Anda melakukan olahraga intensitas sedang seperti latihan beban < 20 kg, senam aero | `programs.ptm_questionnaire[Q0013 1.10] (inherited rule: sufficient activity -> Ya, insufficient -> Tidak)` |
| Apakah Anda melakukan olahraga intensitas berat seperti bersepeda cepat (>16 km/jam), jala | `programs.ptm_questionnaire[Q0013 1.10] (inherited rule: insufficient activity -> Tidak)` |

### POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)

| ASIK field | Medisy source |
|---|---|
| Kolesterol Total | `lab[KOLESTEROL TOTAL].result` |
| HDL | `lab[HDL CHOLESTEROL].result` |
| LDL | `lab[LDL CHOLESTEROL].result` |
| Trigliserida | `lab[TRIGLISERIDA].result` |

### Skrining Fungsi Ginjal Laki-Laki (hanya untuk =>40 tahun dengan risiko HT DM)

| ASIK field | Medisy source |
|---|---|
| Hasil Pemeriksaan Kreatinin | `lab[Kreatinin].result` |
| Hasil Pemeriksaan Ureum | `lab[Ureum].result` |
| Nilai Hasil pemeriksaan (e-LFG (CKD-EPI)) | `lab[eGFR].result` |
| Usia | `patient.age.years (derived)` |

### Skrining Fungsi Ginjal Perempuan (hanya untuk =>40 tahun dengan risiko HT DM)

| ASIK field | Medisy source |
|---|---|
| Hasil Pemeriksaan Kreatinin | `lab[Kreatinin].result` |
| Hasil Pemeriksaan Ureum | `lab[Ureum].result` |
| Nilai Hasil pemeriksaan (e-LFG (CKD-EPI)) | `lab[eGFR].result` |
| Usia | `patient.age.years (derived)` |

### Skrining Kerusakan Ginjal (hanya untuk =>40 tahun dengan risiko HT DM)

| ASIK field | Medisy source |
|---|---|
| Konsentrasi Albumin Urin | `lab[Microalbuminuria].result` |

### Pemeriksaan Fibrosis/Sirosis Hati

| ASIK field | Medisy source |
|---|---|
| Nilai SGOT | `lab[SGOT].result` |
| Pemeriksaan Trombosit | `lab[Trombosit].result` |

### Pemeriksaan Calon Pengantin Perempuan

| ASIK field | Medisy source |
|---|---|
| Kadar Hemoglobin | `lab[Hemoglobin].result` |

### Skrining Kanker Paru (Usia =>45 thn)

| ASIK field | Medisy source |
|---|---|
| Apakah pernah didiagnosis/menderita kanker? | `screenings[kanker_paru].question3 / programs.ptm_questionnaire[Q0019 1.1]` |
| Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita kanker sebelumnya? | `screenings[kanker_paru].question4 / programs.ptm_questionnaire[Q0019 1.2]` |
| Riwayat merokok/paparan asap rokok | `screenings[kanker_paru].question5 (only options with identical meaning) / programs.ptm_questionnaire[Q0019 1.3]` |
| Riwayat tempat kerja mengandung zat karsinogenik (Pertambangan/ pabrik/ bengkel/ garmen/ b | `screenings[kanker_paru].question6 / programs.ptm_questionnaire[Q0019 1.4]` |
| Lingkungan tempat tinggal berpotensi tinggi (lingkungan dekat pabrik/pertambangan/buangan  | `screenings[kanker_paru].question7 / programs.ptm_questionnaire[Q0019 1.5]` |
| Lingkungan dalam rumah yang tidak sehat (ventilasi buruk/atap dari asbes/lantai tanah, dap | `screenings[kanker_paru].question8 / programs.ptm_questionnaire[Q0019 1.6]` |
| Pernah didiagnosis penyakit paru kronik? | `screenings[kanker_paru].question9 / programs.ptm_questionnaire[Q0019 1.7]` |

### Penapisan Risiko Kanker Paru

| ASIK field | Medisy source |
|---|---|
| Apakah Anda merokok dalam setahun terakhir ini? | `programs.ptm_questionnaire[Q0013 1.4 Status merokok]` |
| Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir? | `screenings[kanker_paru].riwayat_merokok_15th` |
| Apakah Anda terpapar atau menghirup asap rokok dari orang lain di rumah, lingkungan atau t | `programs.ptm_questionnaire[Q0013 1.5]` |
| Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/saudara kandung)? | `programs.ptm_questionnaire[Q0019 1.2]` |
| Apakah Anda sedang mengalami salah satu atau lebih gejala berikut dan telah diobati tetapi | `screenings[kanker_paru].gejala_kanker_paru` |
| Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK? | `programs.ptm_questionnaire[Q0019 1.7]` |

### Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)

| ASIK field | Medisy source |
|---|---|
| Katakan seluruh frase berikut sesuai urutannya:  “Tolong gambar sebuah jam pada lembar ini | `screenings[pemeriksaan_cog | skilas].clock_drawing_test (Normal -> Benar; Abnormal -> Salah)` |
| Mintalah pasien untuk MENGULANG 3 kata yang disebutkan pada pertanyaan no 1 | `screenings[pemeriksaan_cog].instruction1` |

### Mobilisasi - Pemeriksaan Lanjutan (SPPB)

| ASIK field | Medisy source |
|---|---|
| Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri berdampin | `screenings[short_physical_performance].question1a` |
| Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri semi tand | `screenings[short_physical_performance].question1b` |
| Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri Tandem | `screenings[short_physical_performance].question1c` |
| tes kecepatan berjalan: Waktu untuk berjalan sejauh empat meter | `screenings[short_physical_performance].question2` |
| Tes berdiri dari kursi: Waktu untuk bangkit dari kursi lima kali | `screenings[short_physical_performance].question3` |

### Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)

| ASIK field | Medisy source |
|---|---|
| Apakah anda mengalami penurunan asupan makanan dalam 3 bulan terakhir disebabkan kehilanga | `screenings[pengkajian_nutrisi].penapisan1` |
| Penurunan berat badan dalam tiga bulan terakhir ? | `screenings[pengkajian_nutrisi].penapisan2` |
| Kemampuan melakukan mobilitas ? | `screenings[pengkajian_nutrisi].penapisan3` |
| Menderita stress psikologis atau penyakit akut dalam tiga bulan terakhir ? | `screenings[pengkajian_nutrisi].penapisan4` |
| Mengalami masalah neuropsikologis? | `screenings[pengkajian_nutrisi].penapisan5` |
| Berapa Nilai IMT (Indeks Massa Tubuh)? | `screenings[pengkajian_nutrisi].penapisan6` |

### Riwayat Imunisasi Tetanus(Status T) - Hanya untuk Catin

| ASIK field | Medisy source |
|---|---|
| Apakah anda pernah mendapatkan imunisasi tetanus minimal 2 kali? (imunisasi tetanus biasan | `screenings[imunisasi_tetanus_wus].imunisasi_tetanus (>= T2)` |

### Faktor Risiko Kanker Usus

| ASIK field | Medisy source |
|---|---|
| Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita kanker kolorektal atau  | `programs.ptm_questionnaire[Q0020 1.1]` |
| Apakah Anda merokok? | `programs.ptm_questionnaire[Q0013 1.4 Status merokok]` |

### Skrining Karies dan Gigi Hilang

| ASIK field | Medisy source |
|---|---|
| Gigi karies | `screenings[gigi_dewasa].question4` |
| Gigi hilang/dicabut | `screenings[gigi_dewasa].question3` |

### Skrining Penyakit Periodontal

| ASIK field | Medisy source |
|---|---|
| Gigi Goyang | `screenings[gigi_dewasa | gigi_lansia].gigi_goyang` |
| Penyakit Periodontal | `screenings[gigi_dewasa | gigi_lansia].penyakit_periodontal (Tidak Ada -> Tidak; Gingivitis / Periodontitis -> Ya)` |
