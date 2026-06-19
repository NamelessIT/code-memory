' Chay start.bat o che do an (khong hien cua so console) -> double-click la chay.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("WScript.Shell")
ws.Run "cmd /c """ & scriptDir & "\start.bat""", 0, False
