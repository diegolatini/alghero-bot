"""
Bot prezzi Alghero - Voli, Traghetti, Alloggi
Monitora i prezzi e invia notifiche Telegram quando scendono.
"""

import os
import json
import time
import random
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Soglie "prezzo ottimo" — ricevi notifica anche se non è un nuovo minimo
SOGLIE_OTTIME = {
    "volo_ita_ar_2persone": 200,      # ITA Airways A/R per 2 persone (€)
    "traghetto_ar_2persone": 250,     # Grimaldi A/R piedi per 2 persone (€)
    "alloggio_notte": 80,             # Per notte totale appartamento (€)
}

# Date flessibili da monitorare (formato YYYY-MM-DD)
DATE_FINESTRE = [
    ("2026-08-27", "2026-08-30"),  # 3 notti
    ("2026-08-28", "2026-09-01"),  # 4 notti
    ("2026-08-31", "2026-09-03"),  # 3 notti
    ("2026-08-31", "2026-09-04"),  # 4 notti
    ("2026-09-01", "2026-09-04"),  # 3 notti
]

FILE_PREZZI = "data/prezzi.json"

# ─── UTILS ─────────────────────────────────────────────────────────────────────

def carica_prezzi_precedenti():
    if os.path.exists(FILE_PREZZI):
        with open(FILE_PREZZI, "r") as f:
            return json.load(f)
    return {}

def salva_prezzi(prezzi):
    os.makedirs("data", exist_ok=True)
    with open(FILE_PREZZI, "w") as f:
        json.dump(prezzi, f, indent=2, ensure_ascii=False)

def invia_telegram(messaggio):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": messaggio,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[OK] Messaggio Telegram inviato")
    except Exception as e:
        print(f"[ERRORE] Telegram: {e}")

def headers_casuali():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

def pausa():
    time.sleep(random.uniform(3, 7))

# ─── SCRAPER VOLI (Kayak) ──────────────────────────────────────────────────────

