@echo off
rem Sestavení Signaly.exe lokálně ve Windows (potřebuje Python 3.12 v PATH). Výstup: dist\Signaly\Signaly.exe
python -m venv .venv-build || goto :err
call .venv-build\Scripts\activate || goto :err
pip install -r requirements.txt pyinstaller || goto :err
pyinstaller desktop\signaly.spec --noconfirm || goto :err
copy /y desktop\extras\* dist\Signaly\ > nul
dist\Signaly\Signaly.exe --selftest || goto :err
echo.
echo HOTOVO: dist\Signaly\Signaly.exe
exit /b 0
:err
echo CHYBA sestaveni
exit /b 1
