"""High-level chat-testing operations. Every public method returns a JSON-able dict (the MCP tool result)."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import HOME
from .driver import DriverError, DriverManager, Simulator
from .plan import (
    STATUSES,
    fill_results,
    format_result,
    lint_plan,
    parse_plan,
    public_rows,
)
from .screen import (
    BUTTON_TYPES,
    CONTROL_TYPES,
    Element,
    Screen,
    anchor_hits,
    exact,
    group_options,
    key,
    new_message_elements,
    norm,
    norm_label,
)

RUNS = HOME / "runs"
PLANS = HOME / "plans"
PROFILE = HOME / "profile.md"
WRITABLE = ("runs", "plans")
WRITABLE_EXT = (".md", ".json", ".txt", ".yaml", ".yml")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
VERDICTS = ("PASS", "FAIL", "BLOCKED", "INCOMPLETE", "INCONCLUSIVE")
DRIVER_VERSION = 3  # SimDriverServer.swift "ping" version this code expects (2: "hittable", 3: its "frames")
ECHO_WAIT_S = 2.0  # after a tap: how long to look for the user's own echo bubble
MAX_SCROLL_UP = 3  # swipes to find the start of a reply that is longer than the screen
# widget markup: [SELECT <title>\n0.0 PTS]
_MARKER = re.compile(r"\[[A-Z][A-Z_-]{2,}(?:\s+|(?=\]))([^\]]*)\]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")


def _paragraphs(texts: list[str]) -> list[str]:
    """Evidence texts as lines a chat may draw as separate bubbles: widget markup ([SELECT ...], which may span
    lines) reduced to the text it shows, markdown links to their text, URLs dropped."""
    out: list[str] = []
    for t in texts:
        text = _MARKER.sub(lambda m: "\n".join(_widget_items(m.group(1))), str(t))
        lines: list[str] = []
        for line in text.splitlines():
            # markup cut across evidence items: what is left is a widget body
            if _OPEN_MARKER.search(line):
                lines.extend(_widget_items(_OPEN_MARKER.sub("", line)))
            else:
                lines.append(line)
        for line in lines:
            line = _URL.sub("", _MD_LINK.sub(r"\1", line)).strip()
            if len(key(line)) >= 3 and line.casefold() not in _EMPTY_VALUES:
                out.append(line)
    return out


# markup cut across evidence items
_OPEN_MARKER = re.compile(r"^\[[A-Z][A-Z_-]{2,}(?:\s+|$)|\]$")
_EMPTY_VALUES = {"none", "null", "nil", "undefined", "n/a"}


def _widget_items(body: str) -> list[str]:
    """What a widget shows: its items separated by "|" or lines, without empty values ("None") - e.g. an
    unlabelled checkbox list expects no text (its rows are checked as evidence_options)."""
    items = [x.strip() for part in body.splitlines() for x in part.split("|")]
    return [x for x in items if x and x.casefold() not in _EMPTY_VALUES]


def _ekey(text: str) -> str:
    """key() with numbers compared loosely: "0.0", "0," and "0" are the same; "12.50" = "12,5"."""

    def num(m: re.Match) -> str:
        v = m.group(0).replace(",", ".")
        return (f"{float(v):f}").rstrip("0").rstrip(".") if "." in v else v

    return key(_NUMBER.sub(num, text or ""))


def _missing(paragraphs: list[str], shown: list[str]) -> list[str]:
    """Evidence paragraphs whose start is not among the texts shown on screen."""
    hay = _ekey(" ".join(shown))
    return [p for p in paragraphs if _ekey(p)[:60] not in hay]


class ToolError(Exception):
    """A problem the agent should read and act on (returned as an MCP error result)."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        out = {"error": str(self)}
        out.update(self.details)
        return out


def _row_text(row: list[Element]) -> str:
    """The texts of one table row, left to right."""
    return " · ".join(e.text for e in sorted(row, key=lambda e: e.x))


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "run"


