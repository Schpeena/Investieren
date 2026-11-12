"""Perzistence mezi běhy přes GitHub Release 'data' (nenafukuje git historii)."""
import os, shutil, subprocess
from .config import CACHE, GH_RELEASE_TAG, ROOT

def _gh(*args, check=False):
    if os.environ.get("NO_GH"):
        return None
    return subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True, check=check)

def pull(patterns=("*",)):
    if os.environ.get("NO_GH"):
        return
    _gh("release", "view", GH_RELEASE_TAG)
    r = _gh("release", "view", GH_RELEASE_TAG)
    if r is None or r.returncode != 0:
        print("[store] release 'data' ještě neexistuje – začínám od nuly")
        return
    for pat in patterns:
        out = _gh("release", "download", GH_RELEASE_TAG, "--dir", str(CACHE), "--pattern", pat, "--clobber")
        if out is not None and out.returncode != 0:
            print(f"[store] stažení {pat}: {out.stderr.strip()[:200]}")

def push(files):
    if os.environ.get("NO_GH"):
        return
    r = _gh("release", "view", GH_RELEASE_TAG)
    if r is None or r.returncode != 0:
        _gh("release", "create", GH_RELEASE_TAG, "--title", "data", "--notes", "Automaticky udržovaná data aplikace")
    paths = [str(CACHE / f) for f in files if (CACHE / f).exists()]
    if paths:
        out = _gh("release", "upload", GH_RELEASE_TAG, *paths, "--clobber")
        if out is not None and out.returncode != 0:
            print(f"[store] nahrání selhalo: {out.stderr.strip()[:300]}")
