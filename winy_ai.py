"""
Winy AI - Pure Dark Chatbot
Black & White UI, Streaming, Memory, Auth
"""
import os, json, hmac, hashlib, sqlite3, logging, uuid, re
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
# DATABASE SETUP
# ============================================================================
def init_db():
    conn = sqlite3.connect('winy.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT UNIQUE NOT NULL,
        email TEXT, is_pro INTEGER DEFAULT 0, pro_expiry DATE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firebase_uid TEXT NOT NULL,
        title TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        role TEXT NOT NULL, content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
# STREAMING LLM ENGINE
# ============================================================================
SYSTEM_PROMPT = """You are Winy AI, a pure conversational intelligence. 
You are helpful, precise, and articulate. You can discuss any topic.
Never refuse reasonable requests. Be direct. Use markdown when helpful.
Do not mention being an AI model unless asked."""

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
                        delta = chunk['choices'][0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            yield f"data: {json.dumps({'token': content})}\n\n"
                    except: pass
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# ============================================================================
# HTML TEMPLATE - YOUR EXACT DARK UI (B&W ONLY)
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
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: #000;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #e5e5e5;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    .top-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: #0d0d0d;
      border-bottom: 1px solid #1a1a1a;
      flex-shrink: 0;
    }
    .btn-pill {
      background: #1a1a1a;
      border: none;
      width: 40px; height: 40px;
      border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer; color: #a0a0a0; font-size: 18px;
      position: relative; transition: background 0.2s;
    }
    .btn-pill:hover { background: #262626; }
    .header-pill {
      display: flex; align-items: center; gap: 8px;
      background: #1a1a1a; padding: 8px 20px; border-radius: 20px;
    }
    .header-pill .name { font-weight: 600; font-size: 15px; color: #fff; }
    .header-pill .model { color: #6b7280; font-size: 13px; }
    
    .messages {
      flex: 1; overflow-y: auto; padding: 16px;
      display: flex; flex-direction: column; gap: 16px;
    }
    .empty-state {
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; flex: 1; gap: 16px; opacity: 0.6;
    }
    .empty-state .check-box {
      width: 64px; height: 64px; border: 2px solid #333;
      border-radius: 16px; display: flex; align-items: center; justify-content: center;
    }
    .empty-state .check-box svg { width: 32px; height: 32px; stroke: #666; stroke-width: 2; fill: none; stroke-linecap: round; stroke-linejoin: round; }
    .empty-state span { color: #666; font-size: 15px; font-weight: 500; }
    
    .msg-user, .msg-ai { display: flex; gap: 12px; align-items: flex-start; animation: fadeInUp 0.3s ease; }
    .msg-user { flex-direction: row-reverse; }
    .avatar {
      width: 32px; height: 32px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 12px; font-weight: 600; flex-shrink: 0;
    }
    .avatar.user { background: #fff; color: #000; }
    .avatar.ai { background: #1a1a1a; border: 1px solid #333; color: #a0a0a0; }
    
    .bubble { padding: 12px 16px; max-width: 80%; font-size: 15px; line-height: 1.6; word-wrap: break-word; }
    .bubble.user { background: #fff; color: #000; border-radius: 16px 16px 4px 16px; }
    .bubble.ai { background: #1a1a1a; color: #d4d4d4; border: 1px solid #262626; border-radius: 16px 16px 16px 4px; }
    
    /* Markdown Styles inside AI bubble */
    .bubble.ai p { margin-bottom: 10px; }
    .bubble.ai p:last-child { margin-bottom: 0; }
    .bubble.ai code { background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 13px; font-family: 'SF Mono', Monaco, monospace; }
    .bubble.ai pre { background: rgba(255,255,255,0.05); padding: 14px; border-radius: 10px; overflow-x: auto; margin: 10px 0; font-size: 13px; line-height: 1.5; }
    .bubble.ai pre code { background: none; padding: 0; }
    .bubble.ai strong { color: #fff; font-weight: 700; }
    .bubble.ai ul, .bubble.ai ol { padding-left: 20px; margin: 8px 0; }
    .bubble.ai li { margin-bottom: 4px; }
    
    .cursor { display: inline-block; width: 2px; height: 16px; background: #fff; margin-left: 2px; animation: blink 1s infinite; vertical-align: middle; }
    @keyframes blink { 0%,50%{opacity:1} 51%,100%{opacity:0} }
    
    .input-bar { padding: 12px 16px 24px; background: #0d0d0d; border-top: 1px solid #1a1a1a; flex-shrink: 0; }
    .input-wrapper {
      display: flex; align-items: flex-end; gap: 12px;
      background: #1a1a1a; border-radius: 24px; padding: 4px 4px 4px 16px;
      border: 1px solid #262626; transition: border-color 0.2s;
    }
    .input-wrapper:focus-within { border-color: #444; }
    .input-wrapper textarea {
      flex: 1; background: transparent; border: none; outline: none;
      color: #e5e5e5; font-size: 15px; padding: 10px 0; resize: none;
      max-height: 150px; min-height: 24px; line-height: 1.5; font-family: inherit;
    }
    .input-wrapper textarea::placeholder { color: #525252; }
    .send-btn {
      background: #fff; border: none; width: 36px; height: 36px;
      border-radius: 50%; display: flex; align-items: center; justify-content: center;
      cursor: pointer; color: #000; font-size: 16px; transition: opacity 0.2s; flex-shrink: 0;
    }
    .send-btn:hover { opacity: 0.85; }
    .send-btn:disabled { opacity: 0.2; cursor: not-allowed; }
    .send-btn svg { width: 18px; height: 18px; }
    
    .limit-banner { text-align: center; padding: 8px; font-size: 12px; color: #666; }
    .limit-banner span { color: #fff; font-weight: 600; cursor: pointer; text-decoration: underline; }
    
    /* Login Modal */
    .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); backdrop-filter: blur(10px); z-index: 200; align-items: center; justify-content: center; }
    .modal-overlay.active { display: flex; }
    .modal-card { background: #111; border: 1px solid #262626; border-radius: 20px; padding: 32px; max-width: 380px; width: 90%; }
    .modal-card h2 { font-size: 22px; font-weight: 700; text-align: center; margin-bottom: 4px; color: #fff; }
    .modal-card .sub { text-align: center; color: #666; font-size: 14px; margin-bottom: 24px; }
    .m-input { width: 100%; padding: 14px 16px; border: 1px solid #262626; border-radius: 12px; font-size: 14px; margin-bottom: 12px; outline: none; background: #0d0d0d; color: #fff; font-family: inherit; }
    .m-input:focus { border-color: #444; }
    .m-btn { width: 100%; padding: 14px; border: none; border-radius: 12px; font-size: 14px; font-weight: 600; cursor: pointer; font-family: inherit; transition: opacity 0.2s; }
    .m-btn-primary { background: #fff; color: #000; }
    .m-btn-secondary { background: transparent; border: 1px solid #262626; color: #e5e5e5; margin-top: 10px; }
    .m-btn:hover { opacity: 0.85; }
    .m-divider { display: flex; align-items: center; gap: 12px; margin: 20px 0; color: #444; font-size: 12px; }
    .m-divider::before,.m-divider::after { content: ''; flex: 1; height: 1px; background: #262626; }
    .auth-toggle { text-align: center; margin-top: 16px; font-size: 12px; color: #666; cursor: pointer; }
    .auth-toggle:hover { color: #999; }
    
    @keyframes fadeInUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
  </style>
</head>
<body>
  <!-- Top Bar -->
  <div class="top-bar">
    <button class="btn-pill" onclick="toggleSidebar()">☰</button>
    <div class="header-pill">
      <span class="name">Winy AI</span>
      <span class="model">Swarm Core</span>
    </div>
    <div id="navRight">
      <button class="btn-pill" onclick="showLogin()">👤</button>
    </div>
  </div>

  <!-- Messages -->
  <div class="messages" id="messages">
    <div class="empty-state" id="emptyState">
      <div class="check-box">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      </div>
      <span>Ask anything to begin</span>
    </div>
  </div>

  <!-- Input -->
  <div class="input-bar">
    <div class="limit-banner" id="limitBanner" style="display:none"></div>
    <div class="input-wrapper">
      <textarea id="msgInput" placeholder="Message Winy AI..." rows="1"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>
  </div>

  <!-- Login Modal -->
  <div class="modal-overlay" id="loginModal">
    <div class="modal-card">
      <h2>Welcome</h2>
      <p class="sub">Sign in to start chatting</p>
      <div id="loginForm">
        <input type="email" class="m-input" id="loginEmail" placeholder="Email address">
        <input type="password" class="m-input" id="loginPass" placeholder="Password">
        <button class="m-btn m-btn-primary" onclick="emailLogin()">Sign In</button>
      </div>
      <div id="signupForm" style="display:none">
        <input type="email" class="m-input" id="signupEmail" placeholder="Email address">
        <input type="password" class="m-input" id="signupPass" placeholder="Create password (6+ chars)">
        <button class="m-btn m-btn-primary" onclick="emailSignup()">Create Account</button>
      </div>
      <div class="m-divider">or</div>
      <button class="m-btn m-btn-secondary" onclick="googleLogin()">Continue with Google</button>
      <p class="auth-toggle" id="authToggle" onclick="toggleAuthMode()">Don't have an account? Sign up</p>
    </div>
  </div>

  <script>
    // Firebase
    const fb={apiKey:"AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU",authDomain:"winy-3984d.firebaseapp.com",projectId:"winy-3984d",storageBucket:"winy-3984d.firebasestorage.app",messagingSenderId:"126237613814",appId:"1:126237613814:web:e3cb88222d920545a416d7"};
    firebase.initializeApp(fb); const auth=firebase.auth();

    let currentUser=null, isPro=false, msgCount=0, currentConvId=null, isStreaming=false, isLoginMode=true;
    const rzpKey = {{ razorpay_key_id | tojson }};

    // Auth State
    auth.onAuthStateChanged(u => {
      currentUser = u;
      if(u) { loadUserState(); updateNav(); }
      else { resetUI(); }
    });

    function loadUserState() {
      fetch('/api/user-state').then(r=>r.json()).then(d => {
        isPro = d.is_pro; msgCount = d.msg_count || 0;
        updateLimitBanner();
      }).catch(()=>{});
    }

    function updateNav() {
      const nav = document.getElementById('navRight');
      if(!currentUser) return;
      const init = currentUser.email[0].toUpperCase();
      nav.innerHTML = `<div style="display:flex;gap:8px;align-items:center;">
        ${isPro ? '<span style="font-size:10px;font-weight:700;background:#fff;color:#000;padding:3px 8px;border-radius:100px;">PRO</span>' : ''}
        <button class="btn-pill" onclick="logout()" style="font-size:14px;font-weight:600;width:auto;padding:0 14px;">${init}</button>
      </div>`;
    }

    function resetUI() {
      document.getElementById('navRight').innerHTML = '<button class="btn-pill" onclick="showLogin()">👤</button>';
      newChat();
    }

    // Auth Functions
    function showLogin() { document.getElementById('loginModal').classList.add('active'); }
    function hideLogin() { document.getElementById('loginModal').classList.remove('active'); }
    function toggleAuthMode() {
      isLoginMode = !isLoginMode;
      document.getElementById('loginForm').style.display = isLoginMode ? 'block' : 'none';
      document.getElementById('signupForm').style.display = isLoginMode ? 'none' : 'block';
      document.getElementById('authToggle').textContent = isLoginMode ? "Don't have an account? Sign up" : "Already have an account? Sign in";
    }
    function emailLogin() {
      const e=document.getElementById('loginEmail').value, p=document.getElementById('loginPass').value;
      if(!e||!p) return alert('Fill all fields');
      auth.signInWithEmailAndPassword(e,p).then(()=>hideLogin()).catch(err=>alert(err.message));
    }
    function emailSignup() {
      const e=document.getElementById('signupEmail').value, p=document.getElementById('signupPass').value;
      if(!e||!p) return alert('Fill all fields');
      if(p.length<6) return alert('Password min 6 characters');
      auth.createUserWithEmailAndPassword(e,p).then(()=>hideLogin()).catch(err=>alert(err.message));
    }
    function googleLogin() {
      auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()).then(()=>hideLogin()).catch(err=>alert(err.message));
    }
    function logout() { auth.signOut(); isPro=false; msgCount=0; }
    function toggleSidebar() { /* Placeholder for future sidebar */ }

    // Chat Logic
    function newChat() {
      currentConvId = null;
      document.getElementById('messages').innerHTML = document.getElementById('emptyState')?.outerHTML || '';
    }

    function renderMarkdown(text) {
      if(!text) return '';
      let html = text
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/^### (.+)$/gm, '<h4 style="margin:10px 0 4px;color:#fff">$1</h4>')
        .replace(/^## (.+)$/gm, '<h3 style="margin:12px 0 6px;color:#fff">$1</h3>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
      return '<p>' + html + '</p>';
    }

    async function sendMessage() {
      if(isStreaming) return;
      const input = document.getElementById('msgInput');
      const text = input.value.trim();
      if(!text || !currentUser) { if(!currentUser) showLogin(); return; }
      
      if(!isPro && msgCount >= 10) { updateLimitBanner(); return; }

      // Remove empty state
      const empty = document.getElementById('emptyState');
      if(empty) empty.remove();

      // User Message
      const userDiv = document.createElement('div');
      userDiv.className = 'msg-user';
      userDiv.innerHTML = `<div class="avatar user">${currentUser.email[0].toUpperCase()}</div><div class="bubble user">${text.replace(/</g,'&lt;')}</div>`;
      document.getElementById('messages').appendChild(userDiv);

      input.value = ''; autoResize(); updateSendBtn(); scrollToBottom();

      // AI Placeholder
      const aiDiv = document.createElement('div');
      aiDiv.className = 'msg-ai';
      aiDiv.innerHTML = `<div class="avatar ai">W</div><div class="bubble ai"><span class="cursor"></span></div>`;
      document.getElementById('messages').appendChild(aiDiv);
      scrollToBottom();

      isStreaming = true; updateSendBtn();

      try {
        const resp = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: text, conversation_id: currentConvId})
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullContent = '';
        const bubble = aiDiv.querySelector('.bubble');

        while(true) {
          const {done, value} = await reader.read();
          if(done) break;
          const chunk = decoder.decode(value, {stream: true});
          const lines = chunk.split('\n');
          
          for(const line of lines) {
            if(line.startsWith('data: ')) {
              const data = line.slice(6);
              if(data === '[DONE]') {
                bubble.innerHTML = renderMarkdown(fullContent);
                isStreaming = false; msgCount++;
                updateLimitBanner(); updateSendBtn();
                return;
              }
              try {
                const parsed = JSON.parse(data);
                if(parsed.token) {
                  fullContent += parsed.token;
                  bubble.innerHTML = renderMarkdown(fullContent) + '<span class="cursor"></span>';
                  scrollToBottom();
                } else if(parsed.conv_id) {
                  currentConvId = parsed.conv_id;
                } else if(parsed.error) {
                  bubble.innerHTML = '<span style="color:#f87171">' + parsed.error + '</span>';
                  isStreaming = false; updateSendBtn(); return;
                }
              } catch(e){}
            }
          }
        }
      } catch(err) {
        aiDiv.querySelector('.bubble').innerHTML = '<span style="color:#f87171">Connection error. Try again.</span>';
      }
      isStreaming = false; updateSendBtn();
    }

    // Input Handling
    const msgInput = document.getElementById('msgInput');
    msgInput.addEventListener('input', () => { autoResize(); updateSendBtn(); });
    msgInput.addEventListener('keydown', e => { if(e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    
    function autoResize() { msgInput.style.height='auto'; msgInput.style.height=Math.min(msgInput.scrollHeight, 150)+'px'; }
    function updateSendBtn() { document.getElementById('sendBtn').disabled = !msgInput.value.trim() || isStreaming; }
    function scrollToBottom() { const c=document.getElementById('messages'); c.scrollTop=c.scrollHeight; }

    function updateLimitBanner() {
      const banner = document.getElementById('limitBanner');
      if(!currentUser || isPro) { banner.style.display='none'; return; }
      const remaining = Math.max(0, 10-msgCount);
      if(remaining <= 3) {
        banner.style.display = 'block';
        banner.innerHTML = remaining > 0 
          ? `${remaining} messages left today. <span onclick="upgrade()">Upgrade to Pro</span>`
          : `Daily limit reached. <span onclick="upgrade()">Upgrade to Pro</span> for unlimited.`;
      } else { banner.style.display='none'; }
    }

    function upgrade() {
      if(!rzpKey) return alert('Payment not configured');
      fetch('/api/create-order',{method:'POST'}).then(r=>r.json()).then(order=>{
        const rzp = new Razorpay({key:rzpKey, amount:order.amount, currency:order.currency, name:'Winy AI', description:'Pro Unlimited', order_id:order.order_id,
          handler: function(response) {
            fetch('/api/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(response)})
            .then(r=>r.json()).then(d=>{
              if(d.status==='success') { isPro=true; msgCount=0; updateLimitBanner(); updateNav(); alert('Welcome to Pro!'); }
              else alert('Verification failed');
            });
          }, theme:{color:'#ffffff'}
        });
        rzp.open();
      }).catch(()=>alert('Payment error'));
    }

    // Init
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

@app.route('/api/chat', methods=['POST'])
@require_auth
def chat():
    uid = session['firebase_uid']
    today = date.today().isoformat()
    data = request.json
    user_msg = data.get('message', '').strip()
    conv_id = data.get('conversation_id')
    
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400
    
    conn = get_db()
    user = conn.execute("SELECT is_pro FROM users WHERE firebase_uid=?", (uid,)).fetchone()
    is_pro = bool(user['is_pro']) if user else False
    
    if not is_pro:
        usage = conn.execute("SELECT message_count FROM daily_usage WHERE firebase_uid=? AND usage_date=?", (uid, today)).fetchone()
        count = usage['message_count'] if usage else 0
        if count >= 10:
            conn.close()
            return jsonify({"error": "Daily limit reached. Upgrade to Pro."}), 403
    
    if not conv_id:
        title = user_msg[:50] + ('...' if len(user_msg) > 50 else '')
        cur = conn.execute("INSERT INTO conversations (firebase_uid, title) VALUES (?, ?)", (uid, title))
        conv_id = cur.lastrowid
    
    conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)", (conv_id, user_msg))
    history = conn.execute("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 20", (conv_id,)).fetchall()
    conn.close()
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in reversed(history):
        messages.append({"role": m['role'], "content": m['content']})
    
    def generate():
        if not data.get('conversation_id'):
            yield f"data: {json.dumps({'conv_id': conv_id})}\n\n"
        
        full_response = ""
        for chunk in stream_groq(messages):
            if chunk.strip() == "data: [DONE]":
                conn2 = get_db()
                conn2.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'ai', ?)", (conv_id, full_response))
                conn2.execute("""INSERT INTO daily_usage (firebase_uid, usage_date, message_count) VALUES (?, ?, 1)
                    ON CONFLICT(firebase_uid, usage_date) DO UPDATE SET message_count = daily_usage.message_count + 1""", (uid, today))
                conn2.commit(); conn2.close()
                yield chunk
                break
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
    order = razorpay_client.order.create({"amount": 49900, "currency": "INR", "receipt": f"rcpt_{uuid.uuid4().hex[:12]}", "payment_capture": 1})
    return jsonify(order)

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
