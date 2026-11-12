"""Syntetická data pro test celého řetězce. Vloženo: (1) 8-K 5.02 má záporný drift, 2.02 zvyšuje volatilitu,
(2) po konfliktních špičkách v GDELT roste koš 'industry:Aerospace & Defense' (ostatní koše bez efektu)."""
import numpy as np
import pandas as pd
from . import universe
from .sources import gdelt

def make(seed=11, years=11):
    rng = np.random.default_rng(seed)
    uni = universe.build(offline=True)
    nonEq = uni["region"].isin(["ETF", "CRYPTO"])
    eq = uni[~nonEq].copy()
    eq["cik"] = [str(1000 + i).zfill(10) for i in range(len(eq))]
    uni = pd.concat([eq, uni[nonEq]], ignore_index=True)
    end = pd.Timestamp.today().normalize()
    idx = pd.bdate_range(end - pd.DateOffset(years=years), end)
    n = len(idx)
    spy = rng.standard_t(5, n) * 0.008
    exsa = 0.8 * spy + rng.standard_t(5, n) * 0.004
    rets = {"SPY": spy, "EXSA.DE": exsa}
    # --- GDELT stav světa (podíly) se špičkami ---
    days = pd.date_range(idx[0], idx[-1])
    base = rng.dirichlet(np.ones(20) * 8, len(days))
    feat = {f"r{r}": base[:, k] for k, r in enumerate(gdelt.ROOTS)}
    spike = (rng.random(len(days)) < 0.05).astype(float) * rng.uniform(1, 3, len(days))
    spike = pd.Series(spike).rolling(3, min_periods=1).max().values
    for g in gdelt.HOT:
        for c in gdelt.CLASSES:
            feat[f"h_{g}_{c}"] = rng.gamma(2, 0.002, len(days))
    feat["h_ua_ru_conflict"] = feat["h_ua_ru_conflict"] + spike * 0.02
    feat["tone"] = rng.normal(-2, 0.3, len(days)) - spike
    feat["gold"] = rng.normal(0, 0.3, len(days))
    tot = rng.uniform(5e6, 8e6, len(days))
    daily = pd.DataFrame({k: v * tot for k, v in feat.items()}, index=days)
    daily["tot"] = tot; daily["n"] = tot / 20
    daily = daily.reindex(columns=gdelt.SUM_KEYS).fillna(0.0)
    spike_s = pd.Series(spike, index=days)
    ad_effect = np.zeros(n)
    for d, s in spike_s[spike_s > 1.5].items():
        p = idx.searchsorted(d, side="right")
        ad_effect[p:p + 20] += 0.02 * s / 20 / 2
    # --- 8-K události ---
    items_pool = ["2.02", "5.02", "1.01", "8.01", "7.01", "2.03", "5.07", "4.02", "2.05"]
    pw = np.array([.22, .08, .12, .2, .12, .06, .1, .01, .04]); pw /= pw.sum()
    recs = []
    for _, r in eq.iterrows():
        vol = rng.uniform(0.010, 0.022)
        ar = rng.standard_t(5, n) * vol
        k_ev = rng.poisson(10 * years)
        for d in rng.choice(n - 25, k_ev, replace=False) + 5:
            it = rng.choice(items_pool, p=pw)
            sigma = vol
            if it == "5.02":
                ar[d:d + 20] += -0.6 * sigma * np.sqrt(20) / 20 * 1.0
            if it == "2.02":
                ar[d] += rng.normal(0, 2.5 * sigma)
            hh = 21 if rng.random() < 0.4 else 12
            recs.append({"acc": f"{r['cik']}-{d}", "date": idx[d].strftime("%Y-%m-%d"),
                         "accept": f"{idx[d].strftime('%Y-%m-%d')}T{hh + 5}:30:00.000Z", "form": "8-K",
                         "items": it + ",9.01", "cik": r["cik"]})
            if hh == 21:       # po zavření: reakce až další den -> posuň efekt
                pass
        if r["industry"] == "Aerospace & Defense":
            ar += ad_effect
        beta = rng.uniform(0.7, 1.3)
        rets[r["ticker"]] = (exsa if r["region"] == "EU" else spy) * beta + ar
    for t in uni[uni["region"].eq("ETF")]["ticker"]:
        if t not in rets:
            rets[t] = spy * 0.5 + rng.standard_t(5, n) * 0.01
    R = pd.DataFrame(rets, index=idx)
    P0 = np.exp(R.cumsum())
    prices = (P0 / P0.iloc[-1] * rng.uniform(20, 400, P0.shape[1])).astype("float32")
    return uni, prices, pd.DataFrame(recs), daily

