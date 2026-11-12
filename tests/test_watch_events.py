"""Testy serverové části oblíbených/vlastních symbolů, událostí a kotací (bez sítě): python -m pytest tests"""
import json, sys
sys.path.insert(0, ".")
import numpy as np
import pandas as pd
from pipeline import events, quotes, universe, watch, prices as P
from pipeline.sources import edgar

# ------------------------------------------------------------------ symboly z aplikace
def test_parse_symbols_json_fence_lowercase_dups():
    body = 'Sync\n```json\n{"symbols":["asml.as","BTC-USD","btc-usd","AAPL"]}\n```'
    assert watch.parse_symbols(body) == ["ASML.AS", "BTC-USD", "AAPL"]

def test_parse_symbols_rejects_injection_and_garbage():
    bad = ['$(curl evil)', "a;rm -rf /", "AAPL && ls", "<img src=x>", "../../etc", "A" * 16, "", " ", "-X", ".X", "AA PL"]
    out = watch.parse_symbols(json.dumps({"symbols": bad + ["MSFT"]}))
    assert out == ["MSFT"]
    assert isinstance(watch.parse_symbols('{"symbols": "nope"}'), list)      # nespadne
    assert watch.parse_symbols(None) == []

def test_parse_symbols_valid_json_never_falls_back_to_text_tokens():
    assert watch.parse_symbols('{"symbols":[]}') == []                       # dřív by vzniklo falešné „SYMBOLS“
    assert watch.parse_symbols('{"symbols":["$(x)", "a b"]}') == []
    assert watch.parse_symbols('{"other": 1}') == []
    assert watch.parse_symbols('{"symbols": "AAPL"}') == []

def test_parse_symbols_plain_list_and_limit():
    assert watch.parse_symbols("aapl, msft; nvda") == ["AAPL", "MSFT", "NVDA"]
    many = [f"T{i}" for i in range(200)]
    assert len(watch.parse_symbols(json.dumps({"symbols": many}))) == watch.MAX_SYMBOLS

def test_explicit_empty():
    assert watch.is_explicit_empty('{"symbols":[]}')
    assert not watch.is_explicit_empty("nic")
    assert not watch.is_explicit_empty('{"symbols":["A"]}')

def test_classify():
    assert watch.classify("BTC-USD") == "CRYPTO" and watch.classify("ASML.AS") == "EU" and watch.classify("CEZ.PR") == "EU"
    assert watch.classify("7203.T") == "OTHER" and watch.classify("AAPL") == "US"

# ------------------------------------------------------------------ univerzum
def _uni():
    rows = [dict(ticker=t, name=t, sector="Energy", industry="Oil", region="US", country="", indices="SP500", cik="", stooq="", cg_id="") for t in "ABCDE"]
    rows.append(dict(ticker="OLD", name="OLD", sector="Vlastní", industry="", region="US", country="", indices="CUSTOM", cik="", stooq="", cg_id=""))
    return pd.DataFrame(rows, columns=universe.COLS)

def test_merge_custom_adds_drops_and_keeps_existing():
    uni, added = watch.merge_custom(_uni(), ["A", "ZZZ.DE", "FOO-USD"], offline=True)
    assert added == ["ZZZ.DE", "FOO-USD"]
    assert "OLD" not in set(uni["ticker"])                         # staré vlastní mimo seznam se zahodí
    assert (uni[uni["ticker"] == "A"]["indices"] == "SP500").all()  # existující se nepřepisuje
    z = uni[uni["ticker"] == "ZZZ.DE"].iloc[0]
    assert z["indices"] == "CUSTOM" and z["region"] == "EU" and z["sector"] == "Vlastní"
    assert uni[uni["ticker"] == "FOO-USD"].iloc[0]["region"] == "CRYPTO"

def test_custom_not_in_baskets():
    uni, _ = watch.merge_custom(_uni(), ["ZZZ.DE", "FOO-USD"], offline=True)
    b = universe.baskets(uni, min_members=1)
    assert all("ZZZ.DE" not in v for v in b.values())
    cb = universe.crypto_baskets(uni)
    assert all("FOO-USD" not in v for v in cb.values())

