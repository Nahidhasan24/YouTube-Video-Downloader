from flask import Flask, request, jsonify
import yt_dlp
import random
import time
import re
import os
import logging
from datetime import datetime, timedelta
import hashlib
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
class Config:
    RATE_LIMIT_REQUESTS = 10  # Increased for bigger user base
    RATE_LIMIT_WINDOW = 60  # seconds
    MAX_RETRY_ATTEMPTS = 3
    CACHE_DURATION = 300  # 5 minutes cache
    MAX_FORMATS_PER_CATEGORY = 20

# Lightweight user agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
]

# Storage for rate limiting and caching
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

def is_rate_limited(ip, max_requests=Config.RATE_LIMIT_REQUESTS, window_seconds=Config.RATE_LIMIT_WINDOW):
    """Improved rate limiting with IP hashing"""
    ip_hash = hashlib.md5(ip.encode()).hexdigest()  # Hash IP for privacy
    now = time.time()
    
    if ip_hash not in request_times:
        request_times[ip_hash] = []
    
    # Clean old requests
    request_times[ip_hash] = [t for t in request_times[ip_hash] if now - t < window_seconds]
    
    if len(request_times[ip_hash]) >= max_requests:
        return True
    
    request_times[ip_hash].append(now)
    return False

def get_cache_key(url):
    """Generate cache key from URL"""
    return hashlib.md5(url.encode()).hexdigest()

def get_cached_data(url):
    """Get cached data if available and not expired"""
    cache_key = get_cache_key(url)
    if cache_key in cache:
        data, timestamp = cache[cache_key]
        if time.time() - timestamp < Config.CACHE_DURATION:
            return data
    return None

def set_cache_data(url, data):
    """Cache data with timestamp"""
    cache_key = get_cache_key(url)
    cache[cache_key] = (data, time.time())

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

def validate_youtube_url(url):
    """Validate YouTube URL and return standardized version"""
    video_id = extract_video_id(url)
    if not video_id:
        return None, "Invalid YouTube URL"
    
    # Validate video ID format
    if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        return None, "Invalid YouTube video ID"
    
    return f"https://www.youtube.com/watch?v={video_id}", video_id

def get_ydl_options(attempt):
    """Get optimized yt-dlp options"""
    base_headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    }
    
    if attempt == 1:
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'extract_flat': False,
            'ignoreerrors': True,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'ratelimit': 512000,
            'socket_timeout': 30,
            'extractor_args': {'youtube': {'player_skip': ['configs']}},
        }
    elif attempt == 2:
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'ignoreerrors': True,
            'extract_flat': 'in_playlist',
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
            'retries': 2,
            'socket_timeout': 25,
        }
    else:
        return {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'http_headers': {**base_headers, 'User-Agent': random.choice(USER_AGENTS)},
            'ignoreerrors': True,
            'retries': 1,
            'socket_timeout': 20,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        }

def extract_video_info(url):
    """Extract video information with retry logic"""
    for attempt in range(1, Config.MAX_RETRY_ATTEMPTS + 1):
        try:
            ydl_opts = get_ydl_options(attempt)
            
            # Progressive delay between attempts
            if attempt > 1:
                delay = random.uniform(2, 4) * attempt
                time.sleep(delay)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                logger.info(f"Successfully extracted info for {url} on attempt {attempt}")
                return info, True
                
        except yt_dlp.DownloadError as e:
            error_msg = str(e)
            logger.warning(f"Attempt {attempt} failed for {url}: {error_msg}")
            
            if attempt == Config.MAX_RETRY_ATTEMPTS:
                return None, error_msg
                
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt} for {url}: {str(e)}")
            if attempt == Config.MAX_RETRY_ATTEMPTS:
                return None, f"Unexpected error: {str(e)}"
    
    return None, "Max retry attempts exceeded"

