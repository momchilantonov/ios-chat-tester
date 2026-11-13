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
    "link": ("Read more on our website.", ["Open link"]),
    "confirm": ("Block these cards?", ["Confirm", "Cancel"]),
    "menu": ("What would you like to do?", ["A transfer", "B payment", "C rates", "D limits", "E other"]),
    "products": ("Which product?", ["Overdraft", "Credit card"]),
    "consent": ("Do you want to keep your consent?", ["Keep consent", "Withdraw"]),
    "loans": ("Please choose 👇", ["Car loan", "Home loan"]),
    "main": ("Please choose 👇", ["Loans", "Cards"]),
    "transfer": ("Here is what I can do for you:", []),
    "faq": ("\n\n".join("Paragraph %d of the long answer explains one more aspect of the topic in enough words "
                         "to need several lines on a phone screen." % i for i in range(1, 6)), []),
    "long option": ("Choose how to continue with your request:", ["Show me the details of my current account balance",
                                                                  "Something else"]),
    "show me the details of my current account balance": (
        "Account overview", []),
}
BOT["two"] = ("The first part of the answer.\n\nThe second part of the answer.", [])
BOT["продължи"] = ("Do you want to block the selected cards?", ["Confirm", "Cancel"])
LONG_TITLE = "Show me the details of my curr"  # first 30 characters of the long option


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
        self.start_on_menu = False   # fresh launch shows a menu; "Open chat" opens the chat
        self.prefill = ""            # text pre-filled in the composer on launch
        self.qr_as_other = False     # quick replies exposed as plain views, not buttons (common in chat SDKs)
        self.stale_y = None          # old quick replies keep reporting a position (y) after scrolling away
        self.render_delay = 0.0      # the bot's event exists (evidence) this long before the UI draws it
        self.switch_delay = 0.0      # "Open link" sends the app to the background only after this delay
        self.chip_strip = False      # quick replies as buttons "X." inside a horizontal strip, captions as texts
        self.reverse_order = False   # accessibility order of quick replies differs from screen order
        self.rows_as_text = False    # picker rows as two text elements each, no cell/checkbox/selected state
        self.rows_stacked = False    # picker rows as a cell with two stacked texts (name above number)
        self.hidden_copy = ""        # a hidden (not hittable) copy of this button drawn over the lowest button
        self.no_hittable = False     # an old driver without the "hittable" command
        self.interim = ""            # the app draws this text at once (no bot event), the bot answers later
        self.skip_paragraph = None   # this bubble of a multi-bubble reply is never drawn
        self.web_sheet = False       # "Open link" opens an in-app web page over the chat
        self.long_title_panel = False  # the bot's reply to "long option" has a panel titled like the option
        self.toast = ""              # an in-app banner at the top (exposed as a view with a "toast" id)
        self.ghost_band = False      # old texts leave stacked, overlapping, not hittable copies above the composer
        self.submit_echo = False     # "Продължи" echoes the selected rows (one bubble, one line per text)
        self.late_delay = 0.0        # the 2nd and later bubbles of a reply are drawn this much later
        self.pick_rows = None        # rows the card picker shows (default: two cards)
        self.dialog = False          # an "end the conversation?" dialog covers the chat (no composer)
        self.nav_ghost = False       # an old disabled "Continue" left under the navigation bar
        self.lock = threading.Lock()
        self.received = []           # what the "bot" received: {"text"} or {"payload"}
        self.commands = []
        self.reset()

    # -- app model --------------------------------------------------------------------------------
    def reset(self):
        self.messages = []           # (who, text)
        self.buttons = []            # [(label, payload)]
        self.rows = []               # [[label, selected]] selectable list rows (cells)
        self.rows_after = 0          # ... drawn under this many messages
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
        self.stale = []              # labels of old quick replies that still report a position
        self.events = []             # what the bot's event export shows: (who, text, options)
        self.drawn_at = None         # when the pending reply becomes visible
        self.switch_at = None
        self.offset = 0.0            # how far the user scrolled up (0 = at the bottom)
        self.late = []               # bubbles still to be drawn, and when
        self.late_at = 0.0
        self.actions = []            # full-width action rows ("New transfer ›")
        if self.welcome:
            self.messages.append(("bot", "Welcome! How can I help?"))

    def _user(self, text, payload=None):
        self.messages.append(("user", text))
        self.events.append(("user", text, []))
        if self.stale_y is not None and self.buttons:
            self.stale = [b for b, _ in self.buttons]
        self.buttons = []
        self.received.append({"payload": payload} if payload else {"text": text})
        self.scroll_until = time.monotonic() + 0.6
        self.offset = 0.0
        self.actions = []
        if self.silent:
            return
        if self.interim:
            self.messages.append(("bot", self.interim))
        key = (payload or text).strip().lower().lstrip("/")
        reply = BOT["hello"] if key in ("hello", "здравей") else BOT.get(key)
        if reply is None:
            reply = ("Sorry, I did not understand: %s" % text, [])
        self.typing_until = time.monotonic() + self.reply_delay
        self.pending = reply

    def _tick(self):
        now = time.monotonic()
        if self.pending and now >= self.typing_until and self.drawn_at is None:
            self.events.append(("bot", self.pending[0], list(self.pending[1])))  # the bot has answered
            self.drawn_at = self.typing_until + self.render_delay
        if self.pending and self.drawn_at is not None and now >= self.drawn_at:
            self.drawn_at = None
            text, buttons = self.pending
            for i, part in enumerate(text.split("\n\n")):  # a long answer comes as several bubbles
                if i == self.skip_paragraph:
                    continue
                if i and self.late_delay:
                    self.late.append(part)
                else:
                    self.messages.append(("bot", part))
            self.late_at = now + self.late_delay
            if self.long_title_panel and text == "Account overview":
                self.messages.append(("bot", LONG_TITLE + " (panel)"))
                self.messages.append(("bot", "Balance: 1 234 EUR"))
            self.buttons = [(b, b.lower()) for b in buttons]
            if text.startswith("Select the cards"):
                self.rows = [list(r) for r in self.pick_rows] if self.pick_rows else \
                    [["Visa ****1111", False], ["Mastercard ****2222", False]]
                self.rows_after = len(self.messages)
            if text.startswith("Here is what I can do"):
                self.actions = ["New transfer ›"]
            self.offset = 0.0
            self.pending = None
            self.scroll_until = time.monotonic() + 0.6

    def _base(self):
        return [{"type": "navigationBar", "label": "", "id": "", "value": "", "x": 0, "y": 0, "w": W, "h": 90,
                 "depth": 1},
                {"type": "text", "label": "Assistant", "id": "", "value": "", "x": 150, "y": 50, "w": 90, "h": 20,
                 "depth": 2}]

    def elements(self):
        self._tick()
        if self.late and time.monotonic() >= self.late_at:
            self.messages.extend(("bot", part) for part in self.late)
            self.late = []
        els = self._base()
        if self.screen == "web":
            return self._defaults([
                {"type": "webView", "label": "", "id": "", "value": "", "x": 0, "y": 90, "w": W, "h": H - 90},
                {"type": "text", "label": "Example page", "id": "", "value": "", "x": 20, "y": 120, "w": 300, "h": 30},
                {"type": "button", "label": "Done", "id": "", "value": "", "x": 10, "y": 50, "w": 60, "h": 30}])
        if self.screen == "menu":
            els += [{"type": "button", "label": "Local Flow", "id": "", "value": "", "x": 20, "y": 200, "w": 350, "h": 44},
                    {"type": "button", "label": "Open chat", "id": "", "value": "", "x": 20, "y": 260, "w": 350, "h": 44}]
            return self._defaults(els)
        rows = []
        if self.date_separator:
            rows.append(("sep", self.date_separator, None))
        for n, (who, text) in enumerate(self.messages):
            rows.append(("msg", who, text))
            if n == self.rows_after - 1:  # list rows stay under the message that offered them
                rows.extend(("row", i, None) for i in range(len(self.rows)))
        if self.carousel:
            rows.append(("carousel", None, None))
        for i in range(len(self.actions)):
            rows.append(("action", i, None))
        if self.chip_strip and self.buttons:
            rows.append(("strip", None, None))
        else:
            for label, _ in self.buttons:
                rows.append(("btn", label, None))
        if self.pending and self.drawn_at is None:
            rows.append(("typing", None, None))
        y = 100.0
        placed = []
        for row in rows:
            placed.append((row, y))
            y += 210 if row[0] == "msg" and len(row[2]) > 80 else \
                (24 * len(row[2].split("\n")) + 20) if row[0] == "msg" and "\n" in row[2] else 60
        shift = max(0.0, y - 740)  # chat sticks to the bottom; old rows scroll off the top
        self.offset = max(0.0, min(self.offset, shift))
        for row, ry in placed:
            ry -= shift - self.offset
            kind = row[0]
            if kind == "msg" and "\n" in row[2]:  # one bubble, one text per line (the echo of a submit)
                lines = row[2].split("\n")
                els.append({"type": "other", "label": "", "id": "", "value": "", "x": 150, "y": ry, "w": 230,
                            "h": 24 * len(lines) + 10})
                for j, line in enumerate(lines):
                    els.append({"type": "text", "label": line, "id": "", "value": "", "x": 160, "y": ry + 5 + 24 * j,
                                "w": 200, "h": 20})
            elif kind == "msg":
                x = 150 if row[1] == "user" else 10
                h = 200 if len(row[2]) > 80 else 50
                els.append({"type": "other", "label": row[2], "id": "", "value": "", "x": x, "y": ry, "w": 230, "h": h})
                els.append({"type": "text", "label": row[2], "id": "", "value": "", "x": x + 5, "y": ry + 5, "w": 220, "h": h - 10})
            elif kind == "action":
                label = self.actions[row[1]]
                els.append({"type": "other", "label": label, "id": "act.%d" % row[1], "value": "", "x": 0, "y": ry,
                            "w": W, "h": 44, "_action": label})
                els.append({"type": "text", "label": label, "id": "", "value": "", "x": 16, "y": ry + 10, "w": 200, "h": 24})
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
                if self.rows_stacked:
                    name, number = label.split(" ", 1)
                    els.append({"type": "cell", "label": "", "id": "", "value": "", "x": 10, "y": ry, "w": 370, "h": 56,
                                "selected": sel, "_row": row[1]})
                    els.append({"type": "text", "label": name, "id": "", "value": "", "x": 20, "y": ry + 4, "w": 150, "h": 22})
                    els.append({"type": "text", "label": number, "id": "", "value": "", "x": 20, "y": ry + 28, "w": 150, "h": 22})
                elif self.rows_as_text:
                    name, number = label.split(" ", 1)
                    els.append({"type": "text", "label": name, "id": "", "value": "", "x": 20, "y": ry + 10, "w": 150, "h": 24,
                                "_row": row[1]})
                    els.append({"type": "text", "label": number, "id": "", "value": "", "x": 200, "y": ry + 12, "w": 150, "h": 22,
                                "_row": row[1]})
                else:
                    els.append({"type": "cell", "label": label, "id": "", "value": "", "x": 10, "y": ry, "w": 370, "h": 50,
                                "selected": sel})
            elif kind == "strip":
                els.append({"type": "collectionView", "label": "", "id": "", "value": "", "x": 0, "y": ry, "w": W, "h": 50})
                for i, (label, _) in enumerate(self.buttons):
                    els.append({"type": "button", "label": label + ".", "id": "qr." + label.lower(), "value": "",
                                "x": 10 + 130 * i, "y": ry + 5, "w": 120, "h": 40})
                    els.append({"type": "text", "label": label, "id": "", "value": "",
                                "x": 20 + 130 * i, "y": ry + 12, "w": 100, "h": 26})
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
        if self.ghost_band:  # old texts, stacked and overlapping just above the composer
            old = [t for _, t in self.messages[:-2]][-4:]
            for j, t in enumerate(old):
                els.append({"type": "text", "label": t, "id": "", "value": "", "x": 14 + 3 * j, "y": 700 + 8 * j,
                            "w": 220, "h": 40, "_hidden": True})
        if self.nav_ghost:
            els.append({"type": "button", "label": "Continue", "id": "", "value": "", "x": 20, "y": 18, "w": 120,
                        "h": 40, "enabled": False})
        if self.dialog:
            els.append({"type": "text", "label": "Are you sure you want to end the conversation?", "id": "",
                        "value": "", "x": 40, "y": 380, "w": 310, "h": 40})
            els.append({"type": "button", "label": "Yes", "id": "dlg.yes", "value": "", "x": 40, "y": 440, "w": 140, "h": 44})
            els.append({"type": "button", "label": "No", "id": "dlg.no", "value": "", "x": 210, "y": 440, "w": 140, "h": 44})
        if self.hidden_copy:
            qr = [e for e in els if e["id"].startswith("qr.")]
            if qr:
                low = max(qr, key=lambda e: e["y"])
                els.append({"type": "button", "label": self.hidden_copy, "id": "", "value": "", "x": low["x"],
                            "y": low["y"], "w": low["w"], "h": low["h"], "_hidden": True})
        for i, label in enumerate(self.stale):  # dead copies: tapping them does nothing
            els.append({"type": "button", "label": label, "id": "", "value": "",
                        "x": 10 + 210 * i, "y": self.stale_y, "w": 200, "h": 44})
        if self.toast:
            els.append({"type": "other", "label": self.toast, "id": "toastBanner", "value": "", "x": 8, "y": 95,
                        "w": W - 16, "h": 50})
        if self.banner:
            els.append({"type": "text", "label": self.banner, "id": "", "value": "", "x": 100, "y": 95, "w": 190, "h": 20})
        if self.menu:
            els.append({"type": "button", "label": "Copy", "id": "", "value": "", "x": 150, "y": 400, "w": 90, "h": 40})
        if self.dialog:
            return self._defaults(self._order(els))
        els.append(dict(COMPOSER, type="textView", label="", id="", value=self.value,
                        placeholder="" if self.placeholder_label else "Message"))
        if self.placeholder_label and not self.value:
            els.append({"type": "text", "label": self.placeholder_label, "id": "", "value": "",
                        "x": COMPOSER["x"] + 8, "y": COMPOSER["y"] + 10, "w": 120, "h": 20})
        if self.send_label:
            els.append(dict(SEND, type="button", label=self.send_label, id="", value=""))
        return self._defaults(self._order(els))

    def _order(self, els):
        if not self.reverse_order:
            return els
        qr = [e for e in els if e["id"].startswith("qr.")]
        rest = [e for e in els if not e["id"].startswith("qr.")]
        return rest + qr[1:] + qr[:1]  # accessibility order: B, C, D, E, A

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
            if self.switch_at is not None and time.monotonic() >= self.switch_at:
                self.state, self.switch_at = "backgroundSuspended", None
            if cmd == "ping":
                return {"driver": "simchat", "version": 2}
            if cmd == "state":
                return {"app_state": self.state}
            if cmd == "activate":
                self.state = "foreground"
                return {"app_state": self.state}
            if cmd == "launch":
                self.reset()
                return {"app_state": self.state}
            if cmd == "hittable":
                if self.no_hittable:
                    return {"error": "unknown command 'hittable'"}
                found = [e for e in (self.elements() if self.state == "foreground" else [])
                         if (e["label"] == args.get("label") if args.get("label") else e["id"] == args.get("id"))
                         and (not args.get("type") or e["type"] == args["type"])]
                return {"elements": [{"x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"],
                                      "hittable": not e.get("_hidden")} for e in found]}
            if cmd == "snapshot":
                if self.state != "foreground":
                    return {"app_state": self.state, "elements": [], "keyboard": False, "alerts": []}
                return {"app_state": self.state, "screen": {"w": W, "h": H}, "keyboard": self.focused,
                        "elements": self.elements(), "alerts": []}
            if cmd == "tap":
                x, y = float(args["x"]), float(args["y"])
                if self.dialog:
                    if 440 <= y <= 484 and 210 <= x <= 350:
                        self.dialog = False
                    return {}
                if self.screen == "web":
                    if 10 <= x <= 70 and 50 <= y <= 80:
                        self.screen = "chat"
                    return {}
                if self.screen == "menu":
                    for e in self.elements():
                        if e["type"] == "button" and self._hit(e, x, y) and e["label"] == "Open chat":
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
                if self.rows_as_text:
                    for e in self.elements():
                        if e["type"] == "text" and "_row" in e and self._hit(e, x, y):
                            self.rows[e["_row"]][1] = not self.rows[e["_row"]][1]
                            return {}
                for e in self.elements():
                    if e.get("_action") and self._hit(e, x, y):
                        self._user(e["_action"], payload="/" + e["_action"].rstrip(" ›").lower())
                        return {}
                    if e["type"] == "cell" and "_row" in e and self._hit(e, x, y):
                        self.rows[e["_row"]][1] = not self.rows[e["_row"]][1]
                        return {}
                    if e["type"] == "cell" and self._hit(e, x, y):
                        for row in self.rows:
                            if row[0] == e["label"]:
                                row[1] = not row[1]
                        return {}
                    if e["id"].startswith("qr.") and self._hit(e, x, y):
                        if not e["enabled"]:
                            return {}
                        label = next(b for b, _ in self.buttons if "qr." + b.lower() == e["id"])
                        if label == "Open link":      # opens Safari: the app goes to the background
                            if self.web_sheet:
                                self.screen = "web"
                            elif self.switch_delay:
                                self.switch_at = time.monotonic() + self.switch_delay
                            else:
                                self.state = "background"
                            return {}
                        payload = dict(self.buttons).get(label)
                        if self.submit_echo and label == "Продължи":
                            echo = "\n".join(part for r in self.rows if r[1] for part in r[0].split(" ", 1))
                            self._user(echo, payload="/" + payload)
                            return {}
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
                if abs(y2 - y1) > abs(x2 - x1):  # finger down = scroll up to earlier messages
                    self.offset = max(0.0, self.offset + (y2 - y1))
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
