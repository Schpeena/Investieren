"""Skládání signálů ze všech zdrojů: modely A/B + apriorní hazardy + skandály, s vějířem a vysvětlením."""
import numpy as np
import pandas as pd
from . import forecast, prices as P
from .config import ITEM_CZ, HORIZON, SHOCK_SIGMA
from .learn import datasets, model_a, model_b

BASE_SEV = {"4.02": 8.5, "1.03": 9.0, "3.01": 7.0, "2.04": 7.0, "5.01": 7.0, "1.05": 7.0, "2.06": 5.0, "2.05": 5.0,
            "5.02": 6.5, "2.02": 4.0, "1.01": 3.2, "1.02": 3.5, "2.01": 4.5, "4.01": 4.0, "3.03": 3.0, "3.02": 3.2,
            "2.03": 3.0, "7.01": 3.0, "8.01": 3.0, "5.03": 2.5, "5.07": 2.5, "PS+": 4.5, "PS-": 5.0}
CRITICAL = {"4.02", "1.03", "3.01", "2.04", "1.05", "5.01"}
N_SIM = 4000

class Ctx:
    def __init__(self, uni, db, models_a, model_b, report, events_ds, state, quote_fn=None,
                 cdb=None, model_c=None, crypto_ds=None):
        self.uni, self.db, self.A, self.B, self.report, self.ds, self.state = uni, db, models_a, model_b, report, events_ds, state
        self.meta = uni.set_index("ticker")
        tail = db.tail(420)
        ar, betas = P.abnormal(tail, uni)
        self.ar, self.betas = ar, betas
        self.panel = datasets.Panel(tail, ar)
        # --- krypto: vlastní kalendářní tabulka, model C a benchmark BTC ---
        self.cdb = cdb if cdb is not None else pd.DataFrame()
        self.C, self.dsc = model_c, crypto_ds
        self.arc, self.cpanel = pd.DataFrame(), None
        if not self.cdb.empty:
            ctail = self.cdb.tail(500)
            self.arc, cb = P.abnormal(ctail, uni[uni["region"].eq("CRYPTO")])
            self.betas.update(cb)
            self.cpanel = datasets.Panel(ctail, self.arc, bench="BTC-USD")
        self.quote_fn = quote_fn
        self.baskets = None
        self.spread = {}          # kalibrace šířky vějíře (evaluate.calibration), klíč "stock:8k" apod.

    def region(self, t):
        return self.meta.loc[t, "region"] if t in self.meta.index else "US"

    def is_crypto(self, t):
        return self.region(t) == "CRYPTO"

    def bench_sym(self, t):
        return P.BENCH_BY_REGION.get(self.region(t), "SPY")

    def frame(self, t):
        return self.cdb if self.is_crypto(t) else self.db

    def beta(self, t):
        sym = self.bench_sym(t)
        if t == sym:
            return 0.0            # BTC: abnormální výnos = celý výnos, tržní složku nepřičítat podruhé
        b = self.betas.get(sym)
        if b is not None and t in b.columns and b[t].notna().any():
            return float(b[t].dropna().iloc[-1])
        return 1.0

    def bench_vol(self, t):
        crypto = self.is_crypto(t)
        s = self.frame(t).get(self.bench_sym(t))
        if s is None:
            return 0.035 if crypto else 0.011
        r = np.log(s.dropna()).diff().dropna().tail(250)
        return float(r.std()) if len(r) > 30 else (0.035 if crypto else 0.011)

    def close(self, t):
        s = self.frame(t)[t].dropna()
        if self.quote_fn:
            q = self.quote_fn(t)
            if q:
                ts = pd.Timestamp(q["time"])
                d = ts.tz_localize(None).normalize() if ts.tzinfo is None else ts.tz_convert(None).normalize()
                s = s.copy()
                s.loc[max(d, s.index[-1])] = q["price"]
        return s

    def panel_of(self, t):
        return self.cpanel if self.is_crypto(t) else self.panel

    def ar_of(self, t):
        return self.arc if self.is_crypto(t) else self.ar

