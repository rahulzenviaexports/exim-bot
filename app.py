import os
import time
import json
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# --- GLOBAL STATE & PERSISTENCE ---
DATA_FILE = "exim_config.json"
STATE = {
    "running": False,
    "last_check": "Never"
}
LOGS = []
SEEN_LEADS = set()

def load_data():
    """Loads configuration and target products from a JSON file."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "telegram_token": "8985436294:AAFmTeHQM2PKVAgKjI_VY--4UJYrndoiBZw",
        "telegram_chat_id": "2132933443",
        "products": []
    }

def save_data(data):
    """Saves configuration and target products to a JSON file."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def add_log(message, type="info"):
    """Adds a timestamped log to the in-memory log queue."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {"time": timestamp, "message": message, "type": type}
    LOGS.append(log_entry)
    print(f"[{timestamp}] {message}")
    if len(LOGS) > 100:  # Keep only the last 100 logs to save memory
        LOGS.pop(0)

def send_telegram_alert(lead, matched_keyword, config):
    """Formats and sends the lead alert to Telegram."""
    token = config.get("telegram_token")
    chat_id = config.get("telegram_chat_id")
    
    if not token or not chat_id:
        add_log("Telegram alert skipped: Token or Chat ID not configured.", "error")
        return

    message = (
        f"🚨 *NEW BUY LEADER DETECTED* 🚨\n\n"
        f"📌 *Match Trigger:* {matched_keyword}\n"
        f"📦 *Product:* {lead['product']}\n"
        f"🌍 *Country:* {lead['country']}\n"
        f"🏢 *Buyer:* {lead['buyer']}\n"
        f"📝 *Details:* {lead['description']}\n"
        f"⏳ *Valid Until:* {lead['validity']}\n\n"
        f"🔗 [Contact Buyer]({lead['link']})"
    )
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        add_log(f"Alert sent to Telegram for {lead['product']} ({lead['country']})", "success")
    except Exception as e:
        add_log(f"Failed to send Telegram alert: {e}", "error")

def is_lead_a_match(product_text, details_text, country_text, products_config):
    """Evaluates if the scraped lead matches any of our target products and countries."""
    product_upper = product_text.upper()
    details_upper = details_text.upper()
    country_upper = country_text.upper()

    for p in products_config:
        # Check if Name or HS code is in the product title or description
        name_match = p["name"].upper() in product_upper or p["name"].upper() in details_upper
        hs_match = False
        if p.get("hs_code"):
            hs_code_str = str(p["hs_code"]).strip()
            hs_match = hs_code_str in product_upper or hs_code_str in details_upper
        
        if name_match or hs_match:
            # If the product matches, check if the country matches (or if all countries targeted)
            target_countries = [c.upper().strip() for c in p.get("countries", []) if c.strip()]
            if not target_countries or country_upper in target_countries:
                return p["name"] # Return the name of the matched product target
                
    return False

def scrape_apeda_leads():
    """Scrapes buyer inquiries from APEDA AgriExchange."""
    url = "https://agriexchange.apeda.gov.in/Buyer/MyBuyOffers"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    data = load_data()
    if not data["products"]:
        add_log("No target products configured. Skipping scrape.", "warning")
        return

    add_log(f"Checking APEDA for new leads... (Monitoring {len(data['products'])} targets)")
    STATE["last_check"] = time.strftime("%I:%M %p")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")
        
        rows = soup.find_all("tr")
        leads_found = 0
        matches_found = 0
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                leads_found += 1
                product = cols[0].text.strip()
                buyer_name = cols[2].text.strip()
                country = cols[3].text.strip()
                details = cols[4].text.strip()
                
                lead_id = f"{buyer_name}_{product}_{country}"
                if lead_id in SEEN_LEADS:
                    continue
                
                matched_target = is_lead_a_match(product, details, country, data["products"])
                
                if matched_target:
                    matches_found += 1
                    lead_data = {
                        "product": product,
                        "buyer": buyer_name,
                        "country": country,
                        "description": details[:150] + "..." if len(details) > 150 else details,
                        "validity": "Active",
                        "link": url
                    }
                    
                    send_telegram_alert(lead_data, matched_keyword=matched_target, config=data)
                    SEEN_LEADS.add(lead_id)
        
        add_log(f"Scrape complete: {leads_found} leads parsed, {matches_found} new matches found.")

    except Exception as e:
        add_log(f"Error scraping portal: {e}", "error")

def background_scraper_loop():
    """Runs the scraper continuously in the background when active."""
    while True:
        if STATE["running"]:
            scrape_apeda_leads()
            
            # Wait 15 minutes (900 seconds) but check every second if we should stop
            for _ in range(900):
                if not STATE["running"]:
                    break
                time.sleep(1)
        else:
            time.sleep(2) # Idle state

# Start the background thread immediately
thread = threading.Thread(target=background_scraper_loop, daemon=True)
thread.start()

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EXIM Lead Discovery Bot</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .log-container::-webkit-scrollbar { width: 8px; }
        .log-container::-webkit-scrollbar-track { background: #1e293b; }
        .log-container::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 min-h-screen">
    
    <!-- Top Navbar -->
    <nav class="bg-slate-800 border-b border-slate-700 p-4 sticky top-0 z-10">
        <div class="max-w-7xl mx-auto flex justify-between items-center">
            <div class="flex items-center space-x-3">
                <div class="bg-blue-500/20 p-2 rounded-lg text-blue-400">
                    <i class="fa-solid fa-ship text-xl"></i>
                </div>
                <h1 class="text-xl font-bold text-white tracking-tight">EXIM Lead Notifier</h1>
            </div>
            <div class="flex items-center space-x-4 text-sm font-medium">
                <span id="status-indicator" class="flex items-center space-x-2 bg-slate-700 px-3 py-1.5 rounded-full">
                    <span class="w-2.5 h-2.5 rounded-full bg-slate-500" id="status-dot"></span>
                    <span id="status-text">Stopped</span>
                </span>
            </div>
        </div>
    </nav>

    <div class="max-w-7xl mx-auto p-4 lg:p-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        <!-- Left Column: Controls & Config -->
        <div class="space-y-6">
            
            <!-- Scraper Control Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <div class="absolute top-0 right-0 p-3 opacity-10">
                    <i class="fa-solid fa-power-off text-6xl"></i>
                </div>
                <h2 class="text-lg font-semibold text-white mb-4">Engine Control</h2>
                <div class="flex items-center space-x-4 mb-4">
                    <button id="btn-start" onclick="toggleEngine('start')" class="flex-1 bg-emerald-500 hover:bg-emerald-600 text-white py-3 rounded-xl font-semibold transition-all shadow-lg shadow-emerald-500/20 flex items-center justify-center space-x-2">
                        <i class="fa-solid fa-play"></i> <span>Start Bot</span>
                    </button>
                    <button id="btn-stop" onclick="toggleEngine('stop')" class="flex-1 bg-rose-500 hover:bg-rose-600 text-white py-3 rounded-xl font-semibold transition-all shadow-lg shadow-rose-500/20 opacity-50 cursor-not-allowed flex items-center justify-center space-x-2" disabled>
                        <i class="fa-solid fa-stop"></i> <span>Stop Bot</span>
                    </button>
                </div>
                <p class="text-sm text-slate-400">Last Checked: <span id="last-checked" class="text-slate-300 font-medium">Never</span></p>
            </div>

            <!-- Telegram Config Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl">
                <h2 class="text-lg font-semibold text-white mb-4 flex items-center space-x-2">
                    <i class="fa-brands fa-telegram text-blue-400"></i>
                    <span>Telegram Alerts</span>
                </h2>
                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Bot Token</label>
                        <input type="password" id="tg-token" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all" placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Chat ID</label>
                        <input type="text" id="tg-chat-id" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all" placeholder="-100123456789">
                    </div>
                    <button onclick="saveConfig()" class="w-full bg-slate-700 hover:bg-slate-600 text-white py-2 rounded-lg text-sm font-medium transition-colors">
                        Save Configuration
                    </button>
                </div>
            </div>

            <!-- Live Logs Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl flex flex-col h-[350px]">
                <h2 class="text-lg font-semibold text-white mb-4 flex items-center justify-between">
                    <span><i class="fa-solid fa-terminal mr-2 text-slate-400"></i> System Logs</span>
                    <button onclick="clearLogs()" class="text-xs text-slate-500 hover:text-slate-300"><i class="fa-solid fa-trash"></i></button>
                </h2>
                <div id="logs-container" class="flex-1 bg-slate-900 rounded-xl p-4 overflow-y-auto log-container font-mono text-xs space-y-2 border border-slate-700/50">
                    <!-- Logs will be injected here -->
                </div>
            </div>
        </div>

        <!-- Right Column: Product Management -->
        <div class="lg:col-span-2 space-y-6">
            <div class="bg-slate-800 border border-slate-700 rounded-2xl shadow-xl overflow-hidden flex flex-col h-full">
                
                <!-- Add Product Header Form -->
                <div class="p-6 border-b border-slate-700 bg-slate-800/50">
                    <h2 class="text-lg font-semibold text-white mb-4">Targeted Products</h2>
                    <form id="add-product-form" onsubmit="addProduct(event)" class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
                        <div class="md:col-span-4">
                            <label class="block text-xs font-medium text-slate-400 mb-1">Product Name *</label>
                            <input type="text" id="prod-name" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none" placeholder="e.g. Makhana, Turmeric">
                        </div>
                        <div class="md:col-span-3">
                            <label class="block text-xs font-medium text-slate-400 mb-1">HS Code (Optional)</label>
                            <input type="text" id="prod-hs" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none" placeholder="e.g. 19041090">
                        </div>
                        <div class="md:col-span-3">
                            <label class="block text-xs font-medium text-slate-400 mb-1">Countries (Comma sep.)</label>
                            <input type="text" id="prod-countries" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none" placeholder="e.g. USA, UAE, UK">
                        </div>
                        <div class="md:col-span-2">
                            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg text-sm font-medium transition-colors h-[38px]">
                                Add Target
                            </button>
                        </div>
                    </form>
                </div>

                <!-- Products Table -->
                <div class="flex-1 overflow-auto bg-slate-900/50">
                    <table class="w-full text-left text-sm text-slate-300">
                        <thead class="text-xs uppercase bg-slate-800/80 text-slate-400 sticky top-0">
                            <tr>
                                <th class="px-6 py-4 font-medium">Product Name</th>
                                <th class="px-6 py-4 font-medium">HS Code</th>
                                <th class="px-6 py-4 font-medium">Target Markets</th>
                                <th class="px-6 py-4 font-medium text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody id="products-table-body" class="divide-y divide-slate-700/50">
                            <!-- Rows injected via JS -->
                        </tbody>
                    </table>
                    
                    <!-- Empty State -->
                    <div id="empty-state" class="hidden flex flex-col items-center justify-center p-12 text-slate-500">
                        <i class="fa-solid fa-box-open text-4xl mb-3 opacity-50"></i>
                        <p>No products targeted yet.</p>
                        <p class="text-xs mt-1">Add a product above to start monitoring EXIM leads.</p>
                    </div>
                </div>

            </div>
        </div>

    </div>

    <script>
        // Fetch Initial State
        async function fetchState() {
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                
                // Update Config
                document.getElementById('tg-token').value = data.config.telegram_token;
                document.getElementById('tg-chat-id').value = data.config.telegram_chat_id;
                
                // Update Products
                renderProducts(data.config.products);
                
                // Update Status
                updateStatusUI(data.running, data.last_check);
            } catch (e) {
                console.error("Failed to fetch state", e);
            }
        }

        // Render Products Table
        function renderProducts(products) {
            const tbody = document.getElementById('products-table-body');
            const emptyState = document.getElementById('empty-state');
            
            tbody.innerHTML = '';
            
            if (products.length === 0) {
                emptyState.classList.remove('hidden');
                return;
            }
            
            emptyState.classList.add('hidden');
            
            products.forEach((p, index) => {
                const countries = p.countries && p.countries.length > 0 
                    ? p.countries.map(c => `<span class="px-2 py-1 bg-slate-700 rounded-md text-xs mr-1 mb-1 inline-block">${c}</span>`).join('') 
                    : '<span class="px-2 py-1 bg-blue-900/50 text-blue-300 rounded-md text-xs">Global (All)</span>';
                
                const tr = document.createElement('tr');
                tr.className = "hover:bg-slate-800/50 transition-colors group";
                tr.innerHTML = `
                    <td class="px-6 py-4 font-medium text-white">${p.name}</td>
                    <td class="px-6 py-4 font-mono text-slate-400">${p.hs_code || '-'}</td>
                    <td class="px-6 py-4 flex flex-wrap">${countries}</td>
                    <td class="px-6 py-4 text-right">
                        <button onclick="deleteProduct(${index})" class="text-slate-500 hover:text-rose-400 transition-colors p-2 rounded-lg hover:bg-rose-400/10 opacity-0 group-hover:opacity-100 focus:opacity-100">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        // Add Product
        async function addProduct(e) {
            e.preventDefault();
            const btn = e.target.querySelector('button[type="submit"]');
            btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
            
            const name = document.getElementById('prod-name').value.trim();
            const hs_code = document.getElementById('prod-hs').value.trim();
            const countriesStr = document.getElementById('prod-countries').value.trim();
            
            const countries = countriesStr ? countriesStr.split(',').map(c => c.trim()).filter(c => c) : [];
            
            try {
                const res = await fetch('/api/products', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name, hs_code, countries})
                });
                if (res.ok) {
                    document.getElementById('add-product-form').reset();
                    fetchState();
                }
            } catch (err) {
                alert("Failed to add product");
            } finally {
                btn.innerHTML = 'Add Target';
            }
        }

        // Delete Product
        async function deleteProduct(index) {
            if(!confirm("Remove this target product?")) return;
            try {
                await fetch(`/api/products/${index}`, { method: 'DELETE' });
                fetchState();
            } catch(e) {
                alert("Failed to delete.");
            }
        }

        // Save Config
        async function saveConfig() {
            const token = document.getElementById('tg-token').value.trim();
            const chatId = document.getElementById('tg-chat-id').value.trim();
            
            try {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ telegram_token: token, telegram_chat_id: chatId })
                });
                alert("Configuration Saved!");
            } catch(e) {
                alert("Error saving configuration.");
            }
        }

        // Engine Control UI Updates
        function updateStatusUI(isRunning, lastCheck) {
            const dot = document.getElementById('status-dot');
            const text = document.getElementById('status-text');
            const btnStart = document.getElementById('btn-start');
            const btnStop = document.getElementById('btn-stop');
            
            document.getElementById('last-checked').innerText = lastCheck;

            if (isRunning) {
                dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse";
                text.innerText = "Monitoring Active";
                text.className = "text-emerald-400";
                
                btnStart.disabled = true;
                btnStart.classList.add('opacity-50', 'cursor-not-allowed');
                btnStop.disabled = false;
                btnStop.classList.remove('opacity-50', 'cursor-not-allowed');
            } else {
                dot.className = "w-2.5 h-2.5 rounded-full bg-slate-500";
                text.innerText = "Engine Stopped";
                text.className = "text-slate-400";
                
                btnStart.disabled = false;
                btnStart.classList.remove('opacity-50', 'cursor-not-allowed');
                btnStop.disabled = true;
                btnStop.classList.add('opacity-50', 'cursor-not-allowed');
            }
        }

        // Toggle Engine
        async function toggleEngine(action) {
            try {
                const res = await fetch('/api/engine', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ action: action })
                });
                const data = await res.json();
                updateStatusUI(data.running, data.last_check);
            } catch(e) {
                console.error(e);
            }
        }

        // Fetch and Render Logs
        async function fetchLogs() {
            try {
                const res = await fetch('/api/logs');
                const logs = await res.json();
                const container = document.getElementById('logs-container');
                
                let isScrolledToBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 10;
                
                container.innerHTML = logs.map(log => {
                    let color = 'text-slate-400';
                    let icon = 'fa-info-circle';
                    if (log.type === 'error') { color = 'text-rose-400'; icon = 'fa-triangle-exclamation'; }
                    if (log.type === 'success') { color = 'text-emerald-400'; icon = 'fa-check'; }
                    if (log.type === 'warning') { color = 'text-amber-400'; icon = 'fa-bolt'; }
                    
                    return `<div class="flex items-start space-x-2 border-b border-slate-800 pb-1">
                                <span class="text-slate-500 shrink-0">[${log.time.split(' ')[1]}]</span>
                                <i class="fa-solid ${icon} mt-[2px] ${color} text-[10px] shrink-0"></i>
                                <span class="${color}">${log.message}</span>
                            </div>`;
                }).join('');
                
                if (isScrolledToBottom) {
                    container.scrollTop = container.scrollHeight;
                }
            } catch(e) {}
        }
        
        async function clearLogs() {
            await fetch('/api/logs', { method: 'DELETE' });
            fetchLogs();
        }

        // Initialization & Polling
        fetchState();
        fetchLogs();
        
        // Poll status and logs every 2 seconds
        setInterval(async () => {
            fetchLogs();
            const res = await fetch('/api/state');
            const data = await res.json();
            updateStatusUI(data.running, data.last_check);
        }, 2000);

    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/state")
def get_state():
    return jsonify({
        "config": load_data(),
        "running": STATE["running"],
        "last_check": STATE["last_check"]
    })

@app.route("/api/config", methods=["POST"])
def update_config():
    req_data = request.json
    data = load_data()
    data["telegram_token"] = req_data.get("telegram_token", data["telegram_token"])
    data["telegram_chat_id"] = req_data.get("telegram_chat_id", data["telegram_chat_id"])
    save_data(data)
    add_log("Telegram configuration updated.", "success")
    return jsonify({"status": "ok"})

@app.route("/api/products", methods=["POST"])
def add_product():
    req_data = request.json
    data = load_data()
    new_product = {
        "name": req_data.get("name", "").strip(),
        "hs_code": req_data.get("hs_code", "").strip(),
        "countries": req_data.get("countries", [])
    }
    data["products"].append(new_product)
    save_data(data)
    add_log(f"Target added: {new_product['name']}", "success")
    return jsonify({"status": "ok"})

@app.route("/api/products/<int:index>", methods=["DELETE"])
def delete_product(index):
    data = load_data()
    if 0 <= index < len(data["products"]):
        removed = data["products"].pop(index)
        save_data(data)
        add_log(f"Target removed: {removed['name']}", "warning")
    return jsonify({"status": "ok"})

@app.route("/api/engine", methods=["POST"])
def toggle_engine():
    action = request.json.get("action")
    if action == "start":
        STATE["running"] = True
        add_log("Scraping engine STARTED.", "success")
    elif action == "stop":
        STATE["running"] = False
        add_log("Scraping engine STOPPED.", "warning")
    return jsonify({"running": STATE["running"], "last_check": STATE["last_check"]})

@app.route("/api/logs", methods=["GET"])
def get_logs():
    return jsonify(LOGS)

@app.route("/api/logs", methods=["DELETE"])
def delete_logs():
    LOGS.clear()
    add_log("Logs cleared.")
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # Ensure config file exists initially
    if not os.path.exists(DATA_FILE):
        save_data({"telegram_token": "", "telegram_chat_id": "", "products": []})
        
    add_log("Dashboard starting... Accessible at http://127.0.0.1:5000")
    # Turn off default Flask request logging for cleaner terminal output
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    # Run the web server
    app.run(debug=False, port=5000, host='0.0.0.1')
# ... existing code ...
STATE = {
    "running": False,
    "last_check": "Never"
}
LOGS = []
SEEN_LEADS = set()

# --- MOCK BUYER DATABASE ---
# In a production environment, this would connect to an API like Apollo.io or a custom PostgreSQL database.
MOCK_BUYERS_DB = [
    {"name": "Global Spice Co.", "country": "USA", "interest": ["TURMERIC", "SPICES"], "email": "procurement@globalspice.com", "phone": "+1-555-0192", "verified": True},
    {"name": "Desert Traders LLC", "country": "UAE", "interest": ["MAKHANA", "FOX NUT", "DRY FRUITS"], "email": "purchasing@deserttraders.ae", "phone": "+971-50-1234567", "verified": True},
    {"name": "EuroAgri Imports", "country": "Germany", "interest": ["RICE", "WHEAT", "GRAINS"], "email": "import@euroagri.de", "phone": "+49-30-123456", "verified": False},
    {"name": "London Asian Foods", "country": "UK", "interest": ["MAKHANA", "TURMERIC", "INDIAN GROCERIES"], "email": "buyer@londonasian.co.uk", "phone": "+44-20-7946", "verified": True},
    {"name": "Saudi Agro Corp", "country": "Saudi Arabia", "interest": ["RICE", "SPICES"], "email": "info@saudiagro.sa", "phone": "+966-11-456789", "verified": True},
    {"name": "Sydney Organics", "country": "Australia", "interest": ["TURMERIC", "HONEY", "ORGANIC"], "email": "sourcing@sydneyorganics.com.au", "phone": "+61-2-1234", "verified": False},
    {"name": "Nippon Traders", "country": "Japan", "interest": ["SESAME", "SPICES"], "email": "import@nippontraders.jp", "phone": "+81-3-1234", "verified": True},
]

def load_data():
# ... existing code ...
        else:
            time.sleep(2) # Idle state

# Start the background thread immediately
thread = threading.Thread(target=background_scraper_loop, daemon=True)
thread.start()

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EXIM Lead Discovery Bot</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .log-container::-webkit-scrollbar { width: 8px; }
        .log-container::-webkit-scrollbar-track { background: #1e293b; }
        .log-container::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
        
        .tab-btn { transition: all 0.2s ease-in-out; }
        .tab-active { background-color: #3b82f6; color: white; border-color: #3b82f6; }
        .tab-inactive { background-color: transparent; color: #94a3b8; border-color: #334155; }
        .tab-inactive:hover { background-color: #334155; color: #cbd5e1; }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 min-h-screen flex flex-col">
    
    <!-- Top Navbar -->
    <nav class="bg-slate-800 border-b border-slate-700 p-4 sticky top-0 z-10">
        <div class="max-w-7xl mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
            <div class="flex items-center space-x-3">
                <div class="bg-blue-500/20 p-2 rounded-lg text-blue-400">
                    <i class="fa-solid fa-ship text-xl"></i>
                </div>
                <h1 class="text-xl font-bold text-white tracking-tight">EXIM Lead Notifier</h1>
            </div>
            
            <!-- Tabs -->
            <div class="flex space-x-2 bg-slate-900/50 p-1 rounded-lg border border-slate-700">
                <button onclick="switchTab('live')" id="btn-tab-live" class="tab-btn tab-active px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2">
                    <i class="fa-solid fa-satellite-dish"></i> <span>Live Scraper</span>
                </button>
                <button onclick="switchTab('directory')" id="btn-tab-directory" class="tab-btn tab-inactive px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2">
                    <i class="fa-solid fa-address-book"></i> <span>Buyer Directory</span>
                </button>
            </div>

            <div class="flex items-center space-x-4 text-sm font-medium">
                <span id="status-indicator" class="flex items-center space-x-2 bg-slate-700 px-3 py-1.5 rounded-full">
                    <span class="w-2.5 h-2.5 rounded-full bg-slate-500" id="status-dot"></span>
                    <span id="status-text">Stopped</span>
                </span>
            </div>
        </div>
    </nav>

    <!-- MAIN VIEW: LIVE SCRAPER -->
    <div id="view-live" class="max-w-7xl mx-auto p-4 lg:p-8 w-full grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        <!-- Left Column: Controls & Config -->
        <div class="space-y-6">
            
            <!-- Scraper Control Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <div class="absolute top-0 right-0 p-3 opacity-10">
                    <i class="fa-solid fa-power-off text-6xl"></i>
                </div>
                <h2 class="text-lg font-semibold text-white mb-4">Engine Control</h2>
                <div class="flex items-center space-x-4 mb-4">
                    <button id="btn-start" onclick="toggleEngine('start')" class="flex-1 bg-emerald-500 hover:bg-emerald-600 text-white py-3 rounded-xl font-semibold transition-all shadow-lg shadow-emerald-500/20 flex items-center justify-center space-x-2">
                        <i class="fa-solid fa-play"></i> <span>Start Bot</span>
                    </button>
                    <button id="btn-stop" onclick="toggleEngine('stop')" class="flex-1 bg-rose-500 hover:bg-rose-600 text-white py-3 rounded-xl font-semibold transition-all shadow-lg shadow-rose-500/20 opacity-50 cursor-not-allowed flex items-center justify-center space-x-2" disabled>
                        <i class="fa-solid fa-stop"></i> <span>Stop Bot</span>
                    </button>
                </div>
                <p class="text-sm text-slate-400">Last Checked: <span id="last-checked" class="text-slate-300 font-medium">Never</span></p>
            </div>

            <!-- Telegram Config Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl">
                <h2 class="text-lg font-semibold text-white mb-4 flex items-center space-x-2">
                    <i class="fa-brands fa-telegram text-blue-400"></i>
                    <span>Telegram Alerts</span>
                </h2>
                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Bot Token</label>
                        <input type="password" id="tg-token" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all" placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Chat ID</label>
                        <input type="text" id="tg-chat-id" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all" placeholder="-100123456789">
                    </div>
                    <button onclick="saveConfig()" class="w-full bg-slate-700 hover:bg-slate-600 text-white py-2 rounded-lg text-sm font-medium transition-colors">
                        Save Configuration
                    </button>
                </div>
            </div>

            <!-- Live Logs Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl flex flex-col h-[350px]">
                <h2 class="text-lg font-semibold text-white mb-4 flex items-center justify-between">
                    <span><i class="fa-solid fa-terminal mr-2 text-slate-400"></i> System Logs</span>
                    <button onclick="clearLogs()" class="text-xs text-slate-500 hover:text-slate-300"><i class="fa-solid fa-trash"></i></button>
                </h2>
                <div id="logs-container" class="flex-1 bg-slate-900 rounded-xl p-4 overflow-y-auto log-container font-mono text-xs space-y-2 border border-slate-700/50">
                    <!-- Logs will be injected here -->
                </div>
            </div>
        </div>

        <!-- Right Column: Product Management -->
        <div class="lg:col-span-2 space-y-6">
            <div class="bg-slate-800 border border-slate-700 rounded-2xl shadow-xl overflow-hidden flex flex-col h-full">
                
                <!-- Add Product Header Form -->
                <div class="p-6 border-b border-slate-700 bg-slate-800/50">
                    <h2 class="text-lg font-semibold text-white mb-4">Targeted Products</h2>
                    <form id="add-product-form" onsubmit="addProduct(event)" class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
                        <div class="md:col-span-4">
                            <label class="block text-xs font-medium text-slate-400 mb-1">Product Name *</label>
                            <input type="text" id="prod-name" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none" placeholder="e.g. Makhana, Turmeric">
                        </div>
                        <div class="md:col-span-3">
                            <label class="block text-xs font-medium text-slate-400 mb-1">HS Code (Optional)</label>
                            <input type="text" id="prod-hs" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none" placeholder="e.g. 19041090">
                        </div>
                        <div class="md:col-span-3">
                            <label class="block text-xs font-medium text-slate-400 mb-1">Countries (Comma sep.)</label>
                            <input type="text" id="prod-countries" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none" placeholder="e.g. USA, UAE, UK">
                        </div>
                        <div class="md:col-span-2">
                            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg text-sm font-medium transition-colors h-[38px]">
                                Add Target
                            </button>
                        </div>
                    </form>
                </div>

                <!-- Products Table -->
                <div class="flex-1 overflow-auto bg-slate-900/50">
                    <table class="w-full text-left text-sm text-slate-300">
                        <thead class="text-xs uppercase bg-slate-800/80 text-slate-400 sticky top-0">
                            <tr>
                                <th class="px-6 py-4 font-medium">Product Name</th>
                                <th class="px-6 py-4 font-medium">HS Code</th>
                                <th class="px-6 py-4 font-medium">Target Markets</th>
                                <th class="px-6 py-4 font-medium text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody id="products-table-body" class="divide-y divide-slate-700/50">
                            <!-- Rows injected via JS -->
                        </tbody>
                    </table>
                    
                    <!-- Empty State -->
                    <div id="empty-state" class="hidden flex flex-col items-center justify-center p-12 text-slate-500">
                        <i class="fa-solid fa-box-open text-4xl mb-3 opacity-50"></i>
                        <p>No products targeted yet.</p>
                        <p class="text-xs mt-1">Add a product above to start monitoring EXIM leads.</p>
                    </div>
                </div>

            </div>
        </div>

    </div>

    <!-- MAIN VIEW: BUYER DIRECTORY (Hidden by default) -->
    <div id="view-directory" class="max-w-7xl mx-auto p-4 lg:p-8 w-full hidden flex-col flex-1">
        <div class="flex justify-between items-end mb-6">
            <div>
                <h2 class="text-2xl font-bold text-white mb-1">Global Buyer Database</h2>
                <p class="text-slate-400 text-sm">Discover existing international buyers matching your targeted products.</p>
            </div>
            <button onclick="fetchDirectory()" class="bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center space-x-2">
                <i class="fa-solid fa-rotate-right"></i> <span>Refresh Matches</span>
            </button>
        </div>

        <div id="directory-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <!-- Directory Cards Injected Here -->
        </div>
        
        <div id="directory-empty" class="hidden flex flex-col items-center justify-center p-20 bg-slate-800/50 border border-slate-700 rounded-2xl text-slate-500 mt-6">
            <i class="fa-solid fa-magnifying-glass text-5xl mb-4 opacity-50"></i>
            <h3 class="text-xl font-medium text-slate-300">No matching buyers found</h3>
            <p class="mt-2 text-center max-w-md text-sm">We couldn't find any existing buyers in the database for your specific products. Try adding more general targets like "Spices" or "Rice".</p>
        </div>
    </div>

    <script>
        // --- TAB SWITCHING LOGIC ---
        function switchTab(tabId) {
            const btnLive = document.getElementById('btn-tab-live');
            const btnDir = document.getElementById('btn-tab-directory');
            const viewLive = document.getElementById('view-live');
            const viewDir = document.getElementById('view-directory');

            if(tabId === 'live') {
                btnLive.className = 'tab-btn tab-active px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border';
                btnDir.className = 'tab-btn tab-inactive px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-transparent';
                viewLive.classList.remove('hidden');
                viewLive.classList.add('grid');
                viewDir.classList.add('hidden');
                viewDir.classList.remove('flex');
            } else {
                btnDir.className = 'tab-btn tab-active px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border';
                btnLive.className = 'tab-btn tab-inactive px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-transparent';
                viewDir.classList.remove('hidden');
                viewDir.classList.add('flex');
                viewLive.classList.add('hidden');
                viewLive.classList.remove('grid');
                fetchDirectory(); // Load data when opening tab
            }
        }

        // --- DIRECTORY LOGIC ---
        async function fetchDirectory() {
            try {
                const res = await fetch('/api/directory');
                const buyers = await res.json();
                renderDirectory(buyers);
            } catch (e) {
                console.error("Failed to fetch directory", e);
            }
        }

        function renderDirectory(buyers) {
            const grid = document.getElementById('directory-grid');
            const emptyState = document.getElementById('directory-empty');
            
            grid.innerHTML = '';
            
            if (buyers.length === 0) {
                emptyState.classList.remove('hidden');
                grid.classList.add('hidden');
                return;
            }
            
            emptyState.classList.add('hidden');
            grid.classList.remove('hidden');
            
            buyers.forEach(buyer => {
                const tags = buyer.interest.map(i => `<span class="bg-blue-900/30 text-blue-400 border border-blue-800/50 px-2 py-0.5 rounded text-xs">${i}</span>`).join('');
                const badge = buyer.verified 
                    ? `<span class="flex items-center space-x-1 text-emerald-400 text-xs bg-emerald-400/10 px-2 py-1 rounded-full"><i class="fa-solid fa-circle-check"></i> <span>Verified</span></span>` 
                    : `<span class="flex items-center space-x-1 text-amber-400 text-xs bg-amber-400/10 px-2 py-1 rounded-full"><i class="fa-solid fa-circle-question"></i> <span>Unverified</span></span>`;
                
                const card = document.createElement('div');
                card.className = "bg-slate-800 border border-slate-700 p-5 rounded-xl shadow-lg hover:border-slate-600 transition-colors flex flex-col";
                card.innerHTML = `
                    <div class="flex justify-between items-start mb-4">
                        <div>
                            <h3 class="font-bold text-white text-lg">${buyer.name}</h3>
                            <div class="text-sm text-slate-400 flex items-center space-x-1 mt-1">
                                <i class="fa-solid fa-location-dot"></i> <span>${buyer.country}</span>
                            </div>
                        </div>
                        ${badge}
                    </div>
                    <div class="mb-4 flex-1">
                        <p class="text-xs text-slate-500 mb-2 uppercase tracking-wide font-semibold">Interested In:</p>
                        <div class="flex flex-wrap gap-2">
                            ${tags}
                        </div>
                    </div>
                    <div class="pt-4 border-t border-slate-700 space-y-2">
                        <a href="mailto:${buyer.email}" class="flex items-center space-x-2 text-sm text-slate-300 hover:text-white transition-colors group">
                            <div class="w-8 h-8 rounded bg-slate-700 flex items-center justify-center group-hover:bg-blue-600 transition-colors">
                                <i class="fa-solid fa-envelope"></i>
                            </div>
                            <span>${buyer.email}</span>
                        </a>
                        <div class="flex items-center space-x-2 text-sm text-slate-300 group">
                            <div class="w-8 h-8 rounded bg-slate-700 flex items-center justify-center">
                                <i class="fa-solid fa-phone"></i>
                            </div>
                            <span>${buyer.phone}</span>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        // Fetch Initial State
        async function fetchState() {
# ... existing code ...
        // Initialization & Polling
        fetchState();
        fetchLogs();
        
        // Poll status and logs every 2 seconds
        setInterval(async () => {
            fetchLogs();
            const res = await fetch('/api/state');
            const data = await res.json();
            updateStatusUI(data.running, data.last_check);
        }, 2000);

    </script>
</body>
</html>
"""

@app.route("/")
def index():
# ... existing code ...
@app.route("/api/logs", methods=["DELETE"])
def delete_logs():
    LOGS.clear()
    add_log("Logs cleared.")
    return jsonify({"status": "ok"})

@app.route("/api/directory", methods=["GET"])
def get_directory():
    """Matches configured target products with the mock buyer database."""
    config = load_data()
    target_products = [p["name"].upper() for p in config.get("products", [])]
    
    # If no targets are set, don't show any buyers
    if not target_products:
        return jsonify([])
        
    matched_buyers = []
    
    for buyer in MOCK_BUYERS_DB:
        # Check if any of the buyer's interests align with our targeted products
        # A simple keyword match: if our target word is in their interest list
        buyer_interests = [i.upper() for i in buyer["interest"]]
        
        is_match = False
        for target in target_products:
            for interest in buyer_interests:
                if target in interest or interest in target:
                    is_match = True
                    break
            if is_match:
                break
                
        if is_match:
            matched_buyers.append(buyer)
            
    return jsonify(matched_buyers)


if __name__ == "__main__":
    # Ensure config file exists initially
# ... existing code ...
