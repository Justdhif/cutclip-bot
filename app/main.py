import os
import sys
import logging
import static_ffmpeg

# Sys.path hack to ensure root folder is in path for imports to resolve correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up static ffmpeg path automatically
try:
    static_ffmpeg.add_paths()
except Exception as e:
    logging.warning(f"Gagal memuat static-ffmpeg: {e}")

from app.bot import run_bot

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        logger.error(f"Aplikasi berhenti dengan kesalahan fatal: {e}", exc_info=True)
