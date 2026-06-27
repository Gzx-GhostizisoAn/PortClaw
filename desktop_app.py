from __future__ import annotations

import os
import shutil
import sys
import threading
import traceback
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

LOG_DIR = Path.home() / "Library" / "Logs" / "PortClaw"
LOG_FILE = LOG_DIR / "pyinstaller-app.log"
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "PortClaw"
RUNTIME_DIR = APP_SUPPORT_DIR / "runtime"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class PortClawHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(message.rstrip() + "\n")


def _service_is_ready(url: str) -> bool:
    try:
        with urlopen(f"{url}/api/overview", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _bundled_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def _copy_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _prepare_runtime_home() -> None:
    if not getattr(sys, "frozen", False):
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    (RUNTIME_DIR / "config").mkdir(exist_ok=True)
    (RUNTIME_DIR / "data").mkdir(exist_ok=True)
    bundle = _bundled_root()
    _copy_if_missing(bundle / "config" / "local_config.example.json", RUNTIME_DIR / "config" / "local_config.example.json")
    _copy_if_missing(bundle / "data" / "portfolio.example.json", RUNTIME_DIR / "data" / "portfolio.example.json")
    _copy_if_missing(bundle / "data" / "portfolio_template.csv", RUNTIME_DIR / "data" / "portfolio_template.csv")
    _copy_if_missing(bundle / "data" / "trade_template.csv", RUNTIME_DIR / "data" / "trade_template.csv")
    _copy_if_missing(bundle / ".env.example", RUNTIME_DIR / ".env.example")
    os.environ.setdefault("PORTCLAW_HOME", str(RUNTIME_DIR))


def _start_server(url: str, handler: type[Any]) -> ThreadingHTTPServer | None:
    if _service_is_ready(url):
        _log(f"Existing service is ready: {url}")
        return None
    _log(f"Starting local server on {DEFAULT_HOST}:{DEFAULT_PORT}")
    _log("Creating HTTP server object")
    server = PortClawHTTPServer((DEFAULT_HOST, DEFAULT_PORT), handler)
    _log(f"HTTP server bound to {server.server_address}")
    thread = threading.Thread(target=server.serve_forever, name="PortClawWebServer", daemon=True)
    _log("Starting HTTP server thread")
    thread.start()
    _log("Local server thread started")
    return server


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log("")
    _log("Starting PortClaw desktop app")
    _log(f"Executable: {sys.executable}")
    _log(f"Frozen: {bool(getattr(sys, 'frozen', False))}")
    _log(f"CWD: {os.getcwd()}")
    if hasattr(sys, "_MEIPASS"):
        _log(f"MEIPASS: {getattr(sys, '_MEIPASS')}")
    _prepare_runtime_home()
    _log(f"PORTCLAW_HOME: {os.getenv('PORTCLAW_HOME', '')}")

    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    server: ThreadingHTTPServer | None = None
    try:
        from src.web_app import DEFAULT_HOST as WEB_HOST
        from src.web_app import DEFAULT_PORT as WEB_PORT
        from src.web_app import PortClawAppHandler

        _log("web app handler imported")
        if (WEB_HOST, WEB_PORT) != (DEFAULT_HOST, DEFAULT_PORT):
            _log(f"Warning: web app endpoint differs: {WEB_HOST}:{WEB_PORT}")
        server = _start_server(url, PortClawAppHandler)

        import webview

        _log("pywebview imported")
        webview.create_window(
            "PortClaw",
            url,
            width=1320,
            height=860,
            min_size=(1080, 720),
            confirm_close=True,
        )
        _log("pywebview window created")
        webview.start(debug=False)
        _log("pywebview stopped")
    except Exception:
        _log("Fatal startup error:")
        _log(traceback.format_exc())
        raise
    finally:
        if server:
            _log("Shutting down local server")
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