def _calibrate(ctx, t, endpoint, kind):
    """Rozšíří/zúží vějíř podle vlastní historie trefování (evaluate.py); do 40 uzavřených signálů beze změny."""
    m = ctx.spread.get(("crypto:" if ctx.is_crypto(t) else "stock:") + kind)
    if not m or abs(m - 1.0) < 0.02:
        return endpoint
    med = np.median(endpoint)
    return med + m * (endpoint - med)

def _fan(ctx, t, endpoint, key, kind="x"):
    endpoint = _calibrate(ctx, t, endpoint, kind)
    return forecast.fan(ctx.close(t), endpoint, beta=ctx.beta(t), bench_vol=ctx.bench_vol(t), key=key, n=N_SIM,
                        cal=ctx.is_crypto(t))

def _analogs_8k(ctx, t, primary, limit=4):
    ds = ctx.dsc if ctx.is_crypto(t) else ctx.ds
    if ds is None or ds.empty:
        return []
    sector = ctx.meta.loc[t, "sector"] if t in ctx.meta.index else ""
    own = ds[(ds["ticker"] == t) & (ds["primary"] == primary) & ds["y20"].notna()].tail(3)
    peer = ds[(ds["sector"] == sector) & (ds["primary"] == primary) & (ds["ticker"] != t) & ds["y20"].notna()].tail(limit - len(own))
    out = []
    for r in pd.concat([own, peer]).itertuples():
        out.append({"date": str(r.date)[:10], "desc": f"{r.ticker}: {ITEM_CZ.get(r.primary, r.primary)}",
                    "car20": float(r.y20 * r.vol * np.sqrt(20)), "path": None})
    return out

def company_signal(ctx, t, items, title, link, kind, extra_sev=0.0, evid=""):
    crypto = ctx.is_crypto(t)
    model, panel = (ctx.C, ctx.cpanel) if crypto else (ctx.A, ctx.panel)
    if panel is None or t not in ctx.frame(t).columns or model is None:
        return None
    items = [x for x in items if x != "9.01"]
    prim = datasets.primary_item(items)
    if prim is None:
        return None
    f = panel.features_at(t, len(panel.idx))
    if f is None:
        return None
    shock_z = 0.0
    if prim.startswith("PS"):
        a = panel.ar[t].dropna()
        shock_z = float(a.iloc[-1] / panel.vol[t].values[-1]) if len(a) else 0.0
    row = pd.DataFrame([{"ticker": t, "primary": prim, "items": ",".join(items), "shock_z": shock_z,
                         "is_shock": int(prim.startswith("PS")), "sector": ctx.meta.loc[t, "sector"],
                         "region_us": int(ctx.region(t) != "EU"), **f}])
    zq = model_a.predict(model, row)[0]
    choice = model["choice"].get(prim, "global")
    rep = (ctx.report.get("C" if crypto else "A") or {}).get("items", {}).get(prim, {})
    scale = f["vol"] * np.sqrt(HORIZON)
    rng = np.random.default_rng(forecast.seed_of(evid + t))
    endpoint = forecast.sample_quantiles(zq, N_SIM, rng) * scale
    fan = _fan(ctx, t, endpoint, evid + t, kind=kind)
    med = float(zq[3] * scale)
    width_ok = choice != "global" or rep.get("active", False)
    dir_ok = bool(rep.get("direction_verified")) and choice != "global"
    sev = BASE_SEV.get(prim, 3.0) + 3.0 * min(1.0, abs(zq[3]) / 0.5) + extra_sev
    return {"id": f"{evid}-{t}", "ticker": t, "name": ctx.meta.loc[t, "name"], "sector": ctx.meta.loc[t, "sector"],
            "kind": kind, "asset": "crypto" if crypto else "stock", "beta": round(ctx.beta(t), 3), "bench": ctx.bench_sym(t),
            "type_label": ITEM_CZ.get(prim, prim), "title": title, "link": link, "severity": round(sev, 2),
            "model": choice, "width_verified": bool(width_ok), "direction_verified": dir_ok,
            "confidence": "vyšší" if (width_ok and dir_ok) else ("střední" if width_ok else "nízká"),
            "critical": prim in CRITICAL, "direction": 1 if med > 0 else -1,
            "stats": {"med20": med, "p5": float(zq[0] * scale), "p95": float(zq[-1] * scale),
                      "n_hist": int(rep.get("n", 0)), "hit": rep.get("hit_rate_dir"),
                      "improvement": rep.get("improvement")},
            "analogs": _analogs_8k(ctx, t, prim), "fan": fan, "drivers": None}

