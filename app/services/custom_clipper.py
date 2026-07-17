import json
import logging
import re
from app.services.groq_client import GroqClientManager

logger = logging.getLogger(__name__)

class CustomClipper:
    def __init__(self, client_manager: GroqClientManager):
        self.manager = client_manager
        self.client = client_manager.get_client()

    def parse_time_range(self, user_message: str) -> dict:
        """
        Parses time range (start/end in seconds) from user natural language input.
        Returns a dict: {"start": int, "end": int} or {"error": str}.
        """
        prompt = (
            "Misi Anda adalah mengekstrak waktu mulai (start) dan waktu selesai (end) dalam satuan DETIK "
            "dari instruksi pemotongan video media sosial berikut.\n\n"
            f"Pesan Pengguna: \"{user_message}\"\n\n"
            "Aturan Output:\n"
            "1. Wajib kembalikan HANYA data JSON dengan struktur: {\"start\": <integer>, \"end\": <integer>}\n"
            "2. Jika tidak ada rentang waktu mulai/selesai yang jelas, kembalikan JSON: {\"error\": \"Waktu tidak spesifik\"}\n"
            "3. Konversikan format menit/detik ke total detik dengan tepat (misal: 'menit 1 sampai 2' -> start: 60, end: 120; "
            "'menit 1.30 sampai 2' -> start: 90, end: 120; 'detik 15 ke menit 1' -> start: 15, end: 60).\n"
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
