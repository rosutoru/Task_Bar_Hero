"""TaskBarHero 起動を監視して overlay.py を自動起動する"""
import subprocess
import time
import sys
from pathlib import Path
import win32gui

SCRIPT_DIR = Path(__file__).parent
OVERLAY = str(SCRIPT_DIR / "overlay.py")
PYTHONW = sys.executable.replace("python.exe", "pythonw.exe")

overlay_proc = None


def game_running():
    hwnd = win32gui.FindWindow("UnityWndClass", "TaskBarHero")
    return hwnd != 0


def overlay_running():
    global overlay_proc
    if overlay_proc is None:
        return False
    return overlay_proc.poll() is None


def start_overlay():
    global overlay_proc
    overlay_proc = subprocess.Popen(
        [PYTHONW, OVERLAY],
        cwd=str(SCRIPT_DIR)
    )


def stop_overlay():
    global overlay_proc
    if overlay_proc and overlay_proc.poll() is None:
        overlay_proc.terminate()
    overlay_proc = None


while True:
    if game_running():
        if not overlay_running():
            start_overlay()
    else:
        if overlay_running():
            stop_overlay()
    time.sleep(5)
