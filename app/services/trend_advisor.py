from app.services.groq_client import GroqClientManager

class TrendAdvisor:
    def __init__(self, client_manager: GroqClientManager):
        self.manager = client_manager
        self.client = client_manager.get_client()

    def chat_about_trends(self, user_message: str, chat_history: list = None) -> str:
        """
        Conducts a conversation with the user about video trends, content ideas, and hooks.
        """
        system_prompt = (
            "Anda adalah pakar strategi konten video pendek (TikTok, Reels, YouTube Shorts) yang sangat berpengalaman. "
            "Tugas Anda adalah membantu pengguna merancang konsep video, menemukan hook yang menarik (3 detik pertama), "
            "mengidentifikasi tren terkini, menyusun struktur video agar retensi penonton tinggi, serta memberikan saran editing.\n\n"
            "Aturan respon:\n"
            "1. Gunakan bahasa Indonesia yang santai, profesional, komunikatif, dan kreatif.\n"
            "2. Berikan saran yang praktis, langsung dapat diterapkan, dan fokus pada retensi penonton.\n"
            "3. Format teks menggunakan Markdown yang rapi (bold, bullet points, numbering) agar nyaman dibaca di Telegram.\n"
            "4. Sisipkan emoji standar serta emoji ASCII/Kaomoji khas Jepang (seperti `(๑•̀ㅂ•́)و✧`, `(✿◠‿◠)`, `(づ｡◕‿‿◕｡)づ`, `(*^▽^*)`, `(ノ^_^)ノ`, `(•◡•)`) secara pas dan kreatif agar gaya bicara asisten terasa bersahabat dan unik."
        )

        messages = [{"role": "system", "content": system_prompt}]
        
        if chat_history:
            for role, content in chat_history:
                messages.append({"role": role, "content": content})
                
        messages.append({"role": "user", "content": user_message})

        try:
            completion = self.client.chat.completions.create(
                model=self.manager.llm_model,
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )
            return completion.choices[0].message.content
        except Exception as e:
            return f"Maaf, terjadi kesalahan saat menghubungi AI: {str(e)}"

    def generate_script(self, topic: str, style: str = "edutainment") -> str:
        """
        Generates a viral short-form video script based on a topic and style.
        """
        prompt = (
            f"Buatkan naskah video pendek (durasi sekitar 30-60 detik) dengan topik: '{topic}' dan gaya: '{style}'.\n\n"
            "Naskah harus menyertakan:\n"
            "1. Hook yang kuat (Detik 0-3)\n"
            "2. Pembahasan utama (Detik 3-25)\n"
            "3. Call to Action (Detik 25-30)\n"
            "4. Petunjuk visual/editing untuk editor di setiap bagian (dalam tanda kurung siku, misal: [Tampilkan teks popup, zoom in])."
        )
        return self.chat_about_trends(prompt)
