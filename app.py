"""Signaly.exe – vstupní bod desktopové verze.
  Signaly.exe              spustí lokální server + plánovač a otevře prohlížeč
  Signaly.exe --demo       ukázková syntetická data (rychlé vyzkoušení UI, bez internetu)
  Signaly.exe run <job>    (interní) jeden běh pipeline: fast | daily | learn | custom | demo
  Signaly.exe --selftest   kontrola balíčku (používá ji sestavení ve Windows)"""
import argparse, importlib, json, os, socket, sys, tempfile, threading, time, webbrowser
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

from . import __version__, server, settings as S, utf8
from .sched import MODULE, Scheduler

def static_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "docs"
    return Path(__file__).resolve().parents[1] / "docs"

# ------------------------------------------------------------------ podproces: jeden běh pipeline
def run_job(argv):
    utf8.install()
    job, extra = argv[0], argv[1:]
    if job not in MODULE:
        print(f"neznámý job: {job}", file=sys.stderr)
        return 2
    mod = importlib.import_module(MODULE[job])
    sys.argv = [MODULE[job]] + extra
    try:
        mod.main()
    except SystemExit as e:
        if e.code in (None, 0):
            return 0
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
        return 1 if not isinstance(e.code, int) else e.code
    return 0

# ------------------------------------------------------------------ pomocné
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p

def http(url, method="GET", body=None, headers=None, timeout=5):
    req = Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers or {})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:
        code = getattr(e, "code", None)
        return code or 0, (e.read() if hasattr(e, "read") else b"")

def already_running(port):
    code, body = http(f"http://127.0.0.1:{port}/api/status", timeout=2)
    try:
        return code == 200 and json.loads(body).get("app") == "signaly-desktop"
    except Exception:
        return False

# ------------------------------------------------------------------ kontrola balíčku
def selftest():
    bad = []
    def check(c, m):
        print(("OK   " if c else "FAIL ") + m, flush=True)
        if not c:
            bad.append(m)
    st = static_dir()
    check((st / "index.html").exists() and (st / "app.js").exists() and (st / "sw.js").exists(), f"statická appka ({st})")
    for m in MODULE.values():
        try:
            importlib.import_module(m); check(True, f"import {m}")
        except Exception as e:
            check(False, f"import {m}: {e}")
    try:
        from pipeline import http as H
        s = H._cffi_session() if H._cffi is not None else None
        check(s is not None, f"curl_cffi pro Yahoo (spojení jako {H.IMPERSONATE})")
    except Exception as e:
        check(False, f"curl_cffi: {e}")
    from pipeline import universe
    check((universe.SEEDS / "extras.csv").exists() and (universe.SEEDS / "influencers.csv").exists(), "seed soubory")
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        check(datetime.now(ZoneInfo("Europe/Prague")).tzinfo is not None, "časová zóna Europe/Prague (tzdata)")
    except Exception as e:
        check(False, f"časová zóna: {e}")
    tmp = Path(tempfile.mkdtemp(prefix="signaly-selftest-"))
    txt = "Příliš žluťoučký kůň ▲ ✔ €"
    (tmp / "u.txt").write_text(txt, encoding="utf-8")
    check((tmp / "u.txt").read_text(encoding="utf-8") == txt, "UTF-8 soubory")
    os.environ["SIGNALY_HOME"] = str(tmp)
    home = S.home()
    cfg = dict(S.DEFAULTS, sec_ua="Selftest selftest@example.com")
    sc = Scheduler(home, S.env_for(home, cfg), demo=True, log=lambda m: print("     " + m, flush=True))
    port = free_port()
    ctx = SimpleNamespace(static=st, site=sc.site, home=home, port=port, sched=sc)
    srv = server.start(ctx)
    base = f"http://127.0.0.1:{port}"
    try:
        c, b = http(base + "/api/status")
        check(c == 200 and json.loads(b)["app"] == "signaly-desktop", "API /api/status")
        c, b = http(base + "/")
        check(c == 200 and b"<title>" in b, "statická stránka /")
        c, _ = http(base + "/app.js")
        check(c == 200, "app.js")
        c, _ = http(base + "/api/state", "PUT", {"v": 1, "fav": []})
        check(c == 403, "zápis bez hlavičky X-Signaly je zakázán")
        c, _ = http(base + "/api/state", "PUT", {"v": 1, "fav": []}, {"X-Signaly": "1", "Origin": "http://evil.example"})
        check(c == 403, "zápis s cizím Origin je zakázán")
        c, _ = http(base + "/api/state", "PUT", {"v": 1, "fav": [{"t": "AAPL", "buy": 1}]}, {"X-Signaly": "1", "Content-Type": "application/json"})
        check(c == 200 and json.loads(http(base + "/api/state")[1])["fav"][0]["t"] == "AAPL", "uložení a načtení stavu")
        c, _ = http(base + "/..%2f..%2fsettings.json")
        check(c in (403, 404), "path traversal je zablokován")
        t0 = time.time()
        r1 = sc.tick()
        check(r1 == "demo" and sc.has()["prices"], f"podproces: ukázková data ({int(time.time() - t0)} s)")
        r2 = sc.tick()
        check(r2 == "fast" and sc.has()["signals"], "podproces: fast --demo vytvořil signals.json")
        if sc.has()["signals"]:
            d = json.loads((sc.site / "signals.json").read_text(encoding="utf-8"))
            check(len(d.get("signals", [])) > 0 and len(d.get("market", [])) > 50, f"signals.json: {len(d.get('signals', []))} signálů, {len(d.get('market', []))} firem")
            c, b = http(base + "/data/signals.json")
            check(c == 200 and json.loads(b)["demo"] is True, "server vrací /data/signals.json")
        else:
            print("\n".join(sc.status()["log_tail"]))
    finally:
        sc.shutdown(); srv.shutdown()
    print("\nSELHÁNÍ: %d" % len(bad), flush=True)
    return 1 if bad else 0

