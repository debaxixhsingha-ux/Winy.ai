"""
Winy AI - Pure B&W Glass Chatbot
Streaming, Memory, History, Auth, Responsive
"""
import os, json, hmac, hashlib, sqlite3, logging, uuid, base64
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, session, Response, stream_with_context
import requests as http_requests
import razorpay

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "winy-secret-change-me")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID else None

# ============================================================================
# DATABASE
# ============================================================================
def init_db():
    conn = sqlite3.connect('winy.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT UNIQUE NOT NULL, email TEXT,
        is_pro INTEGER DEFAULT 0, pro_expiry DATE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL, title TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(conversation_id) REFERENCES conversations(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL, usage_date DATE NOT NULL,
        message_count INTEGER DEFAULT 0,
        UNIQUE(firebase_uid, usage_date)
    )''')
    conn.commit(); conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('winy.db')
    conn.row_factory = sqlite3.Row
    return conn

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'firebase_uid' not in session:
            return jsonify({"error": "Auth required"}), 401
        return f(*args, **kwargs)
    return decorated

# ============================================================================
# STREAMING ENGINE
# ============================================================================
SYSTEM_PROMPT = """You are Winy AI. You are helpful, precise, and articulate.
You can discuss any topic. Be direct. Use markdown when helpful.
Never mention being an AI unless asked."""

SWARM_PROMPT = """You are Winy AI in SWARM MODE. Deploy multiple expert perspectives.
For every response analyze: Root Cause, Strategic Options, Risks, Action Steps.
Be thorough, structured, and exceptionally insightful. Use markdown headers and lists."""

def stream_groq(messages):
    try:
        resp = http_requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-8b-instant", "messages": messages,
                  "stream": True, "max_tokens": 4096, "temperature": 0.7},
            stream=True, timeout=120)
        for line in resp.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith('data: ') and decoded != 'data: [DONE]':
                    try:
                        chunk = json.loads(decoded[6:])
                        content = chunk['choices'][0].get('delta', {}).get('content', '')
                        if content:
                            yield f"data: {json.dumps({'token': content})}\n\n"
                    except: pass
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# ============================================================================
# HTML TEMPLATE - PURE B&W GLASS
# ============================================================================
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Winy AI</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#050505;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e8e8e8;height:100vh;display:flex;overflow:hidden}

/* ORBS - WHITE ONLY */
.orb{position:absolute;border-radius:50%;filter:blur(100px);pointer-events:none;z-index:0}
.orb-1{width:400px;height:400px;background:radial-gradient(circle,rgba(255,255,255,0.07) 0%,transparent 70%);top:-150px;left:-100px;animation:drift1 12s ease-in-out infinite}
.orb-2{width:300px;height:300px;background:radial-gradient(circle,rgba(255,255,255,0.05) 0%,transparent 70%);bottom:-80px;right:-80px;animation:drift2 15s ease-in-out infinite reverse}
.orb-3{width:200px;height:200px;background:radial-gradient(circle,rgba(255,255,255,0.04) 0%,transparent 70%);top:50%;left:50%;animation:drift3 18s ease-in-out infinite 3s}
@keyframes drift1{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(40px,-30px) scale(1.08)}66%{transform:translate(-20px,20px) scale(0.95)}}
@keyframes drift2{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(-30px,25px) scale(1.05)}66%{transform:translate(25px,-15px) scale(0.92)}}
@keyframes drift3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(15px,-25px) scale(1.1)}}

/* SIDEBAR */
.sidebar{width:260px;background:rgba(255,255,255,0.03);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);border-right:1px solid rgba(255,255,255,0.06);display:flex;flex-direction:column;z-index:20;transition:transform 0.3s ease;flex-shrink:0}
.sidebar-header{padding:20px;border-bottom:1px solid rgba(255,255,255,0.06)}
.sidebar-logo{font-size:18px;font-weight:700;letter-spacing:-0.5px;color:#fff}
.new-chat-btn{width:calc(100% - 32px);margin:16px auto 8px;padding:12px;background:rgba(255,255,255,0.08);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.1);border-radius:12px;color:#fff;font-size:13px;font-weight:600;cursor:pointer;transition:all 0.3s;text-align:center}
.new-chat-btn:hover{background:rgba(255,255,255,0.15);border-color:rgba(255,255,255,0.2)}
.history-list{flex:1;overflow-y:auto;padding:8px}
.history-item{padding:10px 14px;border-radius:10px;cursor:pointer;font-size:13px;color:rgba(255,255,255,0.4);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:all 0.2s;margin-bottom:2px}
.history-item:hover,.history-item.active{background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.9)}
.sidebar-footer{padding:16px;border-top:1px solid rgba(255,255,255,0.06)}
.user-row{display:flex;align-items:center;gap:10px}
.user-email{font-size:12px;color:rgba(255,255,255,0.5);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pro-pill{font-size:9px;font-weight:700;background:#fff;color:#000;padding:2px 8px;border-radius:100px;letter-spacing:0.5px}
.sidebar-btn{background:none;border:none;color:rgba(255,255,255,0.4);cursor:pointer;font-size:11px;padding:4px 8px;border-radius:6px;transition:all 0.2s}
.sidebar-btn:hover{color:#fff;background:rgba(255,255,255,0.08)}

/* MAIN CHAT */
.chat-main{flex:1;display:flex;flex-direction:column;position:relative;z-index:10;min-width:0}

/* HEADER */
.header{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-bottom:1px solid rgba(255,255,255,0.04);flex-shrink:0;background:rgba(5,5,5,0.5);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.header-left{display:flex;align-items:center;gap:12px}
.menu-toggle{display:none;background:none;border:1px solid rgba(255,255,255,0.08);width:36px;height:36px;border-radius:10px;color:rgba(255,255,255,0.5);cursor:pointer;align-items:center;justify-content:center;font-size:16px;transition:all 0.2s}
.menu-toggle:hover{background:rgba(255,255,255,0.06);color:#fff}
.model-selector{position:relative}
.model-pill{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.08);padding:8px 16px;border-radius:20px;cursor:pointer;transition:all 0.3s;user-select:none}
.model-pill:hover{background:rgba(255,255,255,0.1);border-color:rgba(255,255,255,0.15)}
.model-name{font-weight:600;font-size:13px;color:#e8e8e8}
.model-arrow{font-size:9px;color:rgba(255,255,255,0.3);transition:transform 0.2s}
.model-pill.open .model-arrow{transform:rotate(180deg)}
.model-dropdown{position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%);background:rgba(15,15,15,0.95);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);border:1px solid rgba(255,255,255,0.1);border-radius:14px;padding:6px;min-width:190px;display:none;z-index:100;box-shadow:0 12px 40px rgba(0,0,0,0.5)}
.model-dropdown.active{display:block;animation:dropIn 0.2s ease}
@keyframes dropIn{from{opacity:0;transform:translateX(-50%) translateY(-8px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
.dd-item{padding:10px 14px;border-radius:10px;cursor:pointer;font-size:13px;color:rgba(255,255,255,0.5);transition:all 0.15s;display:flex;align-items:center;justify-content:space-between}
.dd-item:hover{background:rgba(255,255,255,0.08);color:#fff}
.dd-item.selected{color:#fff;background:rgba(255,255,255,0.08)}
.dd-item.selected::after{content:'✓';font-size:11px}
.dd-tag{font-size:8px;font-weight:700;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.4);letter-spacing:0.5px}
.dd-item.selected .dd-tag{background:rgba(255,255,255,0.2);color:#fff}
.header-status{display:flex;align-items:center;gap:6px;font-size:11px;color:rgba(255,255,255,0.3)}
.status-dot{width:6px;height:6px;background:#fff;border-radius:50%;opacity:0.6;animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:0.6;transform:scale(1)}50%{opacity:0.3;transform:scale(0.85)}}

/* MESSAGES */
.messages{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:20px}
.empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:16px;opacity:0.4}
.empty-icon{width:64px;height:64px;border:1px solid rgba(255,255,255,0.1);border-radius:16px;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(20px)}
.empty-icon svg{stroke:rgba(255,255,255,0.3);width:28px;height:28px}
.empty-state span{color:rgba(255,255,255,0.3);font-size:14px;font-weight:500}

.msg-row{display:flex;gap:0;align-items:flex-start;animation:slideUp 0.4s cubic-bezier(0.22,1,0.36,1)}
.msg-row.user{flex-direction:row-reverse}
@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

.msg-wrap{max-width:78%;min-width:60px}
.msg-bubble{backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);padding:14px 18px;position:relative;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.2)}
.msg-bubble.ai{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);border-radius:18px 18px 18px 4px}
.msg-bubble.user{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.15);border-radius:18px 18px 4px 18px}
.msg-shine{position:absolute;top:0;left:0;right:0;height:1px}
.msg-shine.ai{background:linear-gradient(90deg,transparent,rgba(255,255,255,0.12),transparent)}
.msg-shine.user{background:linear-gradient(90deg,transparent,rgba(255,255,255,0.2),transparent)}
.msg-text{margin:0;line-height:1.7;font-size:14px}
.msg-text.ai{color:rgba(255,255,255,0.8)}
.msg-text.user{color:rgba(255,255,255,0.95)}
.msg-text p{margin-bottom:10px}.msg-text p:last-child{margin-bottom:0}
.msg-text code{background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:4px;font-size:12px;font-family:'SF Mono',Monaco,monospace}
.msg-text pre{background:rgba(255,255,255,0.05);padding:14px;border-radius:10px;overflow-x:auto;margin:10px 0;font-size:12px;line-height:1.5;border:1px solid rgba(255,255,255,0.06)}
.msg-text pre code{background:none;padding:0}
.msg-text strong{color:#fff;font-weight:700}
.msg-text ul,.msg-text ol{padding-left:20px;margin:8px 0}
.msg-text li{margin-bottom:4px}
.msg-text h3,.msg-text h4{color:#fff;margin:14px 0 6px;font-size:15px}
.msg-time{font-size:10px;color:rgba(255,255,255,0.15);margin-top:5px}
.msg-time.user{text-align:right;margin-right:4px}
.msg-time.ai{margin-left:4px}

/* TYPING ANIMATION - REDESIGNED */
.typing-bubble{background:rgba(255,255,255,0.04);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid rgba(255,255,255,0.07);padding:16px 22px;border-radius:18px 18px 18px 4px;box-shadow:0 8px 32px rgba(0,0,0,0.2);display:flex;align-items:center;gap:6px}
.typing-bar{width:3px;height:14px;background:rgba(255,255,255,0.4);border-radius:2px;animation:typingWave 1.2s ease-in-out infinite}
.typing-bar:nth-child(1){animation-delay:0s;height:10px}
.typing-bar:nth-child(2){animation-delay:0.15s;height:16px}
.typing-bar:nth-child(3){animation-delay:0.3s;height:12px}
.typing-bar:nth-child(4){animation-delay:0.45s;height:18px}
.typing-bar:nth-child(5){animation-delay:0.6s;height:8px}
@keyframes typingWave{0%,100%{transform:scaleY(0.5);opacity:0.3}50%{transform:scaleY(1);opacity:0.8}}

.cursor{display:inline-block;width:2px;height:15px;background:rgba(255,255,255,0.7);margin-left:2px;animation:blink 0.8s infinite;vertical-align:middle}
@keyframes blink{0%,50%{opacity:1}51%,100%{opacity:0}}

/* INPUT */
.input-area{padding:14px 24px 22px;position:relative;z-index:10;flex-shrink:0}
.input-wrapper{display:flex;align-items:flex-end;gap:10px;background:rgba(255,255,255,0.03);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);border:1px solid rgba(255,255,255,0.06);border-radius:22px;padding:5px 5px 5px 18px;box-shadow:0 4px 24px rgba(0,0,0,0.15),inset 0 1px 0 rgba(255,255,255,0.02);transition:all 0.3s}
.input-wrapper:focus-within{border-color:rgba(255,255,255,0.15);box-shadow:0 4px 30px rgba(255,255,255,0.04),inset 0 1px 0 rgba(255,255,255,0.03)}
.input-field{flex:1;background:transparent;border:none;outline:none;color:rgba(255,255,255,0.9);font-size:15px;line-height:1.5;max-height:120px;min-height:24px;font-family:inherit;padding:11px 0;resize:none}
.input-field::placeholder{color:rgba(255,255,255,0.2)}
.send-btn{background:rgba(255,255,255,0.1);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.15);width:40px;height:40px;border-radius:50%;cursor:pointer;color:rgba(255,255,255,0.9);display:flex;align-items:center;justify-content:center;transition:all 0.3s;flex-shrink:0}
.send-btn:hover{background:rgba(255,255,255,0.2);box-shadow:0 0 20px rgba(255,255,255,0.08)}
.send-btn:disabled{opacity:0.2;cursor:not-allowed}
.send-btn svg{stroke:currentColor;width:18px;height:18px}
.input-hint{text-align:center;margin-top:10px;font-size:10px;color:rgba(255,255,255,0.1);letter-spacing:0.5px}
.limit-banner{text-align:center;padding:8px;font-size:11px;color:rgba(255,255,255,0.3)}
.limit-banner span{color:#fff;font-weight:600;cursor:pointer;text-decoration:underline}

/* LOGIN GATE */
.login-gate{position:fixed;inset:0;background:#050505;z-index:500;display:flex;align-items:center;justify-content:center;padding:20px}
.login-gate.hidden{display:none}
.gate-card{background:rgba(255,255,255,0.03);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);border:1px solid rgba(255,255,255,0.08);border-radius:24px;padding:40px;max-width:400px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.4)}
.gate-card h1{font-size:28px;font-weight:700;margin-bottom:6px;color:#fff;letter-spacing:-0.5px}
.gate-card .sub{color:rgba(255,255,255,0.35);font-size:14px;margin-bottom:32px}
.m-input{width:100%;padding:14px 16px;border:1px solid rgba(255,255,255,0.08);border-radius:12px;font-size:14px;margin-bottom:12px;outline:none;background:rgba(255,255,255,0.03);color:#fff;font-family:inherit;backdrop-filter:blur(10px)}
.m-input:focus{border-color:rgba(255,255,255,0.2)}
.m-input::placeholder{color:rgba(255,255,255,0.2)}
.m-btn{width:100%;padding:14px;border:none;border-radius:12px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;transition:all 0.3s}
.m-btn-primary{background:#fff;color:#000}
.m-btn-primary:hover{opacity:0.9;box-shadow:0 0 20px rgba(255,255,255,0.15)}
.m-btn-secondary{background:transparent;border:1px solid rgba(255,255,255,0.1);color:#e8e8e8;margin-top:10px}
.m-btn-secondary:hover{background:rgba(255,255,255,0.05);border-color:rgba(255,255,255,0.2)}
.m-divider{display:flex;align-items:center;gap:12px;margin:20px 0;color:rgba(255,255,255,0.15);font-size:11px}
.m-divider::before,.m-divider::after{content:'';flex:1;height:1px;background:rgba(255,255,255,0.06)}
.auth-toggle{margin-top:16px;font-size:12px;color:rgba(255,255,255,0.3);cursor:pointer;transition:color 0.2s}
.auth-toggle:hover{color:rgba(255,255,255,0.6)}

/* ALERT MODAL */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);backdrop-filter:blur(10px);z-index:600;align-items:center;justify-content:center}
.modal-overlay.active{display:flex}
.modal-card{background:rgba(15,15,15,0.95);backdrop-filter:blur(30px);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:32px;max-width:380px;width:90%;text-align:center}
.modal-card h2{font-size:18px;margin-bottom:8px;color:#fff}
.modal-card p{color:rgba(255,255,255,0.5);font-size:13px;margin-bottom:24px;line-height:1.5}

::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.06);border-radius:3px}

@media(max-width:768px){
  .sidebar{position:fixed;left:0;top:0;bottom:0;transform:translateX(-100%);z-index:200;width:280px}
  .sidebar.open{transform:translateX(0)}
  .menu-toggle{display:flex}
  .msg-wrap{max-width:88%}
  .gate-card{padding:28px}
  .gate-card h1{font-size:24px}
  .header{padding:12px 16px}
  .messages{padding:16px}
  .input-area{padding:12px 16px 18px}
}
.sidebar-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:150}
.sidebar-overlay.active{display:block}
</style>
</head>
<body>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="orb orb-3"></div>

<!-- LOGIN GATE -->
<div class="login-gate" id="loginGate">
  <div class="gate-card">
    <h1>Winy AI</h1>
    <p class="sub">Sign in to start chatting</p>
    <div id="gateLoginForm">
      <input type="email" class="m-input" id="gLoginEmail" placeholder="Email address">
      <input type="password" class="m-input" id="gLoginPass" placeholder="Password">
      <button class="m-btn m-btn-primary" onclick="gateLogin()">Sign In</button>
    </div>
    <div id="gateSignupForm" style="display:none">
      <input type="email" class="m-input" id="gSignupEmail" placeholder="Email address">
      <input type="password" class="m-input" id="gSignupPass" placeholder="Create password (6+ chars)">
      <button class="m-btn m-btn-primary" onclick="gateSignup()">Create Account</button>
    </div>
    <div class="m-divider">or</div>
    <button class="m-btn m-btn-secondary" onclick="gateGoogle()">Continue with Google</button>
    <p class="auth-toggle" id="gateToggle" onclick="toggleGate()">Don't have an account? Sign up</p>
  </div>
</div>

<!-- SIDEBAR OVERLAY (mobile) -->
<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>

<!-- SIDEBAR -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-header"><div class="sidebar-logo">Winy AI</div></div>
  <button class="new-chat-btn" onclick="newChat()">+ New Chat</button>
  <div class="history-list" id="historyList"></div>
  <div class="sidebar-footer" id="sidebarFooter"></div>
</aside>

<!-- MAIN -->
<main class="chat-main">
  <div class="header">
    <div class="header-left">
      <button class="menu-toggle" onclick="toggleSidebar()">☰</button>
      <div class="model-selector">
        <div class="model-pill" id="modelPill" onclick="toggleDropdown()">
          <span class="model-name" id="modelName">Winy 1.1</span>
          <span class="model-arrow">▼</span>
        </div>
        <div class="model-dropdown" id="modelDD">
          <div class="dd-item selected" onclick="selectModel('winy11','Winy 1.1')" data-m="winy11">Winy 1.1<span class="dd-tag">FAST</span></div>
          <div class="dd-item" onclick="selectModel('swarm','Swarm Mode')" data-m="swarm">Swarm Mode<span class="dd-tag">DEEP</span></div>
        </div>
      </div>
    </div>
    <div class="header-status"><span class="status-dot"></span>Online</div>
  </div>

  <div class="messages" id="messages">
    <div class="empty-state" id="emptyState">
      <div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
      <span>Ask anything to begin</span>
    </div>
  </div>

  <div class="input-area">
    <div class="limit-banner" id="limitBanner" style="display:none"></div>
    <div class="input-wrapper">
      <textarea class="input-field" id="msgInput" placeholder="Type your message..." rows="1"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>
    <div class="input-hint">Winy AI may produce inaccurate information</div>
  </div>
</main>

<!-- ALERT MODAL -->
<div class="modal-overlay" id="alertModal">
  <div class="modal-card">
    <h2 id="alertTitle">Notice</h2>
    <p id="alertMsg">Message</p>
    <button class="m-btn m-btn-primary" onclick="closeAlert()">OK</button>
  </div>
</div>

<script>
const fb={apiKey:"AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU",authDomain:"winy-3984d.firebaseapp.com",projectId:"winy-3984d",storageBucket:"winy-3984d.firebasestorage.app",messagingSenderId:"126237613814",appId:"1:126237613814:web:e3cb88222d920545a416d7"};
firebase.initializeApp(fb);const auth=firebase.auth();

let currentUser=null,isPro=false,msgCount=0,convId=null,isStreaming=false,currentModel='winy11',isGateLogin=true;
const rzpKey={{ razorpay_key_id | tojson }};

// AUTH
auth.onAuthStateChanged(u=>{
  currentUser=u;
  if(u){document.getElementById('loginGate').classList.add('hidden');syncSession().then(()=>{loadState();updateSidebar();loadHistory()})}
  else{document.getElementById('loginGate').classList.remove('hidden');resetUI()}
});

async function syncSession(){
  try{const t=await currentUser.getIdToken();await fetch('/api/auth-sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t,email:currentUser.email})})}catch(e){console.error(e)}
}
function loadState(){fetch('/api/user-state').then(r=>r.json()).then(d=>{isPro=d.is_pro;msgCount=d.msg_count||0;updateLimit()}).catch(()=>{})}
function updateSidebar(){
  const f=document.getElementById('sidebarFooter');if(!currentUser)return;
  f.innerHTML=`<div class="user-row"><span class="user-email">${currentUser.email}</span>${isPro?'<span class="pro-pill">PRO</span>':''}<button class="sidebar-btn" onclick="doLogout()">Logout</button></div>`;
}
function resetUI(){document.getElementById('sidebarFooter').innerHTML='';document.getElementById('historyList').innerHTML='';newChat()}

// GATE
function toggleGate(){isGateLogin=!isGateLogin;document.getElementById('gateLoginForm').style.display=isGateLogin?'block':'none';document.getElementById('gateSignupForm').style.display=isGateLogin?'none':'block';document.getElementById('gateToggle').textContent=isGateLogin?"Don't have an account? Sign up":"Already have an account? Sign in"}
function gateLogin(){const e=document.getElementById('gLoginEmail').value,p=document.getElementById('gLoginPass').value;if(!e||!p)return showAlert('Error','Fill all fields');auth.signInWithEmailAndPassword(e,p).catch(err=>showAlert('Error',err.message))}
function gateSignup(){const e=document.getElementById('gSignupEmail').value,p=document.getElementById('gSignupPass').value;if(!e||!p)return showAlert('Error','Fill all fields');if(p.length<6)return showAlert('Error','Min 6 chars');auth.createUserWithEmailAndPassword(e,p).catch(err=>showAlert('Error',err.message))}
function gateGoogle(){auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()).catch(err=>showAlert('Error',err.message))}
function doLogout(){auth.signOut();isPro=false;msgCount=0}

// SIDEBAR
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open');document.getElementById('sidebarOverlay').classList.toggle('active')}
function loadHistory(){
  fetch('/api/conversations').then(r=>r.json()).then(d=>{
    const l=document.getElementById('historyList');l.innerHTML='';
    (d.conversations||[]).forEach(c=>{const div=document.createElement('div');div.className='history-item'+(c.id===convId?' active':'');div.textContent=c.title||'Untitled';div.onclick=()=>loadConv(c.id);l.appendChild(div)})
  }).catch(()=>{})
}
function loadConv(id){
  convId=id;fetch('/api/conversations/'+id+'/messages').then(r=>r.json()).then(d=>{
    const c=document.getElementById('messages');c.innerHTML='';
    (d.messages||[]).forEach(m=>appendMsg(m.role,m.content,false));scrollToBottom();
    document.querySelectorAll('.history-item').forEach(i=>i.classList.remove('active'));
    if(window.innerWidth<=768)toggleSidebar();
  }).catch(()=>{})
}

// MODEL
function toggleDropdown(){document.getElementById('modelDD').classList.toggle('active');document.getElementById('modelPill').classList.toggle('open')}
function selectModel(m,n){currentModel=m;document.getElementById('modelName').textContent=n;document.querySelectorAll('.dd-item').forEach(i=>i.classList.remove('selected'));document.querySelector(`[data-m="${m}"]`).classList.add('selected');toggleDropdown()}
document.addEventListener('click',e=>{if(!e.target.closest('.model-selector')){document.getElementById('modelDD').classList.remove('active');document.getElementById('modelPill').classList.remove('open')}});

// CHAT
function newChat(){convId=null;document.getElementById('messages').innerHTML='<div class="empty-state" id="emptyState"><div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><span>Ask anything to begin</span></div>'}
function getTime(){return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}

function renderMD(t){
  if(!t)return'';let h=t.replace(/```(\w*)\n([\s\S]*?)```/g,'<pre><code>$2</code></pre>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\*(.+?)\*/g,'<em>$1</em>').replace(/^#### (.+)$/gm,'<h4>$1</h4>').replace(/^### (.+)$/gm,'<h4>$1</h4>').replace(/^## (.+)$/gm,'<h3>$1</h3>').replace(/^- (.+)$/gm,'<li>$1</li>').replace(/(<li>.*<\/li>)/gs,'<ul>$1</ul>').replace(/\n\n/g,'</p><p>').replace(/\n/g,'<br>');return'<p>'+h+'</p>'
}

function appendMsg(role,content,animate=true){
  const c=document.getElementById('messages');const e=document.getElementById('emptyState');if(e)e.remove();
  const d=document.createElement('div');d.className=`msg-row ${role}`;if(!animate)d.style.animation='none';
  const shine=role==='ai'?'msg-shine ai':'msg-shine user';
  const timeClass=role==='ai'?'msg-time ai':'msg-time user';
  d.innerHTML=`<div class="msg-wrap"><div class="msg-bubble ${role}"><div class="${shine}"></div><div class="msg-text ${role}">${renderMD(content)}</div></div><div class="${timeClass}">${getTime()}</div></div>`;
  c.appendChild(d);return d;
}

async function sendMessage(){
  if(isStreaming||!currentUser)return;
  const input=document.getElementById('msgInput');const text=input.value.trim();
  if(!text)return;if(!isPro&&msgCount>=10){updateLimit();return}
  const empty=document.getElementById('emptyState');if(empty)empty.remove();

  // User msg
  const uRow=document.createElement('div');uRow.className='msg-row user';
  uRow.innerHTML=`<div class="msg-wrap"><div class="msg-bubble user"><div class="msg-shine user"></div><div class="msg-text user">${text.replace(/</g,'&lt;')}</div></div><div class="msg-time user">${getTime()}</div></div>`;
  document.getElementById('messages').appendChild(uRow);
  input.value='';autoResize();updateSendBtn();scrollToBottom();

  // Typing indicator
  const tRow=document.createElement('div');tRow.className='msg-row';tRow.id='typingRow';
  tRow.innerHTML=`<div class="msg-wrap"><div class="typing-bubble"><div class="typing-bar"></div><div class="typing-bar"></div><div class="typing-bar"></div><div class="typing-bar"></div><div class="typing-bar"></div></div></div>`;
  document.getElementById('messages').appendChild(tRow);scrollToBottom();
  isStreaming=true;updateSendBtn();

  await new Promise(r=>setTimeout(r,500));

  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,conversation_id:convId,model:currentModel})});
    const reader=resp.body.getReader();const dec=new TextDecoder();let full='';
    let aiRow=null;

    while(true){
      const{done,value}=await reader.read();if(done)break;
      const chunk=dec.decode(value,{stream:true});
      for(const line of chunk.split('\n')){
        if(line.startsWith('data: ')){
          const data=line.slice(6);
          if(data==='[DONE]'){
            if(aiRow){const b=aiRow.querySelector('.msg-text');b.innerHTML=renderMD(full)}
            isStreaming=false;msgCount++;updateLimit();updateSendBtn();loadHistory();return;
          }
          try{
            const p=JSON.parse(data);
            if(p.token){
              full+=p.token;
              if(!aiRow){const tr=document.getElementById('typingRow');if(tr)tr.remove();aiRow=appendMsg('ai','',true);const b=aiRow.querySelector('.msg-text');b.innerHTML='<span class="cursor"></span>'}
              const b=aiRow.querySelector('.msg-text');b.innerHTML=renderMD(full)+'<span class="cursor"></span>';scrollToBottom();
            }else if(p.conv_id){convId=p.conv_id}
            else if(p.error){const tr=document.getElementById('typingRow');if(tr)tr.remove();appendMsg('ai','⚠ '+p.error);isStreaming=false;updateSendBtn();return}
          }catch(e){}
        }
      }
    }
  }catch(err){const tr=document.getElementById('typingRow');if(tr)tr.remove();appendMsg('ai','Connection error. Try again.')}
  isStreaming=false;updateSendBtn();
}

// INPUT
const msgInput=document.getElementById('msgInput');
msgInput.addEventListener('input',()=>{autoResize();updateSendBtn()});
msgInput.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});
function autoResize(){msgInput.style.height='auto';msgInput.style.height=Math.min(msgInput.scrollHeight,120)+'px'}
function updateSendBtn(){document.getElementById('sendBtn').disabled=!msgInput.value.trim()||isStreaming}
function scrollToBottom(){const c=document.getElementById('messages');c.scrollTop=c.scrollHeight}

function updateLimit(){
  const b=document.getElementById('limitBanner');if(!currentUser||isPro){b.style.display='none';return}
  const r=Math.max(0,10-msgCount);
  if(r<=3){b.style.display='block';b.innerHTML=r>0?`${r} messages left today. <span onclick="upgrade()">Upgrade to Pro</span>`:`Limit reached. <span onclick="upgrade()">Upgrade to Pro</span> for unlimited.`}
  else b.style.display='none';
}

function upgrade(){
  if(!rzpKey)return showAlert('Error','Payment not configured');
  fetch('/api/create-order',{method:'POST'}).then(r=>r.json()).then(o=>{
    new Razorpay({key:rzpKey,amount:o.amount,currency:o.currency,name:'Winy AI',description:'Pro Unlimited',order_id:o.order_id,
      handler:function(res){fetch('/api/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(res)}).then(r=>r.json()).then(d=>{if(d.status==='success'){isPro=true;msgCount=0;updateLimit();updateSidebar();showAlert('Welcome!','Pro activated.')}else showAlert('Failed','Verification failed.')})},
      theme:{color:'#ffffff'}}).open()
  }).catch(()=>showAlert('Error','Payment error'))
}

function showAlert(t,m){document.getElementById('alertTitle').textContent=t;document.getElementById('alertMsg').textContent=m;document.getElementById('alertModal').classList.add('active')}
function closeAlert(){document.getElementById('alertModal').classList.remove('active')}

newChat();
</script>
</body>
</html>
'''

# ============================================================================
# ROUTES
# ============================================================================
@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/api/auth-sync', methods=['POST'])
def auth_sync():
    data = request.json
    email = data.get('email', '')
    token = data.get('token', '')
    if not email or not token:
        return jsonify({"error": "Missing data"}), 400
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.b64decode(payload))
        uid = decoded.get('user_id', decoded.get('sub', ''))
    except:
        uid = hashlib.sha256(email.encode()).hexdigest()[:28]
    session['firebase_uid'] = uid
    session['email'] = email
    conn = get_db()
    if not conn.execute("SELECT id FROM users WHERE firebase_uid=?", (uid,)).fetchone():
        conn.execute("INSERT INTO users (firebase_uid, email) VALUES (?, ?)", (uid, email))
        conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/user-state')
