@echo off
chcp 65001 > nul
rem Program se bude spouštět po přihlášení do Windows (minimalizovaný, bez otevření prohlížeče).
"%~dp0Signaly.exe" --autostart on
pause
