"""
YTGRAB - YouTube Downloader Backend
Requires: pip install flask yt-dlp flask-cors
Run:      python app.py
"""

import os, json, uuid, threading, time
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from flask_cors import CORS

try:
    import yt_dlp
except ImportError:
    print("ERROR: yt-dlp not installed. Run: pip install yt-dlp")
    exit(1)

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# In-memory job store
jobs = {}  # job_id -> dict

# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def get_format_opts(mode, fmt, quality, codec, speed):
    """Build yt-dlp format/postprocessor options."""
    opts = {
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s_%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": False,
    }

    if speed and speed != "unlimited":
        opts["ratelimit"] = speed  # e.g. "2M" → 2MB/s

    if mode == "audio":
        audio_codec_map = {
            "mp3": "mp3", "m4a": "m4a", "flac": "flac",
            "wav": "wav", "ogg": "vorbis", "opus": "opus"
        }
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_codec_map.get(fmt, "mp3"),
            "preferredquality": "192",
        }]

    elif mode == "thumbnail":
        opts["skip_download"] = True
        opts["writethumbnail"] = True
        opts["postprocessors"] = [{"key": "FFmpegThumbnailsConvertor", "format": fmt}]

    elif mode in ("video", "playlist"):
        quality_map = {
            "4k": "bestvideo[height<=2160]+bestaudio/best",
            "1440p": "bestvideo[height<=1440]+bestaudio/best",
            "1080p": "bestvideo[height<=1080]+bestaudio/best",
            "720p": "bestvideo[height<=720]+bestaudio/best",
            "480p": "bestvideo[height<=480]+bestaudio/best",
            "360p": "bestvideo[height<=360]+bestaudio/best",
            "best": "bestvideo+bestaudio/best",
        }
        opts["format"] = quality_map.get(quality, "bestvideo+bestaudio/best")

        codec_map = {"h264": "h264", "h265": "hevc", "vp9": "vp9", "av1": "av1"}
        vcodec = codec_map.get(codec)
        if vcodec and codec != "auto":
            opts["format"] += f"[vcodec~='{vcodec}']"

        merge_map = {"mp4": "mp4", "webm": "webm", "mkv": "mkv", "avi": "avi", "mov": "mov"}
        if fmt in merge_map:
            opts["merge_output_format"] = merge_map[fmt]

    return opts


def make_progress_hook(job_id):
    def hook(d):
        job = jobs.get(job_id)
        if not job:
            return
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed", 0)
            eta = d.get("eta", 0)
            pct = (downloaded / total * 100) if total else 0
            job.update({
                "status": "downloading",
                "progress": round(pct, 1),
                "speed": format_speed(speed),
                "eta": format_eta(eta),
                "downloaded": format_bytes(downloaded),
                "total": format_bytes(total),
                "filename": d.get("filename", ""),
            })
        elif d["status"] == "finished":
            job.update({"status": "processing", "progress": 99})
        elif d["status"] == "error":
            job.update({"status": "error", "error": str(d.get("error", "Unknown"))})
    return hook


def format_speed(bps):
    if not bps: return "—"
    if bps > 1_000_000: return f"{bps/1_000_000:.1f} MB/s"
    if bps > 1_000: return f"{bps/1_000:.0f} KB/s"
    return f"{bps:.0f} B/s"

def format_bytes(b):
    if not b: return "—"
    if b > 1_000_000_000: return f"{b/1_000_000_000:.2f} GB"
    if b > 1_000_000: return f"{b/1_000_000:.1f} MB"
    if b > 1_000: return f"{b/1_000:.0f} KB"
    return f"{b} B"

