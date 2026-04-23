# YTGRAB — YouTube Downloader

Full-stack YouTube downloader with a sleek web UI.
Supports video, audio, playlists, and thumbnails.

---

## Quick Start

### 1. Install Dependencies
```bash
pip install flask flask-cors yt-dlp
```

### 2. Start the Server
```bash
python app.py
```

### 3. Open in Browser
```
http://localhost:5000
```

---

## Features

- **Video** — MP4, WebM, MKV, AVI, MOV, FLV up to 4K
- **Audio** — MP3, M4A, FLAC, WAV, OGG, Opus
- **Playlist** — Download full playlists with range control
- **Thumbnail** — Save video thumbnails as JPG/PNG/WebP
- **Inspect** — Preview title, duration, view count before downloading
- **Queue** — Multiple downloads with live progress
- **Files** — Browse and re-download saved files
- **Advanced** — Codec, subtitles, speed limit, file naming

## Requirements

- Python 3.8+
- ffmpeg (for audio extraction and format conversion)

### Install ffmpeg
- **Windows:** `winget install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Ubuntu/Debian:** `sudo apt install ffmpeg`

---

## Project Structure

```
ytgrab/
├── app.py            # Flask backend
├── requirements.txt
├── downloads/        # Saved files (auto-created)
└── static/
    └── index.html    # Web UI
```
