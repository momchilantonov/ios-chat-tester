"""A dependency-free MCP server over stdio (JSON-RPC 2.0, one message per line)."""
from __future__ import annotations

import base64
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, IO, List, Optional

from .tester import Tester, ToolError

SERVER_NAME = "simchat"
SERVER_VERSION = "1.0.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _s(kind: str, desc: str, **extra: Any) -> Dict[str, Any]:
    out = {"type": kind, "description": desc}
    out.update(extra)
    return out


def _tool(name: str, desc: str, props: Optional[Dict[str, Any]] = None, required: List[str] = ()) -> Dict[str, Any]:
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props or {}, "required": list(required)}}


TOOLS: List[Dict[str, Any]] = [
    _tool("status", "Check config, booted simulator, UI driver, app state, local service ports and log files; "
          "also returns the project profile (read it!), the repos you may read and the test plans. "
          "Call first in every session."),
    _tool("start_driver", "Start the UI driver (XCTest) on the booted simulator and bring Simulator.app to the "
          "front. First start builds it (1-3 min): if it returns phase 'starting', call it again.",
          {"wait_s": _s("number", "Seconds to wait for readiness (max 110).", default=50)}),
    _tool("stop_driver", "Stop the UI driver this tool started. Not needed between runs."),
    _tool("open_app", "Bring the app under test to the foreground. fresh=true terminates and relaunches it "
          "(clean conversation) and then taps through app.after_launch from config (e.g. a demo menu entry) to "
          "reach the chat.", {"fresh": _s("boolean", "Relaunch the app.", default=False),
                              "navigate": _s("boolean", "Run app.after_launch after a fresh launch.", default=True)}),
    _tool("screen", "Read the current screen: chat messages, buttons with [index], composer, Send button, "
          "alerts and all labelled elements. image=true also returns a screenshot.",
          {"image": _s("boolean", "Attach a screenshot.", default=False)}),
    _tool("send_message", "Send one chat message as the user: types it into the composer, verifies the text "
          "reads back exactly, taps Send exactly once and confirms it left the composer. Never call it twice "
          "for the same message. Refuses to type the label of an option shown on screen - tap it instead.",
          {"text": _s("string", "One line of text, any language."),
           "allow_button_text": _s("boolean", "Type it even though an option with this label is on screen "
                                   "(only when the test explicitly requires typing it).", default=False)}, ["text"]),
    _tool("wait_for_reply", "Wait until the bot's new messages have appeared and the screen is quiet. Returns "
          "new_messages, the visible buttons with [index] and rich controls (list rows, checkboxes, switches; "
          "SELECTED marks the selected ones), options, actions (tappable cards) and the bot's evidence. "
          "local_only: true = text the app drew without a bot reply - not the answer. Call after every "
          "send_message or tap that should make the bot answer.",
          {"timeout_s": _s("number", "Max seconds (default from config)."),
           "quiet_ms": _s("number", "How long the screen must be unchanged (default from config).")}),
    _tool("tap", "Tap something: a button/element by [index] from the last screen/wait_for_reply, by visible "
          "text, by accessibility id, by x/y points, or a system alert button. tap_mismatch in the result = "
          "the app sent another label than asked: the step is invalid, not a bot result.",
          {"element": _s("integer", "Index from the last listing."), "text": _s("string", "Visible text/label."),
           "id": _s("string", "Accessibility identifier."), "x": _s("number", "X in points."),
           "y": _s("number", "Y in points."), "alert_button": _s("string", "Label of a system alert button.")}),
    _tool("type_text", "Type into a text field (default: the composer) and read it back WITHOUT sending. For "
          "forms; use send_message for chat messages.",
          {"text": _s("string", "Text to type."), "element": _s("integer", "Field [index] (optional).")},
          ["text"]),
    _tool("swipe", "Swipe with one finger. direction is where the FINGER moves: on a carousel 'left' shows the "
          "next item, 'right' the previous one. Target an element (e.g. the carousel/collectionView [index] from "
          "screen()), visible text, an accessibility id or a point; default is the screen centre. Returns what "
          "appeared/disappeared. Indexes change afterwards - call screen() before tapping.",
          {"direction": _s("string", "left | right | up | down", enum=["left", "right", "up", "down"]),
           "element": _s("integer", "Index from the last listing."), "text": _s("string", "Visible text."),
           "id": _s("string", "Accessibility identifier."), "x": _s("number", "X in points."),
           "y": _s("number", "Y in points."),
           "distance": _s("number", "Fraction of the element (or screen) to travel, 0.1-0.95.", default=0.6),
           "speed": _s("string", "slow | normal | fast (fast flicks, slow drags precisely)",
                       enum=["slow", "normal", "fast"], default="normal")}, ["direction"]),
    _tool("long_press", "Press and hold on an element, text, id or point (e.g. to open a context menu).",
          {"element": _s("integer", "Index from the last listing."), "text": _s("string", "Visible text."),
           "id": _s("string", "Accessibility identifier."), "x": _s("number", "X in points."),
           "y": _s("number", "Y in points."), "duration": _s("number", "Seconds 0.3-5.", default=1.0)}),
    _tool("scroll", "Scroll the conversation/screen vertically. 'up' shows earlier content, 'down' later content "
          "(for sideways or element swipes use swipe).",
          {"direction": _s("string", "up or down", enum=["up", "down"]),
           "amount": _s("number", "Fraction of the screen 0.1-0.8.", default=0.5)}),
    _tool("screenshot", "Save a screenshot into the run folder and show it.",
          {"name": _s("string", "Short name, e.g. 'after-confirm'.")}),
    _tool("fetch", "GET a configured local endpoint (e.g. the bot's conversation/event API) for evidence. "
          "The response is saved in the run folder.",
          {"endpoint": _s("string", "Endpoint name from config.json."),
           "vars": _s("object", "Values for {placeholders} in the URL. {session_id} is filled automatically "
                      "after find_session_id/set_session_id."),
           "path": _s("string", "Optional selector, e.g. 'events[-1].text' or 'events.*.event'."),
           "max_chars": _s("integer", "Truncate the returned text.", default=20000)}, ["endpoint"]),
    _tool("read_log", "Read a configured log file: since='turn' (since your last send/tap), 'run' or 'tail'. "
          "Lines matching error patterns are listed separately.",
          {"name": _s("string", "Log name from config.json (default: first)."),
           "since": _s("string", "turn | run | tail", enum=["turn", "run", "tail"], default="turn"),
           "grep": _s("string", "Case-insensitive regex filter."),
           "max_lines": _s("integer", "Return at most this many (last) lines.", default=200)}),
    _tool("app_log", "Read the app's own log from the Simulator (no setup needed): since='turn' (since your last "
          "send/tap), 'run' or 'minutes'. Use grep to filter (regex).",
          {"since": _s("string", "turn | run | minutes", enum=["turn", "run", "minutes"], default="turn"),
           "grep": _s("string", "Case-insensitive regex filter."),
           "minutes": _s("number", "For since='minutes'.", default=5),
           "max_lines": _s("integer", "Return at most this many (last) lines.", default=200)}),
    _tool("find_session_id", "Search the app log and the configured logs for the conversation/session id "
          "(patterns: session.regex in config). Sets it when exactly one candidate is found."),
    _tool("set_session_id", "Set the conversation/session id to use for fetch() {session_id}.",
          {"id": _s("string", "The session id.")}, ["id"]),
    _tool("plans", "List test plans (Markdown tables Flow | User prompt | Expected | Result), or return one plan "
          "with its numbered rows and conversations.",
          {"name": _s("string", "Plan file name from the list, or a path to a plan file (optional).")}),
    _tool("start_run", "Start a test run: creates runs/<time>_<name>/ and journals every action. With plan=..., "
          "returns the numbered rows to execute; record each with record_result.",
          {"name": _s("string", "Run name (default: the plan's file name)."),
           "plan": _s("string", "Plan name or path (optional).")}),
    _tool("record_result", "Record the result of one plan row: success, fail (note = what happened instead, with "
          "the quoted bot text) or blocked (note = why it could not be executed).",
          {"row": _s("integer", "Row number from start_run/plans."),
           "status": _s("string", "success | fail | blocked", enum=["success", "fail", "blocked"]),
           "note": _s("string", "Required for fail and blocked.")}, ["row", "status"]),
    _tool("check", "Record one expectation and whether it held, with concrete evidence. A run can only PASS "
          "with at least one check and no failed checks.",
          {"name": _s("string", "What was expected."), "passed": _s("boolean", "Did it hold?"),
           "evidence": _s("string", "Quoted bot text, button, payload or log line.")},
          ["name", "passed", "evidence"]),
    _tool("note", "Record an observation or bug in the run journal.",
          {"text": _s("string", "The note."),
           "kind": _s("string", "observation | bug", enum=["observation", "bug"], default="observation")},
          ["text"]),
    _tool("end_run", "Finish the run: writes run.json, transcript.json and log slices. With a plan it also writes "
          "the filled table (results.md, and <plan>.result.md next to the plan; unrecorded rows become "
          "'blocked: not run') and computes the verdict. Without a plan: give a verdict; PASS is downgraded if "
          "checks failed or none were recorded.",
          {"summary": _s("string", "3-8 sentences."),
           "verdict": _s("string", "Only for runs without a plan: PASS | FAIL | BLOCKED | INCONCLUSIVE",
                         enum=["PASS", "FAIL", "BLOCKED", "INCONCLUSIVE"])}, ["summary"]),
    _tool("write_file", "Write a report or a test plan. Only under runs/ or plans/ (.md .json .txt .yaml).",
          {"path": _s("string", "Path relative to the chat-tester folder, or the absolute run_dir path."),
           "content": _s("string", "File content.")}, ["path", "content"]),
]
TOOL_NAMES = {t["name"] for t in TOOLS}


