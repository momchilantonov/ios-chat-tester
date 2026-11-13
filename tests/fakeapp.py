"""A fake chat app behind a fake SimDriver: same TCP/JSON protocol as SimDriverServer.swift.

It reproduces the quirks seen with a real chat SDK in the Simulator: a cursor that lands where you tap,
a placeholder label inside the composer, scroll-bar elements that appear while the list moves, hidden
copies of old bubbles, a date separator, a noise banner, a demo menu before the chat, and selectable
list rows with a Continue button.
"""
import json
import socket
import threading
import time

W, H = 390.0, 844.0
COMPOSER = {"x": 10, "y": 770, "w": 300, "h": 40}
SEND = {"x": 320, "y": 770, "w": 60, "h": 40}

BOT = {
    "hello": ("Hi! I can help with cards and payments.", ["Cards", "Payments"]),
    "cards": ("Which card?", ["Debit", "Credit"]),
    "debit": ("Your debit card is blocked.", []),
    "pick": ("Select the cards to block:", ["Продължи"]),
}


class FakeApp:
    def __init__(self, reply_delay=0.25, send_label="Send"):
        self.reply_delay = reply_delay
        self.send_label = send_label
        self.silent = False          # bot never answers
        self.mangle_typing = 0       # number of type commands that get "autocorrected"
        self.welcome = True
        self.placeholder_label = ""  # custom placeholder drawn as a separate text inside the composer
        self.scrollbars = False      # thin "scroll bar" elements while the list moves
        self.ghosts = False          # hidden copies of old bubbles show up in snapshots
        self.date_separator = ""     # e.g. "Днес" above the first message
        self.banner = ""             # noise element, e.g. "test message 2"
        self.start_on_menu = False   # fresh launch shows a menu; "Remote Flow" opens the chat
        self.prefill = ""            # text pre-filled in the composer on launch
        self.qr_as_other = False     # quick replies exposed as plain views, not buttons (common in chat SDKs)
        self.lock = threading.Lock()
        self.received = []           # what the "bot" received: {"text"} or {"payload"}
        self.commands = []
        self.reset()

    # -- app model --------------------------------------------------------------------------------
    def reset(self):
        self.messages = []           # (who, text)
        self.buttons = []            # [(label, payload)]
        self.rows = []               # [[label, selected]] selectable list rows (cells)
        self.value = self.prefill
        self.cursor = len(self.value)
        self.focused = False
        self.typing_until = 0.0
        self.pending = None
        self.state = "foreground"
        self.screen = "menu" if self.start_on_menu else "chat"
        self.scroll_until = 0.0
        self.carousel = []           # items of a horizontal carousel, one visible at a time
        self.carousel_pos = 0
        self.menu = False            # long-press context menu
        self.swipes = []
        if self.welcome:
            self.messages.append(("bot", "Welcome! How can I help?"))

    def _user(self, text, payload=None):
        self.messages.append(("user", text))
        self.buttons = []
        self.received.append({"payload": payload} if payload else {"text": text})
        self.scroll_until = time.monotonic() + 0.6
        if self.silent:
            return
        key = (payload or text).strip().lower().lstrip("/")
        reply = BOT["hello"] if key in ("hello", "здравей") else BOT.get(key)
        if reply is None:
            reply = ("Sorry, I did not understand: %s" % text, [])
        self.typing_until = time.monotonic() + self.reply_delay
        self.pending = reply

    def _tick(self):
        if self.pending and time.monotonic() >= self.typing_until:
            text, buttons = self.pending
            self.messages.append(("bot", text))
            self.buttons = [(b, b.lower()) for b in buttons]
            if text.startswith("Select the cards"):
                self.rows = [["Visa ****1111", False], ["Mastercard ****2222", False]]
            self.pending = None
            self.scroll_until = time.monotonic() + 0.6

    def _base(self):
        return [{"type": "navigationBar", "label": "", "id": "", "value": "", "x": 0, "y": 0, "w": W, "h": 90},
                {"type": "text", "label": "Assistant", "id": "", "value": "", "x": 150, "y": 50, "w": 90, "h": 20}]

    def elements(self):
        self._tick()
        els = self._base()
        if self.screen == "menu":
            els += [{"type": "button", "label": "Local Flow", "id": "", "value": "", "x": 20, "y": 200, "w": 350, "h": 44},
                    {"type": "button", "label": "Remote Flow", "id": "", "value": "", "x": 20, "y": 260, "w": 350, "h": 44}]
            return self._defaults(els)
        rows = []
        if self.date_separator:
            rows.append(("sep", self.date_separator, None))
        for who, text in self.messages:
            rows.append(("msg", who, text))
        if self.carousel:
            rows.append(("carousel", None, None))
        for i in range(len(self.rows)):
            rows.append(("row", i, None))
        for label, _ in self.buttons:
            rows.append(("btn", label, None))
        if self.pending:
            rows.append(("typing", None, None))
        y = 100.0
        placed = []
        for row in rows:
            placed.append((row, y))
            y += 60
        shift = max(0.0, y - 740)  # chat sticks to the bottom; old rows scroll off the top
        for row, ry in placed:
            ry -= shift
            kind = row[0]
            if kind == "msg":
                x = 150 if row[1] == "user" else 10
                els.append({"type": "other", "label": row[2], "id": "", "value": "", "x": x, "y": ry, "w": 230, "h": 50})
                els.append({"type": "text", "label": row[2], "id": "", "value": "", "x": x + 5, "y": ry + 5, "w": 220, "h": 40})
            elif kind == "sep":
                els.append({"type": "text", "label": row[1], "id": "", "value": "", "x": 170, "y": ry + 15, "w": 50, "h": 20})
            elif kind == "btn":
                enabled = not (row[1] == "Продължи" and not any(sel for _, sel in self.rows))
                if self.qr_as_other:
                    els.append({"type": "other", "label": "", "id": "qr." + row[1].lower(), "value": "",
                                "x": 10, "y": ry, "w": 200, "h": 44, "enabled": enabled, "_qr": True})
                else:
                    els.append({"type": "button", "label": row[1], "id": "qr." + row[1].lower(), "value": "",
                                "x": 10, "y": ry, "w": 200, "h": 44, "enabled": enabled})
                els.append({"type": "text", "label": row[1], "id": "", "value": "", "x": 20, "y": ry + 10, "w": 150, "h": 24})
            elif kind == "row":
                label, sel = self.rows[row[1]]
                els.append({"type": "cell", "label": label, "id": "", "value": "", "x": 10, "y": ry, "w": 370, "h": 50,
                            "selected": sel})
            elif kind == "carousel":
                els.append({"type": "collectionView", "label": "", "id": "", "value": "", "x": 0, "y": ry, "w": W, "h": 55})
                els.append({"type": "text", "label": self.carousel[self.carousel_pos], "id": "", "value": "",
                            "x": 40, "y": ry + 10, "w": 300, "h": 30})
            else:
                els.append({"type": "other", "label": "typing", "id": "typing", "value": "", "x": 10, "y": ry, "w": 60, "h": 30})
        if self.ghosts and len(self.messages) > 2:  # hidden copy of the first bubble, drawn low on screen
            els.append({"type": "text", "label": self.messages[0][1], "id": "", "value": "", "x": 15, "y": 690, "w": 220, "h": 40})
            if self.date_separator:
                els.append({"type": "text", "label": self.date_separator, "id": "", "value": "", "x": 170, "y": 720, "w": 50, "h": 20})
        if self.scrollbars and time.monotonic() < self.scroll_until:
            els.append({"type": "other", "label": "Vertical scroll bar, 2 pages", "id": "", "value": "0%",
                        "x": 384, "y": 95, "w": 3, "h": 650})
        if self.banner:
            els.append({"type": "text", "label": self.banner, "id": "", "value": "", "x": 100, "y": 95, "w": 190, "h": 20})
        if self.menu:
            els.append({"type": "button", "label": "Copy", "id": "", "value": "", "x": 150, "y": 400, "w": 90, "h": 40})
        els.append(dict(COMPOSER, type="textView", label="", id="", value=self.value,
                        placeholder="" if self.placeholder_label else "Message"))
        if self.placeholder_label and not self.value:
            els.append({"type": "text", "label": self.placeholder_label, "id": "", "value": "",
                        "x": COMPOSER["x"] + 8, "y": COMPOSER["y"] + 10, "w": 120, "h": 20})
        if self.send_label:
            els.append(dict(SEND, type="button", label=self.send_label, id="", value=""))
        return self._defaults(els)

    @staticmethod
    def _defaults(els):
        for e in els:
            e.setdefault("placeholder", "")
            e.setdefault("enabled", True)
            e.setdefault("selected", False)
            e.setdefault("depth", 1)
        return els

    @staticmethod
    def _hit(r, x, y):
        return r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]

    def handle(self, cmd, args):
        with self.lock:
            self.commands.append((cmd, args))
            if cmd == "ping":
                return {"driver": "simchat", "version": 1}
            if cmd == "state":
                return {"app_state": self.state}
            if cmd == "activate":
                self.state = "foreground"
                return {"app_state": self.state}
            if cmd == "launch":
                self.reset()
                return {"app_state": self.state}
            if cmd == "snapshot":
                if self.state != "foreground":
                    return {"app_state": self.state, "elements": [], "keyboard": False, "alerts": []}
                return {"app_state": self.state, "screen": {"w": W, "h": H}, "keyboard": self.focused,
                        "elements": self.elements(), "alerts": []}
            if cmd == "tap":
                x, y = float(args["x"]), float(args["y"])
                if self.screen == "menu":
                    for e in self.elements():
                        if e["type"] == "button" and self._hit(e, x, y) and e["label"] == "Remote Flow":
                            self.screen = "chat"
                    return {}
                if self._hit(COMPOSER, x, y):
                    self.focused = True
                    frac = (x - COMPOSER["x"]) / COMPOSER["w"]
                    self.cursor = max(0, min(len(self.value), int(round(len(self.value) * frac))))
                    return {}
                if self.send_label and self._hit(SEND, x, y):
                    if self.value.strip():
                        text, self.value, self.cursor = self.value, "", 0
                        self._user(text)
                    return {}
                for e in self.elements():
                    if e["type"] == "cell" and self._hit(e, x, y):
                        for row in self.rows:
                            if row[0] == e["label"]:
                                row[1] = not row[1]
                        return {}
                    if e["id"].startswith("qr.") and self._hit(e, x, y):
                        if not e["enabled"]:
                            return {}
                        label = next(b for b, _ in self.buttons if "qr." + b.lower() == e["id"])
                        payload = dict(self.buttons).get(label)
                        self._user(label, payload="/" + payload)
                        return {}
                return {}
            if cmd == "type":
                if not self.focused:
                    return {"error": "Neither element nor any descendant has keyboard focus."}
                text = args["text"]
                if self.mangle_typing > 0:
                    self.mangle_typing -= 1
                    text = text[:-1] + "x"
                self.value = self.value[:self.cursor] + text + self.value[self.cursor:]
                self.cursor += len(text)
                return {}
            if cmd == "delete":
                n = min(int(args.get("count", 0)), self.cursor)  # deletes only what is before the cursor
                self.value = self.value[:self.cursor - n] + self.value[self.cursor:]
                self.cursor -= n
                return {}
            if cmd == "swipe":
                x1, y1, x2, y2 = (float(args[k]) for k in ("x1", "y1", "x2", "y2"))
                self.swipes.append(args)
                for e in self.elements():
                    if e["type"] == "collectionView" and self._hit(e, x1, y1) and abs(x2 - x1) > abs(y2 - y1):
                        step = 1 if x2 < x1 else -1  # finger left -> next item
                        self.carousel_pos = max(0, min(len(self.carousel) - 1, self.carousel_pos + step))
                return {}
            if cmd == "long_press":
                x, y = float(args["x"]), float(args["y"])
                if any(e["type"] == "other" and self._hit(e, x, y) for e in self.elements()):
                    self.menu = True
                return {}
            if cmd == "stop":
                return {}
            return {"error": "unknown command %s" % cmd}


