from flask import Flask, request, jsonify
import yt_dlp
import random
import time

app = Flask(__name__)

# List of user agents to rotate
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
]

@app.route('/')
def hello_world():
    return 'Hello from Flask!'

@app.route('/api/get_video_links', methods=['POST'])
def get_video_links():
    data = request.json
    url = data.get('url')

    if not url:
        return jsonify({"error": "You must provide a YouTube URL"}), 400

    # Enhanced yt-dlp options to avoid detection
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'no_warnings': False,
        
        # Headers configuration
        'http_headers': {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        },
        
        # Extractor options
        'extract_flat': False,
        'ignoreerrors': False,
        'no_overwrites': True,
        
        # Retry configuration
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'keep_fragments': False,
        
        # Rate limiting to appear more human-like
        'ratelimit': 512000,  # 500 KB/s
        'throttledratelimit': 512000,
        
        # YouTube specific options
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
        
        # Simulate human behavior
        'sleep_interval': 2,
        'max_sleep_interval': 5,
        
        # Format selection
        'format': 'best[height<=1080]',  # Limit to 1080p to avoid suspicious behavior
    }

    try:
        # Add small delay to simulate human behavior
        time.sleep(random.uniform(1, 3))
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First try with standard extraction
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                # If first attempt fails, try with different parameters
                if "Sign in" in str(e) or "bot" in str(e).lower():
                    # Retry with more conservative settings
                    ydl_opts['ratelimit'] = 256000  # Slow down more
                    ydl_opts['retries'] = 5
                    ydl_opts['sleep_interval'] = 5
                    
                    # Try different user agent
                    ydl_opts['http_headers']['User-Agent'] = random.choice(USER_AGENTS)
                    
                    time.sleep(random.uniform(3, 6))  # Longer delay
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                        info = ydl_retry.extract_info(url, download=False)
                else:
                    raise e

    except yt_dlp.DownloadError as e:
        if "Sign in" in str(e):
            return jsonify({
                "error": "YouTube is requiring authentication. This is a temporary restriction. Please try again later or use a different network.",
                "details": "Try again in a few hours or consider using cookies for authentication."
            }), 503
        else:
            return jsonify({
                "error": "Failed to extract video info", 
                "details": str(e)
            }), 500
    except Exception as e:
        return jsonify({
            "error": "An unexpected error occurred",
            "details": str(e)
        }), 500

    # Process formats
    videos = []
    audios = []

    for f in info.get('formats', []):
        if not f.get('url'):
            continue

        ext = f.get('ext')
        protocol = f.get('protocol', '')

        # Skip problematic formats
        if ext in ['m3u8', 'webm_dash', 'f4f', 'mpd'] or 'm3u8' in protocol:
            continue

        # Skip formats with very low quality or suspicious properties
        if f.get('quality') == -1 or f.get('preference') == -1000:
            continue

        # Progressive video (video + audio)
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            # Filter out very low resolution videos
            height = f.get('height')
            if height and height >= 144:  # Minimum 144p
                videos.append({
                    "resolution": f.get('resolution') or f"{height}p",
                    "format": ext,
                    "height": height,
                    "width": f.get('width'),
                    "filesize": f.get('filesize'),
                    "download_url": f.get('url')
                })

        # Audio-only
        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
            audios.append({
                "format": ext,
                "abr": f.get('abr'),  # audio bitrate
                "asr": f.get('asr'),  # audio sample rate
                "filesize": f.get('filesize'),
                "download_url": f.get('url')
            })

    # Sort videos by resolution (highest first)
    videos.sort(key=lambda x: x.get('height', 0), reverse=True)
    
    # Sort audios by bitrate (highest first)
    audios.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)

    # Remove duplicates based on resolution and format
    seen = set()
    unique_videos = []
    for video in videos:
        key = (video.get('height'), video.get('format'))
        if key not in seen:
            seen.add(key)
            unique_videos.append(video)

    response_data = {
        "title": info.get('title'),
        "thumbnail": info.get('thumbnail'),
        "duration": info.get('duration'),
        "uploader": info.get('uploader'),
        "view_count": info.get('view_count'),
        "videos": unique_videos,
        "audios": audios,
        "success": True
    }

    return jsonify(response_data)

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)