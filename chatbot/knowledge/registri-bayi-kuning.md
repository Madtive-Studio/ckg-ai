# Registri Bayi Kuning (Ikterus & Ikterus Berat)

Dua halaman di bawah menu **Registri PJB-K**: **Bayi Kuning - Ikterus** dan
**Bayi Kuning - Ikterus Berat**. Keduanya mendaftar bayi baru lahir (umur 0)
yang dinilai kuning (ikterus) pada pemeriksaan MTBM (Manajemen Terpadu Bayi
Muda), mengikuti format dirjen "Register Sheet Pasien PJB, Ikterus" (sheet
"Bayi Kuning_Ikterus" dan "Bayi Kuning_Ikterus Berat"). Bisa disaring per
puskesmas + tahun + pencarian nama/NIK, dan diexport ke Excel.

## Beda dua sheet

- **Bayi Kuning - Ikterus** memuat bayi dengan klasifikasi **Ikterus** ATAU
  **Ikterus berat**. Punya kolom **Pemantauan** (kunjungan ikterus berikutnya).
- **Bayi Kuning - Ikterus Berat** hanya memuat bayi dengan klasifikasi
  **Ikterus berat**. Tanpa kolom pemantauan (baseline saja).

## Siapa yang masuk daftar

Bayi baru lahir (umur 0) yang klasifikasi ikterus-nya positif. Bayi yang tidak
kuning ("Tidak ada ikterus") tidak ditampilkan.

## Aturan klasifikasi (MTBM)

Diambil dari isian **klasifikasi ikterus** pada pemeriksaan MTBM di Medisy:

- **Tidak ada ikterus** — bayi tidak kuning.
- **Ikterus** — kuning, tanpa kriteria berat.
- **Ikterus berat** — kuning berat (misalnya kuning timbul < 24 jam, > 14 hari,
  atau sampai telapak tangan/kaki), sebagaimana dinilai nakes saat mengisi.

Medisy hanya menyimpan klasifikasi akhirnya, bukan jawaban kuesioner satu per
satu, jadi sistem **tidak menghitung sendiri** klasifikasi. Bila klasifikasi
tidak diisi di Medisy, bayi itu tidak masuk daftar.

## Tanda sumber: Medisy vs Hitung

Setiap nilai klasifikasi diberi tanda kecil, mirip tanda Medisy/ASIK di registri
lain — tapi di sini artinya berbeda:

- **Medisy** — klasifikasi diambil langsung dari isian klasifikasi di Medisy.
  Untuk data Medisy, tandanya selalu ini.
- **Hitung** — klasifikasi yang dihitung sistem dari kuesioner. Hanya muncul
  pada data lama (dari ePuskesmas) yang belum tergantikan.

Diagnosis selalu dari catatan klinik di Medisy.

## Kolom

- **Tanggal Berkunjung** — kunjungan pertama (skrining) tempat ikterus dinilai.
- **Ikterus** — klasifikasi pada kunjungan itu (dengan tanda Medisy/Hitung).
- **Diagnosis** — diagnosis yang tercatat di Medisy pada kunjungan itu.
- **Rujuk Eksternal** — faskes tujuan bila kunjungan itu dirujuk **eksternal**
  di Medisy; kosong bila tidak dirujuk atau hanya dirujuk internal.
- **Pemantauan** (hanya sheet Ikterus) — kunjungan ikterus berikutnya, masing-
  masing dengan tanggal, klasifikasi, diagnosis, dan rujukannya sendiri.

## Beda dengan registri lain (penting)

- Registri ini **hanya dari Medisy**, tidak digabung dengan ASIK, dan
  **tidak** disyaratkan "pasien CKG" (kunjungan cocok di kedua sumber). Sebabnya:
  di lapangan, penilaian ikterus MTBM dicatat pada kunjungan yang tidak ditandai
  CKG, sehingga syarat CKG akan mengosongkan daftar. Jadi bayi masuk daftar
  berdasarkan adanya penilaian ikterus, bukan keanggotaan program CKG.
- Bayi membawa **NIK orang tua** (belum punya KTP), jadi bayi dibedakan dari
  orang tua lewat umur 0 / nama berawalan "BAYI", bukan lewat NIK.

## Yang belum tersedia

- Sheet **PJBK** (skrining jantung bawaan / pulse-oksimetri) belum tersedia di
  aplikasi. Datanya sudah ada di Medisy (saturasi tangan dan kaki, kesimpulan
  Lolos/Gagal), tetapi sheet-nya belum dibuat.
- Kolom "Rujuk Eksternal" sering kosong: hanya terisi bila kunjungan itu
  dirujuk eksternal dan tujuannya tercatat.
