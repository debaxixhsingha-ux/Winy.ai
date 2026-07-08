from flask import Flask, request, jsonify, render_template_string, session
import requests
import re
import os
import razorpay
import hmac
import hashlib

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
    <title>Winy AI</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #fff;
            color: #000;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
            padding: 80px 20px 40px;
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
        
        nav {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            width: 90%;
            max-width: 640px;
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 100;
            background: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 100px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
        }
        .logo { font-size: 16px; font-weight: 700; }
        
        .btn {
            background: rgba(0, 0, 0, 0.05);
            border: 1px solid rgba(0, 0, 0, 0.1);
            color: #000;
            padding: 8px 16px;
            border-radius: 100px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn:hover { background: rgba(0, 0, 0, 0.1); }
        
        .container {
            max-width: 640px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }
        
        h1 {
            font-size: 40px;
            font-weight: 700;
            margin-bottom: 12px;
            text-align: center;
        }
        .sub { color: #666; text-align: center; margin-bottom: 40px; }
        
        .card {
            background: rgba(0, 0, 0, 0.02);
            backdrop-filter: blur(40px);
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 24px;
            padding: 32px;
            margin-bottom: 32px;
        }
        
        textarea {
            width: 100%;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 12px;
            padding: 16px;
            font-size: 15px;
            margin-bottom: 16px;
            min-height: 80px;
            resize: none;
        }
        textarea:focus { outline: 2px solid rgba(0,0,0,0.2); }
        
        select {
            width: 100%;
            background: rgba(0, 0, 0, 0.03);
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 12px;
            padding: 16px;
            font-size: 15px;
            margin-bottom: 16px;
        }
        
        .btn-main {
            width: 100%;
            background: #000;
            color: #fff;
            border: none;
            border-radius: 12px;
            padding: 18px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 8px;
        }
        .btn-main:hover { opacity: 0.9; }
        
        .loader {
            display: none;
            text-align: center;
            padding: 60px 20px;
        }
        .loader.active { display: block; }
        
        .results { display: none; }
        .results.active { display: block; }
        
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.9);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .modal.active { display: flex; }
        .modal-content {
            background: #fff;
            border: 1px solid rgba(0,0,0,0.1);
            border-radius: 20px;
            padding: 32px;
            max-width: 400px;
            width: 100%;
            text-align: center;
        }
        .modal h3 { margin-bottom: 16px; font-size: 20px; }
        .modal p { color: #666; margin-bottom: 24px; line-height: 1.5; }
        .modal-btn {
            background: #000;
            color: #fff;
            border: none;
            padding: 12px 24px;
            border-radius: 100px;
            font-weight: 600;
            cursor: pointer;
        }
    </style>
</head>
<body>

<div class="bg-shape shape-1"></div>
<div class="bg-shape shape-2"></div>

<nav>
    <div class="logo">Winy AI</div>
    <button class="btn" onclick="payNow()">Upgrade to Pro</button>
</nav>

<div class="container">
    <h1>Deploy the Swarm.</h1>
    <p class="sub">Elite business strategy generation.</p>

    <div id="inputArea">
        <div class="card">
            <textarea id="prompt" placeholder="Describe your business idea..."></textarea>
            <select id="industry">
                <option value="General">General</option>
                <option value="Technology">Technology</option>
                <option value="E-commerce">E-commerce</option>
            </select>
            <select id="depth">
                <option value="medium">Standard</option>
                <option value="short">Brief</option>
                <option value="long">Deep Dive (Pro)</option>
            </select>
            <button class="btn-main" onclick="generate()">Initialize Swarm</button>
        </div>
    </div>

    <div class="loader" id="loader">
        <p style="color:#666; font-size:14px;">Swarm processing...</p>
    </div>

    <div class="results" id="results">
        <div class="card">
            <h2 style="margin-bottom:20px;">Results</h2>
            <div id="output"></div>
            <button class="btn-main" onclick="resetApp()" style="margin-top:20px;">New Strategy</button>
        </div>
    </div>

    <p style="text-align:center; color:#666; font-size:12px; margin-top:40px;">
        Free tier: 3 uses/day. <span style="text-decoration:underline; cursor:pointer;" onclick="payNow()">Upgrade to Pro</span>
    </p>
</div>

<div class="modal" id="modal">
    <div class="modal-content">
        <h3 id="modalTitle">Title</h3>
        <p id="modalMsg">Message</p>
        <button class="modal-btn" onclick="closeModal()">OK</button>
    </div>
</div>

<script>
    // Simple variables
    var isPro = false;
    var used = 0;
    var maxUses = 3;

    function showModal(title, msg) {
        document.getElementById('modalTitle').textContent = title;
        document.getElementById('modalMsg').textContent = msg;
        document.getElementById('modal').classList.add('active');
    }

    function closeModal() {
        document.getElementById('modal').classList.remove('active');
    }

    function generate() {
        var prompt = document.getElementById('prompt').value.trim();
        if (!prompt) {
            showModal('Error', 'Please enter a business idea');
            return;
        }

        if (!isPro && used >= maxUses) {
            showModal('Limit Reached', 'You have used all 3 free generations. Please upgrade to Pro.');
            return;
        }

        var industry = document.getElementById('industry').value;
        var depth = document.getElementById('depth').value;

        // Show loader
        document.getElementById('inputArea').style.display = 'none';
        document.getElementById('loader').classList.add('active');

        // Call backend
        fetch('/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt: prompt,
                industry: industry,
                length: depth,
                tone: 'Professional'
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            document.getElementById('loader').classList.remove('active');
            document.getElementById('results').classList.add('active');
            document.getElementById('output').innerHTML = '<pre style="white-space:pre-wrap; line-height:1.6;">' + data.summary + '</pre>';
            used++;
        })
        .catch(function(err) {
            document.getElementById('loader').classList.remove('active');
            document.getElementById('inputArea').style.display = 'block';
            showModal('Error', 'Failed to generate: ' + err.message);
        });
    }

    function payNow() {
        fetch('/api/create-order', {method: 'POST'})
        .then(function(res) { return res.json(); })
        .then(function(order) {
            var options = {
                key: "{{ razorpay_key_id }}",
                amount: order.amount,
                currency: order.currency,
                name: 'Winy AI',
                description: 'Pro Subscription',
                order_id: order.order_id,
                handler: function(response) {
                    // Verify payment
                    return fetch('/api/verify-payment', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(response)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.status === 'success') {
                            isPro = true;
                            used = 0;
                            showModal('Success!', 'Payment successful! You are now Pro.');
                        } else {
                            showModal('Error', 'Payment verification failed');
                        }
                    });
                },
                theme: {color: '#000000'}
            };
            var rzp = new Razorpay(options);
            rzp.open();
        })
        .catch(function(err) {
            showModal('Error', 'Failed to start payment: ' + err.message);
        });
    }

    function resetApp() {
        document.getElementById('results').classList.remove('active');
        document.getElementById('inputArea').style.display = 'block';
        document.getElementById('prompt').value = '';
    }
