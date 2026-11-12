"""Rychlé testy parserů na syntetických vzorcích (bez sítě): python -m pytest tests"""
import io, sys, zipfile
sys.path.insert(0, ".")
import pandas as pd
from pipeline.sources import edgar, gdelt, rss

def _row(root, gold, ment, tone, geo, n):
    c = [""] * n; c[28], c[30], c[31], c[34] = root, str(gold), str(ment), str(tone); c[53 if n >= 61 else 51] = geo
    return "\t".join(c)

def test_gdelt_v1_v2():
    for n in (61, 58):
        b = io.BytesIO(); z = zipfile.ZipFile(b, "w")
        z.writestr("x.CSV", "\n".join([_row("19", -10, 50, -6, "UP", n), _row("03", 3, 100, 2, "US", n)])); z.close()
        s = gdelt.read_events_zip(b.getvalue())
        assert s["tot"] == 150 and s["r19"] == 50 and s["h_ua_ru_conflict"] == 50

def test_edgar_atom_and_reaction_day():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>8-K - Apple Inc. (0000320193) (Filer)</title><id>urn:x:accession-number=0000320193-24-000001</id><updated>2024-01-02T16:05:00-05:00</updated></entry></feed>"""
    assert edgar.parse_atom(atom)[0]["cik"] == "0000320193"
    idx = pd.bdate_range("2024-01-01", periods=10)
    assert idx[edgar.reaction_day("2024-01-02T21:30:00.000Z", "2024-01-02", idx)] == pd.Timestamp("2024-01-03")
    assert idx[edgar.reaction_day("2024-01-03T14:00:00.000Z", "2024-01-03", idx)] == pd.Timestamp("2024-01-03")

def test_rss_scandal():
    uni = pd.DataFrame([{"ticker": "NVDA", "name": "Nvidia", "region": "US"}])
    h = [{"title": "Nvidia CEO resigns amid affair scandal", "link": "x", "source": "bbc"}]
    assert "NVDA" in rss.scandals(h, uni)
