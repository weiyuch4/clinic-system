Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

scriptDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
oShell.CurrentDirectory = scriptDir

' Kill any running sync agent
oShell.Run "powershell -WindowStyle Hidden -Command ""Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*sync_agent*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }""", 0, True

' Pull latest code
oShell.Run "cmd /c git pull", 0, True

' Start silently (no window)
oShell.Run "venv\Scripts\pythonw.exe sync_agent.py", 0, False

MsgBox "Sync agent restarted." & vbCrLf & "Check sync_agent.log to confirm.", vbInformation, "Clinic Sync"
