"""Windows: výchozí kódování textových souborů a konzole je cp1250/cp1252 -> česká diakritika a symboly (▲ ✔) by shodily zápis.
Tento shim nastaví UTF-8 pro open()/Path.read_text/write_text a pro stdout/stderr. Volá se na začátku každého procesu."""
import builtins, io, sys

_done = False

def install():
    global _done
    if _done:
        return
    _done = True
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    orig = builtins.open

    def open_utf8(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
        if "b" not in mode and encoding in (None, "locale"):        # pathlib posílá "locale", když encoding není zadáno
            encoding = "utf-8"
        return orig(file, mode, buffering, encoding, errors, newline, closefd, opener)

    builtins.open = open_utf8
    io.open = open_utf8
