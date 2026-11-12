"""Živý běh (každých ~10 min v okně 8–24): zdroje -> události -> signály -> site/data/signals.json + notifikace."""
import argparse
import shutil, json, sys, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import joblib
import numpy as np
import pandas as pd
from . import evaluate, http, prices as P, quotes as Q, signals as S, store, universe, watch
from .config import *
from .notify import push
from .sources import edgar, gdelt, hazards, rss, social

def in_window(now=None):
    now = now or datetime.now(ZoneInfo(TZ))
    return ACTIVE_START_HOUR <= now.hour < ACTIVE_END_HOUR

def load_state():
    p = CACHE / "state.json"
    return json.load(open(p)) if p.exists() else {"gdelt": {}, "notified": {}, "log": [], "edgar_seen": [], "recent_502": {}}

ACTIVE_TTL_H = 72            # jak dlouho zůstává signál v aplikaci
CRYPTO_REFRESH_H = 8         # jak často se v živém běhu dotahují krypto ceny (dokončené denní svíčky)
FOLLOWUP_MAX_PER_RUN = 8

def _write_if_changed(path, text):
    old = path.read_text() if path.exists() else None
    if old == text:
        return False
    path.write_text(text)
    return True

def merge_active(active, sigs, now):
    """Signály se drží ACTIVE_TTL_H hodin (dřív mizely hned v dalším běhu); stejné id = nejnovější verze, first_seen zůstává."""
    for s in sigs:
        old = active.get(s["id"])
        s["first_seen"] = old["first_seen"] if old else now.isoformat()
        active[s["id"]] = s
    keep = {k: v for k, v in active.items() if (now - datetime.fromisoformat(v["first_seen"])).total_seconds() < ACTIVE_TTL_H * 3600}
    return keep