def basket_members(ctx, name):
    if ctx.baskets is None:
        from . import universe
        ctx.baskets = {**universe.baskets(ctx.uni), **universe.crypto_baskets(ctx.uni)}
    cols = ctx.arc.columns if name.startswith("crypto:") else ctx.ar.columns
    return [m for m in ctx.baskets.get(name, []) if m in cols]

def world_signals(ctx, feats, title, link, evid, max_per_basket=4):
    if ctx.B is None or not ctx.B.get("active"):
        return []
    res = model_b.predict_live(ctx.B, feats)
    maxz = max(abs(z) for _, z in res["top_features"]) if res["top_features"] else 0
    out = []
    if maxz < 2.0:
        return out
    drivers = [{"feature": f, "z": round(float(z), 2)} for f, z in res["top_features"]]
    for b, v in res["baskets"].items():
        q = np.array(v["q"])
        if abs(q[3]) < 0.01 and (q[-1] - q[0]) < 0.08:
            continue
        mem = basket_members(ctx, b)
        if not mem:
            continue
        arf = ctx.arc if b.startswith("crypto:") else ctx.ar
        bar = arf[mem].mean(axis=1).tail(250)
        scored = []
        for m in mem:
            a = arf[m].tail(250)
            ok = a.notna() & bar.notna()
            if ok.sum() < 100:
                continue
            c = np.corrcoef(a[ok], bar[ok])[0, 1]; beta = np.cov(a[ok], bar[ok])[0, 1] / np.var(bar[ok])
            scored.append((m, float(np.clip(0.5 * beta + 0.5, 0, 2.5)), float(a[ok].std() * np.sqrt(1 - c ** 2)), c))
        scored = sorted([s for s in scored if s[3] > 0.2], key=lambda s: -s[3])[:max_per_basket]
        for m, beta_b, idio, _ in scored:
            rng = np.random.default_rng(forecast.seed_of(evid + b + m))
            basket_eff = forecast.sample_quantiles(q, N_SIM, rng)
            endpoint = beta_b * basket_eff + rng.standard_t(5, N_SIM) * 0.775 * idio * np.sqrt(HORIZON)
            fan = _fan(ctx, m, endpoint, evid + m, kind="world")
            med = float(np.median(endpoint))
            sev = 3.5 + 1.0 * min(maxz - 2.0, 3.0) + 20.0 * min(abs(q[3]), 0.1)
            info = v["info"]
            out.append({"id": f"{evid}-{b}-{m}", "ticker": m, "name": ctx.meta.loc[m, "name"],
                        "sector": ctx.meta.loc[m, "sector"], "kind": "world", "asset": "crypto" if b.startswith("crypto:") else "stock",
                        "beta": round(ctx.beta(m), 3), "bench": ctx.bench_sym(m), "type_label": "Stav světa (GDELT)",
                        "title": title, "link": link, "severity": round(sev, 2), "model": "knn",
                        "width_verified": True, "direction_verified": bool(info.get("direction_verified")),
                        "confidence": "vyšší" if info.get("direction_verified") else "střední", "critical": False,
                        "direction": 1 if med > 0 else -1, "basket": b,
                        "stats": {"med20": med, "p5": float(np.percentile(endpoint, 5)),
                                  "p95": float(np.percentile(endpoint, 95)), "n_hist": info["n_anomaly"],
                                  "hit": info.get("hit_rate_dir"), "improvement": info["improvement_anomaly"]},
                        "analogs": [{"date": d, "desc": f"podobný den světa → {b.split(':')[1]}", "car20": float(c), "path": None}
                                    for d, c in zip(res["analog_dates"][:4], v["analog_car"][:4])],
                        "fan": fan, "drivers": drivers})
    return out

