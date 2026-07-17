# CutClip Bot 🎥

CutClip Bot adalah asisten AI Telegram berbasis Python yang dirancang untuk membantu content creator menganalisis potensi viralitas video pendek (TikTok, Reels, YouTube Shorts) serta melakukan brainstorming tren dan penulisan naskah video secara otomatis menggunakan Groq AI.

## ✨ Fitur Utama

1. **Analisis Potensi Viral Video**:
   * **Direct Upload**: Pengguna dapat mengunggah video secara langsung ke bot (ukuran maksimal 20MB dibatasi oleh Telegram API).
   * **YouTube Link Support**: Cukup kirimkan tautan video YouTube biasa, Shorts, atau Youtube Livestream. Bot akan mengunduh stream audio yang efisien untuk dianalisis.
   * **AI Analysis**: Mengekstrak transkrip audio menggunakan **Groq Whisper (`whisper-large-v3`)** dan menganalisis elemen konten (Hook, Retensi, Emosi, Shareability) serta memberikan rekomendasi perbaikan menggunakan **Groq LLM (`llama-3.3-70b-versatile`)**.

2. **Konsultasi Tren & Pembuatan Script (`/tren`)**:
   * Sesi chat interaktif dengan AI mengenai strategi konten dan tren terkini.
   * Membantu memformulasikan hook dan menyusun naskah video lengkap dengan petunjuk visual/editing.

---

## 📁 Struktur Direktori

```text
cutclip-bot/
├── .env                        # File konfigurasi lingkungan (Diabaikan git)
├── .gitignore                  # Aturan file yang diabaikan git
├── requirements.txt            # Dependensi Python
└── app/                        # Paket utama kode bot
    ├── __init__.py
    ├── main.py                 # Entry point untuk menjalankan bot
    ├── config.py               # Pengelola & validator variabel lingkungan
    ├── bot.py                  # Handler Telegram Bot & Event Loop
    ├── services/               # Layanan Integrasi API
    │   ├── __init__.py
    │   ├── groq_client.py      # Wrapper inisialisasi Groq client
    │   ├── video_analyzer.py   # Download video/audio & analisis viralitas
    │   └── trend_advisor.py    # Chat tren & penyusunan naskah
    └── utils/                  # Alat bantu pemrosesan
        ├── __init__.py
        └── file_helper.py      # Manajemen file sementara secara aman

```

---

## 🛠️ Persyaratan Sistem

Untuk mengekstrak audio dari video berukuran besar, aplikasi membutuhkan **FFmpeg** terinstal di sistem Anda:
1. Unduh FFmpeg untuk sistem operasi Anda (Windows/Linux/macOS).
2. Tambahkan direktori bin FFmpeg ke dalam PATH sistem Anda (Environment Variables).

---

## 🚀 Cara Instalasi & Penggunaan

### 1. Kloning & Persiapan Proyek
Masuk ke direktori proyek:
```bash
cd cutclip-bot
```

### 2. Konfigurasi Lingkungan (`.env`)
Buat file bernama `.env` di root direktori dan masukkan token API Anda:
```env
GROQ_API_KEY=gsk_your_groq_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

### 3. Instalasi Dependensi
Instal dependensi Python yang dibutuhkan:
```bash
pip install -r requirements.txt
```

### 4. Jalankan Bot
Jalankan aplikasi utama:
```bash
python app/main.py
```

Setelah bot berjalan sukses, Anda dapat membuka Telegram dan mulai berinteraksi dengan mengirimkan perintah `/start`.
