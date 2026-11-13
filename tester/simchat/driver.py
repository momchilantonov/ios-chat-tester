"""Talks to the SimDriver XCTest server and manages its process and the simulator (xcrun simctl)."""
from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import HOME

DRIVER_DIR = HOME / "driver"
BUILD_DIR = DRIVER_DIR / ".build"
STATE_FILE = BUILD_DIR / "driver.json"
LOG_FILE = BUILD_DIR / "driver.log"


class DriverError(Exception):
    """The driver answered with an error, or could not be reached."""


class DriverClient:
    def __init__(self, port: int, token: str = "", host: str = "127.0.0.1", timeout: float = 90.0):
        self.host, self.port, self.token, self.timeout = host, port, token, timeout

    def call(self, cmd: str, **args: Any) -> Dict[str, Any]:
        request = json.dumps({"token": self.token, "cmd": cmd, "args": args}, ensure_ascii=False)
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(request.encode("utf-8") + b"\n")
                chunks = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
        except OSError as exc:
            raise DriverError("driver not reachable on %s:%s (%s)" % (self.host, self.port, exc))
        raw = b"".join(chunks).split(b"\n", 1)[0]
        try:
            reply = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise DriverError("driver sent an invalid reply: %r" % raw[:200])
        if not reply.get("ok"):
            raise DriverError(str(reply.get("error") or "driver error"))
        return reply

    def alive(self) -> bool:
        try:
            return self.call("ping").get("driver") == "simchat"
        except DriverError:
            return False


Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]


def run(cmd: List[str], timeout: float = 60) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class Simulator:
    """xcrun simctl helpers. Works on whatever simulator is already booted unless a UDID is pinned."""

    def __init__(self, cfg: Dict[str, Any], runner: Runner = run):
        self.cfg, self.runner = cfg, runner

    def booted(self) -> List[Dict[str, str]]:
        try:
            res = self.runner(["xcrun", "simctl", "list", "devices", "booted", "-j"])
        except (OSError, subprocess.SubprocessError) as exc:
            raise DriverError("xcrun simctl not available (%s) - is Xcode installed?" % exc)
        if res.returncode != 0:
            raise DriverError("simctl failed: %s" % (res.stderr or res.stdout).strip()[:300])
        devices = []
        for runtime, items in json.loads(res.stdout).get("devices", {}).items():
            for d in items:
                if d.get("state") == "Booted":
                    devices.append({"udid": d["udid"], "name": d.get("name", ""), "runtime": runtime})
        return devices

    def udid(self) -> str:
        pinned = self.cfg["simulator"].get("udid") or ""
        booted = self.booted()
        if pinned:
            if not any(d["udid"] == pinned for d in booted):
                raise DriverError("pinned simulator %s is not booted - boot it in Xcode/Simulator" % pinned)
            return pinned
        if not booted:
            raise DriverError("no booted simulator - start one from Xcode (Run the app) or Simulator.app")
        if len(booted) > 1:
            names = ", ".join("%s (%s)" % (d["name"], d["udid"]) for d in booted)
            raise DriverError("several simulators are booted (%s) - set simulator.udid in config.json" % names)
        return booted[0]["udid"]

    def show(self, udid: str) -> None:
        """Bring Simulator.app to the front so a human can watch the run."""
        if self.cfg["simulator"].get("open_simulator_app", True):
            try:
                self.runner(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid])
            except (OSError, subprocess.SubprocessError):
                pass

    def screenshot(self, udid: str, path: Path, max_px: int = 1000) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        res = self.runner(["xcrun", "simctl", "io", udid, "screenshot", "--type=png", str(path)])
        if res.returncode != 0 or not path.exists():
            raise DriverError("screenshot failed: %s" % (res.stderr or res.stdout).strip()[:300])
        try:  # macOS built-in image tool; keeps images small for the model
            self.runner(["sips", "-Z", str(max_px), str(path)])
        except (OSError, subprocess.SubprocessError):
            pass
        return path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


class DriverManager:
    """Starts/stops the driver process (only the one we started) and hands out clients."""

    def __init__(self, cfg: Dict[str, Any], sim: Simulator,
                 popen: Callable[..., Any] = subprocess.Popen, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.sim, self.popen, self.clock, self.sleep = cfg, sim, popen, clock, sleep

    def _state(self) -> Dict[str, Any]:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def client(self) -> DriverClient:
        dcfg = self.cfg["driver"]
        if not dcfg.get("manage", True):
            return DriverClient(int(dcfg["port"]), dcfg.get("token", ""))
        state = self._state()
        return DriverClient(int(state.get("port", dcfg["port"])), state.get("token", ""))

    def status(self) -> Dict[str, Any]:
        state = self._state()
        alive = self.client().alive()
        pid = state.get("pid")
        if alive:
            phase = "ready"
        elif pid and _pid_alive(pid):
            phase = "starting"
        else:
            phase = "stopped"
        out = {"phase": phase, "port": self.client().port}
        if state:
            out.update({k: state.get(k) for k in ("pid", "udid", "bundle_id")})
        if phase != "ready" and LOG_FILE.exists():
            out["log_tail"] = self.log_tail(12)
        return out

    def log_tail(self, lines: int = 20) -> List[str]:
        try:
            text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [ln for ln in text.splitlines() if ln.strip()][-lines:]

    def ensure(self, wait_s: float = 50) -> Dict[str, Any]:
        """Start the driver if needed and wait up to wait_s for it. Returns status()."""
        st = self.status()
        if st["phase"] == "ready":
            return st
        if not self.cfg["driver"].get("manage", True):
            raise DriverError("driver not reachable and driver.manage is false - start it yourself")
        if st["phase"] == "stopped":
            udid = self.sim.udid()
            self.sim.show(udid)
            bundle = self.cfg["app"]["bundle_id"]
            port = int(self.cfg["driver"]["port"])
            token = secrets.token_hex(16)
            BUILD_DIR.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            if self.cfg["driver"].get("xcodebuild_args"):
                env["SIMCHAT_XCODEBUILD_ARGS"] = str(self.cfg["driver"]["xcodebuild_args"])
            log = open(LOG_FILE, "w", encoding="utf-8")
            proc = self.popen(["bash", str(DRIVER_DIR / "run-driver.sh"), udid, bundle, str(port), token],
                              stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              cwd=str(DRIVER_DIR), env=env, start_new_session=True)
            log.close()
            STATE_FILE.write_text(json.dumps({"pid": proc.pid, "port": port, "token": token, "udid": udid,
                                              "bundle_id": bundle, "started": time.time()}), encoding="utf-8")
        deadline = self.clock() + wait_s
        while self.clock() < deadline:
            st = self.status()
            if st["phase"] != "starting":
                break
            self.sleep(1.0)
        st = self.status()
        if st["phase"] == "stopped":
            raise DriverError("driver process exited - see log_tail / %s: %s"
                              % (LOG_FILE, " | ".join(self.log_tail(8))))
        return st

    def stop(self) -> Dict[str, Any]:
        state = self._state()
        try:
            self.client().call("stop")
        except DriverError:
            pass
        pid = state.get("pid")
        if pid and _pid_alive(pid):
            deadline = self.clock() + 8
            while self.clock() < deadline and _pid_alive(pid):
                self.sleep(0.5)
            if _pid_alive(pid):  # only the process group we started ourselves
                try:
                    os.killpg(pid, signal.SIGTERM)
                except OSError:
                    pass
        try:
            STATE_FILE.unlink()
        except OSError:
            pass
        return {"phase": "stopped"}
