"""
Winy AI - Enterprise Strategy Swarm Application
A comprehensive Flask application for generating business strategies using AI.
Features: Firebase Authentication, Razorpay Payments, Groq AI Integration, 
SQLite Database, IP-based Rate Limiting, and YouTube Video Analysis.
"""

import os
import re
import json
import time
import hmac
import hashlib
import sqlite3
import logging
import requests
import razorpay
import uuid
from datetime import datetime, date, timedelta
from functools import wraps
from collections import defaultdict

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================

# Initialize Flask App
from flask import Flask, request, jsonify, render_template_string, session, g

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "winy-ai-secret-key-change-in-production")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['JSON_SORT_KEYS'] = False

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

# API Configuration
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

# Initialize Razorpay Client
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    try:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        logger.info("Razorpay client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Razorpay: {e}")
else:
    logger.warning("Razorpay credentials not found in environment variables.")

# In-memory IP tracking for abuse prevention (resets on server restart, supplemented by DB)
ip_usage_tracker = defaultdict(lambda: {'count': 0, 'date': None})

# ==============================================================================
# DATABASE SETUP & UTILITIES
# ==============================================================================

DATABASE_PATH = 'winy_ai.db'

def get_db_connection():
    """Create a new database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """Initialize the SQLite database with required tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table for tracking Pro status
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            is_pro INTEGER DEFAULT 0,
            pro_expiry DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Usage tracking table for daily limits
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            usage_date DATE NOT NULL,
            generations_count INTEGER DEFAULT 0,
            followups_count INTEGER DEFAULT 0,
            UNIQUE(firebase_uid, usage_date)
        )
    ''')
    
    # Strategies history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            prompt TEXT NOT NULL,
            industry TEXT,
            length TEXT,
            tone TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # YouTube analysis cache
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS youtube_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT NOT NULL,
            video_url TEXT NOT NULL,
            analysis_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

# Initialize DB on module load
init_db()

def get_today():
    """Get today's date in ISO format."""
    return date.today().isoformat()

def get_client_ip():
    """Extract the real client IP address from request headers."""
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    return request.remote_addr

def clean_text(text):
    """Remove markdown formatting from AI responses."""
    if not text:
        return ""
    text = text.replace('**', '').replace('*', '').replace('_', '')
    text = re.sub(r'#+\s*', '', text)
    return text.strip()

def require_auth(f):
    """Decorator to ensure user is authenticated via Firebase."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'firebase_uid' not in session:
            return jsonify({"error": "Authentication required. Please login."}), 401
        return f(*args, **kwargs)
    return decorated_function

def require_pro(f):
    """Decorator to ensure user has an active Pro subscription."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'firebase_uid' not in session:
            return jsonify({"error": "Authentication required."}), 401
        
        conn = get_db_connection()
        user = conn.execute(
            "SELECT is_pro, pro_expiry FROM users WHERE firebase_uid = ?", 
            (session['firebase_uid'],)
        ).fetchone()
        conn.close()
        
        if not user or not user['is_pro']:
            return jsonify({"error": "This feature requires a Pro subscription."}), 403
            
        if user['pro_expiry'] and datetime.strptime(user['pro_expiry'], '%Y-%m-%d') < datetime.now():
            # Pro expired
            conn = get_db_connection()
            conn.execute("UPDATE users SET is_pro = 0 WHERE firebase_uid = ?", (session['firebase_uid'],))
            conn.commit()
            conn.close()
            return jsonify({"error": "Your Pro subscription has expired."}), 403
            
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# AI & EXTERNAL SERVICES
# ==============================================================================

def call_groq_llm(system_prompt, user_prompt, temperature=0.7, model="llama-3.1-8b-instant"):
    """
    Call the Groq API to generate text.
    Includes retry logic and error handling.
    """
    if not GROQ_API_KEY:
        return "Error: GROQ_API_KEY is not configured on the server."
        
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = requests.post(
                GROQ_URL, 
                headers=GROQ_HEADERS, 
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": 4096
                }, 
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return clean_text(result['choices'][0]['message']['content'])
                else:
                    logger.error(f"Groq API returned no choices: {result}")
                    return "Error: AI service returned an empty response."
            elif response.status_code == 429:
                logger.warning("Groq API rate limit hit. Retrying...")
                time.sleep(2 ** attempt)
                continue
            else:
                logger.error(f"Groq API error {response.status_code}: {response.text}")
                return f"Error: AI service unavailable (Status {response.status_code})."
                
        except requests.exceptions.Timeout:
            logger.error("Groq API request timed out.")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return "Error: AI service request timed out."
        except Exception as e:
            logger.error(f"Unexpected error calling Groq API: {str(e)}")
            return f"Error: Connection to AI service failed."
            
    return "Error: AI service failed after multiple retries."

def parse_json_response(raw_text):
    """
    Robust JSON parser for AI responses.
    Handles markdown code blocks and minor formatting issues.
    """
    if not raw_text:
        return None
        
    # Remove markdown code blocks if present
    cleaned = raw_text.strip()
    if cleaned.startswith('```json'):
        cleaned = cleaned[7:]
    if cleaned.startswith('```'):
        cleaned = cleaned[3:]
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
        
    cleaned = cleaned.strip()
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error: {e}")
        logger.error(f"Raw text snippet: {cleaned[:200]}")
        
        # Attempt to fix common JSON issues (trailing commas)
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

def get_youtube_transcript(video_url):
    """
    Extract transcript from a YouTube video URL.
    Uses youtube_transcript_api.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        video_id = None
        if "youtube.com/watch?v=" in video_url:
            video_id = video_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
        if not video_id:
            return None, "Invalid YouTube URL format."
            
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([entry['text'] for entry in transcript_list])
        return full_text, None
        
    except Exception as e:
        logger.error(f"YouTube transcript error: {str(e)}")
        return None, f"Could not extract transcript: {str(e)}"

# ==============================================================================
# HTML/CSS/JS TEMPLATE
# ==============================================================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Winy AI | Enterprise Strategy Swarm</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>
    <style>
        /* ==========================================================================
           CSS VARIABLES & RESET
           ========================================================================== */
        :root {
            --bg-color: #ffffff;
            --text-primary: #000000;
            --text-secondary: #666666;
            --glass-bg: rgba(255, 255, 255, 0.7);
            --glass-border: rgba(0, 0, 0, 0.08);
            --accent-color: #000000;
            --accent-text: #ffffff;
            --success-color: #10b981;
            --error-color: #ef4444;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: var(--font-family);
            min-height: 100vh;
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            overflow-x: hidden;
        }

        /* Background Shapes for Glassmorphism */
        .bg-shape {
            position: fixed;
            border-radius: 50%;
            filter: blur(120px);
            z-index: 0;
            pointer-events: none;
        }
        .shape-1 { width: 600px; height: 600px; background: #f0f0f0; top: -150px; left: -150px; }
        .shape-2 { width: 500px; height: 500px; background: #e8e8e8; bottom: -100px; right: -100px; }

        /* ==========================================================================
           NAVIGATION
           ========================================================================== */
        nav {
            position: fixed;
            top: 24px;
            left: 50%;
            transform: translateX(-50%);
            width: 92%;
            max-width: 900px;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 1000;
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 100px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
            transition: all 0.4s ease;
        }

        nav.pro-nav {
            background: #000000;
            border-color: #333333;
        }

        .nav-left, .nav-right {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .logo {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .user-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: var(--accent-color);
            color: var(--accent-text);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 600;
        }

        nav.pro-nav .user-avatar {
            background: #ffffff;
            color: #000000;
        }

        /* Buttons */
        .btn {
            padding: 8px 16px;
            border-radius: 100px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.3s ease;
            font-family: var(--font-family);
        }

        .btn-primary {
            background: var(--accent-color);
            color: var(--accent-text);
        }

        .btn-secondary {
            background: rgba(0, 0, 0, 0.05);
            color: var(--text-primary);
            border: 1px solid var(--glass-border);
        }

        .btn:hover {
            transform: translateY(-1px);
            opacity: 0.9;
        }

        nav.pro-nav .btn-secondary {
            background: rgba(255, 255, 255, 0.1);
            color: #ffffff;
            border-color: rgba(255, 255, 255, 0.2);
        }

        nav.pro-nav .btn-primary {
            background: #ffffff;
            color: #000000;
        }

        .pro-badge {
            background: var(--success-color);
            color: #ffffff;
            padding: 4px 12px;
            border-radius: 100px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }

        /* ==========================================================================
           MAIN CONTAINER & HERO
           ========================================================================== */
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 140px 24px 60px;
            position: relative;
            z-index: 1;
        }

        .hero {
            text-align: center;
            margin-bottom: 60px;
        }

        .hero h1 {
            font-size: 56px;
            font-weight: 800;
            letter-spacing: -2px;
            line-height: 1.1;
            margin-bottom: 16px;
        }

        .hero p {
            font-size: 18px;
            color: var(--text-secondary);
            max-width: 600px;
            margin: 0 auto;
        }

        /* ==========================================================================
           GLASS CARD & INPUTS
           ========================================================================== */
        .glass-card {
            background: var(--glass-bg);
            backdrop-filter: blur(40px);
            -webkit-backdrop-filter: blur(40px);
            border: 1px solid var(--glass-border);
            border-radius: 32px;
            padding: 48px;
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.06);
            margin-bottom: 40px;
        }

        .main-input {
            width: 100%;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 24px;
            font-size: 16px;
            font-family: var(--font-family);
            resize: none;
            outline: none;
            min-height: 120px;
            margin-bottom: 24px;
            transition: all 0.3s ease;
            color: var(--text-primary);
        }

        .main-input:focus {
            border-color: var(--accent-color);
            background: rgba(0, 0, 0, 0.05);
        }

        .main-input::placeholder {
            color: #999999;
        }

        .main-input:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .options-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .option-card {
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 20px;
        }

        .option-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-secondary);
            margin-bottom: 8px;
            display: block;
            font-weight: 600;
        }

        .option-select {
            width: 100%;
            background: transparent;
            border: none;
            font-size: 14px;
            font-family: var(--font-family);
            color: var(--text-primary);
            outline: none;
            cursor: pointer;
        }

        .option-select:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-launch {
            width: 100%;
            background: var(--accent-color);
            color: var(--accent-text);
            border: none;
            border-radius: 16px;
            padding: 20px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            font-family: var(--font-family);
        }

        .btn-launch:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 15px 40px rgba(0, 0, 0, 0.2);
        }

        .btn-launch:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        /* ==========================================================================
           LOADER & FOOTER
           ========================================================================== */
        .loader {
            display: none;
            text-align: center;
            padding: 80px 20px;
        }

        .loader.active {
            display: block;
        }

        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid rgba(0, 0, 0, 0.1);
            border-top-color: var(--accent-color);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 24px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .footer-stats {
            text-align: center;
            padding: 24px;
            border-top: 1px solid var(--glass-border);
            font-size: 13px;
            color: var(--text-secondary);
        }

        .footer-stats strong {
            color: var(--text-primary);
        }

        /* ==========================================================================
           RESULTS OVERLAY
           ========================================================================== */
        .overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 2000;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .overlay.active {
            display: flex;
        }

        .overlay-backdrop {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }

        .overlay-content {
            position: relative;
            background: #ffffff;
            border-radius: 32px;
            width: 100%;
            max-width: 800px;
            max-height: 90vh;
            overflow-y: auto;
            z-index: 10;
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.3);
        }

        .overlay-header {
            position: sticky;
            top: 0;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            padding: 24px 32px;
            border-bottom: 1px solid var(--glass-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 10;
            border-radius: 32px 32px 0 0;
        }

        .overlay-header h2 {
            font-size: 20px;
            font-weight: 700;
        }

        .close-btn {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: none;
            background: var(--accent-color);
            color: var(--accent-text);
            cursor: pointer;
            font-size: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.2s;
        }

        .close-btn:hover {
            transform: scale(1.1);
        }

        .overlay-body {
            padding: 32px;
        }

        .result-summary {
            background: rgba(0, 0, 0, 0.03);
            border-left: 4px solid var(--accent-color);
            padding: 24px;
            border-radius: 12px;
            margin-bottom: 32px;
            font-size: 16px;
            line-height: 1.7;
        }

        .sections-carousel {
            display: flex;
            gap: 20px;
            overflow-x: auto;
            scroll-snap-type: x mandatory;
            padding: 20px 0;
            scrollbar-width: none;
            margin-bottom: 32px;
        }

        .sections-carousel::-webkit-scrollbar {
            display: none;
        }

        .section-card {
            flex: 0 0 90%;
            max-width: 350px;
            background: rgba(0, 0, 0, 0.02);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 28px;
            scroll-snap-align: center;
        }

        .section-card h3 {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-secondary);
            margin-bottom: 16px;
            font-weight: 700;
        }

        .section-card p {
            font-size: 14px;
            line-height: 1.7;
            color: var(--text-primary);
        }

        .costs-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 16px;
            margin-top: 24px;
        }

        .cost-card {
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }

        .cost-card.total {
            background: var(--accent-color);
            color: var(--accent-text);
        }

        .cost-label {
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            margin-bottom: 8px;
        }

        .cost-card.total .cost-label {
            color: rgba(255, 255, 255, 0.7);
        }

        .cost-value {
            font-size: 24px;
            font-weight: 700;
        }

        /* Follow-up Section inside Overlay */
        .followup-section {
            margin-top: 32px;
            padding-top: 32px;
            border-top: 1px solid var(--glass-border);
        }

        .followup-input {
            width: 100%;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 100px;
            padding: 16px 24px;
            font-size: 14px;
            margin-bottom: 12px;
            outline: none;
            font-family: var(--font-family);
        }

        .followup-input:focus {
            border-color: var(--accent-color);
        }

        .qa-list {
            margin-top: 24px;
        }

        .qa-item {
            margin-bottom: 20px;
        }

        .qa-question {
            background: rgba(0, 0, 0, 0.03);
            border-left: 3px solid var(--accent-color);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 12px;
            font-weight: 600;
            font-size: 14px;
        }

        .qa-answer {
            background: rgba(0, 0, 0, 0.02);
            padding: 16px;
            border-radius: 8px;
            font-size: 14px;
            line-height: 1.7;
        }

        /* ==========================================================================
           MODALS (Login & Alerts)
           ========================================================================== */
        .modal-backdrop {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            z-index: 3000;
            align-items: center;
            justify-content: center;
        }

        .modal-backdrop.active {
            display: flex;
        }

        .modal-box {
            background: #ffffff;
            border: 1px solid var(--glass-border);
            border-radius: 32px;
            padding: 40px;
            max-width: 450px;
            width: 90%;
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.15);
        }

        .modal-box h2 {
            text-align: center;
            font-size: 28px;
            margin-bottom: 8px;
        }

        .modal-box > p {
            text-align: center;
            color: var(--text-secondary);
            margin-bottom: 32px;
            font-size: 14px;
        }

        .tabs {
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
            background: rgba(0, 0, 0, 0.05);
            padding: 4px;
            border-radius: 100px;
        }

        .tab {
            flex: 1;
            padding: 12px;
            border: none;
            background: transparent;
            border-radius: 100px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            font-family: var(--font-family);
            color: var(--text-secondary);
        }

        .tab.active {
            background: var(--accent-color);
            color: var(--accent-text);
        }

        .input-field {
            width: 100%;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 16px;
            font-size: 14px;
            margin-bottom: 16px;
            outline: none;
            font-family: var(--font-family);
        }

        .input-field:focus {
            border-color: var(--accent-color);
        }

        .btn-full {
            width: 100%;
            background: var(--accent-color);
            color: var(--accent-text);
            border: none;
            border-radius: 100px;
            padding: 16px;
            font-weight: 600;
            cursor: pointer;
            font-size: 15px;
            font-family: var(--font-family);
            transition: opacity 0.2s;
        }

        .btn-full:hover {
            opacity: 0.9;
        }

        .divider {
            display: flex;
            align-items: center;
            margin: 24px 0;
            color: var(--text-secondary);
            font-size: 12px;
        }

        .divider::before, .divider::after {
            content: '';
            flex: 1;
            border-bottom: 1px solid var(--glass-border);
        }

        .divider::before { margin-right: 12px; }
        .divider::after { margin-left: 12px; }

        .google-btn {
            width: 100%;
            background: #ffffff;
            border: 1px solid var(--glass-border);
            padding: 14px;
            border-radius: 100px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            font-family: var(--font-family);
            transition: background 0.2s;
        }

        .google-btn:hover {
            background: rgba(0, 0, 0, 0.02);
        }

        /* Highlight Boxes for Keywords */
        .hl {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 0.95em;
        }
        .hl-market { background: #dbeafe; color: #1e40af; }
        .hl-revenue { background: #dcfce7; color: #166534; }
        .hl-strategy { background: #f3e8ff; color: #6b21a8; }
        .hl-cost { background: #fee2e2; color: #991b1b; }

        /* Responsive Design */
        @media (max-width: 768px) {
            .hero h1 { font-size: 36px; }
            .glass-card { padding: 24px; }
            .options-grid { grid-template-columns: 1fr; }
            nav { width: 95%; padding: 12px 16px; }
            .overlay-content { max-height: 95vh; border-radius: 24px; }
            .overlay-header { border-radius: 24px 24px 0 0; padding: 16px 20px; }
            .overlay-body { padding: 20px; }
            .section-card { flex: 0 0 100%; }
        }
    </style>
</head>
<body>
    <!-- Background Shapes -->
    <div class="bg-shape shape-1"></div>
    <div class="bg-shape shape-2"></div>

    <!-- Navigation -->
    <nav id="mainNav">
        <div class="nav-left" id="navLeft">
            <div class="logo">Winy AI</div>
        </div>
        <div class="nav-right" id="navRight">
            <button class="btn btn-secondary" onclick="showLoginModal()">Login / Sign Up</button>
        </div>
    </nav>

    <!-- Main Content -->
    <div class="container">
        <div class="hero">
            <h1>Deploy the Swarm.</h1>
            <p>Elite business strategy generation with AI-powered insights, competitor analysis, and financial modeling.</p>
        </div>

        <div id="inputWrapper">
            <div class="glass-card">
                <textarea class="main-input" id="mainPrompt" placeholder="Describe your business idea, challenge, or market in detail..." disabled></textarea>
                <div class="options-grid">
                    <div class="option-card">
                        <span class="option-label">Industry</span>
                        <select class="option-select" id="optIndustry" disabled>
                            <option value="General">General</option>
                            <option value="Technology">Technology / SaaS</option>
                            <option value="E-commerce">E-commerce / Retail</option>
                            <option value="Food & Beverage">Food & Beverage</option>
                            <option value="Real Estate">Real Estate</option>
                            <option value="Healthcare">Healthcare</option>
                            <option value="Finance">Finance / Fintech</option>
                        </select>
                    </div>
                    <div class="option-card">
                        <span class="option-label">Depth</span>
                        <select class="option-select" id="optLength" disabled>
                            <option value="short">Brief (Quick Scan)</option>
                            <option value="medium" selected>Standard (Detailed)</option>
                            <option value="long">Deep Dive (Pro Only)</option>
                        </select>
                    </div>
                    <div class="option-card">
                        <span class="option-label">Tone</span>
                        <select class="option-select" id="optTone" disabled>
                            <option value="Professional">Professional</option>
                            <option value="Direct">Direct & Actionable</option>
                            <option value="Analytical">Analytical</option>
                            <option value="Persuasive">Persuasive (Pitch Deck)</option>
                        </select>
                    </div>
                </div>
                <button class="btn-launch" id="btnLaunch" onclick="runSwarm()" disabled>
                    Login to Initialize Swarm
                </button>
            </div>
        </div>

        <div class="loader" id="loader">
            <div class="spinner"></div>
            <p style="color: var(--text-secondary); font-size: 14px;">AI Swarm is analyzing your business...</p>
        </div>

        <div class="footer-stats" id="footerStats">
            Please login to access features
        </div>
    </div>

    <!-- Results Overlay -->
    <div class="overlay" id="resultsOverlay">
        <div class="overlay-backdrop" onclick="closeResultsOverlay()"></div>
        <div class="overlay-content">
            <div class="overlay-header">
                <h2>Strategic Output</h2>
                <button class="close-btn" onclick="closeResultsOverlay()">✕</button>
            </div>
            <div class="overlay-body">
                <div class="result-summary" id="resultSummary"></div>
                <div class="sections-carousel" id="sectionsCarousel"></div>
                <div class="costs-grid" id="costsGrid"></div>
                
                <div class="followup-section">
                    <span class="option-label">Follow-up Question</span>
                    <input type="text" class="followup-input" id="followupInput" placeholder="Ask the swarm anything about this strategy...">
                    <button class="btn-launch" id="followupBtn" onclick="askFollowup()" style="padding: 12px;">
                        Ask Swarm
                    </button>
                    <div class="qa-list" id="qaList"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Login Modal -->
    <div class="modal-backdrop" id="loginModal">
        <div class="modal-box">
            <h2>Welcome to Winy AI</h2>
            <p>Login to deploy the swarm</p>
            <div class="tabs">
                <button class="tab active" onclick="switchTab('login')">Login</button>
                <button class="tab" onclick="switchTab('signup')">Sign Up</button>
            </div>
            <div id="loginForm">
                <input type="email" class="input-field" id="loginEmail" placeholder="Email">
                <input type="password" class="input-field" id="loginPassword" placeholder="Password">
                <button class="btn-full" onclick="loginWithEmail()">Login</button>
            </div>
            <div id="signupForm" style="display:none;">
                <input type="email" class="input-field" id="signupEmail" placeholder="Email">
                <input type="password" class="input-field" id="signupPassword" placeholder="Password (min 6 characters)">
                <button class="btn-full" onclick="signupWithEmail()">Sign Up</button>
            </div>
            <div class="divider">or continue with</div>
            <button class="google-btn" onclick="loginWithGoogle()">
                <svg width="20" height="20" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                Google
            </button>
        </div>
    </div>

    <!-- Alert Modal -->
    <div class="modal-backdrop" id="alertModal">
        <div class="modal-box">
            <h2 id="alertTitle">Title</h2>
            <p id="alertMessage" style="margin: 20px 0;">Message</p>
            <button class="btn-full" onclick="closeAlert()">OK</button>
        </div>
    </div>

    <script>
        // ======================================================================
        // FIREBASE CONFIGURATION
        // ======================================================================
        const firebaseConfig = {
            apiKey: "AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU",
            authDomain: "winy-3984d.firebaseapp.com",
            projectId: "winy-3984d",
            storageBucket: "winy-3984d.firebasestorage.app",
            messagingSenderId: "126237613814",
            appId: "1:126237613814:web:e3cb88222d920545a416d7"
        };
        
        firebase.initializeApp(firebaseConfig);
        const auth = firebase.auth();
        
        // ======================================================================
        // STATE VARIABLES
        // ======================================================================
        var isPro = {{ session.get('is_pro', False) | tojson }};
        var generationsUsed = {{ session.get('generations_count', 0) | tojson }};
        var followupsUsed = {{ session.get('followups_count', 0) | tojson }};
        var rzpKeyId = {{ razorpay_key_id | tojson }};
        var isLoggedIn = false;
        var currentUser = null;
        var currentContext = '';
        var currentIndustry = '';

        // ======================================================================
        // AUTHENTICATION HANDLERS
        // ======================================================================
        auth.onAuthStateChanged(function(user) {
            if (user) {
                isLoggedIn = true;
                currentUser = user;
                enableFeatures();
                updateUserUI();
            } else {
                isLoggedIn = false;
                currentUser = null;
                disableFeatures();
                updateUserUI();
            }
        });

        function enableFeatures() {
            ['mainPrompt', 'optIndustry', 'optLength', 'optTone'].forEach(id => {
                document.getElementById(id).disabled = false;
            });
            document.getElementById('btnLaunch').disabled = false;
            document.getElementById('btnLaunch').innerHTML = 'Initialize Swarm';
        }

        function disableFeatures() {
            ['mainPrompt', 'optIndustry', 'optLength', 'optTone'].forEach(id => {
                document.getElementById(id).disabled = true;
            });
            document.getElementById('btnLaunch').disabled = true;
            document.getElementById('btnLaunch').innerHTML = 'Login to Initialize Swarm';
        }

        function updateUserUI() {
            var navLeft = document.getElementById('navLeft');
            var navRight = document.getElementById('navRight');
            var footer = document.getElementById('footerStats');
            var mainNav = document.getElementById('mainNav');
            
            if (isLoggedIn) {
                var userInitial = currentUser.email ? currentUser.email.charAt(0).toUpperCase() : 'U';
                navLeft.innerHTML = '<div class="user-avatar">' + userInitial + '</div>';
                
                var rightHtml = '<button class="btn btn-secondary" onclick="logout()">Logout</button>';
                if (isPro) {
                    rightHtml += '<span class="pro-badge">PRO</span>';
                } else {
                    rightHtml += '<button class="btn btn-primary" onclick="initiatePayment()">Upgrade to Pro</button>';
                }
                navRight.innerHTML = rightHtml;
                
                if (isPro) {
                    mainNav.classList.add('pro-nav');
                    footer.innerHTML = '<strong>Pro User:</strong> Unlimited access to all features';
                } else {
                    mainNav.classList.remove('pro-nav');
                    var remaining = Math.max(0, 3 - generationsUsed);
                    footer.innerHTML = '<strong>Free Tier:</strong> ' + remaining + ' generations remaining today. Resets at midnight.';
                }
            } else {
                mainNav.classList.remove('pro-nav');
                navLeft.innerHTML = '<div class="logo">Winy AI</div>';
                navRight.innerHTML = '<button class="btn btn-secondary" onclick="showLoginModal()">Login / Sign Up</button>';
                footer.innerHTML = 'Please login to access features';
            }
        }

        function showLoginModal() { document.getElementById('loginModal').classList.add('active'); }
        function hideLoginModal() { document.getElementById('loginModal').classList.remove('active'); }
        
        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            if (tab === 'login') {
                document.querySelector('.tab:first-child').classList.add('active');
                document.getElementById('loginForm').style.display = 'block';
                document.getElementById('signupForm').style.display = 'none';
            } else {
                document.querySelector('.tab:last-child').classList.add('active');
                document.getElementById('loginForm').style.display = 'none';
                document.getElementById('signupForm').style.display = 'block';
            }
        }

        function loginWithEmail() {
            var email = document.getElementById('loginEmail').value.trim();
            var password = document.getElementById('loginPassword').value;
            if (!email || !password) return showAlert('Error', 'Please enter email and password');
            auth.signInWithEmailAndPassword(email, password)
                .then(() => hideLoginModal())
                .catch(err => showAlert('Error', err.message));
        }

        function signupWithEmail() {
            var email = document.getElementById('signupEmail').value.trim();
            var password = document.getElementById('signupPassword').value;
            if (!email || !password) return showAlert('Error', 'Please enter email and password');
            if (password.length < 6) return showAlert('Error', 'Password must be at least 6 characters');
            auth.createUserWithEmailAndPassword(email, password)
                .then(() => hideLoginModal())
                .catch(err => showAlert('Error', err.message));
        }

        function loginWithGoogle() {
            var provider = new firebase.auth.GoogleAuthProvider();
            auth.signInWithPopup(provider)
                .then(() => hideLoginModal())
                .catch(err => showAlert('Error', err.message));
        }

        function logout() {
            auth.signOut().then(() => {
                isPro = false;
                generationsUsed = 0;
                followupsUsed = 0;
                closeResultsOverlay();
                updateUserUI();
            });
        }

        function showAlert(title, message) {
            document.getElementById('alertTitle').textContent = title;
            document.getElementById('alertMessage').textContent = message;
            document.getElementById('alertModal').classList.add('active');
        }

        function closeAlert() {
            document.getElementById('alertModal').classList.remove('active');
        }

        // ======================================================================
        // UI RENDERING & HIGHLIGHTING
        // ======================================================================
        function highlightText(text) {
            if (!text) return '';
            var colors = {
                'market': 'hl-market',
                'revenue': 'hl-revenue',
                'growth': 'hl-revenue',
                'strategy': 'hl-strategy',
                'cost': 'hl-cost',
                'budget': 'hl-cost'
            };
            var html = text;
            for (var word in colors) {
                var regex = new RegExp('\\\\b' + word + '\\\\b', 'gi');
                html = html.replace(regex, '<span class="hl ' + colors[word] + '">' + word + '</span>');
            }
            return html;
        }

        function renderResults(data) {
            document.getElementById('resultSummary').innerHTML = '<p>' + highlightText(data.summary) + '</p>';
            
            var sections = [
                {id: 'market', title: 'Market Analysis'},
                {id: 'strategy', title: 'Operational Strategy'},
                {id: 'financials', title: 'Financial Projections'},
                {id: 'gtm', title: 'Go-to-Market Plan'}
            ];
            
            var html = '';
            sections.forEach(s => {
                html += '<div class="section-card"><h3>' + s.title + '</h3><p>' + highlightText(data[s.id] || 'No data available') + '</p></div>';
            });
            document.getElementById('sectionsCarousel').innerHTML = html;
            
            var costs = data.costs || {};
            var costHtml = '';
            for (var key in costs) {
                if (key !== 'total') {
                    costHtml += '<div class="cost-card"><div class="cost-label">' + key + '</div><div class="cost-value">$' + Number(costs[key]).toLocaleString() + '</div></div>';
                }
            }
            costHtml += '<div class="cost-card total"><div class="cost-label">Total Capital</div><div class="cost-value">$' + Number(costs.total || 0).toLocaleString() + '</div></div>';
            document.getElementById('costsGrid').innerHTML = costHtml;
        }

        // ======================================================================
        // CORE FUNCTIONALITY (Swarm, Follow-up, Payment)
        // ======================================================================
        function runSwarm() {
            if (!isLoggedIn) { showLoginModal(); return; }
            
            var prompt = document.getElementById('mainPrompt').value.trim();
            if (!prompt) return showAlert('Error', 'Please enter a business idea');
            
            var length = document.getElementById('optLength').value;
            if (length === 'long' && !isPro) return showAlert('Pro Feature', 'Deep Dive is available only for Pro users');
            if (!isPro && generationsUsed >= 3) return showAlert('Limit Reached', 'You have used all 3 free generations for today. Resets at midnight.');
            
            var industry = document.getElementById('optIndustry').value;
            var tone = document.getElementById('optTone').value;
            
            currentContext = prompt;
            currentIndustry = industry;
            
            document.getElementById('inputWrapper').style.display = 'none';
            document.getElementById('loader').classList.add('active');
            document.getElementById('qaList').innerHTML = '';
            
            fetch('/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({prompt: prompt, industry: industry, length: length, tone: tone})
            })
            .then(res => res.json())
            .then(data => {
                document.getElementById('loader').classList.remove('active');
                if (data.error) return showAlert('Error', data.error);
                
                renderResults(data);
                document.getElementById('resultsOverlay').classList.add('active');
                
                if (!isPro) {
                    generationsUsed++;
                    updateUserUI();
                }
            })
            .catch(err => {
                document.getElementById('loader').classList.remove('active');
                document.getElementById('inputWrapper').style.display = 'block';
                showAlert('Error', 'Failed to generate strategy: ' + err.message);
            });
        }

        function askFollowup() {
            if (!isLoggedIn) { showLoginModal(); return; }
            
            var q = document.getElementById('followupInput').value.trim();
            if (!q) return;
            
            if (!isPro && followupsUsed >= 1) return showAlert('Limit', 'Free users get 1 follow-up per day');
            
            var btn = document.getElementById('followupBtn');
            btn.innerHTML = 'Thinking...';
            btn.disabled = true;
            
            var qaList = document.getElementById('qaList');
            qaList.innerHTML += '<div class="qa-item"><div class="qa-question">Q: ' + q + '</div><div class="qa-answer" id="tempAnswer">Thinking...</div></div>';
            
            fetch('/followup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({question: q, context: currentContext, industry: currentIndustry})
            })
            .then(res => res.json())
            .then(data => {
                document.getElementById('tempAnswer').innerHTML = highlightText(data.answer);
                document.getElementById('tempAnswer').id = '';
                document.getElementById('followupInput').value = '';
                btn.innerHTML = 'Ask Swarm';
                btn.disabled = false;
                if (!isPro) followupsUsed++;
            })
            .catch(err => {
                document.getElementById('tempAnswer').innerHTML = 'Error: ' + err.message;
                btn.innerHTML = 'Ask Swarm';
                btn.disabled = false;
            });
        }

        function initiatePayment() {
            if (!isLoggedIn) { showLoginModal(); return; }
            if (!rzpKeyId) return showAlert('Error', 'Payment system not configured');
            
            fetch('/api/create-order', {method: 'POST'})
            .then(res => res.json())
            .then(order => {
                var options = {
                    key: rzpKeyId,
                    amount: order.amount,
                    currency: order.currency,
                    name: 'Winy AI',
                    description: 'Pro Subscription - Monthly',
                    order_id: order.order_id,
                    handler: function(response) {
                        fetch('/api/verify-payment', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(response)
                        })
                        .then(res => res.json())
                        .then(data => {
                            if (data.status === 'success') {
                                isPro = true;
                                generationsUsed = 0;
                                followupsUsed = 0;
                                updateUserUI();
                                showAlert('Welcome to Pro!', 'Payment successful! You now have unlimited access.');
                            } else {
                                showAlert('Payment Failed', 'Verification failed. Contact support with ID: ' + response.razorpay_payment_id);
                            }
                        });
                    },
                    prefill: {
                        name: currentUser ? currentUser.displayName || '' : '',
                        email: currentUser ? currentUser.email : '',
                        contact: ''
                    },
                    theme: {color: '#000000'}
                };
                new Razorpay(options).open();
            })
            .catch(err => showAlert('Error', 'Failed to start payment: ' + err.message));
        }

        function closeResultsOverlay() {
            document.getElementById('resultsOverlay').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';
        }

        // Initialize UI on load
        updateUserUI();
    </script>
</body>
</html>
'''

