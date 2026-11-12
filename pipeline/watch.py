"""Sledované symboly z aplikace (oblíbené) -> serverová strana: vlastní univerzum, historie cen, 8-K, signály, živé ceny.
Aplikace symboly pošle přes předvyplněné GitHub Issue (titulek 'watchlist', tělo JSON se symboly; ceny nákupu se NIKDY neposílají).
Workflow watchlist.yml ho přijme jen od majitele repa, zpracuje a issue zavře."""
import json, re
from datetime import datetime, timezone
import pandas as pd
from . import http
from .config import CACHE
from .universe import COLS, stooq_code

WATCH_FILE = CACHE / "watchlist.json"
SEC_TICKERS_FILE = CACHE / "sec_tickers.json"
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,14}$")
MAX_SYMBOLS = 80
EU_SUFFIX = {".DE", ".F", ".PA", ".AS", ".MI", ".MC", ".L", ".SW", ".ST", ".CO", ".HE", ".OL", ".VI", ".BR", ".LS", ".IR", ".WA", ".PR", ".AT"}

# ------------------------------------------------------------------ vstup
def parse_symbols(body):
    """Z těla issue vytáhne symboly: JSON {"symbols":[...]} (i v code-fence) nebo prostý seznam. Vše validuje, nic nevykonává."""
    body = (body or "").strip()
    syms = []
    m = re.search(r"\{.*\}", body, re.S)
    parsed = False
    if m:
        try:
            js = json.loads(m.group(0))
            parsed = isinstance(js, dict)
            syms = js.get("symbols", []) if parsed else []
            if not isinstance(syms, list):
                syms = []
        except Exception:
            syms = []
    if not parsed:                                   # JSON se vzal vážně, jen když je platný; jinak prostý seznam (AAPL, MSFT)
        syms = re.split(r"[\s,;]+", re.sub(r"[`\[\]\"']", " ", body))
    out = []
    for x in syms:
        x = str(x).strip().upper()
        if SYMBOL_RE.match(x) and x not in out:
            out.append(x)
    return out[:MAX_SYMBOLS]

def is_explicit_empty(body):
    """True, když tělo je JSON se seznamem symbolů, který je prázdný (uživatel odebral všechny oblíbené)."""
    m = re.search(r"\{.*\}", (body or ""), re.S)
    if not m:
        return False
    try:
        js = json.loads(m.group(0))
    except Exception:
        return False
    return isinstance(js, dict) and isinstance(js.get("symbols"), list) and len(js["symbols"]) == 0

def load():
    if WATCH_FILE.exists():
        try:
            return json.load(open(WATCH_FILE)).get("symbols", [])
        except Exception:
            pass
    return []

def save(symbols):
    json.dump({"symbols": list(symbols), "updated": datetime.now(timezone.utc).isoformat()}, open(WATCH_FILE, "w"))

# ------------------------------------------------------------------ metadata symbolu
def classify(sym):
    """Region podle tvaru symbolu: -USD = krypto, přípona burzy = EU nebo OTHER, bez přípony = US."""
    if sym.endswith("-USD"):
        return "CRYPTO"
    if "." in sym:
        return "EU" if "." + sym.rsplit(".", 1)[1] in EU_SUFFIX else "OTHER"
    return "US"

def parse_yahoo_search(js, sym):
    for q in js.get("quotes", []):
        if str(q.get("symbol", "")).upper() == sym:
            return {"name": q.get("longname") or q.get("shortname") or sym, "sector": q.get("sector") or "",
                    "industry": q.get("industry") or "", "type": q.get("quoteType", "")}
    return {}

def parse_sec_tickers(js):
    return {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in js.values()}

def sec_ciks(offline=False):
    if SEC_TICKERS_FILE.exists() and (datetime.now().timestamp() - SEC_TICKERS_FILE.stat().st_mtime < 30 * 86400):
        return json.load(open(SEC_TICKERS_FILE))
    if offline:
        return {}
    try:
        from .sources.edgar import _sec_get
        m = parse_sec_tickers(json.loads(_sec_get("https://www.sec.gov/files/company_tickers.json")))
        json.dump(m, open(SEC_TICKERS_FILE, "w"))
        return m
    except Exception as e:
        print(f"[watch] SEC tickers: {e}")
        return {}

def describe(sym, offline=False):
    if offline:
        return {}
    try:
        txt = http.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={sym}&quotesCount=5&newsCount=0", "yahoo_search")
        return parse_yahoo_search(json.loads(txt), sym)
    except Exception:
        return {}

def build_rows(symbols, uni, offline=False):
    have = set(uni["ticker"])
    cik_map = None
    rows = []
    for sym in symbols:
        if sym in have:
            continue
        region = classify(sym)
        meta = describe(sym, offline)
        cik = ""
        if region == "US":
            cik_map = cik_map if cik_map is not None else sec_ciks(offline)
            cik = cik_map.get(sym, "")
        rows.append({"ticker": sym, "name": meta.get("name", sym), "sector": meta.get("sector") or "Vlastní",
                     "industry": meta.get("industry", ""), "region": region, "country": "", "indices": "CUSTOM", "cik": cik,
                     "stooq": stooq_code(sym, region) if region != "CRYPTO" else "", "cg_id": ""})
    return pd.DataFrame(rows, columns=COLS) if rows else pd.DataFrame(columns=COLS)

def merge_custom(uni, symbols=None, offline=False):
    """Univerzum + vlastní symboly (indices == CUSTOM). Staré CUSTOM řádky mimo seznam se zahodí, existující tickery se nepřepisují."""
    symbols = load() if symbols is None else symbols
    base = uni[uni["indices"].ne("CUSTOM") | uni["ticker"].isin(symbols)].copy()
    new = build_rows(symbols, base, offline)
    out = pd.concat([base, new], ignore_index=True) if len(new) else base
    return out, list(new["ticker"])
