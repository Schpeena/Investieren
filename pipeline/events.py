"""Nadcházející události firem (výsledky, výroční/čtvrtletní zprávy, podklady k valné hromadě).
Zdroje podle spolehlivosti:
  1. POTVRZENÉ termíny z Finnhubu (jen pro sledované symboly; vlastní klíč FINNHUB_KEY, free plán – pokrytí mimo USA neověřeno)
  2. ODHADY ze SEC historie: příští termín = loňský termín stejného období + 364 dní (zachová den v týdnu); u každého odhadu je
     zpětně spočtená typická odchylka v dnech. Jen firmy s CIK (USA, ADR). Evropa bez klíče: bez předem známých termínů
     -> v aplikaci si je přidáš ručně (ukládají se v telefonu, s exportem do kalendáře .ics).
Navíc: typická reakce ceny při výsledcích z vlastní historie 8-K položky 2.02 (medián |abnormálního pohybu|)."""
import json, os
import numpy as np
import pandas as pd
from . import http
from .config import CACHE, SITE_DATA
from .sources import edgar

EVENTS_FILE = CACHE / "events.json"
FINNHUB_KEY = os.environ.get("FINNHUB_KEY") or ""
HORIZON_DAYS = 200                     # jak daleko dopředu události ukazujeme
PERIOD = 364

LABEL = {"earnings": "Výsledky hospodaření", "10-K": "Výroční zpráva (10-K)", "10-Q": "Čtvrtletní zpráva (10-Q)",
         "20-F": "Výroční zpráva (20-F)", "40-F": "Výroční zpráva (40-F)", "DEF 14A": "Podklady k valné hromadě (DEF 14A)"}

# ------------------------------------------------------------------ odhad příštího termínu
def estimate_next(dates, today, period=PERIOD):
    """dates: minulé termíny téhož typu. Vrací (datum, typická odchylka ve dnech, n) nebo None.
    Kandidáti = minulé termíny + k·364 dní; vezme se nejbližší po dnešku a po poslední skutečnosti (min. 25 dní)."""
    ds = sorted({pd.Timestamp(d).normalize() for d in dates if pd.notna(d)})
    if len(ds) < 2:
        return None
    today = pd.Timestamp(today).normalize()
    last = ds[-1]
    floor = max(today, last + pd.Timedelta(days=25))
    recent = [d for d in ds if d >= last - pd.Timedelta(days=3 * 365)]
    cands = sorted({d + pd.Timedelta(days=period * k) for d in recent for k in (1, 2, 3)} )
    cands = [c for c in cands if c >= floor and (c - today).days <= HORIZON_DAYS + 30]
    if not cands:
        return None
    nxt = cands[0]
    # zpětný test: jak přesně loňský termín (+364 d) trefil skutečný termín v dalším období
    errs = []
    for d in ds:
        prev = [p + pd.Timedelta(days=period) for p in ds if 300 <= (d - p).days <= 430]
        if prev:
            errs.append(min(abs((d - q).days) for q in prev))
    err = int(np.median(errs)) if errs else 7
    return nxt, max(err, 1), len(ds)

def _ds(df, form=None, items=None):
    if df is None or df.empty:
        return []
    if form:
        return list(pd.to_datetime(df[df["form"].eq(form)]["filed"]))
    return list(pd.to_datetime(df["date"]))

def earnings_dates(e8k_cik):
    """Data 8-K s položkou 2.02 (Results of Operations) jedné firmy."""
    if e8k_cik is None or e8k_cik.empty:
        return []
    m = e8k_cik["items"].fillna("").map(lambda s: "2.02" in edgar.items_of(s))
    return list(pd.to_datetime(e8k_cik[m]["date"]))

def for_cik(cik, e8k, per, today):
    out = []
    e = estimate_next(earnings_dates(e8k.get(cik)), today)
    if e:
        out.append({"date": e[0].strftime("%Y-%m-%d"), "type": "earnings", "title": LABEL["earnings"] + " (odhad)",
                    "confirmed": False, "src": f"odhad z {e[2]} předchozích termínů SEC (±{e[1]} d)", "err": e[1]})
    p = per.get(cik)
    if p is not None and not p.empty:
        for form in ("10-Q", "10-K", "20-F", "DEF 14A"):
            est = estimate_next(_ds(p, form), today)
            if est:
                out.append({"date": est[0].strftime("%Y-%m-%d"), "type": form, "title": LABEL[form] + " (odhad)",
                            "confirmed": False, "src": f"odhad z {est[2]} podání na SEC (±{est[1]} d)", "err": est[1]})
    return out

# ------------------------------------------------------------------ potvrzené termíny (Finnhub)
HOUR = {"bmo": "před otevřením trhu", "amc": "po zavření trhu", "dmh": "během obchodování"}

