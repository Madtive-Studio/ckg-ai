"""Exact ASIK form and question labels (verified against the live ASIK forms by the EPUS converter's audits).

GENERATED once from ``EPUS_BREADCRUMBS`` so that ``medisy_to_asik`` can look labels up instead of retyping them: a label that
is off by one character silently breaks paket grouping and the sync back to ASIK. Keep this file in step with the live ASIK
forms (``capture_target.py`` / ``audit_coverage.py`` report drift); it is deliberately independent of ``epus_to_asik.py`` so
that module can be removed.
"""

ASIK_FORM_LABELS: dict[str, tuple[str, ...]] = {
    'identitas_pasien': (
        'NIK',
        'Nama',
        'Tanggal Lahir',
        'Tempat Lahir',
        'Jenis Kelamin',
        'Alamat Domisili',
    ),
    'Kesehatan Jiwa': (
        'Dalam 2 minggu terakhir, seberapa sering anda kurang/ tidak bersemangat dalam melakukan kegiatan sehari-hari?',
        'Dalam 2 minggu terakhir, seberapa sering anda merasa murung, tertekan, atau putus asa?',
        'Dalam 2 minggu terakhir, seberapa sering anda merasa gugup, cemas, atau gelisah?',
        'Dalam 2 minggu terakhir, seberapa sering anda tidak mampu mengendalikan rasa khawatir?',
    ),
    'SKILAS Pemeriksaan Gejala Depresi - Lansia': (
        'Apakah dalam 2 minggu terakhir Anda merasa sedih, tertekan, atau putus asa?',
        'Apakah dalam 2 minggu terakhir Anda sedikit minat atau kesenangan dalam melakukan sesuatu?',
    ),
    'SKILAS Malnutrisi': (
        'Apakah berat badan Anda berkurang >3 kg dalam 3 bulan terakhir atau pakaian menjadi lebih longgar?',
        'Apakah Anda hilang nafsu makan Atau mengalami kesulitan makan (misal batuk atau tersedak saat makan, menggunakan selang makan/sonde)?',
        'Apakah ukuran lingkar lengan atas (LiLA) <21 cm?',
    ),
    'SKILAS Mobilisasi - Lansia': (
        'Tes Berdiri di kursi: Berdiri dari kursi lima kali tanpa bantuan tangan. Apakah orang tersebut dapat berdiri dari kursi utuh sebanyak lima kali dalam 14 detik ?',
    ),
    'SKILAS Penurunan Kognitif - Lansia': (
        'Apakah dapat mengingat tiga kata: bunga, pintu, nasi (contoh)?',
        'Tanggal berapakah hari ini secara lengkap (tanggal/bulan/tahun)? atau- Dimanakah Anda saat ini (Puskesmas, rumah, klinik, dll)?',
        'Apakah peserta dapat mengingat tiga kata sebelumnya?',
    ),
    'Pemeriksaan Gangguan Fungsional/Barthel Index - Lansia': (
        'Dapat mengendalikan rangsang buang air besar (BAB)?',
        'Dapat mengendalikan rangsang berkemih/buar air kecil (BAK)?',
        'Membersihkan diri (seka wajah, sisir rambut, sikat gigi)?',
        'Penggunaan jamban (keluar masuk jamban, melepas/memakai celana, membersihkan, menyiram)?',
        'Makan dan Minum (jika makan harus berupa potongan, dianggap dibantu)',
        'Berubah sikap dari berbaring ke duduk',
        'Berpindah/berjalan',
        'Memakai baju',
        'Naik turun tangga',
        'Mandi',
    ),
    'Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun': (
        'Berat Badan Balita',
        'Pengukuran Tinggi Badan (cm)',
        'Posisi Pengukuran',
    ),
    'Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun': (
        'Pengukuran Tinggi Badan (cm)',
    ),
    'Gizi Anak Sekolah': (
        'Berat Badan',
        'Tinggi Badan',
    ),
    'Tekanan Darah Anak dan Remaja': (
        'Tekanan Darah Sistol',
        'Tekanan Darah Diastol',
    ),
    'Pemeriksaan Gula Darah Anak': (
        'Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?',
        'Gula Darah Sewaktu (GDS)',
    ),
    'Pemeriksaan Gula Darah Remaja': (
        'Apakah Anak Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?',
        'Gula Darah Sewaktu (GDS)',
    ),
    'Pemeriksaan Gigi - Anak': (
        'Berapa jumlah gigi karies?',
    ),
    'Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun)': (
        'Apakah anak Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?',
        'Apakah berat badan anak Anda turun tanpa penyebab jelas/ BB tidak naik dalam 2 bulan sebelumnya/ nafsu makan turun?',
        'Apakah anak anda mengalami demam hilang timbul tanpa sebab yang jelas lebih dari 2 minggu?',
        'Apakah dilakukan pemeriksaan radiografi toraks?',
    ),
    'Pemeriksaan Tuberkulosis Anak': (
        'Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?',
    ),
    'Berat Lahir': (
        'Berat Lahir',
        'Berat Badan Saat Ini (usia >24 jam)',
    ),
    'Riwayat Imunisasi Rutin Balita': (
        'Apakah anak anda sudah pernah menerima imunisasi Hepatitis B pada usia <24 jam?',
    ),
    'Skrining Lanjutan Talasemia - Balita dan Anak Prasekolah': (
        'Hasil Pemeriksaan Hemoglobin (Hb) dalam g/dL',
        'Hasil Pemeriksaan MCV',
        'Hasil Pemeriksaan MCH',
        'Hasil Pemeriksaan Eritrosit / RBC Count',
        'Hasil Pemeriksaan Red cell distribution width (RDW)',
        'Curiga Talasemia',
    ),
    'Skrining Telinga dan Mata - Balita dan Anak Prasekolah': (
        'Hasil Tes Daya Dengar',
        'Hasil pemeriksaan Tes Daya Lihat',
        'Apakah ditemukan selaput mata merah atau kornea keruh atau kelopak mata ada benjolan atau susah berkedip atau posisi bola mata juling atau pupil putih?',
        'Apakah ditemukan serumen impaksi?',
        'Apakah ditemukan infeksi telinga?',
    ),
    'Kuesioner Masalah Perilaku dan Emosional (KMPE) - Jika terindikasi memiliki masalah perilaku dan emosi': (
        'Hasil pemeriksaan KMPE',
    ),
    'Kuesioner Pra Skrining Perkembangan (KPSP)': (
        'Hasil pemeriksaan KPSP',
    ),
    'Kuesioner Gangguan Pemusatan Perhatian dan Hiperaktivitas (GPPH) - bila ada indikasi': (
        'Hasil Pemeriksaan Kuesioner GPPH',
    ),
    'M-CHAT - 1. Penapisan': (
        'Apakah anak Anda memiliki satu atau lebih kondisi berikut ini: 1) Masalah interaksi dengan orang lain seperti kontak mata tidak adekuat; 2) Masalah bahasa dan bicara seperti kosakata bermakna kurang dari 50 dan anak belum mampu merangkai kata, belum bisa menunjuk sesuatu, belum paham instruksi sederhana, atau bicara bahasa planet; 3) Memiliki perilaku berulang tanpa tujuan atau perilaku aneh seperti senang melihat benda berputar, menjejerkan mainan, gerakan stereotipik (flapping, clapping, body rocking), preokupasi terhadap suatu benda, masalah sensoris',
    ),
    'Penapisan dan Pemeriksaan Sifilis Anak': (
        'Hasil Pemeriksaan Rapid Test Sifilis',
    ),
    'Tekanan Darah Dewasa Lansia': (
        'Apakah Anda pernah dinyatakan tekanan darah tinggi?',
        'Tekanan Darah Sistolik',
        'Tekanan darah diastolik',
        'Tekanan Darah Sistolik Ke-2',
        'Tekanan darah diastolik ke-2',
        'Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter? Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, misal didiagnosis 1 tahun yang lalu = 12, dst',
    ),
    'Pemeriksaan Gula Darah Dewasa Lansia': (
        'Apakah Anda pernah dinyatakan diabetes atau kencing manis oleh Dokter?',
        'Gula Darah Sewaktu (GDS) (mg/dl)',
        'Gula Darah Sewaktu Kedua (GDS 2). Lakukan jika hasil GDS 1 Prediabetes (≥140-199mg/dl) atau Hiperglikemia (≥200mg/dl) dan BELUM PERNAH didiagnosis Diabetes',
        'Gula Darah Puasa (GDP) (mg/dl)',
        'Gula Darah 2 Jam PP (mg/dl)',
        'Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter? Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, misal didiagnosis 1 tahun yang lalu = 12, dst',
    ),
    'Gizi (BB - TB - Lingkar Perut) Laki-laki': (
        'Berat Badan (Kg)',
        'Pengukuran Tinggi Badan (cm)',
        'Pengukuran Lingkar Perut',
    ),
    'Gizi (BB - TB - Lingkar Perut) Perempuan': (
        'Berat Badan (Kg)',
        'Pengukuran Tinggi Badan (cm)',
        'Pengukuran Lingkar Perut',
    ),
    'Pemeriksaan PPOK (Skrining PUMA)': (
        'Apakah anda sedang/mempunyai riwayat merokok?',
        'Apakah Anda pernah merasa napas pendek ketika berjalan lebih cepat pada jalan yang datar atau pada jalan yang sedikit menanjak?',
        'Apakah Anda biasanya mempunyai dahak yang berasal dari paru atau kesulitan mengeluarkan dahak saat Anda sedang tidak menderita selesma/flu?',
        'Apakah Anda biasanya batuk saat sedang tidak menderita selesma/flu?',
        'Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk melakukan pemeriksaan spirometri atau peak flow meter (meniup ke dalam suatu alat) untuk mengetahui fungsi paru?',
        'Jika Perokok Aktif, berapa bungkus per tahun?',
    ),
    'Demografi Dewasa Perempuan': (
        'Status Perkawinan',
        'Apakah Anda sedang hamil?',
        'Apakah Anda penyandang disabilitas?',
    ),
    'Demografi Dewasa Laki-Laki': (
        'Status Perkawinan',
        'Apakah Anda penyandang disabilitas?',
    ),
    'Demografi Lansia': (
        'Status Perkawinan',
        'Apakah Anda penyandang disabilitas?',
    ),
    'Pemeriksaan Inspekulo dan IVA': (
        'Pemeriksaan Inspekulo',
        'Pemeriksaan Inspeksi Visual Asam Asetat (IVA)',
    ),
    'Kanker Leher Rahim': (
        'Apakah pernah melakukan hubungan intim/seksual?',
    ),
    'Skrining Kanker Payudara': (
        'Pemeriksaan yang dilakukan',
        'Hasil pemeriksaan SADANIS',
        'Hasil pemeriksaan USG Payudara',
    ),
    'Skrining Telinga dan Mata (=>40 tahun)': (
        'Apa hasil skrining tajam penglihatan?',
        'Hasil pemeriksaan tajam pendengaran',
        'Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?',
        'Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?',
        'Hasil pemeriksaan pupil',
    ),
    'Skrining Telinga dan Mata (18-39 tahun)': (
        'Apa hasil skrining tajam penglihatan?',
        'Hasil pemeriksaan tajam pendengaran',
        'Apa Hasil Pemeriksaan Telinga Luar (serumen impaksi)?',
        'Apa Hasil Pemeriksaan Telinga Luar (infeksi telinga)?',
    ),
    'Faktor Risiko TB - Dewasa & Lansia': (
        'Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?',
    ),
    'Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)': (
        'Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?',
        'Apakah berat badan Anda turun tanpa penyebab jelas/ BB tidak naik/ nafsu makan turun?',
        'Apakah Anda mengalami demam hilang timbul tanpa sebab yang jelas?',
        'Apakah Anda mengalami berkeringat di malam hari tanpa kegiatan?',
        'Apakah pasien memiliki pembesaran kelenjar getah bening?',
        'Apakah dilakukan pemeriksaan radiografi toraks?',
    ),
    'Pemeriksaan Tuberkulosis (Dewasa & Lansia)': (
        'Apakah anda ada kontak dengan pasien Tuberkulosis (TBC)?',
        'Metode Pemeriksaan (untuk terduga TB)',
    ),
    'Hasil Pemeriksaan - Skrining Jantung': (
        'Hasil Pemeriksaan EKG',
    ),
    'Pemeriksaan HIV': (
        'Hasil Pemeriksaan Rapid Test HIV',
    ),
    'Pemeriksaan Sifilis': (
        'Hasil Pemeriksaan Rapid Test Sifilis',
    ),
    'Pemeriksaan Hepatitis': (
        'Hasil Rapid Test Hepatitis B',
        'Hasil Rapid Test Hepatitis C',
    ),
    'Perilaku Merokok': (
        'Apakah Anda merokok dalam setahun terakhir ini?',
        'Apakah Anda terpapar asap rokok atau menghirup asap rokok dari orang lain dalam sebulan terakhir?',
    ),
    'Pemeriksaan Kadar CO (Hanya Diisi Apabila Merokok atau Terpapar Asap Rokok)': (
        'Kadar CO Pernapasan',
    ),
    'Tingkat Aktivitas Fisik (sedang dan berat)': (
        'Apakah Anda melakukan olahraga intensitas sedang seperti latihan beban < 20 kg, senam aerobic, yoga, bermain bola, bersepeda dan berenang (santai)?',
        'Apakah Anda melakukan olahraga intensitas berat seperti bersepeda cepat (>16 km/jam), jalan cepat (>7 km/jam), lari, sepak bola, futsal, bulutangkis, tenis, basket dan lompat tali?',
    ),
    'POCT Lipid Panel (Khusus usia >=40 thn dan penyandang HT dan/atau DM)': (
        'Kolesterol Total',
        'HDL',
        'LDL',
        'Trigliserida',
    ),
    'Skrining Fungsi Ginjal Laki-Laki (hanya untuk =>40 tahun dengan risiko HT DM)': (
        'Hasil Pemeriksaan Kreatinin',
        'Hasil Pemeriksaan Ureum',
        'Nilai Hasil pemeriksaan (e-LFG (CKD-EPI))',
        'Usia',
    ),
    'Skrining Fungsi Ginjal Perempuan (hanya untuk =>40 tahun dengan risiko HT DM)': (
        'Hasil Pemeriksaan Kreatinin',
        'Hasil Pemeriksaan Ureum',
        'Nilai Hasil pemeriksaan (e-LFG (CKD-EPI))',
        'Usia',
    ),
    'Skrining Kerusakan Ginjal (hanya untuk =>40 tahun dengan risiko HT DM)': (
        'Konsentrasi Albumin Urin',
    ),
    'Pemeriksaan Fibrosis/Sirosis Hati': (
        'Nilai SGOT',
        'Pemeriksaan Trombosit',
    ),
    'Pemeriksaan Calon Pengantin Perempuan': (
        'Kadar Hemoglobin',
    ),
    'Skrining Kanker Paru (Usia =>45 thn)': (
        'Apakah pernah didiagnosis/menderita kanker?',
        'Apakah ada keluarga (ayah/ibu/saudara kandung) didiagnosis/menderita kanker sebelumnya?',
        'Riwayat merokok/paparan asap rokok',
        'Riwayat tempat kerja mengandung zat karsinogenik (Pertambangan/ pabrik/ bengkel/ garmen/ bangunan/ laboratorium/ sopir/ galangan kapal, dll)?',
        'Lingkungan tempat tinggal berpotensi tinggi (lingkungan dekat pabrik/pertambangan/buangan sampah, dll)?',
        'Lingkungan dalam rumah yang tidak sehat (ventilasi buruk/atap dari asbes/lantai tanah, dapur tungku, dll)?',
        'Pernah didiagnosis penyakit paru kronik?',
    ),
    'Penapisan Risiko Kanker Paru': (
        'Apakah Anda merokok dalam setahun terakhir ini?',
        'Apakah Anda pernah memiliki riwayat merokok dalam 15 tahun terakhir?',
        'Apakah Anda terpapar atau menghirup asap rokok dari orang lain di rumah, lingkungan atau tempat kerja dalam 1 bulan terakhir?',
        'Apakah memiliki riwayat kanker paru pada keluarga (ayah/ibu/saudara kandung)?',
        'Apakah Anda sedang mengalami salah satu atau lebih gejala berikut dan telah diobati tetapi tidak sembuh-sembuh : batuk dalam jangka waktu yang lama / batuk berdarah/ sesak napas/ nyeri dada/ leher bengkak/ terdapat benjolan pada leher?',
        'Apakah Anda pernah memiliki riwayat penyakit TBC atau PPOK?',
    ),
    'Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)': (
        'Katakan seluruh frase berikut sesuai urutannya:  “Tolong gambar sebuah jam pada lembar ini. Mulailah dengan menggambar sebuah lingkaran besar. Kemudian, tuliskan angka-angka pada lingkaran dan atur jarum jam mengarah pukul 11:10 (11 lewat 10 menit).”Bila subjek tidak dapat menyelesaikan gambar jam dalam waktu 3 menit, hentikan pemeriksaan langkah ini dan lanjut ke langkah ke-3."',
        'Mintalah pasien untuk MENGULANG 3 kata yang disebutkan pada pertanyaan no 1',
    ),
    'Mobilisasi - Pemeriksaan Lanjutan (SPPB)': (
        'Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri berdampingan',
        'Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri semi tandem',
        'Tes keseimbangan: berdiri selama 10 detik dengan kaki di masing-masing : Berdiri Tandem',
        'tes kecepatan berjalan: Waktu untuk berjalan sejauh empat meter',
        'Tes berdiri dari kursi: Waktu untuk bangkit dari kursi lima kali',
    ),
    'Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)': (
        'Apakah anda mengalami penurunan asupan makanan dalam 3 bulan terakhir disebabkan kehilangan nafsu makan, gangguan saluran cerna, kesulitan mengunyah atau menelan?',
        'Penurunan berat badan dalam tiga bulan terakhir ?',
        'Kemampuan melakukan mobilitas ?',
        'Menderita stress psikologis atau penyakit akut dalam tiga bulan terakhir ?',
        'Mengalami masalah neuropsikologis?',
        'Berapa Nilai IMT (Indeks Massa Tubuh)?',
    ),
    'Riwayat Imunisasi Tetanus(Status T) - Hanya untuk Catin': (
        'Apakah anda pernah mendapatkan imunisasi tetanus minimal 2 kali? (imunisasi tetanus biasanya didapatkan pada vaksin DPT saat bayi, vaksin TT/Td saat usia sekolah dasar)',
    ),
    'Faktor Risiko Kanker Usus': (
        'Apakah ada anggota keluarga Anda, yang pernah dinyatakan menderita kanker kolorektal atau kanker usus?',
        'Apakah Anda merokok?',
    ),
    'Skrining Karies dan Gigi Hilang': (
        'Gigi karies',
        'Gigi hilang/dicabut',
    ),
    'Skrining Penyakit Periodontal': (
        'Gigi Goyang',
        'Penyakit Periodontal',
    ),
}
