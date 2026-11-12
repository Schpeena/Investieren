# Signály v4.1 – události světa → akcie a krypto + oblíbené, zisk/ztráta, termíny; cloud (GitHub) i Windows .exe (PWA, GitHub Actions, zdarma)

Statistický nástroj, který z veřejných zdrojů hlídá události, učí se z historie, jak na ně akcie reagovaly,
a posílá nápady k dalšímu zkoumání (vějířový graf ceny, pásma 30/60/90 %). **Není to investiční doporučení.**

## Co v něm je
| Vrstva | Co dělá |
|---|---|
| Univerzum | S&P 500 + Nasdaq-100 (Wikipedia), ~120 evropských firem (STOXX 600 seed) + ČEZ/KB/Moneta/Orlen, ~16 ADR/Asie, 11 makro-ETF (zlato, ropa, plyn, dluhopisy, bitcoin…) |
| Krypto | top 100 podle tržní kapitalizace (seznam CoinGecko, bez stablecoinů a wrapped/staked tokenů; ceny Yahoo `SYMBOL-USD`, záloha CoinGecko 365 d). Samostatná kalendářní tabulka (7 dní v týdnu), benchmark **BTC** (u BTC samotného je abnormální výnos celý výnos), vlastní model C (neobjasněné šoky) a koše BTC / ETH / větší / menší altcoiny v modelu B. Horizont 20 kalendářních dní |
| Vlivní lidé | ~100 jmen v `pipeline/seeds/influencers.csv` (politici, centrální bankéři, tech, investoři, krypto). Zdroje: zmínky v titulcích médií, Truth Social přes veřejné RSS zrcadlo, Bluesky/Mastodon (doplň handle do CSV), volitelně X API. **Apriorní signály** (bez historie), bez notifikací, dokud se jejich směr neověří vlastním vyhodnocením |
| Zdroje | SEC EDGAR 8-K (živě + historie, typ události = číslo položky), GDELT (kódované světové události po 15 min), USGS/GDACS/WHO (katastrofy, ohniska), RSS titulky (skandály firem), ceny Stooq→Yahoo |
| Model A | kvantilový gradient boosting: 8-K položky + neobjasněné cenové šoky → rozdělení 20denní abnormální reakce firmy |
| Model B | kNN analogie: „stav světa“ z GDELT (podíly CAMEO kategorií, horká místa, tón) → rozdělení reakce ~100 košů (sektory, pododvětví, makro-ETF) |
| Ověření | walk-forward: trénink jen na minulosti, test na dalších letech. Model se použije jen tam, kde překoná jednoduchý základ (pinball loss), je stabilní po letech a má správné pokrytí. Směr je „ověřen“ jen při shodě směru ≥ 55 % a ~2σ nad náhodou |
| Vějíř | koncové rozdělení z modelu + tržní složka (beta × volatilita benchmarku) + Brownův most; přerušovaně 90% pásmo bez události |
| Vyhodnocení | **každý** zobrazený signál se zaloguje (`signal_log.json`). Po horizontu (20 pozorování) se odhad porovná se skutečností; u signálů s notifikací přijde po ~30 dnech zpráva „✔ Uzavření signálu (1 měsíc)“ (odhad vs skutečnost, trefa směru, uvnitř/mimo 90% pásma) a po ~91 dnech „(3 měsíce)“ (zda efekt přetrval nebo odezněl). Statistiky podle druhu signálu jsou v záložce **Vyhodnocení** |
| Učení z výsledků | od 40 uzavřených signálů jednoho druhu se **kalibruje šířka vějíře** (násobek 0,7–1,6 podle skutečného pokrytí); od 30 uzavřených se u daného druhu může potvrdit směr (trefa ≥ 55 %, ~2σ) – tím se odemknou notifikace u vlivných osob. Model se přetrénuje týdně na nových datech (workflow `learn`) |
| Signály drží 72 h | signál zůstává v aplikaci 3 dny (`active.json`), ne jen do dalšího běhu |

Co model **ví a neví**: typ události, sektor, volatilitu, nedávný vývoj. Neví nic o textu zprávy ani o výsledku konkrétní události. U většiny typů se ověří jen šířka rozdělení („čekej velký pohyb“), ne směr – appka to u každého signálu říká.

