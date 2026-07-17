import os
import re
import logging
import tempfile
import json
import asyncio
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
custom_clipper = CustomClipper(manager)

# Regex to detect YouTube URLs (including standard, shorts, and live streams)
YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|shorts/|live/)?([a-zA-Z0-9_-]{11})'
)

async def post_init(application: Application) -> None:
    """Registers bot commands to show as suggestions in the Telegram chat."""
    commands = [
        BotCommand("start", "Memulai CutClip Bot"),
        BotCommand("exit", "Keluar dari mode kirim link"),
        BotCommand("help", "Bantuan & Panduan"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Saran perintah bot (Bot Commands) berhasil didaftarkan ke Telegram.")

# Global constant for the main welcome screen
WELCOME_TEXT = (
    "👋 **Halo! Saya CutClip Bot** 🎬🤖\n\n"
    "Saya adalah asisten pintar berbasis AI yang siap mendampingi Anda memproduksi video pendek berkualitas tinggi!\n\n"
    "Tugas utama saya adalah **mendeteksi momen-momen emas (paling menarik/lucu/klimaks)** dari video biasa maupun live streaming YouTube panjang, lalu memotongnya (*clipping*) menjadi cuplikan video pendek berdurasi kustom yang siap Anda unduh.\n\n"
    "Silakan jelajahi tombol di bawah untuk melihat detail bantuan atau cara langsung memotong video! 👇"
)

def get_main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Help", callback_data="menu:help"),
            InlineKeyboardButton("🎬 Clip", callback_data="menu:clip")
        ]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)

async def exit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 **Mode kirim link telah dinonaktifkan.**\n\n" + WELCOME_TEXT,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# tren_mode and exit_mode functions removed

# handle_video function removed

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if not text:
        return

    state = context.user_data.get("state")
    if state != "WAITING_YOUTUBE_LINK":
        await update.message.reply_text(
            "⚠️ Silakan masuk ke menu **Clip** lalu klik **Kirim Link YT** terlebih dahulu sebelum mengirim link atau teks!\n\n"
            "Ketik /start untuk membuka menu utama.",
            parse_mode="Markdown"
        )
        return

    youtube_match = YOUTUBE_REGEX.search(text)
    if youtube_match:
        # Clear state after receiving valid link to exit the mode
        context.user_data.clear()
        
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
            for idx, session in enumerate(sessions):
                label = session["session_label"]
                text_transcript = session["transcript_text"]
                
                analysis_report = ""
                for attempt in range(4):
                    analysis_report = analyzer.analyze_viral_potential(text_transcript, f"YouTube Video ({url})", label)
                    if "429" in analysis_report or "Too Many Requests" in analysis_report:
                        if attempt < 3:
                            wait_sec = 25
                            await status_message.edit_text(
                                f"⏳ Terkena limit API Groq untuk {label}.\n"
                                f"Menunggu {wait_sec} detik sebelum mencoba kembali (Percobaan {attempt + 1}/3)..."
                            )
                            await asyncio.sleep(wait_sec)
                            await status_message.edit_text(f"🧠 Menganalisis potensi viralitas & merekomendasikan klip ({label})...")
                            continue
                    break
                
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
                    button_text = f"🎬 {title}"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
                    
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                await update.message.reply_text(clean_report, parse_mode="Markdown", reply_markup=reply_markup)
                
            await status_message.delete()
            
        except Exception as e:
            logger.error(f"Error handling YouTube link: {e}", exc_info=True)
            await status_message.edit_text(f"❌ Terjadi kesalahan saat memproses link YouTube: {str(e)}")
        return

    await update.message.reply_text(
        "💡 Kirim link video YouTube atau upload file video secara langsung untuk memulai analisis.",
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline keyboard button clicks for video clipping."""
    query = update.callback_query
    try:
        await query.answer() # Ack the query
    except Exception as e:
        logger.warning(f"Gagal menjawab callback query (kemungkinan query kadaluarsa/lama): {e}")
    
    data = query.data
    
    if data == "menu:main":
        context.user_data.clear()
        await query.message.edit_text(WELCOME_TEXT, parse_mode="Markdown", reply_markup=get_main_keyboard())
        return
        
    if data == "menu:help":
        general_text = (
            "🤖 **Tentang CutClip Bot**\n\n"
            "Bot ini dirancang khusus untuk membantu Anda mendeteksi momen-momen menarik dari live streaming maupun video YouTube menggunakan AI secara otomatis, serta memotong klip (*clipping*) dengan durasi waktu kustom yang Anda tentukan sendiri! 🚀"
        )
        keyboard = [[InlineKeyboardButton("« Kembali", callback_data="menu:main")]]
        await query.message.edit_text(general_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    if data == "menu:clip":
        clip_text = (
            "🎬 **Panduan Memotong (Clip) Video & Deteksi Momen**\n\n"
            "1️⃣ **Deteksi Momen Otomatis (AI)**\n"
            "Kirimkan link video YouTube atau Live Stream. AI akan menganalisis percakapan/suara dan menyajikan rekomendasi klip terbaik secara otomatis.\n\n"
            "2️⃣ **Potong Klip Kustom (Manual)**\n"
            "Kirim link YouTube disertai durasi yang ingin Anda potong. Contoh format:\n"
            "• `clip menit 1 sampai 2 https://youtube...`\n"
            "• `clip detik 30 sampai 1:15 https://youtube...`"
        )
        keyboard = [
            [InlineKeyboardButton("🔗 Kirim Link YT", callback_data="menu:send_link")],
            [InlineKeyboardButton("« Kembali", callback_data="menu:main")]
        ]
        await query.message.edit_text(clip_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    if data == "menu:send_link":
        context.user_data["state"] = "WAITING_YOUTUBE_LINK"
        send_link_text = (
            "📥 **Mode Kirim Link YT Aktif**\n\n"
            "Silakan paste/kirimkan link video YouTube, Shorts, atau Live Stream ke chat ini sekarang.\n\n"
            "*(Ketik /exit atau klik tombol Keluar di bawah untuk menonaktifkan mode ini)*"
        )
        keyboard = [[InlineKeyboardButton("❌ Keluar", callback_data="menu:main")]]
        await query.message.edit_text(send_link_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
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
    
    application = (
        Application.builder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("exit", exit_command))

    # Callback Query handler for video clipping buttons
    application.add_handler(CallbackQueryHandler(handle_callback))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started successfully in modular format. Polling for messages...")
    application.run_polling()
