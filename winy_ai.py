"""
Winy AI - Your Personal Problem-Solving Swarm
A comprehensive Flask application for solving any problem using AI.
Features: Firebase Authentication, Razorpay Payments, Groq AI Integration,
YouTube Transcript Analysis, SQLite Database, IP-based Rate Limiting.
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

# Initialize Flask App
from flask import Flask, request, jsonify, render_template_string, session, g

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "winy-ai-secret-key-change-in-production")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['JSON_SORT_KEYS'] = False

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

# Initialize Razorpay
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    try:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        logger.info("Razorpay initialized")
    except Exception as e:
        logger.error(f"Razorpay init error: {e}")

# IP Tracking
ip_usage_tracker = defaultdict(lambda: {'count': 0, 'date': None})

# Database Setup
DATABASE_PATH = 'winy_ai.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT UNIQUE NOT NULL,
        email TEXT NOT NULL,
        is_pro INTEGER DEFAULT 0,
        pro_expiry DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS daily_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        usage_date DATE NOT NULL,
        queries_count INTEGER DEFAULT 0,
        followups_count INTEGER DEFAULT 0,
        UNIQUE(firebase_uid, usage_date)
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS query_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL,
        query_type TEXT,
        query_text TEXT,
        result_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

def get_today():
    return date.today().isoformat()

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    return request.remote_addr

def clean_text(text):
    if not text:
        return ""
    text = text.replace('**', '').replace('*', '').replace('_', '')
    text = re.sub(r'#+\s*', '', text)
    return text.strip()

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'firebase_uid' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

def call_groq_llm(system_prompt, user_prompt, temperature=0.7):
    if not GROQ_API_KEY:
        return "Error: GROQ_API_KEY not configured"
        
    try:
        response = requests.post(GROQ_URL, headers=GROQ_HEADERS, json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": 3000
        }, timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                return clean_text(result['choices'][0]['message']['content'])
        return "Error: AI service unavailable"
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return f"Error: {str(e)}"

def parse_json_response(raw_text):
    if not raw_text:
        return None
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
    except json.JSONDecodeError:
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        try:
            return json.loads(cleaned)
        except:
            return None

def get_youtube_transcript(video_url):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        video_id = None
        if "youtube.com/watch?v=" in video_url:
            video_id = video_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
        if not video_id:
            return None, "Invalid YouTube URL"
            
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([entry['text'] for entry in transcript_list])
        return full_text, None
    except Exception as e:
        logger.error(f"YouTube error: {e}")
        return None, str(e)

# ==============================================================================
# HTML TEMPLATE - Updated for General Problem Solving
# ==============================================================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Winy AI | Your Problem-Solving Swarm</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fff; color: #000; min-height: 100vh; }
        .bg-shape { position: fixed; border-radius: 50%; filter: blur(100px); z-index: 0; }
        .shape-1 { width: 600px; height: 600px; background: #f0f0f0; top: -150px; left: -150px; }
        .shape-2 { width: 500px; height: 500px; background: #e8e8e8; bottom: -100px; right: -100px; }
        
        nav { position: fixed; top: 24px; left: 50%; transform: translateX(-50%); width: 92%; max-width: 900px; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; z-index: 1000; background: rgba(255,255,255,0.85); backdrop-filter: blur(20px); border: 1px solid rgba(0,0,0,0.08); border-radius: 100px; }
        nav.pro-nav { background: #000; border-color: #333; }
        nav.pro-nav * { color: #fff; }
        .logo { font-size: 18px; font-weight: 700; }
        .user-avatar { width: 36px; height: 36px; border-radius: 50%; background: #000; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; }
        nav.pro-nav .user-avatar { background: #fff; color: #000; }
        .btn { padding: 8px 16px; border-radius: 100px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; }
        .btn-primary { background: #000; color: #fff; }
        .btn-secondary { background: rgba(0,0,0,0.05); }
        nav.pro-nav .btn-primary { background: #fff; color: #000; }
        .pro-badge { background: #10b981; color: #fff; padding: 4px 12px; border-radius: 100px; font-size: 11px; font-weight: 700; }
        
        .container { max-width: 900px; margin: 0 auto; padding: 140px 24px 60px; position: relative; z-index: 1; }
        .hero { text-align: center; margin-bottom: 60px; }
        .hero h1 { font-size: 52px; font-weight: 800; margin-bottom: 16px; letter-spacing: -2px; }
        .hero p { font-size: 18px; color: #666; max-width: 600px; margin: 0 auto; }
        
        .glass-card { background: rgba(255,255,255,0.7); backdrop-filter: blur(40px); border: 1px solid rgba(0,0,0,0.08); border-radius: 32px; padding: 48px; margin-bottom: 40px; box-shadow: 0 30px 60px rgba(0,0,0,0.06); }
        .main-input { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.08); border-radius: 16px; padding: 24px; font-size: 16px; min-height: 120px; margin-bottom: 24px; resize: none; outline: none; }
        .main-input:focus { border-color: #000; background: rgba(0,0,0,0.05); }
        .main-input::placeholder { color: #999; }
        
        .mode-tabs { display: flex; gap: 12px; margin-bottom: 24px; }
        .mode-tab { flex: 1; padding: 16px; border: 1px solid rgba(0,0,0,0.08); border-radius: 12px; background: rgba(0,0,0,0.02); cursor: pointer; font-weight: 600; transition: all 0.3s; }
        .mode-tab.active { background: #000; color: #fff; border-color: #000; }
        .mode-tab:hover:not(.active) { background: rgba(0,0,0,0.05); }
        
        .options-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .option-card { background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.08); border-radius: 16px; padding: 20px; }
        .option-label { font-size: 11px; text-transform: uppercase; color: #666; margin-bottom: 8px; display: block; font-weight: 600; }
        .option-select { width: 100%; background: transparent; border: none; font-size: 14px; outline: none; }
        
        .btn-launch { width: 100%; background: #000; color: #fff; border: none; border-radius: 16px; padding: 20px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.3s; }
        .btn-launch:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 15px 40px rgba(0,0,0,0.2); }
        .btn-launch:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .loader { display: none; text-align: center; padding: 80px 20px; }
        .loader.active { display: block; }
        .spinner { width: 50px; height: 50px; border: 4px solid rgba(0,0,0,0.1); border-top-color: #000; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 24px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .footer-stats { text-align: center; padding: 24px; border-top: 1px solid rgba(0,0,0,0.08); color: #666; font-size: 13px; }
        
        .overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 2000; align-items: center; justify-content: center; padding: 20px; }
        .overlay.active { display: flex; }
        .overlay-backdrop { position: absolute; background: rgba(0,0,0,0.5); backdrop-filter: blur(8px); top: 0; left: 0; right: 0; bottom: 0; }
        .overlay-content { position: relative; background: #fff; border-radius: 32px; width: 100%; max-width: 800px; max-height: 90vh; overflow-y: auto; box-shadow: 0 30px 60px rgba(0,0,0,0.3); }
        .overlay-header { position: sticky; top: 0; background: rgba(255,255,255,0.95); backdrop-filter: blur(20px); padding: 24px 32px; border-bottom: 1px solid rgba(0,0,0,0.08); display: flex; justify-content: space-between; align-items: center; z-index: 10; border-radius: 32px 32px 0 0; }
        .close-btn { width: 40px; height: 40px; border-radius: 50%; border: none; background: #000; color: #fff; cursor: pointer; font-size: 20px; }
        .overlay-body { padding: 32px; }
        
        .result-summary { background: rgba(0,0,0,0.03); border-left: 4px solid #000; padding: 24px; border-radius: 12px; margin-bottom: 32px; line-height: 1.7; }
        .sections-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 32px; }
        .section-card { background: rgba(0,0,0,0.02); border: 1px solid rgba(0,0,0,0.08); border-radius: 20px; padding: 28px; }
        .section-card h3 { font-size: 12px; text-transform: uppercase; color: #666; margin-bottom: 16px; font-weight: 700; }
        .section-card p { font-size: 14px; line-height: 1.7; }
        
        .youtube-section { margin-top: 40px; padding: 32px; background: rgba(0,0,0,0.02); border-radius: 24px; border: 1px solid rgba(0,0,0,0.08); }
        .youtube-section h3 { font-size: 18px; margin-bottom: 16px; }
        .youtube-input { display: flex; gap: 12px; margin-bottom: 16px; }
        .youtube-input input { flex: 1; background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.08); border-radius: 12px; padding: 16px; }
        .youtube-input button { background: #ff0000; color: #fff; border: none; border-radius: 12px; padding: 16px 32px; font-weight: 600; cursor: pointer; }
        .youtube-result { background: #fff; border: 1px solid rgba(0,0,0,0.08); border-radius: 12px; padding: 24px; margin-top: 16px; display: none; }
        .youtube-result.active { display: block; }
        
        .followup-section { margin-top: 32px; padding-top: 32px; border-top: 1px solid rgba(0,0,0,0.08); }
        .followup-input { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.08); border-radius: 100px; padding: 16px; margin-bottom: 12px; }
        .qa-list { margin-top: 24px; }
        .qa-item { margin-bottom: 20px; }
        .qa-question { background: rgba(0,0,0,0.03); border-left: 3px solid #000; padding: 16px; border-radius: 8px; margin-bottom: 12px; font-weight: 600; }
        .qa-answer { background: rgba(0,0,0,0.02); padding: 16px; border-radius: 8px; line-height: 1.7; }
        
        .modal-backdrop { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.95); backdrop-filter: blur(20px); z-index: 3000; align-items: center; justify-content: center; }
        .modal-backdrop.active { display: flex; }
        .modal-box { background: #fff; border: 1px solid rgba(0,0,0,0.08); border-radius: 32px; padding: 40px; max-width: 450px; width: 90%; }
        .modal-box h2 { text-align: center; margin-bottom: 8px; }
        .modal-box > p { text-align: center; color: #666; margin-bottom: 32px; }
        .tabs { display: flex; gap: 8px; margin-bottom: 24px; background: rgba(0,0,0,0.05); padding: 4px; border-radius: 100px; }
        .tab { flex: 1; padding: 12px; border: none; background: transparent; border-radius: 100px; font-weight: 600; cursor: pointer; }
        .tab.active { background: #000; color: #fff; }
        .input-field { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.08); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
        .btn-full { width: 100%; background: #000; color: #fff; border: none; border-radius: 100px; padding: 16px; font-weight: 600; cursor: pointer; }
        .divider { display: flex; align-items: center; margin: 24px 0; color: #666; font-size: 12px; }
        .divider::before, .divider::after { content: ''; flex: 1; border-bottom: 1px solid rgba(0,0,0,0.08); }
        .google-btn { width: 100%; background: #fff; border: 1px solid rgba(0,0,0,0.08); padding: 14px; border-radius: 100px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 12px; }
        
        .hl { display: inline-block; padding: 2px 8px; border-radius: 6px; font-weight: 700; }
        .hl-key { background: #dbeafe; color: #1e40af; }
        .hl-solution { background: #dcfce7; color: #166534; }
        .hl-step { background: #f3e8ff; color: #6b21a8; }
        
        @media (max-width: 768px) {
            .hero h1 { font-size: 36px; }
            .glass-card { padding: 24px; }
            nav { width: 95%; }
            .mode-tabs { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="bg-shape shape-1"></div>
    <div class="bg-shape shape-2"></div>

    <nav id="mainNav">
        <div class="logo" id="navLogo">Winy AI</div>
        <div id="navButtons"><button class="btn btn-secondary" onclick="showLoginModal()">Login</button></div>
    </nav>

    <div class="container">
        <div class="hero">
            <h1>Deploy the Swarm.</h1>
            <p>Break down any problem. Get clear solutions. From business to personal challenges.</p>
        </div>

        <div id="inputWrapper">
            <div class="glass-card">
                <div class="mode-tabs">
                    <div class="mode-tab active" onclick="setMode('problem')" id="tabProblem">🎯 Problem Solver</div>
                    <div class="mode-tab" onclick="setMode('business')" id="tabBusiness">💼 Business Strategy</div>
                    <div class="mode-tab" onclick="setMode('learning')" id="tabLearning">📚 Learning Helper</div>
                </div>
                
                <textarea class="main-input" id="mainPrompt" placeholder="Describe your problem or question in detail..." disabled></textarea>
                
                <div class="options-grid" id="optionsGrid">
                    <div class="option-card">
                        <span class="option-label">Category</span>
                        <select class="option-select" id="optCategory" disabled>
                            <option value="General">General Problem</option>
                            <option value="Technical">Technical Issue</option>
                            <option value="Personal">Personal Development</option>
                            <option value="Career">Career & Work</option>
                            <option value="Education">Education & Learning</option>
                            <option value="Health">Health & Wellness</option>
                        </select>
                    </div>
                    <div class="option-card">
                        <span class="option-label">Depth</span>
                        <select class="option-select" id="optDepth" disabled>
                            <option value="quick">Quick Answer</option>
                            <option value="detailed" selected>Detailed Breakdown</option>
                            <option value="comprehensive">Comprehensive Guide (Pro)</option>
                        </select>
                    </div>
                </div>
                
                <button class="btn-launch" id="btnLaunch" onclick="runSwarm()" disabled>
                    Login to Deploy Swarm
                </button>
            </div>
        </div>

        <!-- YouTube Section -->
        <div class="youtube-section" id="youtubeSection" style="display:none;">
            <h3>🎥 YouTube Video Analysis (Pro)</h3>
            <p style="color:#666; margin-bottom:20px;">Extract insights from any YouTube video</p>
            <div class="youtube-input">
                <input type="text" id="youtubeUrl" placeholder="https://youtube.com/watch?v=...">
                <button onclick="analyzeYouTube()">Analyze Video</button>
            </div>
            <div class="youtube-result" id="youtubeResult"></div>
        </div>

        <div class="loader" id="loader">
            <div class="spinner"></div>
            <p style="color:#666;">Swarm is analyzing your problem...</p>
        </div>

        <div class="footer-stats" id="footerStats">Please login to access features</div>
    </div>

    <!-- Results Overlay -->
    <div class="overlay" id="resultsOverlay">
        <div class="overlay-backdrop" onclick="closeResultsOverlay()"></div>
        <div class="overlay-content">
            <div class="overlay-header">
                <h2>Solution Breakdown</h2>
                <button class="close-btn" onclick="closeResultsOverlay()">✕</button>
            </div>
            <div class="overlay-body">
                <div class="result-summary" id="resultSummary"></div>
                <div class="sections-grid" id="sectionsGrid"></div>
                
                <div class="followup-section">
                    <span class="option-label">Need clarification?</span>
                    <input type="text" class="followup-input" id="followupInput" placeholder="Ask a follow-up question...">
                    <button class="btn-launch" id="followupBtn" onclick="askFollowup()" style="padding:12px;">Ask Swarm</button>
                    <div class="qa-list" id="qaList"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Login Modal -->
    <div class="modal-backdrop" id="loginModal">
        <div class="modal-box">
            <h2>Welcome</h2>
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
            <div class="divider">or</div>
            <button class="google-btn" onclick="loginWithGoogle()">Continue with Google</button>
        </div>
    </div>

    <!-- Alert Modal -->
    <div class="modal-backdrop" id="alertModal">
        <div class="modal-box">
            <h2 id="alertTitle">Title</h2>
            <p id="alertMessage" style="margin:20px 0;color:#666;">Message</p>
            <button class="btn-full" onclick="closeAlert()">OK</button>
        </div>
    </div>

    <script>
        const firebaseConfig = { apiKey: "AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU", authDomain: "winy-3984d.firebaseapp.com", projectId: "winy-3984d", storageBucket: "winy-3984d.firebasestorage.app", messagingSenderId: "126237613814", appId: "1:126237613814:web:e3cb88222d920545a416d7" };
        firebase.initializeApp(firebaseConfig);
        const auth = firebase.auth();
        
        var isPro = {{ session.get('is_pro', False) | tojson }};
        var queriesUsed = {{ session.get('queries_count', 0) | tojson }};
        var followupsUsed = {{ session.get('followups_count', 0) | tojson }};
        var rzpKeyId = {{ razorpay_key_id | tojson }};
        var isLoggedIn = false, currentUser = null, currentMode = 'problem', currentContext = '';

        auth.onAuthStateChanged(function(user) {
            if (user) { isLoggedIn = true; currentUser = user; enableFeatures(); updateUserUI(); } 
            else { isLoggedIn = false; currentUser = null; disableFeatures(); updateUserUI(); }
        });

        function setMode(mode) {
            currentMode = mode;
            document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
            document.getElementById('tab' + mode.charAt(0).toUpperCase() + mode.slice(1)).classList.add('active');
            
            var placeholders = {
                'problem': 'Describe your problem or question in detail...',
                'business': 'Describe your business idea or challenge...',
                'learning': 'What topic do you want to learn or understand better?'
            };
            document.getElementById('mainPrompt').placeholder = placeholders[mode];
        }

        function enableFeatures() {
            ['mainPrompt', 'optCategory', 'optDepth'].forEach(id => document.getElementById(id).disabled = false);
            document.getElementById('btnLaunch').disabled = false;
            document.getElementById('btnLaunch').innerHTML = 'Deploy Swarm';
            document.getElementById('youtubeSection').style.display = 'block';
        }
        function disableFeatures() {
            ['mainPrompt', 'optCategory', 'optDepth'].forEach(id => document.getElementById(id).disabled = true);
            document.getElementById('btnLaunch').disabled = true;
            document.getElementById('btnLaunch').innerHTML = 'Login to Deploy Swarm';
            document.getElementById('youtubeSection').style.display = 'none';
        }
        function updateUserUI() {
            var navLogo = document.getElementById('navLogo'), navButtons = document.getElementById('navButtons'), footer = document.getElementById('footerStats'), mainNav = document.getElementById('mainNav');
            if (isLoggedIn) {
                var initial = currentUser.email.charAt(0).toUpperCase();
                navLogo.innerHTML = '<div class="user-avatar">' + initial + '</div>';
                navButtons.innerHTML = '<button class="btn btn-secondary" onclick="logout()">Logout</button>' + (isPro ? '<span class="pro-badge">PRO</span>' : '<button class="btn btn-primary" onclick="initiatePayment()">Upgrade</button>');
                if (isPro) { mainNav.classList.add('pro-nav'); footer.innerHTML = '<strong>Pro User:</strong> Unlimited queries'; } 
                else { mainNav.classList.remove('pro-nav'); footer.innerHTML = '<strong>Free:</strong> ' + Math.max(0, 3-queriesUsed) + ' queries left today'; }
            } else {
                mainNav.classList.remove('pro-nav');
                navLogo.textContent = 'Winy AI';
                navButtons.innerHTML = '<button class="btn btn-secondary" onclick="showLoginModal()">Login</button>';
                footer.innerHTML = 'Please login to access features';
            }
        }

        function showLoginModal() { document.getElementById('loginModal').classList.add('active'); }
        function hideLoginModal() { document.getElementById('loginModal').classList.remove('active'); }
        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            if (tab === 'login') { document.querySelector('.tab:first-child').classList.add('active'); document.getElementById('loginForm').style.display = 'block'; document.getElementById('signupForm').style.display = 'none'; } 
            else { document.querySelector('.tab:last-child').classList.add('active'); document.getElementById('loginForm').style.display = 'none'; document.getElementById('signupForm').style.display = 'block'; }
        }
        function loginWithEmail() { var e = document.getElementById('loginEmail').value, p = document.getElementById('loginPassword').value; if (!e || !p) return showAlert('Error', 'Enter email and password'); auth.signInWithEmailAndPassword(e, p).then(hideLoginModal).catch(err => showAlert('Error', err.message)); }
        function signupWithEmail() { var e = document.getElementById('signupEmail').value, p = document.getElementById('signupPassword').value; if (!e || !p) return showAlert('Error', 'Enter email and password'); auth.createUserWithEmailAndPassword(e, p).then(hideLoginModal).catch(err => showAlert('Error', err.message)); }
        function loginWithGoogle() { auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()).then(hideLoginModal).catch(err => showAlert('Error', err.message)); }
        function logout() { auth.signOut().then(() => { isPro = false; queriesUsed = 0; followupsUsed = 0; updateUserUI(); }); }
        function showAlert(t, m) { document.getElementById('alertTitle').textContent = t; document.getElementById('alertMessage').textContent = m; document.getElementById('alertModal').classList.add('active'); }
        function closeAlert() { document.getElementById('alertModal').classList.remove('active'); }
        
        function highlightText(text) {
            if (!text) return '';
            var colors = {'key': 'hl-key', 'solution': 'hl-solution', 'step': 'hl-step', 'important': 'hl-key'};
            var html = text;
            for (var w in colors) { html = html.replace(new RegExp('\\\\b' + w + '\\\\b', 'gi'), '<span class="hl ' + colors[w] + '">' + w + '</span>'); }
            return html;
        }
        
        function renderResults(data) {
            document.getElementById('resultSummary').innerHTML = '<p>' + highlightText(data.summary) + '</p>';
            var sections = data.sections || [];
            var html = '';
            sections.forEach(s => { html += '<div class="section-card"><h3>' + s.title + '</h3><p>' + highlightText(s.content) + '</p></div>'; });
            document.getElementById('sectionsGrid').innerHTML = html;
        }

        function runSwarm() {
            if (!isLoggedIn) { showLoginModal(); return; }
            var prompt = document.getElementById('mainPrompt').value.trim();
            if (!prompt) return showAlert('Error', 'Describe your problem');
            var depth = document.getElementById('optDepth').value;
            var category = document.getElementById('optCategory').value;
            
            if (depth === 'comprehensive' && !isPro) return showAlert('Pro Feature', 'Comprehensive guides are Pro only');
            if (!isPro && queriesUsed >= 3) return showAlert('Limit', '3 queries used. Resets at midnight');
            
            currentContext = prompt;
            document.getElementById('inputWrapper').style.display = 'none';
            document.getElementById('loader').classList.add('active');
            document.getElementById('qaList').innerHTML = '';
            
            fetch('/solve', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({prompt: prompt, mode: currentMode, category: category, depth: depth}) })
            .then(res => res.json())
            .then(data => {
                document.getElementById('loader').classList.remove('active');
                if (data.error) return showAlert('Error', data.error);
                renderResults(data);
                document.getElementById('resultsOverlay').classList.add('active');
                if (!isPro) { queriesUsed++; updateUserUI(); }
            })
            .catch(err => { document.getElementById('loader').classList.remove('active'); document.getElementById('inputWrapper').style.display = 'block'; showAlert('Error', 'Failed: ' + err.message); });
        }

        function askFollowup() {
            if (!isLoggedIn) { showLoginModal(); return; }
            var q = document.getElementById('followupInput').value.trim();
            if (!q) return;
            if (!isPro && followupsUsed >= 1) return showAlert('Limit', '1 follow-up per day for free users');
            
            var btn = document.getElementById('followupBtn');
            btn.innerHTML = 'Thinking...'; btn.disabled = true;
            document.getElementById('qaList').innerHTML += '<div class="qa-item"><div class="qa-question">Q: ' + q + '</div><div class="qa-answer" id="tempAnswer">Thinking...</div></div>';
            
            fetch('/followup', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question: q, context: currentContext, mode: currentMode}) })
            .then(res => res.json())
            .then(data => { document.getElementById('tempAnswer').innerHTML = highlightText(data.answer); document.getElementById('tempAnswer').id = ''; document.getElementById('followupInput').value = ''; btn.innerHTML = 'Ask Swarm'; btn.disabled = false; if (!isPro) followupsUsed++; })
            .catch(() => { document.getElementById('tempAnswer').innerHTML = 'Error'; btn.innerHTML = 'Ask Swarm'; btn.disabled = false; });
        }

        function analyzeYouTube() {
            if (!isLoggedIn) { showLoginModal(); return; }
            if (!isPro) return showAlert('Pro Feature', 'YouTube analysis is Pro only');
            var url = document.getElementById('youtubeUrl').value.trim();
            if (!url) return showAlert('Error', 'Enter YouTube URL');
            
            var resultDiv = document.getElementById('youtubeResult');
            resultDiv.classList.add('active');
            resultDiv.innerHTML = '<p style="color:#666;">Analyzing video...</p>';
            
            fetch('/analyze-youtube', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: url}) })
            .then(res => res.json())
            .then(data => {
                if (data.error) resultDiv.innerHTML = '<p style="color:red;">Error: ' + data.error + '</p>';
                else resultDiv.innerHTML = '<h4>Key Insights</h4><p>' + highlightText(data.analysis) + '</p>';
            })
            .catch(err => { resultDiv.innerHTML = '<p style="color:red;">Error: ' + err.message + '</p>'; });
        }

        function initiatePayment() {
            if (!isLoggedIn) { showLoginModal(); return; }
            if (!rzpKeyId) return showAlert('Error', 'Payment not configured');
            fetch('/api/create-order', {method: 'POST'}).then(r => r.json()).then(order => {
                var options = { key: rzpKeyId, amount: order.amount, currency: order.currency, name: 'Winy AI', order_id: order.order_id,
                    handler: function(response) {
                        fetch('/api/verify-payment', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(response) })
                        .then(r => r.json()).then(data => {
                            if (data.status === 'success') { isPro = true; queriesUsed = 0; followupsUsed = 0; updateUserUI(); showAlert('Welcome to Pro!', 'Unlimited access activated'); } 
                            else { showAlert('Failed', 'Verification failed'); }
                        });
                    }, theme: {color: '#000000'} };
                new Razorpay(options).open();
            }).catch(() => showAlert('Error', 'Payment failed'));
        }

        function closeResultsOverlay() { document.getElementById('resultsOverlay').classList.remove('active'); document.getElementById('inputWrapper').style.display = 'block'; }
        updateUserUI();
    </script>
</body>
</html>
'''

# ==============================================================================
# ROUTES
# ==============================================================================

@app.route('/')
def home():
    today = get_today()
    if 'is_pro' not in session: session['is_pro'] = False
    if 'queries_count' not in session: session['queries_count'] = 0
    if 'followups_count' not in session: session['followups_count'] = 0
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/solve', methods=['POST'])
@require_auth
def solve():
    """Solve any problem using AI swarm."""
    client_ip = get_client_ip()
    firebase_uid = session['firebase_uid']
    today = get_today()
    
    # Check limits
    if client_ip not in ip_usage_tracker:
        ip_usage_tracker[client_ip] = {'count': 0, 'date': today}
    if ip_usage_tracker[client_ip]['date'] != today:
        ip_usage_tracker[client_ip] = {'count': 0, 'date': today}
        
    if not session.get('is_pro'):
        if session.get('queries_count', 0) >= 3 or ip_usage_tracker[client_ip]['count'] >= 3:
            return jsonify({"error": "Daily limit reached (3 queries). Resets at midnight."}), 403
    
    data = request.json
    prompt = data.get('prompt', '')
    mode = data.get('mode', 'problem')
    category = data.get('category', 'General')
    depth = data.get('depth', 'detailed')
    
    if not prompt or len(prompt) < 10:
        return jsonify({"error": "Please provide more details (at least 10 characters)."}), 400
        
    if depth == 'comprehensive' and not session.get('is_pro'):
        return jsonify({"error": "Comprehensive guides are Pro-only."}), 403
    
    # Dynamic prompts based on mode
    if mode == 'problem':
        system_prompt = f"""You are an expert problem-solver. Break down this problem systematically.
        Problem: "{prompt}"
        Category: {category}
        
        Return ONLY JSON with these keys:
        {{
          "summary": "Brief overview of the problem and approach",
          "sections": [
            {{"title": "Root Cause Analysis", "content": "Detailed analysis"}},
            {{"title": "Key Challenges", "content": "Main obstacles"}},
            {{"title": "Solution Steps", "content": "Step-by-step actionable solutions"}},
            {{"title": "Resources Needed", "content": "Tools, time, skills required"}},
            {{"title": "Expected Outcomes", "content": "What to expect"}}
          ]
        }}"""
    elif mode == 'business':
        system_prompt = f"""You are a business consultant.
        Idea: "{prompt}"
        Industry: {category}
        
        Return JSON:
        {{
          "summary": "Executive summary",
          "sections": [
            {{"title": "Market Opportunity", "content": "Market size and trends"}},
            {{"title": "Business Model", "content": "How to make money"}},
            {{"title": "Go-to-Market", "content": "Launch strategy"}},
            {{"title": "Financial Projections", "content": "Costs and revenue"}},
            {{"title": "Key Milestones", "content": "Timeline and goals"}}
          ]
        }}"""
    else:  # learning
        system_prompt = f"""You are an expert teacher. Explain this topic clearly.
        Topic: "{prompt}"
        Category: {category}
        
        Return JSON:
        {{
          "summary": "What this is about",
          "sections": [
            {{"title": "Core Concepts", "content": "Fundamental ideas"}},
            {{"title": "How It Works", "content": "Mechanisms and processes"}},
            {{"title": "Key Principles", "content": "Important rules/laws"}},
            {{"title": "Practical Examples", "content": "Real-world applications"}},
            {{"title": "Next Steps", "content": "How to learn more"}}
          ]
        }}"""
    
    try:
        raw = call_groq_llm(system_prompt, prompt, temperature=0.7)
        parsed = parse_json_response(raw)
        
        if not parsed:
            return jsonify({"error": "AI formatting error. Try again."}), 500
        
        # Save to DB
        conn = get_db_connection()
        conn.execute('''INSERT INTO query_history (firebase_uid, query_type, query_text, result_json)
                       VALUES (?, ?, ?, ?)''', (firebase_uid, mode, prompt, json.dumps(parsed)))
        
        if not session.get('is_pro'):
            session['queries_count'] = session.get('queries_count', 0) + 1
            ip_usage_tracker[client_ip]['count'] += 1
            conn.execute('''INSERT INTO daily_usage (firebase_uid, ip_address, usage_date, queries_count, followups_count)
                           VALUES (?, ?, ?, 1, 0)
                           ON CONFLICT(firebase_uid, usage_date) 
                           DO UPDATE SET queries_count = daily_usage.queries_count + 1''', 
                        (firebase_uid, client_ip, today))
        conn.commit()
        conn.close()
        
        return jsonify(parsed)
    except Exception as e:
        logger.error(f"Solve error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/followup', methods=['POST'])
@require_auth
def followup():
    if 'firebase_uid' not in session:
        return jsonify({"error": "Authentication required"}), 401
        
    if not session.get('is_pro'):
        if session.get('followups_count', 0) >= 1:
            return jsonify({"error": "Follow-up limit reached (1/day)"}), 403
    
    data = request.json
    question = data.get('question', '')
    context = data.get('context', '')
    mode = data.get('mode', 'problem')
    
    system_prompt = f"Context: {mode} - {context}. Answer concisely: {question}"
    answer = call_groq_llm(system_prompt, question, temperature=0.5)
    
    if not session.get('is_pro'):
        session['followups_count'] = session.get('followups_count', 0) + 1
    
    return jsonify({"answer": answer})

@app.route('/analyze-youtube', methods=['POST'])
@require_auth
def analyze_youtube():
    if not session.get('is_pro'):
        return jsonify({"error": "Pro feature"}), 403
        
    data = request.json
    url = data.get('url', '')
    
    transcript, error = get_youtube_transcript(url)
    if error:
        return jsonify({"error": error}), 400
    
    analysis_prompt = f"Analyze this video transcript and extract key insights, main points, and actionable takeaways:\n{transcript[:15000]}"
    analysis = call_groq_llm("You are an expert analyst. Summarize and extract insights.", analysis_prompt, temperature=0.5)
    
    return jsonify({"analysis": analysis, "transcript": transcript[:500] + "..."})

@app.route('/api/create-order', methods=['POST'])
@require_auth
def create_order():
    if not razorpay_client:
        return jsonify({"error": "Payment not configured"}), 500
    try:
        order = razorpay_client.order.create({"amount": 49900, "currency": "INR", "receipt": f"rcpt_{uuid.uuid4().hex[:16]}", "payment_capture": 1})
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
@require_auth
def verify_payment():
    data = request.json
    order_id = data.get('razorpay_order_id', '')
    payment_id = data.get('razorpay_payment_id', '')
    signature = data.get('razorpay_signature', '')
    
    if not all([order_id, payment_id, signature]):
        return jsonify({"status": "failure"}), 400
    
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    
    if expected == signature:
        firebase_uid = session['firebase_uid']
        pro_expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        conn.execute('''INSERT INTO users (firebase_uid, email, is_pro, pro_expiry)
                       VALUES (?, ?, 1, ?)
                       ON CONFLICT(firebase_uid) 
                       DO UPDATE SET is_pro = 1, pro_expiry = ?''', 
                    (firebase_uid, session.get('email', ''), pro_expiry, pro_expiry))
        conn.commit()
        conn.close()
        
        session['is_pro'] = True
        session['queries_count'] = 0
        session['followups_count'] = 0
        
        return jsonify({"status": "success"})
    return jsonify({"status": "failure"}), 400

if __name__ == '__main__':
    logger.info("Starting Winy AI...")
    app.run(host='0.0.0.0', port=5000, debug=False)
