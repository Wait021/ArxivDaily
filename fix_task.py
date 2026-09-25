# -*- coding: utf-8 -*-
"""维护工具：注册/修复 ArxivDailyAgent 计划任务（ASCII junction 路径，窗口最小化）。

用法：
  python fix_task.py           # 只注册任务
  python fix_task.py --test    # 注册并立即触发一次（会跑完整分析，确认无并发时再用）

要点：
  - 必须先建 junction：C:\\ArxivDaily -> D:\\哈工大\\ZCode\\ArxivDaily（避开中文路径编码坑）
  - 通过 run_daily.bat 启动（日志落 agent_run.log），start /MIN 让窗口最小化到任务栏
"""
import subprocess
import sys

PROJECT = r"C:\ArxivDaily"
TASK = "ArxivDailyAgent"
BAT = PROJECT + r"\run_daily.bat"

assert all(ord(c) < 128 for c in PROJECT + TASK), "路径必须纯 ASCII（junction 方案）"

# 任务动作：cmd /c start "" /MIN bat  → 最小化窗口 + bat 内部重定向日志
ps = (
    f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' "
    f"-Argument '/c start \"\" /MIN \"{BAT}\"' -WorkingDirectory '{PROJECT}'; "
    f"Set-ScheduledTask -TaskName '{TASK}' -Action $a | Out-Null; "
    f"(Get-ScheduledTask -TaskName '{TASK}').Actions[0] | Format-List Execute,Arguments,WorkingDirectory"
)
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout)
if r.returncode != 0:
    print("ERR:", r.stderr)
    raise SystemExit(1)

if "--test" in sys.argv:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-ScheduledTask -TaskName '{TASK}'"])
    print("任务已触发（最小化窗口，日志见 agent_run.log）")
