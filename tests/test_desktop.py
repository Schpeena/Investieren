"""Testy desktopové verze (bez sítě, bez spouštění pipeline): plánovač, server, nastavení, UTF-8 shim."""
import json, os, subprocess, sys, threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
sys.path.insert(0, ".")
from desktop import sched, server, settings, utf8
from desktop.app import http, free_port, run_job

U = timezone.utc
TUE_NOON = datetime(2026, 11, 10, 12, 0, tzinfo=U)           # úterý 13:00 Praha (v okně 8–24)
ALL = {"prices": True, "models": True, "signals": True}

def last(**kw):
    return {"last": {k: {"at": v.isoformat(), "rc": 0, "secs": 1} for k, v in kw.items()}, "fail": {}, "learn_rounds": 0, "gdelt_left": 0, "setup_learn": False}

# ------------------------------------------------------------------ plánovač
def test_first_run_sequence():
    st = {"last": {}, "fail": {}}
    assert sched.decide(st, TUE_NOON, {"prices": False, "models": False, "signals": False}) == ("daily", [])
    assert sched.decide(st, TUE_NOON, {"prices": True, "models": False, "signals": False}) == ("fast", ["--force"])
    assert sched.decide(st, TUE_NOON, {"prices": True, "models": False, "signals": True}) == ("learn", [])

def test_learn_rounds_until_gdelt_done_then_stop():
    st = {"last": {}, "fail": {}, "learn_rounds": 1, "gdelt_left": 900}
    assert sched.decide(st, TUE_NOON, ALL)[0] == "learn"                       # historie GDELT ještě chybí -> další kolo
    st["gdelt_left"] = 10
    assert sched.decide(st, TUE_NOON, ALL)[0] != "learn"
    st.update(learn_rounds=sched.MAX_LEARN_ROUNDS, gdelt_left=900)
    assert sched.decide(st, TUE_NOON, ALL)[0] != "learn"                       # pojistka proti nekonečné smyčce
    st = {"last": {}, "fail": {}, "setup_learn": False}                         # po dokončení nepřetrénovávat jen proto, že chybí soubor
    assert sched.decide(st, TUE_NOON, {"prices": True, "models": False, "signals": True}) != ("learn", [])

def test_failure_backoff():
    st = {"last": {}, "fail": {"daily": (TUE_NOON - timedelta(minutes=5)).isoformat()}}
    assert sched.decide(st, TUE_NOON, {"prices": False, "models": False, "signals": False}) is None
    st["fail"]["daily"] = (TUE_NOON - timedelta(hours=2)).isoformat()
    assert sched.decide(st, TUE_NOON, {"prices": False, "models": False, "signals": False})[0] == "daily"

def test_steady_state_fast_interval_and_window():
    fresh = last(fast=TUE_NOON - timedelta(minutes=3), daily=TUE_NOON - timedelta(hours=14), learn=TUE_NOON - timedelta(days=2))
    assert sched.decide(fresh, TUE_NOON, ALL) is None
    old = last(fast=TUE_NOON - timedelta(minutes=11), daily=TUE_NOON - timedelta(hours=14), learn=TUE_NOON - timedelta(days=2))
    assert sched.decide(old, TUE_NOON, ALL) == ("fast", [])
    night = datetime(2026, 11, 10, 3, 0, tzinfo=U)                              # 4:00 Praha – mimo okno
    old_n = last(fast=night - timedelta(hours=5), daily=night - timedelta(hours=6), learn=night - timedelta(days=2))
    assert sched.decide(old_n, night, ALL) is None

