from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
import requests
import re
import os
import json
import razorpay
import hmac
import hashlib
import sqlite3
import logging
from datetime import datetime, date, timedelta
from functools import wraps
import uuid
import bcrypt
import jwt
from collections import defaultdict
import time
import threading
from youtube_transcript_api import YouTubeTranscriptApi
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import google.generativeai as genai

# Initialize Flask App
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "winy-ai-secret-key-2024-change-this-in-production")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
JWT_SECRET = os.environ.get("JWT_SECRET", "jwt-secret-key-change-in-production")

# API Configuration
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

# Initialize Razorpay
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
else:
    razorpay_client = None
    logger.warning("Razorpay credentials not configured")

# Initialize Gemini for YouTube analysis
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("Gemini API key not configured - YouTube features disabled")

# Rate Limiter
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)

# Database Setup
def init_db():
    """Initialize SQLite database with all tables"""
    conn = sqlite3.connect('winy_ai.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            is_pro INTEGER DEFAULT 0,
            pro_expiry DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT
        )
    ''')
    
    # Usage tracking table
    c.execute('''
        CREATE TABLE IF NOT EXISTS usage_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip_address TEXT,
            usage_date DATE,
            generations_count INTEGER DEFAULT 0,
            followups_count INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Strategies table
    c.execute('''
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            prompt TEXT NOT NULL,
            industry TEXT,
            length TEXT,
            tone TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # YouTube analysis table
    c.execute('''
        CREATE TABLE IF NOT EXISTS youtube_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            video_url TEXT NOT NULL,
            transcript TEXT,
            analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Payment logs table
    c.execute('''
        CREATE TABLE IF NOT EXISTS payment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_id TEXT,
            payment_id TEXT,
            amount INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Competitor analysis cache
    c.execute('''
        CREATE TABLE IF NOT EXISTS competitor_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            industry TEXT,
            competitor_data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

# Initialize DB on startup
init_db()

# Helper Functions
def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect('winy_ai.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_client_ip():
    """Get client IP address"""
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def get_today():
    """Get today's date"""
    return date.today().isoformat()

def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

def check_daily_limit(user_id, limit_type='generations'):
    """Check if user has reached daily limit"""
    conn = get_db_connection()
    today = get_today()
    
    # Check user limit
    user = conn.execute('SELECT is_pro, pro_expiry FROM users WHERE id = ?', (user_id,)).fetchone()
    if user and user['is_pro'] and user['pro_expiry'] and datetime.strptime(user['pro_expiry'], '%Y-%m-%d') > datetime.now():
        conn.close()
        return False, 0  # Pro users have unlimited
    
    # Check usage
    usage = conn.execute('''
        SELECT generations_count, followups_count FROM usage_tracking 
        WHERE user_id = ? AND usage_date = ?
    ''', (user_id, today)).fetchone()
    
    conn.close()
    
    if not usage:
        return False, 0
    
    if limit_type == 'generations':
        return usage['generations_count'] >= 3, usage['generations_count']
    else:
        return usage['followups_count'] >= 1, usage['followups_count']

def increment_usage(user_id, limit_type='generations'):
    """Increment user's daily usage"""
    conn = get_db_connection()
    today = get_today()
    
    # Check if record exists
    existing = conn.execute('''
        SELECT id FROM usage_tracking WHERE user_id = ? AND usage_date = ?
    ''', (user_id, today)).fetchone()
    
    if existing:
        if limit_type == 'generations':
            conn.execute('''
                UPDATE usage_tracking SET generations_count = generations_count + 1 
                WHERE user_id = ? AND usage_date = ?
            ''', (user_id, today))
        else:
            conn.execute('''
                UPDATE usage_tracking SET followups_count = followups_count + 1 
                WHERE user_id = ? AND usage_date = ?
            ''', (user_id, today))
    else:
        if limit_type == 'generations':
            conn.execute('''
                INSERT INTO usage_tracking (user_id, usage_date, generations_count, followups_count)
                VALUES (?, ?, 1, 0)
            ''', (user_id, today))
        else:
            conn.execute('''
                INSERT INTO usage_tracking (user_id, usage_date, generations_count, followups_count)
                VALUES (?, ?, 0, 1)
            ''', (user_id, today))
    
    conn.commit()
    conn.close()

def clean_text(text):
    """Clean AI response text"""
    if not text:
        return ""
    text = text.replace('**', '').replace('*', '').replace('_', '')
    text = re.sub(r'#+\s*', '', text)
    return text.strip()

def call_llm(system_prompt, user_prompt, temperature=0.7, model="llama-3.1-8b-instant"):
    """Call Groq LLM API"""
    try:
        response = requests.post(GROQ_URL, headers=GROQ_HEADERS, json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": 3000
        }, timeout=90)
        
        result = response.json()
        if 'choices' in result and len(result['choices']) > 0:
            return clean_text(result['choices'][0]['message']['content'])
        logger.error(f"Groq API error: {result}")
        return "Error: AI service unavailable"
    except Exception as e:
        logger.error(f"LLM call error: {str(e)}")
        return f"Connection error: {str(e)}"

def extract_youtube_transcript(video_url):
    """Extract transcript from YouTube video"""
    try:
        # Extract video ID from URL
        if "youtube.com/watch?v=" in video_url:
            video_id = video_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
        else:
            return None, "Invalid YouTube URL"
        
        # Get transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_transcript = " ".join([entry['text'] for entry in transcript_list])
        return full_transcript, None
    except Exception as e:
        logger.error(f"YouTube transcript error: {str(e)}")
        return None, str(e)

def analyze_with_gemini(transcript, prompt):
    """Analyze transcript using Gemini"""
    try:
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(f"{prompt}\n\nTranscript:\n{transcript}")
        return response.text
    except Exception as e:
        logger.error(f"Gemini analysis error: {str(e)}")
        return f"Analysis error: {str(e)}"

# HTML Template (Comprehensive)
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
        :root {
            --bg: #ffffff;
            --glass-bg: rgba(0, 0, 0, 0.02);
            --glass-border: rgba(0, 0, 0, 0.08);
            --text: #000000;
            --text-muted: #666666;
            --accent: #000000;
            --accent-text: #ffffff;
            --success: #10b981;
            --error: #ef4444;
            --warning: #f59e0b;
            --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background-color: var(--bg); color: var(--text); font-family: var(--font); min-height: 100vh; line-height: 1.6; }
        .bg-shape { position: fixed; border-radius: 50%; filter: blur(100px); z-index: 0; pointer-events: none; }
        .shape-1 { width: 500px; height: 500px; background: #f0f0f0; top: -100px; left: -100px; }
        .shape-2 { width: 400px; height: 400px; background: #e5e5e5; bottom: -100px; right: -50px; }
        
        /* Navigation */
        nav { position: fixed; top: 24px; left: 50%; transform: translateX(-50%); width: 90%; max-width: 900px; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; z-index: 1000; background: rgba(255, 255, 255, 0.9); backdrop-filter: blur(20px); border: 1px solid var(--glass-border); border-radius: 100px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); transition: all 0.3s ease; }
        nav.pro-nav { background: #000; border-color: #333; }
        nav.pro-nav * { color: #fff; }
        .nav-left, .nav-right { display: flex; align-items: center; gap: 16px; }
        .logo { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        .user-avatar { width: 36px; height: 36px; border-radius: 50%; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; }
        .btn { padding: 8px 16px; border-radius: 100px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.3s; }
        .btn-primary { background: var(--accent); color: var(--accent-text); }
        .btn-secondary { background: rgba(0,0,0,0.05); color: var(--text); border: 1px solid var(--glass-border); }
        .btn:hover { transform: translateY(-2px); opacity: 0.9; }
        
        /* Main Container */
        .container { max-width: 900px; margin: 0 auto; padding: 140px 24px 60px; position: relative; z-index: 1; }
        .hero { text-align: center; margin-bottom: 60px; }
        .hero h1 { font-size: 56px; font-weight: 800; margin-bottom: 16px; letter-spacing: -2px; line-height: 1.1; }
        .hero p { font-size: 18px; color: var(--text-muted); max-width: 600px; margin: 0 auto; }
        
        /* Glass Card */
        .glass-card { background: rgba(255,255,255,0.7); backdrop-filter: blur(40px); border: 1px solid var(--glass-border); border-radius: 32px; padding: 48px; box-shadow: 0 30px 60px rgba(0,0,0,0.08); margin-bottom: 40px; }
        .main-input { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 16px; padding: 24px; font-size: 16px; resize: none; outline: none; min-height: 100px; margin-bottom: 24px; transition: all 0.3s; }
        .main-input:focus { border-color: var(--accent); background: rgba(0,0,0,0.05); }
        .options-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .option-card { background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 16px; padding: 20px; }
        .option-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 8px; display: block; }
        .option-select { width: 100%; background: transparent; border: none; font-size: 14px; outline: none; cursor: pointer; }
        .btn-launch { width: 100%; background: var(--accent); color: #fff; border: none; border-radius: 16px; padding: 20px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.3s; display: flex; align-items: center; justify-content: center; gap: 12px; }
        .btn-launch:hover { transform: translateY(-2px); box-shadow: 0 15px 40px rgba(0,0,0,0.2); }
        .btn-launch:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        
        /* Loader */
        .loader { display: none; text-align: center; padding: 60px; }
        .loader.active { display: block; }
        .spinner { width: 50px; height: 50px; border: 4px solid rgba(0,0,0,0.1); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        /* Footer Stats */
        .footer-stats { text-align: center; padding: 24px; border-top: 1px solid var(--glass-border); font-size: 13px; color: var(--text-muted); }
        .footer-stats strong { color: var(--text); }
        
        /* Overlay Results */
        .overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 2000; align-items: center; justify-content: center; padding: 20px; }
        .overlay.active { display: flex; }
        .overlay-backdrop { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(8px); }
        .overlay-content { position: relative; background: #fff; border-radius: 32px; width: 100%; max-width: 800px; max-height: 90vh; overflow-y: auto; z-index: 10; box-shadow: 0 30px 60px rgba(0,0,0,0.3); }
        .overlay-header { position: sticky; top: 0; background: rgba(255,255,255,0.95); backdrop-filter: blur(20px); padding: 24px; border-bottom: 1px solid var(--glass-border); display: flex; justify-content: space-between; align-items: center; z-index: 10; border-radius: 32px 32px 0 0; }
        .overlay-header h2 { font-size: 24px; font-weight: 700; }
        .close-btn { width: 40px; height: 40px; border-radius: 50%; border: none; background: var(--accent); color: #fff; cursor: pointer; font-size: 20px; display: flex; align-items: center; justify-content: center; }
        .overlay-body { padding: 32px; }
        
        /* Results Sections */
        .result-summary { background: rgba(0,0,0,0.03); border-left: 4px solid var(--accent); padding: 24px; border-radius: 12px; margin-bottom: 32px; font-size: 16px; line-height: 1.7; }
        .sections-carousel { display: flex; gap: 20px; overflow-x: auto; scroll-snap-type: x mandatory; padding: 20px 0; scrollbar-width: none; margin-bottom: 32px; }
        .sections-carousel::-webkit-scrollbar { display: none; }
        .section-card { flex: 0 0 90%; max-width: 350px; background: rgba(0,0,0,0.02); border: 1px solid var(--glass-border); border-radius: 20px; padding: 28px; scroll-snap-align: center; }
        .section-card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 16px; }
        .section-card p { font-size: 14px; line-height: 1.7; }
        .costs-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin-top: 24px; }
        .cost-card { background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 20px; text-align: center; }
        .cost-card.total { background: var(--accent); color: #fff; }
        .cost-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 8px; }
        .cost-card.total .cost-label { color: rgba(255,255,255,0.7); }
        .cost-value { font-size: 24px; font-weight: 700; }
        
        /* Follow-up */
        .followup-section { margin-top: 32px; padding-top: 32px; border-top: 1px solid var(--glass-border); }
        .followup-input { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 100px; padding: 16px 24px; font-size: 14px; margin-bottom: 12px; outline: none; }
        .followup-input:focus { border-color: var(--accent); }
        .qa-list { margin-top: 24px; }
        .qa-item { margin-bottom: 20px; }
        .qa-question { background: rgba(0,0,0,0.03); border-left: 3px solid var(--accent); padding: 16px; border-radius: 8px; margin-bottom: 12px; font-weight: 600; }
        .qa-answer { background: rgba(0,0,0,0.02); padding: 16px; border-radius: 8px; font-size: 14px; line-height: 1.7; }
        
        /* Modals */
        .modal-backdrop { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.95); backdrop-filter: blur(20px); z-index: 3000; align-items: center; justify-content: center; }
        .modal-backdrop.active { display: flex; }
        .modal-box { background: #fff; border: 1px solid var(--glass-border); border-radius: 32px; padding: 40px; max-width: 450px; width: 90%; box-shadow: 0 30px 60px rgba(0,0,0,0.15); }
        .modal-box h2 { font-size: 28px; margin-bottom: 8px; text-align: center; }
        .modal-box p { color: var(--text-muted); text-align: center; margin-bottom: 32px; }
        .tabs { display: flex; gap: 8px; margin-bottom: 24px; background: rgba(0,0,0,0.05); padding: 4px; border-radius: 100px; }
        .tab { flex: 1; padding: 12px; border: none; background: transparent; border-radius: 100px; font-weight: 600; cursor: pointer; transition: all 0.3s; }
        .tab.active { background: var(--accent); color: #fff; }
        .input-field { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 16px; font-size: 14px; margin-bottom: 16px; outline: none; }
        .input-field:focus { border-color: var(--accent); }
        .btn-full { width: 100%; background: var(--accent); color: #fff; border: none; border-radius: 100px; padding: 16px; font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 8px; }
        .divider { display: flex; align-items: center; margin: 24px 0; color: var(--text-muted); font-size: 12px; }
        .divider::before, .divider::after { content: ''; flex: 1; border-bottom: 1px solid var(--glass-border); }
        .divider::before { margin-right: 12px; }
        .divider::after { margin-left: 12px; }
        .google-btn { width: 100%; background: #fff; border: 1px solid var(--glass-border); padding: 14px; border-radius: 100px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 12px; }
        .google-btn:hover { background: rgba(0,0,0,0.02); }
        
        /* Highlight boxes */
        .hl { display: inline-block; padding: 2px 8px; border-radius: 6px; font-weight: 700; }
        .hl-market { background: #dbeafe; color: #1e40af; }
        .hl-revenue { background: #dcfce7; color: #166534; }
        .hl-strategy { background: #f3e8ff; color: #6b21a8; }
        .hl-cost { background: #fee2e2; color: #991b1b; }
        
        /* YouTube Section */
        .youtube-section { margin-top: 40px; padding: 32px; background: rgba(0,0,0,0.02); border-radius: 24px; border: 1px solid var(--glass-border); }
        .youtube-section h3 { font-size: 20px; margin-bottom: 16px; }
        .youtube-input { display: flex; gap: 12px; margin-bottom: 16px; }
        .youtube-input input { flex: 1; background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 16px; font-size: 14px; }
        .youtube-input button { background: #ff0000; color: #fff; border: none; border-radius: 12px; padding: 16px 32px; font-weight: 600; cursor: pointer; }
        .youtube-result { background: #fff; border: 1px solid var(--glass-border); border-radius: 12px; padding: 24px; margin-top: 16px; display: none; }
        .youtube-result.active { display: block; }
        
        /* Competitor Section */
        .competitor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-top: 24px; }
        .competitor-card { background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 16px; padding: 24px; }
        .competitor-card h4 { font-size: 16px; margin-bottom: 12px; color: var(--accent); }
        .competitor-card ul { list-style: none; padding: 0; }
        .competitor-card li { padding: 8px 0; border-bottom: 1px solid rgba(0,0,0,0.05); font-size: 14px; }
        .competitor-card li:last-child { border-bottom: none; }
        
        /* Responsive */
        @media (max-width: 768px) {
            .hero h1 { font-size: 36px; }
            .glass-card { padding: 24px; }
            .options-grid { grid-template-columns: 1fr; }
            nav { width: 95%; padding: 12px 16px; }
            .overlay-content { max-height: 95vh; }
            .section-card { flex: 0 0 100%; }
        }
    </style>
</head>
<body>
<div class="bg-shape shape-1"></div>
<div class="bg-shape shape-2"></div>

<nav id="mainNav">
    <div class="nav-left" id="navLeft">
        <div class="logo">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
            Winy AI
        </div>
    </div>
    <div class="nav-right" id="navRight">
        <button class="btn btn-secondary" onclick="showLoginModal()">Login / Sign Up</button>
    </div>
</nav>

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
                        <option value="Education">Education</option>
                    </select>
                </div>
                <div class="option-card">
                    <span class="option-label">Depth</span>
                    <select class="option-select" id="optLength" disabled>
                        <option value="short">Brief (Quick Scan)</option>
                        <option value="medium" selected>Standard (Detailed)</option>
                        <option value="long">Deep Dive (Pro)</option>
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
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M5 12h14M12 5l7 7-7 7"/>
                </svg>
                Login to Initialize Swarm
            </button>
        </div>
    </div>

    <div class="loader" id="loader">
        <div class="spinner"></div>
        <p style="color: var(--text-muted); font-size: 14px;">AI Swarm is analyzing your business...</p>
    </div>

    <div class="footer-stats" id="footerStats">
        Please login to access features
    </div>

    <!-- YouTube Analysis Section -->
    <div class="youtube-section" id="youtubeSection" style="display:none;">
        <h3>🎥 YouTube Video Analysis (Pro)</h3>
        <p style="color: var(--text-muted); margin-bottom: 20px;">Paste a YouTube URL to extract transcript and get AI analysis</p>
        <div class="youtube-input">
            <input type="text" id="youtubeUrl" placeholder="https://youtube.com/watch?v=...">
            <button onclick="analyzeYouTube()">Analyze Video</button>
        </div>
        <div class="youtube-result" id="youtubeResult"></div>
    </div>

    <!-- Competitor Analysis Section -->
    <div class="youtube-section" id="competitorSection" style="display:none;">
        <h3>🏢 Competitor Analysis</h3>
        <p style="color: var(--text-muted); margin-bottom: 20px;">Top competitors in your industry</p>
        <div id="competitorResults"></div>
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
            <input type="password" class="input-field" id="signupPassword" placeholder="Password (min 6 chars)">
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
    // Firebase Configuration
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
    
    // State Variables
    var isPro = {{ session.get('is_pro', False) | tojson }};
    var generationsUsed = {{ session.get('generations_count', 0) | tojson }};
    var followupsUsed = {{ session.get('followups_count', 0) | tojson }};
    var rzpKeyId = {{ razorpay_key_id | tojson }};
    var isLoggedIn = false;
    var currentUser = null;
    var currentContext = '';
    var currentIndustry = '';
    var currentStrategyId = null;

    // Auth State Listener
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
        document.getElementById('youtubeSection').style.display = 'block';
        document.getElementById('competitorSection').style.display = 'block';
    }

    function disableFeatures() {
        ['mainPrompt', 'optIndustry', 'optLength', 'optTone'].forEach(id => {
            document.getElementById(id).disabled = true;
        });
        document.getElementById('btnLaunch').disabled = true;
        document.getElementById('btnLaunch').innerHTML = 'Login to Initialize Swarm';
        document.getElementById('youtubeSection').style.display = 'none';
        document.getElementById('competitorSection').style.display = 'none';
    }

    function updateUserUI() {
        var navLeft = document.getElementById('navLeft');
        var navRight = document.getElementById('navRight');
        var footer = document.getElementById('footerStats');
        var mainNav = document.getElementById('mainNav');
        
        if (isLoggedIn) {
            var userInitial = currentUser.email ? currentUser.email.charAt(0).toUpperCase() : 'U';
            navLeft.innerHTML = '<div class="user-avatar">' + userInitial + '</div>';
            navRight.innerHTML = '<button class="btn btn-secondary" onclick="logout()">Logout</button>' + 
                                (isPro ? '<span style="background:#10b981;color:#fff;padding:4px 12px;border-radius:100px;font-size:11px;font-weight:700;">PRO</span>' : 
                                '<button class="btn btn-primary" onclick="initiatePayment()">Upgrade to Pro</button>');
            
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
            navLeft.innerHTML = '<div class="logo"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg> Winy AI</div>';
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
        // Summary
        document.getElementById('resultSummary').innerHTML = '<p>' + highlightText(data.summary) + '</p>';
        
        // Sections
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
        
        // Costs
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

    function analyzeYouTube() {
        if (!isLoggedIn) { showLoginModal(); return; }
        if (!isPro) return showAlert('Pro Feature', 'YouTube analysis is available only for Pro users');
        
        var url = document.getElementById('youtubeUrl').value.trim();
        if (!url) return showAlert('Error', 'Please enter a YouTube URL');
        
        var resultDiv = document.getElementById('youtubeResult');
        resultDiv.classList.add('active');
        resultDiv.innerHTML = '<p style="color:var(--text-muted);">Extracting transcript and analyzing...</p>';
        
        fetch('/analyze-youtube', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                resultDiv.innerHTML = '<p style="color:var(--error);">Error: ' + data.error + '</p>';
            } else {
                resultDiv.innerHTML = '<h4>Analysis</h4><p>' + highlightText(data.analysis) + '</p>';
            }
        })
        .catch(err => {
            resultDiv.innerHTML = '<p style="color:var(--error);">Error: ' + err.message + '</p>';
        });
    }

    function loadCompetitors() {
        if (!isLoggedIn) return;
        
        var industry = document.getElementById('optIndustry').value;
        var resultsDiv = document.getElementById('competitorResults');
        
        fetch('/get-competitors?industry=' + encodeURIComponent(industry))
        .then(res => res.json())
        .then(data => {
            if (data.competitors) {
                var html = '<div class="competitor-grid">';
                data.competitors.forEach(c => {
                    html += '<div class="competitor-card"><h4>' + c.name + '</h4><ul>';
                    c.strengths.forEach(s => html += '<li>✓ ' + s + '</li>');
                    html += '</ul></div>';
                });
                html += '</div>';
                resultsDiv.innerHTML = html;
            }
        })
        .catch(err => console.error('Competitor load error:', err));
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
                            showAlert('Welcome to Pro!', 'Payment successful! You now have unlimited access to all features.');
                        } else {
                            showAlert('Payment Failed', 'Verification failed. Contact support with Payment ID: ' + response.razorpay_payment_id);
                        }
                    })
                    .catch(err => showAlert('Error', 'Verification error: ' + err.message));
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

    // Initialize
    updateUserUI();
    if (isLoggedIn) loadCompetitors();
</script>
</body>
</html>
'''

# Routes
@app.route('/')
@limiter.limit("100 per day")
def home():
    """Home page"""
    today = get_today()
    
    # Initialize session
    if 'is_pro' not in session:
        session['is_pro'] = False
    if 'generations_count' not in session:
        session['generations_count'] = 0
    if 'followups_count' not in session:
        session['followups_count'] = 0
    
    # Check if user is logged in via Firebase
    if 'user_id' in session:
        conn = get_db_connection()
        user = conn.execute('SELECT is_pro FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user:
            session['is_pro'] = bool(user['is_pro'])
        conn.close()
    
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/generate', methods=['POST'])
@limiter.limit("20 per hour")
def generate():
    """Generate business strategy"""
    client_ip = get_client_ip()
    
    # Check authentication
    if 'user_id' not in session:
        return jsonify({"error": "Please login to use this feature"}), 401
    
    user_id = session['user_id']
    
    # Check daily limit
    limit_reached, count = check_daily_limit(user_id, 'generations')
    if limit_reached:
        return jsonify({"error": f"Daily limit reached ({count}/3). Resets at midnight."}), 403
    
    data = request.json
    prompt = data.get('prompt', '')
    industry = data.get('industry', 'General')
    length = data.get('length', 'medium')
    tone = data.get('tone', 'Professional')
    
    if not prompt or len(prompt) < 10:
        return jsonify({"error": "Please provide a detailed business idea (at least 10 characters)"}), 400
    
    # Check if Pro feature
    if length == 'long' and not session.get('is_pro'):
        return jsonify({"error": "Deep Dive is a Pro-only feature"}), 403
    
    # Word limits
    word_map = {'short': '150 words', 'medium': '300 words', 'long': '500 words'}
    limit = word_map.get(length, '300 words')
    
    # Comprehensive AI prompt
    system_prompt = f"""You are an expert business consultant with 20+ years of experience. Analyze this business idea comprehensively.

Business Idea: "{prompt}"
Industry: {industry}
Tone: {tone}

Provide a detailed analysis in JSON format with these exact keys:

{{
  "summary": "2-3 sentences executive summary",
  "market": "{limit} covering: market size, growth rate, target segments, trends, opportunities, threats",
  "strategy": "{limit} covering: operational plan, key milestones, team structure, technology stack, timeline",
  "financials": "{limit} covering: revenue model, pricing strategy, CAC, LTV, break-even, 3-year projections with numbers",
  "gtm": "{limit} covering: marketing channels, launch strategy, customer acquisition tactics, partnerships",
  "costs": {{
    "Product Dev": number,
    "Marketing": number,
    "Operations": number,
    "Legal": number,
    "Contingency": number,
    "total": number
  }}
}}

Be specific, actionable, and data-driven. Use real-world examples where applicable."""

    try:
        raw = call_llm(system_prompt, prompt, temperature=0.7)
        logger.info(f"Raw AI response length: {len(raw)}")
        
        # Parse JSON
        raw = raw.replace('```json', '').replace('```', '').strip()
        data_json = json.loads(raw)
        
        # Validate required fields
        required = ['summary', 'market', 'strategy', 'financials', 'gtm', 'costs']
        for field in required:
            if field not in data_json:
                data_json[field] = "Data not available" if field != 'costs' else {"total": 14000}
        
        # Save to database
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO strategies (user_id, prompt, industry, length, tone, result_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, prompt, industry, length, tone, json.dumps(data_json)))
        strategy_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
        conn.close()
        
        # Increment usage
        increment_usage(user_id, 'generations')
        
        return jsonify(data_json)
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.error(f"Raw response: {raw[:500]}")
        return jsonify({"error": "AI formatting error. Please try again."}), 500
    except Exception as e:
        logger.error(f"Generation error: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route('/followup', methods=['POST'])
@limiter.limit("10 per hour")
def followup():
    """Handle follow-up questions"""
    if 'user_id' not in session:
        return jsonify({"error": "Please login"}), 401
    
    user_id = session['user_id']
    
    # Check limit
    limit_reached, count = check_daily_limit(user_id, 'followups')
    if limit_reached:
        return jsonify({"error": f"Follow-up limit reached ({count}/1). Resets at midnight."}), 403
    
    data = request.json
    question = data.get('question', '')
    context = data.get('context', '')
    industry = data.get('industry', 'General')
    
    if not question:
        return jsonify({"error": "Please enter a question"}), 400
    
    system_prompt = f"""You are a business consultant. Context: {industry} business idea: '{context}'.
    Answer this question concisely in 100-150 words: {question}"""
    
    try:
        answer = call_llm(system_prompt, question, temperature=0.5)
        increment_usage(user_id, 'followups')
        return jsonify({"answer": answer})
    except Exception as e:
        logger.error(f"Followup error: {str(e)}")
        return jsonify({"error": "Failed to get answer"}), 500

@app.route('/analyze-youtube', methods=['POST'])
def analyze_youtube():
    """Analyze YouTube video"""
    if 'user_id' not in session:
        return jsonify({"error": "Please login"}), 401
    
    if not session.get('is_pro'):
        return jsonify({"error": "YouTube analysis is a Pro feature"}), 403
    
    data = request.json
    url = data.get('url', '')
    
    if not url:
        return jsonify({"error": "Please provide a YouTube URL"}), 400
    
    try:
        # Extract transcript
        transcript, error = extract_youtube_transcript(url)
        if error:
            return jsonify({"error": f"Transcript error: {error}"}), 400
        
        # Analyze with Gemini
        prompt = "Analyze this video transcript and provide key insights, main points, and actionable takeaways for a business audience."
        analysis = analyze_with_gemini(transcript, prompt)
        
        # Save to database
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO youtube_analysis (user_id, video_url, transcript, analysis)
            VALUES (?, ?, ?, ?)
        ''', (session['user_id'], url, transcript, analysis))
        conn.commit()
        conn.close()
        
        return jsonify({"analysis": analysis, "transcript": transcript[:500] + "..."})
    except Exception as e:
        logger.error(f"YouTube analysis error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get-competitors')
def get_competitors():
    """Get competitor analysis"""
    industry = request.args.get('industry', 'General')
    
    # Check cache
    conn = get_db_connection()
    cached = conn.execute('''
        SELECT competitor_data FROM competitor_cache 
        WHERE industry = ? AND updated_at > datetime('now', '-7 days')
    ''', (industry,)).fetchone()
    
    if cached:
        conn.close()
        return jsonify(json.loads(cached['competitor_data']))
    
    # Generate competitors
    prompt = f"List top 5 competitors in the {industry} industry with their key strengths."
    
    try:
        response = call_llm(prompt, "Provide competitor analysis", temperature=0.3)
        
        # Parse response (simplified)
        competitors = [
            {"name": "Competitor 1", "strengths": ["Strong brand", "Large market share"]},
            {"name": "Competitor 2", "strengths": ["Innovation", "Customer loyalty"]}
        ]
        
        # Cache it
        conn.execute('''
            INSERT OR REPLACE INTO competitor_cache (industry, competitor_data, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (industry, json.dumps({"competitors": competitors})))
        conn.commit()
        conn.close()
        
        return jsonify({"competitors": competitors})
    except Exception as e:
        logger.error(f"Competitor fetch error: {str(e)}")
        return jsonify({"competitors": []}), 500

@app.route('/api/create-order', methods=['POST'])
def create_order():
    """Create Razorpay order"""
    if 'user_id' not in session:
        return jsonify({"error": "Please login"}), 401
    
    if not razorpay_client:
        return jsonify({"error": "Payment system not configured"}), 500
    
    try:
        order = razorpay_client.order.create({
            "amount": 49900,  # ₹499
            "currency": "INR",
            "receipt": f"rcpt_{uuid.uuid4().hex[:16]}",
            "payment_capture": 1
        })
        
        # Log order
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO payment_logs (user_id, order_id, amount, status)
            VALUES (?, ?, ?, 'created')
        ''', (session['user_id'], order['id'], order['amount']))
        conn.commit()
        conn.close()
        
        return jsonify(order)
    except Exception as e:
        logger.error(f"Order creation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
def verify_payment():
    """Verify Razorpay payment"""
    if 'user_id' not in session:
        return jsonify({"error": "Please login"}), 401
    
    data = request.json
    order_id = data.get('razorpay_order_id', '')
    payment_id = data.get('razorpay_payment_id', '')
    signature = data.get('razorpay_signature', '')
    
    if not all([order_id, payment_id, signature]):
        return jsonify({"status": "failure", "message": "Missing payment data"}), 400
    
    try:
        # Verify signature
        message = f"{order_id}|{payment_id}"
        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if expected != signature:
            return jsonify({"status": "failure", "message": "Signature mismatch"}), 400
        
        # Update user to Pro
        conn = get_db_connection()
        pro_expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        conn.execute('''
            UPDATE users SET is_pro = 1, pro_expiry = ? WHERE id = ?
        ''', (pro_expiry, session['user_id']))
        
        # Update payment log
        conn.execute('''
            UPDATE payment_logs SET status = 'success', payment_id = ? WHERE order_id = ?
        ''', (payment_id, order_id))
        conn.commit()
        conn.close()
        
        # Update session
        session['is_pro'] = True
        
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Payment verification error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# Initialize database and run app
if __name__ == '__main__':
    logger.info("Starting Winy AI Server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
