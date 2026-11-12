"""RSS titulky velkých médií + detekce firemních skandálů (kontext k 8-K, ne samostatný model)."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from .. import http

FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml", "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://www.theguardian.com/world/rss", "https://www.theguardian.com/business/rss",
    "https://www.aljazeera.com/xml/rss/all.xml", "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.marketwatch.com/marketwatch/topstories/", "https://www.ft.com/rss/home",
]
SCANDAL = {"scandal": 3, "resigns": 2, "resigned": 2, "steps down": 2, "affair": 3, "investigation": 2, "probe": 2,
           "recall": 2, "fraud": 3, "misconduct": 3, "indicted": 3, "charged": 2, "fired": 2, "ousted": 2,
           "lawsuit": 1.5, "short seller": 2.5, "accounting": 1, "whistleblower": 2.5, "data breach": 2, "outage": 1.5}
STOP = {"Target", "Block", "Match", "General", "United", "American", "First", "National", "Southern", "Western",
        "Delta", "Fox", "News", "Live", "Ross", "Gap", "Ball", "Southwest", "Public", "Ally", "Visa", "Meta"}
SUFFIX = re.compile(r"[,\s]+(Inc\.?|Corp\.?|Corporation|plc|PLC|Co\.?|Company|Holdings?|Group|Ltd\.?|N\.V\.|SE|AG|S\.A\.|\(.*?\))$")
_kw = [(re.compile(rf"\b{re.escape(k)}\b", re.I), w) for k, w in SCANDAL.items()]

def parse_rss(xml_text, url):
    items, src = [], urlparse(url).netloc.replace("www.", "")
    for it in ET.fromstring(xml_text).iter("item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate")
        try:
            ts = parsedate_to_datetime(pub).astimezone(timezone.utc) if pub else datetime.now(timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)
        if title:
            items.append({"title": title, "link": (it.findtext("link") or "").strip(), "source": src, "ts": ts.isoformat()})
    return items

def fetch_headlines():
    out = []
    for u in FEEDS:
        try:
            out += parse_rss(http.get(u, "rss"), u)
        except Exception as e:
            print(f"[rss] {u}: {str(e)[:80]}")
    return out

def _clean(name):
    n = str(name)
    for _ in range(3):
        n = SUFFIX.sub("", n)
    return n.strip()

def alias_table(uni):
    al = []
    for _, r in uni[~uni["region"].eq("ETF")].iterrows():
        nm = _clean(r["name"])
        for cand in {nm, nm.split()[0] if len(nm.split()) > 1 else nm}:
            if len(cand) >= 4 and cand not in STOP:
                al.append((re.compile(rf"\b{re.escape(cand)}\b"), r["ticker"]))
    return al

def scandals(headlines, uni, min_score=2.0):
    """Firemní skandály: titulek zmiňuje firmu + váhy slov >= min_score. Vrací slovník ticker -> záznam."""
    al = alias_table(uni)
    found = {}
    for h in headlines:
        sc = sum(w for rg, w in _kw if rg.search(h["title"]))
        if sc < min_score:
            continue
        for rg, tk in al:
            if rg.search(h["title"]):
                cur = found.get(tk)
                if not cur or sc > cur["score"]:
                    found[tk] = {"ticker": tk, "score": sc, "headline": h["title"], "link": h["link"],
                                 "sources": {h["source"]}}
                else:
                    cur["sources"].add(h["source"])
                if cur and sc <= cur["score"]:
                    cur["sources"].add(h["source"])
    return found
