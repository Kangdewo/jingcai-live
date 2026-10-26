@echo off
setlocal
cd /d "%~dp0"
echo [1/3] Run offline contract tests...
py -3 -m unittest discover -s tests -p "test_tplus_realdata.py" -q
if errorlevel 1 goto failed
echo [2/3] Fetch current Bundesliga 2026/27 from OpenLigaDB (one request)...
py -3 -m tplus_realdata.cli fetch --provider openligadb --league bl1 --season 2026 --output output\openligadb_bl1_2026.json
if errorlevel 1 goto failed
echo [3/3] Compute as-of recent form and provisional table...
py -3 -m tplus_realdata.cli report --input output\openligadb_bl1_2026.json --cutoff now --output output\form_studies.json
if errorlevel 1 goto failed
echo SUCCESS. Files are in output\ . The data is NOT linked to your T match IDs yet.
pause
exit /b 0
:failed
echo FAILED. No fake scores were generated; please copy this error screen.
pause
exit /b 1
