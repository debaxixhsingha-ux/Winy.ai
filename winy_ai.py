from flask import Flask, request, jsonify
import requests
import os
import re

app = Flask(__name__)

# This reads the secret key from Render's vault
API_KEY = os.environ.get("API_KEY")

url = "https://api.groq.com/openai/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Clean AI text to remove annoying ** and ##
def clean_text(text):
    text = text.replace('**', '')
    text = text.replace('*', '')
    text = text.replace('_', '')
    text = re.sub(r'#+\s*', '', text) # remove headers
    text = re.sub(r'^[\-\•]\s*', '', text, flags=re.MULTILINE) # remove bullets
    return text.strip()

def call_agent(system_prompt, context):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context}
    ]
    data = {"model": "llama-3.1-8b-instant", "messages": messages, "temperature": 0.5}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=45)
        result = response.json()['choices'][0]['message']['content']
        return clean_text(result)
    except Exception as e:
        return f"Agent offline: {str(e)}"

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Winy AI | Swarm Intelligence</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
            body {
                background: #050505; color: #e0e0e0;
                font-family: 'Inter', -apple-system, sans-serif;
                min-height: 100vh;
            }

            /* Top Loading Bar (Like YouTube/GitHub) */
            #progress-bar {
                position: fixed; top: 0; left: 0; height: 2px;
                background: #fff; width: 0%; z-index: 9999;
                transition: width 0.4s ease; box-shadow: 0 0 10px #fff;
            }

            /* Navigation */
            nav {
                display: flex; justify-content: space-between; align-items: center;
                padding: 20px 30px; border-bottom: 1px solid #1a1a1a;
                background: rgba(5,5,5,0.8); backdrop-filter: blur(10px);
                position: sticky; top: 0; z-index: 100;
            }
            .nav-logo { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; color: #fff; }
            .nav-badge { font-size: 11px; color: #888; background: #1a1a1a; padding: 4px 8px; border-radius: 4px; font-weight: 500;}

            /* Main Content */
            .container { max-width: 800px; margin: 0 auto; padding: 40px 20px; }

            .hero-text { margin-bottom: 30px; }
            .hero-text h1 { font-size: 32px; font-weight: 700; color: #fff; margin-bottom: 10px; letter-spacing: -1px; }
            .hero-text p { font-size: 15px; color: #888; line-height: 1.6; }

            /* Input Area */
            .input-card {
                background: #0a0a0a; border: 1px solid #222; border-radius: 16px;
                padding: 25px; margin-bottom: 40px;
            }
            textarea {
                width: 100%; min-height: 100px; background: transparent; border: none;
                color: #fff; font-size: 16px; font-family: inherit; resize: none; outline: none;
                margin-bottom: 20px; line-height: 1.6;
            }
            .input-footer { display: flex; justify-content: flex-end; }
            .launch-btn {
                background: #fff; color: #000; border: none; padding: 12px 24px;
                border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer;
                display: flex; align-items: center; gap: 8px; transition: all 0.2s;
            }
            .launch-btn:hover { background: #ddd; }
            .launch-btn:disabled { background: #333; color: #666; cursor: not-allowed; }

            /* Button Spinner */
            .spinner {
                width: 14px; height: 14px; border: 2px solid #666; border-top-color: #fff;
                border-radius: 50%; animation: spin 1s linear infinite; display: none;
            }
            .launch-btn.loading .spinner { display: block; }
            .launch-btn.loading .btn-text { display: none; }
            .launch-btn.loading .loading-text { display: inline; }
            .loading-text { display: none; }
            @keyframes spin { to { transform: rotate(360deg); } }

            /* Horizontal Slider Results */
            .results-header { display: none; margin-bottom: 20px; align-items: center; gap: 10px; }
            .results-header.active { display: flex; }
            .results-header h2 { font-size: 18px; font-weight: 600; color: #fff; }
            .results-hint { font-size: 13px; color: #666; }

            .swarm-carousel {
                display: none; /* Hidden until loaded */
                overflow-x: auto; scroll-snap-type: x mandatory;
                gap: 20px; padding-bottom: 20px;
                scrollbar-width: none; /* Firefox */
            }
            .swarm-carousel::-webkit-scrollbar { display: none; } /* Chrome/Safari */
            .swarm-carousel.active { display: flex; }

            .agent-card {
                flex: 0 0 85vw; /* Takes up 85% of screen width */
                max-width: 600px;
                scroll-snap-align: start;
                background: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 16px;
                padding: 30px; min-height: 400px;
            }
            .agent-badge {
                display: inline-block; font-size: 11px; font-weight: 600; text-transform: uppercase;
                letter-spacing: 1px; padding: 6px 12px; border-radius: 20px; margin-bottom: 20px;
            }
            .badge-research { background: rgba(59, 130, 246, 0.1); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.2); }
            .badge-strategy { background: rgba(168, 85, 247, 0.1); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.2); }
            .badge-marketing { background: rgba(236, 72, 153, 0.1); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.2); }
            .badge-manager { background: rgba(255, 255, 255, 0.1); color: #fff; border: 1px solid rgba(255, 255, 255, 0.2); }

            .agent-content {
                font-size: 15px; line-height: 1.8; color: #bbb; white-space: pre-wrap;
            }

            /* Empty State */
            .empty-state {
                text-align: center; padding: 60px 20px; color: #444;
                border: 1px dashed #222; border-radius: 16px;
            }
        </style>
    </head>
    <body>
        <div id="progress-bar"></div>

        <nav>
            <div class="nav-logo">Winy AI</div>
            <div class="nav-badge">Multi-Agent v2.0</div>
        </nav>

        <div class="container">
            <div class="hero-text">
                <h1>Deploy your AI Swarm.</h1>
                <p>Enter a business idea, problem, or project. Our specialized agents will research, strategize, and build a comprehensive plan.</p>
            </div>

            <div class="input-card">
                <textarea id="prompt" placeholder="What should the swarm solve? (e.g., Start a premium sneaker cleaning service for college students)"></textarea>
                <div class="input-footer">
                    <button class="launch-btn" onclick="launchSwarm()" id="launchBtn">
                        <div class="spinner"></div>
                        <span class="btn-text">Launch Swarm</span>
                        <span class="loading-text">Processing...</span>
                    </button>
                </div>
            </div>

            <div class="results-header" id="resultsHeader">
                <h2>Swarm Output</h2>
                <span class="results-hint">← Swipe to see all agents →</span>
            </div>

            <div class="swarm-carousel" id="carousel">
                <!-- Cards injected here -->
            </div>

            <div class="empty-state" id="emptyState">
                Your swarm results will appear here.
            </div>
        </div>

        <script>
            async function launchSwarm() {
                const prompt = document.getElementById('prompt').value.trim();
                if (!prompt) { alert('Please enter a prompt'); return; }

                const btn = document.getElementById('launchBtn');
                const bar = document.getElementById('progress-bar');
                const emptyState = document.getElementById('emptyState');

                // UI Loading State
                btn.disabled = true;
                btn.classList.add('loading');
                emptyState.style.display = 'none';

                // Start Progress Bar
                bar.style.width = '30%';
                setTimeout(() => bar.style.width = '60%', 1000);
                setTimeout(() => bar.style.width = '80%', 3000);

                try {
                    const res = await fetch('/generate', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({prompt: prompt})
                    });
                    const data = await res.json();

                    bar.style.width = '100%';

                    const agents = [
                        { badge: 'badge-research', title: 'Market Researcher', content: data.research },
                        { badge: 'badge-strategy', title: 'Business Strategist', content: data.strategy },
                        { badge: 'badge-marketing', title: 'Viral Marketer', content: data.marketing },
                        { badge: 'badge-manager', title: 'Executive Manager', content: data.manager }
                    ];

                    let html = '';
                    agents.forEach(agent => {
                        html += `
                            <div class="agent-card">
                                <div class="agent-badge ${agent.badge}">${agent.title}</div>
                                <div class="agent-content">${agent.content}</div>
                            </div>
                        `;
                    });

                    document.getElementById('carousel').innerHTML = html;
                    document.getElementById('carousel').classList.add('active');
                    document.getElementById('resultsHeader').classList.add('active');

                    setTimeout(() => { bar.style.width = '0%'; }, 500);

                } catch (e) {
                    alert('Connection failed. Please try again.');
                    bar.style.width = '0%';
                }

                btn.disabled = false;
                btn.classList.remove('loading');
            }
        </script>
    </body>
    </html>
    '''

@app.route('/generate', methods=['POST'])
def generate():
    user_prompt = request.json.get('prompt')

    # Strict instructions to avoid markdown
    no_markdown = "Write in plain paragraphs. DO NOT use markdown, bolding, asterisks (**), hash symbols (#), or bullet points. Just write clean, readable text."

    # 1. RESEARCHER
    research = call_agent(
        f"You are an expert Market Researcher. {no_markdown}",
        f"Analyze this idea: {user_prompt}. Provide target audience details, 3 key market insights, and current trends."
    )

    # 2. STRATEGIST
    strategy = call_agent(
        f"You are an expert Business Strategist. {no_markdown}",
        f"Idea: {user_prompt}. Research: {research}. Create a step-by-step launch plan, timeline, and resource list."
    )

    # 3. MARKETER
    marketing = call_agent(
        f"You are an expert Viral Marketer. {no_markdown}",
        f"Idea: {user_prompt}. Strategy: {strategy}. Create a marketing plan, positioning strategy, and 3 specific campaign ideas."
    )

    # 4. MANAGER
    manager = call_agent(
        f"You are the CEO. {no_markdown}",
        f"Idea: {user_prompt}. Research: {research}. Strategy: {strategy}. Marketing: {marketing}. Write a final executive summary combining all this into actionable next steps."
    )

    return jsonify({
        "research": research,
        "strategy": strategy,
        "marketing": marketing,
        "manager": manager
    })

if __name__ == '__main__':
    print("\n WINY AI SWARM ONLINE\n")
    app.run(host='0.0.0.0', port=5000)
