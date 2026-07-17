import os
import subprocess
import logging
import json
import math
import yt_dlp
from app.services.groq_client import GroqClientManager
from app.utils.file_helper import ensure_directory, safe_delete

logger = logging.getLogger(__name__)

class VideoAnalyzer:
    def __init__(self, client_manager: GroqClientManager):
        self.manager = client_manager
        self.client = client_manager.get_client()
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        ensure_directory(self.download_dir)

    def extract_youtube_audio(self, url: str) -> str:
        """
        Downloads the audio stream from a YouTube URL.
        Returns the path to the downloaded file.
        """
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(self.download_dir, '%(id)s.%(ext)s'),
            'js_runtimes': {'node': {}},
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Locate actual file
            base, _ = os.path.splitext(filename)
            for ext in ['m4a', 'mp3', 'webm', 'ogg', 'wav']:
                candidate = f"{base}.{ext}"
                if os.path.exists(candidate):
                    return candidate
            if os.path.exists(filename):
                return filename
            raise FileNotFoundError("Gagal mengunduh audio dari YouTube")

    def convert_video_to_audio_if_large(self, video_path: str) -> str:
        """
        Compresses video or extracts mono audio if size exceeds 25MB limit.
        """
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb < 24.5:
            return video_path

        audio_output = os.path.splitext(video_path)[0] + "_extracted.mp3"
        try:
            cmd = [
                "ffmpeg", "-y", "-i", video_path, 
                "-vn", "-acodec", "libmp3lame", 
                "-ac", "1", "-ab", "64k", 
                audio_output
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(audio_output):
                safe_delete(video_path)
                return audio_output
        except Exception as e:
            logger.warning(f"Gagal melakukan konversi ffmpeg: {e}. Menggunakan file asli.")
        return video_path

    def transcribe_audio_verbose(self, file_path: str) -> dict:
        """
        Transcribes audio/video file using Groq Whisper and returns verbose JSON.
        """
        with open(file_path, "rb") as file:
            transcription = self.client.audio.transcriptions.create(
                file=(os.path.basename(file_path), file.read()),
                model=self.manager.whisper_model,
                response_format="verbose_json",
                language="id"
            )
            
        if hasattr(transcription, "model_dump"):
            return transcription.model_dump()
        elif isinstance(transcription, dict):
            return transcription
        else:
            return getattr(transcription, "segments", [])

    def split_transcript_into_sessions(self, transcription_data, session_duration_sec=1200) -> list:
        """
        Splits transcription verbose segments into 20-minute (1200s) sessions.
        Returns a list of session dictionaries.
        """
        segments = []
        if isinstance(transcription_data, dict):
            segments = transcription_data.get("segments", [])
        elif isinstance(transcription_data, list):
            segments = transcription_data
        else:
            return []

        if not segments:
            return []

        # Find max duration
        max_time = 0.0
        for seg in segments:
            if isinstance(seg, dict):
                end = seg.get("end", 0.0)
            else:
                end = getattr(seg, "end", 0.0)
            if end > max_time:
                max_time = end

        # Calculate number of sessions
        num_sessions = math.ceil(max_time / session_duration_sec)
        if num_sessions == 0:
            num_sessions = 1

        sessions = []
        for i in range(num_sessions):
            session_start = i * session_duration_sec
            session_end = (i + 1) * session_duration_sec
            
            session_lines = []
            for seg in segments:
                if isinstance(seg, dict):
                    start = seg.get("start", 0.0)
                    end = seg.get("end", 0.0)
                    text = seg.get("text", "")
                else:
                    start = getattr(seg, "start", 0.0)
                    end = getattr(seg, "end", 0.0)
                    text = getattr(seg, "text", "")
                    
                if session_start <= start < session_end:
                    start_min = int(start // 60)
                    start_sec = int(start % 60)
                    end_min = int(end // 60)
                    end_sec = int(end % 60)
                    session_lines.append(f"[{start_min:02d}:{start_sec:02d} - {end_min:02d}:{end_sec:02d}] {text.strip()}")
                    
            if session_lines:
                start_min = int(session_start // 60)
                end_min = int(session_end // 60)
                sessions.append({
                    "session_id": i + 1,
                    "session_label": f"Sesi {i+1} (Menit {start_min:02d}:00 - {end_min:02d}:00)",
                    "start_time": session_start,
                    "end_time": session_end,
                    "transcript_text": "\n".join(session_lines)
                })
                
        return sessions

    def format_verbose_transcript(self, transcription_data) -> str:
        """
        Formats verbose transcription JSON into a timestamped transcript string (full video).
        """
        segments = []
        if isinstance(transcription_data, dict):
            segments = transcription_data.get("segments", [])
        elif isinstance(transcription_data, list):
            segments = transcription_data
        else:
            return str(transcription_data)
            
        formatted_lines = []
        for seg in segments:
            if isinstance(seg, dict):
                start = seg.get("start", 0.0)
                end = seg.get("end", 0.0)
                text = seg.get("text", "")
            else:
                start = getattr(seg, "start", 0.0)
                end = getattr(seg, "end", 0.0)
                text = getattr(seg, "text", "")
                
            start_min = int(start // 60)
            start_sec = int(start % 60)
            end_min = int(end // 60)
            end_sec = int(end % 60)
            
            formatted_lines.append(f"[{start_min:02d}:{start_sec:02d} - {end_min:02d}:{end_sec:02d}] {text.strip()}")
            
        return "\n".join(formatted_lines)

    def analyze_viral_potential(self, timestamped_transcript: str, title: str = "Video Tanpa Judul", session_info: str = "") -> str:
        """
        Analyzes the timestamped video transcript for viral potential and highlights clipping moments concisely.
        """
        session_prefix = f" ({session_info})" if session_info else ""
        
        prompt = (
            f"Berikut adalah transkrip video ber-timestamp untuk {title}{session_prefix}:\n"
            f"Transkrip:\n\"\"\"\n{timestamped_transcript}\n\"\"\"\n\n"
            "Tugas Anda adalah mendeteksi maksimal 3 cuplikan momen terbaik dari transkrip di atas yang paling berpotensi viral jika dijadikan video pendek (clipping).\n\n"
            "Tuliskan laporan analisis dengan format Markdown Indonesia yang RINGKAS DAN TO-THE-POINT seperti berikut:\n\n"
            f"🎬 **REKOMENDASI MOMEN VIRAL{session_prefix.upper()}**\n\n"
            "1. **[JUDUL MOMEN 1]**\n"
            "   ⏱️ Rentang Waktu: [MM:SS - MM:SS]\n"
            "   📈 Skor Viral: [Nilai 0-100]/100\n"
            "   💡 Alasan: [Alasan singkat kenapa berpotensi viral, maksimal 2 kalimat saja]\n\n"
            "2. **[JUDUL MOMEN 2]**\n"
            "   ⏱️ Rentang Waktu: [MM:SS - MM:SS]\n"
            "   📈 Skor Viral: [Nilai 0-100]/100\n"
            "   💡 Alasan: [Alasan singkat kenapa berpotensi viral, maksimal 2 kalimat saja]\n\n"
            "3. **[JUDUL MOMEN 3]**\n"
            "   ⏱️ Rentang Waktu: [MM:SS - MM:SS]\n"
            "   📈 Skor Viral: [Nilai 0-100]/100\n"
            "   💡 Alasan: [Alasan singkat kenapa berpotensi viral, maksimal 2 kalimat saja]\n\n"
            "PENTING: Di baris paling bawah respons Anda (wajib persis di bagian akhir), sertakan data tag JSON untuk sistem pemotong video otomatis kami. "
            "Pilih momen-momen tersebut dengan durasi ideal per klip berkisar 20 hingga 60 detik. Format JSON harus persis seperti contoh di bawah:\n\n"
            "=== CLIPS DATA ===\n"
            "[\n"
            "  {\"id\": 1, \"start\": <detik_mulai_integer>, \"end\": <detik_selesai_integer>, \"title\": \"Judul Klip 1\"},\n"
            "  {\"id\": 2, \"start\": <detik_mulai_integer>, \"end\": <detik_selesai_integer>, \"title\": \"Judul Klip 2\"},\n"
            "  {\"id\": 3, \"start\": <detik_mulai_integer>, \"end\": <detik_selesai_integer>, \"title\": \"Judul Klip 3\"}\n"
            "]\n"
            "=== END CLIPS DATA ==="
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.manager.llm_model,
                messages=[
                    {"role": "system", "content": "Anda adalah pakar viral marketing dan analis konten media sosial (TikTok/Reels/Shorts). Selalu sertakan emoji standar serta emoji ASCII/Kaomoji khas Jepang (seperti (๑•̀ㅂ•́)و✧, (✿◠‿◠), (づ｡◕‿‿◕｡)づ) di sela-sela tulisan laporan analisis Anda untuk memberikan gaya penulisan yang kreatif dan interaktif."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=2048,
            )
            return completion.choices[0].message.content
        except Exception as e:
            return f"Gagal menganalisis viralitas: {str(e)}"

    def trim_youtube_video(self, video_id: str, start_time: int, end_time: int) -> str:
        """
        Downloads a specific section of a YouTube video with audio.
        Returns the local file path of the trimmed video.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_filename = os.path.join(self.download_dir, f"{video_id}_{start_time}_{end_time}.mp4")
        
        ydl_opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best',
            'outtmpl': output_filename,
            'download_ranges': lambda info_dict, ydl: [{'start_time': start_time, 'end_time': end_time}],
            'force_keyframes_at_cuts': True,
            'external_downloader_args': {
                'ffmpeg_i': ['-headers', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n']
            },
            'js_runtimes': {'node': {}},
        }
        
        logger.info(f"Memulai cuplikan download untuk {video_id} dari detik {start_time} ke {end_time}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        base = os.path.splitext(output_filename)[0]
        for ext in ['mp4', 'mkv', 'webm', '3gp']:
            candidate = f"{base}.{ext}"
            if os.path.exists(candidate):
                if ext != 'mp4':
                    mp4_path = f"{base}.mp4"
                    try:
                        cmd = [
                            "ffmpeg", "-y", "-i", candidate, 
                            "-c:v", "libx264", "-c:a", "aac", 
                            "-strict", "-2", mp4_path
                        ]
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                        safe_delete(candidate)
                        return mp4_path
                    except Exception as e:
                        logger.warning(f"Gagal mengonversi format {ext} ke mp4: {e}. Mengirimkan file asli.")
                return candidate
                
        if os.path.exists(output_filename):
            return output_filename
            
        raise FileNotFoundError("Gagal memotong video YouTube")
