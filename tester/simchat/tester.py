"""High-level chat-testing operations. Every public method returns a JSON-able dict (the MCP tool result)."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import HOME
from .driver import DriverError, DriverManager, Simulator
from .screen import Element, Screen, exact, new_messages, norm

RUNS = HOME / "runs"
SCENARIOS = HOME / "scenarios"
PROFILE = HOME / "profile.md"
WRITABLE = ("runs", "scenarios")
WRITABLE_EXT = (".md", ".json", ".txt", ".yaml", ".yml")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
VERDICTS = ("PASS", "FAIL", "BLOCKED", "INCONCLUSIVE")


class ToolError(Exception):
    """A problem the agent should read and act on (returned as an MCP error result)."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        out = {"error": str(self)}
        out.update(self.details)
        return out


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "run"


def _http_get(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local hosts only
        return resp.read().decode("utf-8", errors="replace")


def _select(doc: Any, path: str) -> Any:
    """Tiny JSON path: 'events[-1].data.text' or 'events.*.event'."""
    if not path:
        return doc
    cur: List[Any] = [doc]
    for part in re.findall(r"[^.\[\]]+|\[-?\d+\]|\[\*\]", path):
        nxt: List[Any] = []
        for node in cur:
            if part in ("*", "[*]"):
                nxt.extend(node if isinstance(node, list) else list(node.values()) if isinstance(node, dict) else [])
            elif part.startswith("["):
                i = int(part[1:-1])
                if isinstance(node, list) and -len(node) <= i < len(node):
                    nxt.append(node[i])
            elif isinstance(node, dict) and part in node:
                nxt.append(node[part])
            elif isinstance(node, list) and part.lstrip("-").isdigit():
                i = int(part)
                if -len(node) <= i < len(node):
                    nxt.append(node[i])
        cur = nxt
    return cur[0] if len(cur) == 1 else cur


class Run:
    def __init__(self, name: str, root: Path, started: float):
        self.name = name
        self.dir = root / ("%s_%s" % (datetime.now().strftime("%Y%m%d-%H%M%S"), _slug(name)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.started = started
        self.checks: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []
        self.transcript: List[Dict[str, Any]] = []
        self.log_offsets: Dict[str, int] = {}
        self.counter = 0

    def journal(self, entry: Dict[str, Any]) -> None:
        entry = dict(entry, ts=datetime.now().isoformat(timespec="milliseconds"))
        with open(self.dir / "journal.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Tester:
    def __init__(self, cfg: Dict[str, Any], sim: Optional[Simulator] = None,
                 manager: Optional[DriverManager] = None, http_get: Callable[[str], str] = _http_get,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 runs_dir: Path = RUNS):
        self.cfg = cfg
        self.sim = sim or Simulator(cfg)
        self.manager = manager or DriverManager(cfg, self.sim, clock=clock, sleep=sleep)
        self.http_get, self.clock, self.sleep = http_get, clock, sleep
        self.runs_dir = runs_dir
        self.run: Optional[Run] = None
        self.last_screen: Optional[Screen] = None   # latest internal snapshot
        self.shown: Optional[Screen] = None         # the screen whose [index] listing the agent saw
        self._before: List[str] = []       # message texts on screen before the last user action
        self._anchor = ""                  # what the user last sent / tapped
        self._turn_offsets: Dict[str, int] = {}
        self._fetch_n = 0

    # ---------------------------------------------------------------- basics
    @property
    def chat(self) -> Dict[str, Any]:
        return self.cfg["chat"]

    def _driver(self):
        client = self.manager.client()
        if not client.alive():
            raise ToolError("UI driver is not running - call start_driver first (it can take 1-3 min the "
                            "first time while Xcode builds it)", driver=self.manager.status())
        return client

    def _call(self, cmd: str, **args: Any) -> Dict[str, Any]:
        try:
            return self._driver().call(cmd, **args)
        except DriverError as exc:
            raise ToolError("driver: %s" % exc, command=cmd)

    def _pace(self) -> None:
        pace = float(self.cfg.get("pace_ms") or 0) / 1000.0
        if pace > 0:
            self.sleep(pace)

    def _snapshot(self) -> Screen:
        scr = Screen(self._call("snapshot"))
        self.last_screen = scr
        return scr

    def _foreground(self) -> Screen:
        scr = self._snapshot()
        if scr.app_state != "foreground":
            self._call("activate")
            scr = self._snapshot()
        if scr.alerts:
            raise ToolError("a system alert covers the app - answer it with tap(alert_button=...)",
                            alerts=scr.alerts)
        if scr.app_state != "foreground":
            raise ToolError("app %s is not in the foreground (state %s)"
                            % (self.cfg["app"]["bundle_id"], scr.app_state))
        return scr

    def _journal(self, entry: Dict[str, Any]) -> None:
        if self.run:
            self.run.journal(entry)

    def _mark_turn(self, anchor: str, before: Screen, exclude: List[Optional[Element]]) -> None:
        self._anchor = anchor
        self._before = [m.text for m in before.messages(exclude)]
        self._turn_offsets = self._log_sizes()

    # ---------------------------------------------------------------- setup / status
    def status(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"config": self.cfg["_path"], "config_problems": self.cfg["_problems"],
                               "app": self.cfg["app"]["bundle_id"]}
        try:
            out["simulator"] = {"udid": self.sim.udid()}
        except DriverError as exc:
            out["simulator"] = {"error": str(exc)}
        out["driver"] = self.manager.status()
        if out["driver"]["phase"] == "ready":
            try:
                out["app_state"] = self.manager.client().call("state").get("app_state")
            except DriverError as exc:
                out["app_state"] = "unknown (%s)" % exc
        out["endpoints"] = {name: self._port_open(url) for name, url in self.cfg["endpoints"].items()}
        out["logs"] = {name: Path(p).expanduser().exists() for name, p in self.cfg["logs"].items()}
        out["run"] = str(self.run.dir) if self.run else None
        out["repos"] = {role: {"path": p, "exists": Path(p).expanduser().is_dir()}
                        for role, p in (self.cfg.get("repos") or {}).items()}
        out["scenarios"] = self._scenario_names()
        try:
            out["profile"] = PROFILE.read_text(encoding="utf-8")[:8000]
        except OSError:
            out["profile"] = None
            out["config_problems"] = out["config_problems"] + ["%s missing - run install.py" % PROFILE]
        out["ok"] = (not out["config_problems"] and "error" not in out["simulator"]
                     and out["driver"]["phase"] == "ready" and all(v == "open" for v in out["endpoints"].values()))
        return out

    @staticmethod
    def _port_open(url: str) -> str:
        import socket
        parts = urllib.parse.urlsplit(url.replace("{", "").replace("}", ""))
        try:
            with socket.create_connection((parts.hostname or "127.0.0.1", parts.port or 80), timeout=1.5):
                return "open"
        except OSError:
            return "closed"

    def start_driver(self, wait_s: float = 50) -> Dict[str, Any]:
        try:
            st = self.manager.ensure(wait_s=max(1.0, min(float(wait_s), 110.0)))
        except DriverError as exc:
            raise ToolError(str(exc), driver=self.manager.status())
        if st["phase"] != "ready":
            st["hint"] = "still starting/building - call start_driver again"
        return st

    def stop_driver(self) -> Dict[str, Any]:
        return self.manager.stop()

    def open_app(self, fresh: bool = False) -> Dict[str, Any]:
        self._pace()
        if fresh:
            res = self._call("launch", arguments=list(self.cfg["app"].get("launch_arguments") or []))
        else:
            res = self._call("activate")
        self._journal({"action": "open_app", "fresh": fresh})
        self._before, self._anchor = [], ""
        return {"app_state": res.get("app_state"), "fresh": fresh}

    # ---------------------------------------------------------------- looking
    def screen(self, image: bool = False) -> Dict[str, Any]:
        scr = self._snapshot()
        self.shown = scr
        comp = scr.composer(self.chat)
        send = scr.send_button(self.chat, comp)
        out: Dict[str, Any] = {
            "app_state": scr.app_state, "keyboard": scr.keyboard, "alerts": scr.alerts,
            "elements": scr.listing(),
            "messages": [m.text for m in scr.messages([comp])],
            "buttons": ["[%d] %s" % (b.index, b.label or b.id) for b in scr.buttons([comp, send])],
            "composer": comp.describe() if comp else None,
            "send_button": send.describe() if send else None,
            "typing": scr.typing(self.chat),
        }
        if image:
            try:
                out["_image"] = self._screenshot_file("screen")
            except DriverError as exc:
                out["image_error"] = str(exc)
        return out

    def _screenshot_file(self, name: str) -> str:
        udid = self.sim.udid()
        folder = (self.run.dir / "screenshots") if self.run else (self.runs_dir / "_scratch")
        if self.run:
            self.run.counter += 1
            name = "%02d-%s" % (self.run.counter, _slug(name))
        path = self.sim.screenshot(udid, folder / ("%s.png" % _slug(name)))
        self._journal({"action": "screenshot", "path": str(path)})
        return str(path)

    def screenshot(self, name: str = "screen") -> Dict[str, Any]:
        try:
            path = self._screenshot_file(name)
        except DriverError as exc:
            raise ToolError(str(exc))
        return {"path": path, "_image": path}

    # ---------------------------------------------------------------- acting
    def tap(self, element: Optional[int] = None, text: str = "", id: str = "",  # noqa: A002
            x: Optional[float] = None, y: Optional[float] = None, alert_button: str = "") -> Dict[str, Any]:
        if alert_button:
            self._pace()
            self._call("tap_alert", label=alert_button)
            self._journal({"action": "tap_alert", "label": alert_button})
            return {"tapped": "system alert button %r" % alert_button}
        before = self._foreground()
        comp = before.composer(self.chat)
        target = self._target(before, element, text, id)
        if target is not None:
            if not target.enabled:
                raise ToolError("element is disabled", element=target.describe())
            px, py = target.center
            what = target.describe()
            anchor = target.text
        elif x is not None and y is not None:
            px, py, what, anchor = float(x), float(y), "point (%s, %s)" % (x, y), ""
        else:
            raise ToolError("tap needs element, text, id, x+y or alert_button")
        self._mark_turn(anchor, before, [comp])
        self._pace()
        self._call("tap", x=px, y=py)
        entry = {"action": "tap", "target": what, "x": px, "y": py}
        if target is not None:
            entry.update({"label": target.label, "id": target.id, "value": target.value, "type": target.type})
            if self.run and target.type in ("button", "link"):
                self.run.transcript.append({"from": "user", "tap": target.label or target.id})
        self._journal(entry)
        return {"tapped": what, "next": "call wait_for_reply if this should make the bot answer"}

    def _target(self, before: Screen, element: Optional[int], text: str, ident: str) -> Optional[Element]:
        """Resolve element [index] (from the listing the agent saw), visible text or accessibility id."""
        target: Optional[Element] = None
        if element is not None:
            if self.shown is None:
                raise ToolError("no screen listing yet - call screen() first")
            old = next((e for e in self._listed() if e.index == int(element)), None)
            if old is None:
                raise ToolError("element [%s] not in the last screen listing" % element)
            target = before.locate(old)
            if target is None:
                raise ToolError("element [%s] %r is no longer on screen - call screen() again"
                                % (element, old.text or old.type))
        elif text or ident:
            hits = before.find(text=text, ident=ident)
            if not hits:
                comp = before.composer(self.chat)
                raise ToolError("nothing on screen matches %r" % (text or ident),
                                buttons=[b.label for b in before.buttons([comp])])
            target = hits[0]
        if target is not None and not before.on_screen(target):
            raise ToolError("element is off screen - scroll first", element=target.describe())
        return target

    def swipe(self, direction: str, element: Optional[int] = None, text: str = "", id: str = "",  # noqa: A002
              x: Optional[float] = None, y: Optional[float] = None, distance: float = 0.6,
              speed: str = "normal") -> Dict[str, Any]:
        """Swipe with one finger. direction = where the finger moves: 'left' on a carousel shows the next item."""
        direction = (direction or "").lower()
        if direction not in ("left", "right", "up", "down"):
            raise ToolError("direction must be left, right, up or down")
        if speed not in ("slow", "normal", "fast"):
            raise ToolError("speed must be slow, normal or fast")
        before = self._foreground()
        w, h = before.width or 390.0, before.height or 844.0
        target = self._target(before, element, text, id)
        if target is not None:
            cx, cy = target.center
            span_w, span_h = max(target.w, 120.0), max(target.h, 120.0)
            what = target.describe()
        elif x is not None and y is not None:
            cx, cy, span_w, span_h = float(x), float(y), w, h
            what = "point (%s, %s)" % (x, y)
        else:
            cx, cy, span_w, span_h = w / 2, h / 2, w, h
            what = "screen centre"
        frac = max(0.1, min(float(distance), 0.95))
        half = (span_w if direction in ("left", "right") else span_h) * frac / 2
        dx = {"left": -1, "right": 1}.get(direction, 0)
        dy = {"up": -1, "down": 1}.get(direction, 0)

        def clamp(v: float, hi: float) -> float:
            return round(max(2.0, min(v, hi - 2.0)), 1)

        x1, y1 = clamp(cx - dx * half, w), clamp(cy - dy * half, h)
        x2, y2 = clamp(cx + dx * half, w), clamp(cy + dy * half, h)
        seen = {(e.type, e.text) for e in before.visible() if e.text}
        self._pace()
        self._call("swipe", x1=x1, y1=y1, x2=x2, y2=y2, speed=speed)
        self.sleep(0.6)  # let paging/scroll animations settle
        after = self._snapshot()
        appeared = [e.text for e in after.visible() if e.text and (e.type, e.text) not in seen]
        gone = sorted({t for (_, t) in seen} - {e.text for e in after.visible() if e.text})
        self._journal({"action": "swipe", "direction": direction, "on": what,
                       "from": [x1, y1], "to": [x2, y2], "speed": speed})
        return {"swiped": direction, "on": what, "from": [x1, y1], "to": [x2, y2],
                "now_visible": appeared[:40], "no_longer_visible": gone[:40],
                "changed": bool(appeared or gone),
                "next": "call screen() to get fresh [index] numbers before tapping"}

    def long_press(self, element: Optional[int] = None, text: str = "", id: str = "",  # noqa: A002
                   x: Optional[float] = None, y: Optional[float] = None, duration: float = 1.0) -> Dict[str, Any]:
        before = self._foreground()
        target = self._target(before, element, text, id)
        if target is not None:
            px, py = target.center
            what = target.describe()
        elif x is not None and y is not None:
            px, py, what = float(x), float(y), "point (%s, %s)" % (x, y)
        else:
            raise ToolError("long_press needs element, text, id or x+y")
        seconds = max(0.3, min(float(duration), 5.0))
        self._pace()
        self._call("long_press", x=px, y=py, duration=seconds)
        self.sleep(0.4)
        after = self._snapshot()
        seen = {(e.type, e.text) for e in before.visible() if e.text}
        appeared = [e.text for e in after.visible() if e.text and (e.type, e.text) not in seen]
        self._journal({"action": "long_press", "on": what, "x": px, "y": py, "duration": seconds})
        return {"long_pressed": what, "now_visible": appeared[:40],
                "next": "call screen() to see a menu that may have opened"}

    def _listed(self) -> List[Element]:
        return self.shown.elements if self.shown else []

    def type_text(self, text: str, element: Optional[int] = None) -> Dict[str, Any]:
        """Type into a field (default: the chat composer) and read it back. Does not press Send."""
        scr = self._foreground()
        field = scr.composer(self.chat)
        if element is not None:
            old = next((e for e in self._listed() if e.index == int(element)), None)
            field = scr.locate(old) if old else None
        if field is None:
            raise ToolError("no text field found on screen")
        typed = self._type_into(field, text)
        return {"typed": text, "read_back": typed.value, "field": typed.describe()}

    def _type_into(self, field: Element, text: str) -> Element:
        self._pace()
        self._call("tap", x=field.center[0], y=field.center[1])
        for attempt in (1, 2):
            scr = self._snapshot()
            cur = scr.locate(field) or scr.composer(self.chat)
            if cur is None:
                raise ToolError("text field disappeared after tapping it")
            if not scr.is_empty_input(cur):
                self._call("delete", count=len(cur.value) + 2)
            self._pace()
            self._call("type", text=text)
            scr = self._snapshot()
            cur = scr.locate(field) or scr.composer(self.chat)
            if cur is not None and exact(cur.value) == exact(text):
                return cur
            got = cur.value if cur else None
            if cur is not None:
                self._call("delete", count=len(cur.value) + 2)
            if attempt == 2:
                raise ToolError("typed text did not read back correctly - nothing was sent (field cleared)",
                                expected=text, read_back=got)
        raise ToolError("unreachable")

    def send_message(self, text: str) -> Dict[str, Any]:
        """Type the message, verify it reads back, tap Send exactly once, confirm it left the composer."""
        if not text or "\n" in text:
            raise ToolError("send_message needs one non-empty line of text")
        before = self._foreground()
        comp = before.composer(self.chat)
        if comp is None:
            raise ToolError("no chat composer (text input) visible", screen=before.listing(40))
        typed = self._type_into(comp, text)
        scr = self.last_screen or before
        send = scr.send_button(self.chat, typed)
        if send is None:
            self._call("delete", count=len(typed.value) + 2)
            raise ToolError("Send button not found - nothing was sent (field cleared). Set chat.send_labels or "
                            "chat.send_ids in config.json", buttons=[b.describe() for b in scr.buttons()])
        self._mark_turn(text, before, [comp])
        self._pace()
        self._call("tap", x=send.center[0], y=send.center[1])
        self._journal({"action": "send", "text": text, "composer": comp.describe(), "send": send.describe()})
        if self.run:
            self.run.transcript.append({"from": "user", "text": text})
        deadline = self.clock() + float(self.cfg["waits"]["send_confirm_s"])
        while True:
            scr = self._snapshot()
            cur = scr.locate(typed) or scr.composer(self.chat)
            bubble = any(norm(m.text) == norm(text) for m in scr.messages([cur]))
            if (cur is not None and scr.is_empty_input(cur)) or bubble:
                return {"sent": text, "confirmed": True, "next": "call wait_for_reply"}
            if self.clock() >= deadline:
                return {"sent": text, "confirmed": False,
                        "warning": "Send was tapped once but the text is still in the composer. Do NOT send "
                                   "again - look at screen()/screenshot() first."}
            self.sleep(0.4)

    def wait_for_reply(self, timeout_s: Optional[float] = None, quiet_ms: Optional[float] = None) -> Dict[str, Any]:
        """Wait until new bot content appeared and the screen stopped changing."""
        waits = self.cfg["waits"]
        timeout = float(timeout_s if timeout_s is not None else waits["reply_timeout_s"])
        quiet = float(quiet_ms if quiet_ms is not None else waits["quiet_ms"]) / 1000.0
        poll = float(waits["poll_ms"]) / 1000.0
        start = self.clock()
        last_sig, stable_since = None, start
        while True:
            scr = self._snapshot()
            comp = scr.composer(self.chat)
            now = self.clock()
            sig = scr.signature()
            if sig != last_sig:
                last_sig, stable_since = sig, now
            new = new_messages(self._before, scr, self._anchor, [comp])
            typing = scr.typing(self.chat)
            settled = now - stable_since >= quiet
            if (new and settled and not typing) or scr.alerts or now - start >= timeout:
                break
            self.sleep(poll)
        self.shown = scr
        send = scr.send_button(self.chat, comp)
        buttons = scr.buttons([comp, send])
        out = {"replied": bool(new), "new_messages": new,
               "buttons": ["[%d] %s" % (b.index, b.label or b.id) for b in buttons],
               "waited_s": round(self.clock() - start, 1), "typing": typing}
        if not new:
            out["timed_out"] = True
            out["hint"] = "no new bot message - check screen()/screenshot() and read_log(since='turn')"
        if scr.alerts:
            out["alerts"] = scr.alerts
        self._journal(dict(out, action="wait_for_reply"))
        if self.run and new:
            self.run.transcript.append({"from": "bot", "messages": new,
                                        "buttons": [b.label or b.id for b in buttons]})
        # Next wait compares against this screen unless a new action resets it.
        self._before = [m.text for m in scr.messages([comp])]
        self._anchor = ""
        return out

    def scroll(self, direction: str = "up", amount: float = 0.5) -> Dict[str, Any]:
        """direction 'up' shows earlier content (finger moves down), 'down' shows later content."""
        scr = self._foreground()
        w, h = scr.width or 390, scr.height or 844
        dy = h * max(0.1, min(float(amount), 0.8)) / 2
        cy = h * 0.5
        y1, y2 = (cy - dy, cy + dy) if direction == "up" else (cy + dy, cy - dy)
        self._pace()
        self._call("swipe", x1=w / 2, y1=y1, x2=w / 2, y2=y2)
        self._journal({"action": "scroll", "direction": direction})
        return {"scrolled": direction}

    # ---------------------------------------------------------------- evidence
    def fetch(self, endpoint: str, vars: Optional[Dict[str, Any]] = None,  # noqa: A002
              path: str = "", max_chars: int = 20000) -> Dict[str, Any]:
        tmpl = self.cfg["endpoints"].get(endpoint)
        if not tmpl:
            raise ToolError("unknown endpoint %r" % endpoint, configured=sorted(self.cfg["endpoints"]))
        url = tmpl
        for key, value in (vars or {}).items():
            url = url.replace("{%s}" % key, urllib.parse.quote(str(value), safe=""))
        if re.search(r"{\w+}", url):
            raise ToolError("missing vars for %s" % re.findall(r"{(\w+)}", url), template=tmpl)
        if urllib.parse.urlsplit(url).hostname not in LOCAL_HOSTS:
            raise ToolError("only local endpoints are allowed", url=url)
        try:
            body = self.http_get(url)
        except urllib.error.HTTPError as exc:
            raise ToolError("HTTP %s from %s" % (exc.code, url))
        except (urllib.error.URLError, OSError) as exc:
            raise ToolError("cannot reach %s (%s) - is the service running?" % (url, exc))
        out: Dict[str, Any] = {"url": url}
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        if self.run:
            self._fetch_n += 1
            saved = self.run.dir / ("fetch-%02d-%s.%s" % (self._fetch_n, _slug(endpoint), "json" if doc is not None else "txt"))
            saved.write_text(body, encoding="utf-8")
            out["saved"] = str(saved)
            self._journal({"action": "fetch", "endpoint": endpoint, "url": url, "saved": str(saved)})
        if doc is not None:
            text = json.dumps(_select(doc, path), ensure_ascii=False)
        else:
            text = body
        out["truncated"] = len(text) > max_chars
        out["data"] = text[:max_chars]
        return out

    def _log_sizes(self) -> Dict[str, int]:
        sizes = {}
        for name, p in self.cfg["logs"].items():
            try:
                sizes[name] = Path(p).expanduser().stat().st_size
            except OSError:
                sizes[name] = 0
        return sizes

    def read_log(self, name: str = "", since: str = "turn", grep: str = "", max_lines: int = 200) -> Dict[str, Any]:
        logs = self.cfg["logs"]
        if not logs:
            raise ToolError("no logs configured in config.json")
        name = name or next(iter(logs))
        if name not in logs:
            raise ToolError("unknown log %r" % name, configured=sorted(logs))
        path = Path(logs[name]).expanduser()
        if not path.exists():
            raise ToolError("log file %s does not exist - is the service writing to it?" % path)
        size = path.stat().st_size
        if since == "turn":
            start = self._turn_offsets.get(name, 0)
        elif since == "run":
            start = self.run.log_offsets.get(name, 0) if self.run else 0
        else:
            start = max(0, size - 400_000)
        if start > size:  # rotated / truncated
            start = 0
        with open(path, "rb") as fh:
            fh.seek(start)
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        if grep:
            rx = re.compile(grep, re.IGNORECASE)
            lines = [ln for ln in lines if rx.search(ln)]
        errs = [ln for ln in lines if any(p in ln for p in self.cfg.get("error_patterns") or [])]
        total = len(lines)
        lines = lines[-int(max_lines):]
        return {"log": name, "since": since, "lines": lines, "total_lines": total,
                "error_lines": errs[-30:], "error_count": len(errs)}

    # ---------------------------------------------------------------- scenarios
    @staticmethod
    def _scenario_names() -> List[str]:
        if not SCENARIOS.is_dir():
            return []
        return sorted(str(p.relative_to(SCENARIOS)) for p in SCENARIOS.rglob("*")
                      if p.is_file() and p.suffix.lower() in WRITABLE_EXT)

    def scenarios(self, name: str = "") -> Dict[str, Any]:
        if not name:
            return {"folder": str(SCENARIOS), "scenarios": self._scenario_names()}
        path = (SCENARIOS / name).resolve()
        if SCENARIOS.resolve() not in path.parents or not path.is_file():
            raise ToolError("no scenario %r" % name, scenarios=self._scenario_names())
        return {"name": name, "path": str(path), "content": path.read_text(encoding="utf-8")}

    # ---------------------------------------------------------------- runs
    def start_run(self, name: str) -> Dict[str, Any]:
        if self.run:
            self.end_run("INCONCLUSIVE", "Superseded by a new run before it was ended.")
        self.run = Run(name, self.runs_dir, self.clock())
        self.run.log_offsets = self._log_sizes()
        self._turn_offsets = dict(self.run.log_offsets)
        self.run.journal({"action": "start_run", "name": name})
        return {"run_dir": str(self.run.dir)}

    def _need_run(self) -> Run:
        if not self.run:
            raise ToolError("no active run - call start_run(name) first")
        return self.run

    def check(self, name: str, passed: bool, evidence: str) -> Dict[str, Any]:
        run = self._need_run()
        if not evidence.strip():
            raise ToolError("a check needs evidence (quoted bot text, payload, log line, ...)")
        item = {"name": name, "passed": bool(passed), "evidence": evidence}
        run.checks.append(item)
        run.journal(dict(item, action="check"))
        return {"recorded": item, "checks_so_far": len(run.checks)}

    def note(self, text: str, kind: str = "observation") -> Dict[str, Any]:
        run = self._need_run()
        item = {"kind": kind, "text": text}
        run.notes.append(item)
        run.journal(dict(item, action="note"))
        return {"recorded": item}

    def end_run(self, verdict: str, summary: str) -> Dict[str, Any]:
        run = self._need_run()
        verdict = verdict.upper().strip()
        if verdict not in VERDICTS:
            raise ToolError("verdict must be one of %s" % ", ".join(VERDICTS))
        failed = [c for c in run.checks if not c["passed"]]
        final, reason = verdict, ""
        if verdict == "PASS" and failed:
            final, reason = "FAIL", "%d check(s) failed" % len(failed)
        elif verdict == "PASS" and not run.checks:
            final, reason = "INCONCLUSIVE", "PASS needs at least one recorded check"
        result = {"name": run.name, "verdict": final, "requested_verdict": verdict, "verdict_reason": reason,
                  "summary": summary, "checks": run.checks, "notes": run.notes,
                  "duration_s": round(self.clock() - run.started, 1)}
        (run.dir / "run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (run.dir / "transcript.json").write_text(json.dumps(run.transcript, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        for name in self.cfg["logs"]:
            try:
                part = self.read_log(name, since="run", max_lines=100000)
                (run.dir / ("log-%s.txt" % _slug(name))).write_text("\n".join(part["lines"]) + "\n", encoding="utf-8")
            except ToolError:
                pass
        run.journal({"action": "end_run", "verdict": final})
        self.run = None
        return {"run_dir": str(run.dir), "verdict": final, "verdict_reason": reason,
                "next": "write report.md into run_dir with write_file"}

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        target = (HOME / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        allowed = [(HOME / d).resolve() for d in WRITABLE] + [self.runs_dir.resolve()]
        if not any(target == a or a in target.parents for a in allowed):
            raise ToolError("you may only write under %s" % ", ".join(str(a) for a in allowed))
        if target.suffix.lower() not in WRITABLE_EXT:
            raise ToolError("allowed file types: %s" % ", ".join(WRITABLE_EXT))
        if len(content) > 1_000_000:
            raise ToolError("file too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"written": str(target), "bytes": len(content.encode("utf-8"))}
