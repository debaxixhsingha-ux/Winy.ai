from flask import Flask, request, jsonify, render_template_string, session
import requests
import re
import os
import razorpay
import hmac
import hashlib

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "winy-ai-secret-key-2024")

# Groq API Configuration
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

# Razorpay Configuration
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

def clean_text(text):
    text = text.replace('**', '').replace('*', '').replace('_', '')
    text = re.sub(r'#+\s*', '', text)
    return text.strip()

def call_llm(system_prompt, user_prompt, temperature=0.7):
    try:
        response = requests.post(GROQ_URL, headers=GROQ_HEADERS, json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": 2000
        }, timeout=90)
        
        result = response.json()
        if 'choices' in result and len(result['choices']) > 0:
            return clean_text(result['choices'][0]['message']['content'])
        return "The swarm encountered a rate limit. Please try again."
    except Exception as e:
        return f"Connection error: {str(e)}"

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Winy AI | Enterprise Strategy Swarm</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        :root {
            --bg: #ffffff;
            --glass-bg: rgba(0, 0, 0, 0.02);
            --glass-border: rgba(0, 0, 0, 0.08);
            --glass-highlight: rgba(255, 255, 255, 0.8);
            --text: #000000;
            --text-muted: #666666;
            --accent: #000000;
            --accent-text: #ffffff;
            --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            background-color: var(--bg);
            color: var(--text);
            font-family: var(--font);
            min-height: 100vh;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
            position: relative;
            overflow-x: hidden;
        }

        .bg-shape {
            position: fixed;
            border-radius: 50%;
            filter: blur(100px);
            z-index: 0;
            pointer-events: none;
        }
        .shape-1 { width: 500px; height: 500px; background: #f0f0f0; top: -100px; left: -100px; }
        .shape-2 { width: 400px; height: 400px; background: #e5e5e5; bottom: -100px; right: -50px; }

        h1, h2, h3 { font-weight: 700; letter-spacing: -0.02em; }

        nav {
            position: fixed;
            top: 24px;
            left: 50%;
            transform: translateX(-50%);
            width: 90%;
            max-width: 900px;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 100;
            background: rgba(255, 255, 255, 0.6);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 100px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
        }
        .logo { font-size: 16px; font-weight: 700; letter-spacing: -0.5px; display: flex; align-items: center; gap: 8px; }
        .logo svg { width: 18px; height: 18px; }

        .btn-pro {
            background: rgba(0, 0, 0, 0.05);
            border: 1px solid rgba(0, 0, 0, 0.1);
            color: var(--text);
            padding: 8px 16px;
            border-radius: 100px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .btn-pro:hover { background: rgba(0, 0, 0, 0.1); border-color: rgba(0, 0, 0, 0.2); }

        .container { max-width: 900px; margin: 0 auto; padding: 120px 24px 60px; position: relative; z-index: 1; }

        .hero { margin-bottom: 48px; text-align: center; }
        .hero h1 { font-size: 48px; line-height: 1.1; margin-bottom: 12px; letter-spacing: -1.5px; }
        .hero p { color: var(--text-muted); font-size: 16px; max-width: 500px; margin: 0 auto; }

        .glass-card {
            background: var(--glass-bg);
            backdrop-filter: blur(40px);
            -webkit-backdrop-filter: blur(40px);
            border-top: 1px solid var(--glass-highlight);
            border-left: 1px solid rgba(255, 255, 255, 0.5);
            border-right: 1px solid rgba(0, 0, 0, 0.05);
            border-bottom: 1px solid rgba(0, 0, 0, 0.1);
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.06), inset 0 0 0 1px rgba(0, 0, 0, 0.03);
            border-radius: 32px;
            padding: 48px;
            margin-bottom: 40px;
        }

        .main-input {
            width: 100%;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            color: var(--text);
            font-size: 16px;
            font-family: var(--font);
            padding: 20px 24px;
            border-radius: 16px;
            resize: none;
            outline: none;
            transition: all 0.3s ease;
            min-height: 80px;
            margin-bottom: 20px;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.02);
        }
        .main-input:focus { background: rgba(0, 0, 0, 0.05); border-color: rgba(0, 0, 0, 0.2); }
        .main-input::placeholder { color: #999; }

        .options-slider {
            display: flex;
            gap: 16px;
            overflow-x: auto;
            padding-bottom: 20px;
            margin-bottom: 20px;
            scrollbar-width: none;
        }
        .options-slider::-webkit-scrollbar { display: none; }

        .option-card {
            flex: 0 0 auto;
            min-width: 180px;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 16px;
            transition: all 0.2s;
        }
        .option-card:hover { border-color: rgba(0, 0, 0, 0.2); }

        .option-label {
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: block;
        }

        .option-select {
            width: 100%;
            background: transparent;
            border: none;
            color: var(--text);
            font-size: 14px;
            font-family: var(--font);
            outline: none;
            cursor: pointer;
            appearance: none;
        }

        .btn-launch {
            width: 100%;
            background: rgba(0, 0, 0, 0.05);
            backdrop-filter: blur(20px);
            border-top: 1px solid rgba(255, 255, 255, 0.5);
            border-left: 1px solid rgba(255, 255, 255, 0.2);
            border-right: 1px solid rgba(0, 0, 0, 0.1);
            border-bottom: 1px solid rgba(0, 0, 0, 0.2);
            border-radius: 16px;
            padding: 22px;
            font-size: 15px;
            font-weight: 600;
            color: var(--text);
            cursor: pointer;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            letter-spacing: 0.5px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.05), inset 0 1px 0 rgba(255,255,255,0.4);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn-launch:hover {
            background: var(--accent);
            color: var(--accent-text);
            border-color: var(--accent);
            box-shadow: 0 15px 40px rgba(0, 0, 0, 0.2);
            transform: translateY(-2px);
        }
        .btn-launch:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

        .swarm-loader {
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 80px 0;
            position: relative;
            height: 300px;
        }
        .swarm-loader.active { display: flex; }

        .swarm-core {
            width: 20px;
            height: 20px;
            background: var(--accent);
            border-radius: 50%;
            position: relative;
            z-index: 10;
            box-shadow: 0 0 20px rgba(0,0,0,0.2);
            animation: pulse-core 1.5s infinite ease-in-out;
        }
        @keyframes pulse-core { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.2); } }

        .robot {
            position: absolute;
            width: 24px;
            height: 24px;
            top: 50%;
            left: 50%;
            margin-top: -12px;
            margin-left: -12px;
            animation: gather-and-orbit 3s infinite ease-in-out;
        }
        .robot svg { width: 100%; height: 100%; fill: var(--text-muted); }
        
        .robot:nth-child(2) { animation-delay: 0s; }
        .robot:nth-child(3) { animation-delay: 0.5s; }
        .robot:nth-child(4) { animation-delay: 1s; }
        .robot:nth-child(5) { animation-delay: 1.5s; }
        .robot:nth-child(6) { animation-delay: 2s; }
        .robot:nth-child(7) { animation-delay: 2.5s; }

        @keyframes gather-and-orbit {
            0% { transform: translate(0, 0) rotate(0deg) scale(0.5); opacity: 0; }
            30% { transform: translate(var(--tx), var(--ty)) rotate(180deg) scale(1); opacity: 1; }
            100% { transform: translate(var(--tx), var(--ty)) rotate(360deg) scale(1); opacity: 1; }
        }

        .swarm-text {
            margin-top: 40px;
            font-size: 12px;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-muted);
            animation: fade-text 2s infinite;
        }
        @keyframes fade-text { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }

        .results-area { display: none; animation: fadeIn 0.6s ease; }
        .results-area.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

        .results-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--glass-border);
        }
        .results-header h2 { font-size: 18px; font-weight: 600; }

        .btn-icon {
            background: transparent;
            border: 1px solid var(--glass-border);
            color: var(--text);
            width: 36px; height: 36px;
            border-radius: 100px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: all 0.2s;
        }
        .btn-icon:hover { border-color: var(--accent); background: rgba(0,0,0,0.05); }
        .btn-icon svg { width: 16px; height: 16px; stroke-width: 2; }

        .unified-summary {
            font-size: 16px;
            line-height: 1.7;
            color: #333;
            margin-bottom: 40px;
            padding-bottom: 40px;
            border-bottom: 1px solid var(--glass-border);
        }

        .accordion { margin-bottom: 40px; }
        .accordion-item { border-bottom: 1px solid var(--glass-border); }

        .accordion-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 24px 0;
            cursor: pointer;
            transition: color 0.2s;
        }
        .accordion-header:hover { color: #000; }
        .accordion-title { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 12px; }
        .accordion-title svg { width: 18px; height: 18px; stroke-width: 1.5; color: var(--text-muted); }

        .accordion-icon { width: 20px; height: 20px; transition: transform 0.3s ease; }
        .accordion-item.active .accordion-icon { transform: rotate(90deg); }

        .accordion-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.4s ease, padding 0.4s ease;
        }
        .accordion-item.active .accordion-content { max-height: 1000px; padding-bottom: 24px; }
        .accordion-text { font-size: 15px; line-height: 1.8; color: #555; white-space: pre-wrap; }

        .cost-section { margin: 40px 0; }
        .cost-slider { display: flex; gap: 16px; overflow-x: auto; padding: 20px 0; scrollbar-width: none; }
        .cost-slider::-webkit-scrollbar { display: none; }

        .cost-card {
            flex: 0 0 auto; min-width: 180px;
            background: var(--glass-bg); border: 1px solid var(--glass-border);
            border-radius: 16px; padding: 20px;
        }
        .cost-card-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
        .cost-card-value { font-size: 24px; font-weight: 700; }

        .cost-card.total { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
        .cost-card.total .cost-card-label { color: #aaa; }

        .followup-wrapper {
            margin-top: 40px; padding-top: 40px; border-top: 1px solid var(--glass-border);
            display: flex; gap: 12px;
        }
        .followup-input {
            flex: 1; background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border);
            color: var(--text); padding: 14px 16px; border-radius: 100px;
            font-size: 14px; outline: none; font-family: var(--font);
        }
        .followup-input:focus { border-color: rgba(0,0,0,0.2); }
        .btn-send {
            background: var(--accent); color: var(--accent-text); border: none;
            width: 44px; height: 44px; border-radius: 50%;
            cursor: pointer; display: flex; align-items: center; justify-content: center;
            transition: transform 0.2s;
        }
        .btn-send:hover { transform: scale(1.05); }
        .btn-send svg { width: 18px; height: 18px; }

        .footer-limit {
            margin-top: 60px; padding-top: 24px; border-top: 1px solid var(--glass-border);
            text-align: center; font-size: 12px; color: var(--text-muted);
        }

        .modal-overlay {
            display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.8); backdrop-filter: blur(10px);
            z-index: 1000; align-items: center; justify-content: center;
        }
        .modal-overlay.active { display: flex; }
        .modal {
            background: #fff; border: 1px solid var(--glass-border);
            border-radius: 24px; padding: 32px; max-width: 400px; width: 90%;
            text-align: center; box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }
        .modal h3 { font-size: 20px; margin-bottom: 16px; font-weight: 700; }
        .modal p { color: var(--text-muted); margin-bottom: 24px; line-height: 1.6; font-size: 14px; }
        .modal-btn {
            background: var(--accent); color: var(--accent-text); border: none;
            padding: 12px 24px; border-radius: 100px; font-weight: 600; cursor: pointer; margin: 0 8px;
            transition: opacity 0.2s;
        }
        .modal-btn:hover { opacity: 0.8; }
        .modal-btn.secondary { background: transparent; color: var(--text); border: 1px solid var(--glass-border); }

        .pro-badge {
            display: inline-block; background: var(--accent); color: var(--accent-text);
            padding: 2px 8px; border-radius: 4px; font-size: 9px; font-weight: 700;
            text-transform: uppercase; letter-spacing: 1px; margin-left: 8px; vertical-align: middle;
        }

        @media (max-width: 768px) {
            .hero h1 { font-size: 36px; }
            .container { padding: 100px 20px 40px; }
            .glass-card { padding: 24px; border-radius: 24px; }
            nav { width: 95%; padding: 12px 20px; }
        }
    </style>
</head>
<body>

<div class="bg-shape shape-1"></div>
<div class="bg-shape shape-2"></div>

<nav>
    <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        Winy AI
    </div>
    <button class="btn-pro" onclick="initiatePayment()">Upgrade to Pro</button>
</nav>

<div class="container">
    <div class="hero">
        <h1>Deploy the Swarm.</h1>
        <p>Elite business strategy generation. Deep research, financial modeling, and actionable roadmaps in seconds.</p>
    </div>

    <div id="inputWrapper">
        <div class="glass-card">
            <textarea class="main-input" id="mainPrompt" placeholder="Describe your business idea, challenge, or market..."></textarea>

            <div class="options-slider">
                <div class="option-card">
                    <span class="option-label">Industry</span>
                    <select class="option-select" id="optIndustry">
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
                    <select class="option-select" id="optLength">
                        <option value="short">Brief (Quick Scan)</option>
                        <option value="medium" selected>Standard (Detailed)</option>
                        <option value="long">Deep Dive (Comprehensive)</option>
                    </select>
                </div>
                <div class="option-card">
                    <span class="option-label">Tone</span>
                    <select class="option-select" id="optTone">
                        <option value="Professional">Professional</option>
                        <option value="Direct">Direct & Actionable</option>
                        <option value="Analytical">Analytical</option>
                        <option value="Persuasive">Persuasive (Pitch Deck)</option>
                    </select>
                </div>
            </div>

            <button class="btn-launch" id="btnLaunch" onclick="runSwarm()">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                Initialize Swarm
            </button>
        </div>
    </div>

    <div class="swarm-loader" id="swarmLoader">
        <div class="swarm-core"></div>
        <div class="robot" style="--tx: -80px; --ty: -60px;"><svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2z"/><circle cx="9" cy="11" r="1.5" fill="#fff"/><circle cx="15" cy="11" r="1.5" fill="#fff"/></svg></div>
        <div class="robot" style="--tx: 80px; --ty: -60px;"><svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2z"/><circle cx="9" cy="11" r="1.5" fill="#fff"/><circle cx="15" cy="11" r="1.5" fill="#fff"/></svg></div>
        <div class="robot" style="--tx: -100px; --ty: 20px;"><svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2z"/><circle cx="9" cy="11" r="1.5" fill="#fff"/><circle cx="15" cy="11" r="1.5" fill="#fff"/></svg></div>
        <div class="robot" style="--tx: 100px; --ty: 20px;"><svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2z"/><circle cx="9" cy="11" r="1.5" fill="#fff"/><circle cx="15" cy="11" r="1.5" fill="#fff"/></svg></div>
        <div class="robot" style="--tx: -60px; --ty: 80px;"><svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2z"/><circle cx="9" cy="11" r="1.5" fill="#fff"/><circle cx="15" cy="11" r="1.5" fill="#fff"/></svg></div>
        <div class="robot" style="--tx: 60px; --ty: 80px;"><svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2v2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2z"/><circle cx="9" cy="11" r="1.5" fill="#fff"/><circle cx="15" cy="11" r="1.5" fill="#fff"/></svg></div>
        <div class="swarm-text">Swarm Processing</div>
    </div>

    <div class="results-area" id="resultsArea">
        <div class="results-header">
            <h2>Strategic Output</h2>
            <div style="display:flex; gap:8px;">
                <button class="btn-icon" onclick="copyResults()" title="Copy Text">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                </button>
                <button class="btn-icon" onclick="exportPDF()" title="Export PDF" id="btnExport" style="display:none;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                </button>
                <button class="btn-icon" onclick="runSwarm()" title="Regenerate">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path></svg>
                </button>
            </div>
        </div>

        <div class="unified-summary" id="unifiedSummary"></div>
        <div class="accordion" id="accordionContainer"></div>

        <div class="cost-section" id="costSection">
            <div class="option-label" style="margin-bottom:16px;">Capital Requirements</div>
            <div class="cost-slider" id="costSlider"></div>
        </div>

        <div class="followup-wrapper">
            <input type="text" class="followup-input" id="followupInput" placeholder="Ask the swarm a follow-up question...">
            <button class="btn-send" onclick="askFollowup()">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
            </button>
        </div>
    </div>

    <div class="footer-limit" id="footerLimit">
        You're currently on free tier. <span style="color:#000; cursor:pointer; text-decoration:underline; font-weight:600;" onclick="initiatePayment()">Upgrade to Pro</span> for unlimited access.
    </div>
</div>

<div class="modal-overlay" id="customModal">
    <div class="modal">
        <h3 id="modalTitle">Title</h3>
        <p id="modalMessage">Message</p>
        <div>
            <button class="modal-btn" id="modalConfirm" onclick="closeModal()">OK</button>
            <button class="modal-btn secondary" id="modalCancel" onclick="closeModal()" style="display:none;">Cancel</button>
        </div>
    </div>
</div>

<script>
    console.log('Winy AI Script Loaded Successfully');
    
    let currentContext = '';
    let currentIndustry = '';
    
    // Safe Jinja parsing to prevent JS crashes
    let isPro = {{ session.get('is_pro', false) | tojson }};
    let generationsUsed = {{ session.get('generations_used', 0) | tojson }};
    let followupsUsed = {{ session.get('followups_used', 0) | tojson }};

    function showModal(title, message, confirmText = 'OK', showCancel = false) {
        document.getElementById('modalTitle').textContent = title;
        document.getElementById('modalMessage').textContent = message;
        document.getElementById('modalConfirm').textContent = confirmText;
        document.getElementById('modalCancel').style.display = showCancel ? 'inline-block' : 'none';
        document.getElementById('customModal').classList.add('active');
    }

    function closeModal() {
        document.getElementById('customModal').classList.remove('active');
    }

    function updateUI() {
        if (isPro) {
            document.getElementById('footerLimit').innerHTML = 'You are a <strong style="color:#000;">Pro</strong> user. Unlimited access enabled.';
            document.getElementById('btnExport').style.display = 'flex';
        } else {
            const remaining = Math.max(0, 3 - generationsUsed);
            document.getElementById('footerLimit').innerHTML = `Free tier: <strong style="color:#000;">${remaining}</strong> generations remaining today. <span style="color:#000; cursor:pointer; text-decoration:underline; font-weight:600;" onclick="initiatePayment()">Upgrade to Pro</span> for unlimited.`;
        }
    }

    function highlightText(text) {
        const map = {
            'market': 'hl-green', 'revenue': 'hl-blue', 'growth': 'hl-blue',
            'strategy': 'hl-purple', 'ROI': 'hl-yellow', 'profit': 'hl-green',
            'cost': 'hl-yellow', 'budget': 'hl-yellow', 'customers': 'hl-blue'
        };
        let html = text;
        for (const [word, cls] of Object.entries(map)) {
            const regex = new RegExp(`\\b${word}\\b`, 'gi');
            html = html.replace(regex, `<span style="font-weight:600; border-bottom: 2px solid currentColor; padding-bottom: 2px;">${word}</span>`);
        }
        return html;
    }

    function toggleAccordion(element) {
        const item = element.parentElement;
        const isActive = item.classList.contains('active');
        document.querySelectorAll('.accordion-item').forEach(i => i.classList.remove('active'));
        if (!isActive) item.classList.add('active');
    }

    function renderResults(data) {
        document.getElementById('unifiedSummary').innerHTML = highlightText(data.summary);

        const sections = [
            { id: 'market', title: 'Market Analysis', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>' },
            { id: 'strategy', title: 'Operational Strategy', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>' },
            { id: 'financials', title: 'Financial Projections', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>' },
            { id: 'gtm', title: 'Go-to-Market Plan', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>' }
        ];

        let accHtml = '';
        sections.forEach(sec => {
            accHtml += `
                <div class="accordion-item">
                    <div class="accordion-header" onclick="toggleAccordion(this)">
                        <div class="accordion-title">${sec.icon} ${sec.title}</div>
                        <svg class="accordion-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
                    </div>
                    <div class="accordion-content">
                        <div class="accordion-text">${highlightText(data[sec.id])}</div>
                    </div>
                </div>
            `;
        });
        document.getElementById('accordionContainer').innerHTML = accHtml;

        const costs = data.costs;
        let costHtml = '';
        for (const [key, val] of Object.entries(costs)) {
            if(key !== 'total') {
                costHtml += `<div class="cost-card"><div class="cost-card-label">${key}</div><div class="cost-card-value">$${val.toLocaleString()}</div></div>`;
            }
        }
        costHtml += `<div class="cost-card total"><div class="cost-card-label">Total Initial Capital</div><div class="cost-card-value">$${costs.total.toLocaleString()}</div></div>`;
        document.getElementById('costSlider').innerHTML = costHtml;
    }

    async function runSwarm() {
        console.log('Run Swarm clicked');
        const prompt = document.getElementById('mainPrompt').value.trim();
        if (!prompt) return showModal('Missing Input', 'Please enter a business idea to analyze.');

        const length = document.getElementById('optLength').value;
        if (length === 'long' && !isPro) {
            return showModal('Pro Feature', 'Deep Dive mode is available only for Pro users. Upgrade to unlock comprehensive 500-word analyses.', 'Upgrade', true);
        }

        if (!isPro && generationsUsed >= 3) {
            return showModal('Daily Limit Reached', 'You have used all 3 free generations for today. Upgrade to Pro for unlimited access.', 'Upgrade', true);
        }

        const industry = document.getElementById('optIndustry').value;
        const tone = document.getElementById('optTone').value;

        currentContext = prompt;
        currentIndustry = industry;

        document.getElementById('inputWrapper').style.display = 'none';
        document.getElementById('resultsArea').classList.remove('active');
        document.getElementById('swarmLoader').classList.add('active');

        try {
            const res = await fetch('/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, industry, length, tone })
            });
            
            if (!res.ok) {
                const errData = await res.json().catch(() => ({error: 'Server error'}));
                throw new Error(errData.error || 'Server error');
            }

            const data = await res.json();
            document.getElementById('swarmLoader').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';
            document.getElementById('resultsArea').classList.add('active');

            if (!isPro) {
                generationsUsed++;
                updateUI();
            }

            renderResults(data);
        } catch (e) {
            console.error('Swarm Error:', e);
            showModal('Error', 'Failed to generate strategy: ' + e.message);
            document.getElementById('swarmLoader').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';
        }
    }

    async function askFollowup() {
        const q = document.getElementById('followupInput').value.trim();
        if (!q) return;

        if (!isPro && followupsUsed >= 1) {
            return showModal('Pro Feature', 'Free users get 1 follow-up question. Upgrade to Pro for unlimited follow-ups.', 'Upgrade', true);
        }

        const btn = document.querySelector('.btn-send');
        const originalSvg = btn.innerHTML;
        btn.innerHTML = '<div style="width:16px;height:16px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>';
        btn.disabled = true;

        try {
            const res = await fetch('/followup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: q, context: currentContext, industry: currentIndustry })
            });
            
            if (!res.ok) throw new Error('Follow-up limit reached or server error');
            
            const data = await res.json();

            const summaryEl = document.getElementById('unifiedSummary');
            summaryEl.innerHTML += `<br><br><strong style="color:#000;">Q: ${q}</strong><br><br>${highlightText(data.answer)}`;
            document.getElementById('followupInput').value = '';

            if (!isPro) {
                followupsUsed++;
            }
        } catch(e) {
            showModal('Error', 'Follow-up failed: ' + e.message);
        }

        btn.innerHTML = originalSvg;
        btn.disabled = false;
    }

    function copyResults() {
        const text = document.getElementById('unifiedSummary').innerText + '\n\n' +
                     Array.from(document.querySelectorAll('.accordion-text')).map(e => e.innerText).join('\n\n');
        navigator.clipboard.writeText(text).then(() => showModal('Copied!', 'Strategy copied to clipboard.'));
    }

    function exportPDF() {
        if (!isPro) {
            return showModal('Pro Feature', 'PDF export is available only for Pro users.', 'Upgrade', true);
        }
        showModal('Exporting...', 'Your PDF is being generated. This feature will be available soon!');
    }

    async function initiatePayment() {
        try {
            const orderRes = await fetch('/api/create-order', { method: 'POST' });
            if (!orderRes.ok) throw new Error('Failed to create order');
            const order = await orderRes.json();
            
            const options = {
                key: {{ razorpay_key_id | tojson }},
                amount: order.amount,
                currency: order.currency,
                name: 'Winy AI',
                description: 'Pro Subscription - Monthly',
                order_id: order.order_id,
                handler: function(response) {
                    fetch('/api/verify-payment', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            razorpay_order_id: response.razorpay_order_id,
                            razorpay_payment_id: response.razorpay_payment_id,
                            razorpay_signature: response.razorpay_signature
                        })
                    }).then(res => res.json()).then(data => {
                        if(data.status === 'success') {
                            isPro = true;
                            generationsUsed = 0;
                            followupsUsed = 0;
                            updateUI();
                            showModal('Payment Successful!', 'Welcome to Winy AI Pro! You now have unlimited access to all features.');
                        } else {
                            showModal('Payment Failed', 'Payment verification failed. Please contact support.');
                        }
                    }).catch(err => showModal('Error', 'Verification failed: ' + err.message));
                },
                prefill: { name: '', email: '', contact: '' },
                theme: { color: '#000000' },
                method: { upi: true, card: true, netbanking: true, wallet: true },
                modal: { ondismiss: function() { console.log('Checkout closed'); } }
            };
            
            const rzp = new Razorpay(options);
            rzp.on('payment.failed', function(response) {
                showModal('Payment Failed', response.error.description);
            });
            rzp.open();
        } catch (e) {
            showModal('Error', 'Failed to initiate payment: ' + e.message);
        }
    }

    // Initialize UI on load
    updateUI();
