import os
import logging

logger = logging.getLogger(__name__)

def ensure_directory(path: str):
    """Ensures a directory exists."""
    os.makedirs(path, exist_ok=True)

def safe_delete(file_path: str):
    """Safely deletes a file if it exists, logging any exceptions."""
    if not file_path:
        return
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Berhasil menghapus file sementara: {file_path}")
    except Exception as e:
        logger.warning(f"Gagal menghapus file {file_path}: {e}")
