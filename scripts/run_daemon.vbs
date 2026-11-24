Set WshShell = CreateObject("WScript.Shell")
AppDir = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\AntigravityControlCenter")
WshShell.CurrentDirectory = AppDir
WshShell.Run """C:\Program Files\nodejs\node.exe"" """ & AppDir & "\antigravity-drag-daemon.js""", 0, False
