Set WshShell = CreateObject("WScript.Shell")
DaemonJs = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\AntigravityControlCenter\antigravity-drag-daemon.js")
WshShell.Run """C:\Program Files\nodejs\node.exe"" """ & DaemonJs & """", 0, False
