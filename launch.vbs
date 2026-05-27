Dim oShell, oFS
Set oShell = CreateObject("WScript.Shell")
Set oFS    = CreateObject("Scripting.FileSystemObject")

' Run from the folder this script lives in
Dim appDir
appDir = oFS.GetParentFolderName(WScript.ScriptFullName)

' Route through cmd /c so the full user PATH is used (handles per-user Python installs,
' Microsoft Store Python, Anaconda, etc. — all of which only appear in cmd PATH not WScript PATH)
oShell.Run "cmd /c python """ & appDir & "\main.py""", 0, False

' Wait for the server to be ready (allow extra time on slower machines)
WScript.Sleep 4000

' Open the browser
oShell.Run "http://localhost:8000"
