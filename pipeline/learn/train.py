"""Týdenní učení: data -> dataset -> model A a B -> walk-forward report -> uložení."""
import json, time
import joblib
import numpy as np
import pandas as pd
from .. import prices as P, universe
from ..config import CACHE, QUANTILES
from ..sources import edgar, gdelt
from . import datasets, model_a, model_b

def run(db=None, uni=None, edgar_df=None, daily=None, quiet=False):
    t0 = time.time()
    uni = universe.load() if uni is None else uni
    db = P.load_db() if db is None else db
    edgar_df = edgar.load() if edgar_df is None else edgar_df
    daily = gdelt.load_daily() if daily is None else daily
    cdb = P.load_crypto_db()
    report = {"built_at": pd.Timestamp.now("UTC").isoformat(), "A": None, "B": None, "C": None}
    # ---------------- Model A ----------------
    df, panel = datasets.build(db, uni, edgar_df)
    print(f"[A] událostí: {len(df)} (8-K {int((df.kind=='8k').sum()) if len(df) else 0}, šoky {int((df.kind=='shock').sum()) if len(df) else 0})")
    if len(df) >= 800:
        sectors = sorted(uni["sector"].unique())
        rep = model_a.walk_forward(df, sectors)
        model = model_a.fit(df, sectors)
        if rep:
            model["choice"] = rep["choice"]
        report["A"] = rep
        joblib.dump(model, CACHE / "model_a.joblib", compress=3)
        df.drop(columns=["items"]).to_parquet(CACHE / "events_dataset.parquet", compression="zstd") if False else \
            df.to_parquet(CACHE / "events_dataset.parquet", compression="zstd")
    # ---------------- Model C = model A pro krypto (jen neobjasněné šoky, kalendářní dny, benchmark BTC) ----------------
    cuni = uni[uni["region"].eq("CRYPTO")]
    extra = None
    if not cdb.empty and len(cuni):
        cdf, _ = datasets.build(cdb, cuni, None, bench="BTC-USD")
        print(f"[C] krypto šoků: {len(cdf)}")
        if len(cdf) >= 300:
            rep = model_a.walk_forward(cdf, ["Crypto"], min_train=200, min_test=40)
            model = model_a.fit(cdf, ["Crypto"])
            if rep:
                model["choice"] = rep["choice"]
            report["C"] = rep
            joblib.dump(model, CACHE / "model_c.joblib", compress=3)
            cdf.to_parquet(CACHE / "crypto_events.parquet", compression="zstd")
        arc, _ = P.abnormal(cdb, cuni)
        extra = (arc, universe.crypto_baskets(uni))
    # ---------------- Model B ----------------
    if len(daily) >= 500:
        ar, _ = P.abnormal(db, uni)
        baskets = universe.baskets(uni)
        mdl, Z, fwd, bk = model_b.fit(daily, ar, baskets, extra=extra)
        rep = model_b.walk_forward(Z, fwd, bk)
        if rep:
            mdl["active"] = {b: v for b, v in rep["baskets"].items() if v["active"]}
        report["B"] = rep
        joblib.dump(mdl, CACHE / "model_b.joblib", compress=3)
    json.dump(report, open(CACHE / "report.json", "w"), indent=1, default=float)
    print(f"[learn] hotovo za {time.time() - t0:.0f}s")
    return report