def test_daily_nightly_catchup_and_weekend():
    t = datetime(2026, 11, 10, 21, 45, tzinfo=U)                                # po zavření USA
    st = last(fast=t - timedelta(minutes=2), daily=t - timedelta(hours=24), learn=t - timedelta(days=2))
    assert sched.decide(st, t, ALL) == ("daily", [])
    st = last(fast=t - timedelta(minutes=2), daily=t - timedelta(hours=2), learn=t - timedelta(days=2))
    assert sched.decide(st, t, ALL) is None
    mon = datetime(2026, 11, 9, 9, 0, tzinfo=U)                                 # počítač byl přes víkend vypnutý
    st = last(fast=mon - timedelta(days=3), daily=mon - timedelta(days=3), learn=mon - timedelta(days=2))
    assert sched.decide(st, mon, ALL) == ("daily", [])
    sun = datetime(2026, 11, 8, 9, 0, tzinfo=U)
    st = last(fast=sun - timedelta(minutes=30), daily=sun - timedelta(hours=40), learn=sun - timedelta(days=2))
    assert sched.decide(st, sun, ALL)[0] != "daily"

def test_weekly_learn_only_at_night():
    night = datetime(2026, 11, 14, 1, 0, tzinfo=U)                              # sobota 2:00 Praha
    st = last(fast=night - timedelta(hours=3), daily=night - timedelta(hours=6), learn=night - timedelta(days=7))
    assert sched.decide(st, night, ALL) == ("learn", [])
    day = night.replace(hour=12)
    st = last(fast=day - timedelta(minutes=2), daily=day - timedelta(hours=14), learn=day - timedelta(days=7))
    assert sched.decide(st, day, ALL) is None

def test_custom_has_priority_but_waits_for_prices():
    st = last(fast=TUE_NOON - timedelta(minutes=1), daily=TUE_NOON - timedelta(hours=3), learn=TUE_NOON - timedelta(days=1))
    assert sched.decide(st, TUE_NOON, ALL, pending_custom=True) == ("custom", [])
    assert sched.decide({"last": {}, "fail": {}}, TUE_NOON, {"prices": False, "models": False, "signals": False}, pending_custom=True)[0] == "daily"

def test_demo_flow():
    st = {"last": {}, "fail": {}}
    assert sched.decide(st, TUE_NOON, {"prices": False, "models": False, "signals": False}, demo=True) == ("demo", [])
    assert sched.decide(st, TUE_NOON, {"prices": True, "models": True, "signals": False}, demo=True) == ("fast", ["--demo"])
    assert sched.decide(st, TUE_NOON, ALL, demo=True) is None

def test_log_helpers(tmp_path):
    p = tmp_path / "l.log"
    p.write_text("a\n[gdelt] backfill: 5 nových dní, celkem 10, zbývá ~120\nx\n[gdelt] backfill: 5 nových dní, celkem 15, zbývá ~7\n", encoding="utf-8")
    assert sched.parse_gdelt_left(p) == 7 and sched.tail(p, 2)[-1].startswith("[gdelt]")
    assert sched.parse_gdelt_left(tmp_path / "nic") is None

def test_request_custom_before_prices_writes_watchlist(tmp_path):
    sc = sched.Scheduler(tmp_path, {}, log=lambda m: None)
    assert sc.request_custom(["AAPL"]) == "uloženo" and json.loads((sc.cache / "watchlist.json").read_text(encoding="utf-8"))["symbols"] == ["AAPL"]
    (sc.cache / "prices.parquet").write_bytes(b"x")
    assert sc.request_custom(["AAPL", "MSFT"]) == "zařazeno" and sc.pending_custom == ["AAPL", "MSFT"]

# ------------------------------------------------------------------ server
def _srv(tmp_path):
    sc = sched.Scheduler(tmp_path, {}, demo=True, log=lambda m: None)
    static = tmp_path / "static"; static.mkdir(); (static / "index.html").write_text("<title>x</title>", encoding="utf-8")
    (sc.site / "signals.json").write_text('{"a":1}', encoding="utf-8")
    port = free_port()
    ctx = SimpleNamespace(static=static, site=sc.site, home=tmp_path, port=port, sched=sc)
    return server.start(ctx), f"http://127.0.0.1:{port}", sc