def _http_get(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _select_all(doc: Any, path: str) -> list[Any]:
    """Tiny JSON path, always a list of matches: 'events[-1].data.text', 'events[-6:].text',
    'events.*.event'. A key applied to a list is applied to each element."""
    if not path:
        return [doc]
    cur: list[Any] = [doc]
    for part in re.findall(r"[^.\[\]]+|\[-?\d*:-?\d*\]|\[-?\d+\]|\[\*\]", path):
        nxt: list[Any] = []
        for node in cur:
            if part in ("*", "[*]"):
                nxt.extend(
                    node
                    if isinstance(node, list)
                    else list(node.values())
                    if isinstance(node, dict)
                    else []
                )
            elif part.startswith("[") and ":" in part:
                a, b = part[1:-1].split(":")
                if isinstance(node, list):
                    nxt.extend(node[int(a) if a else None : int(b) if b else None])
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
            elif isinstance(node, list):
                nxt.extend(x[part] for x in node if isinstance(x, dict) and part in x)
        cur = nxt
    return cur


def _select(doc: Any, path: str) -> Any:
    cur = _select_all(doc, path)
    sliced = bool(re.search(r"\[-?\d*:-?\d*\]|\*", path or ""))
    return cur[0] if len(cur) == 1 and not sliced else cur


class Run:
    def __init__(self, name: str, root: Path, started: float):
        self.name = name
        self.dir = root / (
            "{}_{}".format(datetime.now().strftime("%Y%m%d-%H%M%S"), _slug(name))
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        self.started = started
        self.wall_start = time.time()
        self.checks: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []
        self.log_offsets: dict[str, int] = {}
        self.counter = 0
        self.plan_path: Path | None = None
        self.plan_text = ""
        self.rows: list[dict[str, Any]] = []
        self.results: dict[int, dict[str, Any]] = {}

    def journal(self, entry: dict[str, Any]) -> None:
        entry = dict(entry, ts=datetime.now().isoformat(timespec="milliseconds"))
        with open(self.dir / "journal.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Tester:
    def __init__(
        self,
        cfg: dict[str, Any],
        sim: Simulator | None = None,
        manager: DriverManager | None = None,
        http_get: Callable[[str], str] = _http_get,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        runs_dir: Path = RUNS,
    ):
        self.cfg = cfg
        self.sim = sim or Simulator(cfg)
        self.manager = manager or DriverManager(cfg, self.sim, clock=clock, sleep=sleep)
        self.http_get, self.clock, self.sleep = http_get, clock, sleep
        self.runs_dir = runs_dir
        self.run: Run | None = None
        self.last_screen: Screen | None = None  # latest internal snapshot
        # the screen whose [index] listing the agent saw
        self.shown: Screen | None = None
        self._before: list[
            str
        ] = []  # message texts on screen before the last user action
        self._anchor = ""  # what the user last sent / tapped
        self._turn_offsets: dict[str, int] = {}
        self._fetch_n = 0
        # every message text observed earlier in this conversation
        self._seen: set = set()
        self._seen_seq: dict[
            str, int
        ] = {}  # ... and the order in which they were first seen
        # wall clock of the last user action (for the app log)
        self._turn_wall = time.time()
        self.session_id = ""
        self._executable = ""
        self._sent: set = set()  # normalised texts the user typed in this conversation
        self._last_tap = ""  # label of the last tapped element
        self._alternatives: list[Element] = []
        self._hidden_skipped = 0
        # (type, label, frame) -> hittable (None: the driver did not find it),
        # for hidden-copy detection
        self._hit_cache: dict[tuple, bool | None] = {}
        # the running driver is older than the "hittable" command
        self._no_hittable = False
        self._before_user: list[
            str
        ] = []  # the user's own bubbles on screen before the last action
        # the screen before the last action (to see how far it scrolled)
        self._before_scr: Screen | None = None
        self._before_user_els: list[Element] = []
        self._own: list[
            str
        ] = []  # what the user's last action shows on their side (sent/tapped/selected)
        self._dialog_texts: set = set()  # texts of an in-app dialog that is open
        # right edge of the user's bubbles, learned from a sent message
        self._user_right: float | None = None
        self._learn_from = ""  # the text just sent, until its bubble was seen
        self._option_rows: list[
            list[str]
        ] = []  # option rows of the latest reply (texts)
        self._selected: list[
            str
        ] = []  # texts of rows/controls selected since the latest reply
        # reply-evidence item count at the last user action
        self._ev_base: int | None = None
        self._ev_base_all: int | None = None
        # set when the app was found in the background
        self._left_app: dict[str, Any] | None = None
        # wall clock of the last fresh launch (conversation start)
        self._conv_wall: float | None = None
        self._conv_offsets: dict[str, int] = {}

    # ---------------------------------------------------------------- basics
    @property
    def chat(self) -> dict[str, Any]:
        return self.cfg["chat"]

    def _driver(self):
        client = self.manager.client()
        if not client.alive():
            raise ToolError(
                "UI driver is not running - call start_driver first (it can take 1-3 min the "
                "first time while Xcode builds it)",
                driver=self.manager.status(),
            )
        return client

    def _call(self, cmd: str, **args: Any) -> dict[str, Any]:
        try:
            return self._driver().call(cmd, **args)
        except DriverError as exc:
            raise ToolError(f"driver: {exc}", command=cmd)

    def _pace(self) -> None:
        pace = float(self.cfg.get("pace_ms") or 0) / 1000.0
        if pace > 0:
            self.sleep(pace)

    def _ensure_app(self) -> None:
        """Before reading the screen: if a link/deeplink sent the app to the background, bring it back
        (and remember it for the next result). A snapshot of a suspended app can hang the driver."""
        state = self._call("state").get("app_state")
        if state in ("foreground", "unknown"):
            return
        if state == "notRunning":
            raise ToolError(
                "the app is not running (crashed or closed). That is a finding: screenshot(), "
                "app_log(since='turn'), note it; then open_app(fresh=true) to continue",
                app_state=state,
            )
        self.sleep(1.0)
        self._call("activate")
        after = self._call("state").get("app_state")
        self._left_app = {
            "left_app": True,
            "reactivated": after == "foreground",
            "was": state,
        }
        self._journal(
            {"action": "left_app", "was": state, "reactivated": after == "foreground"}
        )

    def _take_left_app(self, out: dict[str, Any]) -> dict[str, Any]:
        if self._left_app:
            out.update(self._left_app)
            out["left_app_note"] = (
                "the app went to the background (a link/deeplink opened another app) and was "
                "brought back. Links cannot open in the Simulator - if a link was expected, "
                "that is success. Check screen(): the conversation may have been reset."
            )
            self._left_app = None
        return out

    def _snapshot(self, recheck: bool = False) -> Screen:
        self._ensure_app()
        return self._make_screen(self._call("snapshot"), recheck)

    def _make_screen(self, raw: dict[str, Any], recheck: bool = False) -> Screen:
        """A Screen without hidden copies: texts/buttons whose frames overlap another one's (real bubbles never
        overlap) and that the driver reports as not hittable. Never messages, anchors or tap targets."""
        scr = Screen(raw, ignore=self.chat.get("ignore_labels") or [])
        scr.user_right = self._user_right
        cands = scr.overlapping() if not self._no_hittable else []
        if cands:

            def k(e: Element) -> tuple:
                return (
                    e.type,
                    e.label,
                    e.id,
                    round(e.x),
                    round(e.y),
                    round(e.w),
                    round(e.h),
                )

            # a hidden copy stays hidden; a real bubble can turn into one at the same frame (the band above the
            # composer), so "hittable" is asked again after each action and on every screen()
            unknown = [
                e
                for e in cands
                if k(e) not in self._hit_cache
                or (recheck and self._hit_cache[k(e)] is not False)
            ]
            if unknown:
                res = self._hittable(unknown)
                if res:  # the driver answered: a frame it did not find stays unknown (None), asked once
                    for e in unknown:
                        self._hit_cache[k(e)] = res.get(e.index)
                if len(self._hit_cache) > 2000:
                    self._hit_cache.clear()
            scr.hidden = {e.index for e in cands if self._hit_cache.get(k(e)) is False}
        self.last_screen = scr
        return scr

    def _foreground(self) -> Screen:
        scr = self._snapshot()
        if scr.app_state != "foreground":
            self._call("activate")
            scr = self._snapshot()
        if scr.alerts:
            raise ToolError(
                "a system alert covers the app - answer it with tap(alert_button=...)",
                alerts=scr.alerts,
            )
        if scr.app_state != "foreground":
            raise ToolError(
                "app {} is not in the foreground (state {})".format(
                    self.cfg["app"]["bundle_id"], scr.app_state
                )
            )
        return scr

    def _journal(self, entry: dict[str, Any]) -> None:
        if self.run:
            self.run.journal(entry)

    def _evidence(self) -> tuple | None:
        """(all events, bot-reply events) from the configured evidence endpoint, or None."""
        ev = self.cfg.get("reply_evidence") or {}
        tmpl = self.cfg["endpoints"].get(ev.get("endpoint") or "")
        if not tmpl or ("{session_id}" in tmpl and not self.session_id):
            return None
        url = tmpl.replace("{session_id}", urllib.parse.quote(self.session_id, safe=""))
        try:
            doc = json.loads(self.http_get(url))
        except (ValueError, OSError, urllib.error.URLError):
            return None
        items = _select_all(doc, ev.get("list") or "")
        if len(items) == 1 and isinstance(items[0], list):
            items = items[0]
        match = ev.get("match") or {}
        return items, [
            it for it in items if all(_select(it, k) == v for k, v in match.items())
        ]

    def _evidence_texts(self, items: list[Any], key: str = "text") -> list[str]:
        path = (self.cfg.get("reply_evidence") or {}).get(key) or ""
        out: list[str] = []
        for it in items:
            found = _select_all(it, path) if path else []
            flat: list[Any] = []
            for t in found:
                flat.extend(t if isinstance(t, list) else [t])
            for t in flat:
                if isinstance(t, dict):
                    t = t.get("title") or t.get("label") or t.get("text") or ""
                if isinstance(t, (str, int, float)) and str(t).strip():
                    out.append(str(t))
        return out

    def _evidence_options(self, items: list[Any]) -> list[str]:
        """Options (quick replies/buttons) the bot sent: from reply_evidence.options and/or option_regex."""
        ev = self.cfg.get("reply_evidence") or {}
        opts = self._evidence_texts(items, "options")
        rx = ev.get("option_regex") or ""
        if rx:
            for t in self._evidence_texts(items):
                for m in re.finditer(rx, t):
                    opts.append(next((g for g in m.groups() if g), m.group(0)))
        return list(dict.fromkeys(o.strip() for o in opts if o.strip()))

    def _mark_turn(
        self, anchor: str, before: Screen, exclude: list[Element | None]
    ) -> None:
        items = self._evidence()
        self._ev_base_all, self._ev_base = (
            (len(items[0]), len(items[1])) if items is not None else (None, None)
        )
        self._anchor = anchor
        self._own = [anchor] + list(self._selected) if anchor else []
        self._hit_cache = {k: v for k, v in self._hit_cache.items() if v is False}
        self._set_before(before, exclude)
        self._turn_offsets = self._log_sizes()
        self._turn_wall = time.time()
        self._seen_add(self._before)

    def _set_before(self, scr: Screen, exclude: list[Element | None]) -> None:
        """Remember the conversation as it is now - also the bubbles under the navigation bar or a banner."""
        msgs = scr.messages(exclude, covered=True)
        self._before = [m.text for m in msgs]
        # possible ghost copies are no old bubbles of the user
        suspects = {e.index for e in scr.overlapping()}
        self._before_user_els = [
            m for m in msgs if scr.user_side(m) and m.index not in suspects
        ]
        self._before_user = [m.text for m in self._before_user_els]
        self._before_scr = scr

    def _maybe_learn(self, scr: Screen) -> None:
        """The newest bubble with the text just sent is the user's own: remember where it ends. All the user's
        bubbles are right-aligned to the same x, so this separates them from picker rows and wide bot bubbles."""
        text = self._learn_from
        if self._user_right is not None or not text:
            return
        mine = [m for m in scr.messages(covered=True) if norm(m.text) == norm(text)]
        if len(mine) <= len([t for t in self._before if norm(t) == norm(text)]):
            return  # not drawn yet
        self._learn_from = ""
        cands = [m for m in mine if scr.user_side(m)]
        if cands:
            e = max(cands, key=lambda m: m.y)
            self._user_right = round(scr.right_edge(e), 1)
            self._journal({"action": "learned", "user_right_edge": self._user_right})

    def _mine_now(self, scr: Screen) -> list[str]:
        """The user's bubbles from before the action that are still on screen: the chat may have scrolled them
        away, and then a bubble with the same text is the new one."""
        if self._before_scr is None:
            return self._before_user
        dy = scr.shift_from(self._before_scr)
        if dy is None:
            return []  # nothing from before is on screen any more
        top, bottom = 0.0, scr.height or 1e9
        return [
            e.text for e in self._before_user_els if top <= e.center[1] + dy <= bottom
        ]

    def _seen_add(self, texts: list[str]) -> None:
        for t in texts:
            k = norm(t)
            self._seen.add(k)
            self._seen_seq.setdefault(k, len(self._seen_seq))

    def _hidden_copies(
        self, scr: Screen, msgs: list[Element], exclude: list[Element | None]
    ) -> set:
        """Trailing bubbles that repeat an older text below newer ones, with nothing tappable below them: hidden
        copies of old bubbles that chat lists keep in the accessibility tree."""
        floor = min((x.y for x in exclude if x is not None), default=scr.height or 1e9)
        tappable = [
            e.y
            for e in scr.buttons(exclude) + scr.controls(exclude) + scr.actions(exclude)
            if e.center[1] < floor
        ]
        hidden = set()
        for i in range(len(msgs) - 1, 0, -1):
            m = msgs[i]
            seq = self._seen_seq.get(norm(m.text))
            above = [self._seen_seq.get(norm(x.text), 10**9) for x in msgs[:i]]
            if seq is None or seq >= max(above) or any(y > m.y for y in tappable):
                break
            hidden.add(m.index)
        return hidden

    def _in_app_browser(self, scr: Screen | None) -> bool:
        return (
            scr is not None
            and scr.app_state == "foreground"
            and scr.composer(self.chat) is None
            and scr.web_view()
        )

    IN_APP_BROWSER_HINT = (
        "an in-app web page opened over the chat (a link). If the row expects a link, that is "
        "success. Close it: screen(), then tap its Close/Done button, then continue."
    )

    # ---------------------------------------------------------------- setup / status
    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "config": self.cfg["_path"],
            "config_problems": self.cfg["_problems"],
            "app": self.cfg["app"]["bundle_id"],
        }
        try:
            out["simulator"] = {"udid": self.sim.udid()}
        except DriverError as exc:
            out["simulator"] = {"error": str(exc)}
        out["driver"] = self.manager.status()
        if out["driver"]["phase"] == "ready":
            try:
                out["app_state"] = self.manager.client().call("state").get("app_state")
                version = int(self.manager.client().call("ping").get("version") or 1)
                if version < DRIVER_VERSION:
                    out["driver"]["outdated"] = (
                        f"the running driver is v{version}, this tool needs v{DRIVER_VERSION}: "
                        "stop_driver, then start_driver (it rebuilds)"
                    )
            except DriverError as exc:
                out["app_state"] = f"unknown ({exc})"
        out["endpoints"] = {
            name: self._port_open(url) for name, url in self.cfg["endpoints"].items()
        }
        out["logs"] = {
            name: Path(p).expanduser().exists() for name, p in self.cfg["logs"].items()
        }
        out["run"] = str(self.run.dir) if self.run else None
        out["repos"] = {
            role: {"path": p, "exists": Path(p).expanduser().is_dir()}
            for role, p in (self.cfg.get("repos") or {}).items()
        }
        out["plans"] = self._plan_names()
        try:
            out["profile"] = PROFILE.read_text(encoding="utf-8")[:8000]
        except OSError:
            out["profile"] = None
            out["config_problems"] = out["config_problems"] + [
                f"{PROFILE} missing - run install.py"
            ]
        out["ok"] = (
            not out["config_problems"]
            and "error" not in out["simulator"]
            and out["driver"]["phase"] == "ready"
            and all(v == "open" for v in out["endpoints"].values())
        )
        return out

    @staticmethod
    def _port_open(url: str) -> str:
        import socket

        parts = urllib.parse.urlsplit(url.replace("{", "").replace("}", ""))
        try:
            with socket.create_connection(
                (parts.hostname or "127.0.0.1", parts.port or 80), timeout=1.5
            ):
                return "open"
        except OSError:
            return "closed"

    def start_driver(self, wait_s: float = 50) -> dict[str, Any]:
        wait = max(1.0, min(float(wait_s), 110.0))
        try:
            st = self.manager.ensure(wait_s=wait)
        except DriverError as exc:
            # right after the runner app was (re)installed, the first launch can fail: try once more
            if "failed to launch" not in str(exc).lower():
                raise ToolError(str(exc), driver=self.manager.status())
            try:
                st = self.manager.ensure(wait_s=wait)
                st["retried"] = (
                    f"the first launch failed ({str(exc)[:200]}) - started again"
                )
            except DriverError as exc2:
                raise ToolError(str(exc2), driver=self.manager.status())
        if st["phase"] != "ready":
            st["hint"] = "still starting/building - call start_driver again"
        return st

    def stop_driver(self) -> dict[str, Any]:
        return self.manager.stop()

    def open_app(self, fresh: bool = False, navigate: bool = True) -> dict[str, Any]:
        """Activate the app, or relaunch it (fresh). After a fresh launch, tap through app.after_launch
        (e.g. a demo menu) to reach the chat."""
        self._pace()
        if fresh:
            self._conv_wall = time.time()
            self._conv_offsets = self._log_sizes()
            res = self._call(
                "launch", arguments=list(self.cfg["app"].get("launch_arguments") or [])
            )
            self._seen = set()
            self._seen_seq = {}
            self._hit_cache = {}
            self._option_rows, self._selected = [], []
            self._sent = set()
            self._last_tap = ""
            self.session_id = ""
        else:
            res = self._call("activate")
        steps = (
            list(self.cfg["app"].get("after_launch") or [])
            if (fresh and navigate)
            else []
        )
        done = []
        for step in steps:
            label = step if isinstance(step, str) else str(step.get("tap", ""))
            wait_s = 15.0 if isinstance(step, str) else float(step.get("wait_s", 15))
            deadline = self.clock() + wait_s
            while True:
                scr = self._snapshot()
                hits = scr.find(text=label)
                if hits:
                    break
                if self.clock() >= deadline:
                    raise ToolError(
                        f"after_launch: {label!r} did not appear within {wait_s}s",
                        done=done,
                        buttons=[b.label for b in scr.buttons()],
                    )
                self.sleep(0.5)
            self._pace()
            self._call("tap", x=hits[0].center[0], y=hits[0].center[1])
            done.append(label)
        self._journal({"action": "open_app", "fresh": fresh, "navigated": done})
        self._before, self._anchor = [], ""
        return {
            "app_state": res.get("app_state"),
            "fresh": fresh,
            "navigated": done,
            "next": "wait_for_reply to read the welcome message (if any)",
        }

    # ---------------------------------------------------------------- looking
    def screen(self, image: bool = False) -> dict[str, Any]:
        scr = self._snapshot(recheck=True)
        self.shown = scr
        comp = scr.composer(self.chat)
        send = scr.send_button(self.chat, comp)
        msgs = scr.messages([comp])
        hidden = self._hidden_copies(scr, msgs, [comp])
        buttons = scr.buttons([comp, send])
        stale = self._stale_buttons(scr, buttons)
        rows = self._screen_options(
            scr, [m for m in msgs if m.index not in hidden], buttons
        )
        in_rows = {e.index for r in rows for e in r}
        out: dict[str, Any] = {
            "app_state": scr.app_state,
            "keyboard": scr.keyboard,
            "alerts": scr.alerts,
            "elements": scr.listing(),
            # the user's own bubbles are prefixed "you: " - never a reply of the bot
            "messages": [
                ("you: " if scr.user_side(m) else "") + m.text
                for m in msgs
                if m.index not in hidden and m.index not in in_rows
            ],
            "buttons": [
                f"[{b.index}] {b.label or b.id}{'' if b.enabled else ' (disabled)'}"
                for b in buttons
                if b not in stale
            ],
            "composer": comp.describe() if comp else None,
            "send_button": send.describe() if send else None,
            "typing": scr.typing(self.chat),
        }
        if hidden:
            out["hidden_copies"] = [m.describe() for m in msgs if m.index in hidden]
        if rows:
            out["options"] = [f"[{r[0].index}] {_row_text(r)}" for r in rows]
        if stale:
            out["stale_buttons"] = [
                f"[{b.index}] {b.label or b.id} (disabled, belongs to an answered message)"
                for b in stale
            ]
        acts = scr.actions([comp])
        if acts:
            out["actions"] = [f"[{a.index}] {a.text}" for a in acts]
        dlg = self._dialog(scr)
        alerts = scr.app_alerts() + ([dlg] if dlg else [])
        if alerts:
            out["app_alerts"] = alerts
        if dlg:
            out["messages"] = [t for t in out["messages"] if t not in dlg["texts"]]
        if self._in_app_browser(scr):
            out["in_app_browser"] = True
            out["hint"] = self.IN_APP_BROWSER_HINT
        if image:
            try:
                out["_image"] = self._screenshot_file("screen")
            except DriverError as exc:
                out["image_error"] = str(exc)
        return out

    def _screen_options(
        self, scr: Screen, msgs: list[Element], buttons: list[Element]
    ) -> list[list[Element]]:
        """Picker rows below the user's latest bubble: options, not messages. Grouped as in wait_for_reply, or -
        once a row is selected and Continue is enabled - by the rows the latest reply offered."""
        floor = self._latest_user_y(scr)
        after = [m for m in msgs if floor is None or m.y > floor]
        rows = group_options(
            after,
            buttons,
            [e for e in scr.visible() if e.type in ("cell", "other") and e.h <= 160],
            scr.picker_cell(buttons),
        )
        if rows or not self._option_rows:
            return rows
        out: list[list[Element]] = []
        pool = list(after)
        for texts in self._option_rows:
            row: list[Element] = []
            for t in texts:
                hit = next((m for m in pool if norm(m.text) == norm(t)), None)
                if hit is not None:
                    row.append(hit)
                    pool.remove(hit)
            if row:
                out.append(row)
        return out

    def _screenshot_file(self, name: str) -> str:
        udid = self.sim.udid()
        folder = (
            (self.run.dir / "screenshots") if self.run else (self.runs_dir / "_scratch")
        )
        if self.run:
            self.run.counter += 1
            name = f"{self.run.counter:02d}-{_slug(name)}"
        path = self.sim.screenshot(udid, folder / (f"{_slug(name)}.png"))
        self._journal({"action": "screenshot", "path": str(path)})
        return str(path)

    def screenshot(self, name: str = "screen") -> dict[str, Any]:
        try:
            path = self._screenshot_file(name)
        except DriverError as exc:
            raise ToolError(str(exc))
        return {"path": path, "_image": path}

    # ---------------------------------------------------------------- acting
    def tap(
        self,
        element: int | None = None,
        text: str = "",
        id: str = "",
        x: float | None = None,
        y: float | None = None,
        alert_button: str = "",
    ) -> dict[str, Any]:
        if alert_button:
            self._pace()
            self._call("tap_alert", label=alert_button)
            self._journal({"action": "tap_alert", "label": alert_button})
            return {"tapped": f"system alert button {alert_button!r}"}
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
            px, py, what, anchor = float(x), float(y), f"point ({x}, {y})", ""
        else:
            raise ToolError("tap needs element, text, id, x+y or alert_button")
        self._mark_turn(anchor, before, [comp])
        self._pace()
        self._call("tap", x=px, y=py)
        if target is not None and target.text:
            self._last_tap = target.text
        entry = {"action": "tap", "target": what, "x": px, "y": py}
        if target is not None:
            entry.update(
                {
                    "label": target.label,
                    "id": target.id,
                    "value": target.value,
                    "type": target.type,
                }
            )
            if self.run and target.type in ("button", "link"):
                self.run.transcript.append(
                    {"from": "user", "tap": target.label or target.id}
                )
        out: dict[str, Any] = {
            "tapped": what,
            "next": "call wait_for_reply if this should make the bot answer",
        }
        if self._hidden_skipped:
            out["skipped_hidden_copies"] = self._hidden_skipped
        want_echo = (
            target is not None
            and bool(target.text)
            and target.type not in CONTROL_TYPES
        )
        after, echo = self._watch_after_tap(before, want_echo)
        if self._left_app:
            entry["left_app"] = True
            self._journal(entry)
            return self._take_left_app({"tapped": what})
        if self._in_app_browser(after):
            entry["left_app"] = "in_app_browser"
            self._journal(entry)
            return {
                "tapped": what,
                "left_app": "in_app_browser",
                "hint": self.IN_APP_BROWSER_HINT,
            }
        if echo:
            # the reply comes below the user's own bubble, whatever it says
            self._anchor = "\n".join(echo)
            self._own = list(dict.fromkeys(self._own + echo))
            self._last_tap = echo[-1]
            wrong = (
                self._wrong_echo(before, target, echo)
                if want_echo and target is not None
                else []
            )
            if wrong and target is not None:
                sent = " · ".join(echo)
                out["tap_mismatch"] = {"asked": target.text, "sent": sent}
                out["warning"] = (
                    f"the app shows {sent!r} as your message - {wrong[0]!r} is another option on screen, not {target.text!r}: the "
                    "tap went through to another element (e.g. a hidden copy of an old button over "
                    "another row). This step is INVALID - not a bot result. Call screen() and tap the "
                    "right [index]; if it repeats, record the row as blocked with this mismatch."
                )
                entry["tap_mismatch"] = out["tap_mismatch"]
        elif (
            target is not None
            and target.text
            and (target.type not in BUTTON_TYPES or not want_echo)
        ):
            self._remember_selection(target)
        if self._alternatives:
            # The same label is on screen more than once: make sure the tap did something.
            if after is None:
                after = self._snapshot()
            if after.signature() == before.signature():
                out = {
                    "tapped": what,
                    "no_visible_effect": True,
                    "warning": f"nothing changed on screen. {target.text if target else ''!r} is shown "
                    f"{len(self._alternatives) + 1} times - this copy may be an old or "
                    "hidden one. Call screen() and tap(element=n) on the copy that belongs to the "
                    "latest bot message.",
                    "other_copies": [e.describe() for e in self._alternatives[:5]],
                }
                entry["no_visible_effect"] = True
        self._journal(entry)
        return self._take_left_app(out)

    def _watch_after_tap(self, before: Screen, want_echo: bool) -> tuple:
        """After a tap: watch for a link/deeplink switching to another app (it can take seconds), and for the
        user's own echo bubble. Stops as soon as the chat changed (and the echo is there, or ECHO_WAIT_S passed);
        watches up to waits.app_switch_s when nothing changes in the app."""
        t0 = self.clock()
        watch_until = t0 + float(self.cfg["waits"].get("app_switch_s", 6.0))
        echo_until = t0 + ECHO_WAIT_S
        after: Screen | None = None
        echo: list[str] = []
        changed, n = False, 0
        while True:
            now = self.clock()
            if changed and (not want_echo or echo or now >= echo_until):
                break
            if not changed and now >= watch_until:
                break
            self.sleep(0.25)
            if self._call("state").get("app_state") not in ("foreground", "unknown"):
                self.sleep(0.5)
                self._ensure_app()
                return None, []
            n += 1
            if n % 2:
                continue  # a snapshot is slower than a state query: every other poll
            after = self._make_screen(self._call("snapshot"))
            if after.signature() != before.signature():
                changed = True
            if not echo:
                echo = self._echo(before, after)
        return after, echo

    def _echo(self, before: Screen, after: Screen) -> list[str]:
        """The user's new bubble after a tap, all its lines (top to bottom): user-side texts that were not on
        screen before. A submit button's echo may list the selected rows."""
        if after.app_state != "foreground":
            return []
        old = Counter(
            norm(m.text)
            for m in before.messages([before.composer(self.chat)], covered=True)
            if before.user_side(m)
        )
        new = []
        # it may sit under the nav bar
        for m in after.messages([after.composer(self.chat)], covered=True):
            if not after.user_side(m):
                continue
            k = norm(m.text)
            if old[k] > 0:
                old[k] -= 1
                continue
            new.append(m)
        return [m.text for m in new]

    def _remember_selection(self, target: Element) -> None:
        """A tap on a row/control (no echo): its texts may come back in the echo of the submit button."""
        row = next(
            (r for r in self._option_rows if norm(target.text) in {norm(t) for t in r}),
            [target.text],
        )
        self._selected.extend(row)

    def _wrong_echo(
        self, before: Screen, target: Element, echo: list[str]
    ) -> list[str]:
        """Echo lines that are a *different* tappable label on the screen before the tap (and not a row selected
        since the latest reply). An echo that lists the selected cards after "Continue" is fine."""
        if any(self._echo_matches(line, target.text) for line in echo):
            return []
        comp = before.composer(self.chat)
        labels = {
            norm_label(e.text)
            for e in before.buttons([comp])
            + before.controls([comp])
            + before.actions([comp])
            if e.text
        }
        labels |= {norm_label(t) for r in self._option_rows for t in r}
        chosen = key(" ".join(self._selected))
        return [
            line
            for line in echo
            if norm_label(line) in labels and not (key(line) and key(line) in chosen)
        ]

    @staticmethod
    def _echo_matches(echo: str, asked: str) -> bool:
        a, e = norm_label(asked), norm_label(echo).rstrip("…")
        return (
            a == e
            or key(a) == key(e)
            or (len(e) >= 10 and a.startswith(e))
            or (len(a) > 30 and e.startswith(a[:30]))
        )

    def _hittable(self, els: list[Element]) -> dict[int, bool]:
        """Ask the driver which of these elements can really be hit (XCUIElement.isHittable). Hidden copies of
        old buttons stay in the accessibility tree; a tap on them lands on whatever is drawn underneath.
        Empty when the driver is older than this command."""
        res: dict[int, bool] = {}
        groups: dict[tuple, list[Element]] = {}
        for e in els:
            groups.setdefault((e.type, e.label, "" if e.label else e.id), []).append(e)
        for (typ, label, ident), members in groups.items():
            want = [{"x": e.x, "y": e.y, "w": e.w, "h": e.h} for e in members]
            try:
                # frames: the driver looks through every element with this label (a closing line the bot
                # repeats after every flow has dozens of copies) and returns those at these frames
                frames = (
                    self._driver()
                    .call("hittable", type=typ, label=label, id=ident, frames=want)
                    .get("elements")
                    or []
                )
            except DriverError as exc:
                if "unknown command" in str(exc):
                    self._no_hittable = True
                return {}
            except ToolError:
                return {}
            for e in members:
                f = next(
                    (
                        f
                        for f in frames
                        if all(
                            abs(float(f.get(k, -99)) - v) <= 2
                            for k, v in (("x", e.x), ("y", e.y), ("w", e.w), ("h", e.h))
                        )
                    ),
                    None,
                )
                if f is not None:
                    res[e.index] = bool(f.get("hittable", True))
        return res

    def _latest_user_y(self, scr: Screen) -> float | None:
        latest = [norm(t) for t in self._sent] + (
            [norm(self._last_tap)] if self._last_tap else []
        )
        mine = [
            m
            for m in scr.messages(covered=True)
            if norm(m.text) in latest and scr.user_side(m)
        ]
        return max((m.y for m in mine), default=None)

    def _ambiguous(self, scr: Screen, hits: list[Element]) -> list[str]:
        """Several real items with the same label in the latest reply (two "DEBIT MASTERCARD" rows with different
        numbers): list them with their detail instead of guessing. A button and its caption count once."""
        floor = self._latest_user_y(scr)
        # possible hidden copies don't make a label ambiguous
        suspect = {e.index for e in scr.overlapping()}
        fresh = [
            h for h in hits if (floor is None or h.y > floor) and h.index not in suspect
        ]
        kind = [h for h in fresh if h.type in BUTTON_TYPES] or fresh
        reps: list[Element] = []
        for h in kind:
            if not any(r.overlap(h) > 0 for r in reps):
                reps.append(h)
        if len(reps) < 2:
            return []
        reps.sort(key=lambda e: (round(e.y), e.x))
        details = [scr.neighbour(r) for r in reps]
        if len({norm(d) for d in details}) < 2:
            return []
        return [
            f"[{r.index}] {r.text} · {d}" for r, d in zip(reps, details, strict=True)
        ]

    def _rank_fresh(self, scr: Screen, hits: list[Element]) -> list[Element]:
        """Several copies of a label (old menus keep reporting positions after scrolling away): prefer buttons,
        then copies below the user's latest message (they belong to the newest bot reply), then the lowest."""
        latest = [norm(t) for t in self._sent] + (
            [norm(self._last_tap)] if self._last_tap else []
        )
        mine = [m for m in scr.messages(covered=True) if norm(m.text) in latest]
        floor = max((m.y for m in mine), default=None)
        return sorted(
            hits,
            key=lambda e: (
                e.type not in BUTTON_TYPES,
                floor is not None and e.y <= floor,
                -e.y,
            ),
        )

    def _target(
        self, before: Screen, element: int | None, text: str, ident: str
    ) -> Element | None:
        """Resolve element [index] (from the listing the agent saw), visible text or accessibility id."""
        self._alternatives = []
        self._hidden_skipped = 0
        target: Element | None = None
        if element is not None:
            if self.shown is None:
                raise ToolError("no screen listing yet - call screen() first")
            old = next((e for e in self._listed() if e.index == int(element)), None)
            if old is None:
                raise ToolError(f"element [{element}] not in the last screen listing")
            target = before.locate(old)
            if target is None and any(
                e.index in before.hidden and e.same_as(old) for e in before.elements
            ):
                raise ToolError(
                    f"element [{element}] {old.text!r} is a hidden copy (not hittable) - a tap would land on whatever is "
                    "drawn there. Tap a visible copy instead.",
                    visible_copies=[e.describe() for e in before.find(text=old.text)],
                )
            if target is None:
                raise ToolError(
                    f"element [{element}] {old.text or old.type!r} is no longer on screen - call screen() again"
                )
            copies = before.find(text=target.text) if target.text else []
            if len(copies) > 1:
                hit = self._hittable(copies)
                if hit.get(target.index) is False:
                    raise ToolError(
                        f"element [{element}] {target.text!r} is a hidden copy (not hittable) - a tap would land on whatever "
                        "is drawn there. Tap a visible copy instead.",
                        hittable_copies=[
                            e.describe() for e in copies if hit.get(e.index)
                        ],
                    )
        elif text or ident:
            detail = ""
            # "DEBIT MASTERCARD · 4321": a row by its detail
            if " · " in text and not before.find(text=text):
                text, detail = [part.strip() for part in text.split(" · ", 1)]
            hits = before.find(text=text, ident=ident)
            self._hidden_skipped = sum(
                1
                for e in before.elements
                if e.index in before.hidden
                and text
                and norm_label(e.text) == norm_label(text)
            )
            if detail:
                hits = [
                    h
                    for h in hits
                    if key(detail) in key(before.neighbour(h))
                    or key(detail) in key(h.text)
                ]
            if not hits:
                comp = before.composer(self.chat)
                raise ToolError(
                    "nothing on screen matches %r" % (text or ident),
                    buttons=[b.label for b in before.buttons([comp])],
                )
            hits = self._rank_fresh(before, hits)
            if len(hits) > 1:
                hit = self._hittable(hits)
                visible = [e for e in hits if hit.get(e.index, True)]
                if visible:
                    self._hidden_skipped += len(hits) - len(visible)
                    hits = visible
            if len(hits) > 1 and not ident:
                amb = self._ambiguous(before, hits)
                if amb:
                    raise ToolError(
                        "{!r} matches several different items - nothing was tapped. Tap by [index], or by "
                        'the label and its detail, e.g. tap(text="{}")'.format(
                            text, amb[0].split("] ", 1)[1]
                        ),
                        ambiguous=amb,
                    )
            target = hits[0]
            self._alternatives = hits[1:]
        if target is not None and not before.on_screen(target):
            raise ToolError(
                "element is off screen - scroll first", element=target.describe()
            )
        return target

    def swipe(
        self,
        direction: str,
        element: int | None = None,
        text: str = "",
        id: str = "",
        x: float | None = None,
        y: float | None = None,
        distance: float = 0.6,
        speed: str = "normal",
    ) -> dict[str, Any]:
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
            what = f"point ({x}, {y})"
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
        appeared = [
            e.text for e in after.visible() if e.text and (e.type, e.text) not in seen
        ]
        gone = sorted(
            {t for (_, t) in seen} - {e.text for e in after.visible() if e.text}
        )
        self._journal(
            {
                "action": "swipe",
                "direction": direction,
                "on": what,
                "from": [x1, y1],
                "to": [x2, y2],
                "speed": speed,
            }
        )
        return {
            "swiped": direction,
            "on": what,
            "from": [x1, y1],
            "to": [x2, y2],
            "now_visible": appeared[:40],
            "no_longer_visible": gone[:40],
            "changed": bool(appeared or gone),
            "next": "call screen() to get fresh [index] numbers before tapping",
        }

    def long_press(
        self,
        element: int | None = None,
        text: str = "",
        id: str = "",
        x: float | None = None,
        y: float | None = None,
        duration: float = 1.0,
    ) -> dict[str, Any]:
        before = self._foreground()
        target = self._target(before, element, text, id)
        if target is not None:
            px, py = target.center
            what = target.describe()
        elif x is not None and y is not None:
            px, py, what = float(x), float(y), f"point ({x}, {y})"
        else:
            raise ToolError("long_press needs element, text, id or x+y")
        seconds = max(0.3, min(float(duration), 5.0))
        self._pace()
        self._call("long_press", x=px, y=py, duration=seconds)
        self.sleep(0.4)
        after = self._snapshot()
        seen = {(e.type, e.text) for e in before.visible() if e.text}
        appeared = [
            e.text for e in after.visible() if e.text and (e.type, e.text) not in seen
        ]
        self._journal(
            {"action": "long_press", "on": what, "x": px, "y": py, "duration": seconds}
        )
        return {
            "long_pressed": what,
            "now_visible": appeared[:40],
            "next": "call screen() to see a menu that may have opened",
        }

    def _listed(self) -> list[Element]:
        return self.shown.elements if self.shown else []

    def type_text(self, text: str, element: int | None = None) -> dict[str, Any]:
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

    def _tap_end(self, field: Element) -> None:
        """Tap near the trailing end of a text field so the cursor lands after the existing text."""
        x = field.x + field.w - min(12.0, field.w * 0.1)
        self._call("tap", x=round(x, 1), y=field.center[1])

    def _clear(self, field: Element) -> Element:
        """Empty a text field and verify it. Raises if it stays non-empty."""
        cur = field
        for _ in range(3):
            scr = self._snapshot()
            cur = scr.locate(field) or scr.composer(self.chat) or cur
            if scr.is_empty_input(cur):
                return cur
            self._tap_end(cur)
            self._call("delete", count=len(cur.value) + 5)
        scr = self._snapshot()
        cur = scr.locate(field) or scr.composer(self.chat) or cur
        if not scr.is_empty_input(cur):
            raise ToolError(
                "could not clear the text field - nothing was sent", value=cur.value
            )
        return cur

    FOCUS_WAIT_S = 5.0  # right after a fresh launch the composer can take a few seconds to accept focus

    def _type_focused(self, field: Element, text: str) -> None:
        """Type; if the driver says nothing has keyboard focus (nothing was typed), tap the composer again and
        retry for up to FOCUS_WAIT_S."""
        try:
            self._call("type", text=text)
            return
        except ToolError as exc:
            if "keyboard focus" not in str(exc):
                raise
        deadline = self.clock() + self.FOCUS_WAIT_S
        self._tap_end(field)
        while True:
            self.sleep(0.5)
            try:
                self._call("type", text=text)
                self._journal(
                    {"action": "type_retry", "reason": "no keyboard focus yet"}
                )
                return
            except ToolError as exc:
                if "keyboard focus" not in str(exc) or self.clock() >= deadline:
                    raise ToolError(
                        f"the composer did not take keyboard focus within {self.FOCUS_WAIT_S}s - nothing was typed",
                        driver=str(exc),
                    )

    def _type_into(self, field: Element, text: str) -> Element:
        self._pace()
        self._tap_end(field)
        for attempt in (1, 2):
            cur = self._clear(field)
            self._pace()
            self._type_focused(cur, text)
            scr = self._snapshot()
            cur = scr.locate(field) or scr.composer(self.chat) or cur
            if exact(cur.value) == exact(text):
                return cur
            got = cur.value
            self._clear(cur)
            if attempt == 2:
                raise ToolError(
                    "typed text did not read back correctly - nothing was sent (field cleared)",
                    expected=text,
                    read_back=got,
                )
        raise ToolError("unreachable")

    def send_message(
        self, text: str, allow_button_text: bool = False
    ) -> dict[str, Any]:
        """Type the message, verify it reads back, tap Send exactly once, confirm it left the composer."""
        if not text or "\n" in text:
            raise ToolError("send_message needs one non-empty line of text")
        before = self._foreground()
        comp = before.composer(self.chat)
        if comp is None:
            dlg = self._dialog(before)
            if dlg:
                raise ToolError(
                    "a dialog covers the chat - nothing was sent: {!r}. Answer it first: tap one of {}".format(
                        dlg["label"], dlg["buttons"]
                    ),
                    dialog=dlg,
                )
            if self._in_app_browser(before):
                raise ToolError(
                    "an in-app web page covers the chat - nothing was sent. "
                    + self.IN_APP_BROWSER_HINT,
                    left_app="in_app_browser",
                )
            raise ToolError(
                "no chat composer (text input) visible", screen=before.listing(40)
            )
        t = norm(text)
        if not allow_button_text and t not in self._sent:
            # Typing the label of an on-screen option sends text instead of the option's payload - a different
            # code path. Quick replies are often not exposed as buttons, so any short matching label counts.
            hits = [
                e
                for e in before.visible()
                if e.text
                and len(e.text) <= 60
                and norm(e.text) == t
                and e.index != comp.index
                and not before._inside_any(e, [comp])
            ]
            if hits:
                best = min(hits, key=lambda e: (e.type not in BUTTON_TYPES, -e.y))
                self.shown = before
                raise ToolError(
                    f"{text!r} is shown on screen ({best.describe()}). If it is an option/button, "
                    f"TAP it: tap(element={best.index}) - "
                    "typing it sends text instead of the option's payload. Only if the test explicitly "
                    "requires typing this text, call send_message(text, allow_button_text=true).",
                    element=best.describe(),
                )
        typed = self._type_into(comp, text)
        self._sent.add(t)
        scr = self.last_screen or before
        send = scr.send_button(self.chat, typed)
        if send is None:
            self._call("delete", count=len(typed.value) + 2)
            raise ToolError(
                "Send button not found - nothing was sent (field cleared). Set chat.send_labels or "
                "chat.send_ids in config.json",
                buttons=[b.describe() for b in scr.buttons()],
            )
        self._mark_turn(text, before, [comp])
        self._learn_from = text
        self._pace()
        self._call("tap", x=send.center[0], y=send.center[1])
        self._journal(
            {
                "action": "send",
                "text": text,
                "composer": comp.describe(),
                "send": send.describe(),
            }
        )
        if self.run:
            self.run.transcript.append({"from": "user", "text": text})
        deadline = self.clock() + float(self.cfg["waits"]["send_confirm_s"])
        while True:
            scr = self._snapshot()
            cur = scr.locate(typed) or scr.composer(self.chat)
            mine = [
                m
                for m in scr.messages([cur], covered=True)
                if norm(m.text) == norm(text)
            ]
            bubble = bool(mine)
            self._maybe_learn(scr)
            if (cur is not None and scr.is_empty_input(cur)) or bubble:
                out = {"sent": text, "confirmed": True, "next": "call wait_for_reply"}
                self._auto_session(out)
                return self._take_left_app(out)
            if self.clock() >= deadline:
                return {
                    "sent": text,
                    "confirmed": False,
                    "warning": "Send was tapped once but the text is still in the composer. Do NOT send "
                    "again - look at screen()/screenshot() first.",
                }
            self.sleep(0.4)

    def _observe(self, scr: Screen, ev_texts: list[str]) -> dict[str, Any]:
        """What is new on this screen since the user's last action."""
        if self._learn_from and self._user_right is None:
            self._maybe_learn(scr)
            scr.user_right = self._user_right
        comp = scr.composer(self.chat)
        rx = [
            re.compile(p, re.IGNORECASE)
            for p in self.chat.get("interim_labels") or []
            if p
        ]
        busy = scr.typing_elements(self.chat)
        dlg = self._dialog(scr)
        dlg_texts = {norm(t) for t in (dlg or {}).get("texts", [])}
        found = [
            e
            for e in new_message_elements(
                self._before,
                scr,
                self._anchor,
                [comp],
                self._seen,
                ev_texts,
                self._mine_now(scr),
                self._own,
                newest_is_echo=bool(ev_texts),
            )
            if not any(
                b.index == e.index or b.contains(e) for b in busy
            )  # the typing indicator
            and norm(e.text) not in dlg_texts
        ]
        # under the nav bar/banner: not read yet
        covered = [e for e in found if scr.covered(e)]
        new_el = [e for e in found if not scr.covered(e)]
        real = [e for e in new_el if not any(r.search(e.text) for r in rx)]
        return {
            "comp": comp,
            "new_el": new_el,
            "real": real,
            "covered": covered,
            "interim": [e.text for e in new_el if e not in real],
            "cards": [
                e.text for e in scr.carousel_texts() if norm(e.text) not in self._seen
            ],
            "app_alerts": [
                a for a in scr.app_alerts() if norm(a["label"]) not in self._seen
            ]
            + ([dlg] if dlg else []),
        }

    def _dialog(self, scr: Screen) -> dict[str, Any] | None:
        """An in-app dialog drawn as plain views ("Are you sure you want to end the conversation?"): the composer
        is gone, new texts and buttons are on screen."""
        if (
            scr.app_state != "foreground"
            or scr.composer(self.chat) is not None
            or scr.web_view()
        ):
            if scr.app_state == "foreground" and scr.composer(self.chat) is not None:
                self._dialog_texts = set()  # the chat is back: the dialog is closed
            return None
        texts = [
            m.text
            for m in scr.messages()
            if norm(m.text) not in self._seen or norm(m.text) in self._dialog_texts
        ]
        buttons = scr.buttons()
        if not texts or not buttons:
            return None
        # still the dialog when screen() looks again later
        self._dialog_texts |= {norm(t) for t in texts}
        return {
            "kind": "dialog",
            "label": " ".join(texts)[:300],
            "texts": texts,
            "buttons": [f"[{b.index}] {b.label or b.id}" for b in buttons],
        }

    @staticmethod
    def _ev_shown(ev_texts: list[str], shown: list[str]) -> bool:
        """Every paragraph of the bot's new reply is on screen (the start of each is enough)."""
        hay = _ekey(" ".join(shown))
        paras = _paragraphs(ev_texts)
        return bool(paras) and all(_ekey(p)[:30] in hay for p in paras)

    def wait_for_reply(
        self, timeout_s: float | None = None, quiet_ms: float | None = None
    ) -> dict[str, Any]:
        """Wait until new bot content appeared and the screen stopped changing.

        With reply_evidence working, the bot's endpoint decides: texts the app draws on its own ("On it!")
        never end the wait - it ends when the endpoint has the new reply and the screen shows it (or after
        waits.render_grace_s), or at the timeout (then the texts are returned with local_only: true)."""
        waits = self.cfg["waits"]
        timeout = float(
            timeout_s if timeout_s is not None else waits["reply_timeout_s"]
        )
        quiet = float(quiet_ms if quiet_ms is not None else waits["quiet_ms"]) / 1000.0
        poll = float(waits["poll_ms"]) / 1000.0
        grace = float(waits.get("render_grace_s", 6.0))
        ev_on = self._ev_base is not None
        start = self.clock()
        last_sig, stable_since = None, start
        ev: tuple | None = None
        ev_seen_at: float | None = None
        polls = 0
        while True:
            scr = self._snapshot()
            now = self.clock()
            sig = scr.signature()
            if sig != last_sig:
                last_sig, stable_since = sig, now
            if ev_on and polls % 2 == 0:
                ev = self._evidence()
            polls += 1
            ev_new = ev[1][self._ev_base :] if (ev is not None and ev_on) else []
            ev_texts = self._evidence_texts(ev_new)
            o = self._observe(scr, ev_texts)
            typing = scr.typing(self.chat)
            settled = now - stable_since >= quiet
            on_screen = bool(o["real"] or o["covered"] or o["cards"] or o["app_alerts"])
            if ev_new and ev_seen_at is None:
                ev_seen_at = now  # the bot answered; the app may draw it a moment later
            if ev_on:
                drawn = False
                if ev_new:
                    comp_ = o["comp"]
                    shown = (
                        [e.text for e in o["covered"] + o["real"]]
                        + o["cards"]
                        + [b.text for b in scr.buttons([comp_])]
                        + [a.text for a in scr.actions([comp_])]
                        + [c.text for c in scr.controls([comp_])]
                    )
                    drawn = self._ev_shown(ev_texts, shown)
                    # the reply starts above the top edge: its last part must be there
                    if not drawn and o["real"]:
                        msgs = scr.messages([comp_])
                        paras = _paragraphs(ev_texts)
                        drawn = (
                            bool(msgs)
                            and msgs[0].index == o["real"][0].index
                            and bool(paras)
                            and _ekey(paras[-1])[:30] in _ekey(" ".join(shown))
                        )
                if ev_new and on_screen and settled and not typing and drawn:
                    break
                if (
                    ev_new
                    and settled
                    and ev_seen_at is not None
                    and now - ev_seen_at >= grace
                ):
                    break
            elif on_screen and settled and not typing:
                break
            if scr.alerts or self._in_app_browser(scr) or now - start >= timeout:
                break
            if o["app_alerts"] and settled and not o["real"]:
                break  # a dialog/alert and nothing else: the agent must answer it
            self.sleep(poll)

        # A reply longer than the screen: its first bubbles are above the top edge, or under the navigation bar
        # or a banner (chat lists scroll the user's bubble to the top). Scroll up and read them.
        extra: list[str] = []
        scrolled = 0
        found = True
        if self._anchor and (o["real"] or o["covered"]) and not scr.alerts:
            msgs = scr.messages([o["comp"]])
            if o["covered"] or (
                msgs
                and o["real"]
                and msgs[0].index == o["real"][0].index
                and not anchor_hits(scr, msgs, self._anchor)
            ):
                extra, scrolled, found = self._collect_above(o)
                scr = self._snapshot()
                o = self._observe(scr, ev_texts)
        comp = o["comp"]
        self.shown = scr
        send = scr.send_button(self.chat, comp)
        buttons = scr.buttons([comp, send])
        acts = scr.actions([comp])
        # the question of a picker may be under the bar: it still marks where the rows start
        rows = [
            r
            for r in group_options(
                o["covered"] + o["real"],
                buttons,
                [
                    e
                    for e in scr.visible()
                    if e.type in ("cell", "other") and e.h <= 160
                ],
                scr.picker_cell(buttons),
            )
            if not any(scr.covered(e) for e in r)
        ]
        in_rows = {e.index for row in rows for e in row}
        new = extra + [e.text for e in o["real"] if e.index not in in_rows]
        # not read even after scrolling: say so instead of dropping them silently
        if o["covered"]:
            got = {norm(t) for t in new}
            under = [e.text for e in o["covered"] if norm(e.text) not in got]
        else:
            under = []
        replied = bool(
            o["new_el"] or o["covered"] or o["cards"] or ev_new or o["app_alerts"]
        )
        stale = self._stale_buttons(scr, buttons)
        out: dict[str, Any] = {
            "replied": replied,
            "new_messages": new,
            "buttons": [
                f"[{b.index}] {b.label or b.id}{'' if b.enabled else ' (disabled)'}"
                for b in buttons
                if b not in stale
            ],
            "waited_s": round(self.clock() - start, 1),
            "typing": typing,
        }
        if stale:
            out["stale_buttons"] = [
                f"[{b.index}] {b.label or b.id} (disabled, belongs to an answered message)"
                for b in stale
            ]
        if under:
            out["under_bar"] = under
            out["under_bar_note"] = (
                "these new texts are under the navigation bar/banner and could not be read by "
                "scrolling - check screenshot(); exact-text checks need the evidence"
            )
        if scrolled:
            out["scrolled_up"] = scrolled
            out["scroll_note"] = (
                f"the reply was longer than the screen: scrolled up {scrolled} time(s) to read "
                f"its start{'' if found else ' (the start was not found)'}, then back down"
            )
        if o["interim"]:
            out["interim_messages"] = o["interim"]
        if acts:
            out["actions"] = [f"[{a.index}] {a.text}" for a in acts]
            out["actions_note"] = (
                "tappable action cards (not chat text): tap(element=n) or tap(text=...)"
            )
        if o["app_alerts"]:
            out["app_alerts"] = o["app_alerts"]
        if rows:
            out["options"] = [f"[{r[0].index}] {_row_text(r)}" for r in rows]
            out["options_note"] = (
                "selectable rows without a checkbox: tap a row by its [index]; a disabled button "
                "becoming enabled is the sign that the selection worked"
            )
        controls = scr.controls([comp, send])
        if controls:
            out["controls"] = [c.describe() for c in controls]
        carousel = scr.carousel_texts()
        if carousel:
            out["carousel"] = [e.describe() for e in carousel]
            out["new_carousel_cards"] = o["cards"]
        ev_cfg = self.cfg.get("reply_evidence") or {}
        if ev_cfg.get("endpoint") and not ev_on:
            out["evidence"] = (
                "off - no session id yet (find_session_id)"
                if not self.session_id
                else "off - endpoint not reachable"
            )
        if ev_on:
            out["evidence_new_replies"] = len(ev_new)
            texts = self._evidence_texts(ev_new)
            if texts:
                # full texts - the screen may show only part
                out["evidence_texts"] = [t[:2000] for t in texts]
            if ev is not None and self._ev_base_all is not None and ev_cfg.get("flow"):
                flows = self._evidence_texts(ev[0][self._ev_base_all :], "flow")
                if flows:
                    out["evidence_flows"] = list(dict.fromkeys(flows))
            opts = self._evidence_options(ev_new)
            if opts:
                shown = {norm_label(e.text) for e in scr.visible() if e.text}
                missing = [o_ for o_ in opts if norm_label(o_) not in shown]
                out["evidence_options"] = opts
                if missing:
                    out["evidence_options_missing"] = missing
                    out["note_options"] = (
                        f"the bot sent options that are not on screen: {missing} - not rendered "
                        "(possible app/bot bug) or scrolled away; check screen()"
                    )
            if texts and (o["new_el"] or o["covered"] or o["cards"]):
                gone = _missing(
                    _paragraphs(texts),
                    [m.text for m in scr.messages([comp])]
                    + extra
                    + o["cards"]
                    + [b.label for b in buttons]
                    + [a.text for a in acts],
                )
                if gone:
                    out["evidence_texts_missing"] = [g[:300] for g in gone]
                    out["note_missing"] = (
                        "not on screen: scrolled away or not rendered (possible app bug) - check "
                        "screenshot()"
                    )
            if ev_new and not o["new_el"] and not o["covered"] and not o["cards"]:
                out["note"] = (
                    f"the endpoint shows a new bot reply but nothing new appeared on screen within {grace}s: it "
                    "repeats an earlier message, or it was not rendered - compare with screen()"
                )
            if not ev_new and (o["new_el"] or o["covered"] or o["cards"]):
                out["local_only"] = True
                out["local_only_note"] = (
                    "the app drew these texts, but the bot's endpoint shows no new reply within "
                    f"{round(timeout)}s: a local/interim text, or reply_evidence.match does not fit - this is "
                    "not the bot's answer"
                )
        if not replied:
            out["timed_out"] = True
            out["hint"] = (
                "no new bot message - check screen()/screenshot(), read_log(since='turn') or "
                "app_log(since='turn'). Without reply_evidence configured, a reply identical to an "
                "earlier message is not detected as new."
            )
        if scr.alerts:
            out["alerts"] = scr.alerts
        if self._in_app_browser(scr):
            out["left_app"] = "in_app_browser"
            out["hint"] = self.IN_APP_BROWSER_HINT
        self._take_left_app(out)
        self._journal(dict(out, action="wait_for_reply"))
        if self.run and replied:
            self.run.transcript.append(
                {
                    "from": "bot",
                    "messages": new,
                    "options": out.get("options", []),
                    "buttons": [b.label or b.id for b in buttons],
                }
            )
        # Next wait compares against this screen unless a new action resets it.
        self._set_before(scr, [comp])
        self._seen_add(
            extra
            + [t for t in self._before if norm(t) not in self._dialog_texts]
            + [e.text for e in carousel]
        )
        if replied:
            self._option_rows = [[e.text for e in r] for r in rows]
            self._selected = []
        self._anchor = ""
        if ev is not None:
            self._ev_base_all, self._ev_base = len(ev[0]), len(ev[1])
        return out

    def _stale_buttons(self, scr: Screen, buttons: list[Element]) -> list[Element]:
        """Disabled buttons above the user's latest bubble: e.g. the Continue of a picker that was answered."""
        floor = self._latest_user_y(scr)
        if floor is None:
            return []
        return [b for b in buttons if not b.enabled and b.center[1] < floor]

    def _collect_above(self, o: dict[str, Any]) -> tuple:
        """Scroll up (at most MAX_SCROLL_UP swipes) until the user's message is visible, collect the bubbles
        below it, then scroll back down. Returns (texts above the current screen, swipes, anchor found)."""
        # the covered ones are not in it: they are read here
        bottom = {norm(e.text) for e in o["new_el"]}
        screens: list[list[str]] = []
        found = False
        swipes = 0
        for _ in range(MAX_SCROLL_UP):
            self.scroll("up")
            swipes += 1
            self.sleep(0.6)
            scr = self._snapshot()
            msgs = scr.messages([scr.composer(self.chat)])
            runs = anchor_hits(scr, msgs, self._anchor)
            if runs:
                low = max((r[-1] for r in runs), key=lambda m: m.y)
                used = {m.index for r in runs for m in r}
                screens.append(
                    [m.text for m in msgs if m.y > low.y + 1 and m.index not in used]
                )
                found = True
                break
            screens.append([m.text for m in msgs if norm(m.text) not in self._seen])
        for _ in range(swipes):
            self.scroll("down")
        self.sleep(0.6)
        merged: list[str] = []
        for texts in reversed(screens):  # top-most screen first
            for t in texts:
                if norm(t) not in {norm(x) for x in merged}:
                    merged.append(t)
        return [t for t in merged if norm(t) not in bottom], swipes, found

    def scroll(self, direction: str = "up", amount: float = 0.5) -> dict[str, Any]:
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
    def fetch(
        self,
        endpoint: str,
        vars: dict[str, Any] | None = None,
        path: str = "",
        max_chars: int = 20000,
    ) -> dict[str, Any]:
        tmpl = self.cfg["endpoints"].get(endpoint)
        if not tmpl:
            raise ToolError(
                f"unknown endpoint {endpoint!r}",
                configured=sorted(self.cfg["endpoints"]),
            )
        url = tmpl
        vars = dict(vars or {})
        if "{session_id}" in tmpl and "session_id" not in vars:
            if not self.session_id:
                raise ToolError(
                    "this endpoint needs a session id - call find_session_id(), or ask the user and "
                    "call set_session_id(id)"
                )
            vars["session_id"] = self.session_id
        for name, value in vars.items():
            url = url.replace(f"{{{name}}}", urllib.parse.quote(str(value), safe=""))
        if re.search(r"{\w+}", url):
            raise ToolError(
                "missing vars for {}".format(re.findall(r"{(\w+)}", url)), template=tmpl
            )
        if urllib.parse.urlsplit(url).hostname not in LOCAL_HOSTS:
            raise ToolError("only local endpoints are allowed", url=url)
        try:
            body = self.http_get(url)
        except urllib.error.HTTPError as exc:
            raise ToolError(f"HTTP {exc.code} from {url}")
        except (urllib.error.URLError, OSError) as exc:
            raise ToolError(f"cannot reach {url} ({exc}) - is the service running?")
        out: dict[str, Any] = {"url": url}
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        if self.run:
            self._fetch_n += 1
            saved = self.run.dir / (
                f"fetch-{self._fetch_n:02d}-{_slug(endpoint)}."
                f"{'json' if doc is not None else 'txt'}"
            )
            saved.write_text(body, encoding="utf-8")
            out["saved"] = str(saved)
            self._journal(
                {
                    "action": "fetch",
                    "endpoint": endpoint,
                    "url": url,
                    "saved": str(saved),
                }
            )
        if doc is not None:
            text = json.dumps(_select(doc, path), ensure_ascii=False)
        else:
            text = body
        out["truncated"] = len(text) > max_chars
        out["data"] = text[:max_chars]
        return out

    def _log_sizes(self) -> dict[str, int]:
        sizes = {}
        for name, p in self.cfg["logs"].items():
            try:
                sizes[name] = Path(p).expanduser().stat().st_size
            except OSError:
                sizes[name] = 0
        return sizes

    def read_log(
        self, name: str = "", since: str = "turn", grep: str = "", max_lines: int = 200
    ) -> dict[str, Any]:
        logs = self.cfg["logs"]
        if not logs:
            raise ToolError("no logs configured in config.json")
        name = name or next(iter(logs))
        if name not in logs:
            raise ToolError(f"unknown log {name!r}", configured=sorted(logs))
        path = Path(logs[name]).expanduser()
        if not path.exists():
            raise ToolError(
                f"log file {path} does not exist - is the service writing to it?"
            )
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
        errs = [
            ln
            for ln in lines
            if any(p in ln for p in self.cfg.get("error_patterns") or [])
        ]
        total = len(lines)
        lines = lines[-int(max_lines) :]
        return {
            "log": name,
            "since": since,
            "lines": lines,
            "total_lines": total,
            "error_lines": errs[-30:],
            "error_count": len(errs),
        }

    # ---------------------------------------------------------------- app log / session id
    def _app_exec(self, udid: str) -> str:
        if not self._executable:
            bundle = self.cfg["app"]["bundle_id"]
            res = self.sim.runner(["xcrun", "simctl", "appinfo", udid, bundle])
            m = re.search(
                r'CFBundleExecutable\s*=\s*"?([^";\n]+?)"?;', res.stdout or ""
            )
            if not m:
                raise ToolError(
                    "cannot find the app's executable name (simctl appinfo) - set app_log.predicate "
                    "in config.json",
                    bundle_id=bundle,
                )
            self._executable = m.group(1).strip()
        return self._executable

    def _app_log_lines(self, start_wall: float) -> list[str]:
        try:
            udid = self.sim.udid()
        except DriverError as exc:
            raise ToolError(str(exc))
        predicate = (self.cfg.get("app_log") or {}).get(
            "predicate"
        ) or f'process == "{self._app_exec(udid)}"'
        start = datetime.fromtimestamp(start_wall).strftime("%Y-%m-%d %H:%M:%S")
        res = self.sim.runner(
            [
                "xcrun",
                "simctl",
                "spawn",
                udid,
                "log",
                "show",
                "--style",
                "compact",
                "--info",
                "--debug",
                "--start",
                start,
                "--predicate",
                predicate,
            ]
        )
        if res.returncode != 0:
            raise ToolError(
                f"log show failed: {(res.stderr or res.stdout).strip()[:300]}"
            )
        return [
            ln
            for ln in (res.stdout or "").splitlines()
            if ln.strip() and not ln.startswith(("Timestamp", "Filtering the log data"))
        ]

    def app_log(
        self,
        since: str = "turn",
        grep: str = "",
        max_lines: int = 200,
        minutes: float = 5,
    ) -> dict[str, Any]:
        """The app's own log from the Simulator (unified log) - no setup needed."""
        if since == "turn":
            start = self._turn_wall - 2
        elif since == "run":
            start = (self.run.wall_start if self.run else time.time() - 600) - 2
        else:
            start = time.time() - float(minutes) * 60
        lines = self._app_log_lines(start)
        if grep:
            rx = re.compile(grep, re.IGNORECASE)
            lines = [ln for ln in lines if rx.search(ln)]
        errs = [
            ln
            for ln in lines
            if any(p in ln for p in self.cfg.get("error_patterns") or [])
        ]
        total = len(lines)
        return {
            "since": since,
            "lines": [ln[:600] for ln in lines[-int(max_lines) :]],
            "total_lines": total,
            "error_lines": errs[-30:],
            "error_count": len(errs),
        }

    def _auto_session(self, out: dict[str, Any]) -> None:
        """reply_evidence needs the session id, which appears in the logs with the first message of a
        conversation: look for it right after sending, so the first turn has evidence too."""
        ev = self.cfg.get("reply_evidence") or {}
        tmpl = self.cfg["endpoints"].get(ev.get("endpoint") or "", "")
        if self.session_id or "{session_id}" not in tmpl:
            return
        deadline = self.clock() + float(self.cfg["waits"].get("session_find_s", 4.0))
        while True:
            try:
                res = self.find_session_id()
            except ToolError:
                return
            if self.session_id:
                out["session_id"] = self.session_id
                items = self._evidence()
                if items is not None:
                    self._ev_base_all, self._ev_base = len(items[0]), len(items[1])
                return
            if self.clock() >= deadline:
                out["session_id"] = None
                out["session_hint"] = res.get("hint", "")
                return
            self.sleep(0.8)

    def find_session_id(self) -> dict[str, Any]:
        """Search the app log and the configured logs for session/conversation ids (newest first)."""
        patterns = [
            re.compile(p) for p in (self.cfg.get("session") or {}).get("regex") or []
        ]
        if not patterns:
            raise ToolError("no session.regex configured in config.json")
        sources: list[tuple] = []
        wall = self._conv_wall
        conv = wall is not None
        try:
            if wall is not None:
                start = wall - 2  # only this conversation (since the last fresh launch)
            else:
                start = (self.run.wall_start if self.run else time.time() - 900) - 5
            sources.append(("app_log", self._app_log_lines(start)))
        except ToolError as exc:
            sources.append(("app_log", []))
            app_err = str(exc)
        else:
            app_err = ""
        for name in self.cfg["logs"]:
            try:
                if conv:
                    saved, self._turn_offsets = (
                        self._turn_offsets,
                        dict(self._conv_offsets),
                    )
                    try:
                        lines = self.read_log(name, since="turn", max_lines=5000)[
                            "lines"
                        ]
                    finally:
                        self._turn_offsets = saved
                else:
                    lines = self.read_log(
                        name, since="run" if self.run else "tail", max_lines=5000
                    )["lines"]
                sources.append((name, lines))
            except ToolError:
                pass
        found: dict[str, dict[str, Any]] = {}
        for source, lines in sources:
            for line in reversed(lines):
                for rx in patterns:
                    for m in rx.finditer(line):
                        value = next((g for g in m.groups() if g), m.group(0))
                        if value not in found:
                            found[value] = {
                                "id": value,
                                "source": source,
                                "line": line[:300],
                            }
        out: dict[str, Any] = {
            "candidates": list(found.values())[:10],
            "current": self.session_id or None,
        }
        if app_err:
            out["app_log_error"] = app_err
        newest = next(iter(found), None)
        if newest and (len(found) == 1 or conv):
            if self.session_id != newest:
                # Within one conversation the newest id is the conversation's own one.
                self.session_id = newest
                out["current"] = newest
                out["note"] = (
                    "newest id since the last fresh launch - set as the current session id"
                    if conv
                    else "only one candidate - set as the current session id"
                )
                out["auto_picked"] = True
            else:
                out["note"] = (
                    "the current session id is the newest one in the logs - nothing to do"
                )
        elif not found:
            out["hint"] = (
                "no id found - ask the user how to find it (profile.md), then set_session_id(id). "
                "Adjust session.regex in config.json if the logs show it in another format."
            )
        else:
            out["hint"] = (
                "several candidates - pick the one from this conversation and call set_session_id(id)"
            )
        self._journal({"action": "find_session_id", "candidates": list(found)[:10]})
        return out

    def set_session_id(self, id: str) -> dict[str, Any]:
        if not re.match(r"^[\w.:@-]{3,200}$", id or ""):
            raise ToolError("that does not look like a session id")
        self.session_id = id
        self._journal({"action": "set_session_id", "id": id})
        return {
            "session_id": id,
            "next": "fetch(endpoint) now fills {session_id} automatically",
        }

    # ---------------------------------------------------------------- plans
    @staticmethod
    def _plan_names() -> list[str]:
        if not PLANS.is_dir():
            return []
        return sorted(
            str(p.relative_to(PLANS))
            for p in PLANS.rglob("*.md")
            if p.is_file()
            and not p.name.endswith(".result.md")
            and p.name != "README.md"
        )

    def _plan_file(self, name: str) -> Path:
        cand = Path(name).expanduser()
        if not cand.is_absolute():
            cand = PLANS / name
            if not cand.exists() and not name.endswith(".md"):
                cand = PLANS / (name + ".md")
        cand = cand.resolve()
        if not cand.is_file():
            raise ToolError(f"no plan {name!r}", plans=self._plan_names())
        return cand

    def plans(self, name: str = "") -> dict[str, Any]:
        """List test plans, or return one plan with its parsed rows."""
        if not name:
            return {"folder": str(PLANS), "plans": self._plan_names()}
        path = self._plan_file(name)
        text = path.read_text(encoding="utf-8")
        plan = parse_plan(text)
        blocked = [
            {"row": r["row"], "why": r["result"].split(":", 1)[1].strip()}
            for r in plan["rows"]
            if r["result"].lower().startswith("blocked:")
        ]
        out = {
            "path": str(path),
            "title": plan["title"],
            "conversations": plan["sections"],
            "rows": public_rows(plan),
            "content": text,
            "summary": {
                "rows": len(plan["rows"]),
                "runnable": len(plan["rows"]) - len(blocked),
                "blocked": blocked,
            },
        }
        if not plan["rows"]:
            out["warning"] = (
                "no table with the columns Flow | User prompt | Expected | Result found"
            )
        warnings = lint_plan(plan)
        if warnings:
            out["warnings"] = warnings
        return out

    def start_run(self, name: str = "", plan: str = "") -> dict[str, Any]:
        if self.run:
            self.end_run("Superseded by a new run before it was ended.", "INCONCLUSIVE")
        path = self._plan_file(plan) if plan else None
        text = path.read_text(encoding="utf-8") if path else ""
        parsed = parse_plan(text) if path else {"rows": [], "sections": [], "title": ""}
        if path and not parsed["rows"]:
            raise ToolError(
                "plan has no table with the columns Flow | User prompt | Expected | Result",
                path=str(path),
            )
        name = name or (path.stem if path else "run")
        self.run = Run(name, self.runs_dir, self.clock())
        self.run.plan_path, self.run.plan_text, self.run.rows = (
            path,
            text,
            parsed["rows"],
        )
        for r in parsed["rows"]:
            # the planner marked it: needs a precondition
            if r["result"].lower().startswith("blocked:"):
                note = r["result"].split(":", 1)[1].strip()
                self.run.results[r["row"]] = {
                    "status": "blocked",
                    "note": note,
                    "cell": r["result"],
                    "prefilled": True,
                }
        self.run.log_offsets = self._log_sizes()
        self._turn_offsets = dict(self.run.log_offsets)
        self.run.journal(
            {"action": "start_run", "name": name, "plan": str(path) if path else None}
        )
        out: dict[str, Any] = {"run_dir": str(self.run.dir)}
        if path:
            pre = sorted(self.run.results)
            if pre:
                out["prefilled_blocked_rows"] = pre
            out.update(
                {
                    "plan": str(path),
                    "conversations": parsed["sections"],
                    "rows": public_rows(parsed),
                    "next": "for each conversation: open_app(fresh=true); for each row: act, wait_for_reply, "
                    "record_result(row, status, note)",
                }
            )
        return out

    def record_result(self, row: int, status: str, note: str = "") -> dict[str, Any]:
        """Result of one plan row: success, fail (note = what happened instead) or blocked (note = why)."""
        run = self._need_run()
        if not run.rows:
            raise ToolError(
                "this run has no plan - use check() instead, or start_run(plan=...)"
            )
        numbers = [r["row"] for r in run.rows]
        if int(row) not in numbers:
            raise ToolError(f"row {row} is not in the plan (rows 1-{len(numbers)})")
        try:
            cell = format_result(status, note)
        except ValueError as exc:
            raise ToolError(str(exc))
        status = status.lower().strip()
        r = run.rows[int(row) - 1]
        run.results[int(row)] = {"status": status, "note": note, "cell": cell}
        if status != "blocked":
            run.checks.append(
                {
                    "name": "row {}: {}".format(row, r["prompt"][:80]),
                    "passed": status == "success",
                    "evidence": note or "success",
                }
            )
        run.journal(
            {"action": "record_result", "row": int(row), "status": status, "note": note}
        )
        left = [n for n in numbers if n not in run.results]
        return {
            "row": int(row),
            "result": cell,
            "rows_left": left[:20],
            "rows_left_count": len(left),
        }

    def _plan_verdict(self, run: Run) -> dict[str, Any]:
        statuses = [
            run.results.get(r["row"], {}).get("status", "blocked") for r in run.rows
        ]
        counts = {s: statuses.count(s) for s in STATUSES}
        not_run = [r["row"] for r in run.rows if r["row"] not in run.results]
        if counts["fail"]:
            verdict = "FAIL"
        elif not_run:
            verdict = "INCOMPLETE"  # the run stopped before every row was tried
        elif counts["blocked"]:
            verdict = "BLOCKED"
        else:
            verdict = "PASS"
        counts["blocked"] -= len(not_run)
        counts["not_run"] = len(not_run)
        return {"verdict": verdict, "counts": counts, "not_run": not_run}

    def _need_run(self) -> Run:
        if not self.run:
            raise ToolError("no active run - call start_run(name) first")
        return self.run

    def check(self, name: str, passed: bool, evidence: str) -> dict[str, Any]:
        run = self._need_run()
        if not evidence.strip():
            raise ToolError(
                "a check needs evidence (quoted bot text, payload, log line, ...)"
            )
        item = {"name": name, "passed": bool(passed), "evidence": evidence}
        run.checks.append(item)
        run.journal(dict(item, action="check"))
        return {"recorded": item, "checks_so_far": len(run.checks)}

    def note(self, text: str, kind: str = "observation") -> dict[str, Any]:
        run = self._need_run()
        item = {"kind": kind, "text": text}
        run.notes.append(item)
        run.journal(dict(item, action="note"))
        return {"recorded": item}

    def end_run(self, summary: str, verdict: str = "") -> dict[str, Any]:
        run = self._need_run()
        plan_out: dict[str, Any] = {}
        if run.rows:
            pv = self._plan_verdict(run)
            verdict = pv["verdict"]
            cells = {n: v["cell"] for n, v in run.results.items()}
            for n in pv["not_run"]:
                cells[n] = "blocked: not run"
            filled = fill_results(run.plan_text, cells)
            (run.dir / "results.md").write_text(filled, encoding="utf-8")
            plan_out = {
                "counts": pv["counts"],
                "not_run": pv["not_run"],
                "results": str(run.dir / "results.md"),
            }
            if run.plan_path and PLANS.resolve() in run.plan_path.parents:
                beside = run.plan_path.with_name(run.plan_path.stem + ".result.md")
                beside.write_text(filled, encoding="utf-8")
                plan_out["results_beside_plan"] = str(beside)
        verdict = (verdict or "").upper().strip()
        if verdict not in VERDICTS:
            raise ToolError("verdict must be one of {}".format(", ".join(VERDICTS)))
        failed = [c for c in run.checks if not c["passed"]]
        final, reason = verdict, ""
        if verdict == "PASS" and failed:
            final, reason = "FAIL", f"{len(failed)} check(s) failed"
        elif verdict == "PASS" and not run.checks:
            final, reason = "INCONCLUSIVE", "PASS needs at least one recorded check"
        result = {
            "name": run.name,
            "verdict": final,
            "requested_verdict": verdict,
            "verdict_reason": reason,
            "summary": summary,
            "checks": run.checks,
            "notes": run.notes,
            "duration_s": round(self.clock() - run.started, 1),
        }
        result.update(plan_out)
        (run.dir / "run.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run.dir / "transcript.json").write_text(
            json.dumps(run.transcript, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for name in self.cfg["logs"]:
            try:
                part = self.read_log(name, since="run", max_lines=100000)
                (run.dir / (f"log-{_slug(name)}.txt")).write_text(
                    "\n".join(part["lines"]) + "\n", encoding="utf-8"
                )
            except ToolError:
                pass
        run.journal({"action": "end_run", "verdict": final})
        self.run = None
        out = {
            "run_dir": str(run.dir),
            "verdict": final,
            "verdict_reason": reason,
            "next": "write report.md into run_dir with write_file",
        }
        out.update(plan_out)
        return out

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        target = (
            (HOME / path).resolve()
            if not Path(path).is_absolute()
            else Path(path).resolve()
        )
        allowed = [(HOME / d).resolve() for d in WRITABLE] + [self.runs_dir.resolve()]
        if not any(target == a or a in target.parents for a in allowed):
            raise ToolError(
                "you may only write under {}".format(", ".join(str(a) for a in allowed))
            )
        if target.suffix.lower() not in WRITABLE_EXT:
            raise ToolError("allowed file types: {}".format(", ".join(WRITABLE_EXT)))
        if len(content) > 1_000_000:
            raise ToolError("file too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"written": str(target), "bytes": len(content.encode("utf-8"))}
