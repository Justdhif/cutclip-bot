import os
import sys
import logging
import http.server
import socketserver
import threading

# Sys.path hack to ensure root folder is in path for imports to resolve correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up static ffmpeg path automatically
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except (ImportError, AttributeError, Exception) as e:
    logging.warning(f"Gagal memuat static-ffmpeg (mencoba menggunakan ffmpeg sistem): {e}")

from app.bot import run_bot

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def start_dummy_server():
    port = int(os.environ.get("PORT", 7860))
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"CutClip Bot is running!")

    try:
        with socketserver.TCPServer(("", port), QuietHandler) as httpd:
            logger.info(f"Dummy server berjalan di port {port}")
            httpd.serve_forever()
    except Exception as e:
        logger.warning(f"Gagal menjalankan dummy server: {e}")

if __name__ == "__main__":
    try:
        # Jalankan server HTTP dummy di background thread untuk Hugging Face
        threading.Thread(target=start_dummy_server, daemon=True).start()
        
        run_bot()
    except Exception as e:
        logger.error(f"Aplikasi berhenti dengan kesalahan fatal: {e}", exc_info=True)
