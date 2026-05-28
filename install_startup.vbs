Dim oShell, oFS
Set oShell = CreateObject("WScript.Shell")
Set oFS    = CreateObject("Scripting.FileSystemObject")

Dim appDir
appDir = oFS.GetParentFolderName(WScript.ScriptFullName)

Dim launchScript
launchScript = appDir & "\launch.vbs"

If Not oFS.FileExists(launchScript) Then
    MsgBox "找不到 launch.vbs，請確認此檔案與 launch.vbs 放在同一資料夾中。", 16, "錯誤"
    WScript.Quit
End If

' Create a shortcut in the user's Startup folder
Dim startupFolder
startupFolder = oShell.SpecialFolders("Startup")

Dim shortcut
Set shortcut = oShell.CreateShortcut(startupFolder & "\診所追蹤系統.lnk")
shortcut.TargetPath      = "wscript.exe"
shortcut.Arguments       = """" & launchScript & """"
shortcut.WorkingDirectory = appDir
shortcut.WindowStyle     = 7  ' Start minimised (no console window)
shortcut.Description     = "診所追蹤系統 — 背景伺服器"
shortcut.Save

MsgBox "設定完成！" & vbCrLf & vbCrLf & _
       "下次重開機後，伺服器會自動在背景執行。" & vbCrLf & _
       "護理人員只需開啟瀏覽器，輸入 localhost:8000 即可使用。", _
       64, "診所追蹤系統"
