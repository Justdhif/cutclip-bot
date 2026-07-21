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

HELP_TEXT = (
    "📖 **PANDUAN PENGGUNAAN CUTCLIP BOT** 🎬🤖\n\n"
    "Bot ini dirancang khusus untuk membantu Anda menganalisis video, memotong klip, dan membuat caption sosial media menggunakan AI!\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "1️⃣ **Deteksi Momen Viral (AI)**\n"
    "• **Cara**: Kirimkan link video (YouTube/TikTok/IG).\n"
    "• **Hasil**: AI menganalisis percakapan & menyajikan rekomendasi momen terbaik beserta tombol potong otomatis.\n\n"
    "2️⃣ **Potong Klip Kustom (Manual)**\n"
    "• **Cara**: Kirim link YouTube disertai durasi yang ingin dipotong.\n"
    "• **Contoh**: `klip dari menit 24.45 sampai 26.45 https://youtube...` atau `clip menit 1:30 sampai 3:00 https://youtube...`\n"
    "• **Hasil**: Bot memotong & mengunggah klip video HD 1080p.\n\n"
    "3️⃣ **Caption Generator (Gen Z Style)**\n"
    "• **Cara**: Unggah file video (maks 20MB) ATAU kirim link video dengan kata kunci *'caption'* (contoh: `buatkan caption https://...`).\n"
    "• **Hasil**: AI membuatkan 3 pilihan caption gaul Gen Z & daftar hashtag viral.\n\n"
    "👥 **Penggunaan di Grup Chat**:\n"
    "Di dalam grup, Anda **wajib men-tag bot** `@bot` agar bot merespons!\n"
    "• *Contoh*: `@bot clip menit 1 sampai 2 https://...`\n"
    "━━━━━━━━━━━━━━━━━━━"
)

CLIP_GUIDE_TEXT = (
    "🎬 **PANDUAN LENGKAP MEMOTONG (CLIP) VIDEO**\n\n"
    "Fitur ini memungkinkan Anda mendeteksi momen emas secara otomatis atau memotong klip video YouTube secara presisi!\n\n"
    "📌 **1. Pemotongan Kustom (Manual)**\n"
    "Kirimkan pesan berisi link YouTube dan tentukan waktu mulai & selesai.\n"
    "• **Format Menit.Detik**: `klip dari menit 24.45 sampai 26.45 https://youtube.com/watch?v=...`\n"
    "• **Format Jam:Menit:Detik**: `clip 1:15:30 sampai 1:17:00 https://...`\n"
    "• **Format Detik**: `potong detik 30 sampai 90 https://...`\n"
    "*(Klip diproses dalam resolusi Full HD 1080p / 60fps)*\n\n"
    "📌 **2. Deteksi Momen Otomatis (AI)**\n"
    "Cukup paste link video YouTube/TikTok/Instagram tanpa menyebutkan waktu. AI akan mengunduh audio, mentranskripsi percakapan, dan merekomendasikan momen-momen paling berpotensi viral lengkap dengan tombol pemotong otomatis!"
)

