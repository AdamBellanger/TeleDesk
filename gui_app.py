"""
Point d'entrée TéléDesk — lance Flask en thread puis ouvre pywebview.
"""

import ctypes
import sys
import threading
import time
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

import server

threading.Thread(target=lambda: server.run(port=7421), daemon=True).start()
time.sleep(0.8)

import webview

class Api:
    def browse_file(self):
        result = window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('Excel (*.xlsx;*.xls)', 'All files (*.*)')
        )
        return result[0] if result else ""


api_obj = Api()

window = webview.create_window(
    "TéléDesk Import",
    url="http://127.0.0.1:7421/",
    width=1200,
    height=780,
    min_size=(1000, 680),
    resizable=True,
    js_api=api_obj,
)

webview.start(debug=False)
