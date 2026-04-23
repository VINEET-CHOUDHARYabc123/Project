import os
import re
import uuid
import threading
import time
import requests
from flask import Flask, request, jsonify, send_file, render_template
import yt_dlp

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
    "X-IG-App-ID": "936619743392459",
}

# Errors that mean we need login
LOGIN_TRIGGERS = [
    "login", "inappropriate", "private", "unavailable for certain",
    "not available", "age", "restricted", "authentication", "401", "403"
]

def needs_login(error_msg):
    msg = error_msg.lower()
    return any(t in msg for t in LOGIN_TRIGGERS)

# ── URL detection ──────────────────────────────────────────────────────────────

def detect_url_type(url):
    url = url.strip()
    if re.search(r"instagram\.com/(p|reel|tv)/[\w\-]+", url):
        return "post"
    if re.search(r"instagram\.com/stories/[\w\.]+/\d+", url):
        return "story"
    if re.match(r"(https?://)?(www\.)?instagram\.com/[\w\.]+/?$", url):
        return "profile"
    if re.match(r"^@?[\w\.]{1,30}$", url):
        return "username"
    return "unknown"

def extract_username(url):
    url = url.strip().rstrip("/")
    if url.startswith("@"):
        return url[1:]
    m = re.search(r"instagram\.com/([\w\.]+)$", url)
    return m.group(1) if m else url

# ── Profile Pic ────────────────────────────────────────────────────────────────

def download_profile_pic(job_id, username, ig_user=None, ig_pass=None):
    try:
        jobs[job_id]["status"] = "downloading"
        pic_url = None

        session = requests.Session()
        session.headers.update(HEADERS)

        # If credentials provided, login first
        if ig_user and ig_pass:
            try:
                login_resp = session.post(
                    "https://www.instagram.com/api/v1/web/accounts/login/ajax/",
                    data={"username": ig_user, "password": ig_pass},
                    headers={**HEADERS, "X-CSRFToken": "missing", "X-Requested-With": "XMLHttpRequest"},
                    timeout=15
                )
            except Exception:
                pass  # continue anyway, try fetching

        api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        resp = session.get(api_url, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user", {})
            pic_url = user.get("profile_pic_url_hd") or user.get("profile_pic_url")

        if not pic_url:
            page = session.get(f"https://www.instagram.com/{username}/", timeout=15)
            m = re.search(r'"profile_pic_url_hd":"([^"]+)"', page.text)
            if not m:
                m = re.search(r'"profile_pic_url":"([^"]+)"', page.text)
            if m:
                pic_url = m.group(1).replace("\\u0026", "&")

        if not pic_url:
            # If no credentials were given, ask for login
            if not ig_user:
                jobs[job_id]["status"] = "need_login"
                jobs[job_id]["reason"] = "This account may be private. Please login to continue."
                return
            raise ValueError(f"Could not find profile picture for @{username}.")

        img_resp = session.get(pic_url, timeout=30, stream=True)
        img_resp.raise_for_status()

        filename = f"{job_id}_{username}_dp.jpg"
        with open(os.path.join(DOWNLOAD_DIR, filename), "wb") as f:
            for chunk in img_resp.iter_content(8192):
                f.write(chunk)

        jobs[job_id].update({
            "status": "done",
            "files": [{"filename": filename, "label": f"@{username} — Profile Pic"}],
            "title": f"@{username} Profile Picture",
            "thumbnail": pic_url,
        })

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

# ── yt-dlp downloader ──────────────────────────────────────────────────────────

def build_ydl_opts(output_path, media_type, ig_user=None, ig_pass=None):
    opts = {
        "outtmpl": output_path,
        "quiet": True,
        "noplaylist": False,
        "age_limit": 18,
        "http_headers": HEADERS,
        "extractor_retries": 3,
        "retries": 5,
    }
    if ig_user and ig_pass:
        opts["username"] = ig_user
        opts["password"] = ig_pass

    if media_type == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        opts["format"] = "bestvideo+bestaudio/best"
        opts["merge_output_format"] = "mp4"

    return opts

def do_download(job_id, url, media_type, ig_user=None, ig_pass=None):
    try:
        jobs[job_id]["status"] = "downloading"
        output_path = os.path.join(DOWNLOAD_DIR, f"{job_id}_%(autonumber)s_%(title).30s.%(ext)s")
        ydl_opts = build_ydl_opts(output_path, media_type, ig_user, ig_pass)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        all_files = sorted([f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(job_id)])
        if not all_files:
            raise FileNotFoundError("Downloaded file not found.")

        title = info.get("title") or "Instagram Media"
        file_list = [
            {
                "filename": fname,
                "label": f"File {i+1} — {fname.rsplit('.',1)[-1].upper()}" if len(all_files) > 1 else title
            }
            for i, fname in enumerate(all_files)
        ]

        jobs[job_id].update({
            "status": "done",
            "files": file_list,
            "title": title,
            "thumbnail": info.get("thumbnail", ""),
        })

    except Exception as e:
        err = str(e)
        # If it's an auth error and no credentials were given → ask for login
        if needs_login(err) and not ig_user:
            jobs[job_id]["status"] = "need_login"
            jobs[job_id]["reason"] = "This content requires login (private or age-restricted)."
        else:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = err

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json
    raw       = (data.get("url") or "").strip()
    media_type = data.get("type", "video")
    ig_user   = (data.get("username") or "").strip() or None
    ig_pass   = (data.get("password") or "").strip() or None

    if not raw:
        return jsonify({"error": "URL or username is required."}), 400

    url_type = detect_url_type(raw)
    if url_type == "unknown":
        return jsonify({"error": "Invalid input. Paste an Instagram URL or @username."}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "url": raw}

    if url_type in ("profile", "username"):
        username = extract_username(raw)
        t = threading.Thread(target=download_profile_pic,
                             args=(job_id, username, ig_user, ig_pass), daemon=True)
    else:
        t = threading.Thread(target=do_download,
                             args=(job_id, raw, media_type, ig_user, ig_pass), daemon=True)

    t.start()
    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)

@app.route("/api/file/<job_id>/<filename>")
def get_file(job_id, filename):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "File not ready."}), 404
    if not filename.startswith(job_id):
        return jsonify({"error": "Forbidden."}), 403
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found."}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)

def cleanup():
    while True:
        time.sleep(600)
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fp) and now - os.path.getmtime(fp) > 1800:
                os.remove(fp)

threading.Thread(target=cleanup, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
