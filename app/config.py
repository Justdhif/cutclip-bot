import os
from dotenv import load_dotenv

# Load env variables from .env
load_dotenv()

class Config:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    @classmethod
    def validate(cls):
        """Validates that all required configuration variables are present."""
        missing = []
        if not cls.GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        
        if missing:
            raise ValueError(f"Konfigurasi tidak lengkap! Silakan lengkapi file .env untuk: {', '.join(missing)}")
