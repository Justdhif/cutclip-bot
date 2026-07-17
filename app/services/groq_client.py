from groq import Groq
from app.config import Config

class GroqClientManager:
    def __init__(self):
        Config.validate()
        self.client = Groq(api_key=Config.GROQ_API_KEY)
        self.llm_model = "llama-3.3-70b-versatile"
        self.whisper_model = "whisper-large-v3"

    def get_client(self) -> Groq:
        return self.client
