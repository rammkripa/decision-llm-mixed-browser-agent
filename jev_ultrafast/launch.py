"""Launch an isolated local Chrome and clean up its owned Browser Harness daemon."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def chrome_binary():
    configured = os.environ.get("JEV_CHROME_BIN")
    if configured:
        if Path(configured).is_file():
            return configured
        raise RuntimeError("JEV_CHROME_BIN must point to a Chrome executable")
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    if sys.platform == "win32":
        candidates = [str(Path(os.environ.get(key, "")) / "Google/Chrome/Application/chrome.exe")
                      for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if executable := shutil.which(name):
            return executable
    raise RuntimeError("Chrome was not found. Install Chrome or set JEV_CHROME_BIN to its executable.")


def chrome_command(binary, profile, *, headless):
    return [binary, f"--user-data-dir={profile}", "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
            *(["--headless=new"] if headless else []), "about:blank"]


@contextmanager
def launched_browser(*, headless=True):
    binary = chrome_binary()
    name = "jev-cli-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="jev-chrome-") as folder:
        profile = Path(folder)
        with (profile / "chrome.log").open("w") as log:
            process = subprocess.Popen(chrome_command(binary, profile, headless=headless),
                                       stdout=subprocess.DEVNULL, stderr=log)
            try:
                port_file = profile / "DevToolsActivePort"
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Chrome exited during startup; check JEV_CHROME_BIN "
                                           "and display availability")
                    if port_file.exists():
                        lines = port_file.read_text().splitlines()
                        if lines and lines[0].isdigit():
                            break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Chrome did not expose a debugging endpoint within 20 seconds")
                    time.sleep(.05)
                env = dict(os.environ)
                env.pop("BU_CDP_WS", None)
                env.pop("BU_BROWSER_ID", None)
                env.update(BU_NAME=name, BU_CDP_URL=f"http://127.0.0.1:{lines[0]}")
                yield env
            finally:
                try:
                    # The unique daemon is owned by this launch, never the user's default connection.
                    from browser_harness.admin import restart_daemon

                    restart_daemon(name)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
