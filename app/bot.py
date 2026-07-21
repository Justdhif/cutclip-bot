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
TIKTOK_REGEX = re.compile(r'(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/[^\s]+')
INSTAGRAM_REGEX = re.compile(r'(https?://)?(www\.)?instagram\.com/[^\s]+')

def extract_link(text: str):
    """Detects and returns any supported video link (YouTube, TikTok, or Instagram)."""
    yt = YOUTUBE_REGEX.search(text)
    if yt:
        return yt.group(0), "youtube", yt.group(6)
    
    tt = TIKTOK_REGEX.search(text)
    if tt:
        return tt.group(0), "tiktok", None
        
    ig = INSTAGRAM_REGEX.search(text)
    if ig:
        return ig.group(0), "instagram", None
        
    return None, None, None

async def post_init(application: Application) -> None:
    """Registers bot commands to show as suggestions in the Telegram chat."""
    commands = [
        BotCommand("start", "Memulai CutClip Bot"),
        BotCommand("exit", "Keluar dari mode aktif"),
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
            InlineKeyboardButton("🎬 Clip", callback_data="menu:clip"),
            InlineKeyboardButton("✍️ Caption", callback_data="menu:caption")
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
        "👋 **Mode aktif telah dinonaktifkan.**\n\n" + WELCOME_TEXT,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def handle_video_for_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get("state")
    chat_type = update.effective_chat.type
    is_group = chat_type in ["group", "supergroup"]
    
    bot_username = context.bot.username or ""
    caption = update.message.caption or ""
    is_mentioned = f"@{bot_username}" in caption if bot_username else False
    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        is_reply_to_bot = update.message.reply_to_message.from_user.id == context.bot.id

    # If in group and not mentioned/replied and state is not active, ignore video silently
    if is_group and not is_mentioned and not is_reply_to_bot and state != "WAITING_VIDEO_FOR_CAPTION":
        return

    if state != "WAITING_VIDEO_FOR_CAPTION":
        await update.message.reply_text(
            "⚠️ Silakan masuk ke menu **Caption** lalu klik **Generate** terlebih dahulu sebelum mengirimkan file video!\n\n"
            "Ketik /start untuk membuka menu utama.",
            parse_mode="Markdown"
        )
        return

    video = update.message.video or update.message.document
    if not video:
        return

    file_size_mb = video.file_size / (1024 * 1024)
    if file_size_mb > 20:
        await update.message.reply_text(
            "⚠️ Ukuran file video terlalu besar. Telegram membatasi unggahan ke bot maksimal 20MB. "
            "Silakan kompres video Anda atau kirimkan video yang lebih pendek."
        )
        return

    status_message = await update.message.reply_text("📥 Mengunduh video Anda...")
    
    try:
        context.user_data.clear()

        file = await context.bot.get_file(video.file_id)
        temp_dir = tempfile.gettempdir()
        file_ext = ".mp4"
        if hasattr(video, 'file_name') and video.file_name:
            _, file_ext = os.path.splitext(video.file_name)
            
        local_path = os.path.join(temp_dir, f"caption_{video.file_unique_id}{file_ext}")
        await file.download_to_drive(local_path)
        
        await status_message.edit_text("🎵 Mengekstrak & Mentranskripsi Audio (Groq Whisper)...")
        processed_path = analyzer.convert_video_to_audio_if_large(local_path)
        transcript_text = analyzer.transcribe_local_video(processed_path)
        
        safe_delete(local_path)
        if processed_path != local_path:
            safe_delete(processed_path)
            
        await status_message.edit_text("✍️ Menghasilkan Pilihan Caption Kreatif & Hashtags...")
        caption_report = analyzer.generate_caption(transcript_text)
        
        await update.message.reply_text(caption_report, parse_mode="Markdown")
        await status_message.delete()
        
    except Exception as e:
        logger.error(f"Error handling video for caption: {e}", exc_info=True)
        await status_message.edit_text(f"❌ Terjadi kesalahan saat memproses video: {str(e)}")

# tren_mode and exit_mode functions removed

# handle_video function removed

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if not text:
        return

    state = context.user_data.get("state")
    chat_type = update.effective_chat.type
    is_group = chat_type in ["group", "supergroup"]
    
    bot_username = context.bot.username or ""
    is_mentioned = f"@{bot_username}" in text if bot_username else False
    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        is_reply_to_bot = update.message.reply_to_message.from_user.id == context.bot.id

    # If in group and not mentioned/replied and state is not active, ignore message silently
    if is_group and not is_mentioned and not is_reply_to_bot and not state:
        return
    
    # 1. Handling for Caption Generator mode (Link input fallback)
    if state == "WAITING_VIDEO_FOR_CAPTION":
        url, platform, _ = extract_link(text)
        if url:
            context.user_data.clear() # Clear state
            status_message = await update.message.reply_text("📥 Mengunduh audio dari link untuk dibuatkan caption...")
            try:
                audio_path = analyzer.extract_youtube_audio(url)
                await status_message.edit_text("🎵 Mengekstrak & Mentranskripsi Audio (Groq Whisper)...")
                processed_path = analyzer.convert_video_to_audio_if_large(audio_path)
                transcript_text = analyzer.transcribe_local_video(processed_path)
                
                safe_delete(audio_path)
                if processed_path != audio_path:
                    safe_delete(processed_path)
                    
                await status_message.edit_text("✍️ Menghasilkan Pilihan Caption Kreatif & Hashtags...")
                caption_report = analyzer.generate_caption(transcript_text)
                
                await update.message.reply_text(caption_report, parse_mode="Markdown")
                await status_message.delete()
            except Exception as e:
                logger.error(f"Error generating caption from link: {e}", exc_info=True)
                err_msg = str(e)
                if "blocked" in err_msg.lower() or "ip address" in err_msg.lower() or "forbidden" in err_msg.lower():
                    await status_message.edit_text(
                        "❌ **IP Address Bot diblokir oleh TikTok/Instagram.**\n\n"
                        "Sistem keamanan TikTok/Instagram memblokir unduhan bot. "
                        "Silakan coba unggah file video hasil editan Anda secara langsung (maksimal 20MB).",
                        parse_mode="Markdown"
                    )
                else:
                    await status_message.edit_text(f"❌ Gagal memproses link tersebut: {err_msg}")
            return
        else:
            await update.message.reply_text(
                "⚠️ Format tidak dikenali. Silakan unggah file video hasil editan Anda, "
                "atau paste link video (YouTube/TikTok/Instagram) ke chat ini.\n\n"
                "Ketik /exit untuk membatalkan.",
                parse_mode="Markdown"
            )
            return

    # 2. Handling for Moment Clipping mode
    if state == "WAITING_YOUTUBE_LINK":
        url, platform, video_id = extract_link(text)
        if url:
            context.user_data.clear() # Clear state
            
            # Check if platform is not YouTube and user tried custom clip
            is_custom_clip = any(keyword in text.lower() for keyword in ["clip", "potong", "gunting", "cut", "trim", "ambil"])
            if is_custom_clip and platform != "youtube":
                await update.message.reply_text(
                    "⚠️ Fitur potong klip manual (custom clipping) saat ini hanya didukung untuk link YouTube.\n\n"
                    "Untuk link TikTok/Instagram, kami akan langsung menganalisis seluruh isi video tersebut secara otomatis.",
                    parse_mode="Markdown"
                )
                is_custom_clip = False

            if is_custom_clip and platform == "youtube" and video_id:
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
                            return # Exit early
                        except Exception as e:
                            logger.error(f"Gagal memotong klip kustom: {e}", exc_info=True)
                            await status_message.edit_text(f"❌ Terjadi kesalahan saat memotong klip video: {str(e)}")
                            return
                    else:
                        await status_message.edit_text("⚠️ Waktu mulai harus lebih kecil dari selesai, dan durasi maksimal klip kustom adalah 10 menit.")
                        return
                else:
                    await status_message.edit_text(
                        "⚠️ Gagal membaca instruksi rentang waktu pemotongan kustom Anda.\n\n"
                        "Contoh penulisan yang didukung:\n"
                        "• *'tolong clip dari menit 24.45 sampai 26.45'*\n"
                        "• *'clip menit 1:30 sampai 3:00'*\n"
                        "• *'potong detik 30 sampai 90'*",
                        parse_mode="Markdown"
                    )
                    return
            
            # Run full analysis
            status_message = await update.message.reply_text(f"📥 Mengunduh stream audio dari {platform.capitalize()}...")
            try:
                audio_path = analyzer.extract_youtube_audio(url)
                
                await status_message.edit_text(f"🎵 Memproses & Mentranskripsi audio {platform.capitalize()} (Groq Whisper)...")
                processed_path = analyzer.convert_video_to_audio_if_large(audio_path)
                verbose_data = analyzer.transcribe_audio_verbose(processed_path)
                sessions = analyzer.split_transcript_into_sessions(verbose_data)
                
                safe_delete(audio_path)
                if processed_path != audio_path:
                    safe_delete(processed_path)
                
                if not sessions:
                    await status_message.edit_text("❌ Gagal mendeteksi percakapan/suara dari link tersebut.")
                    return

                await status_message.edit_text(f"🧠 Menganalisis potensi viralitas & merekomendasikan klip ({len(sessions)} sesi)...")
                
                title = f"{platform.capitalize()} Video ({video_id or 'Video'})"
                for idx, session in enumerate(sessions):
                    label = session["session_label"]
                    text_transcript = session["transcript_text"]
                    
                    analysis_report = ""
                    for attempt in range(4):
                        analysis_report = analyzer.analyze_viral_potential(text_transcript, title, label)
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
                    
                    # Extract JSON data for buttons (only for YouTube)
                    clips_data = []
                    if platform == "youtube" and video_id:
                        json_match = re.search(r'=== CLIPS DATA ===\n(.*?)\n=== END CLIPS DATA ===', analysis_report, re.DOTALL)
                        if json_match:
                            try:
                                clips_data = json.loads(json_match.group(1).strip())
                            except Exception as e:
                                logger.error(f"Gagal memparsing clips JSON data: {e}")
                    
                    clean_report = re.sub(r'=== CLIPS DATA ===.*=== END CLIPS DATA ===', '', analysis_report, flags=re.DOTALL).strip()
                    
                    # Build inline buttons for each clip recommendation in this session (only for YouTube)
                    keyboard = []
                    if platform == "youtube" and video_id:
                        for clip in clips_data:
                            clip_id = clip.get("id", 1)
                            start_sec = clip.get("start", 0)
                            end_sec = clip.get("end", 0)
                            title_clip = clip.get("title", f"Klip {clip_id}")
                            callback_data = f"cut:{video_id}:{start_sec}:{end_sec}"
                            button_text = f"🎬 {title_clip}"
                            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
                        
                    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                    await update.message.reply_text(clean_report, parse_mode="Markdown", reply_markup=reply_markup)
                    
                await status_message.delete()
                
            except Exception as e:
                logger.error(f"Error handling link: {e}", exc_info=True)
                err_msg = str(e)
                if "blocked" in err_msg.lower() or "ip address" in err_msg.lower() or "forbidden" in err_msg.lower():
                    await status_message.edit_text(
                        "❌ **IP Address Bot diblokir oleh TikTok/Instagram.**\n\n"
                        "Sistem keamanan TikTok/Instagram memblokir unduhan bot. "
                        "Silakan gunakan link YouTube, atau unggah video langsung di bawah 20MB.",
                        parse_mode="Markdown"
                    )
                else:
                    await status_message.edit_text(f"❌ Terjadi kesalahan saat memproses link: {err_msg}")
            return
        else:
            await update.message.reply_text(
                "❌ Link tidak valid atau platform tidak didukung. Silakan kirim link YouTube, TikTok, atau Instagram yang valid.",
                parse_mode="Markdown"
            )
            return

    # 3. Fallback when not in any waiting state
    await update.message.reply_text(
        "⚠️ Silakan masuk ke menu utama `/start` terlebih dahulu untuk memilih fitur yang ingin digunakan!",
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
    
    try:
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
            
        if data == "menu:caption":
            caption_text = (
                "✍️ **Panduan Caption Generator**\n\n"
                "Fitur ini membantu Anda membuat caption media sosial yang pas, menarik, gaul (ala humor Gen Z), serta menyertakan rekomendasi hashtag viral untuk menaikkan views video hasil editan Anda.\n\n"
                "👉 **Cara Penggunaan**:\n"
                "Cukup klik tombol **✨ Generate** di bawah, lalu unggah/kirim file video hasil editan Anda (format MP4/MOV, maksimal 20MB) ke bot ini. AI akan mendengarkan suara/percakapan di dalamnya untuk membuat caption yang sesuai!"
            )
            keyboard = [
                [InlineKeyboardButton("✨ Generate", callback_data="menu:send_video")],
                [InlineKeyboardButton("« Kembali", callback_data="menu:main")]
            ]
            await query.message.edit_text(caption_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        if data == "menu:send_video":
            context.user_data["state"] = "WAITING_VIDEO_FOR_CAPTION"
            send_video_text = (
                "📥 **Mode Caption Generator Aktif**\n\n"
                "Silakan kirimkan/unggah file video hasil editan Anda (maksimal 20MB) ke chat ini sekarang.\n\n"
                "*(Ketik /exit atau klik tombol Keluar di bawah untuk menonaktifkan mode ini)*"
            )
            keyboard = [[InlineKeyboardButton("❌ Keluar", callback_data="menu:main")]]
            await query.message.edit_text(send_video_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
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
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.info("Callback ignored: message content is identical.")
        else:
            logger.error(f"Error in handle_callback: {e}", exc_info=True)

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

    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_for_caption))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started successfully in modular format. Polling for messages...")
    application.run_polling()
