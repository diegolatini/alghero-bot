"""
Bot prezzi Alghero v2 - Scraper robusti + Dashboard
"""

import os, json, time, random, re, sys
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

SOGLIE_OTTIME = {
    "volo":      200,   # A/R 2 persone €
    "traghetto": 220,   # A/R 2 persone €
    "alloggio":  80,    # per notte €
}

FILE_STORICO  = Path("data/storico.json")
FILE_DASHBOARD = Path("docs/index.html")

SESSIONE = requests.Session()

# ─── UTILS ─────────────────────────────────────────────────────────────────────

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def hdrs(referer=None):
    h = {
        "User-Agent": random.choice(UA_LIST),
        "Accept-Language": "it-IT,it;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    if referer:
        h["Referer"] = referer
    return h

def pausa(a=4, b=9):
    time.sleep(random.uniform(a, b))

def estrai_primo_numero(testo):
    """Estrae il primo numero intero ragionevole da una stringa."""
    nums = re.findall(r'\b(\d{2,4})\b', testo.replace('.','').replace(',',''))
    for n in nums:
        v = int(n)
        if 30 < v < 5000:
            return float(v)
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
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                      "text": msg, "parse_mode": "HTML",
                                      "disable_web_page_preview": True}, timeout=10)
        r.raise_for_status()
        print(f"  [TG] ✓ notifica inviata")
    except Exception as e:
        print(f"  [TG] ✗ errore: {e}")

# ─── PLAYWRIGHT BROWSER ────────────────────────────────────────────────────────

def browser_get(url, wait_selector=None, timeout=30000):
    """Apre una pagina con Playwright (browser reale) e restituisce l'HTML."""
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="it-IT",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "it-IT,it;q=0.9"}
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=10000)
                except:
                    pass
            time.sleep(random.uniform(3, 5))
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  [BROWSER] errore: {e}")
        return ""

# ─── SCRAPER VOLI ───────────────────────────────────────────────────────────────

def cerca_volo_ita(data_andata, data_ritorno):
    """Cerca voli FCO→AHO A/R per 2 persone con Playwright."""

    # Tentativo 1: Kayak con browser reale
    try:
        url = (
            f"https://www.kayak.it/flights/FCO-AHO"
            f"/{data_andata}/{data_ritorno}/2adults?sort=price_a"
        )
        html = browser_get(url, wait_selector="[class*='price']")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            prezzi = []
            # Kayak mostra prezzi in elementi con attributi specifici
            for el in soup.find_all(attrs={"class": re.compile(r'price|Price', re.I)}):
                testo = el.get_text(strip=True)
                v = estrai_primo_numero(testo.replace('.',''))
                if v and 80 < v < 5000:
                    prezzi.append(v)
            if prezzi:
                minimo = min(prezzi)
                print(f"  [VOLO KAYAK] trovato €{minimo:.0f} (2 pers A/R)")
                return float(minimo)
    except Exception as e:
        print(f"  [VOLO KAYAK] errore: {e}")

    # Tentativo 2: Skyscanner con browser reale
    try:
        pausa(3, 5)
        url2 = (
            f"https://www.skyscanner.it/trasporti/voli/fco/aho"
            f"/{data_andata.replace('-','')}/{data_ritorno.replace('-','')}/?adults=2"
        )
        html2 = browser_get(url2, wait_selector="[class*='Price']")
        if html2:
            soup2 = BeautifulSoup(html2, "html.parser")
            prezzi2 = []
            for el in soup2.find_all(class_=re.compile(r'BpkText|price|Price')):
                testo = el.get_text(strip=True).replace('.','').replace(',','')
                v = estrai_primo_numero(testo)
                if v and 80 < v < 5000:
                    prezzi2.append(v)
            if prezzi2:
                minimo2 = min(prezzi2)
                print(f"  [VOLO SKY] trovato €{minimo2:.0f} (2 pers A/R)")
                return float(minimo2)
    except Exception as e:
        print(f"  [VOLO SKY] errore: {e}")

    # Tentativo 3: Volagratis (sito italiano)
    try:
        pausa(2, 4)
        url3 = (
            f"https://www.volagratis.com/voli/a/FCO/AHO/"
            f"?departureDate={data_andata}&returnDate={data_ritorno}&adults=2"
        )
        r3 = SESSIONE.get(url3, headers=hdrs(), timeout=20)
        soup3 = BeautifulSoup(r3.text, "html.parser")
        prezzi3 = []
        for el in soup3.find_all(class_=re.compile(r'price|prezzo|costo', re.I)):
            v = estrai_primo_numero(el.get_text().replace('.',''))
            if v and 80 < v < 5000:
                prezzi3.append(v)
        if not prezzi3:
            matches = re.findall(r'€\s*(\d{2,4})', r3.text)
            prezzi3 = [int(m) for m in matches if 80 < int(m) < 5000]
        if prezzi3:
            minimo3 = min(prezzi3)
            print(f"  [VOLO VOLAGRATIS] trovato €{minimo3:.0f}")
            return float(minimo3)
    except Exception as e:
        print(f"  [VOLO VOLAGRATIS] errore: {e}")

    print(f"  [VOLO] nessun prezzo trovato")
    return None