def parse_finnhub(js, symbol_map=None):
    out = []
    for r in js.get("earningsCalendar", []) or []:
        sym = str(r.get("symbol", "")).upper()
        if not r.get("date"):
            continue
        extra = []
        if r.get("hour") in HOUR:
            extra.append(HOUR[r["hour"]])
        if r.get("epsEstimate") is not None:
            extra.append(f"odhad EPS {r['epsEstimate']}")
        q = f" Q{r['quarter']}/{r['year']}" if r.get("quarter") and r.get("year") else ""
        out.append((sym, {"date": r["date"], "type": "earnings", "title": f"{LABEL['earnings']}{q}" + (f" ({', '.join(extra)})" if extra else ""),
                          "confirmed": True, "src": "Finnhub", "err": 0}))
    return out

def finnhub_confirmed(symbols, today, days=HORIZON_DAYS):
    if not FINNHUB_KEY:
        return {}
    res = {}
    frm = pd.Timestamp(today).strftime("%Y-%m-%d")
    to = (pd.Timestamp(today) + pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    for sym in symbols:
        try:
            txt = http.get(f"https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}&symbol={sym}&token={FINNHUB_KEY}", "finnhub")
            for s, ev in parse_finnhub(json.loads(txt)):
                res.setdefault(s or sym, []).append(ev)
        except Exception as e:
            print(f"[events] Finnhub {sym}: {str(e)[:80]}")
    return res

def merge(estimated, confirmed):
    """Potvrzený termín nahradí odhad stejného typu do ±30 dní."""
    out = [e for e in estimated if not any(c["type"] == e["type"] and abs((pd.Timestamp(c["date"]) - pd.Timestamp(e["date"])).days) <= 30 for c in confirmed)]
    return sorted(out + confirmed, key=lambda e: e["date"])

# ------------------------------------------------------------------ typická reakce při výsledcích
def typical_moves(ds):
    """Z natrénovaného datasetu: medián |abnormálního pohybu| 1 a 5 dní po zveřejnění výsledků (8-K 2.02), v % (log)."""
    if ds is None or len(ds) == 0:
        return {}
    d = ds[ds["items"].fillna("").str.split(",").map(lambda x: "2.02" in x)]
    out = {}
    for t, g in d.groupby("ticker"):
        g = g.dropna(subset=["y1", "y5"])
        if len(g) >= 4:
            out[t] = {"n": int(len(g)), "m1": round(float((g["y1"].abs() * g["vol"]).median()), 4),
                      "m5": round(float((g["y5"].abs() * g["vol"] * np.sqrt(5)).median()), 4)}
    return out

# ------------------------------------------------------------------ sestavení
def build(uni, e8k, per, ds, watch_symbols, today, confirmed=None):
    e8k_by = {c: g for c, g in e8k.groupby("cik")} if e8k is not None and not e8k.empty else {}
    per_by = {c: g for c, g in per.groupby("cik")} if per is not None and not per.empty else {}
    confirmed = confirmed or {}
    by, last = {}, {}
    for r in uni.itertuples():
        est = for_cik(r.cik, e8k_by, per_by, today) if r.cik else []
        ev = merge(est, confirmed.get(r.ticker, []))
        ev = [x for x in ev if 0 <= (pd.Timestamp(x["date"]) - pd.Timestamp(today)).days <= HORIZON_DAYS]
        if ev:
            by[r.ticker] = ev
        if r.cik and r.cik in e8k_by:
            ed = earnings_dates(e8k_by[r.cik])
            if ed:
                last[r.ticker] = max(ed).strftime("%Y-%m-%d")
    for t, evs in confirmed.items():                    # potvrzené termíny i pro tickery bez CIK (Evropa)
        if t not in by:
            by[t] = sorted(evs, key=lambda e: e["date"])
    return {"asof": pd.Timestamp(today).strftime("%Y-%m-%d"), "finnhub": bool(FINNHUB_KEY), "by_ticker": by,
            "last_earnings": last, "typical": typical_moves(ds)}

def rebuild(uni, watch_symbols):
    """Načte data z CACHE, postaví events.json (CACHE i SITE_DATA)."""
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    e8k, per = edgar.load(), edgar.load_periodic()
    ds_path = CACHE / "events_dataset.parquet"
    ds = pd.read_parquet(ds_path) if ds_path.exists() else None
    conf = finnhub_confirmed(watch_symbols, today)
    out = build(uni, e8k, per, ds, watch_symbols, today, conf)
    EVENTS_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"[events] tickerů s termíny: {len(out['by_ticker'])}, potvrzených (Finnhub): {sum(len(v) for v in conf.values())}")
    return out
