import os
import re
import asyncio
import logging
import shutil
from pathlib import Path

import yt_dlp

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

# ============================================================
# 🔴 अपना नया BotFather TOKEN यहाँ डालो
# ============================================================

TOKEN = "8853775879:AAF-e9lmNcvWHF4US1odePdP7lHKbOtBFuE"


# Cookies अभी OFF हैं
USE_COOKIES = False
COOKIE_FILE = "cookies.txt"

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Telegram upload के लिए लगभग 49 MB limit रखी है
MAX_VIDEO_SIZE = 49 * 1024 * 1024
MAX_AUDIO_SIZE = 49 * 1024 * 1024


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# URL CHECK
# ============================================================

def is_youtube_url(url: str) -> bool:

    pattern = (
        r"^(https?://)?"
        r"(www\.)?"
        r"(youtube\.com/watch\?v=|"
        r"youtu\.be/|"
        r"youtube\.com/shorts/)"
        r"[\w-]+"
    )

    return bool(
        re.match(
            pattern,
            url,
            re.IGNORECASE,
        )
    )


# ============================================================
# COMMON YT-DLP OPTIONS
# ============================================================

def get_common_opts():

    opts = {
        # YouTube JS challenge solving
        "js_runtimes": {
            "deno": {}
        },

        # EJS package
        "remote_components": {
            "ejs:github"
        },

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "socket_timeout": 30,

        "retries": 3,

        "fragment_retries": 3,

        "concurrent_fragment_downloads": 4,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 14) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0.0.0 "
                "Mobile Safari/537.36"
            ),

            "Accept-Language": (
                "en-US,en;q=0.9"
            ),
        },
    }

    # ========================================================
    # OPTIONAL COOKIES
    # ========================================================

    if USE_COOKIES:

        cookie_path = Path(COOKIE_FILE)

        if cookie_path.exists():

            opts["cookiefile"] = str(
                cookie_path
            )

            logger.info(
                "YouTube cookies enabled."
            )

        else:

            logger.warning(
                "USE_COOKIES=True लेकिन cookies.txt नहीं मिला."
            )

    return opts


# ============================================================
# PROGRESS
# ============================================================

class DownloadProgress:

    def __init__(self, message):

        self.message = message
        self.last_percent = -1

    def hook(self, data):

        if data.get("status") != "downloading":
            return

        total = (
            data.get("total_bytes")
            or data.get("total_bytes_estimate")
            or 0
        )

        downloaded = (
            data.get("downloaded_bytes", 0)
        )

        if total:

            percent = int(
                downloaded * 100 / total
            )

        else:

            percent = 0

        # Same percentage दोबारा update नहीं करेंगे
        if percent == self.last_percent:
            return

        self.last_percent = percent

        try:

            loop = asyncio.get_running_loop()

            loop.create_task(
                self.safe_update(percent)
            )

        except Exception:
            pass

    async def safe_update(self, percent):

        try:

            await self.message.edit_text(
                "⬇️ Downloading...\n\n"
                f"Progress: {percent}%"
            )

        except Exception:
            pass


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    await update.message.reply_text(
        "👋 नमस्ते!\n\n"
        "YouTube वीडियो का link भेजें।\n\n"
        "फिर मैं आपको Video और Audio के options दूँगा।"
    )


# ============================================================
# GET YOUTUBE INFO
# ============================================================

def get_video_info(url: str):

    opts = get_common_opts()

    with yt_dlp.YoutubeDL(opts) as ydl:

        return ydl.extract_info(
            url,
            download=False,
        )


# ============================================================
# RECEIVE URL
# ============================================================

async def receive_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if not update.message.text:
        return

    url = update.message.text.strip()

    if not is_youtube_url(url):

        await update.message.reply_text(
            "❌ कृपया valid YouTube URL भेजें।"
        )

        return

    status = await update.message.reply_text(
        "🔎 YouTube information निकाल रहा हूँ..."
    )

    try:

        info = await asyncio.to_thread(
            get_video_info,
            url,
        )

        title = info.get(
            "title",
            "YouTube Video",
        )

        duration = info.get(
            "duration",
            0,
        )

        video_id = info.get(
            "id",
            "",
        )

        # User के लिए current YouTube data save
        context.user_data["youtube"] = {
            "url": url,
            "title": title,
            "duration": duration,
            "id": video_id,
        }

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🎥 Video",
                        callback_data="download_video",
                    ),

                    InlineKeyboardButton(
                        "🎵 Audio",
                        callback_data="download_audio",
                    ),
                ]
            ]
        )

        duration_text = ""

        if duration:

            minutes = duration // 60
            seconds = duration % 60

            duration_text = (
                f"\n⏱ Duration: "
                f"{minutes}:{seconds:02d}"
            )

        await status.edit_text(

            f"🎬 {title}"
            f"{duration_text}\n\n"
            "क्या डाउनलोड करना है?",

            reply_markup=keyboard,
        )

    except Exception as e:

        logger.exception(
            "Metadata extraction failed"
        )

        error_text = str(e)

        await status.edit_text(

            "❌ YouTube information निकालने में "
            "समस्या हुई।\n\n"

            f"{error_text[:1500]}"
        )


