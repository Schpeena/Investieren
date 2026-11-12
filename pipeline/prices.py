"""Cenová databáze (široká tabulka close: datum × ticker) + stahování ze Stooq/Yahoo."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from . import http
from .config import CACHE, HISTORY_START

PRICES_FILE = CACHE / "prices.parquet"
CRYPTO_FILE = CACHE / "crypto.parquet"      # krypto obchoduje 7 dní v týdnu -> samostatná tabulka s kalendářními dny
_stooq_rl, _yahoo_rl = http.RateLimiter(4), http.RateLimiter(3)

def load_db():
    if PRICES_FILE.exists():
        return pd.read_parquet(PRICES_FILE)
    return pd.DataFrame()

def save_db(df, path=None):
    df = df.sort_index()
    df = df.loc[:, df.notna().sum() > 20].astype("float32")
    df.to_parquet(path or PRICES_FILE, compression="zstd")

def load_crypto_db():
    if CRYPTO_FILE.exists():
        return pd.read_parquet(CRYPTO_FILE)
    return pd.DataFrame()

STOOQ_KEY = os.environ.get("STOOQ_APIKEY") or ""
_stooq_state = {"bad": 0, "ok": 0}            # jistič: Stooq od roku 2025 chce apikey; bez něj by každý ticker plýtval jedním požadavkem

def stooq_key_param():
    return f"&apikey={STOOQ_KEY}" if STOOQ_KEY else ""

def stooq_series(code, start):
    if _stooq_state["bad"] >= 8 and _stooq_state["ok"] == 0:
        raise ValueError("Stooq vypnut pro tento běh (opakovaně vrací HTML místo CSV – chybí STOOQ_APIKEY?)")
    _stooq_rl.wait()
    d1 = pd.Timestamp(start).strftime("%Y%m%d")
    d2 = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y%m%d")
    txt = http.get(f"https://stooq.com/q/d/l/?s={code}&i=d&d1={d1}&d2={d2}{stooq_key_param()}", "stooq")
    if not txt.startswith("Date"):
        _stooq_state["bad"] += 1
        raise ValueError("Stooq: neočekávaná odpověď (vyžaduje apikey – nastav secret STOOQ_APIKEY, viz README)")
    _stooq_state["ok"] += 1
    df = pd.read_csv(pd.io.common.StringIO(txt))
    if "Close" not in df or df.empty:
        raise ValueError("Stooq: prázdné")
    s = pd.Series(df["Close"].values, index=pd.to_datetime(df["Date"]))
    return s[~s.index.duplicated()].sort_index().astype(float)

def yahoo_series(sym, start=None, rng=None):
    _yahoo_rl.wait()
    q = f"range={rng}" if rng else f"period1={int(pd.Timestamp(start).timestamp())}&period2={int(pd.Timestamp.now().timestamp()) + 86400}"
    txt = http.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?{q}&interval=1d&events=div,splits", "yahoo")
    r = json.loads(txt)["chart"]["result"][0]
    ts = r["timestamp"]
    q0 = r["indicators"]["quote"][0]["close"]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    vals = adj or q0
    idx = [pd.Timestamp(datetime.fromtimestamp(t, timezone.utc).date()) for t in ts]
    s = pd.Series(vals, index=idx, dtype="float64").dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()

def fetch_one(ticker, stooq, start, incremental):
    err = None
    if stooq:
        try:
            return stooq_series(stooq, start)
        except Exception as e:
            err = e
    try:
        return yahoo_series(ticker, start=None if incremental else start, rng="1mo" if incremental else None)
    except Exception as e:
        return err or e

def update(universe, full=False, workers=6):
    """Doplní ceny. full=True stáhne celou historii pro tickery, které v DB chybí."""
    db = load_db()
    have = set(db.columns)
    jobs = []
    for _, r in universe.iterrows():
        t = r["ticker"]
        if t in have and not full:
            last = db[t].last_valid_index()
            jobs.append((t, r["stooq"], (last - pd.Timedelta(days=7)) if last is not None else HISTORY_START, True))
        elif t not in have or full:
            jobs.append((t, r["stooq"], HISTORY_START, False))
    results, fails = {}, []
    with ThreadPoolExecutor(workers) as ex:
        for (t, *_), res in zip(jobs, ex.map(lambda j: fetch_one(*j), jobs)):
            if isinstance(res, Exception):
                fails.append(t)
            else:
                results[t] = res
    if results:
        for t, ser in list(results.items()):          # navázání na starou historii bez skoku (rozdíl adjustací zdrojů)
            if t in db.columns:
                old = db[t].dropna()
                common = old.index.intersection(ser.index)
                if len(common) and ser.loc[common[-1]] > 0:
                    results[t] = ser * (old.loc[common[-1]] / ser.loc[common[-1]])
        new = pd.DataFrame(results)
        db = new.combine_first(db) if not db.empty else new      # nová data mají přednost
        db = db.sort_index()
        save_db(db)
    print(f"[prices] staženo {len(results)}/{len(jobs)} tickerů, selhalo {len(fails)}")
    return db, fails

YAHOO_ALIAS = {"TON-USD": "TON11419-USD", "SUI-USD": "SUI20947-USD", "APT-USD": "APT21794-USD", "ARB-USD": "ARB11841-USD"}
_cg_rl = http.RateLimiter(0.2)

def coingecko_series(cg_id, days=365):
    """Záloha: CoinGecko free dává max. ~365 dní denní historie (stačí pro vějíř, ne pro trénink)."""
    _cg_rl.wait()
    txt = http.get(f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days={days}&interval=daily", "coingecko")
    pr = json.loads(txt)["prices"]
    s = pd.Series([p[1] for p in pr], index=[pd.Timestamp(datetime.fromtimestamp(p[0] / 1000, timezone.utc).date()) for p in pr], dtype="float64")
    return s[~s.index.duplicated(keep="last")].sort_index()

def _fetch_coin(t, cg_id, start, incremental):
    res = fetch_one(YAHOO_ALIAS.get(t, t), "", start, incremental)
    if isinstance(res, Exception) and cg_id:
        try:
            return coingecko_series(cg_id)
        except Exception as e:
            return e
    return res

def update_crypto(universe, workers=4):
    """Krypto z Yahoo (SYMBOL-USD, kalendářní dny). Co Yahoo nezná, se vynechá (a vypíše)."""
    cu = universe[universe["region"].eq("CRYPTO")]
    if cu.empty:
        return pd.DataFrame(), []
    cg = cu.set_index("ticker").get("cg_id", pd.Series(dtype=str)).to_dict()
    db = load_crypto_db()
    jobs = []
    for t in cu["ticker"]:
        if t in db.columns and db[t].last_valid_index() is not None:
            jobs.append((t, cg.get(t, ""), db[t].last_valid_index() - pd.Timedelta(days=7), True))
        else:
            jobs.append((t, cg.get(t, ""), HISTORY_START, False))
    results, fails = {}, []
    with ThreadPoolExecutor(workers) as ex:
        for (t, *_), res in zip(jobs, ex.map(lambda j: _fetch_coin(*j), jobs)):
            if isinstance(res, Exception):
                fails.append(t)
            else:
                results[t] = res
    if results:
        for t, ser in list(results.items()):
            if t in db.columns:
                old = db[t].dropna(); common = old.index.intersection(ser.index)
                if len(common) and ser.loc[common[-1]] > 0:
                    results[t] = ser * (old.loc[common[-1]] / ser.loc[common[-1]])
        new = pd.DataFrame(results)
        db = new.combine_first(db) if not db.empty else new
        db = db.sort_index()
        today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
        db = db[db.index < today]                                           # dnešní (nedokončená) svíčka se nebere; živá cena jde z quote
        db = db.reindex(pd.date_range(db.index[0], db.index[-1]))          # kalendářní dny bez děr
        save_db(db, CRYPTO_FILE)
    print(f"[crypto] staženo {len(results)}/{len(jobs)}, selhalo {len(fails)}: {fails[:10]}")
    return db, fails

def latest_quote(sym):
    """Poslední cena (i intradenní) pro konkrétní ticker; při selhání None."""
    try:
        _yahoo_rl.wait()
        sym = YAHOO_ALIAS.get(sym, sym)
        txt = http.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m", "yahoo")
        m = json.loads(txt)["chart"]["result"][0]["meta"]
        return {"price": float(m["regularMarketPrice"]),
                "time": datetime.fromtimestamp(m["regularMarketTime"], timezone.utc).isoformat()}
    except Exception:
        return None

# -------- pomocné výpočty nad DB --------
def bench_for(region):
    from .config import BENCH_EU, BENCH_US
    return BENCH_EU if region == "EU" else BENCH_US

def log_returns(db):
    return np.log(db.ffill(limit=5)).diff()

BENCH_BY_REGION = {"EU": "EXSA.DE", "CRYPTO": "BTC-USD"}      # ostatní regiony -> SPY

def abnormal(db, universe, window=250):
    """Beta-upravené denní abnormální výnosy: AR = r - beta*r_bench, beta z klouzavého okna (shrinkage k 1).
    Benchmark podle regionu: US/OTHER -> SPY, EU -> EXSA.DE, CRYPTO -> BTC-USD (BTC sám: AR = jeho výnos)."""
    r = log_returns(db)
    regions = universe.set_index("ticker")["region"].to_dict()
    ar = pd.DataFrame(index=r.index, columns=r.columns, dtype="float64")
    betas = {}
    groups = {}
    for c in r.columns:
        groups.setdefault(BENCH_BY_REGION.get(regions.get(c), "SPY"), []).append(c)
    for bench_sym, members in groups.items():
        if bench_sym not in r:
            continue
        b = r[bench_sym]
        cols = [c for c in members if c != bench_sym]
        if bench_sym == "BTC-USD":
            ar[bench_sym] = b                                        # BTC = trh krypta
        if not cols:
            continue
        bv = b.rolling(window, min_periods=60).var()
        cov = r[cols].rolling(window, min_periods=60).cov(b)
        beta = (0.67 * cov.div(bv, axis=0) + 0.33).clip(0, 2.5).shift(1)    # jen minulá info
        ar[cols] = r[cols] - beta.mul(b, axis=0)
        betas[bench_sym] = beta
    return ar, betas