def cerca_voli(data_andata, data_ritorno):
    """
    Cerca voli ITA Airways FCO→AHO su Kayak.
    Restituisce il prezzo minimo trovato per 2 persone A/R, o None.
    """
    da = datetime.strptime(data_andata, "%Y-%m-%d").strftime("%Y-%m-%d")
    a = datetime.strptime(data_ritorno, "%Y-%m-%d").strftime("%Y-%m-%d")
    url = f"https://www.kayak.it/flights/FCO-AHO/{da}/{a}/2adults?sort=price_a"

    try:
        r = requests.get(url, headers=headers_casuali(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Kayak mostra i prezzi in elementi con classe che include "price"
        # Cerchiamo il primo prezzo nella pagina (già ordinati per prezzo)
        prezzi = []
        for el in soup.find_all(attrs={"class": lambda c: c and "price" in c.lower()}):
            testo = el.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
            try:
                val = float("".join(c for c in testo if c.isdigit() or c == "."))
                if 50 < val < 2000:
                    prezzi.append(val)
            except ValueError:
                pass

        if prezzi:
            minimo = min(prezzi)
            print(f"[VOLO] {da}→{a}: minimo trovato €{minimo:.0f} (2 pers A/R)")
            return minimo
        else:
            print(f"[VOLO] {da}→{a}: nessun prezzo trovato nel DOM")
            return None

    except Exception as e:
        print(f"[ERRORE] Volo {da}→{a}: {e}")
        return None

# ─── SCRAPER TRAGHETTO (DirectFerries) ─────────────────────────────────────────

def cerca_traghetto(data_andata, data_ritorno):
    """
    Cerca il prezzo del traghetto Civitavecchia→Porto Torres su DirectFerries.
    Restituisce prezzo A/R per 2 passeggeri a piedi, o None.
    """
    # DirectFerries ha URL parametrizzati
    da_str = datetime.strptime(data_andata, "%Y-%m-%d").strftime("%d-%m-%Y")
    a_str = datetime.strptime(data_ritorno, "%Y-%m-%d").strftime("%d-%m-%Y")
    url = (
        f"https://www.directferries.it/book_ferry.htm"
        f"?operator=0&depart=Civitavecchia&arrive=Porto+Torres"
        f"&depart_date={da_str}&return_date={a_str}&adults=2&children=0&return=1"
    )

    try:
        r = requests.get(url, headers=headers_casuali(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        prezzi = []
        for el in soup.find_all(string=lambda t: t and "€" in t):
            testo = el.strip().replace("€", "").replace(".", "").replace(",", ".").strip()
            try:
                val = float("".join(c for c in testo if c.isdigit() or c == "."))
                if 30 < val < 1000:
                    prezzi.append(val)
            except ValueError:
                pass

        if prezzi:
            minimo = min(prezzi)
            totale_2pers = minimo * 2
            print(f"[TRAGHETTO] {da_str}→{a_str}: €{minimo:.0f} pp → €{totale_2pers:.0f} (2 pers A/R)")
            return totale_2pers
        else:
            print(f"[TRAGHETTO] {da_str}→{a_str}: nessun prezzo trovato")
            return None

    except Exception as e:
        print(f"[ERRORE] Traghetto {da_str}→{a_str}: {e}")
        return None

# ─── SCRAPER ALLOGGIO (Booking.com) ────────────────────────────────────────────

def cerca_alloggio(data_andata, data_ritorno):
    """
    Cerca appartamenti 2 camere ad Alghero su Booking.com.
    Restituisce il prezzo minimo per notte trovato, o None.
    """
    checkin = data_andata
    checkout = data_ritorno
    notti = (datetime.strptime(data_ritorno, "%Y-%m-%d") - datetime.strptime(data_andata, "%Y-%m-%d")).days

    url = (
        f"https://www.booking.com/searchresults.it.html"
        f"?ss=Alghero&checkin={checkin}&checkout={checkout}"
        f"&group_adults=2&no_rooms=1&nflt=entire_place%3D1%3Broom_amenities%3D18"
        f"&order=price"
    )

    try:
        r = requests.get(url, headers=headers_casuali(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        prezzi = []
        for el in soup.find_all(attrs={"data-testid": "price-and-discounted-price"}):
            testo = el.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
            try:
                val = float("".join(c for c in testo if c.isdigit() or c == "."))
                if 50 < val < 10000:
                    prezzi.append(val)
            except ValueError:
                pass

        if prezzi:
            minimo_totale = min(prezzi)
            per_notte = round(minimo_totale / notti, 0) if notti > 0 else minimo_totale
            print(f"[ALLOGGIO] {checkin}→{checkout}: €{minimo_totale:.0f} totale ({notti} notti) = €{per_notte:.0f}/notte")
            return {"totale": minimo_totale, "per_notte": per_notte, "notti": notti}
        else:
            print(f"[ALLOGGIO] {checkin}→{checkout}: nessun prezzo trovato")
            return None

    except Exception as e:
        print(f"[ERRORE] Alloggio {checkin}→{checkout}: {e}")
        return None

# ─── LOGICA NOTIFICHE ──────────────────────────────────────────────────────────

def controlla_e_notifica(chiave, nuovo_prezzo, vecchio_prezzo, soglia_ottima, etichetta, url_prenotazione):
    messaggi = []
    ora = datetime.now().strftime("%d/%m %H:%M")

    # Notifica se prezzo scende rispetto al precedente
    if vecchio_prezzo is not None and nuovo_prezzo < vecchio_prezzo:
        risparmio = vecchio_prezzo - nuovo_prezzo
        messaggi.append(
            f"📉 <b>Prezzo sceso!</b> — {etichetta}\n"
            f"<b>€{nuovo_prezzo:.0f}</b> (era €{vecchio_prezzo:.0f}, -€{risparmio:.0f})\n"
            f"🔗 <a href='{url_prenotazione}'>Prenota ora</a>\n"
            f"<i>{ora}</i>"
        )

    # Notifica se sotto soglia ottima (max 1 volta per sessione — evita spam)
    if nuovo_prezzo <= soglia_ottima:
        messaggi.append(
            f"🎯 <b>Prezzo ottimo!</b> — {etichetta}\n"
            f"<b>€{nuovo_prezzo:.0f}</b> (soglia ottima: €{soglia_ottima:.0f})\n"
            f"🔗 <a href='{url_prenotazione}'>Prenota ora</a>\n"
            f"<i>{ora}</i>"
        )

    return messaggi

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"Bot Alghero avviato: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*50}\n")

    prezzi_precedenti = carica_prezzi_precedenti()
    prezzi_nuovi = {}
    tutti_messaggi = []

    for (data_andata, data_ritorno) in DATE_FINESTRE:
        notti = (datetime.strptime(data_ritorno, "%Y-%m-%d") - datetime.strptime(data_andata, "%Y-%m-%d")).days
        etichetta_date = f"{data_andata} → {data_ritorno} ({notti} notti)"
        print(f"\n--- Finestra: {etichetta_date} ---")

        # Chiavi univoche per ogni finestra
        chiave_volo = f"volo_{data_andata}_{data_ritorno}"
        chiave_traghetto = f"traghetto_{data_andata}_{data_ritorno}"
        chiave_alloggio = f"alloggio_{data_andata}_{data_ritorno}"

        # ── VOLO ──
        prezzo_volo = cerca_voli(data_andata, data_ritorno)
        pausa()
        if prezzo_volo:
            prezzi_nuovi[chiave_volo] = prezzo_volo
            vecchio = prezzi_precedenti.get(chiave_volo)
            msgs = controlla_e_notifica(
                chiave_volo,
                prezzo_volo,
                vecchio,
                SOGLIE_OTTIME["volo_ita_ar_2persone"],
                f"Volo ITA A/R 2 pers — {etichetta_date}",
                "https://www.ita-airways.com/it_it/voli-offerte/offerte-voli.html"
            )
            tutti_messaggi.extend(msgs)

        # ── TRAGHETTO ──
        prezzo_traghetto = cerca_traghetto(data_andata, data_ritorno)
        pausa()
        if prezzo_traghetto:
            prezzi_nuovi[chiave_traghetto] = prezzo_traghetto
            vecchio = prezzi_precedenti.get(chiave_traghetto)
            msgs = controlla_e_notifica(
                chiave_traghetto,
                prezzo_traghetto,
                vecchio,
                SOGLIE_OTTIME["traghetto_ar_2persone"],
                f"Traghetto Grimaldi A/R 2 pers — {etichetta_date}",
                "https://www.grimaldi-lines.com/it/prenota/"
            )
            tutti_messaggi.extend(msgs)

        # ── ALLOGGIO ──
        risultato_alloggio = cerca_alloggio(data_andata, data_ritorno)
        pausa()
        if risultato_alloggio:
            per_notte = risultato_alloggio["per_notte"]
            totale = risultato_alloggio["totale"]
            prezzi_nuovi[chiave_alloggio] = per_notte
            vecchio = prezzi_precedenti.get(chiave_alloggio)
            msgs = controlla_e_notifica(
                chiave_alloggio,
                per_notte,
                vecchio,
                SOGLIE_OTTIME["alloggio_notte"],
                f"Alloggio Alghero {notti} notti (€{totale:.0f} tot) — {etichetta_date}",
                f"https://www.booking.com/searchresults.it.html?ss=Alghero&checkin={data_andata}&checkout={data_ritorno}&group_adults=2&nflt=entire_place%3D1&order=price"
            )
            tutti_messaggi.extend(msgs)

    # Invia tutte le notifiche
    if tutti_messaggi:
        print(f"\n[NOTIFICHE] Invio {len(tutti_messaggi)} messaggi Telegram...")
        for msg in tutti_messaggi:
            invia_telegram(msg)
            time.sleep(1)
    else:
        print("\n[INFO] Nessuna variazione di prezzo rilevante. Nessuna notifica inviata.")

    # Riepilogo giornaliero (ogni check salva i dati, ma il riepilogo lo mandiamo solo a mezzogiorno)
    ora_corrente = datetime.now().hour
    if ora_corrente == 9:  # Riepilogo mattutino alle 9
        invia_riepilogo(prezzi_nuovi)

    # Salva i nuovi prezzi
    prezzi_precedenti.update(prezzi_nuovi)
    salva_prezzi(prezzi_precedenti)
    print(f"\n[OK] Prezzi salvati in {FILE_PREZZI}")

def invia_riepilogo(prezzi):
    ora = datetime.now().strftime("%d/%m %H:%M")
    righe = [f"📊 <b>Riepilogo prezzi Alghero</b> — {ora}\n"]

    for chiave, valore in sorted(prezzi.items()):
        tipo = chiave.split("_")[0]
        parti = chiave.split("_")
        date = f"{parti[1]} → {parti[2]}" if len(parti) >= 3 else ""
        emoji = {"volo": "✈️", "traghetto": "⛴️", "alloggio": "🏠"}.get(tipo, "•")
        righe.append(f"{emoji} <b>{tipo.capitalize()}</b> {date}: <b>€{valore:.0f}</b>")

    invia_telegram("\n".join(righe))

if __name__ == "__main__":
    main()
