Dim oShell, oFS
Set oShell = CreateObject("WScript.Shell")
Set oFS    = CreateObject("Scripting.FileSystemObject")

' Run from the folder this script lives in
Dim appDir
appDir = oFS.GetParentFolderName(WScript.ScriptFullName)

' Start the server silently (window style 0 = hidden)
oShell.Run "python """ & appDir & "\main.py""", 0, False

' Wait for the server to be ready
WScript.Sleep 2500

' Open the browser
oShell.Run "http://localhost:8000"
