"""
Bot prezzi Alghero v3 - ITA Airways only + tratta Napoli + dashboard
"""

import os, json, time, random, re
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ─── CONFIG ────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DATE_FINESTRE = [
    ("2026-08-27", "2026-08-30"),
    ("2026-08-28", "2026-09-01"),
    ("2026-08-31", "2026-09-03"),
    ("2026-08-31", "2026-09-04"),
    ("2026-09-01", "2026-09-04"),
]

# Tratte aeree da monitorare (solo ITA Airways)
TRATTE_VOLO = [
    ("FCO", "AHO", "Roma FCO"),    # Fiumicino → Alghero
    ("NAP", "AHO", "Napoli NAP"),  # Napoli → Alghero
]

SOGLIE_OTTIME = {
    "volo":      200,   # A/R 2 persone €
    "traghetto": 220,   # A/R 2 persone €
    "alloggio":  80,    # per notte €
}

FILE_STORICO   = Path("data/storico.json")
FILE_DASHBOARD = Path("docs/index.html")
SESSIONE = requests.Session()

# ─── UTILS ─────────────────────────────────────────────────────────────────────

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def hdrs(referer=None):
    h = {"User-Agent": random.choice(UA_LIST), "Accept-Language": "it-IT,it;q=0.9",
         "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    if referer: h["Referer"] = referer
    return h

def pausa(a=4, b=9): time.sleep(random.uniform(a, b))

def estrai_primo_numero(testo):
    nums = re.findall(r'\b(\d{2,4})\b', str(testo).replace('.','').replace(',',''))
    for n in nums:
        v = int(n)
        if 30 < v < 5000: return float(v)
    return None

def carica_storico():
    if FILE_STORICO.exists():
        return json.loads(FILE_STORICO.read_text())
    return {}

def salva_storico(st):
    FILE_STORICO.parent.mkdir(exist_ok=True)
    FILE_STORICO.write_text(json.dumps(st, indent=2, ensure_ascii=False))

def telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                                      "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
        r.raise_for_status()
        print(f"  [TG] ✓ notifica inviata")
    except Exception as e:
        print(f"  [TG] ✗ errore: {e}")

# ─── PLAYWRIGHT ─────────────────────────────────────────────────────────────────

def browser_get(url, wait_selector=None, timeout=35000):
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="it-IT", viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "it-IT,it;q=0.9"}
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if wait_selector:
                try: page.wait_for_selector(wait_selector, timeout=10000)
                except: pass
            time.sleep(random.uniform(3, 5))
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  [BROWSER] errore: {e}")
        return ""

# ─── SCRAPER VOLI — solo ITA Airways ──────────────────────────────────────────

