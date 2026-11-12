"""Vyhodnocení signálů: každý zobrazený signál se zaloguje, po horizontu (H pozorování), po ~1 a ~3 měsících se
porovná predikce se skutečností. Z toho: (1) notifikace 'uzavření signálu', (2) statistika trefování podle druhu signálu,
(3) kalibrace šířky vějíře (spread multiplier), (4) ověření směru pro zdroje bez historie (např. influenceři)."""
import json
import numpy as np
import pandas as pd
from .config import CACHE, HORIZON

LOG_FILE = CACHE / "signal_log.json"
LEVELS = np.array([0.05, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95])
ONE_MONTH, THREE_MONTHS = 30, 91           # kalendářních dní od data signálu
MIN_N_CALIBRATE, MIN_N_VERIFY = 40, 30
MAX_LOG = 6000

# ------------------------------------------------------------------ log
def load_log(path=LOG_FILE):
    return json.load(open(path)) if path.exists() else []

def save_log(log, path=LOG_FILE):
    log = log[-MAX_LOG:]
    json.dump(log, open(path, "w"), default=float, separators=(",", ":"))
    return log

def record(log, sigs, notified_ids, now):
    """Zaloguje nové signály (dedup podle id), označí odeslané notifikace. Ukládá RAW statistiku modelu (před kalibrací)."""
    have = {e["id"]: e for e in log}
    new = 0
    for s in sigs:
        e = have.get(s["id"])
        if e is None:
            st = s.get("stats_raw") or s["stats"]
            e = {"id": s["id"], "ticker": s["ticker"], "name": s["name"], "asset": s.get("asset", "stock"),
                 "kind": s["kind"], "model": s["model"], "confidence": s["confidence"], "label": s["type_label"],
                 "title": s["title"][:140], "link": s.get("link") or "", "direction": s["direction"],
                 "med": st["med20"], "p5": st["p5"], "p95": st["p95"], "beta": s.get("beta", 1.0),
                 "bench": s.get("bench", "SPY"), "date": s["fan"]["spot_date"], "spot": s["fan"]["spot"],
                 "q": s["fan"]["end_pct"], "created": now.isoformat(), "notified": False, "sent1": None, "sent3": None}
            log.append(e); have[e["id"]] = e; new += 1
        if s["id"] in notified_ids:
            e["notified"] = True
    return new

# ------------------------------------------------------------------ výsledky
def _exit_price(s, d0, mode):
    """mode 'h' = H-té pozorování po d0, mode 'm3' = poslední cena k d0+91 dnům. Vrací (datum, cena) nebo None (data ještě nejsou)."""
    s = s.dropna()
    if s.empty:
        return None
    i0 = s.index.searchsorted(d0)
    if mode == "h":
        j = i0 + HORIZON
        return (s.index[j], float(s.iloc[j])) if j < len(s) else None
    end = d0 + pd.Timedelta(days=THREE_MONTHS)
    if s.index[-1] < end:
        return None
    sub = s.loc[:end]
    return (sub.index[-1], float(sub.iloc[-1]))

def _bench_ret(b, d0, d1):
    if b is None:
        return 0.0
    b = b.dropna()
    try:
        return float(b.asof(d1) / b.asof(d0) - 1)
    except Exception:
        return 0.0

def _result(e, kind, s, b):
    d0 = pd.Timestamp(e["date"])
    ex = _exit_price(s, d0, kind)
    if ex is None:
        return None
    d1, px = ex
    ret = px / e["spot"] - 1
    bret = _bench_ret(b, d0, d1)
    abn = float(np.log1p(ret) - e["beta"] * np.log1p(bret))
    out = {"date": d1.strftime("%Y-%m-%d"), "price": round(px, 6), "ret": round(float(ret), 4),
           "bench_ret": round(bret, 4), "abn": round(abn, 4)}
    if kind == "h":
        qv = np.array([e["q"][k] for k in ("5", "20", "35", "50", "65", "80", "95")])
        out["pit"] = round(float(np.interp(ret, qv, LEVELS, left=0.02, right=0.98)), 3)
        out["inside90"] = bool(qv[0] <= ret <= qv[-1])
        out["hit"] = bool(np.sign(abn) == e["direction"]) if abs(abn) > 1e-9 else None
        half = (e["p95"] - e["p5"]) / 2
        out["u"] = round(float(abs(abn - e["med"]) / half), 3) if half > 0 else None
    return out

def update_outcomes(log, db, cdb, today):
    """Doplní h (horizont), m3 (3 měsíce) a vrátí seznam notifikací, které jsou splatné."""
    due = []
    for e in log:
        frame = cdb if e["asset"] == "crypto" else db
        if frame is None or frame.empty or e["ticker"] not in frame.columns:
            continue
        s, b = frame[e["ticker"]], frame.get(e["bench"])
        age = (today - pd.Timestamp(e["date"])).days
        if "h" not in e and age >= HORIZON:
            r = _result(e, "h", s, b)
            if r:
                e["h"] = r
        if "m3" not in e and age >= THREE_MONTHS:
            r = _result(e, "m3", s, b)
            if r:
                e["m3"] = r
        if e.get("notified"):
            if "h" in e and not e["sent1"] and age >= ONE_MONTH:
                due.append((e, "1m"))
            if "m3" in e and not e["sent3"] and age >= THREE_MONTHS:
                due.append((e, "3m"))
    return due

# ------------------------------------------------------------------ zprávy
def _pct(x, d=1):
    return f"{x * 100:+.{d}f} %".replace(".", ",").replace("-", "−")

