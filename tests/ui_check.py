"""UI kontrola (ne pytest): python tests/ui_check.py [složka_pro_screenshoty] – Playwright proti docs/ (po `python tests/demo_setup.py` + `python -m pipeline.run_fast --demo`).
Binance a Yahoo jsou zamockované (v sandboxu není síť); ověřuje se logika aplikace, ne dostupnost cizích API."""
import json, re, sys, threading, functools, http.server, socketserver, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1] / "docs"
SHOTS = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots"); SHOTS.mkdir(exist_ok=True, parents=True)

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(ROOT)))
port = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{port}/"

def ok(c, m):
    print(("OK   " if c else "FAIL ") + m)
    if not c: ok.bad += 1
ok.bad = 0

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="cs-CZ", accept_downloads=True)
    page = ctx.new_page()
    errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
    ctx.route("https://api.binance.com/**", lambda r: r.fulfill(json=[{"symbol": "BTCUSDT", "price": "50000.00"}, {"symbol": "SOLUSDT", "price": "200.0"}], headers={"access-control-allow-origin": "*"}))
    def yahoo(r):                                   # NEWCO.DE a ZZZCO.DE Yahoo nezná (404), ostatní 120
        if "NEWCO" in r.request.url or "ZZZCO" in r.request.url:
            return r.fulfill(status=404, json={"chart": {"result": None}}, headers={"access-control-allow-origin": "*"})
        r.fulfill(json={"chart": {"result": [{"meta": {"regularMarketPrice": 120.0}}]}}, headers={"access-control-allow-origin": "*"})
    ctx.route("https://query1.finance.yahoo.com/**", yahoo)
    page.goto(URL); page.wait_for_selector(".card")

    # 1) Trh: hvězdička + vlastní symbol
    page.click('nav button[data-tab="market"]'); page.fill("#q", "ASML.AS")
    page.click('button.star[data-t="ASML.AS"]')
    ok(page.locator('button.star.on[data-t="ASML.AS"]').count() == 1, "★ ASML.AS přidána do oblíbených")
    page.fill("#q", "zzzco.de")
    ok(page.locator("[data-addcustom='ZZZCO.DE']").count() == 1, "pro neznámý symbol je nabídka „Přidat vlastní symbol“")
    page.fill("#q", "ab cd")
    ok(page.locator("[data-addcustom]").count() == 0, "neplatný symbol (mezera) se nenabízí")
    page.fill("#q", "BTC-USD"); page.click('button.star[data-t="BTC-USD"]')
    page.fill("#q", "NEWCO.DE"); page.click("[data-addcustom='NEWCO.DE']")
    ok(page.locator('nav button.on[data-tab="mine"]').count() == 1 and page.locator('.fav[data-t="NEWCO.DE"]').count() == 1, "vlastní symbol přidán a otevřena záložka Moje")
    ok("server zatím nemá data" in page.locator('.fav[data-t="NEWCO.DE"]').inner_text(), "symbol, který server sleduje, ale nemá data, to říká")
    page.click('nav button[data-tab="market"]'); page.fill("#q", "ZZZCO.DE"); page.click("[data-addcustom='ZZZCO.DE']")
    ok("čeká na synchronizaci" in page.locator('.fav[data-t="ZZZCO.DE"]').inner_text(), "symbol neznámý serveru je označen jako čekající na synchronizaci")
    page.click('button.star[data-t="ZZZCO.DE"]')
    ok(page.locator('.fav[data-t="ZZZCO.DE"]').count() == 0, "★ bez nákupní ceny odebere hned")

    # 2) nákupní cena -> zisk/ztráta
    page.wait_for_function("document.querySelector('[data-px=\"BTC-USD\"]').textContent.includes('50000')", timeout=5000)
    ok("živě · Binance" in page.locator('[data-src="BTC-USD"]').inner_text(), "BTC: živá cena z Binance (mock)")
    page.fill('.fav[data-t="BTC-USD"] input.buy', "40000")
    ok("+25,0 %" in page.locator('[data-pl="BTC-USD"]').inner_text(), "BTC: nákup 40000 -> +25,0 %: " + page.locator('[data-pl="BTC-USD"]').inner_text())
    page.fill('.fav[data-t="BTC-USD"] input.qty', "0,5")
    ok("+5" in page.locator('[data-pl="BTC-USD"]').inner_text() and "USD" in page.locator('[data-pl="BTC-USD"]').inner_text(), "BTC: s počtem ks ukáže i absolutní zisk: " + page.locator('[data-pl="BTC-USD"]').inner_text())
    page.fill('.fav[data-t="ASML.AS"] input.buy', "100,5")
    ok("živě · Yahoo" in page.locator('[data-src="ASML.AS"]').inner_text(), "ASML.AS: živá cena z Yahoo (mock)")
    ok("+19,4 %" in page.locator('[data-pl="ASML.AS"]').inner_text(), "ASML.AS: 120/100,5 -> +19,4 %: " + page.locator('[data-pl="ASML.AS"]').inner_text())
    ok(page.input_value('.fav[data-t="ASML.AS"] input.buy') == "100,5", "pole se při psaní nepřekresluje")
    page.fill('.fav[data-t="ASML.AS"] input.buy', "")
    ok("zadej nákupní cenu" in page.locator('[data-pl="ASML.AS"]').inner_text(), "prázdná nákupní cena -> výzva")
    page.fill('.fav[data-t="ASML.AS"] input.buy', "abc")
    ok(json.loads(page.evaluate("localStorage.getItem('signaly.v1')"))["fav"][0]["buy"] is None, "neplatný vstup se neuloží jako číslo")
    page.fill('.fav[data-t="ASML.AS"] input.buy', "100,5")

    # 3) události
    page.click('.fav[data-t="ASML.AS"] .row')
    ev = page.locator('.fav[data-t="ASML.AS"] .detail .ev')
    ok(ev.count() >= 2, f"upcoming events: {ev.count()} termínů")
    print("     ", [e.replace("\n", " ")[:90] for e in ev.all_inner_texts()[:4]])
    ok("odhad ±" in page.locator('.fav[data-t="ASML.AS"] .detail').inner_text(), "odhady jsou označeny jako odhad se nejistotou ve dnech")
    page.fill('.fav[data-t="ASML.AS"] .evd', "2027-03-01"); page.fill('.fav[data-t="ASML.AS"] .evt', "Valná hromada | test")
    page.click('[data-addev="ASML.AS"]')
    ok("Valná hromada | test" in page.locator('.fav[data-t="ASML.AS"] .detail').inner_text(), "vlastní událost přidána")
    href = page.locator('.fav[data-t="ASML.AS"] .ev', has_text="Valná hromada").locator("a[download]").get_attribute("href")
    ics = __import__("urllib.parse").parse.unquote(href.split(",", 1)[1])
    ok("BEGIN:VEVENT" in ics and "DTSTART;VALUE=DATE:20270301" in ics and "TRIGGER:-P1D" in ics, "ICS export (celodenní událost + upomínka den předem)")
    page.click('[data-delev^="ASML.AS|2027-03-01|Valná hromada | test"]')
    ok("Valná hromada" not in page.locator('.fav[data-t="ASML.AS"] .detail').inner_text(), "vlastní událost smazána (název obsahuje |)")
    page.fill('.fav[data-t="ASML.AS"] .evd', "2027-03-01"); page.fill('.fav[data-t="ASML.AS"] .evt', "Dny investorů")
    page.click('[data-addev="ASML.AS"]')

    # 4) perzistence + záloha
    page.reload(); page.wait_for_selector(".card"); page.click('nav button[data-tab="mine"]')
    ok(page.locator(".fav").count() == 3, "po obnovení stránky zůstaly 3 oblíbené")
    ok("100,5" in page.input_value('.fav[data-t="ASML.AS"] input.buy') or page.input_value('.fav[data-t="ASML.AS"] input.buy') == "100.5", "nákupní cena přežila reload")
    bk = page.input_value("#bk") if page.locator("#bk").is_visible() else page.evaluate("document.querySelector('#bk').value")
    page.evaluate("localStorage.clear()"); page.reload(); page.wait_for_selector(".card"); page.click('nav button[data-tab="mine"]')
    ok(page.locator(".fav").count() == 0, "po smazání úložiště je prázdno")
    page.locator("details summary").click(); page.fill("#bk", bk)
    page.click("#bkload"); ok(page.locator(".fav").count() == 0, "obnova vyžaduje druhé klepnutí")
    page.click("#bkload")
    ok(page.locator(".fav").count() == 3 and "Dny investorů" in page.evaluate("localStorage.getItem('signaly.v1')"), "záloha obnovena (3 oblíbené + vlastní událost)")
    page.locator("details summary").click(); page.fill("#bk", '{"v":1,"fav":[{"t":"<img src=x onerror=alert(1)>","buy":5},{"t":"aapl","buy":"-3","qty":"x"}],"ev":{"AAPL":[{"d":"2027-02-30","title":"x"}]},"cfg":{"repo":"a/b c"}}')
    page.click("#bkload"); page.click("#bkload")
    st = json.loads(page.evaluate("localStorage.getItem('signaly.v1')"))
    ok([f["t"] for f in st["fav"]] == ["AAPL"] and st["fav"][0]["buy"] is None and not st["ev"] and not st["cfg"], "obnova zahodí nevalidní symboly/ceny/data/repo: " + json.dumps(st)[:120])

    # 5) synchronizace
    page.evaluate("localStorage.setItem('signaly.v1', JSON.stringify({v:1,fav:[{t:'ASML.AS',name:'ASML',buy:100.5,qty:null,add:''}],ev:{},cfg:{repo:'martin/signaly'}}))")
    page.reload(); page.wait_for_selector(".card"); page.click('nav button[data-tab="mine"]')
    h = page.locator("a.btn").get_attribute("href")
    ok(h.startswith("https://github.com/martin/signaly/issues/new?title=watchlist&body=") and "100" not in h.split("body=")[1], "odkaz na issue obsahuje jen symboly, ne ceny: " + h)
    ok(json.loads(__import__("urllib.parse").parse.unquote(h.split("body=")[1])) == {"symbols": ["ASML.AS"]}, "tělo issue je platný JSON se symboly")

    # 6) signály a filtr Moje
    page.click('nav button[data-tab="signals"]'); page.click('.chip[data-f="mine"]')
    print("      signály pro oblíbené:", page.locator(".sig").count())

    # 7) screenshoty
    page.evaluate("localStorage.setItem('signaly.v1', JSON.stringify({v:1,fav:[{t:'ASML.AS',name:'ASML',buy:100.5,qty:10,add:''},{t:'BTC-USD',name:'Bitcoin',buy:40000,qty:0.5,add:''},{t:'SAP.DE',name:'SAP',buy:null,qty:null,add:''},{t:'NEWCO.DE',name:'NEWCO.DE',buy:null,qty:null,add:''}],ev:{'SAP.DE':[{d:'2027-02-10',title:'Capital Markets Day'}]},cfg:{}}))")
    page.reload(); page.wait_for_selector(".card"); page.click('nav button[data-tab="mine"]'); page.wait_for_timeout(600)
    page.screenshot(path=str(SHOTS / "mine.png"), full_page=True)
    page.click('.fav[data-t="ASML.AS"] .row'); page.wait_for_timeout(200)
    page.locator('.fav[data-t="ASML.AS"]').screenshot(path=str(SHOTS / "mine_open.png"))
    page.click('nav button[data-tab="market"]'); page.fill("#q", "ZZZ.DE"); page.screenshot(path=str(SHOTS / "market_custom.png"))
    page.click('nav button[data-tab="signals"]'); page.wait_for_timeout(200); page.screenshot(path=str(SHOTS / "signals.png"))
    ok(not errs, "žádné chyby v konzoli: " + "; ".join(errs))
    b.close()
print("\nSELHÁNÍ:", ok.bad); sys.exit(1 if ok.bad else 0)