## Moje: oblíbené, vlastní symboly, nákupní cena, nadcházející události
Záložky: **Signály | Moje | Trh | Výsledky | Model | Info**.
- **Vlastní symbol:** v *Trh* napiš do hledání libovolný symbol ve tvaru Yahoo Finance (`AAPL`, `ASML.AS`, `CEZ.PR`, `7203.T`, `BTC-USD`) → „＋ Sledovat“. ★ u firmy/mince (v Trhu i na kartě signálu) ji přidá do oblíbených.
- **Nákupní cena a zisk/ztráta:** v *Moje* vyplň cenu (a volitelně počet kusů). Ukládá se **jen v tvém telefonu** (localStorage) a nikam se neposílá. Aplikace ukazuje aktuální zisk/ztrátu v % (a v měně kotace, když zadáš kusy). Počítá se v **měně kotace** – bez kurzových rozdílů (nákup v Kč a kotace v EUR = nesrovnatelné).
- **Odkud je „živá“ cena** (u každé je napsáno, odkud a jak stará): ① prohlížeč přímo (Binance pro krypto, Yahoo pro akcie – jen pokud to prohlížeč/zdroj dovolí) → ② server (`quotes.json`, obnovuje se každých ~10 min při běhu `fast`; krypto CoinGecko, akcie Stooq s klíčem, jinak Yahoo pro sledované symboly) → ③ poslední uzávěrka. Ceny nejsou realtime burzovní data.
- **Synchronizace se serverem:** aplikace je statická, sama do repa psát nemůže. Tlačítko *Synchronizovat se serverem* otevře předvyplněné GitHub issue (titulek `watchlist`, tělo `{"symbols":[…]}` – **jen symboly**, ne ceny); stačí klepnout *Submit new issue*. Workflow `watchlist` issue přijme **jen od majitele repa**, přidá symboly do univerza, stáhne historii cen a 8-K, spočítá termíny, odpoví komentářem a issue zavře. Pak spustí `fast`, takže data jsou v aplikaci za pár minut. Bez synchronizace appka funguje taky (hvězdičky, zisk/ztráta, vlastní termíny), jen bez serverových cen, signálů a odhadů termínů. V **soukromém** repu jsou issue soukromé; ve **veřejném** je seznam symbolů veřejně čitelný (ceny nákupu ne). Ručně: Actions → `watchlist` → Run workflow → `symbols`.
- **Signály pro sledované:** u sledovaných tickerů jsou nižší prahy (zobrazení i notifikace), takže vidíš i slabší signály. Nové vlastní symboly se do modelů A/B/C připojí až po týdenním `learn` (do té doby mají živé ceny a termíny, ale ne natrénované signály).
- **Upcoming events (u každé oblíbené):** nejbližší předem známé termíny. Typ a jistota je vždy vidět: **potvrzeno** (z Finnhub kalendáře výsledků – vyžaduje volitelný `FINNHUB_KEY`, jen pro sledované symboly), **odhad ±N d** (z historie podání na SEC: loňský termín + 364 dní; N je zpětně změřená typická odchylka) nebo **vlastní** (zadáš ručně). Odhady jsou pro firmy s CIK (USA, ADR): výsledky (8-K 2.02), 10-Q, 10-K/20-F, podklady k valné hromadě (DEF 14A). U **evropských firem a krypta** bez klíče žádné předem známé termíny nemám – přidej vlastní (valná hromada, výsledky z IR kalendáře firmy). Každý termín jde jedním klepnutím do kalendáře (📅, soubor `.ics` s upomínkou den předem). U výsledků je i typický pohyb ceny z historie.
- **Záloha:** *Moje → Záloha a obnovení* – kopie JSON (oblíbené, ceny, vlastní termíny). Data jsou jen v prohlížeči, takže při smazání dat webu nebo přechodu na jiný telefon je potřeba záloha.

