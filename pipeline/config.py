"""Centrální konfigurace. Vše důležité se ladí tady nebo přes proměnné prostředí."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("CACHE_DIR", ROOT / "cache"))      # sem se stahují assety z release 'data'
SITE = ROOT / "docs"
SITE_DATA = Path(os.environ.get("SITE_DATA_DIR", SITE / "data"))   # generuje se za běhu, nekomituje se (desktop verze: vlastní složka)
for p in (CACHE, SITE_DATA):
    p.mkdir(parents=True, exist_ok=True)

TZ = "Europe/Prague"
ACTIVE_START_HOUR, ACTIVE_END_HOUR = 8, 24    # živý běh jen 8:00–24:00 pražského času

SEC_UA = os.environ.get("SEC_UA", "SignalApp research bot (nastav SEC_UA='Jmeno email@domena.cz')")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
GH_RELEASE_TAG = "data"

BENCH_US, BENCH_EU = "SPY", "EXSA.DE"          # regionální benchmarky pro abnormální výnosy
HORIZON = 20                                    # obchodních dnů vějíře
QUANTILES = [0.05, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95]
HISTORY_START = "2012-01-01"

# prahy
NOTIFY_MIN_SEVERITY = 6.0
SHOW_MIN_SEVERITY = 3.0
MAX_SIGNALS = 24
GDELT_MAX_SLOTS_PER_RUN = 8                     # kolik 15min souborů max. za běh (úspora času)
SHOCK_SIGMA = 4.0                               # neobjasněný cenový šok (násobek σ abnormálního výnosu)

# gating modelů: model se pro signály používá jen když v out-of-sample testu překoná základní odhad
GATE_MIN_IMPROVEMENT = 0.005                    # min. relativní zlepšení pinball loss (0,5 %)
GATE_COVERAGE = (0.84, 0.96)                    # pokrytí 90% intervalu v testu

ITEM_CZ = {
    "1.01": "Významná smlouva", "1.02": "Ukončení smlouvy", "1.03": "Bankrot / úpadek",
    "1.05": "Kybernetický incident", "2.01": "Akvizice / prodej aktiv", "2.02": "Výsledky hospodaření",
    "2.03": "Nový dluh", "2.04": "Urychlení splatnosti dluhu", "2.05": "Restrukturalizace",
    "2.06": "Znehodnocení aktiv", "3.01": "Upozornění na delisting", "3.02": "Emise akcií mimo registraci",
    "3.03": "Změna práv akcionářů", "4.01": "Změna auditora", "4.02": "Neplatné dřívější výkazy (restatement)",
    "5.01": "Změna kontroly", "5.02": "Odchod/příchod vedení či ředitelů", "5.03": "Změna stanov",
    "5.07": "Hlasování akcionářů", "7.01": "Reg FD sdělení", "8.01": "Jiná událost", "9.01": "Přílohy",
    "PS+": "Neobjasněný cenový skok nahoru", "PS-": "Neobjasněný cenový propad",
}