</script>
<style>@keyframes spin { to { transform: rotate(360deg); } }</style>
</body>
</html>
'''

@app.route('/')
def home():
    if 'generations_used' not in session:
        session['generations_used'] = 0
    if 'followups_used' not in session:
        session['followups_used'] = 0
    if 'is_pro' not in session:
        session['is_pro'] = False
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/generate', methods=['POST'])
def generate():
    if not session.get('is_pro') and session.get('generations_used', 0) >= 3:
        return jsonify({"error": "Daily limit reached. Upgrade to Pro."}), 403

    data = request.json
    prompt = data['prompt']
    industry = data['industry']
    length = data['length']
    tone = data['tone']

    if length == 'long' and not session.get('is_pro'):
        return jsonify({"error": "Deep Dive is a Pro feature"}), 403

    word_map = {'short': '200 words', 'medium': '350 words', 'long': '500 words'}
    limit = word_map.get(length, '350 words')

    sys = f"""You are a business consultant. Industry: {industry}. Tone: {tone}.
    Provide a business analysis for: {prompt}

    Format your response EXACTLY like this:

    SUMMARY:
    [2-3 sentence overview]

    MARKET:
    [Market analysis - {limit}]

    STRATEGY:
    [Operational plan - {limit}]

    FINANCIALS:
    [Revenue model - {limit}]

    GTM:
    [Marketing plan - {limit}]

    COSTS:
    Product Dev: [number only, e.g., 5000]
    Marketing: [number only]
    Operations: [number only]
    Legal: [number only]
    Contingency: [number only]
    """

    raw = call_llm(sys, prompt, temperature=0.7)

    sections = {
        'summary': '', 'market': '', 'strategy': '',
        'financials': '', 'gtm': '', 'costs': {}
    }

    current_section = None
    for line in raw.split('\n'):
        line = line.strip()
        if line.startswith('SUMMARY:'): current_section = 'summary'
        elif line.startswith('MARKET:'): current_section = 'market'
        elif line.startswith('STRATEGY:'): current_section = 'strategy'
        elif line.startswith('FINANCIALS:'): current_section = 'financials'
        elif line.startswith('GTM:'): current_section = 'gtm'
        elif line.startswith('COSTS:'): current_section = 'costs'
        elif current_section and line:
            if current_section == 'costs' and ':' in line:
                try:
                    key, val = line.split(':', 1)
                    sections['costs'][key.strip()] = int(val.strip().replace(',', '').replace('$', ''))
                except: pass
            elif current_section:
                sections[current_section] += line + "\n"

    if 'total' not in sections['costs']:
        sections['costs']['total'] = sum(v for k,v in sections['costs'].items() if isinstance(v, int))

    if not sections['costs'] or sections['costs'].get('total', 0) == 0:
        base_costs = {
            'Technology': {'Product Dev': 8000, 'Marketing': 3000, 'Operations': 2000, 'Legal': 1500, 'Contingency': 1500},
            'E-commerce': {'Product Dev': 3000, 'Marketing': 4000, 'Operations': 2500, 'Legal': 1000, 'Contingency': 1500},
            'Food & Beverage': {'Product Dev': 5000, 'Marketing': 3500, 'Operations': 8000, 'Legal': 2000, 'Contingency': 3000},
        }
        sections['costs'] = base_costs.get(industry, {'Product Dev': 5000, 'Marketing': 3000, 'Operations': 3000, 'Legal': 1500, 'Contingency': 1500})
        sections['costs']['total'] = sum(sections['costs'].values())

    if not session.get('is_pro'):
        session['generations_used'] = session.get('generations_used', 0) + 1

    return jsonify(sections)

@app.route('/followup', methods=['POST'])
def followup():
    if not session.get('is_pro') and session.get('followups_used', 0) >= 1:
        return jsonify({"error": "Follow-up limit reached"}), 403

    data = request.json
    q = data['question']
    ctx = data['context']
    ind = data['industry']

    sys = f"You are the Winy AI Strategy Swarm. Context: User is building a {ind} business based on this idea: '{ctx}'. Answer the following question concisely and professionally in about 150 words."
    ans = call_llm(sys, f"Question: {q}", temperature=0.7)

    if not session.get('is_pro'):
        session['followups_used'] = session.get('followups_used', 0) + 1

    return jsonify({"answer": ans})

@app.route('/api/create-order', methods=['POST'])
def create_order():
    try:
        amount = 49900  # ₹499 in paise
        order = razorpay_client.order.create({
            "amount": amount,
            "currency": "INR",
            "receipt": f"receipt_{int(os.urandom(4).hex(), 16)}",
            "payment_capture": 1
        })
        return jsonify({
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
def verify_payment():
    try:
        data = request.json
        order_id = data.get('razorpay_order_id')
        payment_id = data.get('razorpay_payment_id')
        signature = data.get('razorpay_signature')
        
        message = f"{order_id}|{payment_id}"
        expected_signature = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if expected_signature == signature:
            session['is_pro'] = True
            session['generations_used'] = 0
            session['followups_used'] = 0
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "failure"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("\n[WINY AI] Swarm Online. Port 5000.\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
