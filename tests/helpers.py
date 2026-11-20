import importlib.util
import re
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tester"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import simchat.driver as _driver
from fakeapp import FakeApp, FakeDriverServer, FakeSimctl
from simchat.config import DEFAULTS, _merge
from simchat.driver import DriverManager, Simulator
from simchat.tester import Tester

# Tests never touch the real driver's state/log files: a running driver must survive the unit tests.
_SANDBOX = tempfile.mkdtemp(prefix="simchat-tests-")
_driver.BUILD_DIR = Path(_SANDBOX)
_driver.STATE_FILE = Path(_SANDBOX) / "driver.json"
_driver.LOG_FILE = Path(_SANDBOX) / "driver.log"


def make_cfg(port, token, **over):
    cfg = _merge(
        DEFAULTS,
        {
            "app": {"bundle_id": "com.example.ChatDemo"},
            "driver": {"port": port, "manage": False, "token": token},
            "chat": {"typing_ids": ["typing"]},
            "pace_ms": 0,
            "waits": {
                "reply_timeout_s": 3,
                "quiet_ms": 300,
                "poll_ms": 80,
                "send_confirm_s": 2,
            },
            "endpoints": {
                "conversation": "http://127.0.0.1:8000/conversations/{session_id}",
                "remote": "http://example.com/x",
            },
        },
    )
    cfg = _merge(cfg, over)
    cfg["_problems"], cfg["_path"] = [], "test-config.json"
    return cfg


class Stack:
    """Fake app + fake driver + Tester wired together, with a temp runs dir and log file."""

    def __init__(self, **cfg_over):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = FakeApp()
        self.server = FakeDriverServer(self.app)
        self.log = self.dir / "bot.log"
        self.log.write_text("boot\n", encoding="utf-8")
        over = {"logs": {"bot": str(self.log)}}
        over.update(cfg_over)
        self.cfg = make_cfg(self.server.port, self.server.token, **over)
        self.simctl = FakeSimctl()
        self.http: dict[str, Any] = {}
        sim = Simulator(self.cfg, runner=self.simctl)
        self.tester = Tester(
            self.cfg,
            sim=sim,
            manager=DriverManager(self.cfg, sim),
            http_get=self._get,
            runs_dir=self.dir / "runs",
        )

    def _get(self, url: str) -> str:
        if url not in self.http:
            import urllib.error

            raise urllib.error.URLError("connection refused")
        value = self.http[url]
        return str(value()) if callable(value) else value

    def close(self):
        self.server.close()
        self.tmp.cleanup()


def must_search(pattern: str, text: str, flags: int = 0) -> re.Match[str]:
    """re.search for text a test needs: fails the test instead of returning None."""
    found = re.search(pattern, text, flags)
    if found is None:
        raise AssertionError(f"{pattern!r} not found in:\n{text[:2000]}")
    return found


def load_module(name: str, path: Path) -> ModuleType:
    """Import a .py file by its path (install.py is a script, not a package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
