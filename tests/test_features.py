"""Testy: vyhodnocení signálů (1m/3m notifikace, kalibrace), krypto univerzum, příspěvky vlivných osob, ntfy JSON."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from pipeline import evaluate, notify, universe
from pipeline.sources import social

TODAY = pd.Timestamp("2026-11-10")

def _entry(i, ticker, days_ago, direction=1, asset="stock", kind="8k", notified=True, spot=100.0, bench="SPY", beta=1.0):
    d0 = TODAY - pd.Timedelta(days=days_ago)
    return {"id": f"e{i}", "ticker": ticker, "name": ticker, "asset": asset, "kind": kind, "model": "gbm", "confidence": "vyšší",
            "label": "Odchod vedení", "title": "t", "link": "", "direction": direction, "med": 0.04, "p5": -0.10, "p95": 0.12,
            "beta": beta, "bench": bench, "date": d0.strftime("%Y-%m-%d"), "spot": spot,
            "q": {"5": -0.10, "20": -0.04, "35": 0.0, "50": 0.04, "65": 0.07, "80": 0.1, "95": 0.15},
            "created": d0.isoformat(), "notified": notified, "sent1": None, "sent3": None}

def _frames():
    bidx = pd.bdate_range("2026-04-01", TODAY)
    spy = pd.Series(np.linspace(100, 110, len(bidx)), index=bidx)
    aaa = pd.Series(np.linspace(100, 125, len(bidx)), index=bidx)             # roste výrazně
    cidx = pd.date_range("2026-04-01", TODAY)
    btc = pd.Series(np.linspace(50000, 40000, len(cidx)), index=cidx)         # klesá
    return pd.DataFrame({"SPY": spy, "AAA": aaa}), pd.DataFrame({"BTC-USD": btc})

def test_followups_one_and_three_months():
    db, cdb = _frames()
    log = [_entry(1, "AAA", 40, spot=float(db["AAA"].asof(TODAY - pd.Timedelta(days=40)))),
           _entry(2, "AAA", 100, spot=float(db["AAA"].asof(TODAY - pd.Timedelta(days=100)))),
           _entry(3, "BTC-USD", 45, direction=-1, asset="crypto", bench="BTC-USD", beta=0.0, kind="shock",
                  spot=float(cdb["BTC-USD"].asof(TODAY - pd.Timedelta(days=45)))),
           _entry(4, "AAA", 10), _entry(5, "AAA", 40, notified=False)]
    due = evaluate.update_outcomes(log, db, cdb, TODAY)
    kinds = sorted((e["id"], w) for e, w in due)
    assert ("e1", "1m") in kinds and ("e2", "1m") in kinds and ("e2", "3m") in kinds and ("e3", "1m") in kinds
    assert all(i != "e4" and i != "e5" for i, _ in kinds)              # příliš čerstvý / neodeslaný signál se nenotifikuje
    e1 = next(e for e in log if e["id"] == "e1")
    assert "h" in e1 and e1["h"]["ret"] > 0 and e1["h"]["hit"] is True      # AAA rostla, směr nahoru
    e3 = next(e for e in log if e["id"] == "e3")
    assert e3["h"]["ret"] < 0 and e3["h"]["hit"] is True                   # BTC klesal a čekali jsme pokles (direction=-1) -> trefa
    title, body = evaluate.message(e1, "1m")
    assert "Uzavření signálu" in title and "1 měsíc" in title and "AAA" in title and "▲" in title
    assert "−" in body or "+" in body
    e2 = next(e for e in log if e["id"] == "e2")
    t3, b3 = evaluate.message(e2, "3m")
    assert "3 měsíce" in t3 and "efekt" in b3
    for e, w in due:                                                      # po odeslání už se nic neopakuje
        e["sent1" if w == "1m" else "sent3"] = "x"
    assert evaluate.update_outcomes(log, db, cdb, TODAY) == []

def test_summary_calibration_and_verification():
    rng = np.random.default_rng(0)
    log = []
    for i in range(60):                                                    # 60 uzavřených signálů, skutečnost je 2× širší než odhad
        e = _entry(i, "AAA", 60)
        e["h"] = {"date": "2026-10-01", "price": 1, "ret": 0.0, "bench_ret": 0, "abn": float(rng.normal(0.04, 0.2)),
                  "pit": 0.5, "inside90": bool(rng.random() < 0.6), "hit": bool(rng.random() < 0.75), "u": None}
        half = (e["p95"] - e["p5"]) / 2
        e["h"]["u"] = abs(e["h"]["abn"] - e["med"]) / half
        log.append(e)
    sp = evaluate.spreads(log)
    assert 1.15 < sp["stock:8k"] <= 1.6                                    # vějíř se má rozšířit
    assert evaluate.spreads(log[:20]) == {}                                # málo dat -> žádná kalibrace
    summ = evaluate.summarize(log)
    assert summ["n_closed"] == 60 and summ["by_kind"]["stock:8k"]["n"] == 60
    assert "stock:8k" in evaluate.verified_kinds(summ)                     # 75 % trefa při n=60 je ~3σ
    log2 = log[:20]
    assert evaluate.verified_kinds(evaluate.summarize(log2)) == set()      # n < 30

def test_crypto_universe_filters_and_baskets():
    items = [("tether", "usdt", "Tether"), ("bitcoin", "btc", "Bitcoin"), ("wrapped-bitcoin", "wbtc", "Wrapped Bitcoin"),
             ("ethereum", "eth", "Ethereum"), ("usd-coin", "usdc", "USDC"), ("lido-staked-ether", "steth", "Lido Staked Ether"),
             ("solana", "sol", "Solana")]
    df = universe._crypto_frame(items, 100)
    assert df["ticker"].tolist() == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert (df["region"] == "CRYPTO").all()
    uni = universe.build(offline=True)
    b = universe.crypto_baskets(uni)
    assert "crypto:BTC" in b and "crypto:large_alts" in b
    assert not any(k.startswith("crypto") for k in universe.baskets(uni))   # akciové koše krypto neobsahují

def test_influencers_detection_and_parsers():
    infl = social.load_influencers()
    assert len(infl) >= 100 and {"name", "weight", "tickers"} <= set(infl.columns)
    now = pd.Timestamp.now("UTC").isoformat()
    heads = [{"text": "Musk says Tesla robotaxi launch is a record breakthrough", "link": "u1", "source": "bbc", "ts": now},
             {"text": "Musk visits Berlin factory", "link": "u2", "source": "ft", "ts": now},               # bez slovesa řeči -> ignoruj
             {"text": "Trump threatens new tariffs on imports", "link": "u3", "source": "nyt", "ts": now},
             {"text": "Trump warns of tariffs as trade war escalates", "link": "u4", "source": "cnbc", "ts": now},
             {"text": "Bailey says weather is nice", "link": "u5", "source": "x", "ts": now}]               # slabá osoba bez celého jména
    ev = social.detect(heads, infl, require_speech=True)
    by = {(e["person"], e["topic"]): e for e in ev}
    musk = by[("Elon Musk", "firma / projekt člověka")]
    assert musk["sign"] == 1 and "TSLA" in musk["tickers"]
    tr = by[("Donald Trump", "cla / obchodní válka")]
    assert tr["sign"] == -1 and len(tr["sources"]) == 2 and "sector:Industrials" in tr["targets"]
    assert not any(e["person"] == "Andrew Bailey" for e in ev)
    # staré příspěvky se ignorují
    old = [{"text": "Musk says Tesla is great", "link": "o", "source": "s", "ts": "2020-01-01T00:00:00Z"}]
    assert social.detect(old, infl, require_speech=True) == []
    # parsery
    bs = social.parse_bluesky({"feed": [{"post": {"uri": "at://did:x/app.bsky.feed.post/abc", "author": {"handle": "a.bsky.social"},
                                                  "record": {"text": "hello", "createdAt": "2026-11-10T10:00:00Z"}}},
                                        {"reason": {"$type": "repost"}, "post": {"record": {"text": "RT"}}}]}, "X")
    assert len(bs) == 1 and bs[0]["link"] == "https://bsky.app/profile/a.bsky.social/post/abc"
    xml = '<rss><channel><item><title>Post &lt;b&gt;text&lt;/b&gt;</title><link>l</link><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>'
    rp = social.parse_rss_posts(xml, "https://trumpstruth.org/feed", "Donald Trump", "truth")
    assert rp[0]["text"] == "Post  text" or rp[0]["text"].startswith("Post")
    xs = social.parse_x({"data": [{"id": "1", "text": "hi", "created_at": "2026-11-10T10:00:00Z"}]}, "Elon Musk")
    assert xs[0]["link"].endswith("/1")

def test_ntfy_json_keeps_diacritics(monkeypatch):
    sent = {}
    class R:
        def read(self): return b"{}"
    def fake(req, timeout=0):
        sent["data"] = json.loads(req.data.decode("utf-8")); sent["ct"] = req.headers.get("Content-type")
        return R()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    assert notify.push("tema", "▲ ŠKODA – Změna vedení", "Odhad +3 %", "https://x.cz")
    assert sent["data"]["title"] == "▲ ŠKODA – Změna vedení" and sent["data"]["click"] == "https://x.cz"
    assert "json" in sent["ct"].lower()
