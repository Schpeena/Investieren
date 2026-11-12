"""Vějířový graf z koncového rozdělení (kvantily modelu) + Brownův most pro průběh + tržní složka."""
import hashlib
import numpy as np
import pandas as pd
from .config import QUANTILES, HORIZON

TAUS = np.array([0.0] + QUANTILES + [1.0])
BANDS = [5, 20, 35, 50, 65, 80, 95]

def seed_of(key):
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)

def sample_quantiles(qv, n, rng):
    qv = np.sort(np.asarray(qv, dtype=float))
    lo = qv[0] - 0.8 * (qv[1] - qv[0]); hi = qv[-1] + 0.8 * (qv[-1] - qv[-2])
    return np.interp(rng.uniform(0, 1, n), TAUS, np.concatenate([[lo], qv, [hi]]))

def daily_vol(close):
    r = np.log(close.dropna()).diff().dropna().values[-750:]
    if len(r) < 60:
        return 0.02
    long = float(np.std(r)); v = long ** 2
    for x in r[-250:]:
        v = 0.94 * v + 0.06 * x * x
    return 0.6 * float(np.sqrt(v)) + 0.4 * long

def fan(close, endpoint_abn, beta=1.0, bench_vol=0.011, H=HORIZON, n=4000, key="x", vol_mult=1.2, df=5, cal=False):
    """endpoint_abn: vzorky abnormálního log-výnosu za H dní (n,) – nebo None (jen základní vějíř)."""
    close = close.dropna(); spot = float(close.iloc[-1]); sig = daily_vol(close)
    rng = np.random.default_rng(seed_of(key))
    scale = np.sqrt((df - 2) / df)
    mkt = rng.standard_t(df, n) * scale * bench_vol * np.sqrt(H)
    drift = 0.0002 * H
    if endpoint_abn is None:
        endpoint = drift + beta * mkt + rng.standard_t(df, n) * scale * sig * np.sqrt(H) * 0.8
        vm = np.ones(H)
    else:
        e = endpoint_abn if len(endpoint_abn) == n else rng.choice(endpoint_abn, n)
        endpoint = drift + beta * mkt + e
        vm = np.linspace(vol_mult, 1.0, H)
    steps = rng.standard_t(df, (n, H)) * scale * sig * vm
    W = np.cumsum(steps, axis=1); W = np.concatenate([np.zeros((n, 1)), W], axis=1)
    t = np.arange(H + 1) / H
    path = endpoint[:, None] * t[None, :] + (W - t[None, :] * W[:, -1:])      # Brownův most k cílovému bodu
    prices = spot * np.exp(path)
    nd = 2 if spot >= 1 else 6                       # malé ceny (krypto) potřebují víc desetinných míst
    q = {str(p): np.percentile(prices, p, axis=0).round(nd).tolist() for p in BANDS}
    rng_dates = pd.date_range(close.index[-1], periods=H + 1) if cal else pd.bdate_range(close.index[-1], periods=H + 1)
    dates = [d.strftime("%Y-%m-%d") for d in rng_dates]
    tt = np.sqrt(np.arange(H + 1))
    z = 1.645 * sig * tt * 1.0
    return {"spot": round(spot, nd), "spot_date": close.index[-1].strftime("%Y-%m-%d"), "dates": dates, "q": q,
            "baseline": (spot * np.exp(0.0002 * np.arange(H + 1))).round(nd).tolist(),
            "base_lo": (spot * np.exp(-z)).round(nd).tolist(), "base_hi": (spot * np.exp(z)).round(nd).tolist(),
            "prob_up": round(float((prices[:, -1] > spot).mean()), 3), "daily_vol": round(sig, 4),
            "end_pct": {k: round(v[-1] / spot - 1, 4) for k, v in q.items()}, "cal": bool(cal)}
