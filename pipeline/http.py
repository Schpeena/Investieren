"""HTTP s opakováním, zdvořilými pauzami a evidencí zdraví zdrojů.

Yahoo od roku 2025 odmítá (HTTP 429) klienty podle otisku TLS spojení, ne podle hlavičky User-Agent.
Knihovna `requests` se tím prozradí, prohlížeč projde. Proto jdou dotazy na *.yahoo.com přes curl_cffi,
které navazuje spojení stejně jako Chrome (stejné řešení používá yfinance). Ostatní zdroje zůstávají na requests.
"""
import threading, time
from collections import defaultdict
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:                                              # bez curl_cffi to pořád poběží, jen Yahoo nejspíš odmítne
    from curl_cffi import requests as _cffi
except Exception:                                 # pragma: no cover - závisí na instalaci
    _cffi = None

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1.0,
               status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))))
_session.mount("http://", _session.get_adapter("https://"))
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
IMPERSONATE = "chrome"

HEALTH = defaultdict(lambda: {"ok": 0, "fail": 0, "last_error": None})
_lock = threading.Lock()
_streak = defaultdict(int)                        # chyby po sobě podle zdroje (jistič)
_cool_until = defaultdict(float)                  # zdroj -> monotonic čas, do kdy se po 429 čeká
BREAKER_FAILS = 25                                # tolik chyb po sobě bez jediného úspěchu -> zdroj vypnut pro tento běh
COOLDOWN_429 = 20.0
_tls = threading.local()
_announced = set()

class SourceDisabled(RuntimeError):
    pass

def engine():
    return "curl_cffi" if _cffi is not None else "requests"

def _is_yahoo(url):
    return (urlparse(url).hostname or "").endswith("yahoo.com")

def _cffi_session():
    s = getattr(_tls, "s", None)                  # curl_cffi Session není bezpečná mezi vlákny -> jedna na vlákno
    if s is None:
        s = _tls.s = _cffi.Session(impersonate=IMPERSONATE)
    return s

def _short(e):
    m = f"{type(e).__name__}: {e}"
    return m if len(m) <= 320 else m[:130] + " … " + m[-180:]     # konec zprávy nese příčinu („Caused by …“)

def _wait_cooldown(source):
    d = _cool_until[source] - time.monotonic()
    if d > 0:
        time.sleep(d)

def _get_yahoo(url, source, headers, timeout):
    if source not in _announced:
        _announced.add(source)
        print(f"[http] {source}: spojení přes {engine()}" + (f" ({IMPERSONATE})" if _cffi is not None else " – curl_cffi chybí, Yahoo může odmítat"), flush=True)
    if _cffi is None:
        r = _session.get(url, headers={"User-Agent": BROWSER_UA, **(headers or {})}, timeout=timeout)
        r.raise_for_status()
        return r
    last = None
    for attempt in range(3):
        _wait_cooldown(source)
        r = _cffi_session().get(url, headers=headers or None, timeout=timeout)   # vlastní User-Agent neposílat: musí sedět k otisku
        if r.status_code == 429 or r.status_code >= 500:
            last = r
            if r.status_code == 429:
                with _lock:
                    _cool_until[source] = max(_cool_until[source], time.monotonic() + COOLDOWN_429 * (attempt + 1))
            else:
                time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r
    last.raise_for_status()
    return last

def get(url, source, headers=None, timeout=25, raw=False):
    with _lock:
        h = HEALTH[source]
        if h["ok"] == 0 and _streak[source] >= BREAKER_FAILS:
            raise SourceDisabled(f"zdroj {source} vypnut pro tento běh ({_streak[source]}× chyba po sobě)")
    try:
        if _is_yahoo(url):
            r = _get_yahoo(url, source, headers, timeout)
        else:
            r = _session.get(url, headers={"User-Agent": BROWSER_UA, **(headers or {})}, timeout=timeout)
            r.raise_for_status()
        with _lock:
            HEALTH[source]["ok"] += 1
            _streak[source] = 0
        return r.content if raw else r.text
    except Exception as e:
        with _lock:
            HEALTH[source]["fail"] += 1
            _streak[source] += 1
            HEALTH[source]["last_error"] = _short(e)
        raise

class RateLimiter:
    def __init__(self, per_sec):
        self.gap, self.t, self.lock = 1.0 / per_sec, 0.0, threading.Lock()
    def wait(self):
        with self.lock:
            now = time.monotonic()
            d = self.t + self.gap - now
            if d > 0:
                time.sleep(d)
            self.t = max(now, self.t + self.gap)

def health_report():
    return {k: dict(v) for k, v in HEALTH.items()}