def live(uni, state):
    """Syntetický 'živý' vstup pro test run_fast."""
    from .sources import gdelt
    from .learn import model_b
    eq = uni[uni["cik"].ne("") & uni["region"].eq("US")] if (uni["cik"].ne("") & uni["region"].eq("US")).any() else uni[uni["cik"].ne("")]
    t_a, t_b, t_c = list(eq["ticker"])[:3] if len(eq) >= 3 else list(uni["ticker"])[:3]
    cik = uni.set_index("ticker")["cik"].to_dict()
    filings = [{"acc": "demo-1", "cik": cik[t_a], "items": ["5.02", "9.01"], "link": "https://sec.gov/demo", "company": t_a, "tickers": [t_a]},
               {"acc": "demo-2", "cik": cik[t_b], "items": ["4.02", "9.01"], "link": "https://sec.gov/demo", "company": t_b, "tickers": [t_b]}]
    daily = gdelt.load_daily()
    F = model_b.shares(daily.iloc[-365:]).median()
    feats = F.to_dict()
    feats["h_ua_ru_conflict"] += 0.06
    feats["tone"] -= 3.0
    scand = {t_c: {"ticker": t_c, "score": 8.0, "headline": f"{t_c} CEO resigns amid affair scandal", "link": "https://example.com/demo",
                   "sources": {"bbc.co.uk", "reuters.com"}}}
    haz = [{"kind": "quake", "id": "demo-eq", "title": "Zemětřesení M6.8 – Tchaj-wan (DEMO)", "severity": 6.0,
            "prior": {"industry:Semiconductors": -0.03}, "link": "", "ts": ""}]
    from .sources import social
    ev = social.detect(demo_posts(), social.load_influencers())
    return {"filings": filings, "scandals": scand, "hazards": haz, "gdelt_feats": feats, "gdelt_slots": 96, "headlines": 0,
            "influencer_events": ev}


def make_crypto(uni, daily, seed=5, years=8):
    """Syntetické krypto (kalendářní dny, těžké chvosty). Vložený efekt: po konfliktních špičkách v GDELT klesají altcoiny
    (risk-off), BTC bez efektu -> koš 'crypto:large_alts' má být model B schopen najít."""
    rng = np.random.default_rng(seed)
    coins = list(uni[uni["region"].eq("CRYPTO")]["ticker"])
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    idx = pd.date_range(end - pd.DateOffset(years=years), end)
    n = len(idx)
    btc = rng.standard_t(4, n) * 0.022
    spike = (daily["h_ua_ru_conflict"] / daily["tot"]).reindex(idx)
    sp = (spike > spike.quantile(0.95)).astype(float).values
    eff = np.zeros(n)
    for d in np.where(sp > 0)[0]:
        eff[d + 1:d + 21] += -0.08 / 20
    rets = {"BTC-USD": btc}
    for k, t in enumerate(coins):
        if t == "BTC-USD":
            continue
        beta = rng.uniform(0.8, 1.4)
        ar = rng.standard_t(4, n) * rng.uniform(0.02, 0.035)
        if t != "ETH-USD":
            ar = ar + eff
        rets[t] = beta * btc + ar
    R = pd.DataFrame(rets, index=idx)
    P0 = np.exp(R.cumsum())
    return (P0 / P0.iloc[-1] * rng.uniform(0.5, 3000, P0.shape[1])).astype("float32")

def demo_posts():
    """Syntetické příspěvky pro test detekce vlivných osob (prochází skutečnou funkcí social.detect)."""
    now = pd.Timestamp.now("UTC").isoformat()
    return [{"text": "Great news: Tesla robotaxi launch is a record breakthrough, strong demand", "person": "Elon Musk", "source": "x", "link": "https://x.com/demo/1", "ts": now},
            {"text": "Bitcoin reserve will be great, we support crypto and digital assets", "person": "Michael Saylor", "source": "x", "link": "https://x.com/demo/2", "ts": now},
            {"text": "New tariffs on imports, trade war threat", "person": "Donald Trump", "source": "truth", "link": "https://truth.example/3", "ts": now}]