</script>

</body>
</html>
'''

@app.route('/')
def home():
    if 'used' not in session:
        session['used'] = 0
    if 'is_pro' not in session:
        session['is_pro'] = False
    return render_template_string(HTML_TEMPLATE, razorpay_key_id=RAZORPAY_KEY_ID)

@app.route('/generate', methods=['POST'])
def generate():
    if not session.get('is_pro') and session.get('used', 0) >= 3:
        return jsonify({"error": "Limit reached"}), 403

    data = request.json
    prompt = data.get('prompt', '')
    industry = data.get('industry', 'General')
    length = data.get('length', 'medium')
    
    sys = f"Business consultant for {industry}. Analyze: {prompt}. Provide SUMMARY, MARKET, STRATEGY, FINANCIALS sections."
    result = call_llm(sys, prompt)
    
    if not session.get('is_pro'):
        session['used'] = session.get('used', 0) + 1
    
    return jsonify({"summary": result})

@app.route('/api/create-order', methods=['POST'])
def create_order():
    try:
        order = razorpay_client.order.create({
            "amount": 49900,
            "currency": "INR",
            "receipt": "receipt_1",
            "payment_capture": 1
        })
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
def verify_payment():
    try:
        data = request.json
        sig = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            f"{data.get('razorpay_order_id')}|{data.get('razorpay_payment_id')}".encode(),
            hashlib.sha256
        ).hexdigest()
        
        if sig == data.get('razorpay_signature'):
            session['is_pro'] = True
            session['used'] = 0
            return jsonify({"status": "success"})
        return jsonify({"status": "failure"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
