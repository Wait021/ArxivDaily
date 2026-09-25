' Silent launcher: runs run_daily.bat with window style 0 (completely hidden).
' Task action points here so no console/taskbar window ever appears.
CreateObject("Wscript.Shell").Run """C:\ArxivDaily\run_daily.bat""", 0, False
