"""Nastavení desktopové verze (složka s daty, klíče, první spuštění)."""
import json, os, secrets, sys
from pathlib import Path

DEFAULTS = {"sec_ua": "", "ntfy_topic": "", "stooq_apikey": "", "finnhub_key": "", "port": 8765}

def home():
    """Složka s daty: Windows %LOCALAPPDATA%\\Signaly (jinde ~/.local/share/Signaly). Přepsat jde proměnnou SIGNALY_HOME."""
    if os.environ.get("SIGNALY_HOME"):
        p = Path(os.environ["SIGNALY_HOME"])
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Signaly"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Signaly"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Signaly"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _atomic_write(path, text):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

def load(h):
    s = dict(DEFAULTS)
    p = h / "settings.json"
    if p.exists():
        try:
            s.update({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if k in DEFAULTS})
        except Exception:
            pass
    return s

def save(h, s):
    _atomic_write(h / "settings.json", json.dumps(s, ensure_ascii=False, indent=2))

def valid_ua(x):
    return bool(x) and "@" in x and len(x) >= 6

def wizard(s, ask=input, out=print):
    """První spuštění: SEC vyžaduje identifikaci (jméno + e-mail), ntfy téma je pro notifikace na iPhone (volitelné)."""
    out("\nPrvní spuštění – krátké nastavení (lze později změnit v souboru settings.json).")
    while not valid_ua(s["sec_ua"]):
        s["sec_ua"] = ask("SEC EDGAR vyžaduje identifikaci stahujícího. Zadej jméno a e-mail (např. Martin martin@example.cz): ").strip()
        if not valid_ua(s["sec_ua"]):
            out("  musí obsahovat e-mail")
    if not s["ntfy_topic"]:
        sug = "signaly-" + secrets.token_hex(4)
        a = ask(f"ntfy téma pro notifikace na iPhone [Enter = {sug}, - = bez notifikací]: ").strip()
        s["ntfy_topic"] = "" if a == "-" else (a or sug)
        if s["ntfy_topic"]:
            out(f"  v appce ntfy na iPhonu se přihlas k tématu: {s['ntfy_topic']}")
    if not s["stooq_apikey"]:
        s["stooq_apikey"] = ask("Stooq API klíč (volitelné, Enter = přeskočit; bez něj se ceny berou z Yahoo): ").strip()
    if not s["finnhub_key"]:
        s["finnhub_key"] = ask("Finnhub klíč pro potvrzené termíny výsledků (volitelné, Enter = přeskočit): ").strip()
    return s

def env_for(h, s):
    """Prostředí pro podprocesy pipeline: vše lokálně, bez GitHubu, UTF-8."""
    e = dict(os.environ)
    e.update({"CACHE_DIR": str(h / "cache"), "SITE_DATA_DIR": str(h / "site" / "data"), "NO_GH": "1", "SIGNALY_LOCAL": "1",
              "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "SEC_UA": s["sec_ua"] or "SignalApp research (nastav SEC_UA v settings.json)"})
    for k, env in (("ntfy_topic", "NTFY_TOPIC"), ("stooq_apikey", "STOOQ_APIKEY"), ("finnhub_key", "FINNHUB_KEY")):
        if s.get(k):
            e[env] = s[k]
        else:
            e.pop(env, None)
    return e

def autostart(enable, exe=None):
    """Windows: .bat ve složce Po spuštění (spustí program minimalizovaný, bez otevření prohlížeče). Vrací cestu nebo None."""
    if os.name != "nt" and not os.environ.get("SIGNALY_FAKE_APPDATA"):
        return None
    base = Path(os.environ.get("SIGNALY_FAKE_APPDATA") or os.environ.get("APPDATA") or "")
    d = base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    f = d / "Signaly.bat"
    if enable:
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(f'@echo off\r\nstart "" /min "{exe or sys.executable}" --no-browser\r\n', encoding="utf-8")
        return f
    if f.exists():
        f.unlink()
    return f