def test_server_security_and_api(tmp_path):
    srv, base, sc = _srv(tmp_path)
    try:
        H = {"X-Signaly": "1", "Content-Type": "application/json"}
        assert http(base + "/")[0] == 200 and http(base + "/data/signals.json")[0] == 200
        assert http(base + "/data/..%2fsettings.json")[0] == 404 and http(base + "/data/x.txt")[0] == 404
        assert http(base + "/api/watchlist", "POST", {"symbols": ["AAPL"]})[0] == 403                   # bez hlavičky
        assert http(base + "/api/watchlist", "POST", {"symbols": ["AAPL"]}, {**H, "Origin": "http://evil.com"})[0] == 403
        assert http(base + "/api/watchlist", "POST", {"symbols": "AAPL"}, H)[0] == 400
        c, b = http(base + "/api/watchlist", "POST", {"symbols": ["aapl", "$(rm -rf /)", "BTC-USD", "AAPL"]}, H)
        assert c == 200 and json.loads(b)["symbols"] == ["AAPL", "BTC-USD"]
        assert http(base + "/api/state", "PUT", {"fav": []}, H)[0] == 400
        assert http(base + "/api/state", "PUT", {"v": 1, "fav": [{"t": "A"}]}, H)[0] == 200
        assert json.loads(http(base + "/api/state")[1])["fav"][0]["t"] == "A"
        # DNS rebinding: špatná hlavička Host
        import http.client as hc
        c = hc.HTTPConnection("127.0.0.1", int(base.rsplit(":", 1)[1])); c.request("GET", "/api/status", headers={"Host": "evil.com"})
        assert c.getresponse().status == 403
    finally:
        srv.shutdown()

def test_symbol_regex_matches_pipeline():
    from pipeline import watch
    assert server.SYMBOL_RE.pattern == watch.SYMBOL_RE.pattern and server.MAX_SYMBOLS == watch.MAX_SYMBOLS

# ------------------------------------------------------------------ nastavení, UTF-8
def test_settings_wizard_env_autostart(tmp_path, monkeypatch):
    answers = iter(["bez emailu", "Martin martin@example.cz", "", "KLIC", ""])
    s = settings.wizard(dict(settings.DEFAULTS), ask=lambda q: next(answers), out=lambda m: None)
    assert s["sec_ua"] == "Martin martin@example.cz" and s["ntfy_topic"].startswith("signaly-") and s["stooq_apikey"] == "KLIC" and s["finnhub_key"] == ""
    e = settings.env_for(tmp_path, s)
    assert e["NO_GH"] == "1" and e["PYTHONUTF8"] == "1" and e["SEC_UA"] == s["sec_ua"] and e["STOOQ_APIKEY"] == "KLIC" and "FINNHUB_KEY" not in e
    assert e["CACHE_DIR"].startswith(str(tmp_path)) and e["SITE_DATA_DIR"].startswith(str(tmp_path))
    settings.save(tmp_path, s); assert settings.load(tmp_path)["sec_ua"] == s["sec_ua"]
    monkeypatch.setenv("SIGNALY_FAKE_APPDATA", str(tmp_path / "ad"))
    f = settings.autostart(True, exe="C:/x/Signaly.exe")
    assert f.exists() and "--no-browser" in f.read_text(encoding="utf-8")
    settings.autostart(False); assert not f.exists()

def test_utf8_shim_in_ascii_locale():
    code = "from desktop import utf8; utf8.install(); import pathlib; open('o1.txt','w').write('\\u017elu\\u0165 \\u25b2'); pathlib.Path('o2.txt').write_text('\\u016f'); print('ok \\u25b2')"
    env = dict(os.environ, PYTHONUTF8="0", LC_ALL="C", PYTHONCOERCECLOCALE="0")
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, cwd=os.getcwd())
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-300:]
    base = subprocess.run([sys.executable, "-c", "open('o3.txt','w').write('\\u016f')"], env=env, capture_output=True)
    assert base.returncode != 0                                              # bez shimu by to v tomto prostředí spadlo (to je ten Windows problém)
    for f in ("o1.txt", "o2.txt", "o3.txt"):
        try: os.remove(f)
        except OSError: pass

def test_run_job_unknown():
    assert run_job(["neexistuje"]) == 2
