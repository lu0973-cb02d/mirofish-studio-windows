"""Double-click entry: no terminal, no duplicate server, no secret arguments."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:3888'


def ready():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + '/studio-health', timeout=1) as response:
            return json.load(response).get('service') == 'MiroFish Studio'
    except Exception:
        return False


def main():
    mutex = None
    if os.name == 'nt':
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        name = 'Local\\MiroFishStudioLaunch-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, name)
        already = ctypes.windll.kernel32.GetLastError() == 183
        if already:
            for _ in range(40):
                if ready():
                    webbrowser.open(URL)
                    return
                time.sleep(0.5)
            return
    try:
        if not ready():
            state = ROOT / 'studio_data'
            state.mkdir(exist_ok=True)
            python = ROOT / 'backend/.venv/Scripts/pythonw.exe'
            if not python.exists():
                python = ROOT / 'backend/.venv/Scripts/python.exe'
            env = os.environ.copy()
            env.update({'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
            with (state / 'studio.log').open('a', encoding='utf-8') as log:
                subprocess.Popen([str(python), '-m', 'local_studio.server'], cwd=ROOT,
                    env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(80):
                if ready():
                    break
                time.sleep(0.5)
        if ready():
            webbrowser.open(URL)
        elif os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None,
                '工作台未能启动。请检查 3888 端口是否占用，或查看 MiroFish\\studio_data\\studio.log。',
                'MiroFish Studio', 16)
    finally:
        if mutex:
            ctypes.windll.kernel32.ReleaseMutex(ctypes.c_void_p(mutex))
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == '__main__':
    main()