# ─── SCRAPER TRAGHETTI ──────────────────────────────────────────────────────────

def cerca_traghetto(data_andata, data_ritorno):
    """Cerca traghetto Civitavecchia→Porto Torres con browser reale."""

    # Tentativo 1: Traghetti.com con Playwright
    try:
        da_fmt = datetime.strptime(data_andata, "%Y-%m-%d").strftime("%d-%m-%Y")
        ar_fmt = datetime.strptime(data_ritorno, "%Y-%m-%d").strftime("%d-%m-%Y")
        url = (
            f"https://www.traghetti.com/it/biglietti-traghetto"
            f"?departure=Civitavecchia&arrival=Porto+Torres"
            f"&outward_date={da_fmt}&return_date={ar_fmt}&adults=2"
        )
        html = browser_get(url, wait_selector="[class*='price']")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            prezzi = []
            for el in soup.find_all(class_=re.compile(r'price|prezzo|fare|tariff|amount', re.I)):
                v = estrai_primo_numero(el.get_text())
                if v and 15 < v < 600:
                    prezzi.append(v)
            if not prezzi:
                matches = re.findall(r'€\s*(\d{2,3})', html)
                prezzi = [int(m) for m in matches if 15 < int(m) < 600]
            if prezzi:
                minimo = min(prezzi)
                totale = round(minimo * 4, 0)  # 2 pers × A/R
                print(f"  [TRAGHETTO traghetti.com] €{minimo:.0f}/pp → €{totale:.0f} (2 pers A/R)")
                return float(totale)
    except Exception as e:
        print(f"  [TRAGHETTO traghetti.com] errore: {e}")

    # Tentativo 2: DirectFerries con browser
    try:
        pausa(2, 4)
        da_fmt2 = datetime.strptime(data_andata, "%Y-%m-%d").strftime("%d-%m-%Y")
        ar_fmt2 = datetime.strptime(data_ritorno, "%Y-%m-%d").strftime("%d-%m-%Y")
        url2 = (
            f"https://www.directferries.it/book_ferry.htm"
            f"?operator=0&depart=Civitavecchia&arrive=Porto+Torres"
            f"&depart_date={da_fmt2}&return_date={ar_fmt2}&adults=2&children=0&return=1"
        )
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

    # Tentativo 3: Grimaldi pagina tariffe con SSL disabilitato
    try:
        pausa(2, 4)
        r3 = SESSIONE.get("https://www.grimaldi-lines.com/it/tariffe/", headers=hdrs(), timeout=15, verify=False)
        matches3 = re.findall(r'€\s*(\d{2,3})', r3.text)
        valori3 = [int(m) for m in matches3 if 20 < int(m) < 300]
        if valori3:
            minimo3 = min(valori3)
            totale3 = minimo3 * 4
            print(f"  [TRAGHETTO grimaldi tariffe] €{minimo3:.0f}/pp → €{totale3:.0f} (2 pers A/R stima)")
            return float(totale3)
    except Exception as e:
        print(f"  [TRAGHETTO grimaldi] errore: {e}")

    print(f"  [TRAGHETTO] nessun prezzo trovato")
    return None

# ─── SCRAPER ALLOGGI ────────────────────────────────────────────────────────────