def cerca_volo_ita(iata_da, iata_a, data_andata, data_ritorno):
    """Cerca voli ITA Airways A/R per 2 persone. Ignora altre compagnie."""

    # Tentativo 1: Kayak filtrato ITA Airways
    try:
        url = (f"https://www.kayak.it/flights/{iata_da}-{iata_a}"
               f"/{data_andata}/{data_ritorno}/2adults?airlines=ITA&sort=price_a")
        html = browser_get(url, wait_selector="[class*='price']")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            testo_pagina = soup.get_text()
            # Verifica presenza ITA nella pagina
            if not any(k in testo_pagina for k in ["ITA", "Ita Airways", "ita airways"]):
                print(f"  [VOLO KAYAK] ITA Airways non presente nei risultati")
            else:
                prezzi = []
                for el in soup.find_all(attrs={"class": re.compile(r'price|Price', re.I)}):
                    v = estrai_primo_numero(el.get_text())
                    if v and 80 < v < 5000: prezzi.append(v)
                if prezzi:
                    minimo = min(prezzi)
                    print(f"  [VOLO KAYAK/ITA] trovato €{minimo:.0f} (2 pers A/R)")
                    return float(minimo)
    except Exception as e:
        print(f"  [VOLO KAYAK] errore: {e}")

    # Tentativo 2: ITA Airways sito ufficiale
    try:
        pausa(3, 5)
        url2 = (f"https://www.ita-airways.com/it_it/voli.html"
                f"?from={iata_da}&to={iata_a}"
                f"&departureDate={data_andata}&returnDate={data_ritorno}&adults=2&cabin=ECONOMY")
        html2 = browser_get(url2, wait_selector="[class*='price'],[class*='fare']", timeout=40000)
        if html2:
            soup2 = BeautifulSoup(html2, "html.parser")
            prezzi2 = []
            for el in soup2.find_all(class_=re.compile(r'price|fare|amount|total', re.I)):
                v = estrai_primo_numero(el.get_text())
                if v and 40 < v < 3000: prezzi2.append(v)
            # JSON embedded
            for script in soup2.find_all("script"):
                txt = script.string or ""
                if "price" in txt.lower() and len(txt) > 200:
                    matches = re.findall(r'"(?:price|amount|total)"\s*:\s*(\d+\.?\d*)', txt)
                    prezzi2 += [float(m) for m in matches if 40 < float(m) < 3000]
            if prezzi2:
                minimo2 = min(prezzi2)
                totale = minimo2 if minimo2 > 100 else minimo2 * 2
                print(f"  [VOLO ITA sito] trovato €{totale:.0f} (2 pers A/R)")
                return float(totale)
    except Exception as e:
        print(f"  [VOLO ITA sito] errore: {e}")

    # Tentativo 3: Volagratis filtro ITA
    try:
        pausa(2, 4)
        url3 = (f"https://www.volagratis.com/voli/a/{iata_da}/{iata_a}/"
                f"?departureDate={data_andata}&returnDate={data_ritorno}&adults=2&airlines=ITA")
        r3 = SESSIONE.get(url3, headers=hdrs(), timeout=20)
        if any(k in r3.text for k in ["ITA", "ita airways"]):
            matches3 = re.findall(r'€\s*(\d{2,4})', r3.text)
            valori3 = [int(m) for m in matches3 if 80 < int(m) < 5000]
            if valori3:
                minimo3 = min(valori3)
                print(f"  [VOLO VOLAGRATIS/ITA] trovato €{minimo3:.0f}")
                return float(minimo3)
    except Exception as e:
        print(f"  [VOLO VOLAGRATIS] errore: {e}")

    print(f"  [VOLO {iata_da}→{iata_a}] ITA Airways non trovata")
    return None

# ─── SCRAPER TRAGHETTI ──────────────────────────────────────────────────────────

