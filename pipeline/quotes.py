"""Živé ceny pro aplikaci (docs/data/quotes.json), obnovují se při každém běhu `fast` (~10 min).
- krypto: jedno volání CoinGecko /coins/markets pro celé top 100 (+ vlastní krypta se zdrojem Yahoo)
- akcie: s klíčem STOOQ_APIKEY dávkově celé univerzum (Stooq /q/l/); bez klíče Yahoo po jednom jen pro sledované symboly a tickery se signály
Hodnoty jsou 'poslední známá cena' – zpoždění určuje burza/zdroj, proto se v aplikaci ukazuje stáří."""
import io, json, os
from datetime import datetime, timezone
import pandas as pd
from . import http, prices as P
from .config import SITE_DATA

YAHOO_PER_RUN = 45
STOOQ_BATCH = 40

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ------------------------------------------------------------------ parsery
def parse_cg_markets(rows, id2t):
    out, t = {}, now_iso()
    for r in rows:
        tk = id2t.get(r.get("id"))
        if tk and r.get("current_price") is not None:
            out[tk] = {"p": float(r["current_price"]), "t": r.get("last_updated") or t, "src": "coingecko",
                       "c24": r.get("price_change_percentage_24h")}
    return out

def parse_stooq_quotes(txt, code2t):
    """CSV: Symbol,Date,Time,Open,High,Low,Close,Volume ('N/D' = bez dat)."""
    out, t = {}, now_iso()
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return out
    cols = {c.lower(): c for c in df.columns}
    if "symbol" not in cols or "close" not in cols:
        return out
    for _, r in df.iterrows():
        tk = code2t.get(str(r[cols["symbol"]]).lower())
        try:
            px = float(r[cols["close"]])
        except (TypeError, ValueError):
            continue
        if tk and px > 0:
            out[tk] = {"p": px, "t": t, "src": "stooq"}
    return out

# ------------------------------------------------------------------ zdroje
def crypto_quotes(uni):
    cu = uni[uni["region"].eq("CRYPTO")]
    id2t = {r.cg_id: r.ticker for r in cu.itertuples() if r.cg_id}
    out = {}
    if id2t:
        try:
            ids = ",".join(id2t)
            txt = http.get(f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}&per_page=250&sparkline=false", "coingecko")
            out = parse_cg_markets(json.loads(txt), id2t)
        except Exception as e:
            print(f"[quotes] CoinGecko: {str(e)[:80]}")
    return out

def stooq_batch(tickers, uni):
    if not P.STOOQ_KEY:
        return {}
    code = {r.ticker: r.stooq for r in uni.itertuples() if r.stooq and r.ticker in set(tickers)}
    code2t = {c.lower(): t for t, c in code.items()}
    out, items = {}, list(code2t)
    for i in range(0, len(items), STOOQ_BATCH):
        chunk = items[i:i + STOOQ_BATCH]
        try:
            txt = http.get("https://stooq.com/q/l/?s=" + ",".join(chunk) + "&f=sd2t2ohlcv&h&e=csv" + P.stooq_key_param(), "stooq_q")
            out.update(parse_stooq_quotes(txt, code2t))
        except Exception as e:
            print(f"[quotes] Stooq dávka: {str(e)[:80]}")
            break
    return out

def yahoo_quotes(tickers, state):
    """Po jednom (neoficiální endpoint). Rotuje se, aby se za několik běhů obešli všichni sledovaní."""
    out, tk = {}, sorted(tickers)
    if not tk:
        return out
    k = state.get("yq_rr", 0) % len(tk)
    pick = (tk[k:] + tk[:k])[:YAHOO_PER_RUN]
    state["yq_rr"] = (k + YAHOO_PER_RUN) % len(tk)
    for t in pick:
        q = P.latest_quote(t)
        if q:
            out[t] = {"p": q["price"], "t": q["time"], "src": "yahoo"}
    return out

def refresh(uni, tracked, state, demo=False, db=None):
    """tracked = sledované symboly + tickery se signály. Vrací dict ticker -> {p, t, src}."""
    if demo:                                            # syntetické ceny pro test UI: poslední uzávěrka ± malý šum
        import numpy as np
        rng = np.random.default_rng(3)
        out = {}
        for frame in (db,):
            if frame is None:
                continue
            for t in list(frame.columns):
                s = frame[t].dropna()
                if len(s):
                    out[t] = {"p": float(s.iloc[-1] * (1 + rng.normal(0, 0.004))), "t": now_iso(), "src": "demo"}
        return out
    out = crypto_quotes(uni)
    eq = uni[~uni["region"].isin(["CRYPTO"])]
    if P.STOOQ_KEY:
        out.update(stooq_batch(set(eq["ticker"]), uni))
    need = {t for t in tracked if t not in out and t in set(uni["ticker"])}
    custom_crypto = {t for t in need if t.endswith("-USD")}
    out.update(yahoo_quotes(need | custom_crypto, state))
    return out

def write(q):
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    json.dump({"asof": now_iso(), "q": {t: {"p": round(v["p"], 6 if v["p"] < 1 else 3), "t": v["t"], "src": v["src"], **({"c24": v["c24"]} if v.get("c24") is not None else {})}
                                         for t, v in q.items()}},
              open(SITE_DATA / "quotes.json", "w"), separators=(",", ":"))
