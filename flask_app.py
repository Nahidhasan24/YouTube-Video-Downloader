from flask import Flask, request, jsonify
import yt_dlp
import random
import time
import re
import requests
from urllib.parse import parse_qs, urlparse

app = Flask(__name__)

# Lightweight user agents for Railway
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# Rate limiting storage (in-memory for Railway)
request_times = {}

def is_rate_limited(ip, max_requests=5, window_seconds=60):
    """Basic rate limiting for Railway"""
    now = time.time()
    if ip not in request_times:
        request_times[ip] = []
    
    # Clean old requests
    request_times[ip] = [t for t in request_times[ip] if now - t < window_seconds]
    
    if len(request_times[ip]) >= max_requests:
        return True
    
    request_times[ip].append(now)
    return False

def extract_video_id(url):
    """Extract video ID from various YouTube URL formats"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&?/]+)',
        r'youtube\.com/watch\?.*v=([^&]+)',
        r'youtube\.com/v/([^?]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_ydl_options(attempt):
    """Get optimized yt-dlp options for Railway"""
    base_headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
    }
    
    if attempt == 1:
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'extract_flat': False,
            'ignoreerrors': True,
            'retries': 2,
            'fragment_retries': 2,
            'skip_unavailable_fragments': True,
            'ratelimit': 256000,  # Conservative rate limit
            'socket_timeout': 30,
            'extractor_args': {'youtube': {'player_skip': ['configs']}},
        }
    else:
        # Second attempt with different approach
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'ignoreerrors': True,
            'extract_flat': 'in_playlist',
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
            'retries': 1,
            'socket_timeout': 20,
        }

@app.route('/')
def hello_world():
    return jsonify({
        "message": "YouTube Video Links API",
        "status": "active",
        "usage": "POST /api/get_video_links with JSON body: {'url': 'youtube_url'}"
    })

@app.route('/api/get_video_links', methods=['POST'])
def get_video_links():
    # Get client IP for rate limiting
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if isinstance(client_ip, str) and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    # Rate limiting check
    if is_rate_limited(client_ip, max_requests=3, window_seconds=60):
        return jsonify({
            "error": "Rate limit exceeded",
            "message": "Too many requests. Please try again in a minute."
        }), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON data"}), 400
    
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "You must provide a YouTube URL"}), 400

    # Validate YouTube URL
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    # Construct proper YouTube URL
    clean_url = f"https://www.youtube.com/watch?v={video_id}"

    # Try extraction with retries
    max_attempts = 2  # Limited attempts for Railway
    info = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            ydl_opts = get_ydl_options(attempt)
            
            # Add delay between attempts
            if attempt > 1:
                time.sleep(random.uniform(2, 4))
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                break
                
        except yt_dlp.DownloadError as e:
            error_msg = str(e)
            if attempt == max_attempts:
                # Final attempt failed
                if "Sign in" in error_msg:
                    return jsonify({
                        "error": "YouTube authentication required",
                        "message": "This is a temporary restriction. Please try again later.",
                        "video_id": video_id
                    }), 503
                elif "Failed to extract any player response" in error_msg:
                    return jsonify({
                        "error": "YouTube API change detected",
                        "message": "Please try again later or use a different video.",
                        "video_id": video_id
                    }), 503
                else:
                    return jsonify({
                        "error": "Failed to extract video info",
                        "message": str(e),
                        "video_id": video_id
                    }), 500
            # Continue to next attempt
            continue
            
        except Exception as e:
            if attempt == max_attempts:
                return jsonify({
                    "error": "Extraction failed",
                    "message": str(e),
                    "video_id": video_id
                }), 500
            continue

    if not info:
        return jsonify({
            "error": "Could not extract video information",
            "message": "Please try again later.",
            "video_id": video_id
        }), 500

    # Process formats efficiently
    videos = []
    audios = []
    seen_formats = set()

    for f in info.get('formats', [])[:50]:  # Limit processing for efficiency
        if not f.get('url'):
            continue

        # Skip problematic formats
        ext = f.get('ext', '')
        protocol = f.get('protocol', '')
        if any(x in ext or x in protocol for x in ['m3u8', 'mpd', 'dash']):
            continue

        # Create format signature to avoid duplicates
        format_sig = f"{f.get('height', 0)}-{f.get('vcodec', 'none')}-{f.get('acodec', 'none')}-{ext}"
        if format_sig in seen_formats:
            continue
        seen_formats.add(format_sig)

        # Video with audio
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            height = f.get('height', 0)
            if height >= 144:  # Reasonable minimum
                videos.append({
                    "resolution": f"{height}p",
                    "format": ext,
                    "height": height,
                    "filesize": f.get('filesize'),
                    "download_url": f.get('url')
                })

        # Audio only
        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
            audios.append({
                "format": ext,
                "bitrate": f.get('abr'),
                "download_url": f.get('url')
            })

    # Sort and limit results
    videos.sort(key=lambda x: x.get('height', 0), reverse=True)
    audios.sort(key=lambda x: x.get('bitrate', 0) or 0, reverse=True)
    
    # Limit number of results for efficiency
    videos = videos[:10]
    audios = audios[:5]

    response_data = {
        "title": info.get('title', 'Unknown'),
        "thumbnail": info.get('thumbnail'),
        "duration": info.get('duration'),
        "uploader": info.get('uploader'),
        "video_id": video_id,
        "videos": videos,
        "audios": audios,
        "success": True
    }

    return jsonify(response_data)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for Railway"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Video Links API"
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method not allowed"}), 405

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# Clean up rate limiting data periodically
def cleanup_old_requests():
    """Clean old rate limiting data (basic implementation)"""
    now = time.time()
    global request_times
    for ip in list(request_times.keys()):
        request_times[ip] = [t for t in request_times[ip] if now - t < 300]  # 5 minutes
        if not request_times[ip]:
            del request_times[ip]

# Simple cleanup on every 10th request
request_count = 0

@app.before_request
def before_request():
    global request_count
    request_count += 1
    if request_count % 10 == 0:
        cleanup_old_requests()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    # Don't use debug mode in production
    app.run(host='0.0.0.0', port=port, debug=False)