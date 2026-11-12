"""UI kontrola desktopové verze (ne pytest): spustí `python -m desktop.app --demo` ve vlastní složce dat a proklikne appku
(příprava dat -> signály, auto-synchronizace oblíbených, uložení stavu na disk počítače). Použití: python tests/ui_check_local.py [složka_screenshotů]"""
import json, os, pathlib, subprocess, sys, tempfile, time
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots"); SHOTS.mkdir(exist_ok=True, parents=True)
home = pathlib.Path(tempfile.mkdtemp(prefix="signaly-ui-"))
sys.path.insert(0, str(ROOT))
from desktop.app import free_port
port = free_port()
env = dict(os.environ, SIGNALY_HOME=str(home))
proc = subprocess.Popen([sys.executable, "-m", "desktop.app", "--demo", "--no-browser", "--port", str(port)], cwd=ROOT, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
URL = f"http://127.0.0.1:{port}/"

def ok(c, m):
    print(("OK   " if c else "FAIL ") + m, flush=True)
    if not c: ok.bad += 1
ok.bad = 0

try:
    for _ in range(40):
        try:
            import urllib.request; urllib.request.urlopen(URL + "api/status", timeout=1); break
        except Exception: time.sleep(0.5)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="cs-CZ")
        page = ctx.new_page(); errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
        posts = []
        page.on("request", lambda r: posts.append(r.post_data) if r.method == "POST" and r.url.endswith("/api/watchlist") else None)
        ctx.route("https://api.binance.com/**", lambda r: r.fulfill(json=[{"symbol": "BTCUSDT", "price": "50000.00"}], headers={"access-control-allow-origin": "*"}))
        ctx.route("https://query1.finance.yahoo.com/**", lambda r: r.fulfill(status=404, json={}, headers={"access-control-allow-origin": "*"}))
        page.goto(URL)
        page.wait_for_selector(".card")
        first = page.locator("#view").inner_text()
        ok("Příprava dat" in first or page.locator(".chips").count() > 0, "první pohled: příprava dat (nebo už hotové signály)")
        if "Příprava dat" in first:
            page.screenshot(path=str(SHOTS / "local_setup.png"))
            print("      …čekám na první data:", page.locator("#view .card").first.inner_text().replace("\n", " | ")[:120])
        page.wait_for_selector(".chips", timeout=120000)
        ok(True, "appka se po vytvoření dat sama přepnula na signály")
        ok(page.locator(".sig").count() > 0, f"signály zobrazeny ({page.locator('.sig').count()})")

        page.click('nav button[data-tab="market"]'); page.fill("#q", "BTC-USD"); page.click('button.star[data-t="BTC-USD"]')
        page.click('nav button[data-tab="mine"]')
        page.fill('.fav[data-t="BTC-USD"] input.buy', "40000,5")
        page.wait_for_function("document.querySelector('[data-pl=\"BTC-USD\"]').textContent.includes('%')", timeout=8000)
        ok("Server (tento počítač)" in page.locator("#view").inner_text(), "panel Server ukazuje lokální režim (bez GitHub issue)")
        ok(page.locator("a.btn[href*='github.com']").count() == 0, "žádný odkaz na GitHub issue v lokálním režimu")
        t0 = time.time()
        while not posts and time.time() - t0 < 10: page.wait_for_timeout(300)      # (time.sleep by události Playwrightu nezpracoval)
        ok(bool(posts) and json.loads(posts[-1]) == {"symbols": ["BTC-USD"]}, "oblíbené se samy odeslaly serveru (jen symboly): " + (posts[-1] if posts else "–"))
        ok("40000" not in "".join(posts), "cena nákupu se v odeslaném seznamu neposílá")
        page.wait_for_timeout(1200)
        st = json.loads((home / "demo" / "user_state.json").read_text(encoding="utf-8"))
        ok(st["fav"][0]["t"] == "BTC-USD" and st["fav"][0]["buy"] == 40000.5, "stav (včetně nákupní ceny) je uložen v souboru na disku počítače")
        page.evaluate("localStorage.clear()"); page.reload(); page.wait_for_selector(".chips"); page.click('nav button[data-tab="mine"]')
        ok(page.locator('.fav[data-t="BTC-USD"]').count() == 1 and "40000,5" == page.input_value('.fav[data-t="BTC-USD"] input.buy'), "po smazání dat prohlížeče se oblíbené i cena obnoví ze serveru")
        page.screenshot(path=str(SHOTS / "local_mine.png"), full_page=True)
        ok(not errs, "žádné chyby v konzoli: " + "; ".join(errs))
        b.close()
finally:
    proc.terminate()
    try: out = proc.communicate(timeout=10)[0]
    except Exception: out = ""
print("\n--- log programu (konec) ---\n" + "\n".join(out.splitlines()[-8:]))
print("\nSELHÁNÍ:", ok.bad); sys.exit(1 if ok.bad else 0)
