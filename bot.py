import os
import re
import asyncio
import logging
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

TOKEN = "8853775879:AAF-e9lmNcvWHF4US1odePdP7lHKbOtBFuE"

COOKIE_FILE = "cookies.txt"

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
    return bool(
        re.match(
            r"^(https?://)?(www\.)?"
            r"(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)"
            r"[\w-]+",
            url,
            re.IGNORECASE,
        )
    )


# ============================================================
# SAFE FILENAME
# ============================================================

def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name[:120].strip()


# ============================================================
# PROGRESS
# ============================================================

class DownloadProgress:
    def __init__(self, message):
        self.message = message
        self.last_percent = -1
        self.last_update = 0

    def hook(self, data):

        if data["status"] == "downloading":

            total = (
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or 0
            )

            downloaded = data.get("downloaded_bytes", 0)

            if total:
                percent = int(
                    downloaded * 100 / total
                )
            else:
                percent = 0

            # Don't edit Telegram message on every packet.
            if percent != self.last_percent:

                self.last_percent = percent

                # Telegram API updates are expensive.
                # The async edit is scheduled safely.
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
                f"⬇️ Downloading...\n\n"
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

    await update.message.reply_text(
        "👋 नमस्ते!\n\n"
        "YouTube वीडियो का link भेजें।\n"
        
    )


# ============================================================
# YOUTUBE INFO
# ============================================================

def get_video_info(url: str):

    opts = {
        "js_runtimes": {"deno": {}},

        "quiet": True,
        "no_warnings": True,

        "cookiefile": COOKIE_FILE,

        "noplaylist": True,

        "socket_timeout": 30,

        "retries": 3,

        "fragment_retries": 3,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 14) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0.0.0 "
                "Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

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

    url = update.message.text.strip()

    if not is_youtube_url(url):

        await update.message.reply_text(
            "❌ कृपया valid YouTube URL भेजें।"
        )

        return

    status = await update.message.reply_text(
        "🔎 Video information निकाल रहा हूँ..."
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

        # Save URL and metadata in user context.
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

        await status.edit_text(
            "❌ YouTube information निकालने में "
            "समस्या हुई।\n\n"
            f"{str(e)[:1000]}"
        )


# ============================================================
# DOWNLOAD VIDEO
# ============================================================

def download_video(
    url: str,
    progress_hook,
):

    output_template = str(
        DOWNLOAD_DIR / "%(title)s.%(ext)s"
    )

    opts = {

        "js_runtimes": {"deno": {}},

        "cookiefile": COOKIE_FILE,

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        # Best video + best audio.
        # Falls back to a combined stream.
        "format": "bv*+ba/b",

        "merge_output_format": "mp4",

        "outtmpl": output_template,

        "progress_hooks": [
            progress_hook
        ],

        "retries": 3,

        "fragment_retries": 3,

        "socket_timeout": 30,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 14) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0.0.0 "
                "Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    with yt_dlp.YoutubeDL(opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        # After merging, extension may change.
        base = os.path.splitext(filename)[0]

        possible_files = [
            base + ".mp4",
            filename,
        ]

        for path in possible_files:

            if os.path.exists(path):
                return path

        # Last fallback.
        requested = info.get(
            "requested_downloads"
        ) or []

        for item in requested:

            path = item.get(
                "filepath"
            )

            if path and os.path.exists(path):
                return path

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
        DOWNLOAD_DIR / "%(title)s.%(ext)s"
    )

    opts = {

        "cookiefile": COOKIE_FILE,

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        # Best available audio.
        "format": "ba/bestaudio/best",

        "outtmpl": output_template,

        "progress_hooks": [
            progress_hook
        ],

        "retries": 3,

        "fragment_retries": 3,

        "socket_timeout": 30,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 14) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0.0.0 "
                "Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        base = os.path.splitext(filename)[0]

        mp3_file = base + ".mp3"

        if os.path.exists(mp3_file):
            return mp3_file

        if os.path.exists(filename):
            return filename

        raise FileNotFoundError(
            "Downloaded audio file not found."
        )


# ============================================================
# CALLBACK
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    data = query.data

    youtube_data = context.user_data.get(
        "youtube"
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

    # --------------------------------------------------------
    # VIDEO
    # --------------------------------------------------------

    if data == "download_video":

        status = await query.message.reply_text(
            "🎥 Video download शुरू हो रहा है..."
        )

        progress = DownloadProgress(
            status
        )

        try:

            filepath = await asyncio.to_thread(
                download_video,
                url,
                progress.hook,
            )

            if not os.path.exists(filepath):

                raise FileNotFoundError(
                    "Video file नहीं मिली।"
                )

            size = os.path.getsize(
                filepath
            )

            if size > MAX_VIDEO_SIZE:

                await status.edit_text(
                    "❌ Video तैयार है, लेकिन "
                    "Telegram bot upload limit के "
                    "कारण यह file बहुत बड़ी है।"
                )

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
                    caption=f"🎥 {title[:900]}",
                    supports_streaming=True,
                )

            await status.delete()

            try:
                os.remove(filepath)
            except Exception:
                pass

        except Exception as e:

            logger.exception(
                "Video download failed"
            )

            await status.edit_text(
                "❌ Video download failed.\n\n"
                f"{str(e)[:1500]}"
            )


    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    elif data == "download_audio":

        status = await query.message.reply_text(
            "🎵 Audio download शुरू हो रहा है..."
        )

        progress = DownloadProgress(
            status
        )

        try:

            filepath = await asyncio.to_thread(
                download_audio,
                url,
                progress.hook,
            )

            if not os.path.exists(filepath):

                raise FileNotFoundError(
                    "Audio file नहीं मिली।"
                )

            size = os.path.getsize(
                filepath
            )

            if size > MAX_AUDIO_SIZE:

                await status.edit_text(
                    "❌ Audio तैयार है, लेकिन "
                    "Telegram upload limit के "
                    "कारण file बहुत बड़ी है।"
                )

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

            try:
                os.remove(filepath)
            except Exception:
                pass

        except Exception as e:

            logger.exception(
                "Audio download failed"
            )

            await status.edit_text(
                "❌ Audio download failed.\n\n"
                f"{str(e)[:1500]}"
            )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Unhandled bot error",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":

        raise RuntimeError(
            "TOKEN में अपना Telegram Bot Token डालें।"
        )

    # Check FFmpeg.
    if os.system(
        "command -v ffmpeg >/dev/null 2>&1"
    ) != 0:

        print(
            "WARNING: ffmpeg नहीं मिला। "
            "Video merge और MP3 conversion काम नहीं करेंगे।"
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

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
            filters.TEXT & ~filters.COMMAND,
            receive_url,
        )
    )

    app.add_error_handler(
        error_handler
    )

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


if __name__ == "__main__":
    main()
