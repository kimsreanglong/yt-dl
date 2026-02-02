import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from yt_dlp import YoutubeDL

# ======================================================
# Paths & Directories
# ======================================================

BASE_DIR = Path(__file__).resolve().parent

# 🔐 Render Secret File location
COOKIES_FILE = Path("/etc/secrets/cookies.txt")

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Temporary download storage
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yt_audio_downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ======================================================
# FastAPI App
# ======================================================

app = FastAPI()

# Templates
templates = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ======================================================
# Helper: Download Audio via yt-dlp
# ======================================================

def download_audio_with_cookies(url: str, codec: str):
    job_dir = Path(tempfile.mkdtemp(prefix="yt_", dir=str(DOWNLOAD_DIR)))

    quality = "192" if codec == "mp3" else "0"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": quality,
            }
        ],
    }

    # ✅ Attach cookies ONLY if valid
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
        ydl_opts["cookiefile"] = str(COOKIES_FILE)

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="YouTube blocked this request. Cookies may be missing or expired."
        )

    # Find output file
    file_path = next(job_dir.glob(f"*.{codec}"), None)
    if not file_path:
        raise HTTPException(status_code=500, detail="Audio conversion failed.")

    # Sanitize filename (Windows + URL safe)
    title = info.get("title", "downloaded_audio")
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)
    final_name = f"{safe_title}.{codec}"
    final_path = job_dir / final_name

    file_path.rename(final_path)

    return final_name, job_dir.name, title

# ======================================================
# Routes
# ======================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    tpl = templates.get_template("index.html")
    return HTMLResponse(tpl.render())

@app.post("/download")
async def download_youtube(
    url: str = Form(...),
    format: str = Form(...)
):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    codec = "mp3" if format == "mp3" else "wav"

    final_name, job_dir, title = download_audio_with_cookies(url, codec)

    tpl = templates.get_template("result.html")
    return HTMLResponse(
        tpl.render(
            {
                "title": title,
                "format": codec.upper(),
                "download_url": (
                    f"/download_file"
                    f"?filename={final_name}"
                    f"&job_dir={job_dir}"
                ),
            }
        )
    )

@app.get("/download_file")
async def serve_file(
    filename: str = Query(...),
    job_dir: str = Query(...)
):
    folder = DOWNLOAD_DIR / job_dir
    file_path = folder / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="audio/mpeg"
    )
