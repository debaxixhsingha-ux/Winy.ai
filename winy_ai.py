from flask import Flask, request, jsonify, render_template_string, session
import requests
import re
import os
import razorpay
import hmac
import hashlib
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "winy-ai-secret-key-2024")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
else:
    razorpay_client = None

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
            "max_tokens": 2500
        }, timeout=90)
        result = response.json()
        if 'choices' in result and len(result['choices']) > 0:
            return clean_text(result['choices'][0]['message']['content'])
        return "The swarm encountered a rate limit."
    except Exception as e:
        return f"Connection error: {str(e)}"

def get_today():
    return date.today().isoformat()

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
            scroll-behavior: smooth;
        }
        .bg-shape { position: fixed; border-radius: 50%; filter: blur(100px); z-index: 0; pointer-events: none; }
        .shape-1 { width: 500px; height: 500px; background: #f0f0f0; top: -100px; left: -100px; }
        .shape-2 { width: 400px; height: 400px; background: #e5e5e5; bottom: -100px; right: -50px; }

        h1, h2, h3 { font-weight: 700; letter-spacing: -0.02em; }

        nav {
            position: fixed; top: 24px; left: 50%; transform: translateX(-50%);
            width: 90%; max-width: 900px; padding: 16px 24px;
            display: flex; justify-content: space-between; align-items: center;
            z-index: 100; background: rgba(255, 255, 255, 0.6);
            backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border); border-radius: 100px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
            transition: all 0.5s ease;
        }
        nav.pro-nav {
            background: #000;
            border-color: #333;
        }
        nav.pro-nav .nav-left, nav.pro-nav .nav-right { color: #fff; }
        nav.pro-nav .btn-pro { background: #fff; color: #000; }
        nav.pro-nav .btn-logout { border-color: rgba(255,255,255,0.3); color: rgba(255,255,255,0.7); }

        .nav-left { display: flex; align-items: center; gap: 12px; }
        .nav-right { display: flex; align-items: center; gap: 12px; }

        .logo { font-size: 16px; font-weight: 700; letter-spacing: -0.5px; display: flex; align-items: center; gap: 8px; }
        .logo svg { width: 18px; height: 18px; }

        .btn-pro {
            background: rgba(0, 0, 0, 0.05); border: 1px solid rgba(0, 0, 0, 0.1);
            color: var(--text); padding: 8px 16px; border-radius: 100px;
            font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.3s ease;
        }
        .btn-pro:hover { background: rgba(0, 0, 0, 0.1); border-color: rgba(0, 0, 0, 0.2); }

        .btn-login {
            background: var(--accent); color: var(--accent-text);
            padding: 8px 16px; border-radius: 100px;
            font-size: 12px; font-weight: 600; cursor: pointer; border: none;
            transition: all 0.3s ease;
        }
        .btn-login:hover { opacity: 0.8; }

        .user-info { display: flex; align-items: center; gap: 12px; }
        .user-avatar {
            width: 32px; height: 32px; border-radius: 50%;
            background: var(--accent); color: var(--accent-text);
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: 600;
        }
        .btn-logout {
            background: transparent; border: 1px solid var(--glass-border);
            color: var(--text-muted); padding: 6px 12px; border-radius: 100px;
            font-size: 11px; cursor: pointer; transition: all 0.3s ease;
        }
        .btn-logout:hover { border-color: var(--accent); color: var(--text); }

        .container { max-width: 900px; margin: 0 auto; padding: 120px 24px 60px; position: relative; z-index: 1; }
        .hero { margin-bottom: 48px; text-align: center; }
        .hero h1 { font-size: 48px; line-height: 1.1; margin-bottom: 12px; letter-spacing: -1.5px; }
        .hero p { color: var(--text-muted); font-size: 16px; max-width: 500px; margin: 0 auto; }

        .glass-card {
            background: var(--glass-bg); backdrop-filter: blur(40px); -webkit-backdrop-filter: blur(40px);
            border-top: 1px solid var(--glass-highlight); border-left: 1px solid rgba(255, 255, 255, 0.5);
            border-right: 1px solid rgba(0, 0, 0, 0.05); border-bottom: 1px solid rgba(0, 0, 0, 0.1);
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.06), inset 0 0 0 1px rgba(0, 0, 0, 0.03);
            border-radius: 32px; padding: 48px; margin-bottom: 40px;
        }

        .main-input {
            width: 100%; background: rgba(0, 0, 0, 0.03); border: 1px solid var(--glass-border);
            color: var(--text); font-size: 16px; font-family: var(--font); padding: 20px 24px;
            border-radius: 16px; resize: none; outline: none; transition: all 0.3s ease;
            min-height: 80px; margin-bottom: 20px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.02);
        }
        .main-input:focus { background: rgba(0, 0, 0, 0.05); border-color: rgba(0, 0, 0, 0.2); }
        .main-input::placeholder { color: #999; }
        .main-input:disabled { opacity: 0.5; cursor: not-allowed; }

        .options-slider { display: flex; gap: 16px; overflow-x: auto; padding-bottom: 20px; margin-bottom: 20px; scrollbar-width: none; }
        .options-slider::-webkit-scrollbar { display: none; }
        .option-card {
            flex: 0 0 auto; min-width: 180px; background: rgba(0, 0, 0, 0.03);
            border: 1px solid var(--glass-border); border-radius: 16px; padding: 16px; transition: all 0.2s;
        }
        .option-card:hover { border-color: rgba(0, 0, 0, 0.2); }
        .option-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 12px; display: block; }
        .option-select { width: 100%; background: transparent; border: none; color: var(--text); font-size: 14px; font-family: var(--font); outline: none; cursor: pointer; appearance: none; }
        .option-select:disabled { opacity: 0.5; cursor: not-allowed; }

        .btn-launch {
            width: 100%; background: rgba(0, 0, 0, 0.05); backdrop-filter: blur(20px);
            border-top: 1px solid rgba(255, 255, 255, 0.5); border-left: 1px solid rgba(255, 255, 255, 0.2);
            border-right: 1px solid rgba(0, 0, 0, 0.1); border-bottom: 1px solid rgba(0, 0, 0, 0.2);
            border-radius: 16px; padding: 22px; font-size: 15px; font-weight: 600; color: var(--text);
            cursor: pointer; transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative; overflow: hidden; letter-spacing: 0.5px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.05), inset 0 1px 0 rgba(255,255,255,0.4);
            display: flex; align-items: center; justify-content: center; gap: 8px;
        }
        .btn-launch:hover { background: var(--accent); color: var(--accent-text); border-color: var(--accent); box-shadow: 0 15px 40px rgba(0, 0, 0, 0.2); transform: translateY(-2px); }
        .btn-launch:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

        .swarm-loader { display: none; flex-direction: column; align-items: center; justify-content: center; padding: 80px 0; position: relative; height: 300px; }
        .swarm-loader.active { display: flex; }
        .swarm-core { width: 20px; height: 20px; background: var(--accent); border-radius: 50%; position: relative; z-index: 10; box-shadow: 0 0 20px rgba(0,0,0,0.2); animation: pulse-core 1.5s infinite ease-in-out; }
        @keyframes pulse-core { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.2); } }
        .robot { position: absolute; width: 24px; height: 24px; top: 50%; left: 50%; margin-top: -12px; margin-left: -12px; animation: gather-and-orbit 3s infinite ease-in-out; }
        .robot svg { width: 100%; height: 100%; fill: var(--text-muted); }
        .robot:nth-child(2) { animation-delay: 0s; } .robot:nth-child(3) { animation-delay: 0.5s; }
        .robot:nth-child(4) { animation-delay: 1s; } .robot:nth-child(5) { animation-delay: 1.5s; }
        .robot:nth-child(6) { animation-delay: 2s; } .robot:nth-child(7) { animation-delay: 2.5s; }
        @keyframes gather-and-orbit {
            0% { transform: translate(0, 0) rotate(0deg) scale(0.5); opacity: 0; }
            30% { transform: translate(var(--tx), var(--ty)) rotate(180deg) scale(1); opacity: 1; }
            100% { transform: translate(var(--tx), var(--ty)) rotate(360deg) scale(1); opacity: 1; }
        }
        .swarm-text { margin-top: 40px; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: var(--text-muted); animation: fade-text 2s infinite; }
        @keyframes fade-text { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }

        .footer-limit { margin-top: 60px; padding-top: 24px; border-top: 1px solid var(--glass-border); text-align: center; font-size: 12px; color: var(--text-muted); }

        .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.8); backdrop-filter: blur(10px); z-index: 1000; align-items: center; justify-content: center; }
        .modal-overlay.active { display: flex; }
        .modal { background: #fff; border: 1px solid var(--glass-border); border-radius: 24px; padding: 32px; max-width: 400px; width: 90%; text-align: center; box-shadow: 0 20px 40px rgba(0,0,0,0.1); }
        .modal h3 { font-size: 20px; margin-bottom: 16px; font-weight: 700; }
        .modal p { color: var(--text-muted); margin-bottom: 24px; line-height: 1.6; font-size: 14px; }
        .modal-btn { background: var(--accent); color: var(--accent-text); border: none; padding: 12px 24px; border-radius: 100px; font-weight: 600; cursor: pointer; margin: 0 8px; transition: opacity 0.2s; }
        .modal-btn:hover { opacity: 0.8; }
        .modal-btn.secondary { background: transparent; color: var(--text); border: 1px solid var(--glass-border); }

        /* Login Modal */
        .login-modal { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.9); backdrop-filter: blur(20px); z-index: 2000; align-items: center; justify-content: center; }
        .login-modal.active { display: flex; }
        .login-card {
            background: #fff;
            border: 1px solid var(--glass-border);
            border-radius: 32px;
            padding: 48px;
            max-width: 420px;
            width: 90%;
            box-shadow: 0 30px 60px rgba(0,0,0,0.1);
        }
        .login-card h2 { font-size: 28px; margin-bottom: 8px; text-align: center; }
        .login-card .subtitle { color: var(--text-muted); text-align: center; margin-bottom: 32px; font-size: 14px; }
        .login-tabs { display: flex; gap: 8px; margin-bottom: 24px; background: rgba(0,0,0,0.03); padding: 4px; border-radius: 100px; }
        .login-tab { flex: 1; padding: 10px; border: none; background: transparent; border-radius: 100px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.3s; color: var(--text-muted); }
        .login-tab.active { background: var(--accent); color: var(--accent-text); }
        .login-input { width: 100%; background: rgba(0,0,0,0.03); border: 1px solid var(--glass-border); border-radius: 12px; padding: 14px 16px; font-size: 14px; margin-bottom: 12px; outline: none; font-family: var(--font); }
        .login-input:focus { border-color: rgba(0,0,0,0.2); }
        .login-btn { width: 100%; background: var(--accent); color: var(--accent-text); border: none; padding: 14px; border-radius: 100px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 8px; transition: opacity 0.2s; }
        .login-btn:hover { opacity: 0.8; }
        .divider { display: flex; align-items: center; margin: 24px 0; color: var(--text-muted); font-size: 12px; }
        .divider::before, .divider::after { content: ''; flex: 1; border-bottom: 1px solid var(--glass-border); }
        .divider::before { margin-right: 12px; } .divider::after { margin-left: 12px; }
        .google-btn { width: 100%; background: #fff; border: 1px solid var(--glass-border); padding: 12px; border-radius: 100px; font-size: 14px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 12px; transition: all 0.3s; }
        .google-btn:hover { background: rgba(0,0,0,0.02); border-color: rgba(0,0,0,0.2); }
        .google-btn svg { width: 20px; height: 20px; }
        .login-error { background: #fee; border: 1px solid #fcc; color: #c00; padding: 12px; border-radius: 12px; font-size: 13px; margin-bottom: 16px; display: none; }
        .login-error.active { display: block; }

        /* Results Overlay - Smaller with blur background */
        .results-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            z-index: 1500;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .results-overlay.active { display: flex; }
        
        .overlay-backdrop {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.3);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }
        
        .overlay-container {
            position: relative;
            background: #fff;
            border-radius: 32px;
            width: 100%;
            max-width: 700px;
            max-height: 85vh;
            overflow-y: auto;
            box-shadow: 0 30px 60px rgba(0,0,0,0.2);
            z-index: 10;
        }
        .overlay-container::-webkit-scrollbar { width: 6px; }
        .overlay-container::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.2); border-radius: 3px; }
        
        .overlay-header {
            position: sticky;
            top: 0;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(20px);
            padding: 20px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--glass-border);
            z-index: 10;
            border-radius: 32px 32px 0 0;
        }
        .overlay-header h2 { font-size: 18px; font-weight: 700; }
        .close-overlay {
            background: var(--accent);
            color: var(--accent-text);
            border: none;
            width: 36px; height: 36px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            transition: transform 0.2s;
        }
        .close-overlay:hover { transform: scale(1.1); }
        
        .overlay-content { padding: 24px; }
        
        .overlay-summary {
            font-size: 16px;
            line-height: 1.7;
            color: #333;
            margin-bottom: 24px;
            padding: 20px;
            background: rgba(0,0,0,0.02);
            border-radius: 16px;
            border-left: 3px solid var(--accent);
        }
        
        .overlay-sections {
            display: flex;
            gap: 16px;
            overflow-x: auto;
            scroll-snap-type: x mandatory;
            padding: 16px 0;
            scrollbar-width: none;
        }
        .overlay-sections::-webkit-scrollbar { display: none; }
        
        .overlay-section-card {
            flex: 0 0 85%;
            max-width: 320px;
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 24px;
            scroll-snap-align: center;
        }
        .overlay-section-card h3 {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }
        .overlay-section-card p {
            font-size: 14px;
            line-height: 1.6;
            color: var(--text);
        }
        
        .swipe-hint {
            text-align: center;
            color: var(--text-muted);
            font-size: 11px;
            margin: 16px 0;
            opacity: 0.7;
        }
        
        .overlay-costs {
            margin-top: 24px;
            padding: 20px;
            background: rgba(0,0,0,0.02);
            border-radius: 16px;
        }
        .overlay-costs h3 {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 16px;
        }
        .overlay-cost-slider { display: flex; gap: 12px; overflow-x: auto; padding: 8px 0; scrollbar-width: none; }
        .overlay-cost-slider::-webkit-scrollbar { display: none; }
        .cost-card { flex: 0 0 auto; min-width: 140px; background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: 12px; padding: 16px; }
        .cost-card-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
        .cost-card-value { font-size: 20px; font-weight: 700; }
        .cost-card.total { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
        .cost-card.total .cost-card-label { color: #aaa; }
        
        /* Follow-up in overlay */
        .overlay-followup {
            margin-top: 24px;
            padding: 20px;
            background: rgba(0,0,0,0.02);
            border-radius: 16px;
        }
        .overlay-followup-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: block;
        }
        .overlay-followup-input {
            width: 100%;
            background: rgba(0,0,0,0.03);
            border: 1px solid var(--glass-border);
            color: var(--text);
            padding: 12px 16px;
            border-radius: 100px;
            font-size: 13px;
            outline: none;
            font-family: var(--font);
            margin-bottom: 10px;
        }
        .overlay-followup-input:focus { border-color: rgba(0,0,0,0.2); }
        .overlay-btn-send {
            background: var(--accent);
            color: var(--accent-text);
            border: none;
            width: 100%;
            padding: 12px;
            border-radius: 100px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .overlay-btn-send:disabled { opacity: 0.5; cursor: not-allowed; }
        .overlay-btn-send svg { width: 16px; height: 16px; }
        
        .qa-container { margin-top: 16px; }
        .question-box {
            background: #fff;
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            border-left: 3px solid var(--accent);
        }
        .question-box strong {
            color: var(--text-muted);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            display: block;
            margin-bottom: 6px;
        }
        .question-box p { font-size: 14px; line-height: 1.5; }
        .answer-box {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 16px;
            margin-top: 12px;
        }
        .answer-box p { font-size: 14px; line-height: 1.6; color: var(--text); }

        /* Colorful highlight boxes */
        .hl-box {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 0.95em;
        }
        .hl-market { background: #dbeafe; color: #1e40af; }
        .hl-revenue { background: #dcfce7; color: #166534; }
        .hl-growth { background: #fef3c7; color: #92400e; }
        .hl-strategy { background: #f3e8ff; color: #6b21a8; }
        .hl-roi { background: #fce7f3; color: #9d174d; }
        .hl-cost { background: #fee2e2; color: #991b1b; }
        .hl-customers { background: #e0f2fe; color: #075985; }

        @media (max-width: 768px) {
            .hero h1 { font-size: 36px; } .container { padding: 100px 20px 40px; }
            .glass-card { padding: 24px; border-radius: 24px; } nav { width: 95%; padding: 12px 20px; }
            .login-card { padding: 32px; }
            .overlay-section-card { flex: 0 0 90%; }
            .overlay-container { max-height: 90vh; border-radius: 24px; }
            .overlay-header { border-radius: 24px 24px 0 0; }
        }
    </style>
</head>
<body>
<div class="bg-shape shape-1"></div><div class="bg-shape shape-2"></div>

<nav id="mainNav">
    <div class="nav-left" id="navLeft">
        <div class="logo">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            Winy AI
        </div>
    </div>
    <div class="nav-right" id="navRight">
        <button class="btn-login" onclick="showLoginModal()">Login / Sign Up</button>
    </div>
</nav>

<div class="container">
    <div class="hero">
        <h1>Deploy the Swarm.</h1>
        <p>Elite business strategy generation. Deep research, financial modeling, and actionable roadmaps in seconds.</p>
    </div>

    <div id="inputWrapper">
        <div class="glass-card">
            <textarea class="main-input" id="mainPrompt" placeholder="Describe your business idea, challenge, or market..." disabled></textarea>
            <div class="options-slider">
                <div class="option-card">
                    <span class="option-label">Industry</span>
                    <select class="option-select" id="optIndustry" disabled>
                        <option value="General">General</option><option value="Technology">Technology / SaaS</option>
                        <option value="E-commerce">E-commerce / Retail</option><option value="Food & Beverage">Food & Beverage</option>
                        <option value="Real Estate">Real Estate</option><option value="Healthcare">Healthcare</option>
                    </select>
                </div>
                <div class="option-card">
                    <span class="option-label">Depth</span>
                    <select class="option-select" id="optLength" disabled>
                        <option value="short">Brief (Quick Scan)</option><option value="medium" selected>Standard (Detailed)</option>
                        <option value="long">Deep Dive (Comprehensive)</option>
                    </select>
                </div>
                <div class="option-card">
                    <span class="option-label">Tone</span>
                    <select class="option-select" id="optTone" disabled>
                        <option value="Professional">Professional</option><option value="Direct">Direct & Actionable</option>
                        <option value="Analytical">Analytical</option><option value="Persuasive">Persuasive (Pitch Deck)</option>
                    </select>
                </div>
            </div>
            <button class="btn-launch" id="btnLaunch" onclick="runSwarm()" disabled>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                Login to Initialize Swarm
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

    <div class="footer-limit" id="footerLimit">Please login to access features.</div>
</div>

<!-- Results Overlay -->
<div class="results-overlay" id="resultsOverlay">
    <div class="overlay-backdrop" onclick="closeResultsOverlay()"></div>
    <div class="overlay-container">
        <div class="overlay-header">
            <h2>Strategic Output</h2>
            <button class="close-overlay" onclick="closeResultsOverlay()">✕</button>
        </div>
        <div class="overlay-content">
            <div class="overlay-summary" id="overlaySummary"></div>
            <div class="overlay-sections" id="overlaySections"></div>
            <div class="swipe-hint">← Swipe to explore sections →</div>
            <div class="overlay-costs" id="overlayCosts"></div>
            <div class="overlay-followup">
                <span class="overlay-followup-label">Follow-up Question</span>
                <input type="text" class="overlay-followup-input" id="overlayFollowupInput" placeholder="Ask the swarm anything...">
                <button class="overlay-btn-send" id="overlayBtnSend" onclick="askFollowupOverlay()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                    Ask Swarm
                </button>
                <div class="qa-container" id="overlayQaContainer"></div>
            </div>
        </div>
    </div>
</div>

<!-- Login Modal -->
<div class="login-modal" id="loginModal">
    <div class="login-card">
        <h2>Welcome to Winy AI</h2>
        <p class="subtitle">Login to deploy the swarm</p>
        <div class="login-tabs">
            <button class="login-tab active" onclick="switchTab('login')">Login</button>
            <button class="login-tab" onclick="switchTab('signup')">Sign Up</button>
        </div>
        <div class="login-error" id="loginError"></div>
        <div id="loginForm">
            <input type="email" class="login-input" id="loginEmail" placeholder="Email">
            <input type="password" class="login-input" id="loginPassword" placeholder="Password">
            <button class="login-btn" onclick="loginWithEmail()">Login</button>
        </div>
        <div id="signupForm" style="display:none;">
            <input type="email" class="login-input" id="signupEmail" placeholder="Email">
            <input type="password" class="login-input" id="signupPassword" placeholder="Password (min 6 characters)">
            <button class="login-btn" onclick="signupWithEmail()">Sign Up</button>
        </div>
        <div class="divider">or</div>
        <button class="google-btn" onclick="loginWithGoogle()">
            <svg viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Continue with Google
        </button>
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
    
    var isPro = {{ session.get('is_pro', False) | tojson }};
    var generationsUsed = {{ session.get('generations_count', 0) | tojson }};
    var followupsUsed = {{ session.get('followups_count', 0) | tojson }};
    var rzpKeyId = {{ razorpay_key_id | tojson }};
    var isLoggedIn = false;
    var currentUser = null;
    var currentContext = '';
    var currentIndustry = '';

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
        document.getElementById('mainPrompt').disabled = false;
        document.getElementById('optIndustry').disabled = false;
        document.getElementById('optLength').disabled = false;
        document.getElementById('optTone').disabled = false;
        document.getElementById('btnLaunch').disabled = false;
        document.getElementById('btnLaunch').innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;"><path d="M5 12h14M12 5l7 7-7 7"/></svg> Initialize Swarm';
    }

    function disableFeatures() {
        document.getElementById('mainPrompt').disabled = true;
        document.getElementById('optIndustry').disabled = true;
        document.getElementById('optLength').disabled = true;
        document.getElementById('optTone').disabled = true;
        document.getElementById('btnLaunch').disabled = true;
        document.getElementById('btnLaunch').innerHTML = 'Login to Initialize Swarm';
    }

    function updateUserUI() {
        var navLeft = document.getElementById('navLeft');
        var navRight = document.getElementById('navRight');
        var footer = document.getElementById('footerLimit');
        var mainNav = document.getElementById('mainNav');
        
        if (isLoggedIn) {
            var userInitial = currentUser.email ? currentUser.email.charAt(0).toUpperCase() : 'U';
            navLeft.innerHTML = '<div class="user-info"><div class="user-avatar">' + userInitial + '</div></div>';
            navRight.innerHTML = '<button class="btn-logout" onclick="logout()">Logout</button>' + (isPro ? '' : '<button class="btn-pro" onclick="initiatePayment()">Upgrade to Pro</button>');
            
            if (isPro) {
                mainNav.classList.add('pro-nav');
                footer.innerHTML = 'You are a <strong style="color:#000;">Pro</strong> user. Unlimited access enabled.';
            } else {
                mainNav.classList.remove('pro-nav');
                var remaining = Math.max(0, 3 - generationsUsed);
                footer.innerHTML = 'Free tier: <strong style="color:#000;">' + remaining + '</strong> generations remaining today. Resets at midnight. <span style="color:#000; cursor:pointer; text-decoration:underline; font-weight:600;" onclick="initiatePayment()">Upgrade to Pro</span> for unlimited.';
            }
        } else {
            mainNav.classList.remove('pro-nav');
            navLeft.innerHTML = '<div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg> Winy AI</div>';
            navRight.innerHTML = '<button class="btn-login" onclick="showLoginModal()">Login / Sign Up</button>';
            footer.innerHTML = 'Please login to access features.';
        }
    }

    function showLoginModal() { document.getElementById('loginModal').classList.add('active'); document.getElementById('loginError').classList.remove('active'); }
    function hideLoginModal() { document.getElementById('loginModal').classList.remove('active'); }

    function switchTab(tab) {
        var tabs = document.querySelectorAll('.login-tab');
        tabs.forEach(function(t) { t.classList.remove('active'); });
        if (tab === 'login') {
            tabs[0].classList.add('active');
            document.getElementById('loginForm').style.display = 'block';
            document.getElementById('signupForm').style.display = 'none';
        } else {
            tabs[1].classList.add('active');
            document.getElementById('loginForm').style.display = 'none';
            document.getElementById('signupForm').style.display = 'block';
        }
        document.getElementById('loginError').classList.remove('active');
    }

    function showError(msg) { var errorDiv = document.getElementById('loginError'); errorDiv.textContent = msg; errorDiv.classList.add('active'); }

    function loginWithEmail() {
        var email = document.getElementById('loginEmail').value.trim();
        var password = document.getElementById('loginPassword').value;
        if (!email || !password) return showError('Please enter email and password');
        auth.signInWithEmailAndPassword(email, password).then(function() { hideLoginModal(); }).catch(function(error) { showError(error.message); });
    }

    function signupWithEmail() {
        var email = document.getElementById('signupEmail').value.trim();
        var password = document.getElementById('signupPassword').value;
        if (!email || !password) return showError('Please enter email and password');
        if (password.length < 6) return showError('Password must be at least 6 characters');
        auth.createUserWithEmailAndPassword(email, password).then(function() { hideLoginModal(); }).catch(function(error) { showError(error.message); });
    }

    function loginWithGoogle() {
        var provider = new firebase.auth.GoogleAuthProvider();
        auth.signInWithPopup(provider).then(function() { hideLoginModal(); }).catch(function(error) { showError(error.message); });
    }

    function logout() {
        auth.signOut().then(function() {
            isPro = false; generationsUsed = 0; followupsUsed = 0;
            document.getElementById('resultsOverlay').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';
        });
    }

    function showModal(title, message, confirmText, showCancel) {
        document.getElementById('modalTitle').textContent = title;
        document.getElementById('modalMessage').textContent = message;
        document.getElementById('modalConfirm').textContent = confirmText || 'OK';
        document.getElementById('modalCancel').style.display = showCancel ? 'inline-block' : 'none';
        document.getElementById('customModal').classList.add('active');
    }
    function closeModal() { document.getElementById('customModal').classList.remove('active'); }

    function highlightText(text) {
        if (!text) return '';
        var colors = {
            'market': 'hl-market', 'revenue': 'hl-revenue', 'growth': 'hl-growth',
            'strategy': 'hl-strategy', 'ROI': 'hl-roi', 'profit': 'hl-revenue',
            'cost': 'hl-cost', 'budget': 'hl-cost', 'customers': 'hl-customers'
        };
        var html = text;
        for (var word in colors) {
            var regex = new RegExp('\\b' + word + '\\b', 'gi');
            html = html.replace(regex, '<span class="hl-box ' + colors[word] + '">' + word + '</span>');
        }
        return html;
    }

    function renderResultsOverlay(data) {
        document.getElementById('overlaySummary').innerHTML = '<p>' + highlightText(data.summary || 'No summary available.') + '</p>';
        
        var sections = [
            { id: 'market', title: 'Market Analysis', fallback: 'Market analysis data is being processed. Check back soon for detailed insights about your target market, competitors, and opportunities.' },
            { id: 'strategy', title: 'Operational Strategy', fallback: 'Strategy details are being compiled. This section will contain your operational roadmap and key action items.' },
            { id: 'financials', title: 'Financial Projections', fallback: 'Financial projections are being calculated. Revenue models and cost structures will appear here.' },
            { id: 'gtm', title: 'Go-to-Market Plan', fallback: 'Go-to-market strategy is being formulated. Marketing channels and launch plans will be displayed here.' }
        ];
        
        var sectionsHtml = '';
        for(var i=0; i<sections.length; i++) {
            var sec = sections[i];
            var content = data[sec.id];
            if (!content || content.trim() === '') {
                content = sec.fallback;
            }
            sectionsHtml += '<div class="overlay-section-card"><h3>' + sec.title + '</h3><p>' + highlightText(content) + '</p></div>';
        }
        document.getElementById('overlaySections').innerHTML = sectionsHtml;

        var costs = data.costs || {};
        var costHtml = '<h3>Capital Requirements</h3><div class="overlay-cost-slider">';
        var hasCosts = false;
        for (var key in costs) {
            if(key !== 'total') {
                costHtml += '<div class="cost-card"><div class="cost-card-label">' + key + '</div><div class="cost-card-value">$' + Number(costs[key]).toLocaleString() + '</div></div>';
                hasCosts = true;
            }
        }
        if (!hasCosts) {
            costHtml += '<div class="cost-card"><div class="cost-card-label">Product Dev</div><div class="cost-card-value">$5,000</div></div>';
            costHtml += '<div class="cost-card"><div class="cost-card-label">Marketing</div><div class="cost-card-value">$3,000</div></div>';
            costHtml += '<div class="cost-card"><div class="cost-card-label">Operations</div><div class="cost-card-value">$3,000</div></div>';
        }
        costHtml += '<div class="cost-card total"><div class="cost-card-label">Total Capital</div><div class="cost-card-value">$' + Number(costs.total || 14000).toLocaleString() + '</div></div></div>';
        document.getElementById('overlayCosts').innerHTML = costHtml;
    }

    function closeResultsOverlay() {
        document.getElementById('resultsOverlay').classList.remove('active');
        document.getElementById('inputWrapper').style.display = 'block';
    }

    function runSwarm() {
        if (!isLoggedIn) { showLoginModal(); return; }
        var prompt = document.getElementById('mainPrompt').value.trim();
        if (!prompt) return showModal('Missing Input', 'Please enter a business idea to analyze.');
        var length = document.getElementById('optLength').value;
        if (length === 'long' && !isPro) return showModal('Pro Feature', 'Deep Dive mode is available only for Pro users.', 'Upgrade', true);
        if (!isPro && generationsUsed >= 3) return showModal('Daily Limit Reached', 'You have used all 3 free generations for today.', 'Upgrade', true);

        var industry = document.getElementById('optIndustry').value;
        var tone = document.getElementById('optTone').value;
        currentContext = prompt;
        currentIndustry = industry;

        document.getElementById('inputWrapper').style.display = 'none';
        document.getElementById('swarmLoader').classList.add('active');
        document.getElementById('overlayQaContainer').innerHTML = '';

        fetch('/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: prompt, industry: industry, length: length, tone: tone })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            document.getElementById('swarmLoader').classList.remove('active');
            renderResultsOverlay(data);
            document.getElementById('resultsOverlay').classList.add('active');
            if (!isPro) { generationsUsed++; updateUserUI(); }
        })
        .catch(function(e) {
            document.getElementById('swarmLoader').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';
            showModal('Error', 'Failed to generate strategy.');
        });
    }

    function askFollowupOverlay() {
        if (!isLoggedIn) { showLoginModal(); return; }
        var q = document.getElementById('overlayFollowupInput').value.trim();
        if (!q) return;
        if (!isPro && followupsUsed >= 1) return showModal('Pro Feature', 'Free users get 1 follow-up question per day.', 'Upgrade', true);
        
        var btn = document.getElementById('overlayBtnSend');
        var originalContent = btn.innerHTML;
        btn.innerHTML = 'Processing...';
        btn.disabled = true;
        
        var qaContainer = document.getElementById('overlayQaContainer');
        var questionBox = document.createElement('div');
        questionBox.className = 'question-box';
        questionBox.innerHTML = '<strong>Your Question</strong><p>' + q + '</p>';
        qaContainer.appendChild(questionBox);
        
        var answerBox = document.createElement('div');
        answerBox.className = 'answer-box';
        answerBox.innerHTML = '<p style="color:#666;">Thinking...</p>';
        qaContainer.appendChild(answerBox);

        fetch('/followup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: q, context: currentContext, industry: currentIndustry })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            answerBox.innerHTML = '<p>' + highlightText(data.answer) + '</p>';
            document.getElementById('overlayFollowupInput').value = '';
            if (!isPro) followupsUsed++;
            btn.innerHTML = originalContent;
            btn.disabled = false;
        })
        .catch(function(e) {
            answerBox.innerHTML = '<p style="color:red;">Error: Failed to get answer</p>';
            btn.innerHTML = originalContent;
            btn.disabled = false;
        });
    }

    function initiatePayment() {
        if (!isLoggedIn) { showLoginModal(); return; }
        if (!rzpKeyId) return showModal('Error', 'Payment system not configured.');
        
        console.log('Starting payment...');
        
        fetch('/api/create-order', { method: 'POST' })
        .then(function(res) { 
            if (!res.ok) throw new Error('Failed to create order');
            return res.json(); 
        })
        .then(function(order) {
            console.log('Order created:', order);
            var options = {
                key: rzpKeyId,
                amount: order.amount,
                currency: order.currency,
                name: 'Winy AI',
                description: 'Pro Subscription',
                order_id: order.order_id,
                handler: function(response) {
                    console.log('FULL Razorpay Response:', JSON.stringify(response));
                    
                    var paymentId = response.razorpay_payment_id || response.payment_id || '';
                    var orderId = response.razorpay_order_id || response.order_id || order.order_id;
                    var signature = response.razorpay_signature || response.signature || '';
                    
                    console.log('Extracted - Payment:', paymentId, 'Order:', orderId, 'Signature:', signature);
                    
                    if (!paymentId || !signature) {
                        console.error('Missing data. Full response:', response);
                        return showModal('Error', 'Payment completed but verification data is missing. Payment ID: ' + paymentId + '. Please contact support.');
                    }
                    
                    fetch('/api/verify-payment', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            razorpay_payment_id: paymentId,
                            razorpay_order_id: orderId,
                            razorpay_signature: signature
                        })
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        console.log('Verification result:', data);
                        if(data.status === 'success') {
                            isPro = true; generationsUsed = 0; followupsUsed = 0;
                            updateUserUI();
                            showModal('Welcome to Pro!', 'Payment successful! You now have unlimited access to all features including Deep Dive mode, unlimited generations, and priority support.');
                        } else { 
                            showModal('Payment Failed', 'Verification failed. Contact support with Payment ID: ' + paymentId); 
                        }
                    })
                    .catch(function(err) { 
                        console.error('Verification error:', err);
                        showModal('Error', 'Verification error. Contact support.'); 
                    });
                },
                prefill: { name: currentUser ? currentUser.displayName || '' : '', email: currentUser ? currentUser.email : '', contact: '' },
                theme: { color: '#000000' }
            };
            var rzp = new Razorpay(options);
            rzp.on('payment.failed', function(response) {
                console.error('Payment failed:', response);
                showModal('Payment Failed', response.error.description);
            });
            rzp.open();
        })
        .catch(function(e) { 
            console.error('Payment error:', e);
            showModal('Error', 'Failed to start payment.'); 
        });
    }

    updateUserUI();
</script>
</body>
</html>
'''

@app.route('/')
def home():
    today = get_today()
    if 'is_pro' not in session: session['is_pro'] = False
    if session.get('generations_date') != today:
        session['generations_date'] = today
        session['generations_count'] = 0
    if session.get('followups_date') != today:
        session['followups_date'] = today
        session['followups_count'] = 0
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/generate', methods=['POST'])
def generate():
    if session.get('is_pro'):
        is_pro = True
    else:
        today = get_today()
        if session.get('generations_date') != today:
            session['generations_date'] = today
            session['generations_count'] = 0
        if session.get('generations_count', 0) >= 3:
            return jsonify({"error": "Daily limit reached"}), 403
        is_pro = False

    data = request.json
    prompt = data.get('prompt', '')
    industry = data.get('industry', 'General')
    length = data.get('length', 'medium')
    tone = data.get('tone', 'Professional')
    
    if length == 'long' and not is_pro:
        return jsonify({"error": "Deep Dive is Pro-only"}), 403

    word_map = {'short': '200 words', 'medium': '350 words', 'long': '500 words'}
    limit = word_map.get(length, '350 words')
    
    sys = f"""Business consultant for {industry}. Tone: {tone}.
    Analyze: {prompt}
    
    You MUST provide ALL sections below. Do not skip any:
    SUMMARY: [2-3 sentences overview]
    MARKET: [{limit} about target market, competitors, opportunities]
    STRATEGY: [{limit} about operations, team, execution plan]
    FINANCIALS: [{limit} about revenue model, pricing, projections]
    GTM: [{limit} about marketing channels, launch strategy, customer acquisition]
    COSTS:
    Product Dev: [number only]
    Marketing: [number only]
    Operations: [number only]
    Legal: [number only]
    Contingency: [number only]
    """
    raw = call_llm(sys, prompt)
    print(f"LLM Response length: {len(raw)}")
    
    sections = {'summary': '', 'market': '', 'strategy': '', 'financials': '', 'gtm': '', 'costs': {}}
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
            elif current_section: sections[current_section] += line + "\n"

    if 'total' not in sections['costs']:
        sections['costs']['total'] = sum(v for k,v in sections['costs'].items() if isinstance(v, int))
    if not sections['costs'] or sections['costs'].get('total', 0) == 0:
        sections['costs'] = {'Product Dev': 5000, 'Marketing': 3000, 'Operations': 3000, 'Legal': 1500, 'Contingency': 1500, 'total': 14000}

    if not is_pro:
        session['generations_count'] = session.get('generations_count', 0) + 1
    
    return jsonify(sections)

@app.route('/followup', methods=['POST'])
def followup():
    if session.get('is_pro'):
        is_pro = True
    else:
        today = get_today()
        if session.get('followups_date') != today:
            session['followups_date'] = today
            session['followups_count'] = 0
        if session.get('followups_count', 0) >= 1:
            return jsonify({"error": "Follow-up limit reached"}), 403
        is_pro = False

    data = request.json
    sys = f"Context: {data['industry']} business idea: '{data['context']}'. Answer concisely in 100-150 words: {data['question']}"
    ans = call_llm(sys, data['question'])
    if not is_pro:
        session['followups_count'] = session.get('followups_count', 0) + 1
    return jsonify({"answer": ans})

@app.route('/api/create-order', methods=['POST'])
def create_order():
    if not razorpay_client:
        return jsonify({"error": "Payment not configured"}), 500
    try:
        order = razorpay_client.order.create({"amount": 49900, "currency": "INR", "receipt": f"rcpt_{int(os.urandom(4).hex(), 16)}", "payment_capture": 1})
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
def verify_payment():
    try:
        data = request.json
        order_id = data.get('razorpay_order_id', '')
        payment_id = data.get('razorpay_payment_id', '')
        signature = data.get('razorpay_signature', '')
        
        print(f"Verify - Order: {order_id}, Payment: {payment_id}, Sig: {signature[:20]}...")
        
        if not all([order_id, payment_id, signature]):
            return jsonify({"status": "failure", "message": "Missing data"}), 400
        
        message = f"{order_id}|{payment_id}"
        expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
        
        print(f"Expected: {expected[:20]}..., Received: {signature[:20]}..., Match: {expected == signature}")
        
        if expected == signature:
            session['is_pro'] = True
            session['generations_count'] = 0
            session['followups_count'] = 0
            return jsonify({"status": "success"})
        return jsonify({"status": "failure", "message": "Signature mismatch"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
