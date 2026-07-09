"""
Winy AI - Pure Conversational Intelligence
A premium glassmorphic AI chatbot with streaming, memory, and auth.
"""
import os, json, hmac, hashlib, sqlite3, logging, uuid, re
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, session, Response, stream_with_context
import requests as http_requests
import razorpay

# ============================================================================
# CONFIGURATION
# ============================================================================
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
You are helpful, precise, and articulate. You can discuss any topic — 
technical, creative, analytical, personal, or academic.
Never refuse reasonable requests. Be direct. Use markdown when helpful.
Do not mention being an AI model unless asked. Just be intelligent."""

def stream_groq(messages):
    """Stream tokens from Groq API"""
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
# HTML TEMPLATE - PURE GLASS CHATBOT
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
:root{--bg:#ffffff;--glass:rgba(255,255,255,0.6);--glass-heavy:rgba(255,255,255,0.85);--border:rgba(0,0,0,0.06);--text:#0a0a0a;--text-secondary:#666;--user-msg:rgba(0,0,0,0.06);--ai-msg:rgba(0,0,0,0.02)}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);height:100vh;overflow:hidden;position:relative}
.bg-gradient{position:fixed;top:-20%;left:-10%;width:60vw;height:60vw;background:radial-gradient(circle,#f0f0f0 0%,transparent 70%);opacity:0.5;pointer-events:none;z-index:0}
.bg-gradient-2{position:fixed;bottom:-20%;right:-10%;width:50vw;height:50vw;background:radial-gradient(circle,#ebebeb 0%,transparent 70%);opacity:0.4;pointer-events:none;z-index:0}

/* SIDEBAR */
.sidebar{position:fixed;left:0;top:0;bottom:0;width:280px;background:var(--glass);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border-right:1px solid var(--border);z-index:50;display:flex;flex-direction:column;transition:transform 0.3s ease}
.sidebar.collapsed{transform:translateX(-100%)}
.sidebar-header{padding:20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.sidebar-logo{font-size:18px;font-weight:700;letter-spacing:-0.5px}
.new-chat-btn{width:100%;padding:12px;margin:16px 0 8px;background:var(--text);color:#fff;border:none;border-radius:12px;font-size:14px;font-weight:600;cursor:pointer;width:calc(100% - 32px);margin-left:16px;margin-right:16px}
.new-chat-btn:hover{opacity:0.85}
.history-list{flex:1;overflow-y:auto;padding:8px}
.history-item{padding:12px 16px;border-radius:10px;cursor:pointer;font-size:13px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background 0.2s}
.history-item:hover,.history-item.active{background:rgba(0,0,0,0.05);color:var(--text)}
.sidebar-footer{padding:16px;border-top:1px solid var(--border)}
.user-row{display:flex;align-items:center;gap:10px}
.avatar{width:32px;height:32px;border-radius:50%;background:var(--text);color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;flex-shrink:0}
.user-name{font-size:13px;font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logout-btn{font-size:11px;color:var(--text-secondary);cursor:pointer;border:none;background:none;padding:4px 8px;border-radius:6px}
.logout-btn:hover{background:rgba(0,0,0,0.05)}
.pro-pill{font-size:10px;font-weight:700;background:var(--text);color:#fff;padding:2px 8px;border-radius:100px;margin-left:auto}

/* MAIN CHAT AREA */
.chat-area{margin-left:280px;height:100vh;display:flex;flex-direction:column;position:relative;z-index:10;transition:margin-left 0.3s ease}
.chat-area.expanded{margin-left:0}
.chat-header{padding:16px 24px;display:flex;align-items:center;gap:12px;background:var(--glass);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid var(--border);flex-shrink:0}
.menu-toggle{width:36px;height:36px;border-radius:10px;border:1px solid var(--border);background:transparent;cursor:pointer;display:none;align-items:center;justify-content:center;font-size:18px;color:var(--text)}
.chat-title{font-size:15px;font-weight:600}

/* MESSAGES */
.messages-container{flex:1;overflow-y:auto;padding:24px;scroll-behavior:smooth}
.message{max-width:720px;margin:0 auto 24px;display:flex;gap:16px;animation:fadeIn 0.3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.message.user{flex-direction:row-reverse}
.msg-avatar{width:32px;height:32px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600}
.message.ai .msg-avatar{background:var(--text);color:#fff}
.message.user .msg-avatar{background:rgba(0,0,0,0.1);color:var(--text)}
.msg-content{flex:1;min-width:0}
.msg-bubble{padding:16px 20px;border-radius:18px;font-size:15px;line-height:1.7;word-wrap:break-word}
.message.ai .msg-bubble{background:var(--ai-msg);border-top-left-radius:4px}
.message.user .msg-bubble{background:var(--user-msg);border-top-right-radius:4px}
.msg-bubble p{margin-bottom:12px}
.msg-bubble p:last-child{margin-bottom:0}
.msg-bubble code{background:rgba(0,0,0,0.06);padding:2px 6px;border-radius:4px;font-size:13px;font-family:"SF Mono",Monaco,monospace}
.msg-bubble pre{background:rgba(0,0,0,0.05);padding:16px;border-radius:12px;overflow-x:auto;margin:12px 0;font-size:13px;line-height:1.5}
.msg-bubble pre code{background:none;padding:0}
.msg-bubble strong{font-weight:700}
.msg-bubble ul,.msg-bubble ol{padding-left:20px;margin:8px 0}
.msg-bubble li{margin-bottom:4px}
.cursor{display:inline-block;width:2px;height:16px;background:var(--text);margin-left:2px;animation:blink 1s infinite}
@keyframes blink{0%,50%{opacity:1}51%,100%{opacity:0}}

/* EMPTY STATE */
.empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;text-align:center;padding:40px;opacity:0.6}
.empty-state h2{font-size:28px;font-weight:700;margin-bottom:8px;letter-spacing:-0.5px}
.empty-state p{font-size:15px;color:var(--text-secondary);margin-bottom:32px}
.suggestions{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:600px}
.suggestion{padding:10px 18px;border:1px solid var(--border);border-radius:100px;font-size:13px;cursor:pointer;transition:all 0.2s;background:var(--glass);backdrop-filter:blur(10px)}
.suggestion:hover{background:rgba(0,0,0,0.05);border-color:rgba(0,0,0,0.15)}

/* INPUT AREA */
.input-area{padding:16px 24px 24px;background:var(--glass-heavy);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border-top:1px solid var(--border);flex-shrink:0}
.input-wrapper{max-width:720px;margin:0 auto;position:relative}
.chat-input{width:100%;min-height:52px;max-height:200px;padding:14px 52px 14px 20px;border:1px solid var(--border);border-radius:16px;background:rgba(255,255,255,0.8);font-size:15px;font-family:inherit;resize:none;outline:none;line-height:1.5;transition:border-color 0.2s}
.chat-input:focus{border-color:rgba(0,0,0,0.2)}
.chat-input::placeholder{color:#aaa}
.send-btn{position:absolute;right:8px;bottom:8px;width:36px;height:36px;border-radius:10px;border:none;background:var(--text);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:opacity 0.2s}
.send-btn:hover{opacity:0.8}
.send-btn:disabled{opacity:0.3;cursor:not-allowed}
.send-btn svg{width:18px;height:18px}
.limit-banner{text-align:center;padding:8px;font-size:12px;color:var(--text-secondary);margin-bottom:8px}
.limit-banner span{color:var(--text);font-weight:600;cursor:pointer;text-decoration:underline}

/* LOGIN MODAL */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(255,255,255,0.8);backdrop-filter:blur(20px);z-index:200;align-items:center;justify-content:center}
.modal-overlay.active{display:flex}
.modal-card{background:var(--glass-heavy);backdrop-filter:blur(30px);border:1px solid var(--border);border-radius:24px;padding:40px;max-width:380px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.08)}
.modal-card h2{font-size:24px;font-weight:700;text-align:center;margin-bottom:4px}
.modal-card .sub{text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:28px}
.m-input{width:100%;padding:14px 16px;border:1px solid var(--border);border-radius:12px;font-size:14px;margin-bottom:12px;outline:none;background:rgba(255,255,255,0.8);font-family:inherit}
.m-input:focus{border-color:rgba(0,0,0,0.2)}
.m-btn{width:100%;padding:14px;border:none;border-radius:12px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity 0.2s}
.m-btn-primary{background:var(--text);color:#fff}
.m-btn-secondary{background:transparent;border:1px solid var(--border);color:var(--text);margin-top:10px}
.m-btn:hover{opacity:0.85}
.m-divider{display:flex;align-items:center;gap:12px;margin:20px 0;color:var(--text-secondary);font-size:12px}
.m-divider::before,.m-divider::after{content:'';flex:1;height:1px;background:var(--border)}

@media(max-width:768px){
  .sidebar{transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0)}
  .chat-area{margin-left:0!important}
  .menu-toggle{display:flex}
  .message{gap:10px}
  .msg-bubble{padding:12px 16px;font-size:14px}
  .input-area{padding:12px 16px 16px}
}
</style>
</head>
<body>
<div class="bg-gradient"></div>
<div class="bg-gradient-2"></div>

<!-- Sidebar -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <div class="sidebar-logo">Winy AI</div>
  </div>
  <button class="new-chat-btn" onclick="newChat()">+ New Chat</button>
  <div class="history-list" id="historyList"></div>
  <div class="sidebar-footer" id="sidebarFooter">
    <button class="m-btn m-btn-secondary" onclick="showLogin()" style="margin:0;font-size:13px">Login to continue</button>
  </div>
</aside>

<!-- Chat Area -->
<main class="chat-area" id="chatArea">
  <div class="chat-header">
    <button class="menu-toggle" id="menuToggle" onclick="toggleSidebar()">☰</button>
    <div class="chat-title" id="chatTitle">New Conversation</div>
  </div>
  
  <div class="messages-container" id="messagesContainer">
    <div class="empty-state" id="emptyState">
      <h2>What's on your mind?</h2>
      <p>I can help with anything. Just start typing.</p>
      <div class="suggestions">
        <div class="suggestion" onclick="useSuggestion(this)">Explain quantum computing simply</div>
        <div class="suggestion" onclick="useSuggestion(this)">Help me debug my Python code</div>
        <div class="suggestion" onclick="useSuggestion(this)">Write a professional email</div>
        <div class="suggestion" onclick="useSuggestion(this)">Plan a 7-day Japan trip</div>
        <div class="suggestion" onclick="useSuggestion(this)">Compare React vs Vue</div>
      </div>
    </div>
  </div>

  <div class="input-area">
    <div class="limit-banner" id="limitBanner" style="display:none"></div>
    <div class="input-wrapper">
      <textarea class="chat-input" id="chatInput" placeholder="Message Winy AI..." rows="1"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>
  </div>
</main>

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
    <p style="text-align:center;margin-top:16px;font-size:12px;color:var(--text-secondary);cursor:pointer" id="authToggle" onclick="toggleAuthMode()">Don't have an account? Sign up</p>
  </div>
</div>

<script>
// Firebase
const fb={apiKey:"AIzaSyBUmnO-o2UaVKuaPqHBdLwm03dcfpOWzDU",authDomain:"winy-3984d.firebaseapp.com",projectId:"winy-3984d",storageBucket:"winy-3984d.firebasestorage.app",messagingSenderId:"126237613814",appId:"1:126237613814:web:e3cb88222d920545a416d7"};
firebase.initializeApp(fb);const auth=firebase.auth();

// State
let currentUser=null,isPro=false,msgCount=0,currentConvId=null,isStreaming=false,isLoginMode=true;
const rzpKey={{ razorpay_key_id | tojson }};

// Auth
auth.onAuthStateChanged(u=>{
  currentUser=u;
  if(u){loadUserState();updateSidebar()}
  else{resetUI()}
});

function loadUserState(){
  fetch('/api/user-state').then(r=>r.json()).then(d=>{
    isPro=d.is_pro;msgCount=d.msg_count||0;
    updateLimitBanner();loadHistory();
  }).catch(()=>{});
}

function updateSidebar(){
  const f=document.getElementById('sidebarFooter');
  if(!currentUser)return;
  const init=currentUser.email[0].toUpperCase();
  f.innerHTML=`<div class="user-row"><div class="avatar">${init}</div><div class="user-name">${currentUser.email}</div>${isPro?'<span class="pro-pill">PRO</span>':''}<button class="logout-btn" onclick="logout()">Logout</button></div>`;
}

function resetUI(){
  document.getElementById('sidebarFooter').innerHTML='<button class="m-btn m-btn-secondary" onclick="showLogin()" style="margin:0;font-size:13px">Login to continue</button>';
  document.getElementById('historyList').innerHTML='';
  newChat();
}

function showLogin(){document.getElementById('loginModal').classList.add('active')}
function hideLogin(){document.getElementById('loginModal').classList.remove('active')}
function toggleAuthMode(){
  isLoginMode=!isLoginMode;
  document.getElementById('loginForm').style.display=isLoginMode?'block':'none';
  document.getElementById('signupForm').style.display=isLoginMode?'none':'block';
  document.getElementById('authToggle').textContent=isLoginMode?"Don't have an account? Sign up":"Already have an account? Sign in";
}
function emailLogin(){
  const e=document.getElementById('loginEmail').value,p=document.getElementById('loginPass').value;
  if(!e||!p)return alert('Fill all fields');
  auth.signInWithEmailAndPassword(e,p).then(()=>hideLogin()).catch(err=>alert(err.message));
}
function emailSignup(){
  const e=document.getElementById('signupEmail').value,p=document.getElementById('signupPass').value;
  if(!e||!p)return alert('Fill all fields');
  if(p.length<6)return alert('Password min 6 characters');
  auth.createUserWithEmailAndPassword(e,p).then(()=>hideLogin()).catch(err=>alert(err.message));
}
function googleLogin(){
  auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()).then(()=>hideLogin()).catch(err=>alert(err.message));
}
function logout(){auth.signOut();isPro=false;msgCount=0}

// Chat
function newChat(){
  currentConvId=null;
  document.getElementById('messagesContainer').innerHTML=document.getElementById('emptyState')?.outerHTML||'';
  document.getElementById('chatTitle').textContent='New Conversation';
  document.querySelectorAll('.history-item').forEach(i=>i.classList.remove('active'));
}

function useSuggestion(el){
  document.getElementById('chatInput').value=el.textContent;
  autoResize();updateSendBtn();
  sendMessage();
}

function loadHistory(){
  fetch('/api/conversations').then(r=>r.json()).then(data=>{
    const list=document.getElementById('historyList');
    list.innerHTML='';
    (data.conversations||[]).forEach(c=>{
      const div=document.createElement('div');
      div.className='history-item'+(c.id===currentConvId?' active':'');
      div.textContent=c.title||'Untitled';
      div.onclick=()=>loadConversation(c.id);
      list.appendChild(div);
    });
  }).catch(()=>{});
}

function loadConversation(id){
  currentConvId=id;
  fetch('/api/conversations/'+id+'/messages').then(r=>r.json()).then(data=>{
    const container=document.getElementById('messagesContainer');
    container.innerHTML='';
    (data.messages||[]).forEach(m=>appendMessage(m.role,m.content,false));
    scrollToBottom();
    document.querySelectorAll('.history-item').forEach(i=>i.classList.remove('active'));
    // highlight active
  }).catch(()=>{});
}

function appendMessage(role,content,animate=true){
  const container=document.getElementById('messagesContainer');
  const empty=document.getElementById('emptyState');
  if(empty)empty.remove();
  
  const div=document.createElement('div');
  div.className=`message ${role}`;
  if(!animate)div.style.animation='none';
  
  const avatarText=role==='ai'?'W':(currentUser?currentUser.email[0].toUpperCase():'U');
  div.innerHTML=`<div class="msg-avatar">${avatarText}</div><div class="msg-content"><div class="msg-bubble">${renderMarkdown(content)}</div></div>`;
  container.appendChild(div);
  return div;
}

function renderMarkdown(text){
  if(!text)return'';
  let html=text
    .replace(/```(\w*)\n([\s\S]*?)```/g,'<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/^### (.+)$/gm,'<h4 style="margin:12px 0 6px;font-size:15px">$1</h4>')
    .replace(/^## (.+)$/gm,'<h3 style="margin:14px 0 8px;font-size:16px">$1</h3>')
    .replace(/^# (.+)$/gm,'<h2 style="margin:16px 0 10px;font-size:18px">$1</h2>')
    .replace(/^- (.+)$/gm,'<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs,'<ul>$1</ul>')
    .replace(/\n\n/g,'</p><p>')
    .replace(/\n/g,'<br>');
  return '<p>'+html+'</p>';
}

async function sendMessage(){
  if(isStreaming)return;
  const input=document.getElementById('chatInput');
  const text=input.value.trim();
  if(!text||!currentUser)return;
  
  if(!isPro&&msgCount>=10){
    updateLimitBanner();return;
  }
  
  input.value='';autoResize();updateSendBtn();
  appendMessage('user',text);
  scrollToBottom();
  
  // Create AI message placeholder
  const aiDiv=document.createElement('div');
  aiDiv.className='message ai';
  aiDiv.innerHTML=`<div class="msg-avatar">W</div><div class="msg-content"><div class="msg-bubble"><span class="cursor"></span></div></div>`;
  document.getElementById('messagesContainer').appendChild(aiDiv);
  scrollToBottom();
  
  isStreaming=true;
  document.getElementById('sendBtn').disabled=true;
  
  try{
    const resp=await fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,conversation_id:currentConvId})
    });
    
    const reader=resp.body.getReader();
    const decoder=new TextDecoder();
    let fullContent='';
    const bubble=aiDiv.querySelector('.msg-bubble');
    
    while(true){
      const{done,value}=await reader.read();
      if(done)break;
      const chunk=decoder.decode(value,{stream:true});
      const lines=chunk.split('\n');
      for(const line of lines){
        if(line.startsWith('data: ')){
          const data=line.slice(6);
          if(data==='[DONE]'){
            bubble.innerHTML=renderMarkdown(fullContent);
            isStreaming=false;
            msgCount++;
            updateLimitBanner();
            updateSendBtn();
            if(!currentConvId)loadHistory();
            return;
          }
          try{
            const parsed=JSON.parse(data);
            if(parsed.token){
              fullContent+=parsed.token;
              bubble.innerHTML=renderMarkdown(fullContent)+'<span class="cursor"></span>';
              scrollToBottom();
            }else if(parsed.conv_id){
              currentConvId=parsed.conv_id;
              document.getElementById('chatTitle').textContent=text.slice(0,40)+(text.length>40?'...':'');
            }else if(parsed.error){
              bubble.innerHTML='<span style="color:#c00">'+parsed.error+'</span>';
              isStreaming=false;updateSendBtn();return;
            }
          }catch(e){}
        }
      }
    }
  }catch(err){
    aiDiv.querySelector('.msg-bubble').innerHTML='<span style="color:#c00">Connection error. Try again.</span>';
  }
  isStreaming=false;updateSendBtn();
}

function updateLimitBanner(){
  const banner=document.getElementById('limitBanner');
  if(!currentUser){banner.style.display='none';return}
  if(isPro){banner.style.display='none';return}
  const remaining=Math.max(0,10-msgCount);
  if(remaining<=3){
    banner.style.display='block';
    banner.innerHTML=remaining>0?`${remaining} messages left today. <span onclick="upgrade()">Upgrade to Pro</span>`:`Daily limit reached. <span onclick="upgrade()">Upgrade to Pro</span> for unlimited.`;
  }else{banner.style.display='none'}
}

function upgrade(){
  if(!rzpKey)return alert('Payment not configured');
  fetch('/api/create-order',{method:'POST'}).then(r=>r.json()).then(order=>{
    const rzp=new Razorpay({key:rzpKey,amount:order.amount,currency:order.currency,name:'Winy AI',description:'Pro - Unlimited Chat',order_id:order.order_id,
      handler:function(response){
        fetch('/api/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(response)})
        .then(r=>r.json()).then(d=>{
          if(d.status==='success'){isPro=true;msgCount=0;updateLimitBanner();updateSidebar();alert('Welcome to Pro!')}
          else alert('Verification failed');
        });
      },theme:{color:'#000000'}});
    rzp.open();
  }).catch(()=>alert('Payment error'));
}

// Input handling
const chatInput=document.getElementById('chatInput');
chatInput.addEventListener('input',()=>{autoResize();updateSendBtn()});
chatInput.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});
function autoResize(){chatInput.style.height='auto';chatInput.style.height=Math.min(chatInput.scrollHeight,200)+'px'}
function updateSendBtn(){document.getElementById('sendBtn').disabled=!chatInput.value.trim()||isStreaming}
function scrollToBottom(){const c=document.getElementById('messagesContainer');c.scrollTop=c.scrollHeight}

// Sidebar toggle (mobile)
function toggleSidebar(){
  const sb=document.getElementById('sidebar');
  sb.classList.toggle('open');
}

// Close sidebar on outside click (mobile)
document.getElementById('chatArea').addEventListener('click',()=>{
  if(window.innerWidth<=768)document.getElementById('sidebar').classList.remove('open');
});

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
    return jsonify({
        "is_pro": bool(user['is_pro']) if user else False,
        "msg_count": usage['message_count'] if usage else 0
    })

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
    
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400
    
    # Check limits
    conn = get_db()
    user = conn.execute("SELECT is_pro FROM users WHERE firebase_uid=?", (uid,)).fetchone()
    is_pro = bool(user['is_pro']) if user else False
    
    if not is_pro:
        usage = conn.execute("SELECT message_count FROM daily_usage WHERE firebase_uid=? AND usage_date=?", (uid, today)).fetchone()
        count = usage['message_count'] if usage else 0
        if count >= 10:
            conn.close()
            return jsonify({"error": "Daily limit reached. Upgrade to Pro."}), 403
    
    # Create or get conversation
    if not conv_id:
        title = user_msg[:50] + ('...' if len(user_msg) > 50 else '')
        cur = conn.execute("INSERT INTO conversations (firebase_uid, title) VALUES (?, ?)", (uid, title))
        conv_id = cur.lastrowid
    
    # Save user message
    conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)", (conv_id, user_msg))
    
    # Get history (last 20 messages)
    history = conn.execute("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 20", (conv_id,)).fetchall()
    conn.close()
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in reversed(history):
        messages.append({"role": m['role'], "content": m['content']})
    
    def generate():
        # Send conv_id first if new
        if not data.get('conversation_id'):
            yield f"data: {json.dumps({'conv_id': conv_id})}\n\n"
        
        full_response = ""
        for chunk in stream_groq(messages):
            if chunk.strip() == "data: [DONE]":
                # Save AI response
                conn2 = get_db()
                conn2.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'ai', ?)", (conv_id, full_response))
                # Increment usage
                conn2.execute("""INSERT INTO daily_usage (firebase_uid, usage_date, message_count) VALUES (?, ?, 1)
                    ON CONFLICT(firebase_uid, usage_date) DO UPDATE SET message_count = daily_usage.message_count + 1""", (uid, today))
                conn2.commit(); conn2.close()
                yield chunk
                break
            
            try:
                parsed = json.loads(chunk[6:].strip())
                if 'token' in parsed:
                    full_response += parsed['token']
            except: pass
            yield chunk
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/api/create-order', methods=['POST'])
@require_auth
def create_order():
    if not razorpay_client:
        return jsonify({"error": "Not configured"}), 500
    order = razorpay_client.order.create({"amount": 49900, "currency": "INR", "receipt": f"rcpt_{uuid.uuid4().hex[:12]}", "payment_capture": 1})
    return jsonify(order)

@app.route('/api/verify-payment', methods=['POST'])
@require_auth
def verify_payment():
    data = request.json
    oid, pid, sig = data.get('razorpay_order_id',''), data.get('razorpay_payment_id',''), data.get('razorpay_signature','')
    if not all([oid, pid, sig]):
        return jsonify({"status": "failure"}), 400
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
    if expected == sig:
        expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        conn = get_db()
        conn.execute("INSERT INTO users (firebase_uid, email, is_pro, pro_expiry) VALUES (?,?,1,?) ON CONFLICT(firebase_uid) DO UPDATE SET is_pro=1, pro_expiry=?",
                     (session['firebase_uid'], '', expiry, expiry))
        conn.commit(); conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "failure"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