## Desktopová verze – Signaly.exe (Windows)
Totéž co cloudová verze, ale bez GitHubu: jediný program na tvém počítači, který stahuje data, počítá signály a zároveň je jako web na `http://127.0.0.1:8765/` (otevře se prohlížeč).
- **Sestavení `.exe`** (Windows soubor se nedá sestavit na Linuxu, proto ho sestaví GitHub): Actions → **build-exe** → Run workflow → po ~15–25 min stáhni artefakt **Signaly-windows** (zip), rozbal, spusť `Signaly\Signaly.exe`. Workflow nejdřív spustí testy a pak `Signaly.exe --selftest` (vytvoří ukázková data v podprocesech a vyzkouší lokální API) – když selže, zip se nevytvoří. Alternativa na vlastním Windows s Pythonem 3.12: `desktop\build_exe.bat`.
- **První spuštění:** průvodce se zeptá na jméno + e-mail (SEC to vyžaduje), na ntfy téma (notifikace na iPhone, volitelné) a na klíče Stooq/Finnhub (volitelné); uloží se do `%LOCALAPPDATA%\Signaly\settings.json`. Potom se na pozadí stáhne historie (cca 30–90 min) a trénují se modely (kola po ~2,5 h, nejvýš 8, dokud není GDELT historie hotová). Appka mezitím ukazuje stav a po prvních cenách sama naskočí na signály (modely se doučí na pozadí).
- **Provoz:** běhy `fast` každých 10 min mezi 8:00 a 24:00 pražského času, `daily` po zavření USA (po vypnutém počítači se dožene), `learn` týdně v noci. Každý běh je podproces s logem v `%LOCALAPPDATA%\Signaly\logs`. Program musí běžet (okno může být minimalizované); `Autostart-zapnout.bat` ho spouští po přihlášení do Windows.
- **Oblíbené a ceny nákupu:** ukládají se do `user_state.json` vedle dat (přežije i smazání dat prohlížeče), seznam symbolů se serveru posílá automaticky (bez klikání na GitHub issue). Ceny nákupu opouštějí jen prohlížeč → program na tomtéž počítači.
- **Rozdíl proti cloudu:** běží jen, když je počítač zapnutý (cloudová verze běží sama); iPhone dál dostává notifikace přes ntfy, ale appka na iPhonu (GitHub Pages) a appka na počítači jsou **dvě samostatné instalace** se samostatnými daty. `Signaly.exe --demo` = ukázková data bez internetu, `Signaly-demo.bat` totéž dvojklikem.
- **Bezpečnost:** server poslouchá jen na 127.0.0.1; zápisy vyžadují hlavičku, kterou cizí web neumí poslat, a kontroluje se Host (ochrana proti DNS rebinding); symboly se validují stejně jako v cloudu. Program není podepsaný → Windows SmartScreen („Počítač byl chráněn“): Další informace → Přesto spustit; antivirus může u PyInstaller programů hlásit falešný poplach.

## Nasazení (jednorázově)
1. Nahraj složku do **veřejného** GitHub repa (u soukromého viz rozpočet níže).
2. Settings → Pages → Source: **GitHub Actions**.
3. Settings → Secrets → Actions: `NTFY_TOPIC` (tajný název tématu, např. `signaly-x7k2q9`), `SEC_UA` (např. `Martin martin@example.cz` – SEC to vyžaduje). Volitelně `STOOQ_APIKEY` (Stooq už pro stahování chce klíč – bez něj se použije pomalejší a křehčí Yahoo; **název parametru `apikey` jsem neověřil**, viz níže) a `FINNHUB_KEY` (zdarma na finnhub.io; potvrzené termíny výsledků).
4. iPhone: appka **ntfy** → přihlásit k tématu. Safari → adresa Pages → Sdílet → Přidat na plochu.
5. Actions → spusť ručně **v tomto pořadí**: `daily` (stáhne ceny od 2012 + 8-K, 30–90 min) → `learn` (GDELT historie + trénink; GDELT se doplňuje obnovitelně, po ~4,5 h se zastaví a další spuštění pokračuje) → `fast`.
6. Krypto: `daily` ho stáhne samo (100 mincí × Yahoo); mince, které Yahoo nezná, se vypíšou do logu a vynechají (aliasy jsou v `prices.YAHOO_ALIAS`).
7. Volitelné: plné STOXX 600 – stáhni holdings CSV z iShares (STOXX Europe 600 UCITS ETF) do `pipeline/seeds/stoxx600.csv`, univerzum se při dalším `daily` rozšíří.

## Časování a limity zdarma
- `fast`: cron `*/10 6-22` UTC + první krok propustí jen 8:00–24:00 pražského času (řeší letní/zimní čas). Mimo okno doběhne za pár sekund.
- `daily` po zavření USA (22:30/23:30), `learn` týdně v sobotu v noci.
- **Veřejné repo: minuty Actions neomezené.** Soukromé: 2000 min/měsíc; `fast` při ~2 min/běh a 10min kroku je ~6000 min → změň cron na `*/30` a odhadem to vyjde na ~2000 (spočítej si po prvním týdnu v záložce Actions).
- Zdroje: SEC max 10 req/s (držíme 6), Stooq/Yahoo neoficiální (denně ~700 požadavků), GDELT a ntfy bez klíče.
- Data se neukládají do gitu, ale do Release `data` (ceny, modely, stav) → repo nebobtná. Web se nasazuje přes Pages artefakt.
- Veřejným repům GitHub po 60 dnech bez aktivity vypíná cron; týdenní `learn` proto případně přidá prázdný commit.

