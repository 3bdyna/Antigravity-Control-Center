import os
import subprocess
import sys
import time

NODE_EXE = r"C:\Program Files\nodejs\node.exe"
DAEMON_JS = r"C:\Users\3bdyna\AppData\Local\Programs\AntigravityControlCenter\antigravity-drag-daemon.js"

CREATE_NO_WINDOW = 0x08000000

def main():
    while True:
        try:
            p = subprocess.Popen([NODE_EXE, DAEMON_JS],
                                 creationflags=CREATE_NO_WINDOW,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            p.wait()
        except Exception:
            pass
        time.sleep(2)

if __name__ == "__main__":
    main()
