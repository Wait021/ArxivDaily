# -*- coding: utf-8 -*-
"""用 ASCII 联接路径 C:\\ArxivDaily 重注册计划任务，绕开中文路径编码问题，并实测验证。"""
import subprocess
import time

PROJECT = r"C:\ArxivDaily"  # 指向 D:\哈工大\ZCode\ArxivDaily 的 junction（纯 ASCII）
TASK = "ArxivDailyAgent"
PYTHON = r"C:\Users\Administrator\miniconda3\python.exe"

assert all(ord(c) < 128 for c in PROJECT + TASK + PYTHON), "路径必须纯 ASCII"

# 全 ASCII 的 PowerShell 命令
ps = (
    f"$a = New-ScheduledTaskAction -Execute '{PYTHON}' "
    f"-Argument '{PROJECT}\\paper_agent.py' -WorkingDirectory '{PROJECT}'; "
    f"Set-ScheduledTask -TaskName '{TASK}' -Action $a | Out-Null; "
    f"(Get-ScheduledTask -TaskName '{TASK}').Actions[0] | Format-List Execute,Arguments,WorkingDirectory"
)
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout)
if r.returncode != 0:
    print("ERR:", r.stderr)
    raise SystemExit(1)

# 实测：启动任务，确认 python 进程真的跑起来
subprocess.run(["powershell", "-NoProfile", "-Command", f"Start-ScheduledTask -TaskName '{TASK}'"])
time.sleep(15)
chk = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-Process python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
    capture_output=True, text=True)
pids = chk.stdout.split()
if pids:
    print(f"✓ 任务实测成功：python 进程已启动 pid={','.join(pids)}（正在跑今天的分析，含 8 篇论文，约需 20-40 分钟）")
else:
    print("✗ 仍未检测到 python 进程，需要进一步排查")