def collect_live(uni, state, demo):
    if demo:
        from . import demo as D
        return D.live(uni, state)
    out = {"filings": [], "scandals": {}, "hazards": [], "gdelt_feats": None, "gdelt_slots": 0, "headlines": 0,
           "influencer_events": []}
    cik2t = {}
    for _, r in uni[uni["cik"].ne("")].iterrows():
        cik2t.setdefault(r["cik"], []).append(r["ticker"])
    seen = set(state["edgar_seen"])
    for f in edgar.live_feed():
        if f["acc"] in seen or f["cik"] not in cik2t:
            continue
        try:
            df = edgar.fetch_cik(f["cik"], include_older=False)
            row = df[df["acc"] == f["acc"]]
            if row.empty:
                continue            # filing ještě není v submissions API – zkusí se příští běh
            out["filings"].append({"acc": f["acc"], "cik": f["cik"], "items": edgar.items_of(row.iloc[0]["items"]),
                                   "link": f["link"], "company": f["company"], "tickers": cik2t[f["cik"]]})
            seen.add(f["acc"])
        except Exception as e:
            print(f"[fast] {f['company']}: {e}")
        if len(out["filings"]) >= 40:
            break
    state["edgar_seen"] = list(seen)[-3000:]
    added = gdelt.live_update(state, GDELT_MAX_SLOTS_PER_RUN)
    win, nslots = gdelt.window_sums(state, 24)
    if win and nslots >= 8:
        out["gdelt_feats"] = gdelt.features_from_sums(win)
    out["gdelt_slots"] = nslots
    heads = rss.fetch_headlines()
    out["headlines"] = len(heads)
    try:
        out["influencer_events"] = social.collect(social.load_influencers(), heads, state)
    except Exception as e:
        print(f"[fast] influenceři: {e}")
        out["influencer_events"] = []
    out["scandals"] = rss.scandals(heads, uni)
    out["hazards"] = hazards.all_hazards()
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not (a.demo or a.force) and not in_window():
        print("[fast] mimo okno 8–24 – konec"); return
    t0 = time.time()
    if not a.demo:
        store.pull(["prices.parquet", "crypto.parquet", "universe.csv", "model_a.joblib", "model_b.joblib", "model_c.joblib",
                    "events_dataset.parquet", "crypto_events.parquet", "report.json", "state.json", "signal_log.json", "active.json",
                    "watchlist.json", "events.json"])
    uni, db = universe.load(), P.load_db()
    if db.empty:
        sys.exit("Chybí cenová DB – spusť nejdřív workflow 'daily' (a 'learn').")
    state = load_state()
    now = datetime.now(timezone.utc)
    # --- krypto: dokončené denní svíčky se dotahují přímo v živém běhu (dnešní se bere z živé ceny) ---
    push_files = ["state.json"]
    if not a.demo:
        last = state.get("crypto_ts")
        if not last or (now - datetime.fromisoformat(last)).total_seconds() > CRYPTO_REFRESH_H * 3600:
            try:
                P.update_crypto(uni); state["crypto_ts"] = now.isoformat(); push_files.append("crypto.parquet")
            except Exception as e:
                print(f"[fast] krypto update: {e}")
    cdb = P.load_crypto_db()
    mA = joblib.load(CACHE / "model_a.joblib") if (CACHE / "model_a.joblib").exists() else None
    mB = joblib.load(CACHE / "model_b.joblib") if (CACHE / "model_b.joblib").exists() else None
    mC = joblib.load(CACHE / "model_c.joblib") if (CACHE / "model_c.joblib").exists() else None
    report = json.load(open(CACHE / "report.json")) if (CACHE / "report.json").exists() else {}
    ds = pd.read_parquet(CACHE / "events_dataset.parquet") if (CACHE / "events_dataset.parquet").exists() else None
    dsc = pd.read_parquet(CACHE / "crypto_events.parquet") if (CACHE / "crypto_events.parquet").exists() else None
    watch_syms = set(watch.load())
    active_path = CACHE / "active.json"
    active = json.load(open(active_path)) if active_path.exists() else {}
    live_q = Q.refresh(uni, watch_syms | {v["ticker"] for v in active.values()}, state, demo=a.demo,
                       db=pd.concat([db, cdb], axis=1) if a.demo else None)
    Q.write(live_q)
    quote_cache = {}
    def quote(t):
        if a.demo:
            return None
        if t in live_q:
            return {"price": live_q[t]["p"], "time": live_q[t]["t"]}
        if t not in quote_cache:
            quote_cache[t] = P.latest_quote(t)
        return quote_cache[t]
    # --- vyhodnocení dřívějších signálů (log) -> statistika, kalibrace, ověřené druhy ---
    log = evaluate.load_log()
    due = evaluate.update_outcomes(log, db, cdb, pd.Timestamp(now.date()))
    summary = evaluate.summarize(log)
    ctx = S.Ctx(uni, db, mA, mB, report, ds, state, quote_fn=quote, cdb=cdb, model_c=mC, crypto_ds=dsc)
    ctx.spread = evaluate.spreads(log)
    verified = evaluate.verified_kinds(summary)
    live = collect_live(uni, state, a.demo)
    sigs = []
    # --- 8-K ---
    for f in live["filings"]:
        for t in f["tickers"]:
            sg = S.company_signal(ctx, t, f["items"], f"8-K: {f['company']} – " + ", ".join(ITEM_CZ.get(i, i) for i in f["items"] if i != "9.01"),
                                  f["link"], "8k", evid=f["acc"])
            if sg:
                sigs.append(sg)
            if "5.02" in f["items"]:
                state["recent_502"][t] = now.isoformat()
    # --- neobjasněné cenové šoky z posledního (dokončeného) dne: akcie i krypto ---
    in8k = {t for f in live["filings"] for t in f["tickers"]}
    for panel in (ctx.panel, ctx.cpanel):
        if panel is None:
            continue
        lastr = panel.ar.dropna(how="all")
        if lastr.empty:
            continue
        z = lastr.iloc[-1] / panel.vol.iloc[-1]
        day = panel.idx[-1].strftime("%Y-%m-%d")
        for t in z[z.abs() > SHOCK_SIGMA].index:
            if t in in8k:
                continue
            item = "PS+" if z[t] > 0 else "PS-"
            sg = S.company_signal(ctx, t, [item], f"Neobjasněný pohyb {z[t]:+.1f}σ (abnormální výnos) – příčina neznámá", "", "shock", evid=f"ps{day}")
            if sg:
                sigs.append(sg)
    # --- skandály z titulků ---
    recent = {t for t, ts in state["recent_502"].items() if (now - datetime.fromisoformat(ts)).days < 3}
    sigs += S.scandal_signals(ctx, live["scandals"], recent)
    # --- svět (GDELT) ---
    world_note = None
    if live["gdelt_feats"]:
        day = now.strftime("%Y%m%d%H")[:8] + ("a" if now.hour < 12 else "b")
        sigs += S.world_signals(ctx, live["gdelt_feats"], "Neobvyklý stav světových událostí (GDELT)", "", "w" + day)
    else:
        world_note = f"GDELT zatím nasbíral jen {live['gdelt_slots']} slotů (potřeba ≥ 8)"
    # --- hazardy a vlivní lidé ---
    sigs += S.prior_signals(ctx, live["hazards"])
    sigs += S.influencer_signals(ctx, live["influencer_events"], verified)
    sigs = [s for s in sigs if s["severity"] >= SHOW_MIN_SEVERITY - (1.0 if s["ticker"] in watch_syms else 0.0)]   # u sledovaných citlivěji
    for s in sigs:
        S.finalize_stats(ctx, s)
    # --- aktivní seznam (drží signály 72 h) ---
    active = merge_active(active, sigs, now)
    shown = sorted(active.values(), key=lambda s: -(s["severity"] - 0.04 * (now - datetime.fromisoformat(s["first_seen"])).total_seconds() / 3600))
    shown = shown[:MAX_SIGNALS]
    for s in shown:
        s["age_h"] = round((now - datetime.fromisoformat(s["first_seen"])).total_seconds() / 3600, 1)
    # --- notifikace nových signálů ---
    notified = {k: v for k, v in state["notified"].items() if (now - datetime.fromisoformat(v)).days < 7}
    today = sum(1 for v in notified.values() if v[:10] == now.strftime("%Y-%m-%d"))
    sent = 0
    for s in sorted(sigs, key=lambda s: -s["severity"]):
        worth = s["severity"] >= NOTIFY_MIN_SEVERITY - (1.0 if s["ticker"] in watch_syms else 0.0) and (s["direction_verified"] or s["critical"] or s["kind"] == "world")
        if worth and s["id"] not in notified and sent < 5 and today + sent < 15:
            arrow = "▲" if s["direction"] > 0 else "▼"
            st = s["stats"]
            body = (f"{s['title']}\nOdhad 20 pozorování (vs trh): {st['med20']*100:+.1f} % "
                    f"[{st['p5']*100:+.0f} až {st['p95']*100:+.0f} %], jistota: {s['confidence']}. Statistický nápad, ne rada.")
            if push(NTFY_TOPIC, f"{arrow} {s['ticker']} – {s['type_label']}", body, s["link"] or None):
                notified[s["id"]] = now.isoformat(); sent += 1
    state["notified"] = notified
    # --- log (všechny zobrazené signály; značka 'notified') + notifikace uzavření po 1 a 3 měsících ---
    new_logged = evaluate.record(log, sigs, set(notified), now)
    due = evaluate.update_outcomes(log, db, cdb, pd.Timestamp(now.date()))
    fu = 0
    for e, which in due:
        if fu >= FOLLOWUP_MAX_PER_RUN:
            break
        title, body = evaluate.message(e, which)
        if push(NTFY_TOPIC, title, body, e.get("link") or None, tags=["checkered_flag"]):
            e["sent1" if which == "1m" else "sent3"] = now.isoformat(); fu += 1
    log = evaluate.save_log(log)
    summary = evaluate.summarize(log)
    # --- výstup ---
    market = []
    for frame in (db, cdb):
        if frame is None or frame.empty:
            continue
        last2 = frame.ffill(limit=5).tail(2)
        for _, r in uni[uni["ticker"].isin(frame.columns)].iterrows():
            t = r["ticker"]
            if t in last2 and last2[t].notna().all():
                nd = 2 if float(last2[t].iloc[-1]) >= 1 else 6
                market.append({"ticker": t, "name": r["name"], "sector": r["sector"], "region": r["region"],
                               "spot": round(float(last2[t].iloc[-1]), nd), "chg1d": round(float(last2[t].iloc[-1] / last2[t].iloc[0] - 1), 4)})
    rep = {}
    for key in ("A", "C"):
        if report.get(key):
            rep[key] = {"years": report[key]["years"], "n_test": report[key]["n_test"],
                        "pinball": report[key]["pinball"], "coverage90": report[key]["coverage90"],
                        "items": {k: {kk: v[kk] for kk in ("n", "improvement", "best", "active", "hit_rate_dir", "n_dir", "direction_verified")}
                                  for k, v in report[key]["items"].items()}}
    if report.get("B"):
        rep["B"] = {"overall": report["B"]["overall_improvement_anomaly"], "n_test_days": report["B"]["n_test_days"],
                    "active": {b: v for b, v in report["B"]["baskets"].items() if v["active"]},
                    "tested": len(report["B"]["baskets"])}
    ov = summary.get("overall") or {}
    track = {"n": summary["n_closed"], "hit_rate": round(ov["hit"], 3) if ov.get("hit") is not None else None}
    out = {"generated_at": now.isoformat(), "demo": a.demo, "horizon": HORIZON, "signals": shown, "market": market,
           "report": rep, "built_at": report.get("built_at"), "track_record": track, "evaluation": summary,
           "calibration": ctx.spread, "universe": len(uni), "watch": sorted(watch_syms),
           "sources": {"gdelt_slots_24h": live["gdelt_slots"], "headlines": live["headlines"], "filings_new": len(live["filings"]),
                       "hazards": len(live["hazards"]), "influencer_events": len(live["influencer_events"]),
                       "x_enabled": bool(social.X_BEARER), "note": world_note, "health": http.health_report()},
           "disclaimer": "Statistický nápad k dalšímu zkoumání, ne investiční doporučení. Autor není licencovaný poradce."}
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(SITE_DATA / "signals.json", "w"), ensure_ascii=False, default=float)
    json.dump(state, open(CACHE / "state.json", "w"), default=float)
    if (CACHE / "events.json").exists():
        shutil.copy(CACHE / "events.json", SITE_DATA / "events.json")
    if _write_if_changed(active_path, json.dumps(active, default=float, separators=(",", ":"))):
        push_files.append("active.json")
    if new_logged or fu:
        push_files.append("signal_log.json")
    if not a.demo:
        store.push(push_files)
    print(f"[fast] signálů {len(shown)} (nových {len(sigs)}), notifikací {sent}, uzavření {fu}, logováno {new_logged}, {time.time() - t0:.0f}s")

if __name__ == "__main__":
    main()