def cerca_traghetto(data_andata, data_ritorno):
    # Tentativo 1: Traghetti.com con Playwright
    try:
        da_fmt = datetime.strptime(data_andata, "%Y-%m-%d").strftime("%d-%m-%Y")
        ar_fmt = datetime.strptime(data_ritorno, "%Y-%m-%d").strftime("%d-%m-%Y")
        url = (f"https://www.traghetti.com/it/biglietti-traghetto"
               f"?departure=Civitavecchia&arrival=Porto+Torres"
               f"&outward_date={da_fmt}&return_date={ar_fmt}&adults=2")
        html = browser_get(url, wait_selector="[class*='price']")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            prezzi = []
            for el in soup.find_all(class_=re.compile(r'price|prezzo|fare|tariff|amount', re.I)):
                v = estrai_primo_numero(el.get_text())
                if v and 15 < v < 600: prezzi.append(v)
            if not prezzi:
                matches = re.findall(r'€\s*(\d{2,3})', html)
                prezzi = [int(m) for m in matches if 15 < int(m) < 600]
            if prezzi:
                minimo = min(prezzi)
                totale = round(minimo * 4, 0)
                print(f"  [TRAGHETTO traghetti.com] €{minimo:.0f}/pp → €{totale:.0f} (2 pers A/R)")
                return float(totale)
    except Exception as e:
        print(f"  [TRAGHETTO traghetti.com] errore: {e}")

    # Tentativo 2: DirectFerries
    try:
        pausa(2, 4)
        da_fmt2 = datetime.strptime(data_andata, "%Y-%m-%d").strftime("%d-%m-%Y")
        ar_fmt2 = datetime.strptime(data_ritorno, "%Y-%m-%d").strftime("%d-%m-%Y")
        url2 = (f"https://www.directferries.it/book_ferry.htm"
                f"?operator=0&depart=Civitavecchia&arrive=Porto+Torres"
                f"&depart_date={da_fmt2}&return_date={ar_fmt2}&adults=2&children=0&return=1")
        html2 = browser_get(url2, wait_selector="[class*='price']")
        if html2:
            matches2 = re.findall(r'€\s*(\d{2,3}(?:[.,]\d{2})?)', html2)
            valori2 = [float(m.replace(',','.')) for m in matches2 if 15 < float(m.replace(',','.')) < 600]
            if valori2:
                minimo2 = min(valori2)
                totale2 = round(minimo2 * 2, 0)
                print(f"  [TRAGHETTO directferries] €{minimo2:.0f} → €{totale2:.0f} (2 pers A/R)")
                return float(totale2)
    except Exception as e:
        print(f"  [TRAGHETTO directferries] errore: {e}")

    # Tentativo 3: Grimaldi tariffe (SSL disabilitato)
    try:
        pausa(2, 4)
        r3 = SESSIONE.get("https://www.grimaldi-lines.com/it/tariffe/", headers=hdrs(), timeout=15, verify=False)
        matches3 = re.findall(r'€\s*(\d{2,3})', r3.text)
        valori3 = [int(m) for m in matches3 if 20 < int(m) < 300]
        if valori3:
            minimo3 = min(valori3)
            totale3 = minimo3 * 4
            print(f"  [TRAGHETTO grimaldi] €{minimo3:.0f}/pp → €{totale3:.0f} (2 pers A/R stima)")
            return float(totale3)
    except Exception as e:
        print(f"  [TRAGHETTO grimaldi] errore: {e}")

    print(f"  [TRAGHETTO] nessun prezzo trovato")
    return None

# ─── SCRAPER ALLOGGI ────────────────────────────────────────────────────────────

def cerca_alloggio(data_andata, data_ritorno):
    notti = (datetime.strptime(data_ritorno, "%Y-%m-%d") -
             datetime.strptime(data_andata, "%Y-%m-%d")).days

    # Tentativo 1: Airbnb con Playwright
    try:
        url = (f"https://www.airbnb.it/s/Alghero--Sardinia/homes"
               f"?checkin={data_andata}&checkout={data_ritorno}"
               f"&adults=2&min_bedrooms=2&room_types%5B%5D=Entire+home%2Fapt")
        html = browser_get(url, wait_selector="[data-testid*='price']")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            prezzi = []
            script = soup.find("script", id="__NEXT_DATA__")
            if script and script.string:
                matches = re.findall(r'"amount"\s*:\s*"?(\d+(?:\.\d+)?)"?', script.string)
                prezzi = [float(m) for m in matches if 30 < float(m) < 8000]
            if not prezzi:
                for el in soup.find_all(attrs={"data-testid": re.compile(r'price')}):
                    v = estrai_primo_numero(el.get_text())
                    if v and 30 < v < 3000: prezzi.append(v)
            if not prezzi:
                matches2 = re.findall(r'€(\d{2,4})', html)
                prezzi = [int(m) for m in matches2 if 30 < int(m) < 3000]
            if prezzi:
                minimo = min(prezzi)
                per_notte = minimo if minimo < 600 else round(minimo / notti, 0)
                totale = per_notte * notti
                print(f"  [AIRBNB] €{per_notte:.0f}/notte → €{totale:.0f} totale")
                return {"per_notte": per_notte, "totale": totale, "notti": notti}
    except Exception as e:
        print(f"  [AIRBNB] errore: {e}")

    # Tentativo 2: Booking con Playwright
    try:
        pausa(3, 5)
        url2 = (f"https://www.booking.com/searchresults.it.html"
                f"?ss=Alghero&checkin={data_andata}&checkout={data_ritorno}"
                f"&group_adults=2&no_rooms=1&nflt=entire_place%3D1%3Bmin_bedrooms%3D2&order=price")
        html2 = browser_get(url2, wait_selector="[data-testid='price-and-discounted-price']")
        if html2:
            soup2 = BeautifulSoup(html2, "html.parser")
            prezzi2 = []
            for el in soup2.find_all(attrs={"data-testid": "price-and-discounted-price"}):
                v = estrai_primo_numero(el.get_text().replace('.',''))
                if v and 50 < v < 10000: prezzi2.append(v)
            if not prezzi2:
                matches2 = re.findall(r'€\s*(\d{2,4})', html2)
                prezzi2 = [int(m) for m in matches2 if 50 < int(m) < 10000]
            if prezzi2:
                minimo2 = min(prezzi2)
                per_notte2 = minimo2 if minimo2 < 600 else round(minimo2 / notti, 0)
                totale2 = per_notte2 * notti
                print(f"  [BOOKING] €{per_notte2:.0f}/notte → €{totale2:.0f} totale")
                return {"per_notte": per_notte2, "totale": totale2, "notti": notti}
    except Exception as e:
        print(f"  [BOOKING] errore: {e}")

    print(f"  [ALLOGGIO] nessun prezzo trovato")
    return None

