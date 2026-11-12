"""Vlivní lidé: příspěvky a zmínky -> události. BEZ historie reakcí (ta pro příspěvky neexistuje v čisté podobě),
proto jsou signály z tohoto zdroje APRIORNÍ a o jejich platnosti rozhodne až vlastní vyhodnocení (evaluate.py).

Zdroje (od nejlevnějšího):
  1. zmínky v titulcích velkých médií (zdarma, funguje hned) – 'Musk says ...', 'Trump threatens tariffs ...'
  2. Truth Social přes veřejné RSS zrcadlo (TRUTH_RSS, výchozí trumpstruth.org/feed – neoficiální, může zmizet)
  3. Bluesky (veřejné API bez klíče) a Mastodon (RSS profilu) – jen u lidí, kde doplníte handle v seeds/influencers.csv
  4. X/Twitter přes placené API (proměnná X_BEARER; počítá se po příspěvcích) – volitelné, ve výchozím stavu vypnuto
"""
import hashlib, json, os, re
from datetime import datetime, timedelta, timezone
import pandas as pd
from .. import http
from ..config import ROOT
from . import rss

SEED = ROOT / "pipeline" / "seeds" / "influencers.csv"
TRUTH_RSS = os.environ.get("TRUTH_RSS") or "https://www.trumpstruth.org/feed"
X_BEARER = os.environ.get("X_BEARER", "")
X_POLL_USERS = int(os.environ.get("X_POLL_USERS") or "8")          # kolik X účtů max. za běh (platí se za přečtený příspěvek)
MAX_DIRECT_REQUESTS = 12                                        # Bluesky/Mastodon dotazů na běh (rotuje se)

SPEECH = re.compile(r"\b(says?|said|tweets?|posts?|posted|announces?|announced|warns?|warned|threatens?|vows?|signals?|"
                    r"slams?|hints?|plans?|unveils?|reveals?|claims?|urges?|pledges?|calls? for|admits?|targets?|"
                    r"wants?|backs?|bets?|buys?|sells?|says he|will)\b", re.I)
POS = {"great", "boost", "record", "win", "wins", "surge", "support", "deal", "approve", "approved", "approval", "buy", "buys", "bought",
       "strong", "growth", "bullish", "invest", "investment", "breakthrough", "launch", "launches", "partnership", "beat", "beats",
       "rally", "optimistic", "reserve", "adopt", "adoption", "lower rates", "rate cut", "cut rates", "ceasefire", "peace"}
NEG = {"ban", "bans", "crash", "fraud", "fire", "fires", "fired", "tariff", "tariffs", "threat", "threatens", "warn", "warns",
       "sanction", "sanctions", "attack", "war", "collapse", "bearish", "sell", "sells", "sold", "probe", "lawsuit", "sue", "sues",
       "recession", "default", "bankruptcy", "cut jobs", "layoffs", "delay", "delays", "miss", "misses", "hike", "rate hike", "crackdown"}
# téma: (popis, regex, koše/tickery, znaménko 0=podle tónu, apriorní efekt 20 d)
TOPICS = [
    ("cla / obchodní válka", r"tariffs?|trade war|trade deal|import dut", ["sector:Industrials", "sector:Consumer Discretionary", "sector:Information Technology"], -1, 0.012),
    ("zbrojení / konflikt", r"\bwar\b|invasion|missile|ceasefire|nuclear|defen[cs]e spending|nato", ["industry:Aerospace & Defense"], 1, 0.015),
    ("ropa / energie", r"\boil\b|opec|drilling|gas prices|\blng\b|pipeline", ["sector:Energy"], 0, 0.012),
    ("sazby / inflace", r"interest rates?|rate cuts?|rate hikes?|inflation|balance sheet", ["sector:Financials", "sector:Real Estate"], 0, 0.010),
    ("AI / čipy", r"\bAI\b|artificial intelligence|chips?\b|semiconductors?|export controls?", ["industry:Semiconductors", "sector:Information Technology"], 0, 0.015),
    ("krypto", r"bitcoin|crypto|stablecoin|ethereum|digital assets?", ["crypto:BTC", "crypto:large_alts"], 0, 0.040),
    ("farmacie / zdravotnictví", r"drug prices?|pharma|medicare|medicaid|\bfda\b", ["sector:Health Care"], 0, 0.010),
]
_topics = [(n, re.compile(rx, re.I), tg, sg, ef) for n, rx, tg, sg, ef in TOPICS]

