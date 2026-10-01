import os
import time
import json
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

CONFIG_FILE = "exim_config.json"
STATE = {
    "running": False,
    "last_check": "Never"
}
LOGS = []
SEEN_LEADS = set()

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
    if not os.path.exists(CONFIG_FILE):
        default_config = {"tg_token": "", "tg_chat_id": "", "products": []}
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f)
        return default_config
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {"tg_token": "", "tg_chat_id": "", "products": []}

def save_data(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def add_log(msg):
    timestamp = time.strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    LOGS.append(formatted_msg)
    if len(LOGS) > 50:
        LOGS.pop(0)
    print(formatted_msg)

def send_telegram_alert(lead, matched_keyword, config):
    token = config.get("tg_token")
    chat_id = config.get("tg_chat_id")
    
    if not token or not chat_id:
        add_log("Telegram alert skipped: Token or Chat ID not configured.")
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
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            add_log(f"Telegram alert sent for {lead['product']} ({lead['country']})")
        else:
            add_log(f"Telegram API Error: {response.text}")
    except Exception as e:
        add_log(f"Failed to send Telegram alert: {e}")

def is_lead_a_match(product_text, details_text, country_text, target_products):
    product_upper = product_text.upper()
    details_upper = details_text.upper()
    country_upper = country_text.upper()

    for p in target_products:
        name_match = p["name"].upper() in product_upper or p["name"].upper() in details_upper
        hs_match = False
        if p.get("hs_code"):
            hs_code_str = str(p["hs_code"])
            hs_match = hs_code_str in product_upper or hs_code_str in details_upper
        
        if name_match or hs_match:
            countries = p.get("countries", [])
            if not countries or len(countries) == 0:
                return p["name"]
            
            target_countries_upper = [c.strip().upper() for c in countries]
            if country_upper in target_countries_upper:
                return p["name"]
                
    return False

def scrape_apeda_leads(config):
    url = "https://agriexchange.apeda.gov.in/Buyer/MyBuyOffers"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    target_products = config.get("products", [])

    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, "html.parser")
        rows = soup.find_all("tr")
        
        leads_processed = 0
        matches_found = 0
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                leads_processed += 1
                product = cols[0].text.strip()
                buyer_name = cols[2].text.strip()
                country = cols[3].text.strip()
                details = cols[4].text.strip()
                
                lead_id = f"{buyer_name}_{product}_{country}"
                if lead_id in SEEN_LEADS:
                    continue
                
                matched_target = is_lead_a_match(product, details, country, target_products)
                
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
                    
                    add_log(f"MATCH FOUND: {matched_target} -> {product} ({country})")
                    send_telegram_alert(lead_data, matched_target, config)
                    SEEN_LEADS.add(lead_id)

        add_log(f"Scraped {leads_processed} leads. Found {matches_found} new matches.")
    except Exception as e:
        add_log(f"Error scraping portal: {str(e)}")

