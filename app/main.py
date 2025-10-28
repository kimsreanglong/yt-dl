import os
import tempfile
import shutil
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from yt_dlp import YoutubeDL

# === Base directory ===
BASE_DIR = Path(__file__).resolve().parent

# === FastAPI app ===
app = FastAPI()

# === Template setup ===
templates = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)

# === Static files ===
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# === Temporary download folder ===
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yt_audio_downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# === Helper: clean temp folder ===
def clean_folder(folder: Path):
    if folder.exists():
        shutil.rmtree(folder)

# === Routes ===
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    tpl = templates.get_template("index.html")
    return HTMLResponse(tpl.render())

@app.post("/download")
async def download_youtube(
    url: str = Form(...),
    format: str = Form(...),
    cookies: UploadFile | None = None
):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    # Temporary folder for this download
    job_dir = Path(tempfile.mkdtemp(prefix="yt_", dir=str(DOWNLOAD_DIR)))

    # Determine codec and quality
    codec = "mp3" if format.lower() == "mp3" else "wav"
    quality = "320" if codec == "mp3" else "0"

    # Handle cookies: environment variable or uploaded file
    cookies_path = None
    cookies_env = os.getenv("COOKIES_DATA")
    if cookies_env:
        cookies_path = job_dir / "cookies.txt"
        cookies_path.write_text(cookies_env)

    if cookies:
        cookies_path = job_dir / "cookies.txt"
        with open(cookies_path, "wb") as f:
            f.write(await cookies.read())

    # yt-dlp options
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": quality}
        ],
        "quiet": True,
        "no_warnings": True,
    }

    if cookies_path:
        ydl_opts["cookiefile"] = str(cookies_path)

    # Download the audio
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        clean_folder(job_dir)
        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {e}. Ensure the video is public or provide valid cookies."
        )

    # Get the downloaded file
    file_path = next(job_dir.glob(f"*.{codec}"), None)
    if not file_path or file_path.stat().st_size == 0:
        clean_folder(job_dir)
        raise HTTPException(
            status_code=500,
            detail="Download failed: The downloaded file is empty. Try a public video or provide valid cookies."
        )

    # Safe filename
    title = info.get("title", "downloaded_audio").replace("/", "_")
    final_name = f"{title}.{codec}"
    final_path = job_dir / final_name
    file_path.rename(final_path)

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
    
    # Set proper MIME type
    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(str(file_path), filename=filename, media_type=media_type)
