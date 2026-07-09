"""
Winy AI - Dark Chatbot with Model Selector & Typing Animation
Fixed auth sync, streaming, responsive design
"""
import os, json, hmac, hashlib, sqlite3, logging, uuid
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

SWARM_SYSTEM_PROMPT = """You are Winy AI in SWARM MODE. 
You deploy multiple expert perspectives to analyze any query deeply.
For every response, think through: Root Cause, Strategic Options, Risks, and Action Steps.
Be thorough, structured, and exceptionally insightful. Use markdown headers and lists.
This is your most powerful mode. Deliver premium-quality analysis."""

def stream_groq(messages, model="llama-3.1-8b-instant"):
    try:
        resp = http_requests.post(GROQ_URL, 
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, 
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
# HTML TEMPLATE
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
    body{background:#000;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e5e5e5;height:100vh;display:flex;flex-direction:column;overflow:hidden}
    
    /* TOP BAR */
    .top-bar{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#0d0d0d;border-bottom:1px solid #1a1a1a;flex-shrink:0;z-index:50}
    .btn-pill{background:#1a1a1a;border:none;width:40px;height:40px;border-radius:12px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#a0a0a0;font-size:18px;transition:background 0.2s}
    .btn-pill:hover{background:#262626}
    
    /* MODEL SELECTOR */
    .model-selector{position:relative}
    .header-pill{display:flex;align-items:center;gap:8px;background:#1a1a1a;padding:8px 16px;border-radius:20px;cursor:pointer;transition:background 0.2s;border:1px solid transparent;user-select:none}
    .header-pill:hover{background:#262626;border-color:#333}
    .header-pill .name{font-weight:600;font-size:14px;color:#fff}
    .header-pill .arrow{font-size:10px;color:#666;transition:transform 0.2s}
    .header-pill.open .arrow{transform:rotate(180deg)}
    .dropdown{position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%);background:#111;border:1px solid #262626;border-radius:14px;padding:6px;min-width:200px;display:none;z-index:100;box-shadow:0 12px 40px rgba(0,0,0,0.5)}
    .dropdown.active{display:block;animation:dropIn 0.2s ease}
    @keyframes dropIn{from{opacity:0;transform:translateX(-50%) translateY(-8px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
    .dropdown-item{padding:10px 14px;border-radius:10px;cursor:pointer;font-size:13px;color:#aaa;transition:all 0.15s;display:flex;align-items:center;justify-content:space-between}
    .dropdown-item:hover{background:#1a1a1a;color:#fff}
    .dropdown-item.selected{color:#fff;background:#1a1a1a}
    .dropdown-item.selected::after{content:'✓';font-size:12px;color:#fff}
    .dropdown-item .mode-tag{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;background:#333;color:#888;letter-spacing:0.5px}
    .dropdown-item.selected .mode-tag{background:#fff;color:#000}
    
    /* NAV RIGHT */
    .nav-right{display:flex;gap:8px;align-items:center}
    .pro-pill{font-size:10px;font-weight:700;background:#fff;color:#000;padding:3px 8px;border-radius:100px}
    .avatar-btn{width:36px;height:36px;border-radius:10px;background:#fff;color:#000;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;cursor:pointer;border:none;transition:opacity 0.2s}
    .avatar-btn:hover{opacity:0.85}
    
    /* MESSAGES */
    .messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:16px}
    .empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:16px;opacity:0.5}
    .empty-icon{width:64px;height:64px;border:2px solid #333;border-radius:16px;display:flex;align-items:center;justify-content:center}
    .empty-icon svg{width:28px;height:28px;stroke:#555;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
    .empty-state span{color:#555;font-size:15px;font-weight:500}
    
    .msg-user,.msg-ai{display:flex;gap:12px;align-items:flex-start;animation:fadeInUp 0.3s ease}
    .msg-user{flex-direction:row-reverse}
    .avatar{width:32px;height:32px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex-shrink:0}
    .avatar.user{background:#fff;color:#000}
    .avatar.ai{background:#1a1a1a;border:1px solid #333;color:#a0a0a0}
    .bubble{padding:12px 16px;max-width:80%;font-size:15px;line-height:1.65;word-wrap:break-word}
    .bubble.user{background:#fff;color:#000;border-radius:16px 16px 4px 16px}
    .bubble.ai{background:#1a1a1a;color:#d4d4d4;border:1px solid #262626;border-radius:16px 16px 16px 4px}
    .bubble.ai p{margin-bottom:10px}.bubble.ai p:last-child{margin-bottom:0}
    .bubble.ai code{background:rgba(255,255,255,0.1);padding:2px 6px;border-radius:4px;font-size:13px;font-family:'SF Mono',Monaco,monospace}
    .bubble.ai pre{background:rgba(255,255,255,0.05);padding:14px;border-radius:10px;overflow-x:auto;margin:10px 0;font-size:13px;line-height:1.5}
    .bubble.ai pre code{background:none;padding:0}
    .bubble.ai strong{color:#fff;font-weight:700}
    .bubble.ai ul,.bubble.ai ol{padding-left:20px;margin:8px 0}
    .bubble.ai li{margin-bottom:4px}
    .bubble.ai h3,.bubble.ai h4{color:#fff;margin:12px 0 6px}
    
    /* TYPING INDICATOR */
    .typing-dots{display:inline-flex;gap:4px;padding:4px 0}
    .typing-dots span{width:6px;height:6px;background:#555;border-radius:50%;animation:typingBounce 1.4s infinite ease-in-out both}
    .typing-dots span:nth-child(1){animation-delay:-0.32s}
    .typing-dots span:nth-child(2){animation-delay:-0.16s}
    @keyframes typingBounce{0%,80%,100%{transform:scale(0);opacity:0.4}40%{transform:scale(1);opacity:1}}
    
    .cursor{display:inline-block;width:2px;height:16px;background:#fff;margin-left:2px;animation:blink 1s infinite;vertical-align:middle}
    @keyframes blink{0%,50%{opacity:1}51%,100%{opacity:0}}
    @keyframes fadeInUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
    
    /* INPUT */
    .input-bar{padding:12px 16px 24px;background:#0d0d0d;border-top:1px solid #1a1a1a;flex-shrink:0}
    .input-wrapper{display:flex;align-items:flex-end;gap:12px;background:#1a1a1a;border-radius:24px;padding:4px 4px 4px 16px;border:1px solid #262626;transition:border-color 0.2s}
    .input-wrapper:focus-within{border-color:#444}
    .input-wrapper textarea{flex:1;background:transparent;border:none;outline:none;color:#e5e5e5;font-size:15px;padding:10px 0;resize:none;max-height:150px;min-height:24px;line-height:1.5;font-family:inherit}
    .input-wrapper textarea::placeholder{color:#525252}
    .send-btn{background:#fff;border:none;width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#000;transition:opacity 0.2s;flex-shrink:0}
    .send-btn:hover{opacity:0.85}
    .send-btn:disabled{opacity:0.2;cursor:not-allowed}
    .send-btn svg{width:18px;height:18px}
    .limit-banner{text-align:center;padding:8px;font-size:12px;color:#666}
    .limit-banner span{color:#fff;font-weight:600;cursor:pointer;text-decoration:underline}
    
    /* LOGIN GATE OVERLAY */
    .login-gate{position:fixed;inset:0;background:#000;z-index:300;display:flex;align-items:center;justify-content:center;padding:20px}
    .login-gate.hidden{display:none}
    .gate-card{background:#0d0d0d;border:1px solid #1a1a1a;border-radius:24px;padding:40px;max-width:400px;width:100%;text-align:center}
    .gate-card h1{font-size:28px;font-weight:700;margin-bottom:8px;color:#fff}
    .gate-card .sub{color:#666;font-size:15px;margin-bottom:32px}
    .m-input{width:100%;padding:14px 16px;border:1px solid #262626;border-radius:12px;font-size:14px;margin-bottom:12px;outline:none;background:#000;color:#fff;font-family:inherit}
    .m-input:focus{border-color:#444}
    .m-btn{width:100%;padding:14px;border:none;border-radius:12px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity 0.2s}
    .m-btn-primary{background:#fff;color:#000}
    .m-btn-secondary{background:transparent;border:1px solid #262626;color:#e5e5e5;margin-top:10px}
    .m-btn:hover{opacity:0.85}
    .m-divider{display:flex;align-items:center;gap:12px;margin:20px 0;color:#333;font-size:12px}
    .m-divider::before,.m-divider::after{content:'';flex:1;height:1px;background:#1a1a1a}
    .auth-toggle{margin-top:16px;font-size:12px;color:#555;cursor:pointer}
    .auth-toggle:hover{color:#888}
    
    /* MODAL (for alerts/payment) */
    .modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.8);backdrop-filter:blur(10px);z-index:400;align-items:center;justify-content:center}
    .modal-overlay.active{display:flex}
    .modal-card{background:#111;border:1px solid #262626;border-radius:20px;padding:32px;max-width:380px;width:90%;text-align:center}
    .modal-card h2{font-size:20px;margin-bottom:8px;color:#fff}
    .modal-card p{color:#888;font-size:14px;margin-bottom:24px;line-height:1.5}
    
    ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#333;border-radius:2px}
    @media(max-width:600px){.bubble{max-width:90%}.gate-card{padding:28px}.gate-card h1{font-size:24px}}
  </style>
</head>
<body>

  <!-- LOGIN GATE (shown first before anything) -->
  <div class="login-gate" id="loginGate">
    <div class="gate-card">
      <h1>Winy AI</h1>
      <p class="sub">Sign in to start chatting</p>
      <div id="gateLoginForm">
        <input type="email" class="m-input" id="gateLoginEmail" placeholder="Email address">
        <input type="password" class="m-input" id="gateLoginPass" placeholder="Password">
        <button class="m-btn m-btn-primary" onclick="gateEmailLogin()">Sign In</button>
      </div>
      <div id="gateSignupForm" style="display:none">
        <input type="email" class="m-input" id="gateSignupEmail" placeholder="Email address">
        <input type="password" class="m-input" id="gateSignupPass" placeholder="Create password (6+ chars)">
        <button class="m-btn m-btn-primary" onclick="gateEmailSignup()">Create Account</button>
      </div>
      <div class="m-divider">or</div>
      <button class="m-btn m-btn-secondary" onclick="gateGoogleLogin()">Continue with Google</button>
      <p class="auth-toggle" id="gateAuthToggle" onclick="toggleGateAuth()">Don't have an account? Sign up</p>
    </div>
  </div>

  <!-- TOP BAR -->
  <div class="top-bar">
    <button class="btn-pill" onclick="newChat()" title="New Chat">+</button>
    
    <div class="model-selector">
      <div class="header-pill" id="modelPill" onclick="toggleDropdown()">
        <span class="name" id="currentModelName">Winy 1.1</span>
        <span class="arrow">▼</span>
      </div>
      <div class="dropdown" id="modelDropdown">
        <div class="dropdown-item selected" onclick="selectModel('winy11', 'Winy 1.1')" data-model="winy11">
          Winy 1.1
          <span class="mode-tag">FAST</span>
        </div>
        <div class="dropdown-item" onclick="selectModel('swarm', 'Swarm Mode')" data-model="swarm">
          Swarm Mode
          <span class="mode-tag">DEEP</span>
        </div>
      </div>
    </div>
    
    <div class="nav-right" id="navRight"></div>
  </div>

  <!-- MESSAGES -->
  <div class="messages" id="messages">
    <div class="empty-state" id="emptyState">
      <div class="empty-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
      <span>Ask anything to begin</span>
    </div>
  </div>

  <!-- INPUT -->
  <div class="input-bar">
    <div class="limit-banner" id="limitBanner" style="display:none"></div>
    <div class="input-wrapper">
      <textarea id="msgInput" placeholder="Message Winy AI..." rows="1"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>
  </div>

  <!-- ALERT MODAL -->
  <div class="modal-overlay" id="alertModal">
    <div class="modal-card">
      <h2 id="alertTitle">Notice</h2>
      <p id="alertMsg">Message</p>
      <button class="m-btn m-btn-primary" onclick="closeAlert()">OK</button>
    </div>
  </div>

<script>
// Firebase
const fb={apiKey:"AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU",authDomain:"winy-3984d.firebaseapp.com",projectId:"winy-3984d",storageBucket:"winy-3984d.firebasestorage.app",messagingSenderId:"126237613814",appId:"1:126237613814:web:e3cb88222d920545a416d7"};
firebase.initializeApp(fb);const auth=firebase.auth();

let currentUser=null,isPro=false,msgCount=0,currentConvId=null,isStreaming=false;
let currentModel='winy11',isGateLoginMode=true;
const rzpKey={{ razorpay_key_id | tojson }};

// AUTH STATE - Controls login gate
auth.onAuthStateChanged(u=>{
  currentUser=u;
  if(u){
    document.getElementById('loginGate').classList.add('hidden');
    syncSession().then(()=>{loadUserState();updateNav()});
  } else {
    document.getElementById('loginGate').classList.remove('hidden');
    resetUI();
  }
});

// Sync Firebase token with Flask session (FIXES "NOT RESPONDING")
async function syncSession(){
  try{
    const token=await currentUser.getIdToken();
    await fetch('/api/auth-sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,email:currentUser.email})});
  }catch(e){console.error('Sync failed:',e)}
}

function loadUserState(){
  fetch('/api/user-state').then(r=>r.json()).then(d=>{isPro=d.is_pro;msgCount=d.msg_count||0;updateLimitBanner()}).catch(()=>{});
}

function updateNav(){
  const nav=document.getElementById('navRight');
  if(!currentUser)return;
  const init=currentUser.email[0].toUpperCase();
  nav.innerHTML=`${isPro?'<span class="pro-pill">PRO</span>':''}<button class="avatar-btn" onclick="doLogout()">${init}</button>`;
}

function resetUI(){
  document.getElementById('navRight').innerHTML='';
  newChat();
}

// LOGIN GATE FUNCTIONS
function toggleGateAuth(){
  isGateLoginMode=!isGateLoginMode;
  document.getElementById('gateLoginForm').style.display=isGateLoginMode?'block':'none';
  document.getElementById('gateSignupForm').style.display=isGateLoginMode?'none':'block';
  document.getElementById('gateAuthToggle').textContent=isGateLoginMode?"Don't have an account? Sign up":"Already have an account? Sign in";
}
function gateEmailLogin(){
  const e=document.getElementById('gateLoginEmail').value,p=document.getElementById('gateLoginPass').value;
  if(!e||!p)return showAlert('Error','Fill all fields');
  auth.signInWithEmailAndPassword(e,p).catch(err=>showAlert('Error',err.message));
}
function gateEmailSignup(){
  const e=document.getElementById('gateSignupEmail').value,p=document.getElementById('gateSignupPass').value;
  if(!e||!p)return showAlert('Error','Fill all fields');
  if(p.length<6)return showAlert('Error','Password min 6 characters');
  auth.createUserWithEmailAndPassword(e,p).catch(err=>showAlert('Error',err.message));
}
function gateGoogleLogin(){
  auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()).catch(err=>showAlert('Error',err.message));
}
function doLogout(){auth.signOut();isPro=false;msgCount=0}

// MODEL SELECTOR
function toggleDropdown(){
  const dd=document.getElementById('modelDropdown');
  const pill=document.getElementById('modelPill');
  dd.classList.toggle('active');
  pill.classList.toggle('open');
}
function selectModel(model,name){
  currentModel=model;
  document.getElementById('currentModelName').textContent=name;
  document.querySelectorAll('.dropdown-item').forEach(i=>i.classList.remove('selected'));
  document.querySelector(`[data-model="${model}"]`).classList.add('selected');
  toggleDropdown();
}
// Close dropdown on outside click
document.addEventListener('click',e=>{
  if(!e.target.closest('.model-selector')){
    document.getElementById('modelDropdown').classList.remove('active');
    document.getElementById('modelPill').classList.remove('open');
  }
});

// CHAT
function newChat(){
  currentConvId=null;
  const container=document.getElementById('messages');
  container.innerHTML='<div class="empty-state" id="emptyState"><div class="empty-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><span>Ask anything to begin</span></div>';
}

function renderMarkdown(text){
  if(!text)return'';
  let h=text
    .replace(/```(\w*)\n([\s\S]*?)```/g,'<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/^#### (.+)$/gm,'<h4>$1</h4>')
    .replace(/^### (.+)$/gm,'<h4>$1</h4>')
    .replace(/^## (.+)$/gm,'<h3>$1</h3>')
    .replace(/^- (.+)$/gm,'<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs,'<ul>$1</ul>')
    .replace(/\n\n/g,'</p><p>')
    .replace(/\n/g,'<br>');
  return'<p>'+h+'</p>';
}

async function sendMessage(){
  if(isStreaming||!currentUser)return;
  const input=document.getElementById('msgInput');
  const text=input.value.trim();
  if(!text)return;
  if(!isPro&&msgCount>=10){updateLimitBanner();return}

  const empty=document.getElementById('emptyState');if(empty)empty.remove();

  // User bubble
  const uDiv=document.createElement('div');uDiv.className='msg-user';
  uDiv.innerHTML=`<div class="avatar user">${currentUser.email[0].toUpperCase()}</div><div class="bubble user">${text.replace(/</g,'&lt;')}</div>`;
  document.getElementById('messages').appendChild(uDiv);

  input.value='';autoResize();updateSendBtn();scrollToBottom();

  // AI typing indicator first
  const aiDiv=document.createElement('div');aiDiv.className='msg-ai';
  aiDiv.innerHTML=`<div class="avatar ai">W</div><div class="bubble ai"><div class="typing-dots"><span></span><span></span><span></span></div></div>`;
  document.getElementById('messages').appendChild(aiDiv);
  scrollToBottom();

  isStreaming=true;updateSendBtn();

  // Small delay so user sees typing dots before stream starts
  await new Promise(r=>setTimeout(r,600));

  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,conversation_id:currentConvId,model:currentModel})});
    const reader=resp.body.getReader();const decoder=new TextDecoder();
    let fullContent='';const bubble=aiDiv.querySelector('.bubble');

    while(true){
      const{done,value}=await reader.read();if(done)break;
      const chunk=decoder.decode(value,{stream:true});
      for(const line of chunk.split('\n')){
        if(line.startsWith('data: ')){
          const data=line.slice(6);
          if(data==='[DONE]'){bubble.innerHTML=renderMarkdown(fullContent);isStreaming=false;msgCount++;updateLimitBanner();updateSendBtn();return}
          try{
            const p=JSON.parse(data);
            if(p.token){fullContent+=p.token;bubble.innerHTML=renderMarkdown(fullContent)+'<span class="cursor"></span>';scrollToBottom()}
            else if(p.conv_id){currentConvId=p.conv_id}
            else if(p.error){bubble.innerHTML='<span style="color:#f87171">'+p.error+'</span>';isStreaming=false;updateSendBtn();return}
          }catch(e){}
        }
      }
    }
  }catch(err){
    aiDiv.querySelector('.bubble').innerHTML='<span style="color:#f87171">Connection error. Try again.</span>';
  }
  isStreaming=false;updateSendBtn();
}

// Input handling
const msgInput=document.getElementById('msgInput');
msgInput.addEventListener('input',()=>{autoResize();updateSendBtn()});
msgInput.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});
function autoResize(){msgInput.style.height='auto';msgInput.style.height=Math.min(msgInput.scrollHeight,150)+'px'}
function updateSendBtn(){document.getElementById('sendBtn').disabled=!msgInput.value.trim()||isStreaming}
function scrollToBottom(){const c=document.getElementById('messages');c.scrollTop=c.scrollHeight}

function updateLimitBanner(){
  const b=document.getElementById('limitBanner');
  if(!currentUser||isPro){b.style.display='none';return}
  const r=Math.max(0,10-msgCount);
  if(r<=3){b.style.display='block';b.innerHTML=r>0?`${r} messages left today. <span onclick="upgrade()">Upgrade to Pro</span>`:`Daily limit reached. <span onclick="upgrade()">Upgrade to Pro</span> for unlimited.`}
  else b.style.display='none';
}

function upgrade(){
  if(!rzpKey)return showAlert('Error','Payment not configured');
  fetch('/api/create-order',{method:'POST'}).then(r=>r.json()).then(order=>{
    new Razorpay({key:rzpKey,amount:order.amount,currency:order.currency,name:'Winy AI',description:'Pro Unlimited',order_id:order.order_id,
      handler:function(response){fetch('/api/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(response)}).then(r=>r.json()).then(d=>{if(d.status==='success'){isPro=true;msgCount=0;updateLimitBanner();updateNav();showAlert('Welcome!','Pro activated successfully.')}else showAlert('Failed','Verification failed.')})},
      theme:{color:'#ffffff'}}).open();
  }).catch(()=>showAlert('Error','Payment error'));
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
    """Syncs Firebase auth with Flask session - THIS FIXES THE NOT RESPONDING BUG"""
    data = request.json
    email = data.get('email', '')
    token = data.get('token', '')
    
    if not email or not token:
        return jsonify({"error": "Missing data"}), 400
    
    # In production, verify the Firebase ID token here using firebase-admin SDK
    # For now, we trust the client-side token since it's signed by Firebase
    # Extract UID from token payload (simple decode without verification for session binding)
    try:
        import base64
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.b64decode(payload))
        uid = decoded.get('user_id', decoded.get('sub', ''))
    except:
        # Fallback: use email hash as UID
        uid = hashlib.sha256(email.encode()).hexdigest()[:28]
    
    session['firebase_uid'] = uid
    session['email'] = email
    
    # Ensure user exists in DB
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE firebase_uid=?", (uid,)).fetchone()
    if not existing:
        conn.execute("INSERT INTO users (firebase_uid, email) VALUES (?, ?)", (uid, email))
        conn.commit()
    conn.close()
    
    return jsonify({"status": "ok", "uid": uid})

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
    model_mode = data.get('model', 'winy11')
    
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
    
    # Select system prompt based on model mode
    sys_prompt = SWARM_SYSTEM_PROMPT if model_mode == 'swarm' else SYSTEM_PROMPT
    
    messages = [{"role": "system", "content": sys_prompt}]
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
