import os
import re
import logging
import tempfile
import json
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from app.config import Config
from app.services.groq_client import GroqClientManager
from app.services.video_analyzer import VideoAnalyzer
from app.services.trend_advisor import TrendAdvisor
from app.services.custom_clipper import CustomClipper
from app.utils.file_helper import safe_delete

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize services
manager = GroqClientManager()
analyzer = VideoAnalyzer(manager)
trend_advisor = TrendAdvisor(manager)
custom_clipper = CustomClipper(manager)

# Regex to detect YouTube URLs (including standard, shorts, and live streams)
YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|shorts/|live/)?([a-zA-Z0-9_-]{11})'
)

async def post_init(application: Application) -> None:
    """Registers bot commands to show as suggestions in the Telegram chat."""
    commands = [
        BotCommand("start", "Memulai bot & tampilkan menu utama"),
        BotCommand("analisis", "Panduan cara menganalisis video"),
        BotCommand("tren", "Diskusi tren video & pembuatan script AI"),
        BotCommand("exit", "Keluar dari mode diskusi tren"),
        BotCommand("help", "Penjelasan fitur & cara pakai"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Saran perintah bot (Bot Commands) berhasil didaftarkan ke Telegram.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    welcome_text = (
        "👋 **Selamat datang di CutClip Bot!**\n\n"
        "Saya adalah asisten AI yang siap membantu Anda memproduksi video dengan potensi viral tinggi. Berikut adalah fitur utama:\n\n"
        "🎥 **1. Analisis Potensi Viral & Clipping Otomatis**\n"
        "Kirim link video YouTube (Short / Livestream) atau unggah video langsung. "
        "AI akan membagi transkrip per sesi (20 menit sekali) dan mendeteksi momen terbaik untuk diunduh langsung!\n\n"
        "✂️ **2. Potong Klip Kustom (Manual Clipping)**\n"
        "Kirim link YouTube dan ketik instruksi pemotongan Anda, contoh:\n"
        "• *'tolong clip dari menit 1 sampai menit 2 dari link https://youtube...'* \n"
        "• *'clip detik 30 sampai 1:15 https://youtube...'*\n"
        "Bot akan langsung memotong video sesuai durasi kustom Anda dan mengirimkannya dengan audio!\n\n"
        "💡 **3. Diskusi Tren & Pembuatan Script**\n"
        "Gunakan perintah /tren untuk masuk ke mode diskusi. Anda bisa menanyakan ide konten, strategi hook, atau meminta AI membuatkan script.\n\n"
        "📖 **Perintah Lainnya:**\n"
        "• /analisis - Panduan analisis video\n"
        "• /tren - Masuk ke mode diskusi tren\n"
        "• /help - Tampilkan pesan bantuan ini"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def analisis_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info_text = (
        "🎥 **Cara Menganalisis Video:**\n\n"
        "1. **Upload Video Langsung**:\n"
        "   Kirim file video (.mp4, .mov, dll.) langsung ke chat ini. Pastikan ukuran file di bawah 20MB.\n\n"
        "2. **Kirim Link YouTube**:\n"
        "   Cukup paste/kirim link YouTube, YouTube Shorts, atau link Youtube stream ke chat ini. AI akan mengambil audio dari link tersebut untuk dianalisis secara berkala (per 20 menit)."
    )
    await update.message.reply_text(info_text, parse_mode="Markdown")

async def tren_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "TRENDS_DISCUSSION"
    context.user_data["history"] = []
    tren_text = (
        "💡 **Mode Diskusi Tren Aktif!**\n\n"
        "Silakan tanyakan apa saja tentang tren konten video pendek, konsultasi ide, atau minta saya membuatkan script video.\n"
        "Ketik /exit atau /start untuk keluar dari mode diskusi."
    )
    await update.message.reply_text(tren_text, parse_mode="Markdown")

async def exit_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Keluar dari mode diskusi. Mode normal aktif kembali.")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    video = update.message.video or update.message.document
    if not video:
        return

    file_size_mb = video.file_size / (1024 * 1024)
    if file_size_mb > 20:
        await update.message.reply_text(
            "⚠️ Ukuran file video terlalu besar. Telegram membatasi download langsung oleh bot maksimal 20MB. "
            "Silakan gunakan video dengan durasi/ukuran lebih kecil atau upload ke YouTube lalu kirim link-nya."
        )
        return

    status_message = await update.message.reply_text("📥 Mengunduh video Anda...")
    
    try:
        file = await context.bot.get_file(video.file_id)
        temp_dir = tempfile.gettempdir()
        file_ext = ".mp4"
        if hasattr(video, 'file_name') and video.file_name:
            _, file_ext = os.path.splitext(video.file_name)
            
        local_path = os.path.join(temp_dir, f"{video.file_unique_id}{file_ext}")
        await file.download_to_drive(local_path)
        
        await status_message.edit_text("🎵 Mengekstrak & Mentranskripsi Audio (Groq Whisper)...")
        processed_path = analyzer.convert_video_to_audio_if_large(local_path)
        
        # Transcribe with timestamps
        verbose_data = analyzer.transcribe_audio_verbose(processed_path)
        sessions = analyzer.split_transcript_into_sessions(verbose_data)
        
        # Cleanup
        safe_delete(local_path)
        if processed_path != local_path:
            safe_delete(processed_path)

        if not sessions:
            await status_message.edit_text("❌ Gagal mendeteksi percakapan/suara dalam video tersebut. Pastikan suara terdengar jelas.")
            return

        await status_message.edit_text(f"🧠 Menganalisis potensi viralitas ({len(sessions)} sesi)...")
        
        title = getattr(video, 'file_name', 'Video Telegram') or 'Video Telegram'
        for session in sessions:
            label = session["session_label"]
            text_transcript = session["transcript_text"]
            
            analysis_report = analyzer.analyze_viral_potential(text_transcript, title, label)
            clean_report = re.sub(r'=== CLIPS DATA ===.*=== END CLIPS DATA ===', '', analysis_report, flags=re.DOTALL).strip()
            
            await update.message.reply_text(clean_report, parse_mode="Markdown")
            
        await status_message.delete()

    except Exception as e:
        logger.error(f"Error handling video: {e}", exc_info=True)
        await status_message.edit_text(f"❌ Terjadi kesalahan saat memproses video: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if not text:
        return

    youtube_match = YOUTUBE_REGEX.search(text)
    if youtube_match:
        url = youtube_match.group(0)
        video_id = youtube_match.group(6) # The 11 character video ID
        
        # Check if the user is requesting a custom clip (e.g. contains clip, potong, cut, or timestamp indicators)
        is_custom_clip = any(keyword in text.lower() for keyword in ["clip", "potong", "gunting", "cut", "trim", "ambil"])
        
        if is_custom_clip:
            status_message = await update.message.reply_text("🔍 Menganalisis instruksi pemotongan kustom Anda...")
            time_data = custom_clipper.parse_time_range(text)
            
            if "error" not in time_data:
                start_sec = time_data["start"]
                end_sec = time_data["end"]
                duration = end_sec - start_sec
                
                if start_sec >= 0 and end_sec > start_sec and duration <= 600: # Limit custom clips to 10 mins
                    await status_message.edit_text(
                        f"✂️ Sedang mengambil & memotong video kustom (Detik {start_sec} - {end_sec}, Durasi: {duration}s). Mohon tunggu..."
                    )
                    try:
                        clip_path = analyzer.trim_youtube_video(video_id, start_sec, end_sec)
                        await status_message.edit_text("📤 Mengunggah klip video kustom Anda...")
                        
                        with open(clip_path, "rb") as video_file:
                            await update.message.reply_video(
                                video=video_file,
                                caption=f"🎥 **Potongan Klip Kustom (Detik {start_sec} - {end_sec})**\nSelesai dipotong sesuai permintaan Anda dengan audio!",
                                parse_mode="Markdown"
                            )
                        safe_delete(clip_path)
                        await status_message.delete()
                        return # Exit early, do not do the full analysis
                    except Exception as e:
                        logger.error(f"Gagal memotong klip kustom: {e}", exc_info=True)
                        await status_message.edit_text(f"❌ Terjadi kesalahan saat memotong klip video: {str(e)}")
                        return
                else:
                    await status_message.edit_text("⚠️ Waktu mulai harus lebih kecil dari selesai, dan durasi maksimal klip kustom adalah 10 menit.")
                    return
            else:
                # If extraction fails to find a range, clean up and fallback to normal session analysis
                await status_message.delete()
        
        status_message = await update.message.reply_text("📥 Mengunduh stream audio dari YouTube...")
        try:
            audio_path = analyzer.extract_youtube_audio(url)
            
            await status_message.edit_text("🎵 Memproses & Mentranskripsi audio YouTube (Groq Whisper)...")
            processed_path = analyzer.convert_video_to_audio_if_large(audio_path)
            
            # Transcribe with timestamps
            verbose_data = analyzer.transcribe_audio_verbose(processed_path)
            sessions = analyzer.split_transcript_into_sessions(verbose_data)
            
            safe_delete(audio_path)
            if processed_path != audio_path:
                safe_delete(processed_path)
            
            if not sessions:
                await status_message.edit_text("❌ Gagal mendeteksi percakapan/suara dari link tersebut.")
                return

            await status_message.edit_text(f"🧠 Menganalisis potensi viralitas & merekomendasikan klip ({len(sessions)} sesi)...")
            
            # Send separate bubble chats for each 20-minute session
            for session in sessions:
                label = session["session_label"]
                text_transcript = session["transcript_text"]
                
                analysis_report = analyzer.analyze_viral_potential(text_transcript, f"YouTube Video ({url})", label)
                
                # Extract JSON data for buttons
                clips_data = []
                json_match = re.search(r'=== CLIPS DATA ===\n(.*?)\n=== END CLIPS DATA ===', analysis_report, re.DOTALL)
                if json_match:
                    try:
                        clips_data = json.loads(json_match.group(1).strip())
                    except Exception as e:
                        logger.error(f"Gagal memparsing clips JSON data: {e}")
                
                clean_report = re.sub(r'=== CLIPS DATA ===.*=== END CLIPS DATA ===', '', analysis_report, flags=re.DOTALL).strip()
                
                # Build inline buttons for each clip recommendation in this session
                keyboard = []
                for clip in clips_data:
                    clip_id = clip.get("id", 1)
                    start_sec = clip.get("start", 0)
                    end_sec = clip.get("end", 0)
                    title = clip.get("title", f"Klip {clip_id}")
                    
                    # Format callback: cut:<youtube_id>:<start_sec>:<end_sec>
                    callback_data = f"cut:{video_id}:{start_sec}:{end_sec}"
                    button_text = f"🎬 Gunting: {title} ({start_sec}s - {end_sec}s)"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
                    
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                await update.message.reply_text(clean_report, parse_mode="Markdown", reply_markup=reply_markup)
                
            await status_message.delete()
            
        except Exception as e:
            logger.error(f"Error handling YouTube link: {e}", exc_info=True)
            await status_message.edit_text(f"❌ Terjadi kesalahan saat memproses link YouTube: {str(e)}")
        return

    state = context.user_data.get("state")
    if state == "TRENDS_DISCUSSION":
        history = context.user_data.get("history", [])
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        response = trend_advisor.chat_about_trends(text, history)
        
        history.append(("user", text))
        history.append(("assistant", response))
        context.user_data["history"] = history[-10:]
        
        await update.message.reply_text(response, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "💡 Kirim link video YouTube atau upload file video secara langsung untuk memulai analisis.\n\n"
            "Atau ketik /tren untuk masuk ke mode konsultasi ide dan penulisan script video."
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline keyboard button clicks for video clipping."""
    query = update.callback_query
    await query.answer() # Ack the query
    
    data = query.data
    if data.startswith("cut:"):
        parts = data.split(":")
        if len(parts) == 4:
            _, video_id, start_str, end_str = parts
            start_sec = int(start_str)
            end_sec = int(end_str)
            duration = end_sec - start_sec
            
            status_msg = await query.message.reply_text(
                f"✂️ Sedang mengambil & memotong momen video (Detik {start_sec} - {end_sec}, Durasi: {duration}s). Mohon tunggu..."
            )
            
            try:
                # Trim video clip
                clip_path = analyzer.trim_youtube_video(video_id, start_sec, end_sec)
                
                await status_msg.edit_text("📤 Mengunggah klip video dengan audio ke Telegram Anda...")
                
                # Send the final mp4 clip with audio
                with open(clip_path, "rb") as video_file:
                    await query.message.reply_video(
                        video=video_file,
                        caption=f"🎥 **Potongan Momen (Detik {start_sec} - {end_sec})**\nSelesai dipotong otomatis dengan audio & siap diunduh ke galeri perangkat Anda!",
                        parse_mode="Markdown"
                    )
                
                # Cleanup file
                safe_delete(clip_path)
                await status_msg.delete()
                
            except Exception as e:
                logger.error(f"Gagal memotong klip video: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ Terjadi kesalahan saat memotong klip video: {str(e)}")

def run_bot() -> None:
    """Initializes and runs the Telegram bot polling loop."""
    Config.validate()
    
    application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("analisis", analisis_info))
    application.add_handler(CommandHandler("tren", tren_mode))
    application.add_handler(CommandHandler("exit", exit_mode))

    # Callback Query handler for video clipping buttons
    application.add_handler(CallbackQueryHandler(handle_callback))

    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started successfully in modular format. Polling for messages...")
    application.run_polling()
