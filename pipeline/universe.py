"""Univerzum firem: S&P 500 + Nasdaq-100 (Wikipedia), STOXX 600 (seed + volitelné CSV z iShares) + doplňky."""
import io, re
import pandas as pd
from . import http
from .config import CACHE, ROOT

SEEDS = ROOT / "pipeline" / "seeds"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
STOOQ_SUFFIX = {".DE": ".de", ".L": ".uk", ".WA": ".pl"}          # kde Stooq obvykle pokrytí má
LOC_SUFFIX = {"Germany": ".DE", "United Kingdom": ".L", "France": ".PA", "Netherlands": ".AS", "Belgium": ".BR",
              "Portugal": ".LS", "Switzerland": ".SW", "Italy": ".MI", "Spain": ".MC", "Sweden": ".ST",
              "Denmark": ".CO", "Finland": ".HE", "Norway": ".OL", "Ireland": ".IR", "Austria": ".VI", "Poland": ".WA"}
SECTOR_FIX = {"Communication": "Communication Services", "Telecommunications": "Communication Services",
              "Information technology": "Information Technology"}
COLS = ["ticker", "name", "sector", "industry", "region", "country", "indices", "cik", "stooq", "cg_id"]
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=200&page=1&sparkline=false"
NOT_COIN = re.compile(r"usd|tether|wrapped|staked|bridged|dollar|\bweth\b|restaked|liquid staking", re.I)

def _norm_us(t):
    return str(t).strip().upper().replace(".", "-")

def stooq_code(ticker, region):
    if region == "US" or (region == "ETF" and "." not in ticker):
        return f"{ticker.lower()}.us"
    for suf, s in STOOQ_SUFFIX.items():
        if ticker.endswith(suf):
            return ticker[: -len(suf)].lower() + s
    return ""

def _read_tables(url, source):
    html = http.get(url, source, headers={"User-Agent": "SignalApp/1.0 (research; contact via GitHub)"})
    return pd.read_html(io.StringIO(html))

def fetch_sp500():
    t = _read_tables(SP500_URL, "wikipedia")[0]
    df = pd.DataFrame({"ticker": t["Symbol"].map(_norm_us), "name": t["Security"], "sector": t["GICS Sector"],
                       "industry": t["GICS Sub-Industry"], "cik": t.get("CIK")})
    df["indices"] = "SP500"
    return df

def fetch_ndx():
    for t in _read_tables(NDX_URL, "wikipedia"):
        cols = {str(c).lower(): c for c in t.columns}
        if "ticker" in cols and "company" in cols and any("sector" in c for c in cols):
            sec = next(c for k, c in cols.items() if "sector" in k)
            ind = next((c for k, c in cols.items() if "sub-industry" in k or "subindustry" in k), None)
            df = pd.DataFrame({"ticker": t[cols["ticker"]].map(_norm_us), "name": t[cols["company"]],
                               "sector": t[sec], "industry": t[ind] if ind else ""})
            df["cik"] = None
            df["indices"] = "NDX"
            return df
    raise ValueError("Nasdaq-100 tabulka nenalezena")