@require_auth
def user_state():
    uid = session['firebase_uid']
    today = date.today().isoformat()
    conn = get_db()
    user = conn.execute("SELECT is_pro FROM users WHERE firebase_uid=?", (uid,)).fetchone()
    usage = conn.execute("SELECT message_count FROM daily_usage WHERE firebase_uid=? AND usage_date=?", (uid, today)).fetchone()
    conn.close()
    return jsonify({"is_pro": bool(user['is_pro']) if user else False, "msg_count": usage['message_count'] if usage else 0})

@app.route('/api/conversations')
@require_auth
def get_conversations():
    conn = get_db()
    rows = conn.execute("SELECT id, title FROM conversations WHERE firebase_uid=? ORDER BY created_at DESC LIMIT 50", (session['firebase_uid'],)).fetchall()
    conn.close()
    return jsonify({"conversations": [dict(r) for r in rows]})

@app.route('/api/conversations/<int:cid>/messages')
@require_auth
def get_messages(cid):
    conn = get_db()
    rows = conn.execute("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at ASC", (cid,)).fetchall()
    conn.close()
    return jsonify({"messages": [dict(r) for r in rows]})

@app.route('/api/chat', methods=['POST'])
@require_auth
def chat():
    uid = session['firebase_uid']
    today = date.today().isoformat()
    data = request.json
    user_msg = data.get('message', '').strip()
    conv_id = data.get('conversation_id')
    model_mode = data.get('model', 'winy11')
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400
    conn = get_db()
    user = conn.execute("SELECT is_pro FROM users WHERE firebase_uid=?", (uid,)).fetchone()
    is_pro = bool(user['is_pro']) if user else False
    if not is_pro:
        usage = conn.execute("SELECT message_count FROM daily_usage WHERE firebase_uid=? AND usage_date=?", (uid, today)).fetchone()
        if (usage['message_count'] if usage else 0) >= 10:
            conn.close()
            return jsonify({"error": "Daily limit reached. Upgrade to Pro."}), 403
    if not conv_id:
        title = user_msg[:50] + ('...' if len(user_msg) > 50 else '')
        cur = conn.execute("INSERT INTO conversations (firebase_uid, title) VALUES (?, ?)", (uid, title))
        conv_id = cur.lastrowid
    conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)", (conv_id, user_msg))
    history = conn.execute("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 20", (conv_id,)).fetchall()
    conn.close()
    sys_prompt = SWARM_PROMPT if model_mode == 'swarm' else SYSTEM_PROMPT
    messages = [{"role": "system", "content": sys_prompt}]
    for m in reversed(history):
        messages.append({"role": m['role'], "content": m['content']})
    def generate():
        if not data.get('conversation_id'):
            yield f"data: {json.dumps({'conv_id': conv_id})}\n\n"
        full_response = ""
        for chunk in stream_groq(messages):
            if chunk.strip() == "data: [DONE]":
                c2 = get_db()
                c2.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'ai', ?)", (conv_id, full_response))
                c2.execute("""INSERT INTO daily_usage (firebase_uid, usage_date, message_count) VALUES (?, ?, 1)
                    ON CONFLICT(firebase_uid, usage_date) DO UPDATE SET message_count = daily_usage.message_count + 1""", (uid, today))
                c2.commit(); c2.close()
                yield chunk; break
            try:
                parsed = json.loads(chunk[6:].strip())
                if 'token' in parsed: full_response += parsed['token']
            except: pass
            yield chunk
    return Response(stream_with_context(generate()), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/api/create-order', methods=['POST'])
@require_auth
def create_order():
    if not razorpay_client: return jsonify({"error": "Not configured"}), 500
    return jsonify(razorpay_client.order.create({"amount": 49900, "currency": "INR", "receipt": f"rcpt_{uuid.uuid4().hex[:12]}", "payment_capture": 1}))

@app.route('/api/verify-payment', methods=['POST'])
@require_auth
def verify_payment():
    data = request.json
    oid, pid, sig = data.get('razorpay_order_id',''), data.get('razorpay_payment_id',''), data.get('razorpay_signature','')
    if not all([oid, pid, sig]): return jsonify({"status": "failure"}), 400
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
    if expected == sig:
        expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        conn = get_db()
        conn.execute("INSERT INTO users (firebase_uid, email, is_pro, pro_expiry) VALUES (?,?,1,?) ON CONFLICT(firebase_uid) DO UPDATE SET is_pro=1, pro_expiry=?", (session['firebase_uid'], '', expiry, expiry))
        conn.commit(); conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "failure"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