def categorize_formats(formats):
    """Categorize formats into multiple types with enhanced information"""
    
    progressive_formats = []
    adaptive_video_formats = []
    adaptive_audio_formats = []
    storyboard_formats = []
    
    seen_combinations = set()
    
    for f in formats:
        if not f.get('url'):
            continue
            
        # Skip problematic formats
        ext = f.get('ext', '')
        protocol = f.get('protocol', '')
        if any(x in ext or x in protocol for x in ['m3u8', 'mpd', 'dash', 'f4f']):
            continue
        
        filesize = f.get('filesize')
        filesize_display = format_file_size(filesize)
        
        # Storyboard formats (thumbnails)
        if f.get('format_note', '').startswith('storyboard'):
            storyboard_formats.append({
                "type": "storyboard",
                "format_note": f.get('format_note'),
                "width": f.get('width'),
                "height": f.get('height'),
                "columns": f.get('columns'),
                "rows": f.get('rows'),
                "duration": f.get('duration'),
                "download_url": f.get('url')
            })
            continue
            
        # Progressive format (video + audio together) - THE FIXED VERSION WITH AUDIO
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            height = f.get('height', 0)
            if height >= 144:  # Reasonable minimum
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
    
    # Sort and limit formats
    progressive_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
    adaptive_video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
    adaptive_audio_formats.sort(key=lambda x: x.get('bitrate', 0), reverse=True)
    
    return {
        "progressive": progressive_formats[:Config.MAX_FORMATS_PER_CATEGORY],
        "adaptive_video": adaptive_video_formats[:Config.MAX_FORMATS_PER_CATEGORY],
        "adaptive_audio": adaptive_audio_formats[:Config.MAX_FORMATS_PER_CATEGORY],
        "storyboards": storyboard_formats[:5]
    }

@app.route('/')
def home():
    return jsonify({
        "message": "Professional YouTube Video Links API",
        "version": "2.0.0",
        "status": "active",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "get_video_links": "POST /api/get_video_links",
            "health_check": "GET /api/health",
            "stats": "GET /api/stats"
        },
        "documentation": "Send POST request to /api/get_video_links with JSON: {'url': 'youtube_url'}"
    })

