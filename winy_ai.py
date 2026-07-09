"""
NoteFlow - Glass Student Note Organizer & Flashcard Generator
Animated UI, No Emojis, Custom Keyboard, Auth, Payments
"""
import os, json, hmac, hashlib, sqlite3, logging, uuid, base64, re
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, session
import razorpay

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "noteflow-secret-change-me")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID else None

# ============================================================================
# DATABASE
# ============================================================================
def init_db():
    conn = sqlite3.connect('noteflow.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT UNIQUE NOT NULL, email TEXT,
        is_pro INTEGER DEFAULT 0, pro_expiry DATE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL, title TEXT NOT NULL,
        content TEXT NOT NULL, course TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS flashcards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_id INTEGER NOT NULL, front TEXT NOT NULL,
        back TEXT NOT NULL, mastery INTEGER DEFAULT 0,
        next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL, usage_date DATE NOT NULL,
        cards_generated INTEGER DEFAULT 0,
        UNIQUE(firebase_uid, usage_date)
    )''')
    conn.commit(); conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('noteflow.db')
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
# FLASHCARD GENERATOR (No External AI Needed)
# ============================================================================
def generate_flashcards_from_text(text):
    """Extracts key concepts from text using pattern matching."""
    cards = []
    sentences = re.split(r'[.!?]+', text)
    
    patterns = [
        (r'(.+?)\s+(?:is|are|was|were|means|refers to)\s+(.+)', '{}', '{}'),
        (r'(.+?)\s+(?:can be defined as|is defined as|is known as)\s+(.+)', '{}', '{}'),
        (r'(?:the|a|an)\s+(.+?)\s+(?:is|are)\s+(.+)', '{}', '{}'),
    ]
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15 or len(sentence) > 300:
            continue
            
        for pattern, front_fmt, back_fmt in patterns:
            match = re.match(pattern, sentence, re.IGNORECASE)
            if match:
                front = match.group(1).strip().capitalize()
                back = match.group(2).strip()
                if len(front) > 5 and len(back) > 5:
                    cards.append({"front": front, "back": back})
                    break
    
    # Fallback: create question-answer pairs from longer sentences
    if len(cards) < 3:
        for sentence in sentences:
            sentence = sentence.strip()
            if 30 < len(sentence) < 200 and len(cards) < 8:
                words = sentence.split()
                mid = len(words) // 2
                cards.append({
                    "front": "Complete: " + " ".join(words[:mid]) + "...",
                    "back": sentence
                })
    
    return cards[:10]  # Max 10 cards per note

# ============================================================================
# HTML TEMPLATE
# ============================================================================
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>NoteFlow</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{--glass:rgba(255,255,255,0.04);--glass-border:rgba(255,255,255,0.08);--glass-hover:rgba(255,255,255,0.08);--text:#e8e8e8;--text-dim:rgba(255,255,255,0.4);--accent:rgba(255,255,255,0.9)}
body{background:#050505;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--text);min-height:100vh;overflow-x:hidden}

/* ANIMATED BACKGROUND */
.bg-orb{position:fixed;border-radius:50%;filter:blur(120px);pointer-events:none;z-index:0;opacity:0.6}
.bg-orb-1{width:500px;height:500px;background:radial-gradient(circle,rgba(255,255,255,0.06),transparent 70%);top:-200px;left:-150px;animation:orbFloat1 20s ease-in-out infinite}
.bg-orb-2{width:400px;height:400px;background:radial-gradient(circle,rgba(255,255,255,0.04),transparent 70%);bottom:-150px;right:-100px;animation:orbFloat2 25s ease-in-out infinite reverse}
.bg-orb-3{width:300px;height:300px;background:radial-gradient(circle,rgba(255,255,255,0.03),transparent 70%);top:40%;left:60%;animation:orbFloat3 18s ease-in-out infinite 5s}
@keyframes orbFloat1{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(60px,-40px) scale(1.1)}66%{transform:translate(-30px,30px) scale(0.95)}}
@keyframes orbFloat2{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(-40px,35px) scale(1.08)}66%{transform:translate(35px,-25px) scale(0.92)}}
@keyframes orbFloat3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(25px,-35px) scale(1.12)}}

/* LAYOUT */
.app{display:flex;min-height:100vh;position:relative;z-index:1}
.sidebar{width:280px;background:var(--glass);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);border-right:1px solid var(--glass-border);display:flex;flex-direction:column;flex-shrink:0;transition:transform 0.4s cubic-bezier(0.22,1,0.36,1)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}

/* SIDEBAR */
.sidebar-header{padding:24px;border-bottom:1px solid var(--glass-border)}
.logo{font-size:20px;font-weight:700;letter-spacing:-0.5px;display:flex;align-items:center;gap:10px}
.logo svg{width:24px;height:24px;stroke:var(--accent);fill:none;stroke-width:1.5}
.new-note-btn{width:calc(100% - 32px);margin:16px auto;padding:14px;background:rgba(255,255,255,0.08);border:1px solid var(--glass-border);border-radius:14px;color:#fff;font-size:14px;font-weight:600;cursor:pointer;transition:all 0.3s;display:flex;align-items:center;justify-content:center;gap:8px}
.new-note-btn:hover{background:rgba(255,255,255,0.14);border-color:rgba(255,255,255,0.2);transform:translateY(-1px)}
.new-note-btn svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2}
.notes-list{flex:1;overflow-y:auto;padding:8px}
.note-item{padding:14px 16px;border-radius:12px;cursor:pointer;transition:all 0.25s;margin-bottom:4px;border:1px solid transparent}
.note-item:hover{background:var(--glass-hover);border-color:var(--glass-border)}
.note-item.active{background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.12)}
.note-item-title{font-size:14px;font-weight:600;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.note-item-meta{font-size:11px;color:var(--text-dim);display:flex;gap:8px}
.sidebar-footer{padding:16px;border-top:1px solid var(--glass-border)}
.user-row{display:flex;align-items:center;gap:10px}
.user-avatar{width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.1);border:1px solid var(--glass-border);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600}
.user-info{flex:1;min-width:0}
.user-name{font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.user-plan{font-size:10px;color:var(--text-dim)}
.pro-badge{font-size:9px;font-weight:700;background:#fff;color:#000;padding:2px 8px;border-radius:100px;letter-spacing:0.5px}
.sb-btn{background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:11px;padding:6px 10px;border-radius:8px;transition:all 0.2s}
.sb-btn:hover{color:#fff;background:rgba(255,255,255,0.06)}

/* MAIN CONTENT */
.main-header{padding:16px 24px;border-bottom:1px solid var(--glass-border);display:flex;align-items:center;gap:12px;background:rgba(5,5,5,0.3);backdrop-filter:blur(20px);flex-shrink:0}
.menu-btn{display:none;width:36px;height:36px;border-radius:10px;border:1px solid var(--glass-border);background:none;color:var(--text-dim);cursor:pointer;align-items:center;justify-content:center}
.menu-btn svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2}
.header-title{font-size:16px;font-weight:600;flex:1}
.header-actions{display:flex;gap:8px}
.h-btn{padding:8px 14px;border-radius:10px;border:1px solid var(--glass-border);background:var(--glass);color:var(--text);font-size:12px;font-weight:600;cursor:pointer;transition:all 0.2s;display:flex;align-items:center;gap:6px}
.h-btn:hover{background:var(--glass-hover);border-color:rgba(255,255,255,0.15)}
.h-btn svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2}
.h-btn.primary{background:rgba(255,255,255,0.1);border-color:rgba(255,255,255,0.15)}

/* EDITOR */
.editor-area{flex:1;padding:24px;overflow-y:auto;display:flex;flex-direction:column}
.editor-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;opacity:0.3;text-align:center;gap:16px}
.editor-empty svg{width:64px;height:64px;stroke:rgba(255,255,255,0.3);fill:none;stroke-width:1}
.editor-empty p{font-size:15px;color:var(--text-dim)}
.note-title-input{width:100%;background:transparent;border:none;outline:none;color:#fff;font-size:28px;font-weight:700;letter-spacing:-0.5px;margin-bottom:8px;font-family:inherit}
.note-title-input::placeholder{color:rgba(255,255,255,0.2)}
.note-course-input{width:200px;background:transparent;border:none;outline:none;color:var(--text-dim);font-size:13px;margin-bottom:24px;font-family:inherit;border-bottom:1px solid transparent;transition:border-color 0.2s}
.note-course-input:focus{border-bottom-color:var(--glass-border)}
.note-course-input::placeholder{color:rgba(255,255,255,0.15)}
.note-content-input{width:100%;flex:1;background:transparent;border:none;outline:none;color:rgba(255,255,255,0.85);font-size:16px;line-height:1.8;resize:none;font-family:inherit;min-height:300px}
.note-content-input::placeholder{color:rgba(255,255,255,0.15)}

/* FLASHCARDS PANEL */
.cards-panel{border-top:1px solid var(--glass-border);padding:24px;background:rgba(255,255,255,0.02);flex-shrink:0}
.cards-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.cards-title{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim)}
.cards-count{font-size:12px;color:var(--text-dim)}
.gen-btn{padding:10px 20px;border-radius:10px;border:1px solid var(--glass-border);background:rgba(255,255,255,0.08);color:#fff;font-size:13px;font-weight:600;cursor:pointer;transition:all 0.3s;display:flex;align-items:center;gap:8px}
.gen-btn:hover{background:rgba(255,255,255,0.14);transform:translateY(-1px)}
.gen-btn:disabled{opacity:0.3;cursor:not-allowed;transform:none}
.gen-btn svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;max-height:400px;overflow-y:auto;padding:4px}
.flashcard{background:var(--glass);border:1px solid var(--glass-border);border-radius:16px;padding:20px;cursor:pointer;transition:all 0.4s cubic-bezier(0.22,1,0.36,1);position:relative;min-height:140px;display:flex;align-items:center;justify-content:center;text-align:center;perspective:1000px}
.flashcard:hover{border-color:rgba(255,255,255,0.15);transform:translateY(-2px)}
.flashcard-inner{position:relative;width:100%;height:100%;transition:transform 0.6s cubic-bezier(0.22,1,0.36,1);transform-style:preserve-3d}
.flashcard.flipped .flashcard-inner{transform:rotateY(180deg)}
.flashcard-front,.flashcard-back{backface-visibility:hidden;-webkit-backface-visibility:hidden}
.flashcard-back{position:absolute;top:0;left:0;width:100%;height:100%;transform:rotateY(180deg);display:flex;align-items:center;justify-content:center}
.fc-text{font-size:14px;line-height:1.6;color:rgba(255,255,255,0.85)}
.fc-label{position:absolute;top:10px;left:14px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim)}
.fc-mastery{position:absolute;bottom:10px;right:14px;display:flex;gap:3px}
.fc-dot{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,0.1)}
.fc-dot.filled{background:rgba(255,255,255,0.6)}

/* CUSTOM KEYBOARD OVERLAY (Mobile) */
.custom-kb{display:none;position:fixed;bottom:0;left:0;right:0;background:rgba(15,15,15,0.95);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);border-top:1px solid var(--glass-border);padding:8px;z-index:300;flex-direction:column;gap:6px}
.kb-row{display:flex;gap:4px;justify-content:center}
.kb-key{flex:1;max-width:44px;height:44px;border-radius:8px;border:1px solid var(--glass-border);background:rgba(255,255,255,0.06);color:#fff;font-size:16px;font-weight:500;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all 0.1s;-webkit-user-select:none;user-select:none}
.kb-key:active{background:rgba(255,255,255,0.2);transform:scale(0.95)}
.kb-key.wide{flex:2;max-width:88px;font-size:13px}
.kb-key.space{flex:4;max-width:176px}
.kb-key.action{background:rgba(255,255,255,0.12);font-size:13px}

/* LOGIN GATE */
.login-gate{position:fixed;inset:0;background:#050505;z-index:500;display:flex;align-items:center;justify-content:center;padding:20px}
.login-gate.hidden{display:none}
.gate-card{background:var(--glass);backdrop-filter:blur(40px);border:1px solid var(--glass-border);border-radius:24px;padding:40px;max-width:400px;width:100%;text-align:center;animation:gateIn 0.6s cubic-bezier(0.22,1,0.36,1)}
@keyframes gateIn{from{opacity:0;transform:translateY(20px) scale(0.98)}to{opacity:1;transform:translateY(0) scale(1)}}
.gate-card h1{font-size:28px;font-weight:700;margin-bottom:6px;letter-spacing:-0.5px}
.gate-card .sub{color:var(--text-dim);font-size:14px;margin-bottom:32px}
.m-input{width:100%;padding:14px 16px;border:1px solid var(--glass-border);border-radius:12px;font-size:14px;margin-bottom:12px;outline:none;background:rgba(255,255,255,0.03);color:#fff;font-family:inherit;transition:border-color 0.2s}
.m-input:focus{border-color:rgba(255,255,255,0.2)}
.m-input::placeholder{color:rgba(255,255,255,0.3)}
.m-btn{width:100%;padding:14px;border:none;border-radius:12px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;transition:all 0.3s}
.m-btn-primary{background:#fff;color:#000}
.m-btn-primary:hover{opacity:0.9;transform:translateY(-1px)}
.m-btn-secondary{background:transparent;border:1px solid var(--glass-border);color:var(--text);margin-top:10px}
.m-btn-secondary:hover{background:rgba(255,255,255,0.05)}
.m-divider{display:flex;align-items:center;gap:12px;margin:20px 0;color:rgba(255,255,255,0.15);font-size:11px}
.m-divider::before,.m-divider::after{content:'';flex:1;height:1px;background:var(--glass-border)}
.auth-toggle{margin-top:16px;font-size:12px;color:var(--text-dim);cursor:pointer;transition:color 0.2s}
.auth-toggle:hover{color:rgba(255,255,255,0.6)}

/* MODAL */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(8px);z-index:600;align-items:center;justify-content:center}
.modal-overlay.active{display:flex}
.modal-card{background:rgba(15,15,15,0.95);backdrop-filter:blur(30px);border:1px solid var(--glass-border);border-radius:20px;padding:32px;max-width:380px;width:90%;text-align:center;animation:modalIn 0.3s ease}
@keyframes modalIn{from{opacity:0;transform:scale(0.95)}to{opacity:1;transform:scale(1)}}
.modal-card h2{font-size:18px;margin-bottom:8px}
.modal-card p{color:var(--text-dim);font-size:13px;margin-bottom:24px;line-height:1.5}

/* TOAST */
.toast{position:fixed;top:20px;right:20px;background:rgba(15,15,15,0.95);backdrop-filter:blur(20px);border:1px solid var(--glass-border);border-radius:12px;padding:14px 20px;font-size:13px;z-index:700;transform:translateX(120%);transition:transform 0.4s cubic-bezier(0.22,1,0.36,1);display:flex;align-items:center;gap:10px}
.toast.show{transform:translateX(0)}
.toast svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2}

::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.06);border-radius:3px}

@media(max-width:768px){
  .sidebar{position:fixed;left:0;top:0;bottom:0;transform:translateX(-100%);z-index:200;width:280px}
  .sidebar.open{transform:translateX(0)}
  .menu-btn{display:flex}
  .custom-kb.active{display:flex}
  .editor-area{padding:16px}
  .note-title-input{font-size:22px}
  .cards-grid{grid-template-columns:1fr}
  .main-header{padding:12px 16px}
}
.sidebar-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:150;backdrop-filter:blur(4px)}
.sidebar-overlay.active{display:block}
</style>
</head>
<body>
<div class="bg-orb bg-orb-1"></div>
<div class="bg-orb bg-orb-2"></div>
<div class="bg-orb bg-orb-3"></div>

<!-- LOGIN GATE -->
<div class="login-gate" id="loginGate">
  <div class="gate-card">
    <h1>NoteFlow</h1>
    <p class="sub">Your glass study companion</p>
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

<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>

<div class="app">
  <!-- SIDEBAR -->
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        NoteFlow
      </div>
    </div>
    <button class="new-note-btn" onclick="createNote()">
      <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      New Note
    </button>
    <div class="notes-list" id="notesList"></div>
    <div class="sidebar-footer" id="sidebarFooter"></div>
  </aside>

  <!-- MAIN -->
  <main class="main">
    <div class="main-header">
      <button class="menu-btn" onclick="toggleSidebar()">
        <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <div class="header-title" id="headerTitle">Select a note</div>
      <div class="header-actions" id="headerActions" style="display:none">
        <button class="h-btn" onclick="deleteNote()">
          <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          Delete
        </button>
      </div>
    </div>

    <div class="editor-area" id="editorArea">
      <div class="editor-empty" id="editorEmpty">
        <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <p>Select a note or create a new one</p>
      </div>
      <div id="editorContent" style="display:none;flex:1;display:none;flex-direction:column">
        <input type="text" class="note-title-input" id="noteTitle" placeholder="Untitled Note" oninput="autoSave()">
        <input type="text" class="note-course-input" id="noteCourse" placeholder="Course / Subject" oninput="autoSave()">
        <textarea class="note-content-input" id="noteContent" placeholder="Start typing your lecture notes here..." oninput="autoSave()" onfocus="showKB()" onblur="hideKBDelayed()"></textarea>
      </div>
    </div>

    <div class="cards-panel" id="cardsPanel" style="display:none">
      <div class="cards-header">
        <div>
          <div class="cards-title">Flashcards</div>
          <div class="cards-count" id="cardsCount">0 cards</div>
        </div>
        <button class="gen-btn" id="genBtn" onclick="generateCards()">
          <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          Generate Cards
        </button>
      </div>
      <div class="cards-grid" id="cardsGrid"></div>
    </div>
  </main>
</div>

<!-- CUSTOM KEYBOARD -->
<div class="custom-kb" id="customKB">
  <div class="kb-row">
    <div class="kb-key" onclick="kbType('q')">q</div><div class="kb-key" onclick="kbType('w')">w</div><div class="kb-key" onclick="kbType('e')">e</div><div class="kb-key" onclick="kbType('r')">r</div><div class="kb-key" onclick="kbType('t')">t</div><div class="kb-key" onclick="kbType('y')">y</div><div class="kb-key" onclick="kbType('u')">u</div><div class="kb-key" onclick="kbType('i')">i</div><div class="kb-key" onclick="kbType('o')">o</div><div class="kb-key" onclick="kbType('p')">p</div>
  </div>
  <div class="kb-row">
    <div class="kb-key" onclick="kbType('a')">a</div><div class="kb-key" onclick="kbType('s')">s</div><div class="kb-key" onclick="kbType('d')">d</div><div class="kb-key" onclick="kbType('f')">f</div><div class="kb-key" onclick="kbType('g')">g</div><div class="kb-key" onclick="kbType('h')">h</div><div class="kb-key" onclick="kbType('j')">j</div><div class="kb-key" onclick="kbType('k')">k</div><div class="kb-key" onclick="kbType('l')">l</div>
  </div>
  <div class="kb-row">
    <div class="kb-key wide action" onclick="kbShift()">ABC</div><div class="kb-key" onclick="kbType('z')">z</div><div class="kb-key" onclick="kbType('x')">x</div><div class="kb-key" onclick="kbType('c')">c</div><div class="kb-key" onclick="kbType('v')">v</div><div class="kb-key" onclick="kbType('b')">b</div><div class="kb-key" onclick="kbType('n')">n</div><div class="kb-key" onclick="kbType('m')">m</div><div class="kb-key wide action" onclick="kbBackspace()">&#9003;</div>
  </div>
  <div class="kb-row">
    <div class="kb-key wide action" onclick="kbType('.')">.</div><div class="kb-key space" onclick="kbType(' ')">space</div><div class="kb-key wide action" onclick="kbEnter()">return</div>
  </div>
</div>

<!-- TOAST -->
<div class="toast" id="toast"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg><span id="toastMsg">Saved</span></div>

<!-- MODAL -->
<div class="modal-overlay" id="alertModal">
  <div class="modal-card"><h2 id="alertTitle">Notice</h2><p id="alertMsg">Message</p><button class="m-btn m-btn-primary" onclick="closeAlert()">OK</button></div>
</div>

<script>
const fb={apiKey:"AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU",authDomain:"winy-3984d.firebaseapp.com",projectId:"winy-3984d",storageBucket:"winy-3984d.firebasestorage.app",messagingSenderId:"126237613814",appId:"1:126237613814:web:e3cb88222d920545a416d7"};
firebase.initializeApp(fb);const auth=firebase.auth();

let currentUser=null,isPro=false,currentNoteId=null,saveTimer=null,isGateLogin=true,kbHideTimer=null;
const rzpKey={{ razorpay_key_id | tojson }};

// AUTH
auth.onAuthStateChanged(u=>{
  currentUser=u;
  if(u){document.getElementById('loginGate').classList.add('hidden');syncSession().then(()=>{loadState();updateSidebar();loadNotes()})}
  else{document.getElementById('loginGate').classList.remove('hidden');resetUI()}
});
async function syncSession(){try{const t=await currentUser.getIdToken();await fetch('/api/auth-sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t,email:currentUser.email})})}catch(e){}}
function loadState(){fetch('/api/user-state').then(r=>r.json()).then(d=>{isPro=d.is_pro}).catch(()=>{})}
function updateSidebar(){
  const sf=document.getElementById('sidebarFooter');if(!currentUser)return;
  const init=currentUser.email[0].toUpperCase();
  sf.innerHTML='<div class="user-row"><div class="user-avatar">'+init+'</div><div class="user-info"><div class="user-name">'+currentUser.email+'</div><div class="user-plan">'+(isPro?'<span class="pro-badge">PRO</span>':'Free Plan')+'</div></div>'+(isPro?'':'<button class="sb-btn" onclick="upgrade()">Upgrade</button>')+'<button class="sb-btn" onclick="doLogout()">Logout</button></div>';
}
function resetUI(){document.getElementById('sidebarFooter').innerHTML='';document.getElementById('notesList').innerHTML='';showEmpty()}
function doLogout(){auth.signOut();isPro=false;currentNoteId=null}

// GATE
function toggleGate(){isGateLogin=!isGateLogin;document.getElementById('gateLoginForm').style.display=isGateLogin?'block':'none';document.getElementById('gateSignupForm').style.display=isGateLogin?'none':'block';document.getElementById('gateToggle').textContent=isGateLogin?"Don't have an account? Sign up":"Already have an account? Sign in"}
function gateLogin(){const e=document.getElementById('gLoginEmail').value,p=document.getElementById('gLoginPass').value;if(!e||!p)return showAlert('Error','Fill all fields');auth.signInWithEmailAndPassword(e,p).catch(err=>showAlert('Error',err.message))}
function gateSignup(){const e=document.getElementById('gSignupEmail').value,p=document.getElementById('gSignupPass').value;if(!e||!p)return showAlert('Error','Fill all fields');if(p.length<6)return showAlert('Error','Min 6 chars');auth.createUserWithEmailAndPassword(e,p).catch(err=>showAlert('Error',err.message))}
function gateGoogle(){auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()).catch(err=>showAlert('Error',err.message))}

// SIDEBAR
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open');document.getElementById('sidebarOverlay').classList.toggle('active')}

// NOTES
function loadNotes(){
  fetch('/api/notes').then(r=>r.json()).then(d=>{
    const l=document.getElementById('notesList');l.innerHTML='';
    (d.notes||[]).forEach(n=>{
      const div=document.createElement('div');div.className='note-item'+(n.id===currentNoteId?' active':'');
      div.innerHTML='<div class="note-item-title">'+(n.title||'Untitled')+'</div><div class="note-item-meta"><span>'+(n.course||'No course')+'</span><span>'+new Date(n.created_at).toLocaleDateString()+'</span></div>';
      div.onclick=()=>openNote(n.id);l.appendChild(div);
    });
  }).catch(()=>{})
}
function createNote(){
  fetch('/api/notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'',content:'',course:''})})
  .then(r=>r.json()).then(d=>{currentNoteId=d.id;loadNotes();openNote(d.id);if(window.innerWidth<=768)toggleSidebar()}).catch(()=>showAlert('Error','Failed to create note'))
}
function openNote(id){
  currentNoteId=id;
  fetch('/api/notes/'+id).then(r=>r.json()).then(d=>{
    document.getElementById('editorEmpty').style.display='none';
    const ec=document.getElementById('editorContent');ec.style.display='flex';
    document.getElementById('noteTitle').value=d.title||'';
    document.getElementById('noteCourse').value=d.course||'';
    document.getElementById('noteContent').value=d.content||'';
    document.getElementById('headerTitle').textContent=d.title||'Untitled';
    document.getElementById('headerActions').style.display='flex';
    document.getElementById('cardsPanel').style.display='block';
    loadCards(id);
    document.querySelectorAll('.note-item').forEach(i=>i.classList.remove('active'));
    const active=document.querySelector('.note-item.active');if(active)active.classList.remove('active');
    // Highlight in sidebar
    const items=document.querySelectorAll('.note-item');
    items.forEach(i=>{if(i.onclick.toString().includes(id))i.classList.add('active')});
  }).catch(()=>showAlert('Error','Failed to load note'))
}
function autoSave(){
  if(!currentNoteId)return;
  clearTimeout(saveTimer);
  saveTimer=setTimeout(()=>{
    const title=document.getElementById('noteTitle').value;
    const course=document.getElementById('noteCourse').value;
    const content=document.getElementById('noteContent').value;
    document.getElementById('headerTitle').textContent=title||'Untitled';
    fetch('/api/notes/'+currentNoteId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,course,content})})
    .then(()=>{showToast('Saved');loadNotes()}).catch(()=>{})
  },800)
}
function deleteNote(){
  if(!currentNoteId)return;
  if(!confirm('Delete this note?'))return;
  fetch('/api/notes/'+currentNoteId,{method:'DELETE'}).then(()=>{currentNoteId=null;showEmpty();loadNotes()}).catch(()=>showAlert('Error','Failed to delete'))
}
function showEmpty(){
  document.getElementById('editorEmpty').style.display='flex';
  document.getElementById('editorContent').style.display='none';
  document.getElementById('headerActions').style.display='none';
  document.getElementById('cardsPanel').style.display='none';
  document.getElementById('headerTitle').textContent='Select a note';
}

// FLASHCARDS
function loadCards(noteId){
  fetch('/api/notes/'+noteId+'/cards').then(r=>r.json()).then(d=>{
    const grid=document.getElementById('cardsGrid');grid.innerHTML='';
    const cards=d.cards||[];
    document.getElementById('cardsCount').textContent=cards.length+' card'+(cards.length!==1?'s':'');
    cards.forEach(c=>{
      const div=document.createElement('div');div.className='flashcard';div.onclick=function(){this.classList.toggle('flipped')};
      const mastery=Math.min(c.mastery||0,5);
      let dots='';for(let i=0;i<5;i++)dots+='<div class="fc-dot'+(i<mastery?' filled':'')+'"></div>';
      div.innerHTML='<div class="flashcard-inner"><div class="flashcard-front"><div class="fc-label">Question</div><div class="fc-text">'+escHtml(c.front)+'</div><div class="fc-mastery">'+dots+'</div></div><div class="flashcard-back"><div class="fc-label">Answer</div><div class="fc-text">'+escHtml(c.back)+'</div></div></div>';
      grid.appendChild(div);
    });
  }).catch(()=>{})
}
function generateCards(){
  if(!currentNoteId)return;
  const content=document.getElementById('noteContent').value.trim();
  if(content.length<30)return showAlert('Error','Write at least 30 characters of notes first');
  const btn=document.getElementById('genBtn');btn.disabled=true;btn.innerHTML='<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1s linear infinite"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Generating...';
  fetch('/api/notes/'+currentNoteId+'/generate-cards',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content})})
  .then(r=>r.json()).then(d=>{
    btn.disabled=false;btn.innerHTML='<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Generate Cards';
    if(d.error)return showAlert('Error',d.error);
    showToast((d.count||0)+' cards generated');loadCards(currentNoteId);
  }).catch(()=>{btn.disabled=false;btn.innerHTML='<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Generate Cards';showAlert('Error','Generation failed')})
}
function escHtml(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// CUSTOM KEYBOARD
function showKB(){if(window.innerWidth<=768){clearTimeout(kbHideTimer);document.getElementById('customKB').classList.add('active')}}
function hideKBDelayed(){kbHideTimer=setTimeout(()=>{document.getElementById('customKB').classList.remove('active')},200)}
function kbType(char){const ta=document.getElementById('noteContent');const start=ta.selectionStart;const end=ta.selectionEnd;ta.value=ta.value.substring(0,start)+char+ta.value.substring(end);ta.selectionStart=ta.selectionEnd=start+char.length;ta.focus();autoSave()}
function kbBackspace(){const ta=document.getElementById('noteContent');const start=ta.selectionStart;const end=ta.selectionEnd;if(start===end&&start>0){ta.value=ta.value.substring(0,start-1)+ta.value.substring(end);ta.selectionStart=ta.selectionEnd=start-1}else if(start!==end){ta.value=ta.value.substring(0,start)+ta.value.substring(end);ta.selectionStart=ta.selectionEnd=start}ta.focus();autoSave()}
function kbEnter(){kbType('\n')}
function kbShift(){/* Could add uppercase toggle later */}

// UTILS
function showToast(msg){const t=document.getElementById('toast');document.getElementById('toastMsg').textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2000)}
function showAlert(t,m){document.getElementById('alertTitle').textContent=t;document.getElementById('alertMsg').textContent=m;document.getElementById('alertModal').classList.add('active')}
function closeAlert(){document.getElementById('alertModal').classList.remove('active')}
function upgrade(){
  if(!currentUser)return;
  if(!rzpKey)return showAlert('Error','Payment not configured');
  fetch('/api/create-order',{method:'POST'}).then(r=>r.json()).then(o=>{
    new Razorpay({key:rzpKey,amount:o.amount,currency:o.currency,name:'NoteFlow',description:'Pro - Unlimited Flashcards',order_id:o.order_id,
      handler:function(res){fetch('/api/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(res)}).then(r=>r.json()).then(d=>{if(d.status==='success'){isPro=true;updateSidebar();showAlert('Welcome!','Pro activated.')}else showAlert('Failed','Verification failed.')})},
      theme:{color:'#ffffff'}}).open()
  }).catch(()=>showAlert('Error','Payment error'))
}

// Add spin animation dynamically
const styleSheet=document.createElement('style');styleSheet.textContent='@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}';document.head.appendChild(styleSheet);

showEmpty();
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
    email, token = data.get('email',''), data.get('token','')
    if not email or not token: return jsonify({"error":"Missing"}), 400
    try:
        payload = token.split('.')[1]; payload += '='*(4-len(payload)%4)
        uid = json.loads(base64.b64decode(payload)).get('user_id','')
    except: uid = hashlib.sha256(email.encode()).hexdigest()[:28]
    session['firebase_uid'] = uid; session['email'] = email
    conn = get_db()
    if not conn.execute("SELECT id FROM users WHERE firebase_uid=?",(uid,)).fetchone():
        conn.execute("INSERT INTO users (firebase_uid,email) VALUES (?,?)",(uid,email)); conn.commit()
    conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/user-state')
@require_auth
def user_state():
    conn = get_db()
    user = conn.execute("SELECT is_pro FROM users WHERE firebase_uid=?",(session['firebase_uid'],)).fetchone()
    conn.close()
    return jsonify({"is_pro": bool(user['is_pro']) if user else False})

@app.route('/api/notes', methods=['GET'])
@require_auth
def get_notes():
    conn = get_db()
    rows = conn.execute("SELECT id,title,course,created_at FROM notes WHERE firebase_uid=? ORDER BY updated_at DESC",(session['firebase_uid'],)).fetchall()
    conn.close()
    return jsonify({"notes":[dict(r) for r in rows]})

@app.route('/api/notes', methods=['POST'])
@require_auth
def create_note():
    data = request.json
    conn = get_db()
    cur = conn.execute("INSERT INTO notes (firebase_uid,title,content,course) VALUES (?,?,?,?)",
        (session['firebase_uid'], data.get('title',''), data.get('content',''), data.get('course','')))
    conn.commit(); note_id = cur.lastrowid; conn.close()
    return jsonify({"id": note_id})

@app.route('/api/notes/<int:nid>', methods=['GET'])
@require_auth
def get_note(nid):
    conn = get_db()
    row = conn.execute("SELECT * FROM notes WHERE id=? AND firebase_uid=?",(nid,session['firebase_uid'])).fetchone()
    conn.close()
    if not row: return jsonify({"error":"Not found"}), 404
    return jsonify(dict(row))

@app.route('/api/notes/<int:nid>', methods=['PUT'])
@require_auth
def update_note(nid):
    data = request.json
    conn = get_db()
    conn.execute("UPDATE notes SET title=?,content=?,course=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND firebase_uid=?",
        (data.get('title',''), data.get('content',''), data.get('course',''), nid, session['firebase_uid']))
    conn.commit(); conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/notes/<int:nid>', methods=['DELETE'])
@require_auth
def delete_note(nid):
    conn = get_db()
    conn.execute("DELETE FROM notes WHERE id=? AND firebase_uid=?",(nid,session['firebase_uid']))
    conn.commit(); conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/notes/<int:nid>/cards', methods=['GET'])
@require_auth
def get_cards(nid):
    conn = get_db()
    # Verify note ownership
    note = conn.execute("SELECT id FROM notes WHERE id=? AND firebase_uid=?",(nid,session['firebase_uid'])).fetchone()
    if not note: conn.close(); return jsonify({"error":"Not found"}), 404
    rows = conn.execute("SELECT * FROM flashcards WHERE note_id=? ORDER BY id",(nid,)).fetchall()
    conn.close()
    return jsonify({"cards":[dict(r) for r in rows]})

@app.route('/api/notes/<int:nid>/generate-cards', methods=['POST'])
@require_auth
def generate_cards(nid):
    conn = get_db()
    note = conn.execute("SELECT id,content FROM notes WHERE id=? AND firebase_uid=?",(nid,session['firebase_uid'])).fetchone()
    if not note: conn.close(); return jsonify({"error":"Not found"}), 404
    
    content = note['content']
    cards = generate_flashcards_from_text(content)
    
    if not cards:
        conn.close()
        return jsonify({"error":"Could not extract key concepts. Try adding more definitions or detailed sentences."})
    
    # Check free limit
    today = date.today().isoformat()
    usage = conn.execute("SELECT cards_generated FROM daily_usage WHERE firebase_uid=? AND usage_date=?",(session['firebase_uid'],today)).fetchone()
    user = conn.execute("SELECT is_pro FROM users WHERE firebase_uid=?",(session['firebase_uid'],)).fetchone()
    is_pro = bool(user['is_pro']) if user else False
    
    if not is_pro and (usage['cards_generated'] if usage else 0) >= 20:
        conn.close()
        return jsonify({"error":"Daily card limit reached (20). Upgrade to Pro for unlimited."})
    
    # Save cards
    for card in cards:
        conn.execute("INSERT INTO flashcards (note_id,front,back) VALUES (?,?,?)",(nid,card['front'],card['back']))
    
    # Update usage
    conn.execute("""INSERT INTO daily_usage (firebase_uid,usage_date,cards_generated) VALUES (?,?,?)
        ON CONFLICT(firebase_uid,usage_date) DO UPDATE SET cards_generated=daily_usage.cards_generated+?""",
        (session['firebase_uid'],today,len(cards),len(cards)))
    conn.commit(); conn.close()
    
    return jsonify({"count": len(cards)})

@app.route('/api/create-order', methods=['POST'])
@require_auth
def create_order():
    if not razorpay_client: return jsonify({"error":"Not configured"}), 500
    return jsonify(razorpay_client.order.create({"amount":49900,"currency":"INR","receipt":f"rcpt_{uuid.uuid4().hex[:12]}","payment_capture":1}))

@app.route('/api/verify-payment', methods=['POST'])
@require_auth
def verify_payment():
    data = request.json
    oid,pid,sig = data.get('razorpay_order_id',''),data.get('razorpay_payment_id',''),data.get('razorpay_signature','')
    if not all([oid,pid,sig]): return jsonify({"status":"failure"}), 400
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(),f"{oid}|{pid}".encode(),hashlib.sha256).hexdigest()
    if expected == sig:
        expiry = (datetime.now()+timedelta(days=30)).strftime('%Y-%m-%d')
        conn = get_db()
        conn.execute("INSERT INTO users (firebase_uid,email,is_pro,pro_expiry) VALUES (?,?,1,?) ON CONFLICT(firebase_uid) DO UPDATE SET is_pro=1,pro_expiry=?",(session['firebase_uid'],'',expiry,expiry))
        conn.commit(); conn.close()
        return jsonify({"status":"success"})
    return jsonify({"status":"failure"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
