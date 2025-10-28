import os
import tempfile
import subprocess
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from yt_dlp import YoutubeDL

# === Base Directory ===
BASE_DIR = Path(__file__).resolve().parent

# === Paths ===
COOKIES_FILE = BASE_DIR / "cookies.txt"   # your cookies file
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# === FastAPI App ===
app = FastAPI()

# === Template Setup ===
templates = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

# === Static Files ===
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# === Download Directory ===
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yt_audio_downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# === Helper: Download Audio with yt-dlp ===
def download_audio_with_cookies(url: str, codec: str):
    """Downloads YouTube audio using yt-dlp with cookies"""
    job_dir = Path(tempfile.mkdtemp(prefix="yt_", dir=str(DOWNLOAD_DIR)))

    quality = "192" if codec == "mp3" else "0"
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": quality,
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    # Add cookies if file exists
    if COOKIES_FILE.exists():
        ydl_opts["cookiefile"] = str(COOKIES_FILE)

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")

    file_path = next(job_dir.glob(f"*.{codec}"), None)
    if not file_path:
        raise HTTPException(status_code=500, detail="Conversion failed.")

    # Rename the final file
    title = info.get("title", "downloaded_audio").replace("/", "_")
    final_name = f"{title}.{codec}"
    final_path = job_dir / final_name
    file_path.rename(final_path)

    return final_name, job_dir, title


# === Routes ===
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    tpl = templates.get_template("index.html")
    return HTMLResponse(tpl.render())


@app.post("/download")
async def download_youtube(url: str = Form(...), format: str = Form(...)):
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
                "download_url": f"/download_file/{final_name}?job_dir={job_dir.name}",
            }
        )
    )


@app.get("/download_file/{filename}")
async def serve_file(filename: str, job_dir: str):
    folder = DOWNLOAD_DIR / job_dir
    file_path = folder / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(str(file_path), filename=filename, media_type="audio/mpeg")
