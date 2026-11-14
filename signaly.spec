# -*- mode: python ; coding: utf-8 -*-
# Sestavení:  pyinstaller desktop/signaly.spec --noconfirm      (výstup: dist/Signaly/Signaly.exe + složka _internal)
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))                                # collect_submodules('pipeline') importuje balíček z tohoto stromu
datas = []
for f in (ROOT / "docs").rglob("*"):                         # appka; generovaná data (docs/data) se nebalí
    if f.is_file() and "data" not in f.relative_to(ROOT / "docs").parts[:1]:
        datas.append((str(f), str(Path("docs") / f.relative_to(ROOT / "docs").parent)))
for f in (ROOT / "pipeline" / "seeds").glob("*"):
    datas.append((str(f), "pipeline/seeds"))
datas += collect_data_files("tzdata")                        # Windows nemá systémovou databázi časových zón

hidden = collect_submodules("pipeline") + collect_submodules("desktop") + ["lxml.etree", "lxml._elementpath", "sklearn.ensemble._gb"]
cf_datas, cf_bins, cf_hidden = collect_all("curl_cffi")       # Yahoo přes curl_cffi: nativní knihovna + certifikáty
datas += cf_datas
hidden += cf_hidden + ["_cffi_backend"]

a = Analysis([str(ROOT / "desktop" / "launcher.py")], pathex=[str(ROOT)], binaries=cf_bins, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PyQt6", "PySide6", "notebook", "sphinx", "playwright"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Signaly", console=True, upx=False,
          icon=str(ROOT / "desktop" / "signaly.ico") if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Signaly")