CAPTION_GUIDE_TEXT = (
    "✍️ **PANDUAN LENGKAP CAPTION GENERATOR**\n\n"
    "Fitur ini menggunakan AI untuk mendengarkan isi konten video Anda dan membuatkan caption gaul kekinian ala Gen Z serta tagar pemacu views!\n\n"
    "📌 **1. Mengunggah File Video Langsung**\n"
    "Unggah file video hasil editan Anda (format MP4/MOV, ukuran maksimal 20MB) langsung ke chat ini. AI akan otomatis mendengarkan suaranya.\n\n"
    "📌 **2. Menggunakan Link Video (YouTube/TikTok/IG)**\n"
    "Kirimkan link video disertai kata kunci *'caption'* atau *'deskripsi'*. Contoh:\n"
    "• `buatkan caption untuk link ini https://tiktok.com/...`\n"
    "• `caption https://youtube.com/shorts/...`\n\n"
    "📌 **Hasil yang Diberikan AI**:\n"
    "• **Pilihan 1**: Caption gaya Gen Z (gaul, relatable, kaomoji).\n"
    "• **Pilihan 2**: High Hook (clickbait & memikat penonton).\n"
    "• **Pilihan 3**: Singkat & Aesthetic.\n"
    "• **Hashtag Viral**: Daftar hashtag paling populer untuk boost views ke FYP/Explore."
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
    bot_username = context.bot.username or "bot"
    formatted_help = HELP_TEXT.replace("@bot", f"@{bot_username}")
    await update.message.reply_text(formatted_help, parse_mode="Markdown")

async def exit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 **Mode aktif telah dinonaktifkan.**\n\n" + WELCOME_TEXT,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def handle_video_for_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat_type = update.effective_chat.type
    is_group = chat_type in ["group", "supergroup"]
    
    bot_username = context.bot.username or ""
    caption = update.message.caption or ""
    is_mentioned = f"@{bot_username}" in caption if bot_username else False
    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        is_reply_to_bot = update.message.reply_to_message.from_user.id == context.bot.id

    # If in group, ignore video upload unless tagged in caption or replied to bot
    if is_group and not is_mentioned and not is_reply_to_bot:
        return

    video = update.message.video or update.message.document
    if not video:
        return

    file_size_mb = video.file_size / (1024 * 1024)
    if file_size_mb > 20:
        await update.message.reply_text(
            "⚠️ Ukuran file video terlalu besar. Telegram membatasi unggahan ke bot maksimal 20MB. "
            "Silakan kompres video Anda atau kirimkan link video (YouTube/TikTok/IG)."
        )
        return

    status_message = await update.message.reply_text("📥 Mengunduh video Anda untuk didengarkan...")
    
    try:
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
    if not update.message:
        return
    text = update.message.text
    if not text:
        return

    chat_type = update.effective_chat.type
    is_group = chat_type in ["group", "supergroup"]
    
    bot_username = context.bot.username or ""
    is_mentioned = f"@{bot_username}" in text if bot_username else False
    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        is_reply_to_bot = update.message.reply_to_message.from_user.id == context.bot.id

    # If in group and NOT mentioned and NOT replying to bot -> ignore message completely!
    if is_group and not is_mentioned and not is_reply_to_bot:
        return

    # Extract any supported video link (YouTube, TikTok, Instagram)
    url, platform, video_id = extract_link(text)
    
    if url:
        text_lower = text.lower()
        is_caption_request = any(keyword in text_lower for keyword in ["caption", "deskripsi", "tagar", "hashtag"])
        is_custom_clip = any(keyword in text_lower for keyword in ["clip", "potong", "gunting", "cut", "trim", "ambil"])

        # 1. Handle Caption Request for link
        if is_caption_request:
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

        # 2. Handle Custom Clip Request (YouTube)
        if is_custom_clip:
            if platform != "youtube":
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

        # 3. Default Analysis Request (YouTube, TikTok, Instagram)
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

    # 4. If NO link was provided:
    if is_group:
        tag_hint = f"@{bot_username}" if bot_username else "@bot"
        await update.message.reply_text(
            f"👋 Halo! Kirimkan link video (YouTube/TikTok/IG) beserta instruksi Anda.\n\n"
            f"Contoh penggunaan di grup:\n"
            f"• `{tag_hint} klip video ini dari menit 24.45 sampai 26.45 https://youtube...`\n"
            f"• `{tag_hint} analisis link ini https://youtube...`\n"
            f"• `{tag_hint} buatkan caption https://tiktok...`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 Silakan kirimkan link video (YouTube/TikTok/IG) atau unggah file video untuk memulai!\n\n"
            "• **Potong Klip**: *'clip dari menit 1 sampai 2 https://...'*\n"
            "• **Analisis Momen**: Langsung paste link video\n"
            "• **Caption Generator**: Unggah file video atau *'buatkan caption https://...'*",
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
            bot_username = context.bot.username or "bot"
            formatted_help = HELP_TEXT.replace("@bot", f"@{bot_username}")
            keyboard = [[InlineKeyboardButton("« Kembali", callback_data="menu:main")]]
            await query.message.edit_text(formatted_help, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        if data == "menu:clip":
            keyboard = [[InlineKeyboardButton("« Kembali", callback_data="menu:main")]]
            await query.message.edit_text(CLIP_GUIDE_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        if data == "menu:caption":
            keyboard = [[InlineKeyboardButton("« Kembali", callback_data="menu:main")]]
            await query.message.edit_text(CAPTION_GUIDE_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
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