# ------------------------------------------------------------------ seznam lidí
def load_influencers(path=SEED):
    df = pd.read_csv(path, dtype=str).fillna("")
    df["weight"] = df["weight"].astype(int)
    pats = []
    for r in df.itertuples():
        names = {r.name}
        for a in str(r.aliases).split("|"):
            a = a.strip()
            if a and (r.weight >= 2 or " " in a):       # jednoslovné příjmení jen u vlivných (menší riziko záměny)
                names.add(a)
        rg = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b")
        pats.append(rg)
    df["rg"] = pats
    return df

# ------------------------------------------------------------------ analýza textu
def tone(text):
    t = text.lower()
    p = sum(1 for w in POS if re.search(rf"\b{re.escape(w)}\b", t))
    n = sum(1 for w in NEG if re.search(rf"\b{re.escape(w)}\b", t))
    return (p - n) / max(1, p + n)

def topics_of(text):
    return [(n, tg, sg, ef) for n, rg, tg, sg, ef in _topics if rg.search(text)]

def event_id(person, text, link):
    h = hashlib.md5((person + (link or text[:80])).encode()).hexdigest()[:10]
    return f"inf-{h}"

def detect(posts, infl, require_speech=False, max_age_h=36, now=None):
    """posts: [{text, link, source, ts, person?}] -> události (seskupené podle člověka a tématu, s počtem zdrojů)."""
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(hours=max_age_h)
    agg = {}
    for p in posts:
        try:
            if pd.Timestamp(p["ts"]).tz_convert("UTC") < cut:
                continue
        except Exception:
            pass
        text = p["text"]
        if require_speech and not SPEECH.search(text):
            continue
        who = [p["person"]] if p.get("person") else [r.name for r in infl.itertuples() if r.rg.search(text)]
        for name in who:
            row = infl[infl["name"] == name].iloc[0]
            tps = topics_of(text)
            tk = [t for t in str(row["tickers"]).split(";") if t]
            if not tps and not tk:
                continue
            tn = tone(text)
            if not tps:                                  # čistě firemní zmínka (Musk -> TSLA)
                tps = [("firma / projekt člověka", [], 0, 0.015)]
            for tname, targets, sign, eff in tps:
                s = sign if sign != 0 else (1 if tn > 0 else -1 if tn < 0 else 0)
                if s == 0:
                    continue
                key = (name, tname)
                cur = agg.get(key)
                if cur is None:
                    agg[key] = {"id": event_id(name, text, p.get("link", "")), "person": name, "category": row["category"],
                                "weight": int(row["weight"]), "topic": tname, "targets": targets, "tickers": tk, "sign": s,
                                "effect": eff, "text": text[:200], "link": p.get("link", ""), "sources": {p.get("source", "?")},
                                "ts": p.get("ts", ""), "tone": round(tn, 2)}
                else:
                    cur["sources"].add(p.get("source", "?"))
    return list(agg.values())

# ------------------------------------------------------------------ adaptéry
def parse_bluesky(js, person):
    out = []
    for it in js.get("feed", []):
        post = it.get("post", {})
        if it.get("reason"):                              # repost
            continue
        rec = post.get("record", {})
        uri = post.get("uri", "")
        out.append({"text": rec.get("text", ""), "ts": rec.get("createdAt", ""), "person": person, "source": "bluesky",
                    "link": f"https://bsky.app/profile/{post.get('author', {}).get('handle', '')}/post/{uri.rsplit('/', 1)[-1]}"})
    return out

def parse_rss_posts(xml, url, person, source):
    items = rss.parse_rss(xml, url)
    return [{"text": re.sub(r"<[^>]+>", " ", i["title"]).strip(), "ts": i["ts"], "link": i["link"], "person": person, "source": source}
            for i in items]

def parse_x(js, person):
    return [{"text": t.get("text", ""), "ts": t.get("created_at", ""), "person": person, "source": "x",
             "link": f"https://x.com/i/status/{t.get('id')}"} for t in js.get("data", []) or []]

