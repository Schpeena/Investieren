"""Sestavení trénovacích dat: (A) firemní události 8-K + neobjasněné cenové šoky, s označením CAR."""
import numpy as np
import pandas as pd
from ..config import SHOCK_SIGMA
from ..sources import edgar

H = (1, 5, 20)
PRIORITY = ["4.02", "1.03", "3.01", "2.04", "5.01", "1.05", "2.06", "2.05", "5.02", "2.02", "1.01", "1.02",
            "2.01", "4.01", "3.03", "3.02", "2.03", "7.01", "5.03", "5.07", "8.01", "PS+", "PS-"]
ITEM_COLS = PRIORITY

class Panel:
    """Předpočítané pole nad cenami: kumulativní AR, volatilita, tržní kontext."""
    def __init__(self, db, ar, bench="SPY"):
        self.idx = ar.index
        self.tickers = list(ar.columns)
        self.ar = ar
        self.cs = {t: np.concatenate([[0.0], np.cumsum(np.nan_to_num(ar[t].values))]) for t in self.tickers}
        v = ar.rolling(60, min_periods=40).std().shift(1)
        self.vol = v.clip(lower=1e-4)
        first = db.apply(lambda s: s.first_valid_index()); last = db.apply(lambda s: s.last_valid_index())
        self.first = {t: self.idx.searchsorted(first[t]) for t in self.tickers if pd.notna(first.get(t))}
        self.last = {t: self.idx.searchsorted(last[t]) for t in self.tickers if pd.notna(last.get(t))}
        r = np.log(db[bench].ffill(limit=5)).diff() if bench in db else pd.Series(0.0, index=self.idx)
        self.mvol = r.rolling(20, min_periods=10).std().shift(1).fillna(0.01).values
        self.mret = r.rolling(20, min_periods=10).sum().shift(1).fillna(0).values

    def features_at(self, t, i):
        """Příznaky známé před reakčním dnem i (bez dne i). None při nedostatku historie."""
        if t not in self.cs or i < 60 or i > len(self.idx) or i < self.first.get(t, 10 ** 9) + 60:
            return None
        ii = min(i, len(self.idx) - 1)
        vol = float(self.vol[t].values[ii]) if i < len(self.idx) else float(self.vol[t].values[-1])
        if not np.isfinite(vol):
            return None
        cs = self.cs[t]
        return {"vol": vol, "ret5": (cs[i] - cs[i - 5]) / (vol * np.sqrt(5)),
                "ret20": (cs[i] - cs[i - 20]) / (vol * np.sqrt(20)),
                "mvol": self.mvol[ii], "mret": self.mret[ii]}

    def labels_at(self, t, i, feats):
        out = {}
        if i + max(H) > self.last.get(t, -1) + 1:
            return {f"y{h}": np.nan for h in H}
        cs = self.cs[t]
        for h in H:
            out[f"y{h}"] = (cs[i + h] - cs[i]) / (feats["vol"] * np.sqrt(h))
        return out

def primary_item(items):
    for p in PRIORITY:
        if p in items:
            return p
    return None

def build(db, uni, edgar_df, shock_sigma=SHOCK_SIGMA, bench="SPY"):
    from ..prices import abnormal
    ar, _ = abnormal(db, uni)
    P = Panel(db, ar, bench=bench)
    sector = uni.set_index("ticker")["sector"].to_dict()
    region = uni.set_index("ticker")["region"].to_dict()
    cik2t = {}
    for _, r in uni[uni["cik"].ne("")].iterrows():
        cik2t.setdefault(r["cik"], []).append(r["ticker"])
    rows, event_idx = [], {}
    # --- 8-K ---
    if edgar_df is not None and not edgar_df.empty:
        for e in edgar_df.itertuples():
            items = [x for x in edgar.items_of(e.items) if x != "9.01"]
            prim = primary_item(items)
            if prim is None:
                continue
            for t in cik2t.get(e.cik, []):
                if t not in P.cs:
                    continue
                i = edgar.reaction_day(e.accept, e.date, P.idx)
                f = P.features_at(t, i)
                if f is None:
                    continue
                event_idx.setdefault(t, set()).add(i)
                rows.append({"ticker": t, "date": P.idx[min(i, len(P.idx) - 1)], "i": i, "kind": "8k", "primary": prim,
                             "items": ",".join(items), "shock_z": 0.0, "is_shock": 0, **f, **P.labels_at(t, i, f)})
    # --- neobjasněné šoky ---
    for t in P.tickers:
        a = P.ar[t].values
        z = a / P.vol[t].values
        hits = np.where(np.abs(z) > shock_sigma)[0]
        for d in hits:
            if any(abs(d - j) <= 1 for j in event_idx.get(t, ())):
                continue
            i = d + 1
            f = P.features_at(t, i)
            if f is None:
                continue
            item = "PS+" if z[d] > 0 else "PS-"
            rows.append({"ticker": t, "date": P.idx[min(i, len(P.idx) - 1)], "i": i, "kind": "shock", "primary": item,
                         "items": item, "shock_z": float(z[d]), "is_shock": 1, **f, **P.labels_at(t, i, f)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df, P
    df["sector"] = df["ticker"].map(sector).fillna("")
    df["region_us"] = (df["ticker"].map(region) != "EU").astype(int)
    return df.sort_values("date").reset_index(drop=True), P

def featurize(df, sectors):
    """Matice příznaků pro model A (pořadí sloupců je pevné)."""
    cols = []
    for it in ITEM_COLS:
        cols.append(df["items"].map(lambda s, it=it: 1.0 if it in str(s).split(",") else 0.0).values)
    n_items = df["items"].map(lambda s: len(str(s).split(","))).values
    sec = df["sector"].map(lambda s: sectors.index(s) if s in sectors else -1).values
    base = [n_items, sec, df["region_us"].values, np.log(df["vol"].values), df["ret5"].values.clip(-6, 6),
            df["ret20"].values.clip(-6, 6), np.log(df["mvol"].values.clip(1e-4)), df["mret"].values,
            df["shock_z"].values.clip(-12, 12), df["is_shock"].values]
    return np.column_stack(cols + base).astype(float)

FEATURE_NAMES = ["item_" + i for i in ITEM_COLS] + ["n_items", "sector", "region_us", "log_vol", "ret5", "ret20",
                                                     "log_mvol", "mret", "shock_z", "is_shock"]
