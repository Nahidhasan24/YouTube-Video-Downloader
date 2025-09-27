from flask import Flask, request, jsonify
import yt_dlp
import random
import time
import re
import os

app = Flask(__name__)

# Lightweight user agents for Railway
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# Rate limiting storage
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
            'ratelimit': 256000,
            'socket_timeout': 30,
        }
    else:
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

def categorize_formats(formats):
    """Categorize formats into multiple types with detailed information"""
    
    # Progressive formats (video + audio combined)
    progressive_formats = []
    # Adaptive video formats (video only)
    adaptive_video_formats = []
    # Adaptive audio formats (audio only)
    adaptive_audio_formats = []
    
    seen_combinations = set()
    
    for f in formats:
        if not f.get('url'):
            continue
            
        # Skip problematic formats
        ext = f.get('ext', '')
        protocol = f.get('protocol', '')
        if any(x in ext or x in protocol for x in ['m3u8', 'mpd', 'dash']):
            continue
            
        # Get basic format info
        format_id = f.get('format_id', '')
        filesize = f.get('filesize', 0)
        quality = f.get('quality', 0)
        
        # Progressive format (video + audio together)
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            height = f.get('height', 0)
            if height >= 144:
                format_key = f"{height}p-{ext}-progressive"
                if format_key not in seen_combinations:
                    seen_combinations.add(format_key)
                    progressive_formats.append({
                        "type": "progressive",
                        "quality": f"{height}p",
                        "height": height,
                        "width": f.get('width'),
                        "format": ext,
                        "format_note": f.get('format_note', ''),
                        "filesize": filesize,
                        "filesize_mb": round(filesize / (1024 * 1024), 2) if filesize else 0,
                        "video_codec": f.get('vcodec', '').split('.')[0],
                        "audio_codec": f.get('acodec', '').split('.')[0],
                        "fps": f.get('fps'),
                        "download_url": f.get('url'),
                        "format_id": format_id
                    })
        
        # Adaptive video (video only)
        elif f.get('vcodec') != 'none' and f.get('acodec') == 'none':
            height = f.get('height', 0)
            if height >= 144:
                format_key = f"{height}p-{ext}-adaptive-video"
                if format_key not in seen_combinations:
                    seen_combinations.add(format_key)
                    adaptive_video_formats.append({
                        "type": "adaptive_video",
                        "quality": f"{height}p",
                        "height": height,
                        "width": f.get('width'),
                        "format": ext,
                        "format_note": f.get('format_note', ''),
                        "filesize": filesize,
                        "filesize_mb": round(filesize / (1024 * 1024), 2) if filesize else 0,
                        "video_codec": f.get('vcodec', '').split('.')[0],
                        "fps": f.get('fps'),
                        "download_url": f.get('url'),
                        "format_id": format_id
                    })
        
        # Adaptive audio (audio only)
        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
            audio_bitrate = f.get('abr', 0)
            format_key = f"audio-{audio_bitrate}-{ext}"
            if format_key not in seen_combinations:
                seen_combinations.add(format_key)
                adaptive_audio_formats.append({
                    "type": "adaptive_audio",
                    "format": ext,
                    "audio_codec": f.get('acodec', '').split('.')[0],
                    "bitrate": audio_bitrate,
                    "bitrate_kbps": f"{audio_bitrate} kbps" if audio_bitrate else "Unknown",
                    "sample_rate": f.get('asr'),
                    "filesize": filesize,
                    "filesize_mb": round(filesize / (1024 * 1024), 2) if filesize else 0,
                    "download_url": f.get('url'),
                    "format_id": format_id
                })
    
    # Sort formats
    progressive_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
    adaptive_video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
    adaptive_audio_formats.sort(key=lambda x: x.get('bitrate', 0), reverse=True)
    
    return {
        "progressive": progressive_formats[:15],  # Limit to top 15
        "adaptive_video": adaptive_video_formats[:15],
        "adaptive_audio": adaptive_audio_formats[:10]
    }

@app.route('/')
def hello_world():
    return jsonify({
        "message": "YouTube Video Links API",
        "status": "active",
        "endpoints": {
            "get_video_links": "POST /api/get_video_links",
            "health_check": "GET /api/health"
        },
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
    max_attempts = 2
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

    # Categorize formats into multiple types
    formats = categorize_formats(info.get('formats', []))

    # Get thumbnails in different qualities
    thumbnails = info.get('thumbnails', [])
    thumbnail_dict = {}
    if thumbnails:
        for thumb in thumbnails:
            quality = thumb.get('id', 'default')
            thumbnail_dict[quality] = thumb.get('url')
    else:
        thumbnail_dict['default'] = info.get('thumbnail')

    response_data = {
        "video_info": {
            "title": info.get('title', 'Unknown'),
            "duration": info.get('duration'),
            "duration_string": info.get('duration_string'),
            "uploader": info.get('uploader'),
            "uploader_id": info.get('uploader_id'),
            "view_count": info.get('view_count'),
            "like_count": info.get('like_count'),
            "description": info.get('description', '')[:500] + '...' if info.get('description') and len(info.get('description', '')) > 500 else info.get('description', ''),
            "upload_date": info.get('upload_date'),
            "video_id": video_id,
            "categories": info.get('categories', []),
            "tags": info.get('tags', [])[:10]  # Limit tags
        },
        "thumbnails": thumbnail_dict,
        "formats": formats,
        "format_summary": {
            "progressive_count": len(formats["progressive"]),
            "adaptive_video_count": len(formats["adaptive_video"]),
            "adaptive_audio_count": len(formats["adaptive_audio"]),
            "total_formats": len(formats["progressive"]) + len(formats["adaptive_video"]) + len(formats["adaptive_audio"])
        },
        "success": True
    }

    return jsonify(response_data)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for Railway"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "YouTube Video Links API",
        "rate_limited_ips": len(request_times)
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
    """Clean old rate limiting data"""
    now = time.time()
    global request_times
    for ip in list(request_times.keys()):
        request_times[ip] = [t for t in request_times[ip] if now - t < 300]
        if not request_times[ip]:
            del request_times[ip]

# Cleanup every 10th request
request_count = 0

@app.before_request
def before_request():
    global request_count
    request_count += 1
    if request_count % 10 == 0:
        cleanup_old_requests()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)