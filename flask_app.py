from flask import Flask, request, jsonify
import yt_dlp
import random
import time
import re
import os
import logging
from datetime import datetime
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class Config:
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW = 60
    CACHE_DURATION = 300
    MAX_FORMATS_PER_CATEGORY = 15

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# Storage
request_times = {}
cache = {}

def format_file_size(bytes_size):
    """Convert bytes to human readable format (KB, MB, GB, TB)"""
    if bytes_size is None:
        return "Unknown"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0 or unit == 'TB':
            break
        bytes_size /= 1024.0
    
    if unit == 'B':
        return f"{int(bytes_size)} {unit}"
    else:
        return f"{bytes_size:.2f} {unit}"

def is_rate_limited(ip):
    """Rate limiting with IP hashing"""
    ip_hash = hashlib.md5(ip.encode()).hexdigest()
    now = time.time()
    
    if ip_hash not in request_times:
        request_times[ip_hash] = []
    
    request_times[ip_hash] = [t for t in request_times[ip_hash] if now - t < Config.RATE_LIMIT_WINDOW]
    
    if len(request_times[ip_hash]) >= Config.RATE_LIMIT_REQUESTS:
        return True
    
    request_times[ip_hash].append(now)
    return False

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&?/]+)',
        r'youtube\.com/watch\?.*v=([^&]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_ydl_options(attempt=1):
    """Get yt-dlp options with format selection for video+audio"""
    base_headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
    }
    
    # Critical fix: Use format selection that ensures video has audio
    format_selector = 'bv*+ba/b'  # Best video + best audio, fallback to best pre-merged
    
    if attempt == 1:
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'format': format_selector,  # This ensures video includes audio
            'extract_flat': False,
            'ignoreerrors': True,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'ratelimit': 512000,
            'socket_timeout': 30,
        }
    else:
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'format': format_selector,  # Consistent format selection across attempts
            'ignoreerrors': True,
            'retries': 2,
            'socket_timeout': 25,
        }

def categorize_formats(info):
    """
    Categorize formats with proper video+audio handling
    Uses yt-dlp's format selection results
    """
    formats = info.get('formats', [])
    requested_formats = info.get('requested_formats', [])
    
    progressive_formats = []
    adaptive_video_formats = []
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
        
        filesize = f.get('filesize')
        filesize_display = format_file_size(filesize)
        
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
                        "filesize_display": filesize_display,
                        "video_codec": f.get('vcodec', '').split('.')[0],
                        "audio_codec": f.get('acodec', '').split('.')[0],
                        "fps": f.get('fps'),
                        "audio_bitrate": f.get('abr'),
                        "download_url": f.get('url'),
                        "format_id": f.get('format_id', ''),
                        "has_audio": True,
                        "has_video": True
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
                        "filesize_display": filesize_display,
                        "video_codec": f.get('vcodec', '').split('.')[0],
                        "fps": f.get('fps'),
                        "download_url": f.get('url'),
                        "format_id": f.get('format_id', ''),
                        "has_audio": False,
                        "has_video": True
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
                    "bitrate_display": f"{audio_bitrate} kbps" if audio_bitrate else "Unknown",
                    "sample_rate": f.get('asr'),
                    "filesize": filesize,
                    "filesize_display": filesize_display,
                    "download_url": f.get('url'),
                    "format_id": f.get('format_id', ''),
                    "has_audio": True,
                    "has_video": False
                })
    
    # Sort formats
    progressive_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
    adaptive_video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
    adaptive_audio_formats.sort(key=lambda x: x.get('bitrate', 0), reverse=True)
    
    return {
        "progressive": progressive_formats[:Config.MAX_FORMATS_PER_CATEGORY],
        "adaptive_video": adaptive_video_formats[:Config.MAX_FORMATS_PER_CATEGORY],
        "adaptive_audio": adaptive_audio_formats[:Config.MAX_FORMATS_PER_CATEGORY],
        "recommended_format": info.get('format_id'),  # yt-dlp's recommended format
        "requested_formats": len(requested_formats)  # Info about merged formats
    }

@app.route('/')
def home():
    return jsonify({
        "message": "Professional YouTube Video Links API",
        "version": "2.1.0",
        "status": "active",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "Video + audio format selection",
            "Human-readable file sizes",
            "Rate limiting",
            "Multiple quality options"
        ]
    })

@app.route('/api/get_video_links', methods=['POST'])
def get_video_links():
    start_time = time.time()
    
    # Rate limiting
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if isinstance(client_ip, str) and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    if is_rate_limited(client_ip):
        return jsonify({
            "error": "Rate limit exceeded",
            "message": f"Maximum {Config.RATE_LIMIT_REQUESTS} requests per minute allowed"
        }), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON data"}), 400
    
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "YouTube URL is required"}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    clean_url = f"https://www.youtube.com/watch?v={video_id}"

    # Extract video information
    max_attempts = 2
    info = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            ydl_opts = get_ydl_options(attempt)
            
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
                        "message": "Try again later or use cookies for authentication"
                    }), 503
                else:
                    return jsonify({
                        "error": "Failed to extract video info",
                        "message": str(e)
                    }), 500
            continue
            
        except Exception as e:
            if attempt == max_attempts:
                return jsonify({
                    "error": "Extraction failed",
                    "message": str(e)
                }), 500
            continue

    if not info:
        return jsonify({
            "error": "Could not extract video information",
            "message": "Please try again later"
        }), 500

    # Categorize formats with the new function
    formats = categorize_formats(info)

    # Prepare response
    response_data = {
        "video_info": {
            "title": info.get('title', 'Unknown Title'),
            "duration": info.get('duration'),
            "duration_display": info.get('duration_string'),
            "uploader": info.get('uploader', 'Unknown Uploader'),
            "view_count": info.get('view_count'),
            "upload_date": info.get('upload_date'),
            "video_id": video_id,
            "webpage_url": info.get('webpage_url'),
        },
        "thumbnail": info.get('thumbnail'),
        "formats": formats,
        "success": True,
        "response_time": round((time.time() - start_time) * 1000, 2),
        "timestamp": datetime.now().isoformat()
    }

    return jsonify(response_data)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "YouTube Video Links API"
    })

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)