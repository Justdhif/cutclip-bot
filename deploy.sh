#!/bin/bash

# Exit on error
set -e

echo "=== Memulai Setup CutClip Bot pada VPS Ubuntu/Debian ==="

# 1. Update sistem dan install system dependencies
echo "1. Menginstal system dependencies (Python, Pip, Venv, FFmpeg)..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg git

# 2. Buat Python Virtual Environment
echo "2. Membuat Python Virtual Environment (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# 3. Aktifkan venv dan install Python dependencies
echo "3. Menginstal Python dependencies dari requirements.txt..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Cek file .env
echo "4. Memeriksa konfigurasi .env..."
if [ ! -f ".env" ]; then
    echo "Berkas .env tidak ditemukan. Membuat berkas .env baru..."
    echo "Masukkan GROQ_API_KEY Anda:"
    read -r groq_key
    echo "Masukkan TELEGRAM_BOT_TOKEN Anda:"
    read -r bot_token

    cat <<EOT > .env
GROQ_API_KEY=$groq_key
TELEGRAM_BOT_TOKEN=$bot_token
EOT
    echo ".env berhasil dibuat!"
else
    echo "Berkas .env sudah ada, melewati pembuatan .env."
fi

# 5. Konfigurasi Systemd Service agar bot jalan 24/7 di background
echo "5. Mengonfigurasi Systemd Service..."
WORKDIR=$(pwd)
USER=$(whoami)

cat <<EOT | sudo tee /etc/systemd/system/cutclip-bot.service > /dev/null
[Unit]
Description=CutClip Telegram Bot Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKDIR
ExecStart=$WORKDIR/.venv/bin/python $WORKDIR/app/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOT

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable dan start service
echo "6. Menjalankan dan mengaktifkan CutClip Bot Service..."
sudo systemctl enable cutclip-bot.service
sudo systemctl restart cutclip-bot.service

echo "=== Setup Selesai! ==="
echo "Untuk melihat status bot Anda, jalankan perintah:"
echo "sudo systemctl status cutclip-bot.service"
echo ""
echo "Untuk melihat log aktivitas bot Anda secara real-time, jalankan:"
echo "sudo journalctl -u cutclip-bot.service -f"
