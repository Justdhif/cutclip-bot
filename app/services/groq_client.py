import requests
import json
import time
from app.config import Config

class GroqAudioTranscriptions:
    def __init__(self, api_key):
        self.api_key = api_key

    def create(self, file, model, response_format="verbose_json", language="id"):
        filename, file_content = file
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        files = {
            "file": (filename, file_content, "audio/mpeg")
        }
        data = {
            "model": model,
            "response_format": response_format,
            "language": language
        }
        
        for attempt in range(3):
            response = requests.post(url, headers=headers, files=files, data=data)
            if response.status_code == 429:
                # Rate limit hit, wait 20s and retry
                time.sleep(20)
                continue
            response.raise_for_status()
            return response.json()
        
        response.raise_for_status()

class GroqChatCompletionsChoiceMessage:
    def __init__(self, content):
        self.content = content

class GroqChatCompletionsChoice:
    def __init__(self, message_content):
        self.message = GroqChatCompletionsChoiceMessage(message_content)

class GroqChatCompletionsResponse:
    def __init__(self, message_content):
        self.choices = [GroqChatCompletionsChoice(message_content)]

class GroqChatCompletions:
    def __init__(self, api_key):
        self.api_key = api_key

    def create(self, model, messages, temperature=0.7, max_tokens=2048):
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        for attempt in range(3):
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 429:
                # Rate limit hit, wait 20s and retry
                time.sleep(20)
                continue
            response.raise_for_status()
            data = response.json()
            message_content = data["choices"][0]["message"]["content"]
            return GroqChatCompletionsResponse(message_content)
            
        response.raise_for_status()

class GroqAudio:
    def __init__(self, api_key):
        self.transcriptions = GroqAudioTranscriptions(api_key)

class GroqChat:
    def __init__(self, api_key):
        self.completions = GroqChatCompletions(api_key)

class MockGroq:
    def __init__(self, api_key):
        self.audio = GroqAudio(api_key)
        self.chat = GroqChat(api_key)

class GroqClientManager:
    def __init__(self):
        Config.validate()
        self.client = MockGroq(api_key=Config.GROQ_API_KEY)
        self.llm_model = "llama-3.3-70b-versatile"
        self.whisper_model = "whisper-large-v3"

    def get_client(self) -> MockGroq:
        return self.client