def test_parse_sec_tickers_and_yahoo_search():
    m = watch.parse_sec_tickers({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}})
    assert m == {"AAPL": "0000320193"}
    js = {"quotes": [{"symbol": "ASML.AS", "longname": "ASML Holding N.V.", "sector": "Technology"}]}
    assert watch.parse_yahoo_search(js, "ASML.AS")["name"] == "ASML Holding N.V."
    assert watch.parse_yahoo_search(js, "XXX") == {}

# ------------------------------------------------------------------ odhady termínů
def _yearly(start, years, jitter):
    return [pd.Timestamp(start) + pd.DateOffset(years=i) + pd.Timedelta(days=int(j)) for i, j in zip(range(years), jitter)]

def test_estimate_next_yearly_pattern():
    ds = _yearly("2021-02-04", 5, [0, 1, -2, 1, 0])               # výsledky každý únor (poslední 2025-02-05)
    est = events.estimate_next(ds, pd.Timestamp("2025-12-01"))
    assert est is not None
    d, err, n = est
    assert pd.Timestamp("2026-01-25") <= d <= pd.Timestamp("2026-02-15") and n == 5 and 1 <= err <= 5

def test_estimate_next_needs_history_and_is_in_future():
    assert events.estimate_next([pd.Timestamp("2025-01-01")], pd.Timestamp("2025-06-01")) is None
    ds = _yearly("2022-02-04", 5, [0] * 5)                          # poslední 2026-02-04
    d, _, _ = events.estimate_next(ds, pd.Timestamp("2026-11-01"))
    assert d >= pd.Timestamp("2026-11-01") and d <= pd.Timestamp("2027-02-10")
    assert events.estimate_next(ds, pd.Timestamp("2026-03-01")) is None   # příští roční termín je dál než horizont (200 d)

def test_estimate_error_reflects_noise():
    rng = np.random.default_rng(1)
    quiet = _yearly("2015-05-01", 9, [0] * 9)
    noisy = _yearly("2015-05-01", 9, rng.integers(-25, 25, 9))
    e_q = events.estimate_next(quiet, pd.Timestamp("2024-01-01"))[1]
    e_n = events.estimate_next(noisy, pd.Timestamp("2024-01-01"))[1]
    assert e_n > e_q

def test_merge_confirmed_replaces_estimate():
    est = [{"date": "2027-02-01", "type": "earnings", "confirmed": False}, {"date": "2027-03-01", "type": "10-K", "confirmed": False}]
    conf = [{"date": "2027-02-10", "type": "earnings", "confirmed": True}]
    m = events.merge(est, conf)
    assert [(e["type"], e["confirmed"]) for e in m] == [("earnings", True), ("10-K", False)]
    far = events.merge(est, [{"date": "2027-06-10", "type": "earnings", "confirmed": True}])
    assert len(far) == 3                                          # potvrzený termín >30 d od odhadu odhad nenahradí

def test_parse_finnhub():
    js = {"earningsCalendar": [{"symbol": "AAPL", "date": "2027-01-29", "hour": "amc", "epsEstimate": 2.1, "quarter": 1, "year": 2027}, {"symbol": "X"}]}
    out = events.parse_finnhub(js)
    assert len(out) == 1 and out[0][0] == "AAPL" and out[0][1]["confirmed"] and "po zavření trhu" in out[0][1]["title"]

def test_typical_moves():
    rows = [dict(ticker="A", items="2.02,9.01", y1=0.02 * (-1) ** i, y5=0.03, vol=1.0) for i in range(6)] + \
           [dict(ticker="B", items="5.02", y1=0.5, y5=0.5, vol=1.0) for _ in range(6)] + \
           [dict(ticker="C", items="2.02", y1=0.1, y5=0.1, vol=1.0) for _ in range(2)]
    t = events.typical_moves(pd.DataFrame(rows))
    assert set(t) == {"A"} and abs(t["A"]["m1"] - 0.02) < 1e-9          # B není výsledková zpráva, C má málo případů