def prior_signals(ctx, haz):
    """Hazardy (zemětřesení, cyklóny, ohniska): apriorní efekt, výslovně neověřeno."""
    out = []
    for h in haz:
        for b, eff in h["prior"].items():
            mem = basket_members(ctx, b)[:3] if not b.startswith("ticker:") else []
            for m in mem:
                rng = np.random.default_rng(forecast.seed_of(h["id"] + m))
                endpoint = rng.normal(eff, 0.06, N_SIM)
                fan = _fan(ctx, m, endpoint, h["id"] + m, kind="hazard")
                out.append({"id": f"{h['id']}-{m}", "ticker": m, "name": ctx.meta.loc[m, "name"],
                            "sector": ctx.meta.loc[m, "sector"], "kind": "hazard", "asset": "stock", "beta": round(ctx.beta(m), 3),
                            "bench": ctx.bench_sym(m), "type_label": "Přírodní/zdravotní událost",
                            "title": h["title"], "link": h["link"], "severity": round(h["severity"], 2), "model": "prior",
                            "width_verified": False, "direction_verified": False, "confidence": "nízká", "critical": False,
                            "direction": 1 if eff > 0 else -1, "basket": b,
                            "stats": {"med20": float(eff), "p5": float(np.percentile(endpoint, 5)),
                                      "p95": float(np.percentile(endpoint, 95)), "n_hist": 0, "hit": None, "improvement": None},
                            "analogs": [], "fan": fan, "drivers": None})
    return out

def scandal_signals(ctx, scandals, recent_502):
    out = []
    for t, s in scandals.items():
        if t not in ctx.db.columns:
            continue
        sev_x = 0.4 * (len(s["sources"]) - 1) + 0.3 * s["score"]
        if t in recent_502:       # titulek + 8-K 5.02: použij model A
            sig = company_signal(ctx, t, ["5.02"], "Titulky: " + s["headline"], s["link"], "scandal", extra_sev=1.5 + sev_x, evid="sc" + t)
            if sig:
                sig["type_label"] = "Skandál/krize firmy + 8-K 5.02"
                out.append(sig)
            continue
        rng = np.random.default_rng(forecast.seed_of("sc" + t))
        endpoint = rng.normal(-0.04, 0.09, N_SIM)        # apriorní předpoklad, žádný natrénovaný model
        out.append({"id": f"sc-{t}", "ticker": t, "name": ctx.meta.loc[t, "name"], "sector": ctx.meta.loc[t, "sector"],
                    "kind": "scandal", "asset": "stock", "beta": round(ctx.beta(t), 3), "bench": ctx.bench_sym(t),
                    "type_label": "Skandál/krize firmy (zatím bez 8-K)", "title": "Titulky: " + s["headline"],
                    "link": s["link"], "severity": round(3.5 + sev_x, 2), "model": "prior", "width_verified": False,
                    "direction_verified": False, "confidence": "nízká", "critical": False, "direction": -1,
                    "stats": {"med20": -0.04, "p5": float(np.percentile(endpoint, 5)), "p95": float(np.percentile(endpoint, 95)),
                              "n_hist": 0, "hit": None, "improvement": None},
                    "analogs": [], "fan": _fan(ctx, t, endpoint, "sc" + t, kind="scandal"), "drivers": None})
    return out


