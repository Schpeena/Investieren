"""Model A: kvantilový gradient boosting pro firemní události + výběr nejlepší varianty podle out-of-sample testu."""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from ..config import QUANTILES, GATE_MIN_IMPROVEMENT, GATE_COVERAGE
from .datasets import featurize, PRIORITY

QS = np.array(QUANTILES)
MIN_TRAIN = 400

def pinball(y, q, taus=QS):
    """y: (n,), q: (n, k) -> průměrná pinball loss přes kvantily."""
    d = y[:, None] - q
    return float(np.mean(np.maximum(taus * d, (taus - 1) * d)))

def _fit_gbm(X, y, tau, seed=0):
    m = HistGradientBoostingRegressor(loss="quantile", quantile=tau, max_iter=120, learning_rate=0.07, max_depth=4,
                                      min_samples_leaf=80, l2_regularization=2.0, random_state=seed,
                                      categorical_features=None)
    return m.fit(X, y)

def fit(df, sectors):
    d = df.dropna(subset=["y20"])
    X, y = featurize(d, sectors), d["y20"].values
    gbm = [_fit_gbm(X, y, t) for t in QUANTILES]
    glob = np.quantile(y, QUANTILES)
    per_item = {}
    for it in PRIORITY:
        s = d[d["primary"] == it]["y20"].values
        if len(s) >= 60:
            per_item[it] = np.quantile(s, QUANTILES).tolist()
    med5 = _fit_gbm(X, d.dropna(subset=["y5"])["y5"].values, 0.5) if d["y5"].notna().sum() > MIN_TRAIN else None
    return {"gbm": gbm, "global": glob.tolist(), "per_item": per_item, "sectors": sectors, "med5": med5,
            "n_train": int(len(d)), "choice": {}}

def predict_variants(model, df):
    """Vrací dict varianta -> (n, k) z-kvantily."""
    X = featurize(df, model["sectors"])
    gb = np.sort(np.column_stack([m.predict(X) for m in model["gbm"]]), axis=1)
    g = np.tile(model["global"], (len(df), 1))
    it = np.array([model["per_item"].get(p, model["global"]) for p in df["primary"]])
    return {"global": g, "item": it, "gbm": gb}

def predict(model, df):
    var = predict_variants(model, df)
    out = np.empty_like(var["global"])
    for k, p in enumerate(df["primary"].values):
        out[k] = var[model["choice"].get(p, "global")][k]
    return out

def walk_forward(df, sectors, years=None, embargo_days=30, min_train=MIN_TRAIN, min_test=100):
    d = df.dropna(subset=["y20"]).copy()
    d["year"] = d["date"].dt.year
    ymax = d["year"].max()
    years = years or [y for y in range(ymax - 3, ymax + 1) if (d["year"] < y).sum() >= min_train and (d["year"] == y).sum() >= min_test]
    pooled = {v: [] for v in ("global", "item", "gbm")}
    ys, prim, yrs = [], [], []
    for Y in years:
        cutoff = pd.Timestamp(f"{Y}-01-01")
        tr = d[d["date"] < cutoff - pd.Timedelta(days=embargo_days)]
        te = d[d["year"] == Y]
        if len(tr) < min_train or len(te) < min(50, min_test):
            continue
        m = fit(tr, sectors)
        var = predict_variants(m, te)
        for v in pooled:
            pooled[v].append(var[v])
        ys.append(te["y20"].values); prim += list(te["primary"]); yrs += [Y] * len(te)
    if not ys:
        return None
    y = np.concatenate(ys); prim = np.array(prim); yrs = np.array(yrs)
    P = {v: np.vstack(pooled[v]) for v in pooled}
    losses = {v: pinball(y, P[v]) for v in P}
    rep = {"years": [int(x) for x in sorted(set(yrs))], "n_test": int(len(y)), "pinball": losses,
           "coverage90": {v: float(np.mean((y >= P[v][:, 0]) & (y <= P[v][:, -1]))) for v in P}, "items": {}}
    choice = {}
    for it in PRIORITY:
        mk = prim == it
        if mk.sum() < 60:
            continue
        L = {v: pinball(y[mk], P[v][mk]) for v in P}
        base = L["global"]
        best = min(("item", "gbm"), key=lambda v: L[v])
        imp = (base - L[best]) / base if base > 0 else 0.0
        # stabilita: zlepšení musí platit i v alespoň polovině testovaných let
        yr_ok = []
        for Y in rep["years"]:
            m2 = mk & (yrs == Y)
            if m2.sum() >= 15:
                yr_ok.append(pinball(y[m2], P[best][m2]) < pinball(y[m2], P["global"][m2]))
        stable = (np.mean(yr_ok) >= 0.5) if yr_ok else False
        cov = float(np.mean((y[mk] >= P[best][mk][:, 0]) & (y[mk] <= P[best][mk][:, -1])))
        ok = imp >= GATE_MIN_IMPROVEMENT and stable and GATE_COVERAGE[0] - 0.08 <= cov <= GATE_COVERAGE[1] + 0.06
        choice[it] = best if ok else "global"
        sgn = P[best][mk][:, 3]
        strong = np.abs(sgn) > 0.15
        ns = int(strong.sum())
        hit = float(np.mean(np.sign(sgn[strong]) == np.sign(y[mk][strong]))) if ns >= 30 else None
        dir_ok = bool(hit is not None and (hit - 0.5) * np.sqrt(ns) / 0.5 >= 2.0 and hit >= 0.55)   # ~2σ nad náhodou
        rep["items"][it] = {"n": int(mk.sum()), "improvement": float(imp), "best": best, "active": bool(ok),
                            "coverage90": cov, "hit_rate_dir": hit, "n_dir": ns, "direction_verified": dir_ok,
                            "stable_years": bool(stable)}
    rep["choice"] = choice
    rep["overall_improvement_gbm"] = (losses["global"] - losses["gbm"]) / losses["global"]
    return rep
