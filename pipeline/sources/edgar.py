"""SEC EDGAR: živý proud 8-K + historie 8-K (položky = strukturované typy událostí)."""
import json, re
import xml.etree.ElementTree as ET
import pandas as pd
from .. import http
from ..config import CACHE, SEC_UA, HISTORY_START

EDGAR_FILE = CACHE / "edgar_8k.parquet"
PERIODIC_FILE = CACHE / "edgar_periodic.parquet"        # 10-K, 10-Q, DEF 14A, 20-F: z nich se odhadují příští termíny
PERIODIC_FORMS = ("10-K", "10-Q", "DEF 14A", "20-F", "40-F")
ATOM = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include"
        "&start=0&count=100&output=atom")
_rl = http.RateLimiter(6)           # SEC: max 10 req/s, držíme se bezpečně pod
NS = {"a": "http://www.w3.org/2005/Atom"}
_title = re.compile(r"^(?P<form>\S+)\s+-\s+(?P<co>.*?)\s+\((?P<cik>\d{10})\)\s+\((?P<role>\w+)\)")

def _sec_get(url, source="sec"):
    _rl.wait()
    return http.get(url, source, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"})

def parse_atom(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        t = (e.findtext("a:title", "", NS) or "").strip()
        m = _title.match(t)
        if not m or m["role"].lower() != "filer":
            continue
        eid = e.findtext("a:id", "", NS) or ""
        acc = eid.split("accession-number=")[-1]
        link = (e.find("a:link", NS).get("href") if e.find("a:link", NS) is not None else "")
        out.append({"form": m["form"], "company": m["co"], "cik": m["cik"], "acc": acc,
                    "updated": e.findtext("a:updated", "", NS), "link": link})
    return out

def live_feed():
    try:
        return parse_atom(_sec_get(ATOM, "sec_feed"))
    except Exception as e:
        print(f"[edgar] živý feed selhal: {e}")
        return []

def _frame(rec):
    df = pd.DataFrame({"acc": rec["accessionNumber"], "date": rec["filingDate"],
                       "accept": rec.get("acceptanceDateTime", [None] * len(rec["accessionNumber"])),
                       "form": rec["form"], "items": rec.get("items", [""] * len(rec["accessionNumber"]))})
    return df[df["form"].isin(["8-K", "8-K/A"]) & df["form"].eq("8-K")]

def parse_submissions(js, include_older=False, fetch=None):
    frames = [_frame(js["filings"]["recent"])]
    if include_older and fetch:
        for f in js["filings"].get("files", []):
            if f.get("filingTo", "9999") < HISTORY_START[:4]:
                continue
            try:
                frames.append(_frame(json.loads(fetch(f"https://data.sec.gov/submissions/{f['name']}"))))
            except Exception as e:
                print(f"[edgar] {f.get('name')}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def parse_periodic(js):
    rec = js["filings"]["recent"]
    n = len(rec["accessionNumber"])
    df = pd.DataFrame({"acc": rec["accessionNumber"], "form": rec["form"], "filed": rec["filingDate"],
                       "report": rec.get("reportDate", [""] * n)})
    return df[df["form"].isin(PERIODIC_FORMS)].reset_index(drop=True)

def fetch_cik_both(cik, include_older):
    js = json.loads(_sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    df = parse_submissions(js, include_older, fetch=_sec_get)
    df["cik"] = cik
    per = parse_periodic(js)
    per["cik"] = cik
    return df, per

def fetch_cik(cik, include_older):
    return fetch_cik_both(cik, include_older)[0]

def load_periodic():
    return pd.read_parquet(PERIODIC_FILE) if PERIODIC_FILE.exists() else pd.DataFrame()

def load():
    return pd.read_parquet(EDGAR_FILE) if EDGAR_FILE.exists() else pd.DataFrame()

def refresh_order(ciks, known, day_ordinal, per_day):
    """Nejdřív neznámé CIKy (celá historie), pak známé s denní rotací – dřív se pořád obnovovalo jen prvních N v abecedě."""
    new = [c for c in ciks if c not in known]
    old = [c for c in ciks if c in known]
    if old:
        k = (day_ordinal * per_day) % len(old)
        old = old[k:] + old[:k]
    return new + old

def update_history(ciks, budget_requests=2500):
    """Doplní historii 8-K a seznam periodických zpráv. Nové CIKy dostanou i starší soubory, známé jen nejnovější filings."""
    from datetime import date
    old = load()
    old_per = load_periodic()
    known = set(old["cik"]) if not old.empty else set()
    parts, per_parts, n = [], [], 0
    for cik in refresh_order(list(ciks), known, date.today().toordinal(), budget_requests):
        if n >= budget_requests:
            break
        try:
            d8, per = fetch_cik_both(cik, include_older=cik not in known)
            parts.append(d8); per_parts.append(per)
            n += 1
        except Exception as e:
            print(f"[edgar] CIK {cik}: {e}")
    if per_parts:
        per = pd.concat(per_parts + ([old_per] if not old_per.empty else []), ignore_index=True).drop_duplicates("acc", keep="first")
        per.to_parquet(PERIODIC_FILE, compression="zstd")
    if parts:
        new = pd.concat(parts, ignore_index=True)
        df = pd.concat([old, new], ignore_index=True) if not old.empty else new
        df = df.drop_duplicates("acc", keep="last")
        df.to_parquet(EDGAR_FILE, compression="zstd")
        return df
    return old

def items_of(s):
    return [x.strip() for x in str(s or "").split(",") if x.strip()]

def reaction_day(accept, date, index):
    """První obchodní den, který mohl reagovat: po 16:00 ET až následující den."""
    d = pd.Timestamp(date).normalize()
    try:
        t = pd.Timestamp(accept)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        et = t.tz_convert("America/New_York")
        d = pd.Timestamp(et.date())
        after = et.hour >= 16
    except Exception:
        after = False
    i = index.searchsorted(d + pd.Timedelta(days=1 if after else 0))
    return i
