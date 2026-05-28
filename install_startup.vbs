Dim oShell, oFS
Set oShell = CreateObject("WScript.Shell")
Set oFS    = CreateObject("Scripting.FileSystemObject")

Dim appDir
appDir = oFS.GetParentFolderName(WScript.ScriptFullName)

Dim launchScript
launchScript = appDir & "\launch.vbs"

If Not oFS.FileExists(launchScript) Then
    MsgBox "Cannot find launch.vbs. Make sure this file is in the same folder as launch.vbs.", 16, "Error"
    WScript.Quit
End If

' Create a shortcut in the user's Startup folder
Dim startupFolder
startupFolder = oShell.SpecialFolders("Startup")

Dim shortcut
Set shortcut = oShell.CreateShortcut(startupFolder & "\clinic-system.lnk")
shortcut.TargetPath      = "wscript.exe"
shortcut.Arguments       = """" & launchScript & """"
shortcut.WorkingDirectory = appDir
shortcut.WindowStyle     = 7  ' Start minimised (no console window)
shortcut.Description     = "Clinic System Server"
shortcut.Save

MsgBox "Done! The server will start automatically in the background on next reboot." & vbCrLf & vbCrLf & _
       "Nurses can open the browser and go to localhost:8000 whenever they need it.", _
       64, "Clinic System"