# ============================================================
# FIND DOWNLOADED FILE
# ============================================================

def find_downloaded_file(
    info,
    prepared_filename,
    extensions,
):

    # --------------------------------------------------------
    # Requested downloads
    # --------------------------------------------------------

    requested = (
        info.get("requested_downloads")
        or []
    )

    for item in requested:

        filepath = item.get(
            "filepath"
        )

        if filepath and os.path.exists(
            filepath
        ):

            return filepath

    # --------------------------------------------------------
    # Prepared filename
    # --------------------------------------------------------

    if os.path.exists(
        prepared_filename
    ):

        return prepared_filename

    # --------------------------------------------------------
    # Try extensions
    # --------------------------------------------------------

    base = os.path.splitext(
        prepared_filename
    )[0]

    for ext in extensions:

        path = base + ext

        if os.path.exists(path):

            return path

    # --------------------------------------------------------
    # Latest file fallback
    # --------------------------------------------------------

    if DOWNLOAD_DIR.exists():

        files = [
            x
            for x in DOWNLOAD_DIR.iterdir()
            if x.is_file()
        ]

        files.sort(
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        for file in files:

            if (
                not extensions
                or file.suffix.lower()
                in extensions
            ):

                return str(file)

    return None


# ============================================================
# DOWNLOAD VIDEO
# ============================================================

def download_video(
    url: str,
    progress_hook,
):

    output_template = str(
        DOWNLOAD_DIR
        / "%(title)s [%(id)s].%(ext)s"
    )

    opts = get_common_opts()

    opts.update({

        # पहले <=720p try करेगा
        # फिर available fallback
        "format": (
            "bv*[height<=720]+ba/"
            "b[height<=720]/"
            "bv*+ba/b"
        ),

        "merge_output_format": "mp4",

        "outtmpl": output_template,

        "progress_hooks": [
            progress_hook
        ],
    })

    with yt_dlp.YoutubeDL(opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        filepath = find_downloaded_file(
            info,
            filename,
            [
                ".mp4",
                ".mkv",
                ".webm",
            ],
        )

        if filepath:

            return filepath

        raise FileNotFoundError(
            "Downloaded video file not found."
        )


# ============================================================
# DOWNLOAD AUDIO
# ============================================================

def download_audio(
    url: str,
    progress_hook,
):

    output_template = str(
        DOWNLOAD_DIR
        / "%(title)s [%(id)s].%(ext)s"
    )

    opts = get_common_opts()

    opts.update({

        "format": (
            "ba/"
            "bestaudio/"
            "best"
        ),

        "outtmpl": output_template,

        "progress_hooks": [
            progress_hook
        ],

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",

                "preferredcodec": "mp3",

                "preferredquality": "192",
            }
        ],
    })

    with yt_dlp.YoutubeDL(opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        filepath = find_downloaded_file(
            info,
            filename,
            [
                ".mp3",
                ".m4a",
                ".opus",
                ".webm",
            ],
        )

        if filepath:

            return filepath

        raise FileNotFoundError(
            "Downloaded audio file not found."
        )


# ============================================================
# DELETE FILE
# ============================================================

def delete_file(filepath):

    try:

        if filepath and os.path.exists(
            filepath
        ):

            os.remove(filepath)

    except Exception:

        logger.exception(
            "Could not delete file"
        )


# ============================================================
# VIDEO SIZE CHECK
# ============================================================

def check_file_size(
    filepath,
    maximum_size,
):

    if not os.path.exists(filepath):

        return False, 0

    size = os.path.getsize(filepath)

    return size <= maximum_size, size


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = query.data

    youtube_data = (
        context.user_data.get(
            "youtube"
        )
    )

    if not youtube_data:

        await query.message.reply_text(
            "❌ यह download request expire हो गई है।"
        )

        return

    url = youtube_data["url"]

    title = youtube_data.get(
        "title",
        "YouTube",
    )

    # ========================================================
    # VIDEO
    # ========================================================

    if data == "download_video":

        status = await query.message.reply_text(
            "🎥 Video download शुरू हो रहा है..."
        )

        progress = DownloadProgress(
            status
        )

        filepath = None

        try:

            filepath = await asyncio.to_thread(
                download_video,
                url,
                progress.hook,
            )

            if not filepath:

                raise FileNotFoundError(
                    "Video file नहीं मिली।"
                )

            if not os.path.exists(filepath):

                raise FileNotFoundError(
                    "Video file नहीं मिली।"
                )

            valid, size = check_file_size(
                filepath,
                MAX_VIDEO_SIZE,
            )

            logger.info(
                "Video downloaded: %s bytes",
                size,
            )

            if not valid:

                await status.edit_text(

                    "❌ Video तैयार है, लेकिन "
                    "file बहुत बड़ी है।\n\n"

                    f"Size: "
                    f"{size / 1024 / 1024:.1f} MB"
                )

                delete_file(filepath)

                return

            await status.edit_text(
                "📤 Video Telegram पर भेज रहा हूँ..."
            )

            with open(
                filepath,
                "rb"
            ) as video_file:

                await query.message.reply_video(

                    video=video_file,

                    caption=(
                        f"🎥 {title[:900]}"
                    ),

                    supports_streaming=True,
                )

            await status.delete()

            delete_file(filepath)

        except Exception as e:

            logger.exception(
                "Video download failed"
            )

            if filepath:
                delete_file(filepath)

            try:

                await status.edit_text(

                    "❌ Video download failed.\n\n"
                    f"{str(e)[:1500]}"
                )

            except Exception:
                pass

    # ========================================================
    # AUDIO
    # ========================================================

    elif data == "download_audio":

        status = await query.message.reply_text(
            "🎵 Audio download शुरू हो रहा है..."
        )

        progress = DownloadProgress(
            status
        )

        filepath = None

        try:

            filepath = await asyncio.to_thread(
                download_audio,
                url,
                progress.hook,
            )

            if not filepath:

                raise FileNotFoundError(
                    "Audio file नहीं मिली।"
                )

            if not os.path.exists(filepath):

                raise FileNotFoundError(
                    "Audio file नहीं मिली।"
                )

            valid, size = check_file_size(
                filepath,
                MAX_AUDIO_SIZE,
            )

            logger.info(
                "Audio downloaded: %s bytes",
                size,
            )

            if not valid:

                await status.edit_text(

                    "❌ Audio तैयार है, लेकिन "
                    "file बहुत बड़ी है।\n\n"

                    f"Size: "
                    f"{size / 1024 / 1024:.1f} MB"
                )

                delete_file(filepath)

                return

            await status.edit_text(
                "📤 Audio Telegram पर भेज रहा हूँ..."
            )

            with open(
                filepath,
                "rb"
            ) as audio_file:

                await query.message.reply_audio(

                    audio=audio_file,

                    title=title[:64],

                    performer="YouTube",
                )

            await status.delete()

            delete_file(filepath)

        except Exception as e:

            logger.exception(
                "Audio download failed"
            )

            if filepath:
                delete_file(filepath)

            try:

                await status.edit_text(

                    "❌ Audio download failed.\n\n"
                    f"{str(e)[:1500]}"
                )

            except Exception:
                pass


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Unhandled bot error: %s",
        context.error,
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # TOKEN CHECK
    # ========================================================

    if (
        not TOKEN
        or TOKEN == "PASTE_YOUR_NEW_BOT_TOKEN_HERE"
        or TOKEN == "अपना_नया_BOT_TOKEN"
    ):

        raise RuntimeError(

            "\nBOT TOKEN सही नहीं है.\n\n"

            "bot.py की शुरुआत में यह line खोजो:\n\n"

            'TOKEN = "PASTE_YOUR_NEW_BOT_TOKEN_HERE"\n\n'

            "और इसके अंदर BotFather का नया token डालो."
        )

    # ========================================================
    # FFMPEG
    # ========================================================

    if shutil.which("ffmpeg"):

        print("FFmpeg: OK")

    else:

        print(
            "WARNING: FFmpeg नहीं मिला."
        )

        print(
            "Video merge और MP3 conversion "
            "काम नहीं कर सकते."
        )

    # ========================================================
    # DENO
    # ========================================================

    if shutil.which("deno"):

        print("Deno: OK")

    else:

        print(
            "WARNING: Deno नहीं मिला."
        )

    # ========================================================
    # YT-DLP VERSION
    # ========================================================

    try:

        print(
            "yt-dlp:",
            yt_dlp.version.__version__
        )

    except Exception:

        print(
            "yt-dlp version: unknown"
        )

    # ========================================================
    # COOKIES STATUS
    # ========================================================

    if USE_COOKIES:

        print(
            "Cookies: ON"
        )

    else:

        print(
            "Cookies: OFF"
        )

    # ========================================================
    # TELEGRAM APPLICATION
    # ========================================================

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # ========================================================
    # HANDLERS
    # ========================================================

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            receive_url,
        )
    )

    app.add_error_handler(
        error_handler
    )

    # ========================================================
    # START
    # ========================================================

    print(
        "===================================="
    )

    print(
        " YouTube Telegram Bot Started"
    )

    print(
        " Video + Audio buttons enabled"
    )

    print(
        "===================================="
    )

    app.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()