def load_stoxx_csv(path):
    """iShares STOXX Europe 600 holdings CSV (hlavička 'Ticker,Name,Sector,...,Location,...')."""
    lines = open(path, encoding="utf-8-sig", errors="ignore").read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.lower().startswith("ticker,"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df = df[df.get("Asset Class", "Equity").astype(str).str.lower().eq("equity")] if "Asset Class" in df else df
    out = []
    for _, r in df.iterrows():
        suf = LOC_SUFFIX.get(str(r.get("Location", "")).strip())
        if not suf or pd.isna(r.get("Ticker")):
            continue
        tk = re.sub(r"\s+", "-", str(r["Ticker"]).strip().upper()) + suf
        sec = SECTOR_FIX.get(str(r.get("Sector", "")).strip(), str(r.get("Sector", "")).strip())
        out.append({"ticker": tk, "name": r.get("Name", tk), "sector": sec, "industry": "",
                    "country": str(r.get("Location", "")), "indices": "STOXX600", "region": "EU"})
    return pd.DataFrame(out)

def fetch_crypto_top(n=100):
    """Top n kryptoměn podle tržní kapitalizace (CoinGecko) bez stablecoinů a wrapped/staked duplicit."""
    import json
    rows = json.loads(http.get(CG_MARKETS, "coingecko"))
    return _crypto_frame([(r["id"], r["symbol"], r["name"]) for r in rows], n)

def _crypto_frame(items, n):
    out, seen = [], set()
    for cid, sym, name in items:
        sym = str(sym).upper()
        if NOT_COIN.search(name) or NOT_COIN.search(cid) or sym in seen or not sym.isalnum():
            continue
        seen.add(sym)
        out.append({"ticker": f"{sym}-USD", "name": name, "sector": "Crypto", "industry": "Kryptoměna", "region": "CRYPTO",
                    "country": "", "indices": "CRYPTO100", "cik": "", "stooq": "", "cg_id": cid})
        if len(out) >= n:
            break
    return pd.DataFrame(out)

def load_crypto(offline=False):
    if not offline:
        try:
            df = fetch_crypto_top()
            if len(df) >= 30:
                return df
        except Exception as e:
            print(f"[universe] CoinGecko selhalo ({e}) – použiji seed")
    seed = pd.read_csv(SEEDS / "crypto_seed.csv", dtype=str)
    return _crypto_frame(list(zip(seed["id"], seed["symbol"], seed["name"])), 100)

def build(offline=False):
    parts = []
    if not offline:
        for fn in (fetch_sp500, fetch_ndx):
            try:
                parts.append(fn())
            except Exception as e:
                print(f"[universe] {fn.__name__} selhalo: {e}")
    seed = pd.read_csv(SEEDS / "extras.csv", dtype=str).fillna("")
    seed["indices"] = seed["region"].map({"EU": "STOXX600*", "OTHER": "EXTRA", "ETF": "ETF"})
    parts.append(seed)
    stoxx = SEEDS / "stoxx600.csv"
    if stoxx.exists():
        try:
            parts.append(load_stoxx_csv(stoxx))
        except Exception as e:
            print(f"[universe] stoxx600.csv nelze načíst: {e}")
    parts.append(load_crypto(offline))
    df = pd.concat(parts, ignore_index=True)
    for c in COLS:
        if c not in df:
            df[c] = ""
    df["sector"] = df["sector"].astype(str).replace(SECTOR_FIX)
    df["ticker"] = df["ticker"].astype(str).str.strip()
    # sloučení indexů u duplicit (SP500 + NDX), první záznam vyhrává
    idx = df.groupby("ticker")["indices"].agg(lambda s: ",".join(sorted(set(",".join(map(str, s)).split(",")) - {""})))
    df = df.drop_duplicates("ticker", keep="first").copy()
    df["indices"] = df["ticker"].map(idx)
    def region(r):
        if r.get("region") in ("EU", "OTHER", "ETF", "CRYPTO"):
            return r["region"]
        return "US"
    df["region"] = df.apply(region, axis=1)
    df["country"] = df["country"].replace("", "US")
    df["cik"] = df["cik"].apply(lambda c: str(int(float(c))).zfill(10) if str(c) not in ("", "nan", "None") else "")
    df["industry"] = df["industry"].fillna("")
    df["stooq"] = [stooq_code(t, r) if r != "CRYPTO" else "" for t, r in zip(df["ticker"], df["region"])]
    df["cg_id"] = df["cg_id"].fillna("")
    df = df[COLS].reset_index(drop=True)
    return df

def refresh(offline=False):
    df = build(offline)
    df.to_csv(CACHE / "universe.csv", index=False)
    print(f"[universe] {len(df)} firem: {df['region'].value_counts().to_dict()}")
    return df

def load():
    p = CACHE / "universe.csv"
    if not p.exists():
        return refresh(offline=False)
    return pd.read_csv(p, dtype=str).fillna("")

def baskets(uni, min_members=4):
    """Koše pro model B: sektory + pododvětví (≥ min_members firem) + jednotlivé makro-ETF."""
    out = {}
    eq = uni[~uni["region"].isin(["ETF", "CRYPTO"]) & uni["indices"].ne("CUSTOM")]
    for s, g in eq.groupby("sector"):
        if s and len(g) >= min_members:
            out[f"sector:{s}"] = list(g["ticker"])
    for i, g in eq[eq["industry"].ne("")].groupby("industry"):
        if len(g) >= min_members:
            out[f"industry:{i}"] = list(g["ticker"])
    for t in uni[uni["region"].eq("ETF")]["ticker"]:
        out[f"etf:{t}"] = [t]
    return out

def crypto_baskets(uni):
    """Koše krypta: BTC, ETH, větší altcoiny (pořadí 3–20), menší altcoiny (21+)."""
    c = list(uni[uni["region"].eq("CRYPTO") & uni["indices"].ne("CUSTOM")]["ticker"])      # pořadí = tržní kapitalizace
    out = {}
    for t in ("BTC-USD", "ETH-USD"):
        if t in c:
            out[f"crypto:{t.split('-')[0]}"] = [t]
    rest = [t for t in c if t not in ("BTC-USD", "ETH-USD")]
    if len(rest) >= 6:
        out["crypto:large_alts"] = rest[:18]
    if len(rest) >= 30:
        out["crypto:small_alts"] = rest[18:]
    return out