# ─── NOTIFICHE ──────────────────────────────────────────────────────────────────

def controlla_notifiche(chiave, nuovo, vecchio, soglia, label, link):
    msgs = []
    ora = datetime.now().strftime("%d/%m %H:%M")
    if vecchio is not None and nuovo < vecchio:
        diff = vecchio - nuovo
        msgs.append(f"📉 <b>Prezzo sceso!</b>\n{label}\n<b>€{nuovo:.0f}</b> (era €{vecchio:.0f}, risparmi €{diff:.0f})\n🔗 <a href='{link}'>Prenota subito</a>\n<i>{ora}</i>")
    if nuovo <= soglia:
        msgs.append(f"🎯 <b>Prezzo ottimo!</b>\n{label}\n<b>€{nuovo:.0f}</b> ≤ soglia €{soglia:.0f}\n🔗 <a href='{link}'>Prenota subito</a>\n<i>{ora}</i>")
    return msgs

# ─── DASHBOARD ──────────────────────────────────────────────────────────────────

def genera_dashboard(storico):
    ora = datetime.now().strftime("%d/%m/%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard Prezzi Alghero</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  :root {{ --bg:#0f1117; --card:#1a1d27; --border:#2a2d3a; --text:#e2e8f0; --sub:#8892a4; --green:#4ade80; --blue:#60a5fa; --orange:#fb923c; --red:#f87171; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--text); font-family:-apple-system,sans-serif; padding:1.5rem; }}
  h1 {{ font-size:1.4rem; font-weight:600; margin-bottom:4px; }}
  .sub {{ color:var(--sub); font-size:.85rem; margin-bottom:2rem; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; margin-bottom:2rem; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:1.25rem; }}
  .card-label {{ font-size:.75rem; color:var(--sub); text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }}
  .card-value {{ font-size:1.8rem; font-weight:600; }}
  .card-sub {{ font-size:.8rem; color:var(--sub); margin-top:4px; }}
  .badge {{ display:inline-block; font-size:.7rem; padding:2px 8px; border-radius:20px; margin-left:8px; vertical-align:middle; }}
  .badge-green {{ background:#166534; color:#4ade80; }}
  .badge-yellow {{ background:#78350f; color:#fbbf24; }}
  .chart-wrap {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:1.25rem; margin-bottom:1.5rem; }}
  .chart-title {{ font-size:.9rem; font-weight:600; margin-bottom:1rem; }}
  .chart-title span {{ color:var(--sub); font-weight:400; font-size:.8rem; margin-left:8px; }}
  canvas {{ max-height:260px; }}
  .soglia-line {{ font-size:.8rem; color:var(--sub); margin-top:8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
  th {{ color:var(--sub); font-weight:500; text-align:left; padding:6px 8px; border-bottom:1px solid var(--border); }}
  td {{ padding:8px 8px; border-bottom:1px solid var(--border); }}
  tr:last-child td {{ border-bottom:none; }}
  .down {{ color:var(--green); }} .up {{ color:var(--red); }}
  .update {{ color:var(--sub); font-size:.75rem; text-align:right; margin-top:1rem; }}
</style>
</head>
<body>
<h1>📊 Dashboard Prezzi — Alghero 2026</h1>
<div class="sub">Aggiornamento: {ora} · ogni ora automatico · solo ITA Airways (bagaglio incluso)</div>

<div class="grid" id="kpis"></div>

<div class="chart-wrap">
  <div class="chart-title">✈️ Voli ITA Airways → Alghero <span>A/R 2 persone · € · bagaglio incluso</span></div>
  <canvas id="chartVoli"></canvas>
  <div class="soglia-line">— soglia ottima: €{SOGLIE_OTTIME['volo']}</div>
</div>
<div class="chart-wrap">
  <div class="chart-title">⛴️ Traghetto Civitavecchia→Porto Torres <span>A/R 2 persone · €</span></div>
  <canvas id="chartTraghetti"></canvas>
  <div class="soglia-line">— soglia ottima: €{SOGLIE_OTTIME['traghetto']}</div>
</div>
<div class="chart-wrap">
  <div class="chart-title">🏠 Appartamenti Alghero (2 camere) <span>€/notte</span></div>
  <canvas id="chartAlloggi"></canvas>
  <div class="soglia-line">— soglia ottima: €{SOGLIE_OTTIME['alloggio']}/notte</div>
</div>
<div class="chart-wrap">
  <div class="chart-title">📋 Ultimi prezzi rilevati</div>
  <table>
    <thead><tr><th>Categoria</th><th>Tratta / Date</th><th>Prezzo</th><th>Var.</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<div class="update">Dati raccolti automaticamente · GitHub Actions · aggiornamento ogni ora</div>

<script>
const storico = {json.dumps(storico, ensure_ascii=False)};
const SOGLIE = {json.dumps(SOGLIE_OTTIME)};
const colori = ["#4F8EF7","#fb923c","#4ade80","#c084fc","#f87171","#fbbf24"];

function buildDs(prefisso) {{
  const ds = []; let i = 0;
  for (const [k,v] of Object.entries(storico)) {{
    if (!k.startsWith(prefisso)||!v||!v.length) {{ continue; }}
    const label = k.replace(prefisso+'_','').replace(/_/g,'→');
    const punti = v.map(p=>({{x:new Date(p.ts),y:typeof p.v==='object'?p.v.per_notte:p.v}})).filter(p=>p.y);
    if (!punti.length) {{ i++; continue; }}
    ds.push({{label,data:punti,borderColor:colori[i%colori.length],backgroundColor:colori[i%colori.length]+'22',tension:.3,fill:false,pointRadius:4}});
    i++;
  }}
  return ds;
}}

const opts = {{responsive:true,plugins:{{legend:{{labels:{{color:'#8892a4',font:{{size:11}}}}}}}},scales:{{x:{{type:'time',time:{{unit:'hour',displayFormats:{{hour:'dd/MM HH:mm'}}}},ticks:{{color:'#8892a4',maxTicksLimit:8}},grid:{{color:'#2a2d3a'}}}},y:{{ticks:{{color:'#8892a4',callback:v=>'€'+v}},grid:{{color:'#2a2d3a'}}}}}}}};

[['Voli','volo'],['Traghetti','traghetto'],['Alloggi','alloggio']].forEach(([nome,key])=>{{
  const ds = buildDs(key);
  const ctx = document.getElementById('chart'+nome).getContext('2d');
  if (ds.length) new Chart(ctx,{{type:'line',data:{{datasets:ds}},options:opts}});
  else ctx.canvas.parentElement.insertAdjacentHTML('beforeend','<p style="color:#8892a4;padding:1rem">Dati in raccolta...</p>');
}});

// KPI
function ultimoMin(pref) {{
  let min=null;
  for (const [k,v] of Object.entries(storico)) {{
    if(!k.startsWith(pref)||!v||!v.length) continue;
    const last=v[v.length-1]; const val=typeof last.v==='object'?last.v.per_notte:last.v;
    if(val&&(min===null||val<min)) min=val;
  }}
  return min;
}}
function trend(pref) {{
  for (const [k,v] of Object.entries(storico)) {{
    if(!k.startsWith(pref)||!v||v.length<2) continue;
    const a=typeof v[v.length-2].v==='object'?v[v.length-2].v.per_notte:v[v.length-2].v;
    const b=typeof v[v.length-1].v==='object'?v[v.length-1].v.per_notte:v[v.length-1].v;
    if(a&&b) return b<a?'↓':b>a?'↑':'→';
  }}
  return '–';
}}
const kpis=[
  {{label:'Volo ITA minimo (A/R 2 pers)',pref:'volo',soglia:SOGLIE.volo,extra:''}},
  {{label:'Traghetto minimo (A/R 2 pers)',pref:'traghetto',soglia:SOGLIE.traghetto,extra:''}},
  {{label:'Alloggio minimo',pref:'alloggio',soglia:SOGLIE.alloggio,extra:'/notte'}},
];
const kDiv=document.getElementById('kpis');
kpis.forEach(k=>{{
  const v=ultimoMin(k.pref); const t=trend(k.pref);
  const tc=t==='↓'?'down':t==='↑'?'up':'';
  const bc=v&&v<=k.soglia?'badge-green':'badge-yellow';
  const bt=v&&v<=k.soglia?'ottimo':'in monitoraggio';
  kDiv.innerHTML+=`<div class="card"><div class="card-label">${{k.label}}</div><div class="card-value">${{v?'€'+Math.round(v)+k.extra:'–'}}<span class="badge ${{bc}}">${{bt}}</span></div><div class="card-sub">Trend: <span class="${{tc}}">${{t}}</span> · Soglia: €${{k.soglia}}${{k.extra}}</div></div>`;
}});

// Tabella
const tbody=document.getElementById('tbody');
const emj={{volo:'✈️',traghetto:'⛴️',alloggio:'🏠'}};
for(const[k,v] of Object.entries(storico)){{
  if(!v||!v.length) continue;
  const tipo=k.split('_')[0];
  const label=k.replace(tipo+'_','').replace(/_/g,' ');
  const last=v[v.length-1]; const prev=v.length>1?v[v.length-2]:null;
  const val=typeof last.v==='object'?last.v.per_notte:last.v;
  const vp=prev?(typeof prev.v==='object'?prev.v.per_notte:prev.v):null;
  if(!val) continue;
  const diff=vp?Math.round(val-vp):0;
  const dt=diff===0?'–':diff<0?`<span class="down">▼ €${{Math.abs(diff)}}</span>`:`<span class="up">▲ €${{diff}}</span>`;
  tbody.innerHTML+=`<tr><td>${{emj[tipo]||''}} ${{tipo}}</td><td>${{label}}</td><td><b>€${{Math.round(val)}}</b></td><td>${{dt}}</td></tr>`;
}}
if(!tbody.innerHTML) tbody.innerHTML='<tr><td colspan="4" style="text-align:center;color:var(--sub);padding:2rem">Dati in raccolta — torna tra qualche ora</td></tr>';
</script>
</body>
</html>"""
    FILE_DASHBOARD.parent.mkdir(exist_ok=True)
    FILE_DASHBOARD.write_text(html)
    print(f"[DASHBOARD] generata → docs/index.html")

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"Bot Alghero v3 · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*50}")

    storico = carica_storico()
    ora_iso = datetime.now().isoformat()
    notifiche = []

    for (data_andata, data_ritorno) in DATE_FINESTRE:
        notti = (datetime.strptime(data_ritorno,"%Y-%m-%d") - datetime.strptime(data_andata,"%Y-%m-%d")).days
        label_date = f"{data_andata}→{data_ritorno} ({notti}n)"
        print(f"\n▸ {label_date}")

        # ── Voli ITA su tutte le tratte ──
        for (iata_da, iata_a, nome_citta) in TRATTE_VOLO:
            chiave_volo = f"volo_{iata_da}_{data_andata}_{data_ritorno}"
            print(f"  ✈️  {nome_citta} → Alghero (ITA Airways)")
            pv = cerca_volo_ita(iata_da, iata_a, data_andata, data_ritorno)
            pausa()
            if pv:
                serie = storico.setdefault(chiave_volo, [])
                vecchio = serie[-1]["v"] if serie else None
                serie.append({"ts": ora_iso, "v": pv})
                notifiche += controlla_notifiche(
                    chiave_volo, pv, vecchio, SOGLIE_OTTIME["volo"],
                    f"✈️ ITA Airways {nome_citta}→Alghero A/R 2 pers · {label_date}\n💼 Bagaglio a mano + zaino inclusi",
                    f"https://www.ita-airways.com/it_it/voli.html?from={iata_da}&to={iata_a}&departureDate={data_andata}&returnDate={data_ritorno}&adults=2&cabin=ECONOMY"
                )

        # ── Traghetto ──
        chiave_traghetto = f"traghetto_{data_andata}_{data_ritorno}"
        print(f"  ⛴️  Civitavecchia → Porto Torres (Grimaldi)")
        pt = cerca_traghetto(data_andata, data_ritorno)
        pausa()
        if pt:
            serie = storico.setdefault(chiave_traghetto, [])
            vecchio = serie[-1]["v"] if serie else None
            serie.append({"ts": ora_iso, "v": pt})
            notifiche += controlla_notifiche(
                chiave_traghetto, pt, vecchio, SOGLIE_OTTIME["traghetto"],
                f"⛴️ Traghetto Civitavecchia→Porto Torres A/R 2 pers · {label_date}\n🧳 Nessun limite bagaglio",
                f"https://www.traghetti.com/it/biglietti-traghetto?departure=Civitavecchia&arrival=Porto+Torres&outward_date={data_andata}&return_date={data_ritorno}&adults=2"
            )

        # ── Alloggio ──
        chiave_alloggio = f"alloggio_{data_andata}_{data_ritorno}"
        print(f"  🏠  Appartamenti Alghero (2 camere)")
        pa = cerca_alloggio(data_andata, data_ritorno)
        pausa()
        if pa:
            serie = storico.setdefault(chiave_alloggio, [])
            vecchio = serie[-1]["v"]["per_notte"] if serie and isinstance(serie[-1]["v"], dict) else (serie[-1]["v"] if serie else None)
            serie.append({"ts": ora_iso, "v": pa})
            notifiche += controlla_notifiche(
                chiave_alloggio, pa["per_notte"], vecchio, SOGLIE_OTTIME["alloggio"],
                f"🏠 Appartamento Alghero (2 camere) · {label_date}",
                f"https://www.airbnb.it/s/Alghero/homes?checkin={data_andata}&checkout={data_ritorno}&adults=2&min_bedrooms=2"
            )

    # ── Notifiche ──
    if notifiche:
        print(f"\n[TG] Invio {len(notifiche)} notifiche...")
        for msg in notifiche:
            telegram(msg)
            time.sleep(1)
    else:
        print("\n[INFO] Nessuna variazione significativa.")

    # ── Riepilogo mattutino alle 9 ──
    if datetime.now().hour == 9:
        righe = [f"📊 <b>Riepilogo mattutino</b> · {datetime.now().strftime('%d/%m %H:%M')}\n"]
        for tipo, emoji in [("volo","✈️"),("traghetto","⛴️"),("alloggio","🏠")]:
            for chiave, serie in storico.items():
                if not chiave.startswith(tipo) or not serie: continue
                last = serie[-1]["v"]
                val = last["per_notte"] if isinstance(last, dict) else last
                if val:
                    label = chiave.replace(f"{tipo}_","").replace("_","→")
                    righe.append(f"{emoji} {label}: <b>€{val:.0f}</b>")
        telegram("\n".join(righe))

    salva_storico(storico)
    genera_dashboard(storico)
    print(f"\n✓ Done · {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
