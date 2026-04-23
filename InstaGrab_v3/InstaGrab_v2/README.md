# InstaGrab 📸
**Download Instagram Posts, Reels, IGTV & Stories**

Built with Flask + yt-dlp. Supports both Video (MP4) and Audio (MP3) downloads.

---

## ⚡ Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the server
```bash
python app.py
```

### 3. Open in browser
```
http://localhost:5000
```

---

## 🌐 Supported URLs

| Type     | Example URL Pattern                          |
|----------|----------------------------------------------|
| Posts    | `https://www.instagram.com/p/XXXXXX/`        |
| Reels    | `https://www.instagram.com/reel/XXXXXX/`     |
| IGTV     | `https://www.instagram.com/tv/XXXXXX/`       |
| Stories  | `https://www.instagram.com/stories/user/ID/` |

---

## 🔐 Private Accounts (Cookie Login)

For private account content, export your Instagram cookies from your browser and save as `cookies.txt` in the project root.

Then update `app.py` to add:
```python
ydl_opts["cookiefile"] = "cookies.txt"
```

Use a browser extension like **Get cookies.txt LOCALLY** (Chrome/Firefox) to export Netscape-format cookies.

---

## 📁 Project Structure
```
InstaGrab/
├── app.py              # Flask backend
├── requirements.txt    # Dependencies
├── README.md
├── downloads/          # Temporary download storage (auto-cleaned)
└── templates/
    └── index.html      # Frontend UI
```

---

## ⚙️ How It Works

1. User pastes an Instagram URL and clicks Download
2. Flask starts a background thread using yt-dlp to fetch the media
3. Frontend polls `/api/status/<job_id>` every 1.5 seconds
4. When ready, user clicks **Save to Device** → Flask serves the file

---

## 📝 Notes
- Downloaded files are auto-deleted after 30 minutes
- For personal use only — respect content creators
- yt-dlp must be kept updated: `pip install -U yt-dlp`
