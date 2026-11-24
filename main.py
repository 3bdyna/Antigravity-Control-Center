"""
Antigravity Control Center Launcher v1.3.1
"""
import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

from app import main

if __name__ == "__main__":
    main()
