"""Plánovač běhů pipeline pro desktopovou verzi. Každý běh je podproces (izolované pády, log do souboru):
  daily  = ceny celého univerza + 8-K historie (první naplnění 1–3 h)
  learn  = GDELT historie + trénink modelů (první naplnění hodiny, obnovitelné; potom týdně v noci)
  fast   = živý běh (signály, kotace, notifikace) každých 10 min mezi 8:00 a 24:00 pražského času
  custom = přidání sledovaných symbolů z aplikace
Rozhodování je čistá funkce decide() (otestováno bez spouštění čehokoli)."""
import json, os, re, subprocess, sys, threading, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FAST_EVERY_S = 600
TIMEOUT_S = {"fast": 900, "daily": 4 * 3600, "learn": 8 * 3600, "custom": 3600, "demo": 1800}
BACKOFF_S = {"fast": 300, "daily": 1800, "learn": 3600, "custom": 600, "demo": 600}
MAX_LEARN_ROUNDS = 8
GDELT_LEFT_OK = 30                      # zbývá-li víc dní GDELT historie, další kolo learn pokračuje
MODULE = {"fast": "pipeline.run_fast", "daily": "pipeline.run_daily", "learn": "pipeline.run_learn",
          "custom": "pipeline.run_custom", "demo": "pipeline.demo_setup"}
PHASE_CZ = {"daily": "Stahuji ceny a historii podání SEC (první naplnění obvykle 1–3 h)",
            "learn": "Učím modely (GDELT historie + trénink, první kolo může trvat hodiny)",
            "fast": "Počítám signály a ceny", "custom": "Přidávám sledované symboly (historie cen, termíny)",
            "demo": "Generuji ukázková data"}

def _iso(dt):
    return dt.isoformat()

def _ago(st, job, now):
    t = (st.get("last") or {}).get(job, {}).get("at")
    return (now - datetime.fromisoformat(t)).total_seconds() if t else None

def _failed_recently(st, job, now):
    t = (st.get("fail") or {}).get(job)
    return bool(t) and (now - datetime.fromisoformat(t)).total_seconds() < BACKOFF_S[job]

def decide(st, now, has, pending_custom=False, demo=False, tz="Europe/Prague"):
    """Vrací (job, argumenty) nebo None. now = aware datetime (UTC). has = {'prices','models','signals': bool}."""
    if demo:
        if not has["prices"]:
            return ("demo", []) if not _failed_recently(st, "demo", now) else None
        return ("fast", ["--demo"]) if not has["signals"] and not _failed_recently(st, "fast", now) else None
    loc = now.astimezone(ZoneInfo(tz))
    rounds = st.get("learn_rounds", 0)

    def ok(job):
        return not _failed_recently(st, job, now)

    if pending_custom and has["prices"] and ok("custom"):
        return ("custom", [])
    if not has["prices"]:
        return ("daily", []) if ok("daily") else None                     # první naplnění: bez cen nic nejde
    if not has["signals"] and ok("fast"):
        return ("fast", ["--force"])                                      # hned po cenách ukázat první signály
    if st.get("setup_learn", True) and rounds < MAX_LEARN_ROUNDS and ok("learn"):      # první naplnění: kola learn, dokud není GDELT hotový
        left = st.get("gdelt_left")
        if not has["models"] or (left is not None and left > GDELT_LEFT_OK):
            return ("learn", [])
    a_daily = _ago(st, "daily", now)
    wk = now.weekday() < 5
    after_close = now.hour > 21 or (now.hour == 21 and now.minute >= 30)
    if ok("daily") and wk and ((a_daily is None or a_daily > 30 * 3600) or (after_close and (a_daily or 1e9) > 20 * 3600)):
        return ("daily", [])
    a_learn = _ago(st, "learn", now)
    if ok("learn") and a_learn is not None and a_learn > 6.5 * 86400 and loc.hour < 8:
        return ("learn", [])                                              # týdně, v noci (fast stejně běží jen 8–24)
    a_fast = _ago(st, "fast", now)
    if ok("fast") and 8 <= loc.hour < 24 and (a_fast is None or a_fast >= FAST_EVERY_S):
        return ("fast", [])
    return None

def tail(path, n=12):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return [l[:220] for l in lines[-n:]]
    except Exception:
        return []

def parse_gdelt_left(path):
    try:
        m = re.findall(r"zbývá ~(\d+)", Path(path).read_text(encoding="utf-8", errors="replace"))
        return int(m[-1]) if m else None
    except Exception:
        return None

def job_cmd(job, extra):
    if getattr(sys, "frozen", False):
        return [sys.executable, "run", job, *extra]
    return [sys.executable, "-m", "desktop.app", "run", job, *extra]

