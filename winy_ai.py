from flask import Flask, request, jsonify, render_template_string
import requests
import re
import json
import os

app = Flask(__name__)

# REPLACE WITH YOUR ACTUAL GROQ API KEY
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

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
    <style>
        :root {
            --bg: #000000;
            --surface: #0a0a0a;
            --border: #1a1a1a;
            --border-hover: #333333;
            --text: #ffffff;
            --text-muted: #888888;
            --accent: #ffffff;
            --accent-text: #000000;
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
        }

        /* Typography */
        h1, h2, h3 { font-weight: 500; letter-spacing: -0.02em; }

        /* Navigation */
        nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 24px 40px;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(12px);
            z-index: 100;
        }
        .logo { font-size: 18px; font-weight: 600; letter-spacing: -0.5px; display: flex; align-items: center; gap: 8px; }
        .logo svg { width: 20px; height: 20px; }

        .btn-pro {
            background: var(--accent);
            color: var(--accent-text);
            border: none;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .btn-pro:hover { opacity: 0.8; }

        /* Main Container */
        .container { max-width: 900px; margin: 0 auto; padding: 60px 24px; }

        /* Hero */
        .hero { margin-bottom: 48px; }
        .hero h1 { font-size: 40px; line-height: 1.1; margin-bottom: 12px; }
        .hero p { color: var(--text-muted); font-size: 16px; max-width: 500px; }

        /* Input Area */
        .input-wrapper { margin-bottom: 40px; }
        .main-input {
            width: 100%;
            background: transparent;
            border: none;
            border-bottom: 1px solid var(--border);
            color: var(--text);
            font-size: 20px;
            font-family: var(--font);
            padding: 20px 0;
            resize: none;
            outline: none;
            transition: border-color 0.3s;
            min-height: 80px;
        }
        .main-input:focus { border-bottom-color: var(--accent); }
        .main-input::placeholder { color: #333; }

        /* Horizontal Options Slider */
        .options-slider {
            display: flex;
            gap: 16px;
            overflow-x: auto;
            padding: 20px 0;
            margin-bottom: 32px;
            scrollbar-width: none;
        }
        .options-slider::-webkit-scrollbar { display: none; }

        .option-card {
            flex: 0 0 auto;
            min-width: 200px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            transition: all 0.2s;
        }
        .option-card:hover { border-color: var(--border-hover); }

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

        /* Launch Button */
        .btn-launch {
            background: var(--accent);
            color: var(--accent-text);
            border: none;
            padding: 16px 32px;
            font-size: 14px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.2s, opacity 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .btn-launch:hover { transform: translateY(-2px); opacity: 0.9; }
        .btn-launch:disabled { opacity: 0.3; cursor: not-allowed; transform: none; }

        /* Swarm Animation (Abstract) */
        .swarm-loader {
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 80px 0;
        }
        .swarm-loader.active { display: flex; }

        .swarm-core {
            width: 12px;
            height: 12px;
            background: var(--accent);
            border-radius: 50%;
            position: relative;
            animation: pulse-core 2s infinite ease-in-out;
        }
        .swarm-core::before, .swarm-core::after {
            content: '';
            position: absolute;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            border: 1px solid var(--accent);
            border-radius: 50%;
            animation: pulse-ring 2s infinite ease-out;
        }
        .swarm-core::after { animation-delay: 1s; }

        @keyframes pulse-core { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.2); opacity: 0.8; } }
        @keyframes pulse-ring { 0% { width: 12px; height: 12px; opacity: 1; } 100% { width: 100px; height: 100px; opacity: 0; } }

        .swarm-text {
            margin-top: 32px;
            font-size: 12px;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-muted);
            animation: fade-text 2s infinite;
        }
        @keyframes fade-text { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }

        /* Results Area */
        .results-area { display: none; animation: fadeIn 0.6s ease; }
        .results-area.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

        .results-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
        }
        .results-header h2 { font-size: 18px; font-weight: 500; }

        .btn-icon {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text);
            width: 36px; height: 36px;
            border-radius: 6px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: all 0.2s;
        }
        .btn-icon:hover { border-color: var(--accent); background: var(--surface); }
        .btn-icon svg { width: 16px; height: 16px; stroke-width: 2; }

        /* Unified Summary */
        .unified-summary {
            font-size: 16px;
            line-height: 1.7;
            color: #ccc;
            margin-bottom: 40px;
            padding-bottom: 40px;
            border-bottom: 1px solid var(--border);
        }

        /* Accordion Sections */
        .accordion { margin-bottom: 40px; }
        .accordion-item { border-bottom: 1px solid var(--border); }

        .accordion-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 24px 0;
            cursor: pointer;
            transition: color 0.2s;
        }
        .accordion-header:hover { color: #ccc; }
        .accordion-title { font-size: 15px; font-weight: 500; display: flex; align-items: center; gap: 12px; }
        .accordion-title svg { width: 18px; height: 18px; stroke-width: 1.5; color: var(--text-muted); }

        .accordion-icon {
            width: 20px; height: 20px;
            transition: transform 0.3s ease;
        }
        .accordion-item.active .accordion-icon { transform: rotate(90deg); }

        .accordion-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.4s ease, padding 0.4s ease;
        }
        .accordion-item.active .accordion-content {
            max-height: 1000px;
            padding-bottom: 24px;
        }
        .accordion-text {
            font-size: 15px;
            line-height: 1.8;
            color: #aaa;
            white-space: pre-wrap;
        }

        /* Cost Breakdown (Horizontal) */
        .cost-section { margin: 40px 0; }
        .cost-slider {
            display: flex;
            gap: 16px;
            overflow-x: auto;
            padding: 20px 0;
            scrollbar-width: none;
        }
        .cost-slider::-webkit-scrollbar { display: none; }

        .cost-card {
            flex: 0 0 auto;
            min-width: 180px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
        }
        .cost-card-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
        .cost-card-value { font-size: 24px; font-weight: 500; }

        .cost-card.total {
            background: var(--accent);
            color: var(--accent-text);
            border-color: var(--accent);
        }
        .cost-card.total .cost-card-label { color: #333; }
        .cost-card.total .cost-card-value { font-weight: 600; }

        /* Follow Up Input */
        .followup-wrapper {
            margin-top: 40px;
            padding-top: 40px;
            border-top: 1px solid var(--border);
            display: flex;
            gap: 12px;
        }
        .followup-input {
            flex: 1;
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 14px 16px;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            font-family: var(--font);
        }
        .followup-input:focus { border-color: var(--accent); }
        .btn-send {
            background: var(--accent);
            color: var(--accent-text);
            border: none;
            width: 44px; height: 44px;
            border-radius: 8px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
        }
        .btn-send svg { width: 18px; height: 18px; }

        /* Footer Limit */
        .footer-limit {
            margin-top: 60px;
            padding-top: 24px;
            border-top: 1px solid var(--border);
            text-align: center;
            font-size: 11px;
            color: var(--text-muted);
        }

        /* Highlights */
        .hl-green { color: #4ade80; border-bottom: 1px solid #4ade80; }
        .hl-blue { color: #60a5fa; border-bottom: 1px solid #60a5fa; }
        .hl-purple { color: #c084fc; border-bottom: 1px solid #c084fc; }
        .hl-yellow { color: #facc15; border-bottom: 1px solid #facc15; }

        @media (max-width: 768px) {
            .hero h1 { font-size: 32px; }
            .container { padding: 40px 20px; }
            nav { padding: 20px; }
            .option-card { min-width: 160px; }
        }
    </style>
</head>
<body>

<nav>
    <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        Winy AI
    </div>
    <button class="btn-pro" onclick="alert('Pro features are coming soon! We are building something amazing.')">Upgrade to Pro</button>
</nav>

<div class="container">
    <div class="hero">
        <h1>Deploy the Swarm.</h1>
        <p>Elite business strategy generation. Deep research, financial modeling, and actionable roadmaps in seconds.</p>
    </div>

    <div class="input-wrapper" id="inputWrapper">
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
                    <option value="long" disabled>Deep Dive (Comprehensive)</option>
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
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
            Initialize Swarm
        </button>
    </div>

    <div class="swarm-loader" id="swarmLoader">
        <div class="swarm-core"></div>
        <div class="swarm-text">Swarm Processing</div>
    </div>

    <div class="results-area" id="resultsArea">
        <div class="results-header">
            <h2>Strategic Output</h2>
            <div style="display:flex; gap:8px;">
                <button class="btn-icon" onclick="copyResults()" title="Copy Text">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
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
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>                                                 </button>                                           </div>
    </div>

    <div class="footer-limit">
        You're currently on free tier. <span style="color:#fff; cursor:pointer; text-decoration:underline;" onclick="alert('Pro features coming soon!')">Upgrade to Pro</span>.                                                     </div>
</div>                                                  
<script>                                                    let currentContext = '';
    let currentIndustry = '';

    function highlightText(text) {
        const map = {
            'market': 'hl-green', 'revenue': 'hl-blue', 'growth': 'hl-blue',
            'strategy': 'hl-purple', 'ROI': 'hl-yellow', 'profit': 'hl-green',
            'cost': 'hl-yellow', 'budget': 'hl-yellow', 'customers': 'hl-blue'                                          };                                                      let html = text;
        for (const [word, cls] of Object.entries(map)) {
            const regex = new RegExp(`\\\\b${word}\\\\b`, 'gi');
            html = html.replace(regex, `<span class="${cls}">${word}</span>`);                                          }
        return html;                                        }

    function toggleAccordion(element) {
        const item = element.parentElement;
        const isActive = item.classList.contains('active');

        // Close all
        document.querySelectorAll('.accordion-item').forEach(i => i.classList.remove('active'));                
        // Open clicked if it wasn't active
        if (!isActive) item.classList.add('active');
    }

    function renderResults(data) {                              document.getElementById('unifiedSummary').innerHTML = highlightText(data.summary);                      
        const sections = [                                          { id: 'market', title: 'Market Analysis', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>' },
            { id: 'strategy', title: 'Operational Strategy', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>' },
            { id: 'financials', title: 'Financial Projections', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>' },                                                  { id: 'gtm', title: 'Go-to-Market Plan', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>' }
        ];

        let accHtml = '';
        sections.forEach(sec => {                                   accHtml += `                                                <div class="accordion-item">
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

        // Render Costs
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
        const prompt = document.getElementById('mainPrompt').value.trim();
        if (!prompt) return alert('Please enter a business idea.');

        const industry = document.getElementById('optIndustry').value;                                                  const length = document.getElementById('optLength').value;
        const tone = document.getElementById('optTone').value;
                                                                currentContext = prompt;
        currentIndustry = industry;

        document.getElementById('inputWrapper').style.display = 'none';
        document.getElementById('resultsArea').classList.remove('active');
        document.getElementById('swarmLoader').classList.add('active');

        try {
            const res = await fetch('/generate', {                      method: 'POST',                                         headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, industry, length, tone })                                                    });
            const data = await res.json();
                                                                    document.getElementById('swarmLoader').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';                                                document.getElementById('resultsArea').classList.add('active');

            renderResults(data);
        } catch (e) {
            alert('Error: ' + e.message);
            document.getElementById('swarmLoader').classList.remove('active');
            document.getElementById('inputWrapper').style.display = 'block';
        }                                                   }

    async function askFollowup() {
        const q = document.getElementById('followupInput').value.trim();
        if (!q) return;                                 
        const btn = document.querySelector('.btn-send');        btn.innerHTML = '<div style="width:16px;height:16px;border:2px solid #000;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></div>';

        try {                                                       const res = await fetch('/followup', {
                method: 'POST',                                         headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: q, context: currentContext, industry: currentIndustry })
            });                                                     const data = await res.json();

            // Append to summary or create a new section (simplified: append to summary)                                    const summaryEl = document.getElementById('unifiedSummary');
            summaryEl.innerHTML += `<br><br><strong style="color:#fff;">Q: ${q}</strong><br><br>${highlightText(data.answer)}`;
            document.getElementById('followupInput').value = '';
        } catch(e) {                                                alert('Follow-up failed: ' + e.message);
        }

        btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
    }

    function copyResults() {                                    const text = document.getElementById('unifiedSummary').innerText + '\\n\\n' +
                     Array.from(document.querySelectorAll('.accordion-text')).map(e => e.innerText).join('\\n\\n');                                                             navigator.clipboard.writeText(text).then(() => alert('Copied to clipboard.'));                              }
</script>
<style>@keyframes spin { to { transform: rotate(360deg); } }</style>                                            </body>
</html>
'''

@app.route('/')                                         def home():
    return render_template_string(HTML_TEMPLATE)        
@app.route('/generate', methods=['POST'])
def generate():                                             data = request.json
    prompt = data['prompt']                                 industry = data['industry']
    length = data['length']                                 tone = data['tone']

    word_map = {'short': '200 words', 'medium': '350 words', 'long': '500 words'}
    limit = word_map.get(length, '350 words')

    # Use 8b model - faster, cheaper, more reliable for this task
    sys = f"""You are a business consultant. Industry: {industry}. Tone: {tone}.                                    Provide a business analysis for: {prompt}
                                                            Format your response EXACTLY like this (copy the structure):

    SUMMARY:
    [2-3 sentence overview]                             
    MARKET:
    [Market analysis - {limit}]

    STRATEGY:                                               [Operational plan - {limit}]

    FINANCIALS:
    [Revenue model - {limit}]
                                                            GTM:
    [Marketing plan - {limit}]

    COSTS:                                                  Product Dev: [number only, e.g., 5000]
    Marketing: [number only]
    Operations: [number only]
    Legal: [number only]
    Contingency: [number only]                              """
                                                            raw = call_llm(sys, prompt, temperature=0.7)

    # Parse the structured text                             sections = {                                                'summary': '', 'market': '', 'strategy': '',
        'financials': '', 'gtm': '', 'costs': {}            }                                                   
    current_section = None                                  for line in raw.split('\n'):                                line = line.strip()
        if line.startswith('SUMMARY:'):                             current_section = 'summary'                         elif line.startswith('MARKET:'):
            current_section = 'market'
        elif line.startswith('STRATEGY:'):
            current_section = 'strategy'                        elif line.startswith('FINANCIALS:'):
            current_section = 'financials'
        elif line.startswith('GTM:'):
            current_section = 'gtm'
        elif line.startswith('COSTS:'):
            current_section = 'costs'                           elif current_section and line:
            if current_section == 'costs' and ':' in line:
                try:
                    key, val = line.split(':', 1)
                    sections['costs'][key.strip()] = int(val.strip().replace(',', '').replace('$', ''))
                except:
                    pass
            elif current_section:
                sections[current_section] += line + "\n"
                                                            # Calculate total if missing
    if 'total' not in sections['costs']:
        sections['costs']['total'] = sum(v for k,v in sections['costs'].items() if isinstance(v, int))

    # Fallback costs if parsing failed
    if not sections['costs'] or sections['costs'].get('total', 0) == 0:                                                 base_costs = {
            'Technology': {'Product Dev': 8000, 'Marketing': 3000, 'Operations': 2000, 'Legal': 1500, 'Contingency': 1500},
            'E-commerce': {'Product Dev': 3000, 'Marketing': 4000, 'Operations': 2500, 'Legal': 1000, 'Contingency': 1500},
            'Food & Beverage': {'Product Dev': 5000, 'Marketing': 3500, 'Operations': 8000, 'Legal': 2000, 'Contingency': 3000},
        }
        sections['costs'] = base_costs.get(industry, {'Product Dev': 5000, 'Marketing': 3000, 'Operations': 3000, 'Legal': 1500, 'Contingency': 1500})                          sections['costs']['total'] = sum(sections['costs'].values())

    return jsonify(sections)

@app.route('/followup', methods=['POST'])               def followup():
    data = request.json
    q = data['question']                                    ctx = data['context']
    ind = data['industry']

    sys = f"You are the Winy AI Strategy Swarm. Context: User is building a {ind} business based on this idea: '{ctx}'. Answer the following question concisely and professionally in about 150 words."
    ans = call_llm(sys, f"Question: {q}", temperature=0.7)

    return jsonify({"answer": ans})

if __name__ == '__main__':
    print("\n[WINY AI] Swarm Online. Port 5000.\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