def background_scraper_loop():
    add_log("Background engine initialized. Waiting for START signal.")
    while True:
        if STATE["running"]:
            config = load_data()
            products = config.get("products", [])
            
            if not products:
                add_log("Engine running, but no products are targeted. Please add products.")
                time.sleep(15)
                continue
                
            add_log(f"Initiating scan for {len(products)} targeted product(s)...")
            scrape_apeda_leads(config)
            STATE["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            add_log("Scan complete. Sleeping for 15 minutes...")
            
            # Sleep in chunks so we can interrupt it if the user clicks Stop
            for _ in range(15 * 60): 
                if not STATE["running"]:
                    add_log("Engine stopped by user during sleep cycle.")
                    break
                time.sleep(1)
        else:
            time.sleep(2) # Idle state checking every 2 seconds

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
        .log-container::-webkit-scrollbar-track { background: #1e293b; border-radius: 4px; }
        .log-container::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
        .log-container::-webkit-scrollbar-thumb:hover { background: #64748b; }
        
        .tab-btn { transition: all 0.2s ease-in-out; }
        .tab-active { background-color: #3b82f6; color: white; border-color: #3b82f6; }
        .tab-inactive { background-color: transparent; color: #94a3b8; border-color: #334155; }
        .tab-inactive:hover { background-color: #334155; color: #cbd5e1; }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 min-h-screen flex flex-col">
    
    <nav class="bg-slate-800 border-b border-slate-700 p-4 sticky top-0 z-10 shadow-lg">
        <div class="max-w-7xl mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
            <div class="flex items-center space-x-3">
                <div class="bg-blue-500/20 p-2.5 rounded-lg text-blue-400">
                    <i class="fa-solid fa-ship text-xl"></i>
                </div>
                <div>
                    <h1 class="text-xl font-bold text-white tracking-tight">EXIM Lead Notifier</h1>
                    <p class="text-xs text-slate-400 font-medium">Automated Buyer Discovery</p>
                </div>
            </div>
            
            <div class="flex space-x-2 bg-slate-900/50 p-1 rounded-lg border border-slate-700">
                <button onclick="switchTab('live')" id="btn-tab-live" class="tab-btn tab-active px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border">
                    <i class="fa-solid fa-satellite-dish"></i> <span>Live Scraper</span>
                </button>
                <button onclick="switchTab('directory')" id="btn-tab-directory" class="tab-btn tab-inactive px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-transparent">
                    <i class="fa-solid fa-address-book"></i> <span>Buyer Directory</span>
                </button>
            </div>

            <div class="flex items-center space-x-4 text-sm font-medium">
                <span id="status-indicator" class="flex items-center space-x-2 bg-slate-700 px-3 py-1.5 rounded-full border border-slate-600 shadow-inner">
                    <span class="w-2.5 h-2.5 rounded-full bg-slate-400" id="status-dot"></span>
                    <span id="status-text">Stopped</span>
                </span>
            </div>
        </div>
    </nav>

    <div id="view-live" class="max-w-7xl mx-auto p-4 lg:p-8 w-full grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        <div class="space-y-6">
            <!-- Engine Control Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl relative overflow-hidden group">
                <div class="absolute top-0 right-0 p-4 opacity-5 transition-opacity group-hover:opacity-10">
                    <i class="fa-solid fa-microchip text-7xl"></i>
                </div>
                <h2 class="text-lg font-semibold text-white mb-4">Engine Control</h2>
                <div class="flex items-center space-x-4 mb-4 relative z-10">
                    <button id="btn-start" onclick="toggleEngine('start')" class="flex-1 bg-emerald-500 hover:bg-emerald-600 text-white py-3 rounded-xl font-bold transition-all shadow-lg shadow-emerald-500/20 flex items-center justify-center space-x-2">
                        <i class="fa-solid fa-play"></i> <span>Start Bot</span>
                    </button>
                    <button id="btn-stop" onclick="toggleEngine('stop')" class="flex-1 bg-rose-500 hover:bg-rose-600 text-white py-3 rounded-xl font-bold transition-all shadow-lg shadow-rose-500/20 opacity-50 cursor-not-allowed flex items-center justify-center space-x-2" disabled>
                        <i class="fa-solid fa-stop"></i> <span>Stop Bot</span>
                    </button>
                </div>
                <p class="text-sm text-slate-400">Last Checked: <span id="last-checked" class="text-slate-200 font-medium bg-slate-900 px-2 py-0.5 rounded">Never</span></p>
            </div>

            <!-- Telegram Config Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl">
                <h2 class="text-lg font-semibold text-white mb-4 flex items-center space-x-2">
                    <i class="fa-brands fa-telegram text-blue-400"></i>
                    <span>Telegram Alerts</span>
                </h2>
                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Bot Token</label>
                        <input type="password" id="tg-token" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all placeholder-slate-600" placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Chat ID</label>
                        <input type="text" id="tg-chat-id" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all placeholder-slate-600" placeholder="-100123456789">
                    </div>
                    <button onclick="saveConfig()" class="w-full bg-slate-700 hover:bg-slate-600 text-white py-2.5 rounded-lg text-sm font-semibold transition-colors">
                        Save Configuration
                    </button>
                </div>
            </div>

            <!-- Live Logs Card -->
            <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl flex flex-col h-[380px]">
                <h2 class="text-lg font-semibold text-white mb-4 flex items-center justify-between">
                    <span><i class="fa-solid fa-terminal mr-2 text-slate-400"></i> System Logs</span>
                    <button onclick="clearLogs()" class="text-xs text-slate-400 hover:text-white px-2 py-1 bg-slate-900 rounded border border-slate-700 transition-colors"><i class="fa-solid fa-trash mr-1"></i> Clear</button>
                </h2>
                <div id="logs-container" class="flex-1 bg-slate-900 rounded-xl p-4 overflow-y-auto log-container font-mono text-xs space-y-2 border border-slate-700 shadow-inner">
                    <!-- Logs will be injected here -->
                </div>
            </div>
        </div>

        <div class="lg:col-span-2 space-y-6">
            <div class="bg-slate-800 border border-slate-700 rounded-2xl shadow-xl overflow-hidden flex flex-col h-full">
                
                <div class="p-6 border-b border-slate-700 bg-slate-800/80">
                    <h2 class="text-lg font-semibold text-white mb-4 flex items-center space-x-2">
                        <i class="fa-solid fa-crosshairs text-emerald-400"></i>
                        <span>Targeted Products</span>
                    </h2>
                    <form id="add-product-form" onsubmit="addProduct(event)" class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
                        <div class="md:col-span-4">
                            <label class="block text-xs font-semibold text-slate-400 mb-1.5">Product Name *</label>
                            <input type="text" id="prod-name" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white focus:ring-2 focus:ring-emerald-500 outline-none placeholder-slate-600" placeholder="e.g. Makhana, Turmeric">
                        </div>
                        <div class="md:col-span-3">
                            <label class="block text-xs font-semibold text-slate-400 mb-1.5">HS Code (Optional)</label>
                            <input type="text" id="prod-hs" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white focus:ring-2 focus:ring-emerald-500 outline-none placeholder-slate-600" placeholder="e.g. 19041090">
                        </div>
                        <div class="md:col-span-3">
                            <label class="block text-xs font-semibold text-slate-400 mb-1.5">Countries (Comma sep.)</label>
                            <input type="text" id="prod-countries" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white focus:ring-2 focus:ring-emerald-500 outline-none placeholder-slate-600" placeholder="e.g. USA, UAE">
                        </div>
                        <div class="md:col-span-2">
                            <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 rounded-lg text-sm font-semibold transition-colors shadow-lg shadow-emerald-600/20 h-[42px]">
                                Add Target
                            </button>
                        </div>
                    </form>
                </div>

                <div class="flex-1 overflow-auto bg-slate-900/50 relative">
                    <table class="w-full text-left text-sm text-slate-300">
                        <thead class="text-xs uppercase bg-slate-800/95 text-slate-400 sticky top-0 border-b border-slate-700 shadow-sm z-10">
                            <tr>
                                <th class="px-6 py-4 font-semibold">Product Name</th>
                                <th class="px-6 py-4 font-semibold">HS Code</th>
                                <th class="px-6 py-4 font-semibold">Target Markets</th>
                                <th class="px-6 py-4 font-semibold text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody id="products-table-body" class="divide-y divide-slate-700/50">
                            <!-- Rows injected via JS -->
                        </tbody>
                    </table>
                    
                    <div id="empty-state" class="hidden absolute inset-0 flex flex-col items-center justify-center p-12 text-slate-500 bg-slate-900/50 backdrop-blur-sm z-0">
                        <i class="fa-solid fa-box-open text-5xl mb-4 opacity-30"></i>
                        <p class="font-medium text-slate-400">No products targeted yet.</p>
                        <p class="text-xs mt-1 text-slate-500">Add a product above to start monitoring EXIM leads.</p>
                    </div>
                </div>

            </div>
        </div>

    </div>

    <div id="view-directory" class="max-w-7xl mx-auto p-4 lg:p-8 w-full hidden flex-col flex-1">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-end mb-8 gap-4">
            <div>
                <h2 class="text-3xl font-bold text-white mb-2 tracking-tight">Global Buyer Database</h2>
                <p class="text-slate-400 text-sm max-w-xl border-l-2 border-blue-500 pl-3">This directory automatically cross-references your targeted products with our database to surface verified international buyers instantly.</p>
            </div>
            <button onclick="fetchDirectory()" class="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center space-x-2 shadow-lg shadow-blue-500/20 whitespace-nowrap">
                <i class="fa-solid fa-rotate-right"></i> <span>Refresh Matches</span>
            </button>
        </div>

        <div id="directory-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <!-- Directory Cards Injected Here -->
        </div>
        
        <div id="directory-empty" class="hidden flex flex-col items-center justify-center p-20 bg-slate-800/50 border border-slate-700 rounded-2xl text-slate-500 mt-6 shadow-inner">
            <i class="fa-solid fa-magnifying-glass text-6xl mb-6 opacity-20"></i>
            <h3 class="text-xl font-semibold text-slate-300">No matching buyers found</h3>
            <p class="mt-2 text-center max-w-md text-sm leading-relaxed">We couldn't find any existing buyers in the database for your specific products. Try adding broader targets like "Spices" or "Rice" to your Live Scraper tab.</p>
            <button onclick="switchTab('live')" class="mt-6 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm font-medium transition-colors">Go back to setup</button>
        </div>
    </div>

    <script>
        function switchTab(tabId) {
            const btnLive = document.getElementById('btn-tab-live');
            const btnDir = document.getElementById('btn-tab-directory');
            const viewLive = document.getElementById('view-live');
            const viewDir = document.getElementById('view-directory');

            if(tabId === 'live') {
                btnLive.className = 'tab-btn tab-active px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-blue-500';
                btnDir.className = 'tab-btn tab-inactive px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-transparent';
                viewLive.classList.remove('hidden');
                viewLive.classList.add('grid');
                viewDir.classList.add('hidden');
                viewDir.classList.remove('flex');
            } else {
                btnDir.className = 'tab-btn tab-active px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-blue-500';
                btnLive.className = 'tab-btn tab-inactive px-4 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 border border-transparent';
                viewDir.classList.remove('hidden');
                viewDir.classList.add('flex');
                viewLive.classList.add('hidden');
                viewLive.classList.remove('grid');
                fetchDirectory(); 
            }
        }

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
                const tags = buyer.interest.map(i => `<span class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2.5 py-1 rounded-md text-xs font-medium tracking-wide">${i}</span>`).join('');
                const badge = buyer.verified 
                    ? `<span class="flex items-center space-x-1.5 text-emerald-400 text-xs font-bold bg-emerald-400/10 px-2.5 py-1 rounded-full"><i class="fa-solid fa-certificate"></i> <span>Verified</span></span>` 
                    : `<span class="flex items-center space-x-1.5 text-slate-400 text-xs font-bold bg-slate-700/50 px-2.5 py-1 rounded-full"><i class="fa-regular fa-circle-question"></i> <span>Unverified</span></span>`;
                
                const card = document.createElement('div');
                card.className = "bg-slate-800 border border-slate-700 p-6 rounded-2xl shadow-xl hover:border-slate-500 hover:shadow-2xl transition-all flex flex-col group";
                card.innerHTML = `
                    <div class="flex justify-between items-start mb-5">
                        <div>
                            <h3 class="font-bold text-white text-lg group-hover:text-blue-400 transition-colors">${buyer.name}</h3>
                            <div class="text-sm text-slate-400 flex items-center space-x-1.5 mt-1.5 font-medium">
                                <i class="fa-solid fa-earth-americas opacity-75"></i> <span>${buyer.country}</span>
                            </div>
                        </div>
                        ${badge}
                    </div>
                    <div class="mb-6 flex-1">
                        <p class="text-[11px] text-slate-500 mb-2.5 uppercase tracking-wider font-bold">Import Interests</p>
                        <div class="flex flex-wrap gap-2">
                            ${tags}
                        </div>
                    </div>
                    <div class="pt-5 border-t border-slate-700 space-y-3">
                        <a href="mailto:${buyer.email}" class="flex items-center space-x-3 text-sm text-slate-300 hover:text-white transition-colors group/link p-2 -ml-2 rounded-lg hover:bg-slate-700/50">
                            <div class="w-8 h-8 rounded-lg bg-slate-900 border border-slate-700 flex items-center justify-center group-hover/link:bg-blue-600 group-hover/link:border-blue-500 transition-colors text-slate-400 group-hover/link:text-white shadow-sm">
                                <i class="fa-solid fa-envelope"></i>
                            </div>
                            <span class="font-medium">${buyer.email}</span>
                        </a>
                        <div class="flex items-center space-x-3 text-sm text-slate-300 p-2 -ml-2">
                            <div class="w-8 h-8 rounded-lg bg-slate-900 border border-slate-700 flex items-center justify-center text-slate-400 shadow-sm">
                                <i class="fa-solid fa-phone"></i>
                            </div>
                            <span class="font-medium">${buyer.phone}</span>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        async function fetchState() {
            try {
                const res = await fetch('/api/config');
                const data = await res.json();
                document.getElementById('tg-token').value = data.tg_token || "";
                document.getElementById('tg-chat-id').value = data.tg_chat_id || "";
                renderProducts(data.products || []);
                
                const stateRes = await fetch('/api/state');
                const stateData = await stateRes.json();
                updateStatusUI(stateData.running, stateData.last_check);
            } catch (error) {
                console.error("Error fetching state:", error);
            }
        }

        async function fetchLogs() {
            try {
                const res = await fetch('/api/logs');
                const logs = await res.json();
                const container = document.getElementById('logs-container');
                container.innerHTML = logs.map(l => `<div class="py-1 border-b border-slate-800/50 text-slate-300">${l}</div>`).join('');
                container.scrollTop = container.scrollHeight;
            } catch (error) {
                console.error("Error fetching logs:", error);
            }
        }

        async function toggleEngine(action) {
            const res = await fetch('/api/state', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action})
            });
            const data = await res.json();
            updateStatusUI(data.running, data.last_check);
            fetchLogs();
        }

        function updateStatusUI(isRunning, lastCheck) {
            const btnStart = document.getElementById('btn-start');
            const btnStop = document.getElementById('btn-stop');
            const statusDot = document.getElementById('status-dot');
            const statusText = document.getElementById('status-text');
            const lastCheckText = document.getElementById('last-checked');

            lastCheckText.textContent = lastCheck;

            if (isRunning) {
                btnStart.classList.add('opacity-50', 'cursor-not-allowed');
                btnStart.disabled = true;
                btnStop.classList.remove('opacity-50', 'cursor-not-allowed');
                btnStop.disabled = false;
                
                statusDot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse';
                statusText.textContent = 'Engine Active';
                statusText.className = 'text-emerald-400 font-bold';
            } else {
                btnStart.classList.remove('opacity-50', 'cursor-not-allowed');
                btnStart.disabled = false;
                btnStop.classList.add('opacity-50', 'cursor-not-allowed');
                btnStop.disabled = true;
                
                statusDot.className = 'w-2.5 h-2.5 rounded-full bg-slate-500';
                statusText.textContent = 'Stopped';
                statusText.className = 'text-slate-400 font-semibold';
            }
        }

        async function saveConfig() {
            const token = document.getElementById('tg-token').value;
            const chatId = document.getElementById('tg-chat-id').value;
            
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({tg_token: token, tg_chat_id: chatId})
            });
            
            const btn = document.querySelector('button[onclick="saveConfig()"]');
            const originalText = btn.textContent;
            btn.textContent = "Saved Successfully!";
            btn.classList.add('bg-emerald-600');
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('bg-emerald-600');
            }, 2000);
        }

        async function addProduct(e) {
            e.preventDefault();
            const name = document.getElementById('prod-name').value;
            const hs = document.getElementById('prod-hs').value;
            const countries = document.getElementById('prod-countries').value;

            const res = await fetch('/api/products', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name, hs_code: hs, countries})
            });
            
            const data = await res.json();
            renderProducts(data.products);
            document.getElementById('add-product-form').reset();
        }

        async function removeProduct(index) {
            const res = await fetch(`/api/products?index=${index}`, { method: 'DELETE' });
            const data = await res.json();
            renderProducts(data.products);
        }

        async function clearLogs() {
            await fetch('/api/logs', { method: 'DELETE' });
            fetchLogs();
        }

        function renderProducts(products) {
            const tbody = document.getElementById('products-table-body');
            const emptyState = document.getElementById('empty-state');
            
            tbody.innerHTML = '';
            
            if (products.length === 0) {
                emptyState.classList.remove('hidden');
                return;
            }
            
            emptyState.classList.add('hidden');
            
            products.forEach((p, idx) => {
                const tr = document.createElement('tr');
                tr.className = "hover:bg-slate-800/50 transition-colors group";
                
                const cList = p.countries.length > 0 ? p.countries.join(", ") : "Global (All)";
                const hsDisplay = p.hs_code ? `<span class="bg-slate-800 px-2 py-1 rounded text-xs border border-slate-700 font-mono text-slate-300">${p.hs_code}</span>` : `<span class="text-slate-500 italic text-xs">None</span>`;
                
                tr.innerHTML = `
                    <td class="px-6 py-4 font-semibold text-white">${p.name}</td>
                    <td class="px-6 py-4">${hsDisplay}</td>
                    <td class="px-6 py-4">
                        <span class="text-xs font-medium px-2 py-1 bg-blue-900/20 text-blue-400 rounded-md border border-blue-800/30">
                            ${cList}
                        </span>
                    </td>
                    <td class="px-6 py-4 text-right">
                        <button onclick="removeProduct(${idx})" class="text-slate-500 hover:text-rose-400 transition-colors p-2 rounded hover:bg-slate-800">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        fetchState();
        fetchLogs();
        
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

@app.route("/api/state", methods=["GET", "POST"])
def api_state():
    if request.method == "POST":
        action = request.json.get("action")
        if action == "start":
            STATE["running"] = True
            add_log("Engine received START command.")
        elif action == "stop":
            STATE["running"] = False
            add_log("Engine received STOP command.")
    return jsonify(STATE)

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    config = load_data()
    if request.method == "POST":
        config["tg_token"] = request.json.get("tg_token", "").strip()
        config["tg_chat_id"] = request.json.get("tg_chat_id", "").strip()
        save_data(config)
        add_log("Telegram configuration saved securely.")
    return jsonify(config)

@app.route("/api/products", methods=["POST", "DELETE"])
def api_products():
    config = load_data()
    if request.method == "POST":
        name = request.json.get("name", "").strip()
        hs = request.json.get("hs_code", "").strip()
        countries_raw = request.json.get("countries", "")
        countries = [c.strip() for c in countries_raw.split(",")] if countries_raw.strip() else []
        
        if name:
            config.setdefault("products", []).append({
                "name": name,
                "hs_code": hs,
                "countries": countries
            })
            save_data(config)
            add_log(f"Added new target: {name}")

    elif request.method == "DELETE":
        idx = int(request.args.get("index", -1))
        if 0 <= idx < len(config.get("products", [])):
            removed = config["products"].pop(idx)
            save_data(config)
            add_log(f"Removed target: {removed['name']}")
            
    return jsonify(config)

@app.route("/api/logs", methods=["GET"])
def get_logs():
    return jsonify(LOGS)

@app.route("/api/logs", methods=["DELETE"])
def delete_logs():
    LOGS.clear()
    add_log("Logs cleared by user.")
    return jsonify({"status": "ok"})

@app.route("/api/directory", methods=["GET"])
def get_directory():
    config = load_data()
    target_products = [p["name"].upper() for p in config.get("products", [])]
    
    if not target_products:
        return jsonify([])
        
    matched_buyers = []
    
    for buyer in MOCK_BUYERS_DB:
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
    load_data() 
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