class Scheduler:
    def __init__(self, home, env, demo=False, log=print):
        self.home, self.env, self.demo, self.log = Path(home), dict(env), demo, log
        self.cache, self.site = self.home / "cache", self.home / "site" / "data"
        (self.home / "logs").mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True); self.site.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.proc = None
        self.job = None
        self.job_since = None
        self.pending_custom = None           # poslední požadovaný seznam symbolů
        self.custom_syncing = False
        self.st = self._load()

    # ---- stav
    def _load(self):
        try:
            return json.loads((self.home / "sched_state.json").read_text(encoding="utf-8"))
        except Exception:
            return {"last": {}, "fail": {}, "learn_rounds": 0, "gdelt_left": None}

    def _save(self):
        p = self.home / "sched_state.json"
        tmp = Path(str(p) + ".tmp")
        tmp.write_text(json.dumps(self.st), encoding="utf-8")
        os.replace(tmp, p)

    def has(self):
        return {"prices": (self.cache / "prices.parquet").exists(), "models": (self.cache / "model_a.joblib").exists(),
                "signals": (self.site / "signals.json").exists()}

    def log_path(self, job):
        return self.home / "logs" / f"{job}.log"

    def status(self):
        now = datetime.now(timezone.utc)
        job = self.job
        has = self.has()
        sig = self.site / "signals.json"
        a_fast = _ago(self.st, "fast", now)
        if job:
            phase = PHASE_CZ.get(job, job)
        elif self.pending_custom is not None:
            phase = "Čeká na zpracování sledovaných symbolů"
        elif self.demo:
            phase = "Ukázkový režim (syntetická data)"
        else:
            nxt = max(0, int(FAST_EVERY_S - a_fast)) if a_fast is not None else 0
            phase = f"Čeká na další běh (za ~{nxt // 60 + 1} min)"
        show = job or next(iter(sorted((self.st.get("last") or {}), key=lambda k: self.st["last"][k]["at"], reverse=True)), None)
        return {"app": "signaly-desktop", "demo": self.demo, "job": job, "job_since": self.job_since, "phase": phase,
                "has": has, "last": self.st.get("last", {}), "learn_rounds": self.st.get("learn_rounds", 0),
                "gdelt_left": self.st.get("gdelt_left"), "syncing": bool(self.custom_syncing or self.pending_custom is not None),
                "data_version": int(sig.stat().st_mtime) if sig.exists() else 0,
                "log_tail": tail(self.log_path(show)) if show else []}

    # ---- watchlist z aplikace
    def request_custom(self, symbols):
        """Před prvním naplněním dat stačí uložit seznam (zpracuje ho daily), jinak se zařadí běh custom."""
        if not self.has()["prices"]:
            import json as _j
            (self.cache / "watchlist.json").write_text(_j.dumps({"symbols": symbols, "updated": _iso(datetime.now(timezone.utc))}), encoding="utf-8")
            return "uloženo"
        if self.demo:
            return "demo"
        with self.lock:
            self.pending_custom = list(symbols)
        return "zařazeno"

    # ---- běh jednoho jobu
    def run(self, job, extra=(), env_extra=None):
        env = dict(self.env)
        env.update(env_extra or {})
        lp = self.log_path(job)
        t0 = time.time()
        self.job, self.job_since = job, _iso(datetime.now(timezone.utc))
        self.log(f"[{datetime.now():%H:%M:%S}] spouštím {job} {' '.join(extra)}".strip())
        rc = -1
        try:
            with open(lp, "w", encoding="utf-8") as lf:
                cwd = None if getattr(sys, "frozen", False) else str(Path(__file__).resolve().parents[1])
                self.proc = subprocess.Popen(job_cmd(job, list(extra)), env=env, stdout=lf, stderr=subprocess.STDOUT, cwd=cwd)
                while True:
                    try:
                        rc = self.proc.wait(timeout=2)
                        break
                    except subprocess.TimeoutExpired:
                        if self.stop.is_set() or time.time() - t0 > TIMEOUT_S[job]:
                            self.proc.kill(); rc = -9
                            break
        except Exception as e:
            self.log(f"[sched] {job}: {e}")
        finally:
            self.proc = None
        if rc == 0 and job == "daily" and not self.has()["prices"]:
            self.log("[sched] daily skončil bez uložených cen (všechna stahování selhala) – beru jako chybu, zkusím později; podrobnosti v logs\\daily.log")
            rc = 3
        now = datetime.now(timezone.utc)
        if rc == 0:
            self.st.setdefault("last", {})[job] = {"at": _iso(now), "rc": 0, "secs": int(time.time() - t0)}
            self.st.setdefault("fail", {}).pop(job, None)
        else:
            self.st.setdefault("fail", {})[job] = _iso(now)
            self.st.setdefault("last", {}).setdefault(job, {"at": _iso(now - timedelta(days=3650)), "rc": rc, "secs": 0})["rc"] = rc
        if job == "learn":
            self.st["learn_rounds"] = self.st.get("learn_rounds", 0) + 1
            left = parse_gdelt_left(lp)
            if left is not None:
                self.st["gdelt_left"] = left
            if rc == 0 and (left is None or left <= GDELT_LEFT_OK):
                self.st["learn_rounds"] = 0                               # hotovo; další kolo až při týdenním běhu
                self.st["setup_learn"] = False
        self._save()
        self.job, self.job_since = None, None
        self.log(f"[{datetime.now():%H:%M:%S}] {job} skončil (kód {rc}, {int(time.time() - t0)} s)")
        return rc

    def tick(self):
        """Jedno rozhodnutí; vrací název spuštěného jobu nebo None (pro testy)."""
        now = datetime.now(timezone.utc)
        with self.lock:
            pend = self.pending_custom
        d = decide(self.st, now, self.has(), pending_custom=pend is not None, demo=self.demo)
        if not d:
            return None
        job, extra = d
        if job == "custom":
            with self.lock:
                syms, self.pending_custom = self.pending_custom, None
            self.custom_syncing = True
            try:
                rc = self.run("custom", env_extra={"SYMBOLS": json.dumps({"symbols": syms}), "ISSUE_BODY": ""})
            finally:
                self.custom_syncing = False
            if rc == 0:
                self.run("fast", ["--force"])                             # ať jsou kotace a signály hned
            return "custom"
        rc = self.run(job, extra)
        if rc == 0 and job in ("daily",) and not self.demo:
            self.run("fast", ["--force"])
        return job

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as e:
                self.log(f"[sched] chyba: {e}")
            self.stop.wait(5)

    def shutdown(self):
        self.stop.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
