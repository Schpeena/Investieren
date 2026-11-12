"""Přírodní a zdravotní události: USGS zemětřesení, GDACS (katastrofy), WHO (ohniska).
Tyto události jsou vzácné → bez natrénovaného modelu, jen apriorní efekty (označeno 'neověřeno')."""
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from .. import http

USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
GDACS = "https://www.gdacs.org/xml/rss.xml"
WHO = "https://www.who.int/feeds/entity/csr/don/en/rss.xml"

# oblast -> (lat_min, lat_max, lon_min, lon_max, koše s apriorním efektem za 20 dní)
REGIONS = {
    "Tchaj-wan": (21.5, 25.6, 119.5, 122.5, {"industry:Semiconductors": -0.03, "industry:Semiconductor Equipment": -0.03}),
    "Japonsko": (30.0, 46.0, 128.0, 146.5, {"industry:Automobile Manufacturers": -0.015, "industry:Semiconductor Equipment": -0.015}),
    "Chile/Peru": (-40.0, -5.0, -80.0, -65.0, {"industry:Diversified Metals & Mining": +0.02, "industry:Copper": +0.02}),
}
OUTBREAK_PRIOR = {"industry:Pharmaceuticals": +0.02, "industry:Biotechnology": +0.02, "industry:Passenger Airlines": -0.03}
TC_PRIOR = {"industry:Property & Casualty Insurance": -0.02, "sector:Energy": +0.01}

def quakes(min_mag=6.0):
    out = []
    try:
        js = json.loads(http.get(USGS, "usgs"))
    except Exception as e:
        print(f"[hazards] USGS: {e}"); return out
    for f in js.get("features", []):
        p, (lon, lat, *_) = f["properties"], f["geometry"]["coordinates"]
        if (p.get("mag") or 0) < min_mag:
            continue
        for name, (a, b, c, d, prior) in REGIONS.items():
            if a <= lat <= b and c <= lon <= d:
                out.append({"kind": "quake", "id": f["id"], "title": f"Zemětřesení M{p['mag']} – {p.get('place')} ({name})",
                            "severity": 4 + (p["mag"] - 6.0) * 2.5, "prior": prior, "link": p.get("url", ""),
                            "ts": datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat()})
    return out

def gdacs():
    out = []
    try:
        root = ET.fromstring(http.get(GDACS, "gdacs"))
    except Exception as e:
        print(f"[hazards] GDACS: {e}"); return out
    for it in root.iter("item"):
        level, etype = "", ""
        for ch in it:
            tag = ch.tag.split("}")[-1]
            if tag == "alertlevel": level = (ch.text or "").strip().lower()
            if tag == "eventtype": etype = (ch.text or "").strip().upper()
        if level not in ("red", "orange") or etype != "TC":
            continue
        out.append({"kind": "cyclone", "id": it.findtext("guid") or it.findtext("link"),
                    "title": (it.findtext("title") or "Tropický cyklón").strip(),
                    "severity": 6.0 if level == "red" else 4.0, "prior": TC_PRIOR,
                    "link": it.findtext("link") or "", "ts": datetime.now(timezone.utc).isoformat()})
    return out

def who_outbreaks():
    out = []
    try:
        root = ET.fromstring(http.get(WHO, "who"))
    except Exception as e:
        print(f"[hazards] WHO: {e}"); return out
    for it in list(root.iter("item"))[:5]:
        out.append({"kind": "outbreak", "id": it.findtext("guid") or it.findtext("link"),
                    "title": "WHO: " + (it.findtext("title") or "").strip(), "severity": 3.5,
                    "prior": OUTBREAK_PRIOR, "link": it.findtext("link") or "",
                    "ts": datetime.now(timezone.utc).isoformat()})
    return out

def all_hazards():
    return quakes() + gdacs() + who_outbreaks()
