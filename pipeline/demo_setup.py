"""Vygeneruje syntetická data do CACHE_DIR a natrénuje modely (celý řetězec bez internetu).
Použití:  CACHE_DIR=/tmp/democache NO_GH=1 python -m pipeline.demo_setup && CACHE_DIR=/tmp/democache NO_GH=1 python -m pipeline.run_fast --demo
(desktop verze: Signaly.exe --demo)"""
import numpy as np
import pandas as pd
from . import demo, events, prices as P, watch
from .config import CACHE
from .learn import train
from .sources import edgar as edgar_mod


def main():
    uni, prices, edgar, daily = demo.make()
    crypto = demo.make_crypto(uni, daily)
    uni.to_csv(CACHE / "universe.csv", index=False)
    P.save_db(prices); P.save_db(crypto, P.CRYPTO_FILE)
    edgar.to_parquet(CACHE / "edgar_8k.parquet")
    daily.to_parquet(CACHE / "gdelt_daily.parquet")
    print("data:", prices.shape, crypto.shape, len(edgar), daily.shape)
    train.run(prices, uni, edgar, daily)

    # --- sledované symboly, periodické zprávy a nadcházející události (demo) ---
    rng = np.random.default_rng(11)
    rows = []
    for cik in uni[uni["cik"].ne("")]["cik"].unique():
        base = pd.Timestamp.today().normalize() - pd.Timedelta(days=int(rng.integers(5, 80)))
        for k in range(12):
            d = base - pd.Timedelta(days=91 * k + int(rng.integers(-2, 3)))
            rows.append({"acc": f"{cik}-{k}", "form": "10-K" if k % 4 == 3 else "10-Q", "filed": d.strftime("%Y-%m-%d"), "report": "", "cik": cik})
    pd.DataFrame(rows).to_parquet(edgar_mod.PERIODIC_FILE)
    syms = ["ASML.AS", "SAP.DE", "BTC-USD", "SOL-USD", "NEWCO.DE"]
    watch.save(syms)
    uni2, added = watch.merge_custom(uni, syms, offline=True)
    uni2.to_csv(CACHE / "universe.csv", index=False)
    ev = events.rebuild(uni2, syms)
    print("sledované:", syms, "nově:", added, "| události pro", len(ev["by_ticker"]), "tickerů, typical:", len(ev["typical"]))


if __name__ == "__main__":
    main()