def _dm(date):
    d = pd.Timestamp(date)
    return f"{d.day}. {d.month}."

def message(e, which):
    arrow = "▲" if e["direction"] > 0 else "▼"
    h = e["h"]
    vs = "BTC" if e["asset"] == "crypto" else "trh"
    if which == "1m":
        title = f"✔ Uzavření signálu (1 měsíc): {arrow} {e['ticker']}"
        ok = "✔ směr trefen" if h.get("hit") else ("✘ směr netrefen" if h.get("hit") is False else "směr nelze určit")
        band = "uvnitř 90% pásma" if h.get("inside90") else "MIMO 90% pásmo"
        body = (f"Signál z {_dm(e['date'])}: {e['label']}.\n"
                f"Odhad vs {vs}: {_pct(e['med'])} [{_pct(e['p5'], 0)} až {_pct(e['p95'], 0)}].\n"
                f"Skutečnost k {_dm(h['date'])} ({HORIZON} pozorování): {_pct(h['ret'])} (vs {vs} {_pct(h['abn'])}).\n"
                f"{ok}, {band}. Statistický test, ne rada.")
    else:
        m3, h = e["m3"], e["h"]
        persist = "efekt přetrval" if np.sign(m3["abn"]) == np.sign(h["abn"]) and abs(m3["abn"]) >= 0.5 * abs(h["abn"]) else \
            ("efekt odezněl/obrátil se" if np.sign(m3["abn"]) != np.sign(h["abn"]) else "efekt zeslábl")
        title = f"✔ Uzavření signálu (3 měsíce): {arrow} {e['ticker']}"
        body = (f"Signál z {_dm(e['date'])}: {e['label']}.\n"
                f"Po 3 měsících ({_dm(m3['date'])}): {_pct(m3['ret'])} (vs {vs} {_pct(m3['abn'])}); po horizontu byl výsledek {_pct(h['abn'])} → {persist}.\n"
                f"Původní odhad vs {vs}: {_pct(e['med'])}.")
    return title, body

# ------------------------------------------------------------------ statistika a kalibrace
def _group_stats(es):
    n = len(es)
    dirs = [e["h"]["hit"] for e in es if e["h"].get("hit") is not None]
    nd = len(dirs)
    hit = float(np.mean(dirs)) if nd else None
    z = (hit - 0.5) * np.sqrt(nd) / 0.5 if nd else 0.0
    pits = [e["h"]["pit"] for e in es]
    m3 = [e for e in es if "m3" in e]
    return {"n": n, "n_dir": nd, "hit": hit, "z": round(float(z), 2),
            "coverage90": float(np.mean([e["h"]["inside90"] for e in es])) if n else None,
            "pit_mean": round(float(np.mean(pits)), 3) if pits else None,
            "mean_abn_in_dir": round(float(np.mean([e["direction"] * e["h"]["abn"] for e in es])), 4) if n else None,
            "n3": len(m3), "mean_abn_in_dir_3m": round(float(np.mean([e["direction"] * e["m3"]["abn"] for e in m3])), 4) if m3 else None,
            "verified": bool(nd >= MIN_N_VERIFY and hit is not None and hit >= 0.55 and z >= 2.0)}

def summarize(log):
    """Souhrn pro frontend: celkem, podle druhu (asset:kind), podle jistoty modelu + posledních 40 uzavřených."""
    closed = [e for e in log if "h" in e]
    out = {"n_logged": len(log), "n_closed": len(closed), "n_notified": sum(1 for e in log if e.get("notified")),
           "overall": _group_stats(closed) if closed else None, "by_kind": {}, "by_confidence": {}, "recent": []}
    groups, conf = {}, {}
    for e in closed:
        groups.setdefault(f"{e['asset']}:{e['kind']}", []).append(e)
        conf.setdefault(e["confidence"], []).append(e)
    out["by_kind"] = {k: _group_stats(v) for k, v in groups.items()}
    out["by_confidence"] = {k: _group_stats(v) for k, v in conf.items()}
    for e in sorted(closed, key=lambda e: e["h"]["date"], reverse=True)[:40]:
        out["recent"].append({"id": e["id"], "ticker": e["ticker"], "name": e["name"], "kind": e["kind"], "asset": e["asset"],
                              "label": e["label"], "date": e["date"], "direction": e["direction"], "med": e["med"],
                              "p5": e["p5"], "p95": e["p95"], "confidence": e["confidence"], "notified": bool(e.get("notified")),
                              "h": e["h"], "m3": e.get("m3")})
    return out

def spreads(log):
    """Násobič šířky vějíře podle druhu signálu: 90% kvantil |chyba|/(půl-šířka 90% pásma), stažený k 1 podle n."""
    groups = {}
    for e in log:
        if "h" in e and e["h"].get("u") is not None:
            groups.setdefault(f"{e['asset']}:{e['kind']}", []).append(e["h"]["u"])
    out = {}
    for k, us in groups.items():
        n = len(us)
        if n < MIN_N_CALIBRATE:
            continue
        raw = float(np.quantile(us, 0.90))
        m = 1 + (raw - 1) * n / (n + 60)
        out[k] = round(float(np.clip(m, 0.7, 1.6)), 3)
    return out

def verified_kinds(summary):
    """Druhy signálů, jejichž směr se v živém vyhodnocení statisticky potvrdil (n ≥ 30, trefa ≥ 55 %, ~2σ)."""
    return {k for k, v in (summary or {}).get("by_kind", {}).items() if v.get("verified")}
