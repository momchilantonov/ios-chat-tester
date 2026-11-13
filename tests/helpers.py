import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tester"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakeapp import FakeApp, FakeDriverServer, FakeSimctl  # noqa: E402
from simchat.config import DEFAULTS, _merge  # noqa: E402
from simchat.driver import DriverManager, Simulator  # noqa: E402
from simchat.tester import Tester  # noqa: E402


def make_cfg(port, token, **over):
    cfg = _merge(DEFAULTS, {
        "app": {"bundle_id": "com.example.ChatDemo"},
        "driver": {"port": port, "manage": False, "token": token},
        "chat": {"typing_ids": ["typing"]},
        "pace_ms": 0,
        "waits": {"reply_timeout_s": 3, "quiet_ms": 300, "poll_ms": 80, "send_confirm_s": 2},
        "endpoints": {"conversation": "http://127.0.0.1:8000/conversations/{session_id}",
                      "remote": "http://example.com/x"},
    })
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
        self.http = {}
        sim = Simulator(self.cfg, runner=self.simctl)
        self.tester = Tester(self.cfg, sim=sim, manager=DriverManager(self.cfg, sim),
                             http_get=self._get, runs_dir=self.dir / "runs")

    def _get(self, url):
        if url not in self.http:
            import urllib.error
            raise urllib.error.URLError("connection refused")
        return self.http[url]

    def close(self):
        self.server.close()
        self.tmp.cleanup()