## Co je a není ověřeno
- Logika (parsery, modely, gating, vějíř, frontend) je otestovaná na syntetických datech se **zabudovaným** efektem: model A našel zabudovaný pokles po 5.02 a model B zabudovanou reakci jednoho koše a ostatních 29 košů správně zamítl (`python -m pytest tests`, `--demo`).
- **V reálném provozu zatím nic neběželo.** Můžou se objevit chyby zdrojů: Stooq může chtít klíč, Yahoo bývá z cloudu blokované (429), GDELT v1 denní soubory nemusí pokrývat všechny dny, formát Wikipedie se může změnit. Stav je vidět v záložce **Info → Zdraví dat** a v logu Actions.
- Datumy a tickery v seedech jsem psal z paměti – ověř je. Totéž platí pro seznam influencerů, X handly a Yahoo aliasy kryptoměn.
- **Desktopová verze (`Signaly.exe`):** celý řetěz (balíček PyInstaller, podprocesy, lokální server, plánovač, UI s mockovanými cizími API) je otestovaný na **Linuxu** včetně zamrzlé binárky a simulace Windows kódování (`python -m pytest tests`, `python tests/ui_check_local.py`, `Signaly --selftest`). **Neověřeno:** samotné sestavení a běh ve Windows (ověří až workflow `build-exe` na Windows runneru), SmartScreen/antivirus a reálný provoz doma (SEC, Yahoo, GDELT, CoinGecko z domácí IP).
- **Oblíbené/zisk-ztráta/termíny:** logika je otestovaná (`python -m pytest tests`, 28 testů; `python tests/ui_check.py` (vyžaduje `pip install playwright`) – prohlížečový test na 390×844 se **zamockovanými** odpověďmi Binance/Yahoo). **Neověřeno** (v sandboxu není síť): zda Binance/Yahoo povolí přímé volání z prohlížeče (CORS) – když ne, aplikace tiše použije server/uzávěrku a u ceny to napíše; přesný název parametru Stooq klíče; pokrytí Finnhub free plánu mimo USA; zda iOS ve „standalone“ appce stáhne `.ics` (jinak otevři appku v Safari).
- Krypto, vyhodnocení po 1/3 měsících a detekce příspěvků jsou otestované na syntetických datech a jednotkových testech (`tests/test_features.py`); na živých zdrojích neběžely.
- Krypto má kratší a rozbouřenější historii než akcie: model C a krypto koše B projdou stejným testem, ale s menším počtem událostí je ověření slabší.

## Kam sáhnout
`pipeline/config.py` (prahy, okno, horizont, gating), `pipeline/seeds/extras.csv` (další firmy/ETF), `pipeline/sources/gdelt.py` (horká místa), `pipeline/signals.py` (závažnost, výběr signálů).
Lokální test: `CACHE_DIR=/tmp/c NO_GH=1 python tests/demo_setup.py && CACHE_DIR=/tmp/c NO_GH=1 python -m pipeline.run_fast --demo`.

## Příspěvky vlivných lidí – co jde zdarma a co ne
Výchozí stav (nic nenastavuješ): zmínky v titulcích BBC/NYT/Guardian/Al Jazeera/CNBC/MarketWatch/FT („Musk says…“, „Trump threatens tariffs…“) + Truth Social přes zrcadlo `trumpstruth.org/feed` (neoficiální třetí strana, může se změnit – adresu lze přepsat proměnnou `TRUTH_RSS`).
- **Bluesky / Mastodon:** veřejné API bez účtu; doplň `bluesky` (např. `jmeno.bsky.social`) nebo `mastodon` (`uzivatel@instance`) do `influencers.csv` u lidí, kteří tam opravdu jsou.
- **X (Twitter):** čtení je **placené** (pay-per-use, orientačně 0,005 USD za přečtený příspěvek – ověř v X Developer Console). Vytvoř si vlastní developer účet, vygeneruj Bearer token a ulož ho jako secret `X_BEARER`; počet sledovaných účtů za běh řídí proměnná `X_POLL_USERS` (výchozí 8, nejvlivnější první). Bez klíče je X vypnuté.
- **Truth Social:** oficiální placené „Truth API“ je podle zpráv z léta 2026 určené firmám a cena není veřejná; vlastní účet přístup k datům nedá.
- Signály z příspěvků jsou **apriorní** (téma + tón textu → znaménko a malý efekt). Historie „příspěvek → reakce ceny“ neexistuje, proto se jejich platnost učí až z tvého vlastního vyhodnocení.
- Seznam lidí je výchozí návrh (ne oficiální žebříček); uprav `influencers.csv` – sloupce `weight` (1–3), `aliases` (jednoslovné příjmení se bere jen u `weight ≥ 2`), `tickers` (u firem/mincí spojených s osobou).
