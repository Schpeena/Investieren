"""HTTP s opakováním, zdvořilými pauzami a evidencí zdraví zdrojů."""
import threading, time
from collections import defaultdict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1.0,
               status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))))
_session.mount("http://", _session.get_adapter("https://"))
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

HEALTH = defaultdict(lambda: {"ok": 0, "fail": 0, "last_error": None})
_lock = threading.Lock()

def get(url, source, headers=None, timeout=25, raw=False):
    h = {"User-Agent": BROWSER_UA}
    if headers:
        h.update(headers)
    try:
        r = _session.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        with _lock:
            HEALTH[source]["ok"] += 1
        return r.content if raw else r.text
    except Exception as e:
        with _lock:
            HEALTH[source]["fail"] += 1
            HEALTH[source]["last_error"] = str(e)[:160]
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
