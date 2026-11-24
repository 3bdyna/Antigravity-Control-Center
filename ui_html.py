"""
Static UI asset loader for Antigravity Control Center.
Loads separated HTML, CSS, and JS assets from the static/ directory.
"""
import os
import sys


def get_static_dir():
    candidates = [
        os.path.join(getattr(sys, "_MEIPASS", ""), "static"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "static"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal", "static"),
    ]
    for d in candidates:
        if d and os.path.isdir(d):
            return d
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def load_static_bytes(filename):
    path = os.path.join(get_static_dir(), filename)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None