def fetch_direct(infl, state):
    """Přímé příspěvky. Každý dotaz je zabalený – výpadek zdroje nikdy neshodí běh."""
    posts, st = [], state.setdefault("social", {})
    try:                                                  # Truth Social přes zrcadlo (jen Trump)
        if "Donald Trump" in set(infl["name"]):
            posts += parse_rss_posts(http.get(TRUTH_RSS, "truth_rss"), TRUTH_RSS, "Donald Trump", "truth")
    except Exception as e:
        print(f"[social] Truth RSS: {str(e)[:80]}")
    rr = st.get("rr", 0)
    cand = [r for r in infl.itertuples() if getattr(r, "bluesky", "") or getattr(r, "mastodon", "")]
    for r in cand[rr:rr + MAX_DIRECT_REQUESTS] + cand[:max(0, rr + MAX_DIRECT_REQUESTS - len(cand))]:
        try:
            if getattr(r, "bluesky", ""):
                u = f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={r.bluesky}&limit=10&filter=posts_no_replies"
                posts += parse_bluesky(json.loads(http.get(u, "bluesky")), r.name)
            if getattr(r, "mastodon", ""):                # formát 'uzivatel@instance'
                user, inst = r.mastodon.split("@")
                u = f"https://{inst}/@{user}.rss"
                posts += parse_rss_posts(http.get(u, "mastodon"), u, r.name, "mastodon")
        except Exception as e:
            print(f"[social] {r.name}: {str(e)[:80]}")
    st["rr"] = (rr + MAX_DIRECT_REQUESTS) % max(1, len(cand))
    if X_BEARER and X_POLL_USERS > 0:
        posts += fetch_x(infl, st)
    return posts

def fetch_x(infl, st):
    """Placené X API (pay-per-use, účtuje se přečtený příspěvek). Vlastní klíč v X_BEARER; počet účtů za běh omezuje X_POLL_USERS."""
    hdr = {"Authorization": f"Bearer {X_BEARER}"}
    out = []
    users = [r for r in infl.itertuples() if r.x]
    ids = st.setdefault("x_ids", {})
    need = [r.x for r in users if r.x not in ids][:100]
    try:
        if need:
            js = json.loads(http.get("https://api.x.com/2/users/by?usernames=" + ",".join(need), "x", headers=hdr))
            for u in js.get("data", []):
                ids[u["username"].lower()] = u["id"]
            for n in need:
                ids.setdefault(n.lower(), None)
        pool = [r for r in users if ids.get(r.x.lower())]
        pool.sort(key=lambda r: -r.weight)
        k = st.get("x_rr", 0)
        pick = (pool + pool)[k:k + X_POLL_USERS] if pool else []
        st["x_rr"] = (k + X_POLL_USERS) % max(1, len(pool))
        since = st.setdefault("x_since", {})
        for r in pick:
            uid = ids[r.x.lower()]
            u = f"https://api.x.com/2/users/{uid}/tweets?max_results=5&exclude=retweets,replies&tweet.fields=created_at"
            if since.get(uid):
                u += f"&since_id={since[uid]}"
            js = json.loads(http.get(u, "x", headers=hdr))
            for t in js.get("data", []) or []:
                since[uid] = max(since.get(uid, "0"), t["id"], key=int)
            out += parse_x(js, r.name)
    except Exception as e:
        print(f"[social] X API: {str(e)[:100]}")
    return out

def collect(infl, headlines, state, demo_posts=None):
    """Hlavní vstup pro run_fast: zmínky v titulcích + přímé příspěvky -> události (id je stabilní, duplicity řeší aktivní seznam)."""
    posts = demo_posts if demo_posts is not None else fetch_direct(infl, state)
    news = [{"text": h["title"], "link": h["link"], "source": h["source"], "ts": h["ts"]} for h in headlines]
    ev = detect(news, infl, require_speech=True) + detect(posts, infl)
    merged = {}
    for e in ev:                                          # sloučení stejné osoby a tématu z titulků i příspěvků
        k = (e["person"], e["topic"])
        if k in merged:
            merged[k]["sources"] |= e["sources"]
        else:
            merged[k] = e
    return list(merged.values())
