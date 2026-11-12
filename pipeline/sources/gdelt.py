"""GDELT: kódované události světa (CAMEO). Živě po 15 minutách (v2), historie po dnech (v1)."""
import io, re, zipfile
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
from .. import http
from ..config import CACHE

DAILY_FILE = CACHE / "gdelt_daily.parquet"
ROOTS = [f"{i:02d}" for i in range(1, 21)]
HOT = {   # FIPS kódy zemí akce -> skupina horkých míst
    "ua_ru": ["UP", "RS"], "levant": ["IS", "GZ", "WE", "LE"], "gulf": ["IR", "SA", "YM", "KU", "AE", "QA", "BA"],
    "iraq_syria": ["IZ", "SY"], "east_asia": ["CH", "TW", "KN", "KS"],
}
CLASSES = {"conflict": {"18", "19", "20"}, "coerce": {"16", "17"}, "protest": {"14"}}
_geo2grp = {c: g for g, cs in HOT.items() for c in cs}
SUM_KEYS = (["tot", "tone", "gold", "n"] + [f"r{r}" for r in ROOTS] +
            [f"h_{g}_{c}" for g in HOT for c in CLASSES])
FEATURES = ([f"r{r}" for r in ROOTS] + [f"h_{g}_{c}" for g in HOT for c in CLASSES] + ["tone", "gold"])

def sums_from_frame(df):
    """df: sloupce root (str), gold, ment, tone, geo -> slovník sum vážených počtem zmínek."""
    ment = df["ment"].astype(float).clip(lower=0).fillna(0)
    out = {k: 0.0 for k in SUM_KEYS}
    out["tot"] = float(ment.sum()); out["n"] = float(len(df))
    out["tone"] = float((df["tone"].astype(float).fillna(0) * ment).sum())
    out["gold"] = float((df["gold"].astype(float).fillna(0) * ment).sum())
    by = ment.groupby(df["root"].astype(str).str.zfill(2)).sum()
    for r in ROOTS:
        out[f"r{r}"] = float(by.get(r, 0.0))
    grp = df["geo"].map(_geo2grp)
    for cls, codes in CLASSES.items():
        m = df["root"].astype(str).str.zfill(2).isin(codes)
        sub = ment[m].groupby(grp[m]).sum()
        for g in HOT:
            out[f"h_{g}_{cls}"] = float(sub.get(g, 0.0))
    return out

def read_events_zip(content):
    """Čte export soubor GDELT v1 (58 sloupců) i v2 (61 sloupců)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            ncols = f.readline().decode("utf-8", "ignore").count("\t") + 1
        geo = 53 if ncols >= 61 else 51
        with z.open(name) as f:
            df = pd.read_csv(f, sep="\t", header=None, usecols=[28, 30, 31, 34, geo], dtype=str,
                             on_bad_lines="skip", quoting=3)
    df.columns = ["root", "gold", "ment", "tone", "geo"]
    for c in ("gold", "ment", "tone"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return sums_from_frame(df.dropna(subset=["root"]))

def _get_zip(url):
    for u in (url, url.replace("https://", "http://")):
        try:
            return http.get(u, "gdelt", raw=True, timeout=60)
        except Exception:
            last = u
    raise IOError(f"GDELT nedostupný: {url}")

def v2_url(slot):
    return f"https://data.gdeltproject.org/gdeltv2/{slot}.export.CSV.zip"

def latest_slot():
    txt = http.get("https://data.gdeltproject.org/gdeltv2/lastupdate.txt", "gdelt")
    m = re.search(r"/(\d{14})\.export\.CSV\.zip", txt)
    return m.group(1) if m else None

def slots_between(last_slot, newest, max_n):
    """Posloupnost 15min slotů po last_slot až newest (max_n nejnovějších)."""
    fmt = "%Y%m%d%H%M%S"
    cur = datetime.strptime(newest, fmt)
    out = []
    while len(out) < max_n:
        s = cur.strftime(fmt)
        if last_slot and s <= last_slot:
            break
        out.append(s)
        cur -= timedelta(minutes=15)
    return out[::-1]

def live_update(state, max_slots):
    """Přidá nové 15min sloty do state['gdelt'] (slot -> sums), drží 48 h."""
    g = state.setdefault("gdelt", {})
    try:
        newest = latest_slot()
    except Exception as e:
        print(f"[gdelt] lastupdate: {e}")
        return 0
    if not newest:
        return 0
    todo = slots_between(max(g) if g else None, newest, max_slots)
    added = 0
    for s in todo:
        try:
            g[s] = read_events_zip(_get_zip(v2_url(s)))
            added += 1
        except Exception as e:
            print(f"[gdelt] slot {s}: {e}")
    cutoff = (datetime.strptime(newest, "%Y%m%d%H%M%S") - timedelta(hours=48)).strftime("%Y%m%d%H%M%S")
    for k in [k for k in g if k < cutoff]:
        del g[k]
    return added

def window_sums(state, hours=24):
    g = state.get("gdelt", {})
    if not g:
        return None, 0
    newest = datetime.strptime(max(g), "%Y%m%d%H%M%S")
    cut = (newest - timedelta(hours=hours)).strftime("%Y%m%d%H%M%S")
    sel = [v for k, v in g.items() if k > cut]
    return {k: float(sum(v[k] for v in sel)) for k in SUM_KEYS}, len(sel)

def features_from_sums(s):
    tot = max(s["tot"], 1.0)
    return {f: (s[f] / tot) for f in FEATURES}

# ---- historie (v1 denní soubory), obnovitelná po částech ----
def v1_url(day):
    return f"https://data.gdeltproject.org/events/{day:%Y%m%d}.export.CSV.zip"

def load_daily():
    return pd.read_parquet(DAILY_FILE) if DAILY_FILE.exists() else pd.DataFrame(columns=SUM_KEYS)

def backfill(start, end, budget_seconds=600, workers=3):
    import time
    from concurrent.futures import ThreadPoolExecutor
    df = load_daily()
    have = set(df.index)
    days = [d for d in pd.date_range(start, end) if d not in have]
    t0, rows = time.time(), {}
    def work(d):
        if time.time() - t0 > budget_seconds:
            return d, None
        try:
            return d, read_events_zip(_get_zip(v1_url(d)))
        except Exception:
            return d, "missing"
    with ThreadPoolExecutor(workers) as ex:
        for d, r in ex.map(work, days):
            if isinstance(r, dict):
                rows[d] = r
    if rows:
        new = pd.DataFrame.from_dict(rows, orient="index")[SUM_KEYS]
        df = pd.concat([df, new]).sort_index()
        df.to_parquet(DAILY_FILE, compression="zstd")
    print(f"[gdelt] backfill: {len(rows)} nových dní, celkem {len(df)}, zbývá ~{max(0, len(days) - len(rows))}")
    return df