def test_build_events_from_sec_history():
    today = pd.Timestamp("2026-11-10")
    e8k = pd.DataFrame([{"cik": "0000000001", "date": d, "items": "2.02,9.01"} for d in _yearly("2021-01-28", 6, [0, 1, 0, -1, 0, 1])])
    per = pd.DataFrame([{"cik": "0000000001", "form": "10-K", "filed": d, "acc": str(i), "report": ""} for i, d in enumerate(_yearly("2021-02-20", 6, [0] * 6))])
    uni = pd.DataFrame([dict(ticker="TST", name="Test", sector="X", industry="", region="US", country="", indices="SP500", cik="0000000001", stooq="", cg_id=""),
                        dict(ticker="NOC", name="NoCik", sector="X", industry="", region="EU", country="", indices="CUSTOM", cik="", stooq="", cg_id="")], columns=universe.COLS)
    out = events.build(uni, e8k, per, None, ["TST"], today, {"NOC": [{"date": "2027-01-15", "type": "earnings", "title": "t", "confirmed": True, "src": "Finnhub", "err": 0}]})
    kinds = {e["type"] for e in out["by_ticker"]["TST"]}
    assert {"earnings", "10-K"} <= kinds and all(e["date"] >= "2026-11-10" for e in out["by_ticker"]["TST"])
    assert out["by_ticker"]["NOC"][0]["confirmed"]                  # potvrzené termíny i bez CIK
    assert out["last_earnings"]["TST"] == "2026-01-29"

def test_edgar_refresh_order_rotates_and_prioritizes_new():
    ciks = [f"{i:010d}" for i in range(10)]
    known = set(ciks[:8])
    o0 = edgar.refresh_order(ciks, known, 0, 3)
    assert o0[:2] == ciks[8:] and o0[2:] == ciks[:8]
    assert edgar.refresh_order(ciks, known, 1, 3)[2] == ciks[3]    # druhý den začíná jinde než první

# ------------------------------------------------------------------ kotace
def test_parse_stooq_quotes():
    txt = "Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-11-10,22:00:00,1,2,0.5,190.5,100\nXXX.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"
    q = quotes.parse_stooq_quotes(txt, {"aapl.us": "AAPL", "xxx.us": "XXX"})
    assert list(q) == ["AAPL"] and q["AAPL"]["p"] == 190.5
    assert quotes.parse_stooq_quotes("<html>chyba</html>", {}) == {}

def test_parse_cg_markets():
    rows = [{"id": "bitcoin", "current_price": 90000.5, "last_updated": "2026-11-10T10:00:00Z", "price_change_percentage_24h": 1.5}, {"id": "zzz", "current_price": None}]
    q = quotes.parse_cg_markets(rows, {"bitcoin": "BTC-USD", "zzz": "ZZZ-USD"})
    assert list(q) == ["BTC-USD"] and q["BTC-USD"]["c24"] == 1.5

def test_stooq_key_is_sent(monkeypatch):
    seen = []
    monkeypatch.setattr(P, "STOOQ_KEY", "TAJNY")
    monkeypatch.setattr(P._stooq_rl, "wait", lambda: None)
    monkeypatch.setattr(P.http, "get", lambda url, src, **k: (seen.append(url), "Date,Open,High,Low,Close,Volume\n2026-11-09,1,1,1,5,1\n")[1])
    s = P.stooq_series("aapl.us", "2026-11-01")
    assert "apikey=TAJNY" in seen[0] and float(s.iloc[-1]) == 5.0

def test_stooq_circuit_breaker(monkeypatch):
    import pytest
    monkeypatch.setattr(P, "_stooq_state", {"bad": 0, "ok": 0})
    monkeypatch.setattr(P._stooq_rl, "wait", lambda: None)
    calls = []
    monkeypatch.setattr(P.http, "get", lambda url, src, **k: (calls.append(1), "<html>apikey</html>")[1])
    for _ in range(8):
        with pytest.raises(ValueError):
            P.stooq_series("x", "2026-01-01")
    n = len(calls)
    with pytest.raises(ValueError):
        P.stooq_series("x", "2026-01-01")
    assert len(calls) == n                                         # po 8 selháních bez úspěchu už žádný další požadavek
