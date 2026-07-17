#!/bin/bash

# Dapatkan lokasi folder script berada secara dinamis
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Periksa apakah virtual environment ada
if [ -d ".venv" ]; then
    echo "🔵 Mengaktifkan Virtual Environment (.venv)..."
    source .venv/bin/activate
else
    echo "⚠️ Folder .venv tidak ditemukan. Pastikan Anda sudah membuat venv."
fi

# Jalankan bot
echo "🚀 Menjalankan CutClip Bot..."
python app/main.py
