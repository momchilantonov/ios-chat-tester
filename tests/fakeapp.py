"""A fake chat app behind a fake SimDriver: same TCP/JSON protocol as SimDriverServer.swift."""
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
}


class FakeApp:
    def __init__(self, reply_delay=0.25, send_label="Send"):
        self.reply_delay = reply_delay
        self.send_label = send_label
        self.silent = False          # bot never answers
        self.mangle_typing = 0       # number of type commands that get "autocorrected"
        self.welcome = True
        self.lock = threading.Lock()
        self.received = []           # what the "bot" received: {"text"} or {"payload"}
        self.commands = []
        self.reset()

    # -- app model --------------------------------------------------------------------------------
    def reset(self):
        self.messages = []           # (who, text)
        self.buttons = []            # [(label, payload)]
        self.value = ""
        self.focused = False
        self.typing_until = 0.0
        self.pending = None
        self.state = "foreground"
        if self.welcome:
            self.messages.append(("bot", "Welcome! How can I help?"))

    def _user(self, text, payload=None):
        self.messages.append(("user", text))
        self.buttons = []
        self.received.append({"payload": payload} if payload else {"text": text})
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
            self.pending = None

    def elements(self):
        self._tick()
        els = [{"type": "navigationBar", "label": "", "id": "", "value": "", "x": 0, "y": 0, "w": W, "h": 90},
               {"type": "text", "label": "Assistant", "id": "", "value": "", "x": 150, "y": 50, "w": 90, "h": 20}]
        rows = []
        for who, text in self.messages:
            rows.append(("msg", who, text))
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
            elif kind == "btn":
                els.append({"type": "button", "label": row[1], "id": "qr." + row[1].lower(), "value": "",
                            "x": 10, "y": ry, "w": 200, "h": 44})
                els.append({"type": "text", "label": row[1], "id": "", "value": "", "x": 20, "y": ry + 10, "w": 150, "h": 24})
            else:
                els.append({"type": "other", "label": "typing", "id": "typing", "value": "", "x": 10, "y": ry, "w": 60, "h": 30})
        els.append(dict(COMPOSER, type="textView", label="", id="", value=self.value, placeholder="Message"))
        if self.send_label:
            els.append(dict(SEND, type="button", label=self.send_label, id="", value=""))
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
                if self._hit(COMPOSER, x, y):
                    self.focused = True
                    return {}
                if self.send_label and self._hit(SEND, x, y):
                    if self.value.strip():
                        text, self.value = self.value, ""
                        self._user(text)
                    return {}
                for e in self.elements():
                    if e["type"] == "button" and e["id"].startswith("qr.") and self._hit(e, x, y):
                        label = e["label"]
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
                self.value += text
                return {}
            if cmd == "delete":
                n = int(args.get("count", 0))
                self.value = self.value[:-n] if n < len(self.value) else ""
                return {}
            if cmd == "swipe":
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

    def __call__(self, cmd, timeout=60):
        import subprocess
        self.calls.append(cmd)
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]:
            devs = [{"udid": u, "name": "iPhone 16", "state": "Booted"} for u in self.booted]
            out = json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-4": devs}})
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:4] == ["xcrun", "simctl", "io", cmd[3]] and cmd[4] == "screenshot":
            with open(cmd[-1], "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\nfake")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
