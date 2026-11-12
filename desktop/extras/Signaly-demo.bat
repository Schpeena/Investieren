@echo off
chcp 65001 > nul
rem Ukázkový režim: syntetická data, bez internetu (rychlé vyzkoušení appky).
"%~dp0Signaly.exe" --demo
pause
