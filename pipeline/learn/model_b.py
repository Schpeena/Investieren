"""Model B: analogová (kNN) predikce reakce košů akcií na 'stav světa' z GDELT (CAMEO) + walk-forward test."""
import numpy as np
import pandas as pd
from ..config import QUANTILES, GATE_MIN_IMPROVEMENT
from ..sources import gdelt
from .model_a import pinball

QS = np.array(QUANTILES)
K, GAP_DAYS, H = 40, 5, 20

def shares(daily):
    tot = daily["tot"].clip(lower=1.0)
    F = pd.DataFrame({f: daily[f] / tot for f in gdelt.FEATURES}, index=daily.index)
    return F

def zscores(F):
    mu = F.rolling(365, min_periods=60).mean().shift(1)
    sd = F.rolling(365, min_periods=60).std().shift(1).clip(lower=1e-9)
    return ((F - mu) / sd).clip(-6, 6)

def basket_forward(ar, baskets, gdelt_days):
    """Dopředné kumulativní AR koše (h=20) pro každý den GDELT (první obchodní den PO tomto dni)."""
    cols = {}
    idx = ar.index
    for b, members in baskets.items():
        mem = [m for m in members if m in ar.columns]
        if mem:
            cols[b] = ar[mem].mean(axis=1, skipna=True).fillna(0.0)
    B = pd.DataFrame(cols, index=idx)
    cs = np.vstack([np.zeros((1, B.shape[1])), np.cumsum(B.values, axis=0)])
    pos = idx.searchsorted(gdelt_days, side="right")
    out = np.full((len(gdelt_days), B.shape[1]), np.nan)
    ok = pos + H <= len(idx)
    out[ok] = cs[pos[ok] + H] - cs[pos[ok]]
    return out, list(B.columns)

def neighbors(Zh, z, valid, k=K, gap=GAP_DAYS):
    d = np.sqrt(((Zh - z) ** 2).sum(axis=1))
    d[~valid] = np.inf
    chosen = []
    for j in np.argsort(d):
        if not np.isfinite(d[j]) or len(chosen) >= k:
            break
        if all(abs(j - c) > gap for c in chosen):
            chosen.append(int(j))
    return chosen, d

def _q(a):
    return np.nanquantile(a, QS, axis=0)       # (7, n_baskets)