# ==============================================================================
# FLASK ROUTES
# ==============================================================================

@app.route('/')
def home():
    """Render the main application page."""
    today = get_today()
    
    # Initialize session variables if not present
    if 'is_pro' not in session:
        session['is_pro'] = False
    if 'generations_count' not in session:
        session['generations_count'] = 0
    if 'followups_count' not in session:
        session['followups_count'] = 0
        
    # Sync session with database if user is logged in
    if 'firebase_uid' in session:
        conn = get_db_connection()
        user = conn.execute(
            "SELECT is_pro FROM users WHERE firebase_uid = ?", 
            (session['firebase_uid'],)
        ).fetchone()
        if user:
            session['is_pro'] = bool(user['is_pro'])
        conn.close()
        
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/generate', methods=['POST'])
@require_auth
def generate():
    """Generate a business strategy using Groq AI."""
    client_ip = get_client_ip()
    firebase_uid = session['firebase_uid']
    today = get_today()
    
    # IP-based abuse prevention
    if client_ip not in ip_usage_tracker:
        ip_usage_tracker[client_ip] = {'count': 0, 'date': today}
    if ip_usage_tracker[client_ip]['date'] != today:
        ip_usage_tracker[client_ip] = {'count': 0, 'date': today}
        
    # Check limits for non-Pro users
    if not session.get('is_pro'):
        if session.get('generations_count', 0) >= 3 or ip_usage_tracker[client_ip]['count'] >= 3:
            return jsonify({"error": "Daily limit reached (3 generations). Resets at midnight."}), 403
            
    data = request.json
    prompt = data.get('prompt', '')
    industry = data.get('industry', 'General')
    length = data.get('length', 'medium')
    tone = data.get('tone', 'Professional')
    
    if not prompt or len(prompt) < 10:
        return jsonify({"error": "Please provide a detailed business idea (at least 10 characters)."}), 400
        
    if length == 'long' and not session.get('is_pro'):
        return jsonify({"error": "Deep Dive is a Pro-only feature."}), 403
        
    # Word limits based on depth
    word_map = {'short': '150 words', 'medium': '300 words', 'long': '500 words'}
    limit = word_map.get(length, '300 words')
    
    # Comprehensive AI Prompt forcing JSON output
    system_prompt = f"""You are an expert business consultant with 20+ years of experience. 
    Analyze this business idea comprehensively and return ONLY valid JSON.
    
    Business Idea: "{prompt}"
    Industry: {industry}
    Tone: {tone}
    
    Return a JSON object with these exact keys:
    {{
      "summary": "2-3 sentences executive summary",
      "market": "{limit} covering: market size, growth rate, target segments, trends, opportunities, threats",
      "strategy": "{limit} covering: operational plan, key milestones, team structure, technology stack, timeline",
      "financials": "{limit} covering: revenue model, pricing strategy, CAC, LTV, break-even, 3-year projections with numbers",
      "gtm": "{limit} covering: marketing channels, launch strategy, customer acquisition tactics, partnerships",
      "costs": {{
        "Product Dev": 5000,
        "Marketing": 3000,
        "Operations": 3000,
        "Legal": 1500,
        "Contingency": 1500,
        "total": 14000
      }}
    }}
    
    CRITICAL: Return ONLY the JSON object. No markdown, no text outside the JSON."""

    try:
        raw_response = call_groq_llm(system_prompt, prompt, temperature=0.7)
        logger.info(f"Raw AI response length: {len(raw_response)}")
        
        parsed_data = parse_json_response(raw_response)
        
        if not parsed_data:
            logger.error("Failed to parse JSON from AI response.")
            return jsonify({"error": "AI formatting error. Please try again."}), 500
            
        # Ensure all required keys exist with fallbacks
        sections = {
            'summary': parsed_data.get('summary', 'Summary not available.'),
            'market': parsed_data.get('market', 'Market data not available.'),
            'strategy': parsed_data.get('strategy', 'Strategy data not available.'),
            'financials': parsed_data.get('financials', 'Financials data not available.'),
            'gtm': parsed_data.get('gtm', 'GTM data not available.'),
            'costs': parsed_data.get('costs', {'Product Dev': 5000, 'Marketing': 3000, 'Operations': 3000, 'Legal': 1500, 'Contingency': 1500, 'total': 14000})
        }
        
        # Save strategy to database
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO strategies (firebase_uid, prompt, industry, length, tone, result_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (firebase_uid, prompt, industry, length, tone, json.dumps(sections)))
        conn.commit()
        conn.close()
        
        # Increment usage counters
        if not session.get('is_pro'):
            session['generations_count'] = session.get('generations_count', 0) + 1
            ip_usage_tracker[client_ip]['count'] += 1
            
            # Update database usage
            conn = get_db_connection()
            conn.execute('''
                INSERT INTO daily_usage (firebase_uid, ip_address, usage_date, generations_count, followups_count)
                VALUES (?, ?, ?, 1, 0)
                ON CONFLICT(firebase_uid, usage_date) 
                DO UPDATE SET generations_count = daily_usage.generations_count + 1
            ''', (firebase_uid, client_ip, today))
            conn.commit()
            conn.close()
            
        return jsonify(sections)
        
    except Exception as e:
        logger.error(f"Generation error: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route('/followup', methods=['POST'])
@require_auth
def followup():
    """Handle follow-up questions about a generated strategy."""
    firebase_uid = session['firebase_uid']
    today = get_today()
    
    # Check limits
    if not session.get('is_pro'):
        if session.get('followups_count', 0) >= 1:
            return jsonify({"error": "Follow-up limit reached (1 per day). Resets at midnight."}), 403
            
    data = request.json
    question = data.get('question', '')
    context = data.get('context', '')
    industry = data.get('industry', 'General')
    
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
        
    system_prompt = f"""You are a business consultant. 
    Context: {industry} business idea: '{context}'.
    Answer this question concisely in 100-150 words: {question}"""
    
    try:
        answer = call_groq_llm(system_prompt, question, temperature=0.5)
        
        if not session.get('is_pro'):
            session['followups_count'] = session.get('followups_count', 0) + 1
            
            conn = get_db_connection()
            conn.execute('''
                INSERT INTO daily_usage (firebase_uid, ip_address, usage_date, generations_count, followups_count)
                VALUES (?, ?, ?, 0, 1)
                ON CONFLICT(firebase_uid, usage_date) 
                DO UPDATE SET followups_count = daily_usage.followups_count + 1
            ''', (firebase_uid, get_client_ip(), today))
            conn.commit()
            conn.close()
            
        return jsonify({"answer": answer})
    except Exception as e:
        logger.error(f"Followup error: {str(e)}")
        return jsonify({"error": "Failed to get answer."}), 500

@app.route('/api/create-order', methods=['POST'])
@require_auth
def create_order():
    """Create a Razorpay order for Pro subscription."""
    if not razorpay_client:
        return jsonify({"error": "Payment system not configured."}), 500
        
    try:
        order = razorpay_client.order.create({
            "amount": 49900,  # ₹499 in paise
            "currency": "INR",
            "receipt": f"rcpt_{uuid.uuid4().hex[:16]}",
            "payment_capture": 1
        })
        return jsonify(order)
    except Exception as e:
        logger.error(f"Order creation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
@require_auth
def verify_payment():
    """Verify Razorpay payment signature and activate Pro."""
    data = request.json
    order_id = data.get('razorpay_order_id', '')
    payment_id = data.get('razorpay_payment_id', '')
    signature = data.get('razorpay_signature', '')
    
    if not all([order_id, payment_id, signature]):
        return jsonify({"status": "failure", "message": "Missing payment data."}), 400
        
    try:
        # Verify HMAC signature
        message = f"{order_id}|{payment_id}"
        expected_signature = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if expected_signature != signature:
            logger.warning("Payment signature mismatch.")
            return jsonify({"status": "failure", "message": "Signature mismatch."}), 400
            
        # Activate Pro status
        firebase_uid = session['firebase_uid']
        pro_expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO users (firebase_uid, email, is_pro, pro_expiry, last_login)
            VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(firebase_uid) 
            DO UPDATE SET is_pro = 1, pro_expiry = ?, last_login = CURRENT_TIMESTAMP
        ''', (firebase_uid, currentUser.email if currentUser else '', pro_expiry, pro_expiry))
        conn.commit()
        conn.close()
        
        session['is_pro'] = True
        session['generations_count'] = 0
        session['followups_count'] = 0
        
        logger.info(f"User {firebase_uid} upgraded to Pro.")
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"Payment verification error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

if __name__ == '__main__':
    logger.info("Starting Winy AI Server on port 5000...")
    # In production, use gunicorn: gunicorn -w 4 -b 0.0.0.0:5000 winy_ai:app
    app.run(host='0.0.0.0', port=5000, debug=False)