# ------------------------------------------------------------------ hlavní program
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"]:
        return run_job(argv[1:])
    utf8.install()
    ap = argparse.ArgumentParser(prog="Signaly", description="Signály – lokální verze (server + plánovač + appka v prohlížeči)")
    ap.add_argument("--demo", action="store_true", help="ukázková syntetická data (bez internetu)")
    ap.add_argument("--no-browser", action="store_true", help="neotevírat prohlížeč")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--autostart", choices=["on", "off"], help="Windows: spouštět s přihlášením")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        print("Signály", __version__); return 0
    if a.selftest:
        return selftest()
    if os.name == "nt":
        os.system("chcp 65001 > nul")
    if a.autostart:
        p = S.autostart(a.autostart == "on", exe=sys.executable)
        print(("Automatické spuštění zapnuto: " if a.autostart == "on" else "Automatické spuštění vypnuto: ") + str(p)); return 0

    base = S.home()
    cfg = S.load(base)
    if not a.demo and not S.valid_ua(cfg["sec_ua"]):
        if sys.stdin and sys.stdin.isatty():
            cfg = S.wizard(cfg); S.save(base, cfg)
        else:
            print("Chybí nastavení (settings.json: sec_ua) – spusť program v okně příkazové řádky pro průvodce."); return 1
    elif not a.demo and not (base / "settings.json").exists():
        S.save(base, cfg)
    home = base / "demo" if a.demo else base
    home.mkdir(parents=True, exist_ok=True)
    port = a.port or int(cfg.get("port") or 8765)
    url = f"http://127.0.0.1:{port}/"
    if already_running(port):
        print("Signály už běží – otevírám prohlížeč."); webbrowser.open(url); return 0
    sc = Scheduler(home, S.env_for(home, cfg), demo=a.demo, log=lambda m: print(m, flush=True))
    ctx = SimpleNamespace(static=static_dir(), site=sc.site, home=home, port=port, sched=sc)
    try:
        srv = server.start(ctx)
    except OSError as e:
        print(f"Port {port} nejde použít ({e}). Zavři program, který ho používá, nebo spusť s --port jiné_číslo."); return 1
    threading.Thread(target=sc.loop, daemon=True).start()
    print(f"\nSignály {__version__} běží na {url}  (data: {home})")
    print("Okno nech otevřené (může být minimalizované) – zavřením se běhy zastaví. Ukončení: Ctrl+C.\n")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nKončím…")
    finally:
        sc.shutdown(); srv.shutdown()
    return 0

if __name__ == "__main__":
    sys.exit(main())
