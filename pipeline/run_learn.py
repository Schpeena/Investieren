"""Týdenní/ruční běh: doplní GDELT historii (obnovitelně), natrénuje modely A a B, uloží report."""
import argparse
import pandas as pd
from . import store
from .config import CACHE
from .learn import train
from .sources import edgar, gdelt
from . import universe

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gdelt-years", type=int, default=8)
    ap.add_argument("--gdelt-budget-min", type=int, default=150, help="max. minut stahování GDELT historie za běh")
    a = ap.parse_args()
    store.pull(["prices.parquet", "crypto.parquet", "universe.csv", "edgar_8k.parquet", "gdelt_daily.parquet"])
    uni = universe.load()
    edgar.update_history(sorted(set(uni[uni['cik'].ne('')]['cik'])), budget_requests=2000)
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=2)
    gdelt.backfill(end - pd.DateOffset(years=a.gdelt_years), end, budget_seconds=a.gdelt_budget_min * 60)
    train.run()
    store.push(["gdelt_daily.parquet", "model_a.joblib", "model_b.joblib", "model_c.joblib", "events_dataset.parquet",
                "crypto_events.parquet", "report.json"])

if __name__ == "__main__":
    main()