def call_tool(tester: Tester, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name not in TOOL_NAMES:
        raise ToolError("unknown tool %r" % name)
    return getattr(tester, name)(**(args or {}))


def to_content(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = dict(result)
    image = result.pop("_image", None)
    content: List[Dict[str, Any]] = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}]
    if image:
        try:
            data = Path(image).read_bytes()
            content.append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(data).decode()})
        except OSError:
            pass
    return content


class Server:
    def __init__(self, factory: Callable[[], Tester], out: IO[str]):
        self.factory, self.out = factory, out
        self.tester: Optional[Tester] = None

    def send(self, msg: Dict[str, Any]) -> None:
        self.out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.out.flush()

    def handle(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method, mid = msg.get("method"), msg.get("id")
        if method is None or mid is None:
            return None  # notification or a response to us
        params = msg.get("params") or {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                      "instructions": "Chat-testing tools for an app in the iOS Simulator. Start with status."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name", "")
            try:
                if self.tester is None:
                    self.tester = self.factory()
                result = {"content": to_content(call_tool(self.tester, name, params.get("arguments") or {})),
                          "isError": False}
            except ToolError as exc:
                result = {"content": to_content(exc.to_dict()), "isError": True}
            except TypeError as exc:
                result = {"content": to_content({"error": "bad arguments: %s" % exc}), "isError": True}
            except Exception as exc:  # keep the server alive, report the bug
                traceback.print_exc(file=sys.stderr)
                result = {"content": to_content({"error": "internal error: %r" % exc}), "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, inp: IO[str]) -> None:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            reply = self.handle(msg) if isinstance(msg, dict) else None
            if reply is not None:
                self.send(reply)