def cerca_alloggio(data_andata, data_ritorno):
    """Cerca appartamenti 2 camere ad Alghero con browser reale."""
    notti = (datetime.strptime(data_ritorno, "%Y-%m-%d") -
             datetime.strptime(data_andata, "%Y-%m-%d")).days

    # Tentativo 1: Airbnb con Playwright
    try:
        url = (
            f"https://www.airbnb.it/s/Alghero--Sardinia/homes"
            f"?checkin={data_andata}&checkout={data_ritorno}"
            f"&adults=2&min_bedrooms=2&room_types%5B%5D=Entire+home%2Fapt"
        )
        html = browser_get(url, wait_selector="[data-testid*='price']")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            prezzi = []
            # JSON embedded __NEXT_DATA__
            script = soup.find("script", id="__NEXT_DATA__")
            if script and script.string:
                matches = re.findall(r'"amount"\s*:\s*"?(\d+(?:\.\d+)?)"?', script.string)
                prezzi = [float(m) for m in matches if 30 < float(m) < 8000]
            if not prezzi:
                for el in soup.find_all(attrs={"data-testid": re.compile(r'price')}):
                    v = estrai_primo_numero(el.get_text())
                    if v and 30 < v < 3000:
                        prezzi.append(v)
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
        url2 = (
            f"https://www.booking.com/searchresults.it.html"
            f"?ss=Alghero&checkin={data_andata}&checkout={data_ritorno}"
            f"&group_adults=2&no_rooms=1&nflt=entire_place%3D1%3Bmin_bedrooms%3D2&order=price"
        )
        html2 = browser_get(url2, wait_selector="[data-testid='price-and-discounted-price']")
        if html2:
            soup2 = BeautifulSoup(html2, "html.parser")
            prezzi2 = []
            for el in soup2.find_all(attrs={"data-testid": "price-and-discounted-price"}):
                v = estrai_primo_numero(el.get_text().replace('.',''))
                if v and 50 < v < 10000:
                    prezzi2.append(v)
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

# ─── LOGICA NOTIFICHE ───────────────────────────────────────────────────────────

def controlla_notifiche(chiave, nuovo, vecchio, soglia, label, link):
    msgs = []
    ora = datetime.now().strftime("%d/%m %H:%M")

    if vecchio is not None and nuovo < vecchio:
        diff = vecchio - nuovo
        msgs.append(
            f"📉 <b>Prezzo sceso!</b>\n"
            f"{label}\n"
            f"<b>€{nuovo:.0f}</b> (era €{vecchio:.0f}, risparmi €{diff:.0f})\n"
            f"🔗 <a href='{link}'>Prenota subito</a>\n"
            f"<i>{ora}</i>"
        )
    if nuovo <= soglia:
        msgs.append(
            f"🎯 <b>Prezzo ottimo raggiunto!</b>\n"
            f"{label}\n"
            f"<b>€{nuovo:.0f}</b> ≤ soglia €{soglia:.0f}\n"
            f"🔗 <a href='{link}'>Prenota subito</a>\n"
            f"<i>{ora}</i>"
        )
    return msgs

# ─── DASHBOARD HTML ─────────────────────────────────────────────────────────────

