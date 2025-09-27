from flask import Flask, request, jsonify
import yt_dlp
import os

app = Flask(__name__)

# --- Hello World ---
@app.route('/')
def hello_world():
    return 'Hello from Flask!'

# --- YouTube Downloader API with optional cookies ---
@app.route('/api/get_video_links', methods=['POST'])
def get_video_links():
    data = request.json
    url = data.get('url')
    use_cookies = data.get('use_cookies', False)  # boolean, optional

    if not url:
        return jsonify({"error": "You must provide a YouTube URL"}), 400

    # Prepare yt-dlp options
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'noproxy': True,
    }

    # Use cookies if requested and file exists
    cookies_path = 'cookies.txt'
    if use_cookies:
        if os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path
        else:
            return jsonify({"error": "cookies.txt not found. Please upload your cookies file."}), 400

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({
            "error": "Failed to extract video info",
            "details": str(e)
        }), 500

    videos = []
    audios = []

    for f in info.get('formats', []):
        if not f.get('url'):
            continue

        ext = f.get('ext')

        # Skip HLS or DASH streams
        if ext in ['m3u8', 'webm_dash', 'f4m', 'mpd']:
            continue

        # Progressive video (video + audio)
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            videos.append({
                "resolution": f.get('resolution') or f.get('height'),
                "format": f.get('ext'),
                "language": f.get('language'),
                "download_url": f.get('url')
            })

        # Audio-only
        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
            audios.append({
                "format": f.get('ext'),
                "abr": f.get('abr'),
                "language": f.get('language'),
                "download_url": f.get('url')
            })

    # Sort videos by resolution descending
    videos = sorted(videos, key=lambda x: int(x['resolution'].replace('p','')) if x['resolution'] else 0, reverse=True)
    # Sort audios by bitrate descending
    audios = sorted(audios, key=lambda x: x.get('abr') or 0, reverse=True)

    return jsonify({
        "title": info.get('title'),
        "thumbnail": info.get('thumbnail'),
        "videos": videos,
        "audios": audios
    })


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
