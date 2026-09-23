@echo off
chcp 65001 >nul
title ArxivDaily 本地论文智能体
cd /d "%~dp0"
echo [%date% %time%] 开始论文深度分析... >> agent_run.log
python paper_agent.py >> agent_run.log 2>&1
if %errorlevel%==0 (
    echo [%date% %time%] 分析完成 >> agent_run.log
) else (
    echo [%date% %time%] 分析失败，详见 agent_run.log >> agent_run.log
)