def walk_forward(Z, fwd, baskets, years=4, step=4, anomaly_share=0.3):
    dates = Z.index
    Zv = np.nan_to_num(Z.values)
    norms = np.linalg.norm(Zv, axis=1)
    last_year = dates[-1].year
    test_idx = [a for a in range(len(dates)) if dates[a].year >= last_year - years + 1 and a % step == 0
                and np.isfinite(fwd[a]).any() and norms[a] > 0]
    if len(test_idx) < 60:
        return None
    thr = np.quantile(norms[test_idx], 1 - anomaly_share)
    nb = fwd.shape[1]
    acc = {k: np.zeros((2, nb)) for k in ("model", "base")}       # [všechny/anomální, koš]
    cnt = np.zeros((2, nb)); cov = np.zeros((2, nb)); dirn = np.zeros(nb); dirhit = np.zeros(nb)
    peryear = {}
    for a in test_idx:
        valid = np.arange(len(dates)) <= a - 30
        valid &= np.isfinite(fwd).any(axis=1)
        if valid.sum() < 300:
            continue
        ch, _ = neighbors(Zv, Zv[a], valid)
        if len(ch) < 15:
            continue
        qm, qb = _q(fwd[ch]), _q(fwd[valid])
        y = fwd[a]
        anom = norms[a] >= thr
        for b in range(nb):
            if not np.isfinite(y[b]) or not np.isfinite(qm[:, b]).all():
                continue
            lm, lb = pinball(np.array([y[b]]), qm[:, b][None, :]), pinball(np.array([y[b]]), qb[:, b][None, :])
            for r in ([0, 1] if anom else [0]):
                acc["model"][r, b] += lm; acc["base"][r, b] += lb; cnt[r, b] += 1
                cov[r, b] += float(qm[0, b] <= y[b] <= qm[-1, b])
            if anom and abs(qm[3, b]) > 0.005:
                dirn[b] += 1; dirhit[b] += float(np.sign(qm[3, b]) == np.sign(y[b]))
            if anom:
                py = peryear.setdefault((dates[a].year, b), [0.0, 0.0, 0])
                py[0] += lm; py[1] += lb; py[2] += 1
    names = list(baskets)
    out = {}
    for b in range(nb):
        if cnt[1, b] < 20 or acc["base"][1, b] <= 0 or acc["base"][0, b] <= 0:
            continue
        imp_anom = 1 - acc["model"][1, b] / acc["base"][1, b]
        imp_all = 1 - acc["model"][0, b] / acc["base"][0, b]
        yrs = [(v[1] - v[0]) > 0 for (yr, bb), v in peryear.items() if bb == b and v[2] >= 5]
        stable = bool(yrs) and np.mean(yrs) >= 0.6
        c90 = cov[1, b] / cnt[1, b]
        hit = float(dirhit[b] / dirn[b]) if dirn[b] >= 20 else None
        dir_ok = bool(hit is not None and hit >= 0.55 and (hit - 0.5) * np.sqrt(dirn[b]) / 0.5 >= 2.0)
        out[names[b]] = {"hit_rate_dir": hit, "n_dir": int(dirn[b]), "direction_verified": dir_ok,
                         "improvement_anomaly": float(imp_anom), "improvement_all": float(imp_all),
                         "n_anomaly": int(cnt[1, b]), "coverage90": float(c90), "stable_years": stable,
                         "active": bool(imp_anom >= GATE_MIN_IMPROVEMENT and imp_all > -0.01 and stable
                                        and 0.75 <= c90 <= 0.99)}
    tot_m, tot_b = acc["model"][1].sum(), acc["base"][1].sum()
    return {"baskets": out, "overall_improvement_anomaly": float(1 - tot_m / tot_b) if tot_b else 0.0,
            "n_test_days": len(test_idx), "anomaly_threshold": float(thr)}

def fit(daily, ar, baskets, extra=None):
    """extra = (ar_krypto, krypto_koše): kalendářní řada, dopředné výnosy se počítají zvlášť a přidají se jako další koše."""
    F = shares(daily)
    Z = zscores(F)
    days = pd.DatetimeIndex(F.index)
    fwd, names = basket_forward(ar, baskets, days)
    if extra is not None and extra[0] is not None and len(extra[1]):
        f2, n2 = basket_forward(extra[0], extra[1], days)
        fwd = np.hstack([fwd, f2]); names = names + n2; baskets = {**baskets, **extra[1]}
    ok = Z.notna().all(axis=1).values
    Z, fwd, days = Z[ok], fwd[ok], days[ok]
    last = F.iloc[-365:]
    return {"features": list(F.columns), "Z": np.nan_to_num(Z.values).astype("float32"), "dates": [d.strftime("%Y-%m-%d") for d in days],
            "fwd": fwd.astype("float32"), "baskets": names, "mu": last.mean().values, "sd": last.std().clip(lower=1e-9).values,
            "active": {}}, Z, fwd, {n: baskets[n] for n in names}

def predict_live(model, feats):
    """feats: slovník podíl-příznaků z posledních 24 h. Vrací z-vektor, analogy a kvantily pro aktivní koše."""
    x = np.array([feats[f] for f in model["features"]])
    z = np.clip((x - model["mu"]) / model["sd"], -6, 6)
    Zh, fwd = model["Z"].astype(float), model["fwd"].astype(float)
    valid = np.isfinite(fwd).any(axis=1)
    ch, d = neighbors(Zh, z, valid)
    names = model["baskets"]
    res = {"z": z, "norm": float(np.linalg.norm(z)), "analog_dates": [model["dates"][j] for j in ch[:8]],
           "top_features": sorted(zip(model["features"], z), key=lambda t: -abs(t[1]))[:4], "baskets": {}}
    if len(ch) < 15:
        return res
    qm = _q(fwd[ch])
    for b, info in model["active"].items():
        j = names.index(b)
        res["baskets"][b] = {"q": qm[:, j].tolist(), "analog_car": fwd[ch[:8], j].tolist(), "info": info}
    return res
