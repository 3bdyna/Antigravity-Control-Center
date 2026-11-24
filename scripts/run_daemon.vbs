Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\3bdyna\AppData\Local\Programs\AntigravityControlCenter"
WshShell.Run """C:\Program Files\nodejs\node.exe"" ""C:\Users\3bdyna\AppData\Local\Programs\AntigravityControlCenter\antigravity-drag-daemon.js""", 0, False