def genera_dashboard(storico):
    ora = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Raggruppa dati per tipo e finestra
    voli = {}; traghetti = {}; alloggi = {}
    for chiave, valore in storico.items():
        if not isinstance(valore, list):
            continue
        parti = chiave.split("_")
        tipo = parti[0]
        date = f"{parti[1]}→{parti[2]}" if len(parti) >= 3 else chiave
        if tipo == "volo":      voli[date] = valore
        elif tipo == "traghetto": traghetti[date] = valore
        elif tipo == "alloggio":  alloggi[date] = valore

    def serie_js(dizionario):
        """Converte {label: [{"ts":..,"v":..},...]} in lista JS per Chart.js"""
        datasets = []
        colori = ["#4F8EF7","#F7874F","#4FF7A0","#F74F8E","#C44FF7"]
        for i, (label, serie) in enumerate(dizionario.items()):
            punti = [{"x": p["ts"], "y": p["v"]} for p in serie if p.get("v")]
            datasets.append({
                "label": label,
                "data": punti,
                "borderColor": colori[i % len(colori)],
                "backgroundColor": colori[i % len(colori)] + "33",
                "tension": 0.3,
                "fill": False,
            })
        return json.dumps(datasets)

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard Prezzi Alghero</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  :root {{
    --bg: #0f1117; --card: #1a1d27; --border: #2a2d3a;
    --text: #e2e8f0; --sub: #8892a4; --green: #4ade80;
    --blue: #60a5fa; --orange: #fb923c; --red: #f87171;
    --purple: #c084fc;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, sans-serif; padding: 1.5rem; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; }}
  .sub {{ color: var(--sub); font-size: 0.85rem; margin-bottom: 2rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; }}
  .card-label {{ font-size: 0.75rem; color: var(--sub); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }}
  .card-value {{ font-size: 1.8rem; font-weight: 600; }}
  .card-sub {{ font-size: 0.8rem; color: var(--sub); margin-top: 4px; }}
  .badge {{ display: inline-block; font-size: 0.7rem; padding: 2px 8px; border-radius: 20px; margin-left: 8px; vertical-align: middle; }}
  .badge-green {{ background: #166534; color: #4ade80; }}
  .badge-red {{ background: #7f1d1d; color: #f87171; }}
  .badge-yellow {{ background: #78350f; color: #fbbf24; }}
  .chart-wrap {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; }}
  .chart-title {{ font-size: 0.9rem; font-weight: 600; margin-bottom: 1rem; }}
  .chart-title span {{ color: var(--sub); font-weight: 400; font-size: 0.8rem; margin-left: 8px; }}
  canvas {{ max-height: 260px; }}
  .soglia-line {{ font-size: 0.8rem; color: var(--sub); margin-top: 8px; }}
  .empty {{ color: var(--sub); font-size: 0.85rem; padding: 2rem 0; text-align: center; }}
  .update {{ color: var(--sub); font-size: 0.75rem; text-align: right; margin-top: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ color: var(--sub); font-weight: 500; text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }}
  td {{ padding: 8px 8px; border-bottom: 1px solid var(--border); }}
  tr:last-child td {{ border-bottom: none; }}
  .up {{ color: var(--red); }} .down {{ color: var(--green); }} .eq {{ color: var(--sub); }}
</style>
</head>
<body>

<h1>📊 Dashboard Prezzi — Roma → Alghero</h1>
<div class="sub">Ultimo aggiornamento: {ora} · Aggiornamento automatico ogni ora</div>

<div class="grid" id="kpis"></div>

<div class="chart-wrap">
  <div class="chart-title">✈️ Voli ITA Airways FCO→AHO <span>A/R 2 persone · €</span></div>
  <canvas id="chartVoli"></canvas>
  <div class="soglia-line">— soglia ottima: €{SOGLIE_OTTIME['volo']}</div>
</div>

<div class="chart-wrap">
  <div class="chart-title">⛴️ Traghetto Grimaldi Civitavecchia→Porto Torres <span>A/R 2 persone · €</span></div>
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
  <table id="tabellaUltimi">
    <thead><tr><th>Categoria</th><th>Date</th><th>Prezzo</th><th>Var.</th></tr></thead>
    <tbody id="tbodyUltimi"></tbody>
  </table>
</div>

<div class="update">Dati raccolti automaticamente da GitHub Actions · aggiornamento ogni ora</div>

<script>
const storico = {json.dumps(storico, ensure_ascii=False)};
const SOGLIE = {json.dumps(SOGLIE_OTTIME)};

// ── Prepara dataset per tipo ──
function buildDatasets(tipo, campo) {{
  const colori = ["#4F8EF7","#fb923c","#4ade80","#c084fc","#f87171"];
  const ds = [];
  let i = 0;
  for (const [chiave, serie] of Object.entries(storico)) {{
    if (!chiave.startsWith(tipo)) continue;
    const label = chiave.replace(tipo+'_','').replace('_','→');
    const punti = (serie||[]).map(p => ({{
      x: new Date(p.ts),
      y: typeof p.v === 'object' ? p.v.per_notte : p.v
    }})).filter(p => p.y);
    if (!punti.length) {{ i++; continue; }}
    ds.push({{
      label, data: punti,
      borderColor: colori[i%colori.length],
      backgroundColor: colori[i%colori.length]+'22',
      tension: 0.3, fill: false, pointRadius: 4
    }});
    i++;
  }}
  return ds;
}}

function sogliAnnotation(valore) {{
  return {{
    type: 'line', yMin: valore, yMax: valore,
    borderColor: '#fbbf24', borderWidth: 1, borderDash: [4,4],
  }};
}}

const opzioniBase = (soglia) => ({{
  responsive: true,
  plugins: {{ legend: {{ labels: {{ color: '#8892a4', font: {{ size: 11 }} }} }} }},
  scales: {{
    x: {{
      type: 'time',
      time: {{ unit: 'hour', displayFormats: {{ hour: 'dd/MM HH:mm' }} }},
      ticks: {{ color: '#8892a4', maxTicksLimit: 8 }},
      grid: {{ color: '#2a2d3a' }}
    }},
    y: {{
      ticks: {{ color: '#8892a4', callback: v => '€'+v }},
      grid: {{ color: '#2a2d3a' }}
    }}
  }}
}});

// ── Grafici ──
['Voli','Traghetti','Alloggi'].forEach(tipo => {{
  const key = tipo === 'Voli' ? 'volo' : tipo === 'Traghetti' ? 'traghetto' : 'alloggio';
  const ds = buildDatasets(key);
  const ctx = document.getElementById('chart'+tipo).getContext('2d');
  if (!ds.length) {{
    ctx.canvas.parentElement.insertAdjacentHTML('beforeend',
      '<div class="empty">Dati in raccolta — torna tra qualche ora</div>');
    return;
  }}
  new Chart(ctx, {{ type: 'line', data: {{ datasets: ds }}, options: opzioniBase(SOGLIE[key]) }});
}});

// ── KPI Cards ──
function ultimoValore(tipo) {{
  let min = null;
  for (const [k,v] of Object.entries(storico)) {{
    if (!k.startsWith(tipo)||!v||!v.length) continue;
    const last = v[v.length-1];
    const val = typeof last.v === 'object' ? last.v.per_notte : last.v;
    if (val && (min === null || val < min)) min = val;
  }}
  return min;
}}

function trend(tipo) {{
  for (const [k,v] of Object.entries(storico)) {{
    if (!k.startsWith(tipo)||!v||v.length<2) continue;
    const a = typeof v[v.length-2].v==='object'?v[v.length-2].v.per_notte:v[v.length-2].v;
    const b = typeof v[v.length-1].v==='object'?v[v.length-1].v.per_notte:v[v.length-1].v;
    if (a&&b) return b<a?'↓':b>a?'↑':'→';
  }}
  return '–';
}}

const kpiData = [
  {{ label:'Volo minimo (A/R 2 pers)', tipo:'volo', soglia: SOGLIE.volo, unita:'€', extra:'' }},
  {{ label:'Traghetto minimo (A/R 2 pers)', tipo:'traghetto', soglia: SOGLIE.traghetto, unita:'€', extra:'' }},
  {{ label:'Alloggio minimo', tipo:'alloggio', soglia: SOGLIE.alloggio, unita:'€', extra:'/notte' }},
];

const kpiDiv = document.getElementById('kpis');
kpiData.forEach(k => {{
  const v = ultimoValore(k.tipo);
  const t = trend(k.tipo);
  const tClass = t==='↓'?'down':t==='↑'?'up':'eq';
  const badgeClass = v&&v<=k.soglia?'badge-green':'badge-yellow';
  const badgeTxt = v&&v<=k.soglia?'ottimo':'in monitoraggio';
  kpiDiv.innerHTML += `
    <div class="card">
      <div class="card-label">${{k.label}}</div>
      <div class="card-value">
        ${{v ? k.unita+Math.round(v)+k.extra : '–'}}
        <span class="badge ${{badgeClass}}">${{badgeTxt}}</span>
      </div>
      <div class="card-sub">
        Trend: <span class="${{tClass}}">${{t}}</span> &nbsp;·&nbsp; Soglia ottima: ${{k.unita}}${{k.soglia}}${{k.extra}}
      </div>
    </div>`;
}});

// ── Tabella ultimi valori ──
const tbody = document.getElementById('tbodyUltimi');
const emoji = {{volo:'✈️', traghetto:'⛴️', alloggio:'🏠'}};
for (const [chiave, serie] of Object.entries(storico)) {{
  if (!serie||!serie.length) continue;
  const tipo = chiave.split('_')[0];
  const date = chiave.replace(tipo+'_','').replace('_','→');
  const last = serie[serie.length-1];
  const prev = serie.length>1 ? serie[serie.length-2] : null;
  const val = typeof last.v==='object'?last.v.per_notte:last.v;
  const valPrev = prev ? (typeof prev.v==='object'?prev.v.per_notte:prev.v) : null;
  if (!val) continue;
  const diff = valPrev ? Math.round(val-valPrev) : 0;
  const diffTxt = diff===0?'–':diff<0?`<span class="down">▼ €${{Math.abs(diff)}}</span>`:`<span class="up">▲ €${{diff}}</span>`;
  tbody.innerHTML += `<tr>
    <td>${{emoji[tipo]||''}} ${{tipo}}</td>
    <td>${{date}}</td>
    <td><b>€${{Math.round(val)}}</b></td>
    <td>${{diffTxt}}</td>
  </tr>`;
}}
if (!tbody.innerHTML) tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);padding:2rem">Dati in raccolta — torna tra qualche ora</td></tr>';
</script>
</body>
</html>"""
    FILE_DASHBOARD.parent.mkdir(exist_ok=True)
    FILE_DASHBOARD.write_text(html)
    print(f"[DASHBOARD] generata → docs/index.html")

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"Bot Alghero v2 · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*50}")

    storico = carica_storico()
    ora_iso = datetime.now().isoformat()
    notifiche = []

    for (data_andata, data_ritorno) in DATE_FINESTRE:
        notti = (datetime.strptime(data_ritorno,"%Y-%m-%d") -
                 datetime.strptime(data_andata,"%Y-%m-%d")).days
        label_date = f"{data_andata}→{data_ritorno} ({notti}n)"
        print(f"\n▸ {label_date}")

        chiavi = {
            "volo":      f"volo_{data_andata}_{data_ritorno}",
            "traghetto": f"traghetto_{data_andata}_{data_ritorno}",
            "alloggio":  f"alloggio_{data_andata}_{data_ritorno}",
        }

        # ── Volo ──
        pv = cerca_volo_ita(data_andata, data_ritorno)
        pausa()
        if pv:
            serie = storico.setdefault(chiavi["volo"], [])
            vecchio = serie[-1]["v"] if serie else None
            serie.append({"ts": ora_iso, "v": pv})
            notifiche += controlla_notifiche(
                chiavi["volo"], pv, vecchio, SOGLIE_OTTIME["volo"],
                f"✈️ Volo A/R 2 pers · {label_date}",
                "https://www.ita-airways.com/it_it/voli-offerte/offerte-voli.html"
            )

        # ── Traghetto ──
        pt = cerca_traghetto(data_andata, data_ritorno)
        pausa()
        if pt:
            serie = storico.setdefault(chiavi["traghetto"], [])
            vecchio = serie[-1]["v"] if serie else None
            serie.append({"ts": ora_iso, "v": pt})
            notifiche += controlla_notifiche(
                chiavi["traghetto"], pt, vecchio, SOGLIE_OTTIME["traghetto"],
                f"⛴️ Traghetto A/R 2 pers · {label_date}",
                "https://www.grimaldi-lines.com/it/prenota/"
            )

        # ── Alloggio ──
        pa = cerca_alloggio(data_andata, data_ritorno)
        pausa()
        if pa:
            serie = storico.setdefault(chiavi["alloggio"], [])
            vecchio = serie[-1]["v"]["per_notte"] if serie and isinstance(serie[-1]["v"], dict) else (serie[-1]["v"] if serie else None)
            serie.append({"ts": ora_iso, "v": pa})
            notifiche += controlla_notifiche(
                chiavi["alloggio"], pa["per_notte"], vecchio, SOGLIE_OTTIME["alloggio"],
                f"🏠 Alloggio €/notte · {label_date}",
                f"https://www.airbnb.it/s/Alghero/homes?checkin={data_andata}&checkout={data_ritorno}&adults=2&min_bedrooms=2"
            )

    # ── Notifiche Telegram ──
    if notifiche:
        print(f"\n[TG] Invio {len(notifiche)} notifiche...")
        for msg in notifiche:
            telegram(msg)
            time.sleep(1)
    else:
        print("\n[INFO] Nessuna variazione significativa.")

    # ── Riepilogo giornaliero alle 9:00 ──
    if datetime.now().hour == 9:
        righe = [f"📊 <b>Riepilogo mattutino</b> · {datetime.now().strftime('%d/%m %H:%M')}\n"]
        for tipo, emoji in [("volo","✈️"),("traghetto","⛴️"),("alloggio","🏠")]:
            for chiave, serie in storico.items():
                if not chiave.startswith(tipo) or not serie: continue
                last = serie[-1]["v"]
                val = last["per_notte"] if isinstance(last, dict) else last
                if val:
                    date = chiave.replace(f"{tipo}_","").replace("_","→")
                    righe.append(f"{emoji} {date}: <b>€{val:.0f}</b>")
        telegram("\n".join(righe))

    # ── Salva storico e genera dashboard ──
    salva_storico(storico)
    genera_dashboard(storico)
    print(f"\n✓ Done · {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
