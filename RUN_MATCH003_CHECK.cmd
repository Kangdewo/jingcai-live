@echo off
setlocal
cd /d "%~dp0"
echo Checking match 003: Sevilla vs Osasuna
py -3 -m tplus_resultlink.cli check --config evidence\match003_config.json --evidence evidence\match003_prematch_evidence.json --out-dir output\match003_result_review
if errorlevel 1 echo ERROR: inspect status and source mismatch before retry.
echo Results saved in output\match003_result_review\latest_review.json
pause
