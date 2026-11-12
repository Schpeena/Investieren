"""Denní běh (po zavření trhů): univerzum (týdně), inkrementální ceny, nové 8-K historie. Mimo živé okno nezáleží."""
import sys
from datetime import datetime
from . import events, prices as P, store, universe, watch
from .config import CACHE
from .sources import edgar

def main():
    store.pull(["prices.parquet", "crypto.parquet", "universe.csv", "edgar_8k.parquet", "edgar_periodic.parquet",
                "watchlist.json", "events_dataset.parquet"])
    uni_path = CACHE / "universe.csv"
    stale = (not uni_path.exists()) or (datetime.now().timestamp() - uni_path.stat().st_mtime > 6 * 86400)
    uni = universe.refresh() if stale else universe.load()
    uni, added = watch.merge_custom(uni)                       # vlastní symboly z aplikace (oblíbené)
    uni.to_csv(CACHE / "universe.csv", index=False)
    print(f"[daily] vlastních symbolů nově: {added}")
    db, fails = P.update(uni)
    print(f"[daily] DB: {db.shape}, selhalo {len(fails)}: {fails[:15]}")
    cdb, cfails = P.update_crypto(uni)
    print(f"[daily] krypto DB: {cdb.shape}, selhalo {len(cfails)}")
    ciks = sorted(set(uni[uni['cik'].ne('')]['cik']))
    edgar.update_history(ciks, budget_requests=400)         # denně max. 400 požadavků; nové CIKy dostanou celou historii
    events.rebuild(uni, watch.load())
    store.push(["prices.parquet", "crypto.parquet", "universe.csv", "edgar_8k.parquet", "edgar_periodic.parquet", "events.json"])

if __name__ == "__main__":
    main()