class FakeDriverServer:
    """TCP server speaking the SimDriver protocol, backed by a FakeApp."""

    def __init__(self, app, token="t0k3n"):
        self.app, self.token = app, token
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        self.sock.settimeout(0.2)
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            with conn:
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                try:
                    req = json.loads(data.split(b"\n")[0].decode("utf-8"))
                    if req.get("token") != self.token:
                        reply = {"ok": False, "error": "bad token"}
                    else:
                        res = self.app.handle(req.get("cmd"), req.get("args") or {})
                        reply = {"ok": False, "error": res["error"]} if "error" in res else dict(res, ok=True)
                except Exception as exc:  # pragma: no cover
                    reply = {"ok": False, "error": repr(exc)}
                conn.sendall(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")

    def close(self):
        self.running = False
        self.thread.join(timeout=2)
        self.sock.close()


class FakeSimctl:
    """Stands in for `xcrun simctl`, `open` and `sips`."""

    def __init__(self, booted=("SIM-1",)):
        self.booted = list(booted)
        self.calls = []
        self.app_log = []  # lines returned by `simctl spawn ... log show`

    def __call__(self, cmd, timeout=60):
        import subprocess
        self.calls.append(cmd)
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]:
            devs = [{"udid": u, "name": "iPhone 16", "state": "Booted"} for u in self.booted]
            out = json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-4": devs}})
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:3] == ["xcrun", "simctl", "appinfo"]:
            out = '{\n    CFBundleExecutable = "ChatDemo";\n    CFBundleIdentifier = "%s";\n}\n' % cmd[4]
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:3] == ["xcrun", "simctl", "spawn"] and "log" in cmd:
            out = "Timestamp               Ty Process[PID:TID]\n" + "\n".join(self.app_log) + "\n"
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:4] == ["xcrun", "simctl", "io", cmd[3]] and cmd[4] == "screenshot":
            with open(cmd[-1], "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\nfake")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