def format_eta(s):
    if not s: return "—"
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/info", methods=["POST"])
def get_info():
    """Fetch video/playlist metadata without downloading."""
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" in info:
            # Playlist
            entries = [e for e in info["entries"] if e]
            return jsonify({
                "type": "playlist",
                "title": info.get("title", "Playlist"),
                "uploader": info.get("uploader", ""),
                "count": len(entries),
                "entries": [
                    {"title": e.get("title", f"Video {i+1}"), "id": e.get("id", "")}
                    for i, e in enumerate(entries[:100])
                ],
                "thumbnail": info.get("thumbnails", [{}])[-1].get("url", "") if info.get("thumbnails") else "",
            })
        else:
            return jsonify({
                "type": "video",
                "title": info.get("title", ""),
                "uploader": info.get("uploader", ""),
                "duration": info.get("duration", 0),
                "view_count": info.get("view_count", 0),
                "thumbnail": info.get("thumbnail", ""),
                "description": (info.get("description") or "")[:300],
                "upload_date": info.get("upload_date", ""),
                "formats": [
                    {"format_id": f["format_id"], "ext": f.get("ext",""), "height": f.get("height",0),
                     "filesize": f.get("filesize",0), "vcodec": f.get("vcodec",""), "acodec": f.get("acodec","")}
                    for f in info.get("formats", [])
                    if f.get("height") or f.get("acodec") != "none"
                ][-20:],
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def start_download():
    """Queue a download job and return job_id."""
    data = request.json or {}
    url   = data.get("url", "").strip()
    mode  = data.get("mode", "video")
    fmt   = data.get("format", "mp4")
    qual  = data.get("quality", "1080p")
    codec = data.get("codec", "auto")
    speed = data.get("speed", "unlimited")
    subs  = data.get("subtitles", "none")
    naming = data.get("naming", "title")
    play_from = int(data.get("playFrom", 1))
    play_to   = int(data.get("playTo", 50))

    if not url:
        return jsonify({"error": "No URL"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id, "url": url, "mode": mode, "format": fmt,
        "status": "queued", "progress": 0,
        "speed": "—", "eta": "—", "downloaded": "—", "total": "—",
        "files": [], "error": None, "created": time.time()
    }

    def run():
        try:
            opts = get_format_opts(mode, fmt, qual, codec, speed)
            opts["progress_hooks"] = [make_progress_hook(job_id)]

            # Naming template
            name_map = {
                "title": "%(title)s.%(ext)s",
                "id": "%(id)s.%(ext)s",
                "title-id": "%(title)s_%(id)s.%(ext)s",
                "date-title": "%(upload_date)s_%(title)s.%(ext)s",
            }
            opts["outtmpl"] = str(DOWNLOAD_DIR / name_map.get(naming, "%(title)s.%(ext)s"))

            # Subtitles
            if subs != "none":
                opts["writesubtitles"] = True
                opts["subtitleslangs"] = ["all"] if subs == "all" else [subs]
                opts["postprocessors"] = opts.get("postprocessors", []) + [
                    {"key": "FFmpegEmbedSubtitle"}
                ]

            # Playlist range
            if mode == "playlist":
                opts["playliststart"] = play_from
                opts["playlistend"] = play_to

            jobs[job_id]["status"] = "downloading"

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

            # Collect output files
            files = []
            for f in DOWNLOAD_DIR.iterdir():
                if f.stat().st_mtime > jobs[job_id]["created"] - 2:
                    files.append(f.name)

            jobs[job_id].update({
                "status": "done",
                "progress": 100,
                "files": files,
                "title": info.get("title", "") if info else "",
                "thumbnail": info.get("thumbnail", "") if info else "",
            })

        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e), "progress": 0})

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/file/<filename>")
def serve_file(filename):
    path = DOWNLOAD_DIR / filename
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(path), as_attachment=True)


@app.route("/files")
def list_files():
    files = []
    for f in sorted(DOWNLOAD_DIR.iterdir(), key=lambda x: -x.stat().st_mtime):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": format_bytes(f.stat().st_size),
                "mtime": f.stat().st_mtime,
            })
    return jsonify(files)


@app.route("/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    path = DOWNLOAD_DIR / filename
    if path.exists():
        path.unlink()
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


@app.route("/jobs")
def all_jobs():
    return jsonify(list(jobs.values()))


if __name__ == "__main__":
    print("=" * 50)
    print("  YTGRAB Server starting...")
    print("  Open: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000, threaded=True)