@app.route('/api/get_video_links', methods=['POST'])
def get_video_links():
    start_time = time.time()
    
    # Get client IP for rate limiting
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if isinstance(client_ip, str) and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    # Rate limiting check
    if is_rate_limited(client_ip):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        return jsonify({
            "error": "Rate limit exceeded",
            "message": f"Too many requests. Maximum {Config.RATE_LIMIT_REQUESTS} requests per {Config.RATE_LIMIT_WINDOW} seconds allowed.",
            "retry_after": Config.RATE_LIMIT_WINDOW
        }), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON data"}), 400
    
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "YouTube URL is required"}), 400

    # Validate and standardize YouTube URL
    clean_url, video_id = validate_youtube_url(url)
    if not clean_url:
        return jsonify({"error": "Invalid YouTube URL", "details": video_id}), 400

    # Check cache first
    cached_data = get_cached_data(clean_url)
    if cached_data:
        logger.info(f"Serving from cache for video: {video_id}")
        cached_data['cached'] = True
        cached_data['response_time'] = round((time.time() - start_time) * 1000, 2)
        return jsonify(cached_data)

    # Extract video information
    info, success = extract_video_info(clean_url)
    if not success:
        logger.error(f"Failed to extract info for {video_id}: {success}")
        return jsonify({
            "error": "Failed to extract video information",
            "message": str(success),
            "video_id": video_id,
            "suggestion": "This might be a temporary issue. Please try again in a few minutes."
        }), 500

    # Categorize formats
    formats = categorize_formats(info.get('formats', []))

    # Get best available thumbnail
    thumbnails = info.get('thumbnails', [])
    thumbnail_info = {}
    if thumbnails:
        # Sort by resolution and get the best
        thumbnails.sort(key=lambda x: x.get('width', 0) * x.get('height', 0), reverse=True)
        for thumb in thumbnails[:3]:  # Top 3 thumbnails
            quality = f"{thumb.get('width', 0)}x{thumb.get('height', 0)}"
            thumbnail_info[quality] = thumb.get('url')
    else:
        thumbnail_info['default'] = info.get('thumbnail')

    # Prepare response data
    response_data = {
        "video_info": {
            "title": info.get('title', 'Unknown Title'),
            "duration": info.get('duration'),
            "duration_display": info.get('duration_string'),
            "uploader": info.get('uploader', 'Unknown Uploader'),
            "uploader_id": info.get('uploader_id'),
            "uploader_url": info.get('uploader_url'),
            "channel_id": info.get('channel_id'),
            "view_count": info.get('view_count'),
            "like_count": info.get('like_count'),
            "comment_count": info.get('comment_count'),
            "description": info.get('description'),
            "upload_date": info.get('upload_date'),
            "publish_date": info.get('upload_date'),
            "video_id": video_id,
            "webpage_url": info.get('webpage_url'),
            "categories": info.get('categories', []),
            "tags": info.get('tags', [])[:15],
            "age_limit": info.get('age_limit', 0),
            "is_live": info.get('is_live', False),
            "was_live": info.get('was_live', False)
        },
        "thumbnails": thumbnail_info,
        "formats": formats,
        "format_summary": {
            "progressive_count": len(formats["progressive"]),
            "adaptive_video_count": len(formats["adaptive_video"]),
            "adaptive_audio_count": len(formats["adaptive_audio"]),
            "storyboard_count": len(formats["storyboards"]),
            "total_formats": len(formats["progressive"]) + len(formats["adaptive_video"]) + len(formats["adaptive_audio"])
        },
        "recommendations": {
            "best_video_with_audio": formats["progressive"][0] if formats["progressive"] else None,
            "best_video_quality": formats["adaptive_video"][0] if formats["adaptive_video"] else None,
            "best_audio_quality": formats["adaptive_audio"][0] if formats["adaptive_audio"] else None
        },
        "success": True,
        "video_id": video_id,
        "cached": False,
        "response_time": round((time.time() - start_time) * 1000, 2),
        "timestamp": datetime.now().isoformat()
    }

    # Cache the successful response
    set_cache_data(clean_url, response_data)
    
    logger.info(f"Successfully processed video {video_id} in {response_data['response_time']}ms")
    return jsonify(response_data)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Comprehensive health check endpoint"""
    now = time.time()
    
    # Calculate rate limiting stats
    active_ips = 0
    total_requests = 0
    for ip_times in request_times.values():
        active_requests = [t for t in ip_times if now - t < Config.RATE_LIMIT_WINDOW]
        if active_requests:
            active_ips += 1
            total_requests += len(active_requests)
    
    health_data = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "YouTube Video Links API",
        "version": "2.0.0",
        "system": {
            "cache_size": len(cache),
            "active_ips": active_ips,
            "total_recent_requests": total_requests,
            "rate_limit_config": {
                "requests_per_window": Config.RATE_LIMIT_REQUESTS,
                "window_seconds": Config.RATE_LIMIT_WINDOW
            }
        },
        "dependencies": {
            "yt_dlp": "available",
            "flask": "available"
        }
    }
    
    return jsonify(health_data)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """API usage statistics"""
    now = time.time()
    
    # Calculate recent activity
    recent_activity = {}
    for ip_hash, times in request_times.items():
        recent_times = [t for t in times if now - t < 3600]  # Last hour
        if recent_times:
            recent_activity[ip_hash[:8]] = len(recent_times)
    
    stats_data = {
        "cache": {
            "total_entries": len(cache),
            "max_duration_seconds": Config.CACHE_DURATION
        },
        "rate_limiting": {
            "total_tracked_ips": len(request_times),
            "recent_activity_last_hour": recent_activity
        },
        "current_time": datetime.now().isoformat(),
        "uptime": "unknown"  # Would need more sophisticated tracking
    }
    
    return jsonify(stats_data)

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "message": "Check the API documentation at the root endpoint",
        "documentation_url": "/"
    }), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "error": "Method not allowed",
        "message": "This endpoint does not support the requested HTTP method"
    }), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        "error": "Internal server error",
        "message": "An unexpected error occurred. Please try again later.",
        "support": "If the issue persists, please contact support."
    }), 500

# Background cleanup task
def cleanup_old_data():
    """Clean up old rate limiting and cache data"""
    now = time.time()
    global request_times, cache
    
    # Clean rate limiting data
    for ip_hash in list(request_times.keys()):
        request_times[ip_hash] = [t for t in request_times[ip_hash] if now - t < 3600]  # Keep 1 hour
        if not request_times[ip_hash]:
            del request_times[ip_hash]
    
    # Clean cache data
    for cache_key in list(cache.keys()):
        data, timestamp = cache[cache_key]
        if now - timestamp > Config.CACHE_DURATION:
            del cache[cache_key]

# Cleanup every 20 requests
request_count = 0

@app.before_request
def before_request():
    global request_count
    request_count += 1
    if request_count % 20 == 0:
        cleanup_old_data()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Starting YouTube Video Links API on port {port}")
    logger.info(f"Debug mode: {debug}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)