def _top_members(ctx, basket, k=2):
    """Členové koše s nejvyšší korelací k průměru koše (kandidáti pro signál)."""
    mem = basket_members(ctx, basket)
    if not mem:
        return []
    arf = ctx.arc if basket.startswith("crypto:") else ctx.ar
    bar = arf[mem].mean(axis=1).tail(250)
    sc = []
    for m in mem:
        a = arf[m].tail(250); ok = a.notna() & bar.notna()
        if ok.sum() < 100:
            continue
        sc.append((float(np.corrcoef(a[ok], bar[ok])[0, 1]), m))
    return [m for _, m in sorted(sc, reverse=True)[:k]]

def influencer_signals(ctx, events, verified_kinds=()):
    """Příspěvky/zmínky vlivných osob. Apriorní efekt (znaménko z tématu/tónu); neověřeno, dokud to nepotvrdí vlastní vyhodnocení."""
    out, done = [], set()
    for ev in events:
        targets = [t for t in ev["tickers"] if t in ctx.meta.index and t in ctx.frame(t).columns]
        for b in ev["targets"]:
            targets += _top_members(ctx, b, 2)
        for m in dict.fromkeys(targets):
            if (ev["id"], m) in done:
                continue
            done.add((ev["id"], m))
            crypto = ctx.is_crypto(m)
            close = ctx.close(m)
            sig = forecast.daily_vol(close)
            eff = ev["sign"] * ev["effect"] * (0.7 + 0.15 * ev["weight"])
            rng = np.random.default_rng(forecast.seed_of(ev["id"] + m))
            endpoint = rng.normal(eff, 0.8 * sig * np.sqrt(HORIZON), N_SIM)
            asset = "crypto" if crypto else "stock"
            ver = f"{asset}:influencer" in verified_kinds
            n_src = len(ev["sources"])
            sev = 3.0 + 0.6 * ev["weight"] + 0.5 * (min(n_src, 4) - 1)
            sev = sev + 1.5 if ver else min(sev, 5.8)
            out.append({"id": f"{ev['id']}-{m}", "ticker": m, "name": ctx.meta.loc[m, "name"], "sector": ctx.meta.loc[m, "sector"],
                        "kind": "influencer", "asset": asset, "beta": round(ctx.beta(m), 3), "bench": ctx.bench_sym(m),
                        "type_label": f"Vlivná osoba – {ev['topic']}", "title": f"{ev['person']}: {ev['text'][:140]}",
                        "link": ev["link"], "severity": round(sev, 2), "model": "prior", "width_verified": False,
                        "direction_verified": ver, "confidence": "střední" if ver else "nízká", "critical": False,
                        "direction": 1 if eff > 0 else -1,
                        "stats": {"med20": float(np.median(endpoint)), "p5": float(np.percentile(endpoint, 5)),
                                  "p95": float(np.percentile(endpoint, 95)), "n_hist": 0, "hit": None, "improvement": None},
                        "analogs": [], "drivers": None,
                        "evidence": {"person": ev["person"], "category": ev["category"], "sources": sorted(ev["sources"]), "tone": ev["tone"]},
                        "fan": _fan(ctx, m, endpoint, ev["id"] + m, kind="influencer")})
    return out

def finalize_stats(ctx, s):
    """Uloží surovou statistiku modelu (pro log/kalibraci) a zobrazovanou statistiku přepočte kalibračním násobkem šířky."""
    s["stats_raw"] = dict(s["stats"])
    m = ctx.spread.get(f"{s.get('asset', 'stock')}:{s['kind']}")
    if m and abs(m - 1.0) >= 0.02:
        st, med = s["stats"], s["stats"]["med20"]
        st["p5"] = med + m * (st["p5"] - med); st["p95"] = med + m * (st["p95"] - med)
        s["calibrated"] = m
