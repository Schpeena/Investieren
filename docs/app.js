const $ = s => document.querySelector(s);
const pct = (x, d = 1) => x == null ? "–" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d).replace(".", ",") + " %";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const dm = d => { const [y, m, dd] = d.split("-"); return `${+dd}.${+m}.`; };
let D = null, tab = "signals", open = null, filter = "all", query = "";
const KIND = { "8k": "Firemní (8-K)", shock: "Cenový šok", world: "Svět", hazard: "Příroda/zdraví", scandal: "Skandál", influencer: "Vlivná osoba" };
const KIND_FULL = k => { const [a, kk] = k.split(":"); return (a === "crypto" ? "Krypto · " : "Akcie · ") + (KIND[kk] || kk); };
const fmt = v => v >= 1000 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v >= 1 ? v.toFixed(2) : v.toFixed(4);
const ago = h => h == null ? "" : h < 1 ? "před chvílí" : h < 48 ? `před ${Math.round(h)} h` : `před ${Math.round(h / 24)} d`;

function fanChart(f) {
  const W = 340, H = 210, L = 40, R = 8, T = 8, B = 22, n = f.dates.length;
  const all = [].concat(...Object.values(f.q), f.baseline, f.base_lo, f.base_hi);
  let lo = Math.min(...all), hi = Math.max(...all); const pad = (hi - lo) * .06; lo -= pad; hi += pad;
  const x = i => L + (W - L - R) * i / (n - 1), y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const band = (a, b, cls) => `<polygon points="${f.q[a].map((v, i) => `${x(i)},${y(v)}`).concat(f.q[b].map((v, i) => `${x(i)},${y(v)}`).reverse()).join(" ")}" fill="var(--${cls})"/>`;
  const line = (arr, extra) => `<polyline fill="none" ${extra} points="${arr.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>`;
  let g = "";
  for (let k = 0; k <= 3; k++) { const v = lo + (hi - lo) * k / 3; g += `<line class="axis" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="lbl" x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${fmt(v)}</text>`; }
  for (const i of [0, 5, 10, 15, n - 1]) g += `<text class="lbl" x="${x(i)}" y="${H - 6}" text-anchor="middle">${dm(f.dates[i])}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Vějířový graf ceny">${g}
    ${band("5", "95", "b1")}${band("20", "80", "b2")}${band("35", "65", "b3")}
    ${line(f.base_lo, 'stroke="var(--mu)" stroke-dasharray="2 3" stroke-width="1"')}${line(f.base_hi, 'stroke="var(--mu)" stroke-dasharray="2 3" stroke-width="1"')}
    ${line(f.q["50"], 'stroke="var(--ac)" stroke-width="2"')}
    <circle cx="${x(0)}" cy="${y(f.spot)}" r="3.5" fill="var(--tx)"/></svg>
    <div class="legend"><span><i class="sw" style="background:var(--b3)"></i>30 %</span><span><i class="sw" style="background:var(--b2)"></i>60 %</span><span><i class="sw" style="background:var(--b1)"></i>90 %</span><span>— medián</span><span>··· 90% pásmo bez události</span></div>`;
}
function spark(p) {
  if (!p) return "";
  const W = 110, H = 30, lo = Math.min(0, ...p), hi = Math.max(0, ...p), r = (hi - lo) || 1;
  const pts = p.map((v, i) => `${(W * i / (p.length - 1)).toFixed(1)},${(H - 3 - (H - 6) * (v - lo) / r).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${W} ${H}" style="width:110px"><polyline fill="none" stroke="var(--ac)" stroke-width="1.6" points="${pts}"/></svg>`;
}
const confPill = s => s.confidence === "vyšší" ? "ok" : s.confidence === "nízká" ? "warn" : "";
function card(s) {
  const up = s.direction > 0, c = up ? "up" : "dn", st = s.stats, isOpen = open === s.id;
  let h = `<div class="card sig" data-id="${esc(s.id)}"><div class="row"><div>${starBtn(s.ticker, s.name)} <span class="tk">${esc(s.ticker)}</span> <span class="muted">${esc(s.name)}</span></div>
    <div class="${c}"><b>${up ? "▲" : "▼"} ${pct(st.med20)}</b><span class="muted"> medián 20 d</span></div></div>
    <div class="hl">${esc(s.title)}</div>
    <div>${s.asset === "crypto" ? '<span class="pill crypto">krypto</span>' : ""}<span class="pill">${KIND[s.kind] || s.kind}</span><span class="pill">${esc(s.type_label)}</span><span class="pill ${confPill(s)}">jistota: ${s.confidence}</span><span class="pill">závažnost ${s.severity.toFixed(1)}</span>${s.age_h != null ? `<span class="pill">${ago(s.age_h)}</span>` : ""}</div>`;
  if (isOpen) {
    const verdict = s.model === "prior" ? "Apriorní předpoklad – nemá natrénovaný ani ověřený model." :
      `Model: ${s.model === "knn" ? "analogie světových dní (kNN)" : s.model === "gbm" ? "kvantilový GBM" : s.model === "item" ? "empirické rozdělení pro tento typ" : "základní rozdělení"}. Šířka rozdělení ${s.width_verified ? "ověřena" : "neověřena"}, směr ${s.direction_verified ? "<b>ověřen</b>" : "<b>neověřen</b> (ber jako riziko pohybu, ne jako směr)"} v out-of-sample testu.`;
    h += `<div class="detail"><div class="muted">${verdict}</div>
      <div class="muted">Cena ${s.fan.spot} (${dm(s.fan.spot_date)}) · šance růstu za ${D.horizon} ${s.asset === "crypto" ? "dní" : "obch. dnů"}: <b>${Math.round(s.fan.prob_up * 100)} %</b> · 90% rozpětí (vs ${s.asset === "crypto" ? "BTC" : "trh"}): ${pct(st.p5, 0)} až ${pct(st.p95, 0)}${s.calibrated ? ` · šířka vějíře upravena ×${s.calibrated} podle vlastního vyhodnocení` : ""}</div>
      ${s.evidence ? `<div class="muted">Osoba: <b>${esc(s.evidence.person)}</b> (${esc(s.evidence.category)}) · zdroje: ${s.evidence.sources.map(esc).join(", ")} · tón textu ${s.evidence.tone > 0 ? "+" : ""}${s.evidence.tone}. Znaménko vychází z tématu/tónu textu, ne z naučené historie.</div>` : ""}
      ${fanChart(s.fan)}
      ${s.drivers ? `<div class="muted">Co je neobvyklé: ${s.drivers.map(d => `${esc(d.feature)} (${d.z > 0 ? "+" : ""}${d.z}σ)`).join(", ")}</div>` : ""}
      <h2>Historické paralely</h2>
      <table><tr><th>Datum</th><th>Událost</th><th></th><th class="n">20 d</th></tr>
      ${s.analogs.map(a => `<tr><td>${a.date}</td><td>${esc(a.desc)}</td><td>${spark(a.path)}</td><td class="n ${a.car20 >= 0 ? "up" : "dn"}">${pct(a.car20)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">Bez historických záznamů.</td></tr>'}</table>
      <p class="muted">${s.link ? `<a href="${esc(s.link)}" target="_blank" rel="noopener">Zdroj</a> · ` : ""}Statistický nápad k dalšímu zkoumání, ne doporučení.</p></div>`;
  }
  return h + "</div>";
}
// ================= lokální stav (jen v tomto telefonu; ceny nákupu se nikam neposílají) =================
const LS = "signaly.v1";
let S = { v: 1, fav: [], ev: {}, cfg: {} }, storeOk = true, openFav = null, flash = "";
try { const j = JSON.parse(localStorage.getItem(LS) || "null"); if (j && j.v === 1) S = { v: 1, fav: j.fav || [], ev: j.ev || {}, cfg: j.cfg || {} }; } catch (e) { storeOk = false; }
let LOCAL = null, lastSynced = null, pushT = null, syncT = null, dataVer = 0, metaBase = "";      // LOCAL = stav desktopové verze (Signaly.exe), jinak null
const save = () => { try { localStorage.setItem(LS, JSON.stringify(S)); storeOk = true; } catch (e) { storeOk = false; } if (LOCAL) { pushState(); syncSoon(); } };
const favKey = () => S.fav.map(f => f.t).sort().join(",");
async function localApi(method, path, body) {
  const r = await fetch(path, { method, headers: { "X-Signaly": "1", "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) throw new Error(r.status); return r.json();
}
function pushState() { clearTimeout(pushT); pushT = setTimeout(() => localApi("PUT", "api/state", S).catch(() => {}), 500); }
function syncSoon() { if (favKey() === lastSynced) return; clearTimeout(syncT); syncT = setTimeout(() => syncNow(false), 2500); }
async function syncNow(manual) {
  const key = favKey();
  try { await localApi("POST", "api/watchlist", { symbols: S.fav.map(f => f.t) }); lastSynced = key; if (manual) flash = "Seznam odeslán serveru na tomto počítači. Data se doplní během chvíle (stav nahoře)."; pollLocal(); }
  catch (e) { if (manual) flash = "Server na počítači neodpovídá."; }
  if (manual && tab === "mine") render();
}
const favOf = t => S.fav.find(f => f.t === t), isFav = t => !!favOf(t);
function toggleFav(t, name) { const i = S.fav.findIndex(f => f.t === t); if (i >= 0) S.fav.splice(i, 1); else S.fav.push({ t, name: name || t, buy: null, qty: null, add: new Date().toISOString() }); save(); }
const num = v => { const x = parseFloat(String(v ?? "").replace(/\s/g, "").replace(",", ".")); return isFinite(x) && x > 0 ? x : null; };
const CCY = { ".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR", ".HE": "EUR", ".VI": "EUR", ".BR": "EUR", ".LS": "EUR", ".IR": "EUR", ".L": "GBp", ".SW": "CHF", ".ST": "SEK", ".CO": "DKK", ".OL": "NOK", ".WA": "PLN", ".PR": "CZK", ".T": "JPY", ".HK": "HKD", ".KS": "KRW", ".TO": "CAD" };
const ccy = t => /-USD$/.test(t) ? "USD" : t.includes(".") ? (CCY[t.slice(t.lastIndexOf("."))] || "") : "USD";
const SYM_RE = /^[A-Za-z0-9][A-Za-z0-9.\-=^]{0,14}$/;
let MK = {}, SQ = {}, SQ_ASOF = null, LQ = {}, EV = null, yahooOk = true, live = false;

// ---------- ceny: živě z prohlížeče (Binance pro krypto, Yahoo pokud to prohlížeč dovolí) > server (quotes.json) > uzávěrka ----------
async function getJSON(url, ms = 6000) { const c = new AbortController(), to = setTimeout(() => c.abort(), ms); try { const r = await fetch(url, { signal: c.signal }); if (!r.ok) throw new Error(r.status); return await r.json(); } finally { clearTimeout(to); } }
async function loadServerQuotes() { try { const j = await getJSON("data/quotes.json?" + Date.now()); SQ = j.q || {}; SQ_ASOF = j.asof; } catch (e) {} }
async function loadEvents() { try { EV = await getJSON("data/events.json?" + Date.now()); } catch (e) { EV = null; } }
async function loadLive() {
  const favs = S.fav.map(f => f.t), cr = favs.filter(t => /-USD$/.test(t)), st = favs.filter(t => !/-USD$/.test(t));
  const jobs = [];
  if (cr.length) jobs.push(getJSON("https://api.binance.com/api/v3/ticker/price", 8000).then(j => { const m = Object.fromEntries(j.map(x => [x.symbol, +x.price])); cr.forEach(t => { const p = m[t.replace("-USD", "") + "USDT"]; if (p) LQ[t] = { p, ts: Date.now(), src: "Binance" }; }); }).catch(() => {}));
  if (yahooOk) st.slice(0, 25).forEach(t => jobs.push(getJSON("https://query1.finance.yahoo.com/v8/finance/chart/" + encodeURIComponent(t) + "?range=1d&interval=5m").then(j => { const m = j.chart.result[0].meta; if (m && m.regularMarketPrice) LQ[t] = { p: +m.regularMarketPrice, ts: Date.now(), src: "Yahoo" }; }).catch(e => { if (e instanceof TypeError) yahooOk = false; })));
  await Promise.allSettled(jobs);
}
function priceOf(t) {
  const now = Date.now(), l = LQ[t];
  if (l && now - l.ts < 5 * 60e3) return { p: l.p, src: "živě · " + l.src, age: 0 };
  const q = SQ[t];
  if (q) { const age = Math.max(0, (now - Date.parse(q.t)) / 6e4); return { p: q.p, src: "server · " + q.src + " · " + ago2(age), age }; }
  const m = MK[t]; if (m) return { p: m.spot, src: "poslední uzávěrka", age: null };
  return null;
}
const ago2 = m => m < 2 ? "právě teď" : m < 90 ? `před ${Math.round(m)} min` : m < 2880 ? `před ${Math.round(m / 60)} h` : `před ${Math.round(m / 1440)} d`;
const fc = v => fmt(v).replace(".", ",");
const plOf = f => { const q = priceOf(f.t); return q && f.buy ? q.p / f.buy - 1 : null; };
const plHtml = f => { const pl = plOf(f), q = priceOf(f.t); if (pl == null) return f.buy ? "" : '<span class="muted">zadej nákupní cenu</span>'; const abs = f.qty ? ` <span class="muted">(${(q.p - f.buy) * f.qty >= 0 ? "+" : "−"}${fc(Math.abs((q.p - f.buy) * f.qty))} ${ccy(f.t)})</span>` : ""; return `<span class="${pl >= 0 ? "up" : "dn"}"><b>${pct(pl)}</b></span>${abs}`; };

// ---------- události: server (odhady ze SEC, potvrzené z Finnhubu) + vlastní (jen v telefonu) ----------
const today0 = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };
const daysTo = d => Math.round((new Date(d + "T00:00:00").getTime() - today0()) / 864e5);
const eventsOf = t => [...((EV && EV.by_ticker && EV.by_ticker[t]) || []), ...((S.ev[t] || []).map(e => ({ date: e.d, title: e.title, user: true, confirmed: true })))].filter(e => daysTo(e.date) >= 0).sort((a, b) => a.date.localeCompare(b.date));
const evBadge = e => e.user ? "vlastní" : e.confirmed ? "potvrzeno" : `odhad ±${e.err ?? "?"} d`;
const inDays = n => n === 0 ? "dnes" : n === 1 ? "zítra" : `za ${n} d`;
function icsHref(t, e) {
  const d = e.date.replace(/-/g, ""), end = new Date(Date.parse(e.date + "T00:00:00Z") + 864e5).toISOString().slice(0, 10).replace(/-/g, "");
  const x = v => String(v).replace(/[\;,]/g, m => "\\" + m).replace(/\n/g, "\\n");
  const body = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Signaly//CS", "BEGIN:VEVENT", `UID:${t}-${d}-${e.title.length}@signaly`, `DTSTAMP:${new Date().toISOString().replace(/[-:]|\.\d+/g, "")}`,
    `DTSTART;VALUE=DATE:${d}`, `DTEND;VALUE=DATE:${end}`, `SUMMARY:${x(t + " – " + e.title)}`, `DESCRIPTION:${x(evBadge(e) + (e.src ? " · " + e.src : ""))}`, "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", `DESCRIPTION:${x("Zítra: " + t + " – " + e.title)}`, "END:VALARM", "END:VEVENT", "END:VCALENDAR"].join("\r\n");
  return "data:text/calendar;charset=utf-8," + encodeURIComponent(body);
}
const evRow = (t, e, del) => `<div class="ev"><div><b>${dm(e.date)}${e.date.slice(0, 4) !== String(new Date().getFullYear()) ? e.date.slice(0, 4) : ""}</b> <span class="muted">${inDays(daysTo(e.date))}</span> ${esc(e.title)} <span class="pill ${e.confirmed ? "ok" : ""}">${evBadge(e)}</span></div><div class="evb"><a href="${icsHref(t, e)}" download="${esc(t)}-${e.date}.ics" title="Přidat do kalendáře">📅</a>${del ? `<button class="x" data-delev="${esc(t)}|${e.date}|${esc(e.title)}" title="Smazat">✕</button>` : ""}</div></div>`;

// ---------- synchronizace se serverem: předvyplněné GitHub issue (posílají se JEN symboly, ne ceny) ----------
function repoSlug() { if (S.cfg.repo) return S.cfg.repo; const h = location.hostname; if (h.endsWith(".github.io")) { const seg = location.pathname.split("/")[1]; return h.split(".")[0] + "/" + (seg && !seg.includes(".") ? seg : h); } return ""; }
const syncUrl = () => { const r = repoSlug(); return r ? `https://github.com/${r}/issues/new?title=watchlist&body=${encodeURIComponent(JSON.stringify({ symbols: S.fav.map(f => f.t) }))}` : ""; };

// ---------- karty a pohledy pro „Moje“ ----------
const starBtn = (t, n) => `<button class="star ${isFav(t) ? "on" : ""}" data-t="${esc(t)}" data-n="${esc(n || t)}" aria-label="Oblíbené">${isFav(t) ? "★" : "☆"}</button>`;
function favCard(f) {
  const t = f.t, m = MK[t], q = priceOf(t), c = ccy(t), isOpen = openFav === t, nx = eventsOf(t)[0], sg = (D.signals || []).filter(s => s.ticker === t);
  const wait = !q ? `<span class="muted">${(D.watch || []).includes(t) ? "server zatím nemá data (první běh po synchronizaci)" : "čeká na synchronizaci – zatím bez dat"}</span>` : "";
  let h = `<div class="card fav" data-t="${esc(t)}"><div class="row"><div>${starBtn(t, f.name)} <span class="tk">${esc(t)}</span> <span class="muted">${esc(m ? m.name : f.name)}</span></div>
    <div class="r"><b class="px" data-px="${esc(t)}">${q ? fc(q.p) : "–"}</b> <span class="muted">${c}</span></div></div>
    <div class="row"><span class="muted src" data-src="${esc(t)}">${q ? esc(q.src) : wait}</span><span class="plc" data-pl="${esc(t)}">${plHtml(f)}</span></div>
    <div class="inputs"><label>Nákupní cena (${c || "měna kotace"})<input class="buy" inputmode="decimal" placeholder="např. 123,45" value="${f.buy == null ? "" : String(f.buy).replace(".", ",")}" data-t="${esc(t)}"></label>
    <label>Počet ks (nepovinné)<input class="qty" inputmode="decimal" placeholder="ks" value="${f.qty == null ? "" : String(f.qty).replace(".", ",")}" data-t="${esc(t)}"></label></div>
    <div class="muted">${nx ? `📅 ${esc(nx.title)} ${inDays(daysTo(nx.date))} (${dm(nx.date)}) · ${evBadge(nx)}` : "📅 Žádný předem známý termín"}${sg.length ? ` · <b>${sg.length}× signál</b>` : ""}</div>`;
  if (isOpen) {
    const evs = eventsOf(t), ty = EV && EV.typical && EV.typical[t], le = EV && EV.last_earnings && EV.last_earnings[t];
    h += `<div class="detail"><h2 style="margin-top:0">Upcoming events</h2>${evs.map(e => evRow(t, e, e.user)).join("") || `<div class="muted">Žádné předem známé termíny. ${/\.|-USD/.test(t) ? "U evropských firem a krypta je nezjistím bez placeného zdroje (nebo Finnhub klíče) – přidej vlastní." : "Zatím chybí historie podání na SEC."}</div>`}
      <div class="inputs evadd"><input type="date" class="evd" data-t="${esc(t)}"><input type="text" class="evt" placeholder="Název (např. valná hromada)" data-t="${esc(t)}"><button class="btn" data-addev="${esc(t)}">Přidat</button></div>
      ${le ? `<div class="muted">Poslední výsledky (8-K 2.02): ${dm(le)}${le.slice(0, 4)}.</div>` : ""}
      ${ty ? `<div class="muted">Historicky se po výsledcích hýbala o ±${(ty.m1 * 100).toFixed(1).replace(".", ",")} % za 1 den a ±${(ty.m5 * 100).toFixed(1).replace(".", ",")} % za 5 dní (medián abnormálního pohybu vs trh, ${ty.n} případů).</div>` : ""}
      ${sg.length ? `<h2>Aktivní signály</h2>${sg.map(s => `<div class="muted">${s.direction > 0 ? "▲" : "▼"} ${esc(s.type_label)} · medián ${pct(s.stats.med20)} · ${esc(s.title.slice(0, 90))}</div>`).join("")}` : ""}
      ${m ? `<div class="muted">Sektor: ${esc(m.sector)} · poslední uzávěrka ${fmt(m.spot)} (${pct(m.chg1d)} za 1 d)</div>` : ""}
      <p><button class="btn warn" data-rm="${esc(t)}">Odebrat z oblíbených</button></p></div>`;
  }
  return h + "</div>";
}
function serverCard(unsynced, url) {
  if (LOCAL) return `<div class="card"><h2 style="margin-top:0">Server (tento počítač)</h2><div class="muted">${esc(LOCAL.phase)}. Sleduje ${(D.watch || []).length} symbolů. ${unsynced.length ? `<b>Čeká na zpracování: ${unsynced.map(esc).join(", ")}</b> (odesílá se automaticky)` : "Vše synchronizováno."} Ceny nákupu zůstávají v tomto počítači.</div><p><button class="btn" id="syncnow">Synchronizovat teď</button></p></div>`;
  return `<div class="card"><h2 style="margin-top:0">Server (živé ceny, signály, historie)</h2><div class="muted">Server sleduje: ${(D.watch || []).length} symbolů. ${unsynced.length ? `<b>Nesynchronizováno: ${unsynced.map(esc).join(", ")}</b>` : "Vše synchronizováno."} Posílají se jen symboly, ne ceny nákupu. GitHub otevře předvyplněné issue – stačí klepnout na „Submit new issue“.</div>
    ${url ? `<p><a class="btn" href="${url}" target="_blank" rel="noopener">Synchronizovat se serverem</a></p>` : '<div class="muted">Adresu repa nepoznám – vyplň níž (vlastník/repo).</div>'}
    <input class="q" id="repo" placeholder="vlastník/repo (jen pokud neběží na github.io)" value="${esc(S.cfg.repo || "")}"></div>`;
}
function mineView() {
  const favs = S.fav, withBuy = favs.filter(f => plOf(f) != null), avg = withBuy.length >= 2 ? withBuy.reduce((a, f) => a + plOf(f), 0) / withBuy.length : null;
  const unsynced = favs.filter(f => !(D.watch || []).includes(f.t)).map(f => f.t), url = LOCAL ? "" : syncUrl();
  const up = []; favs.forEach(f => eventsOf(f.t).forEach(e => up.push({ t: f.t, e }))); up.sort((a, b) => a.e.date.localeCompare(b.e.date));
  let h = `${storeOk ? "" : '<div class="card warn-card">Úložiště prohlížeče není dostupné (soukromé okno?) – oblíbené se po zavření ztratí. Dělej zálohu níže.</div>'}${flash ? `<div class="card ok-card">${esc(flash)}</div>` : ""}`;
  if (!favs.length) h += '<div class="card muted">Zatím nic nesleduješ. V záložce <b>Trh</b> nebo na kartě signálu klepni na ☆. Libovolný symbol (např. <b>ASML.AS</b>, <b>CEZ.PR</b>, <b>BTC-USD</b>) přidáš v Trhu zadáním do hledání.</div>';
  else {
    h += `<div class="card"><div class="kv"><span>Oblíbených</span><span>${favs.length}</span></div>${avg != null ? `<div class="kv"><span>Prostý průměr zisku/ztráty (jen z titulů s nákupní cenou)</span><span class="${avg >= 0 ? "up" : "dn"}">${pct(avg)}</span></div>` : ""}
      <div class="kv"><span>Živé ceny z prohlížeče</span><span>${live ? "ano" : "zatím ne – použit server"}</span></div></div>`;
    if (up.length) h += `<h2>Nadcházející události oblíbených</h2><div class="card">${up.slice(0, 8).map(x => `<div class="muted" style="margin-bottom:2px"><b class="tk2">${esc(x.t)}</b></div>${evRow(x.t, x.e, false)}`).join("")}</div>`;
    h += favs.map(favCard).join("");
  }
  h += serverCard(unsynced, url);
  h += `<details class="card"><summary>Záloha a obnovení (${LOCAL ? "záloha je i na disku počítače" : "data jsou jen v tomto telefonu"})</summary><textarea id="bk" rows="5">${esc(JSON.stringify(S))}</textarea>
    <p><button class="btn" id="bkcopy">Kopírovat</button> <button class="btn warn" id="bkload">Obnovit ze zálohy (přepíše)</button></p></details>`;
  return h;
}
let rmArm = null, bkArm = false;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/, validDate = d => DATE_RE.test(d) && !isNaN(Date.parse(d + "T00:00:00Z")) && new Date(d + "T00:00:00Z").toISOString().slice(0, 10) === d;
function sanitizeState(j) {                       // záloha z textového pole je nedůvěryhodný vstup: vše se validuje
  if (!j || j.v !== 1 || !Array.isArray(j.fav)) throw new Error("neplatný formát");
  const out = { v: 1, fav: [], ev: {}, cfg: {} };
  for (const f of j.fav.slice(0, 200)) {
    const t = String(f && f.t || "").toUpperCase(); if (!SYM_RE.test(t) || out.fav.some(x => x.t === t)) continue;
    out.fav.push({ t, name: String(f.name || t).slice(0, 80), buy: num(f.buy), qty: num(f.qty), add: String(f.add || "").slice(0, 40) });
  }
  for (const [t, arr] of Object.entries(j.ev || {})) {
    if (!SYM_RE.test(t) || !Array.isArray(arr)) continue;
    const ok = arr.filter(e => e && validDate(String(e.d)) && String(e.title || "").trim()).slice(0, 50).map(e => ({ d: String(e.d), title: String(e.title).trim().slice(0, 80) }));
    if (ok.length) out.ev[t.toUpperCase()] = ok;
  }
  const r = String(j.cfg && j.cfg.repo || ""); if (/^[\w.-]{1,40}\/[\w.-]{1,100}$/.test(r)) out.cfg.repo = r;
  return out;
}
function removeFav(t) { const f = favOf(t); if (!f) return; if (f.buy && rmArm !== t) { rmArm = t; flash = `Klepni na ★ / „Odebrat“ u ${t} ještě jednou – smaže i nákupní cenu.`; return render(); } rmArm = null; flash = ""; toggleFav(t); if (openFav === t) openFav = null; render(); }

document.addEventListener("click", e => {
  const el = e.target.closest("button,summary"); if (!el) return;
  const d = el.dataset;
  if (rmArm && !(d.rm === rmArm || (el.classList.contains("star") && d.t === rmArm))) { rmArm = null; flash = ""; }
  if (el.classList.contains("star")) { if (isFav(d.t)) removeFav(d.t); else { toggleFav(d.t, d.n); flash = ""; render(); if (tab === "mine") refreshPrices(); } return; }
  if (d.addcustom) { const t = d.addcustom.toUpperCase(); if (!isFav(t)) toggleFav(t, t); flash = `Přidáno: ${t}. Server o něm ví až po synchronizaci (dole). Cena a termíny se doplní, jakmile pro něj budou data.`; query = ""; tab = "mine"; openFav = t; render(); window.scrollTo(0, 0); refreshPrices(); return; }
  if (d.rm) return removeFav(d.rm);
  if (d.addev) {
    const card = el.closest(".fav"), dt = card.querySelector(".evd").value, ti = card.querySelector(".evt").value.trim().slice(0, 80);
    if (!validDate(dt) || !ti) { flash = "Vyplň datum i název události."; return render(); }
    (S.ev[d.addev] = S.ev[d.addev] || []).push({ d: dt, title: ti }); save(); flash = ""; return render();
  }
  if (d.delev) { const [t, dt, ...r] = d.delev.split("|"), title = r.join("|"); S.ev[t] = (S.ev[t] || []).filter(x => !(x.d === dt && x.title === title)); if (!S.ev[t].length) delete S.ev[t]; save(); return render(); }
  if (el.id === "syncnow") return syncNow(true);
  if (el.id === "bkcopy") { const ta = $("#bk"); ta.select(); try { navigator.clipboard.writeText(ta.value); } catch (er) { document.execCommand("copy"); } el.textContent = "Zkopírováno ✓"; return; }
  if (el.id === "bkload") {
    if (!bkArm) { bkArm = true; el.textContent = "Opravdu přepsat? Klepni znovu"; return; }
    bkArm = false;
    try { S = sanitizeState(JSON.parse($("#bk").value)); save(); flash = `Obnoveno: ${S.fav.length} oblíbených.`; } catch (er) { flash = "Zálohu se nepodařilo načíst (" + er.message + ")."; }
    return render();
  }
});
document.addEventListener("click", e => {          // otevření/zavření karty oblíbené
  const c = e.target.closest(".fav"); if (!c || e.target.closest("input,button,a,label,.detail,summary,textarea")) return;
  openFav = openFav === c.dataset.t ? null : c.dataset.t; render();
});
document.addEventListener("input", e => {
  const el = e.target;
  if (el.classList.contains("buy") || el.classList.contains("qty")) {
    const f = favOf(el.dataset.t); if (!f) return;
    f[el.classList.contains("buy") ? "buy" : "qty"] = num(el.value); save(); patchLive();
  }
});
document.addEventListener("change", e => {
  if (e.target.id === "repo") { const v = e.target.value.trim(); if (!v || /^[\w.-]{1,40}\/[\w.-]{1,100}$/.test(v)) { S.cfg.repo = v; save(); flash = ""; } else flash = "Repo zadej jako vlastník/repo."; render(); }
});

function patchLive() {
  document.querySelectorAll("[data-px]").forEach(el => { const q = priceOf(el.dataset.px); el.textContent = q ? fc(q.p) : "–"; });
  document.querySelectorAll("[data-src]").forEach(el => { const q = priceOf(el.dataset.src); if (q) el.textContent = q.src; });
  document.querySelectorAll("[data-pl]").forEach(el => { const f = favOf(el.dataset.pl); if (f) el.innerHTML = plHtml(f); });
}
async function refreshPrices() { await Promise.all([loadServerQuotes(), loadLive()]); live = Object.keys(LQ).length > 0; if (tab === "mine") patchLive(); }

const filters = { all: () => true, company: s => s.asset !== "crypto" && ["8k", "shock", "scandal"].includes(s.kind), world: s => ["world", "hazard"].includes(s.kind), crypto: s => s.asset === "crypto", people: s => s.kind === "influencer", mine: s => isFav(s.ticker), verified: s => s.direction_verified };
const views = {
  signals: () => {
    const list = D.signals.filter(filters[filter]);
    return `<div class="chips">${[["all", "Vše"], ["mine", "★ Moje"], ["company", "Firmy"], ["world", "Svět"], ["crypto", "Krypto"], ["people", "Lidé"], ["verified", "Ověřený směr"]].map(([k, l]) => `<button class="chip ${filter === k ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div>` +
      (list.length ? list.map(card).join("") : '<div class="card muted">Teď nic zásadního – žádná událost nepřekročila práh závažnosti.</div>');
  },
  market: () => {
    const q = query.toLowerCase(), rows = D.market.filter(m => !q || m.ticker.toLowerCase().includes(q) || m.name.toLowerCase().includes(q) || m.sector.toLowerCase().includes(q)).slice(0, 150);
    const raw = query.trim(), exact = D.market.some(m => m.ticker.toLowerCase() === raw.toLowerCase());
    const custom = raw && SYM_RE.test(raw) && !exact ? `<div class="card row"><div>Přidat vlastní symbol <b>${esc(raw.toUpperCase())}</b><div class="muted">Tvar jako ve Yahoo Finance: AAPL, ASML.AS, CEZ.PR, BTC-USD</div></div>${isFav(raw.toUpperCase()) ? '<span class="muted">už sleduješ</span>' : `<button class="btn" data-addcustom="${esc(raw.toUpperCase())}">＋ Sledovat</button>`}</div>` : "";
    return `<input class="q" id="q" placeholder="Hledej firmu, ticker, sektor (${D.universe} firem) nebo zadej vlastní symbol" value="${esc(query)}">${custom}<div class="card"><table><tr><th>Firma</th><th class="n">Cena</th><th class="n">1 d</th></tr>${rows.map(m => `<tr><td>${starBtn(m.ticker, m.name)} <b>${esc(m.ticker)}</b> <span class="muted">${esc(m.name)}</span></td><td class="n">${m.spot}</td><td class="n ${m.chg1d >= 0 ? "up" : "dn"}">${pct(m.chg1d)}</td></tr>`).join("")}</table></div>`;
  },
  model: () => {
    const A = D.report.A, C = D.report.C, B = D.report.B;
    const tbl = (R, title) => `<h2>${title}</h2><div class="card"><div class="muted">Testovací roky: ${R.years.join(", ")}, ${R.n_test} událostí.</div><table><tr><th>Typ</th><th class="n">n</th><th class="n">Zlepšení</th><th>Použit</th><th>Směr</th></tr>${Object.entries(R.items).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.n}</td><td class="n">${pct(v.improvement)}</td><td>${v.active ? v.best : "základ"}</td><td>${v.direction_verified ? "✓ " + Math.round(v.hit_rate_dir * 100) + " %" : "–"}</td></tr>`).join("")}</table></div>`;
    let h = `<div class="card muted">Modely se učí z historie a pak se testují <b>jen na datech, která při učení neviděly</b> (walk-forward). Použijí se jen tam, kde překonají jednoduchý základ. ${D.built_at ? "Natrénováno " + D.built_at.slice(0, 10) + "." : ""}</div>`;
    if (A) h += tbl(A, "Model A – firemní události (8-K, cenové šoky)");
    else h += '<div class="card muted">Model A zatím není natrénovaný (spusť workflow learn).</div>';
    if (C) h += tbl(C, "Model C – krypto (neobjasněné cenové šoky)");
    else h += '<div class="card muted">Model C (krypto) zatím není natrénovaný nebo je málo historie.</div>';
    if (B) h += `<h2>Model B – stav světa (GDELT) → koše akcií a krypta</h2><div class="card"><div class="muted">Otestováno ${B.tested} košů, ověřený náskok má ${Object.keys(B.active).length}. Celkové zlepšení na anomálních dnech: ${pct(B.overall)}.</div><table><tr><th>Koš</th><th class="n">Zlepšení</th><th>Směr</th></tr>${Object.entries(B.active).map(([k, v]) => `<tr><td>${esc(k.split(":")[1])}</td><td class="n">${pct(v.improvement_anomaly)}</td><td>${v.direction_verified ? "✓ " + Math.round(v.hit_rate_dir * 100) + " %" : "–"}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">Žádný koš nepřekonal základ – svět-signály se nezobrazují.</td></tr>'}</table></div>`;
    else h += '<div class="card muted">Model B zatím není natrénovaný (potřebuje GDELT historii).</div>';
    return h;
  },
  mine: () => mineView(),
  eval: () => {
    const E = D.evaluation, o = E.overall, cal = D.calibration || {};
    const verdict = v => v.verified ? '<span class="up">✓ ověřeno</span>' : v.n_dir < 30 ? `sbírá data (${v.n_dir}/30)` : "neověřeno";
    const p0 = x => x == null ? "–" : Math.round(x * 100) + " %";
    let h = `<div class="card muted">Každý zobrazený signál se uloží. Po 20 pozorováních (akcie: obch. dny, krypto: dny) se porovná odhad se skutečností; po ~1 a ~3 měsících ti u signálů s notifikací přijde zpráva „✔ Uzavření signálu“. Z toho se (1) počítá skutečná úspěšnost, (2) upravuje šířka vějíře a (3) potvrzuje směr u zdrojů bez historie (vlivné osoby).</div>
      <div class="card"><div class="kv"><span>Zalogováno signálů</span><span>${E.n_logged}</span></div><div class="kv"><span>S notifikací</span><span>${E.n_notified}</span></div><div class="kv"><span>Vyhodnoceno (po horizontu)</span><span>${E.n_closed}</span></div>
      ${o ? `<div class="kv"><span>Trefa směru</span><span>${p0(o.hit)} (n=${o.n_dir})</span></div><div class="kv"><span>Skutečnost uvnitř 90% pásma (cíl ≈ 90 %)</span><span>${p0(o.coverage90)}</span></div><div class="kv"><span>Průměrný abnormální výnos ve směru signálu (20 poz.)</span><span>${pct(o.mean_abn_in_dir)}</span></div>${o.n3 ? `<div class="kv"><span>…po 3 měsících (n=${o.n3})</span><span>${pct(o.mean_abn_in_dir_3m)}</span></div>` : ""}` : '<p class="muted">Zatím nic vyhodnoceno – první výsledky přijdou po ~4 týdnech od prvního signálu.</p>'}</div>`;
    const kinds = Object.entries(E.by_kind);
    if (kinds.length) h += `<h2>Podle druhu signálu</h2><div class="card"><table><tr><th>Druh</th><th class="n">n</th><th class="n">Směr</th><th class="n">90% pásmo</th><th>Stav</th></tr>${kinds.map(([k, v]) => `<tr><td>${esc(KIND_FULL(k))}${cal[k] ? ` <span class="muted">×${cal[k]}</span>` : ""}</td><td class="n">${v.n}</td><td class="n">${p0(v.hit)}</td><td class="n">${p0(v.coverage90)}</td><td>${verdict(v)}</td></tr>`).join("")}</table><p class="muted">„×“ = násobek šířky vějíře naučený z vlastních výsledků (od 40 uzavřených signálů). Ověřeno = trefa ≥ 55 % a ~2σ nad náhodou při n ≥ 30. Signály vlivných osob zůstávají bez notifikací, dokud se jejich směr takto neověří.</p></div>`;
    const conf = Object.entries(E.by_confidence);
    if (conf.length) h += `<h2>Znamená „jistota“ něco?</h2><div class="card"><table><tr><th>Jistota</th><th class="n">n</th><th class="n">Trefa směru</th></tr>${conf.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.n}</td><td class="n">${p0(v.hit)}</td></tr>`).join("")}</table></div>`;
    if (E.recent.length) h += `<h2>Poslední uzavřené</h2><div class="card"><table><tr><th>Signál</th><th class="n">Odhad</th><th class="n">Skutečnost</th><th></th></tr>${E.recent.map(r => `<tr><td><b>${esc(r.ticker)}</b> <span class="muted">${r.direction > 0 ? "▲" : "▼"} ${dm(r.date)}</span></td><td class="n">${pct(r.med)}</td><td class="n ${r.h.abn >= 0 ? "up" : "dn"}">${pct(r.h.abn)}${r.m3 ? `<div class="muted">3 m: ${pct(r.m3.abn)}</div>` : ""}</td><td>${r.h.hit ? "✓" : "✗"}${r.h.inside90 ? "" : " ⚠"}</td></tr>`).join("")}</table><p class="muted">Skutečnost = abnormální výnos (vs trh, u krypta vs BTC). ✓/✗ = trefen směr, ⚠ = mimo 90% pásmo.</p></div>`;
    return h;
  },
  about: () => {
    const S = D.sources, health = Object.entries(S.health || {}).map(([k, v]) => `<div class="kv"><span>${esc(k)}</span><span>${v.ok} ok / ${v.fail} chyb</span></div>`).join("");
    return `<div class="card"><h2 style="margin-top:0">Jak to funguje</h2>
    <p><b>Zdroje:</b> SEC 8-K (strukturované firemní události), GDELT (kódované světové události po 15 min), USGS/GDACS/WHO (katastrofy a ohniska), titulky médií (skandály a výroky vlivných osob), veřejné příspěvky (Truth Social zrcadlo, Bluesky, Mastodon; X jen s vlastním placeným klíčem), ceny Stooq/Yahoo, top 100 krypta (CoinGecko seznam, ceny Yahoo).</p>
    <p><b>Učení:</b> z historie 8-K a cenových šoků se trénuje kvantilový model reakce akcií; z historie GDELT se hledají analogické dny a jejich dopad na koše akcií. Vše se testuje out-of-sample a použije se jen tam, kde to překoná základ.</p>
    <p><b>Vějíř:</b> pásma 30/60/90 % z koncového rozdělení modelu + tržní složka + volatilita firmy.</p>
    <p><b>Limity:</b> ceny jsou denní a zpožděné, RSS/GDELT bývají za trhem, historie vzácných událostí je malá, odhady jsou nejisté. Směr je důvěryhodný jen tam, kde je ve výsledcích modelu označen ✓.</p>
    <p><b>Track record:</b> ${D.track_record.n ? `${D.track_record.n} vyhodnocených, shoda směru ${D.track_record.hit_rate == null ? "–" : Math.round(D.track_record.hit_rate * 100) + " %"} (podrobně v záložce Vyhodnocení)` : "zatím žádné vyhodnocené (první po ~4 týdnech)"}.</p>
    <p class="muted">${esc(D.disclaimer)}</p></div>
    <div class="card"><h2 style="margin-top:0">Zdraví dat</h2><div class="kv"><span>GDELT sloty za 24 h</span><span>${S.gdelt_slots_24h}/96</span></div><div class="kv"><span>Nové 8-K</span><span>${S.filings_new}</span></div><div class="kv"><span>Titulky</span><span>${S.headlines}</span></div><div class="kv"><span>Události vlivných osob</span><span>${S.influencer_events ?? 0}${S.x_enabled ? " (X API zapnuto)" : ""}</span></div>${S.note ? `<p class="muted">${esc(S.note)}</p>` : ""}${health}</div>`;
  }
};
function render() {
  if (!D) return renderSetup();
  $("#view").innerHTML = views[tab]();
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  document.querySelectorAll(".sig").forEach(el => el.onclick = e => { if (e.target.closest("a,button,input")) return; open = open === el.dataset.id ? null : el.dataset.id; render(); });
  document.querySelectorAll(".chip").forEach(b => b.onclick = () => { filter = b.dataset.f; render(); });
  const q = $("#q"); if (q) { q.oninput = () => { query = q.value; const p = q.selectionStart; render(); const n = $("#q"); n.focus(); n.setSelectionRange(p, p); }; }
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => { tab = b.dataset.tab; rmArm = null; bkArm = false; flash = ""; render(); window.scrollTo(0, 0); if (tab === "mine") refreshPrices(); });
// ---------- načtení dat, desktopová verze (Signaly.exe): detekce, stav serveru, příprava dat při prvním spuštění ----------
async function loadData() {
  const r = await fetch("data/signals.json?" + Date.now()); if (!r.ok) throw new Error(r.status);
  const d = await r.json(); if (!d || !d.market) throw new Error("data");
  D = d; MK = Object.fromEntries((d.market || []).map(m => [m.ticker, m]));
  metaBase = "Aktualizováno " + new Date(d.generated_at).toLocaleString("cs-CZ", { dateStyle: "short", timeStyle: "short" }) + " · " + d.universe + " firem"; showMeta();
  if (d.demo) { const b = $("#banner"); b.hidden = false; b.textContent = "DEMO: syntetická data pro test aplikace, nejde o skutečný trh."; }
}
function showMeta() { $("#meta").textContent = metaBase + (LOCAL && LOCAL.job ? " · běží: " + LOCAL.phase : ""); }
async function detectLocal() { try { const j = await getJSON("api/status", 2500); if (j && j.app === "signaly-desktop") LOCAL = j; } catch (e) {} }
async function initLocalState() {                    // na počítači je zdrojem pravdy soubor vedle programu (přežije i smazání dat prohlížeče)
  try {
    const j = await getJSON("api/state", 3000);
    if (j && j.v === 1) { S = sanitizeState(j); try { localStorage.setItem(LS, JSON.stringify(S)); } catch (e) {} }
    else if (S.fav.length || Object.keys(S.ev).length) pushState();
  } catch (e) {}
}
async function pollLocal() {
  try { LOCAL = await getJSON("api/status", 3000); } catch (e) { return; }
  if (!D) return;
  showMeta();
  if (LOCAL.data_version && LOCAL.data_version !== dataVer) {
    dataVer = LOCAL.data_version;
    try { await loadData(); await Promise.all([loadServerQuotes(), loadEvents()]); } catch (e) {}
    if (!/INPUT|TEXTAREA/.test(document.activeElement.tagName)) render();
  }
}
let setupT = null;
function renderSetup() {
  const L = LOCAL;
  if (!L) { $("#view").innerHTML = '<div class="card">Data se nepodařilo načíst (po prvním nasazení chvíli počkej na první běh).</div>'; return; }
  const step = (ok, t) => `<div class="kv"><span>${ok ? "✔" : "…"} ${t}</span><span></span></div>`;
  $("#view").innerHTML = `<div class="card"><h2 style="margin-top:0">Příprava dat (první spuštění)</h2><div>${esc(L.phase)}</div>
    ${step(L.has.prices, "Ceny a historie podání SEC")}${step(L.has.signals, "První signály")}${step(L.has.models, "Modely" + (L.gdelt_left > 30 ? ` (zbývá ~${L.gdelt_left} dní historie GDELT)` : ""))}
    <p class="muted">Program na pozadí stahuje historii (ceny od roku 2012, podání SEC, události světa) a učí modely. Poprvé to trvá od desítek minut po několik hodin – okno programu nech běžet. Appka se otevře sama, jakmile budou první data.</p>
    ${L.log_tail && L.log_tail.length ? `<pre class="log">${esc(L.log_tail.join("\n"))}</pre>` : ""}</div>`;
}
function setupPoll() {
  clearInterval(setupT); renderSetup();
  setupT = setInterval(async () => { await pollLocal(); if (LOCAL && LOCAL.has && LOCAL.has.signals) { clearInterval(setupT); boot(); } else renderSetup(); }, 4000);
}
async function boot() {
  try { await loadData(); } catch (e) { if (LOCAL) return setupPoll(); return renderSetup(); }
  dataVer = LOCAL ? LOCAL.data_version : 0;
  render();
  Promise.all([loadServerQuotes(), loadEvents()]).then(() => { if (tab === "mine" && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) render(); });
  if (S.fav.length) refreshPrices();
  if (LOCAL) { lastSynced = (D.watch || []).slice().sort().join(","); syncSoon(); }
}
(async () => { await detectLocal(); if (LOCAL) await initLocalState(); boot(); })();
setInterval(() => { if (LOCAL && D) pollLocal(); }, 15000);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

setInterval(() => { if (tab === "mine" && !document.hidden && S.fav.length) refreshPrices(); }, 45000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && tab === "mine" && S.fav.length) refreshPrices(); });
