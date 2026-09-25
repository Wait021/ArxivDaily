@echo off
rem ASCII-only batch file: UTF-8 + chcp 65001 corrupts lines containing
rem multi-byte chars (known cmd bug), so keep this file pure ASCII.
cd /d "%~dp0"
echo [%date% %time%] start >> agent_run.log
python paper_agent.py >> agent_run.log 2>&1
echo [%date% %time%] exit=%errorlevel% >> agent_run.log
