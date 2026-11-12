"""Zpracování seznamu sledovaných symbolů z aplikace (workflow watchlist.yml, spouští ho předvyplněné issue od majitele repa).
Uloží seznam, přidá nové symboly do univerza, stáhne jim historii cen a 8-K, přepočítá nadcházející události."""
import os, sys
from . import events, prices as P, store, universe, watch
from .config import CACHE
from .sources import edgar

def main():
    store.pull(["prices.parquet", "crypto.parquet", "universe.csv", "edgar_8k.parquet", "edgar_periodic.parquet",
                "watchlist.json", "events_dataset.parquet"])
    body = os.environ.get("ISSUE_BODY") or os.environ.get("SYMBOLS") or ""
    syms = watch.parse_symbols(body)
    rep = CACHE / "watch_report.txt"
    if not syms and not watch.is_explicit_empty(body):
        rep.write_text("Nenašel jsem žádný platný symbol (očekávám JSON {\"symbols\": [...]} nebo seznam oddělený čárkou).")
        print(rep.read_text()); return
    watch.save(syms)
    uni = universe.load()
    uni, added = watch.merge_custom(uni, syms)
    uni.to_csv(CACHE / "universe.csv", index=False)
    lines = [f"Sledováno {len(syms)} symbolů, z toho nových mimo univerzum: {len(added)}."]
    if added:
        sub = uni[uni["ticker"].isin(added)]
        db, fails = P.update(sub[~sub["region"].eq("CRYPTO")])
        cdb, cfails = P.update_crypto(sub)
        bad = sorted(set(fails) | set(cfails))
        ciks = sorted(set(sub[sub["cik"].ne("")]["cik"]))
        if ciks:
            edgar.update_history(ciks, budget_requests=50)
        ok = [t for t in added if t not in bad]
        lines.append("Historie cen stažena: " + (", ".join(ok) or "–"))
        if bad:
            lines.append("BEZ DAT (zdroj symbol nezná – zkus tvar jako ve Yahoo, např. ASML.AS, CEZ.PR, BTC-USD): " + ", ".join(bad))
        lines.append("Signály a modely se k novým symbolům plně připojí po týdenním učení; živé ceny a události jsou hned.")
    events.rebuild(uni, syms)
    store.push(["watchlist.json", "universe.csv", "prices.parquet", "crypto.parquet", "edgar_8k.parquet", "edgar_periodic.parquet", "events.json"])
    rep.write_text("\n".join(lines))
    print(rep.read_text())

if __name__ == "__main__":
    main()
