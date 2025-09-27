from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello from Flask!'

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
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": "Failed to extract video info", "details": str(e)}), 500

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
                "download_url": f.get('url')
            })

        # Audio-only
        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
            audios.append({
                "format": f.get('ext'),
                "abr": f.get('abr'),
                "download_url": f.get('url')
            })

    return jsonify({
        "title": info.get('title'),
        "thumbnail": info.get('thumbnail'),
        "videos": videos,
        "audios": audios
    })


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
