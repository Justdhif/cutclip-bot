import json
import logging
import re
from app.services.groq_client import GroqClientManager

logger = logging.getLogger(__name__)

class CustomClipper:
    def __init__(self, client_manager: GroqClientManager):
        self.manager = client_manager
        self.client = client_manager.get_client()

    def _to_seconds(self, time_str: str, context: str) -> int:
        """Helper to convert time string (e.g., '24.45', '1:30', '45') to total seconds."""
        parts = re.split(r'[:.]', time_str.strip())
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 1:
                val = int(parts[0])
                if "menit" in context.lower() and "detik" not in context.lower() and ":" not in time_str and "." not in time_str:
                    return val * 60
                return val
        except ValueError:
            pass
        return -1

    def parse_time_range(self, user_message: str) -> dict:
        """
        Parses time range (start/end in seconds) from user natural language input.
        Returns a dict: {"start": int, "end": int} or {"error": str}.
        """
        # 1. Deterministic Regex Parsing for common formats (e.g. "24.45 sampai 26.45", "1:30 - 2:45", "menit 1 - 2")
        match = re.search(
            r'(?:menit|detik)?\s*(\d+(?:[:.]\d+)?)\s*(?:sampai|-|hingga|ke|s/d)\s*(?:menit|detik)?\s*(\d+(?:[:.]\d+)?)',
            user_message,
            re.IGNORECASE
        )
        if match:
            start_sec = self._to_seconds(match.group(1), user_message)
            end_sec = self._to_seconds(match.group(2), user_message)
            
            if start_sec >= 0 and end_sec > start_sec:
                logger.info(f"Berhasil memparsing rentang waktu dengan Regex: start={start_sec}, end={end_sec}")
                return {"start": start_sec, "end": end_sec}

        # 2. LLM Fallback if Regex didn't extract a valid range
        prompt = (
            "Misi Anda adalah mengekstrak waktu mulai (start) dan waktu selesai (end) dalam satuan DETIK "
            "dari instruksi pemotongan video media sosial berikut.\n\n"
            f"Pesan Pengguna: \"{user_message}\"\n\n"
            "Aturan Output:\n"
            "1. Wajib kembalikan HANYA data JSON dengan struktur: {\"start\": <integer>, \"end\": <integer>}\n"
            "2. Jika tidak ada rentang waktu mulai/selesai yang jelas, kembalikan JSON: {\"error\": \"Waktu tidak spesifik\"}\n"
            "3. Konversikan format menit/detik ke total detik dengan tepat (misal: 'menit 1 sampai 2' -> start: 60, end: 120; "
            "'menit 1.30 sampai 2' -> start: 90, end: 120; 'menit 24.45 sampai 26.45' -> start: 1485, end: 1605; 'detik 15 ke menit 1' -> start: 15, end: 60).\n"
            "4. Jangan berikan penjelasan teks lainnya selain string JSON murni. Jangan gunakan markdown block (```json) jika tidak diperlukan, kembalikan raw JSON."
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.manager.llm_model,
                messages=[
                    {"role": "system", "content": "Anda adalah sistem ekstraktor parameter waktu dari kalimat natural ke format JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0, # low temperature for deterministic parsing
                max_tokens=256,
            )
            
            response_text = completion.choices[0].message.content.strip()
            # Clean markdown code block wraps if LLM adds them
            if response_text.startswith("```"):
                response_text = re.sub(r'^```(?:json)?\n|```$', '', response_text, flags=re.MULTILINE).strip()
                
            data = json.loads(response_text)
            return data
            
        except Exception as e:
            logger.error(f"Gagal memparsing rentang waktu kustom: {e}", exc_info=True)
            return {"error": f"Gagal mengekstrak waktu: {str(e)}"}
