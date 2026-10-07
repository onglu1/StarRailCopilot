"""Launch the combined SRC WebUI using an existing Python environment."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('SRC_WEBUI_PORT', '22369'))
URL = f'http://127.0.0.1:{PORT}'


def main():
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', PORT))
    except OSError:
        try:
            with urllib.request.urlopen(URL, timeout=2) as response:
                if '<title>SRC</title>' in response.read().decode('utf-8', errors='replace'):
                    webbrowser.open(URL)
                    return 0
        except (OSError, urllib.error.URLError):
            pass
        print(f'Port {PORT} is already in use. Set SRC_WEBUI_PORT to a free port.')
        return 1
    finally:
        probe.close()
    child = subprocess.Popen([sys.executable, 'gui.py', '--host', '127.0.0.1', '--port', str(PORT)], cwd=ROOT)
    opened = False
    try:
        while child.poll() is None:
            if not opened:
                try:
                    with urllib.request.urlopen(URL, timeout=0.8) as response:
                        if response.status == 200:
                            webbrowser.open(URL)
                            opened = True
                            print(f'SRC WebUI: {URL}')
                except (OSError, urllib.error.URLError):
                    pass
            time.sleep(0.4)
        return child.returncode
    except KeyboardInterrupt:
        child.terminate()
        child.wait(timeout=10)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
