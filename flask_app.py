from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

# --- Simple Hello World ---
@app.route('/')
def hello_world():
    return 'Hello from Flask!'

# --- YouTube Downloader API ---
@app.route('/api/get_video_links', methods=['POST'])
def get_video_links():
    data = request.json
    url = data.get('url')

    if not url:
        return jsonify({"error": "You must provide a YouTube URL"}), 400

    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'noproxy': True,
        'ignoreerrors': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": "Failed to extract video info. Check the URL or your network.", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    formats = []
    for f in info.get('formats', []):
        if f.get('url'):
            formats.append({
                "format_id": f.get('format_id'),
                "ext": f.get('ext'),
                "resolution": f.get('resolution') or f.get('height'),
                "filesize_MB": round(f.get('filesize', 0) / (1024*1024), 2) if f.get('filesize') else None,
                "fps": f.get('fps'),
                "abr": f.get('abr'),
                "download_url": f.get('url')
            })

    return jsonify({
        "title": info.get('title'),
        "uploader": info.get('uploader'),
        "formats": formats
    })


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
