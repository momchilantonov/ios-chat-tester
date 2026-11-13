"""Turns a driver snapshot into something a chat tester can use: messages, buttons, composer, Send."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

INPUT_TYPES = ("textField", "textView", "searchField")
TEXT_TYPES = ("text", "textView", "other", "cell", "link")
BUTTON_TYPES = ("button", "link")
CHROME_TYPES = ("navigationBar", "tabBar", "toolbar")  # app chrome, not conversation
CONTAINER_TYPES = ("scrollView", "collectionView", "table")  # swipe targets such as carousels
CONTROL_TYPES = ("cell", "switch", "toggle", "checkBox", "radioButton", "slider", "segmentedControl",
                 "picker", "pickerWheel", "stepper")  # rich components: list rows, checkboxes, ...
THIN_PT = 8.0  # scroll indicators are a few points wide; real text is never this thin
ALERT_TYPES = ("alert", "sheet")
BANNER_RX = re.compile(r"banner|toast|snackbar|notification", re.IGNORECASE)


def norm(text: str) -> str:
    """Comparison form: NFC, whitespace collapsed, case-folded."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip().casefold()


def norm_label(text: str) -> str:
    """Label comparison: like norm; iOS's trailing '.' on button labels ("Confirm.") and a trailing chevron
    ("New transfer ›") are ignored."""
    return norm(text).rstrip(" .›>❯")


def key(text: str) -> str:
    """Loose comparison form: letters and digits only (markdown, punctuation, emoji and spacing dropped)."""
    return "".join(ch for ch in norm(text) if ch.isalnum())


def anchor_hits(scr: "Screen", msgs: List["Element"], anchor: str) -> List[List["Element"]]:
    """Occurrences of the user's own bubble. A multi-line anchor (the echo of a submit that lists the selected
    rows) must match as consecutive user-side lines; the last line marks where the reply starts."""
    lines = [ln for ln in (anchor or "").split("\n") if ln.strip()]
    if len(lines) <= 1:
        return [[m] for m in msgs if anchor_match(scr, m, anchor)]
    out = []
    for i in range(len(msgs) - len(lines) + 1):
        run = msgs[i:i + len(lines)]
        if all(anchor_match(scr, m, ln) for m, ln in zip(run, lines)):
            out.append(run)
    return out


def anchor_match(scr: "Screen", e: "Element", anchor: str) -> bool:
    """Is e the user's own message/tap echo for this anchor? Only a bubble on the user's side; exact
    (norm_label), or a prefix (the echo of a long label may be truncated)."""
    a = norm_label(anchor)
    if not a or (scr.width and not scr.user_side(e)):
        return False  # never a bot bubble, an option row with the same text, a button or a hidden copy
    t = norm_label(e.text)
    if t == a:
        return True
    t = t.rstrip("…")
    return (len(a) > 30 and t.startswith(a[:30])) or (len(t) >= 10 and a.startswith(t))


def exact(text: str) -> str:
    """Read-back form: NFC, whitespace collapsed, case kept."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


@dataclass
class Element:
    index: int
    type: str
    label: str
    id: str
    value: str
    placeholder: str
    enabled: bool
    selected: bool
    x: float
    y: float
    w: float
    h: float
    depth: int = 0

    @property
    def text(self) -> str:
        return self.label or self.value

    @property
    def center(self):
        return (round(self.x + self.w / 2, 1), round(self.y + self.h / 2, 1))

    def contains(self, other: "Element") -> bool:
        return (self.x - 1 <= other.x and self.y - 1 <= other.y
                and other.x + other.w <= self.x + self.w + 1 and other.y + other.h <= self.y + self.h + 1)

    def same_as(self, other: "Element") -> bool:
        return self.type == other.type and self.label == other.label and self.id == other.id

    def describe(self) -> str:
        parts = ["[%d] %s" % (self.index, self.type)]
        if self.label:
            parts.append(repr(self.label[:160]))
        if self.value and self.value != self.label:
            parts.append("value=%r" % self.value[:160])
        if self.placeholder and self.type in INPUT_TYPES:
            parts.append("placeholder=%r" % self.placeholder[:60])
        if self.id:
            parts.append("id=%s" % self.id)
        if not self.enabled:
            parts.append("disabled")
        if self.selected:
            parts.append("SELECTED")
        cx, cy = self.center
        parts.append("@(%d,%d)" % (cx, cy))
        if self.type in CONTAINER_TYPES:
            parts.append("%dx%d" % (self.w, self.h))
        return " ".join(parts)

    def overlap(self, other: "Element") -> float:
        ix = min(self.x + self.w, other.x + other.w) - max(self.x, other.x)
        iy = min(self.y + self.h, other.y + other.h) - max(self.y, other.y)
        return ix * iy if ix > 0 and iy > 0 else 0.0

    def same_frame(self, other: "Element") -> bool:
        return all(abs(a - b) <= 1 for a, b in ((self.x, other.x), (self.y, other.y), (self.w, other.w),
                                                 (self.h, other.h)))


class Screen:
    def __init__(self, raw: Dict[str, Any], ignore: Sequence[str] = ()):
        self.raw = raw
        self.ignore = [re.compile(p, re.IGNORECASE) for p in ignore if p]
        self.app_state = raw.get("app_state", "unknown")
        size = raw.get("screen") or {}
        self.width = float(size.get("w") or 0)
        self.height = float(size.get("h") or 0)
        self.keyboard = bool(raw.get("keyboard"))
        self.alerts: List[Dict[str, Any]] = raw.get("alerts") or []
        self.elements: List[Element] = []
        for i, e in enumerate(raw.get("elements") or []):
            self.elements.append(Element(
                index=i, type=str(e.get("type", "")), label=str(e.get("label") or ""),
                id=str(e.get("id") or ""), value=str(e.get("value") or ""),
                placeholder=str(e.get("placeholder") or ""), enabled=bool(e.get("enabled", True)),
                selected=bool(e.get("selected", False)), x=float(e.get("x", 0)), y=float(e.get("y", 0)),
                w=float(e.get("w", 0)), h=float(e.get("h", 0)), depth=int(e.get("depth") or 0)))
        self.hidden: set = set()  # indices of hidden copies (set by the tester after asking the driver)
        self._shown = [e for e in self.elements if self.on_screen(e) and not self._under_chrome(e)]

    # -- geometry -------------------------------------------------------------------------------
    def user_side(self, e: Element) -> bool:
        """Right-aligned: the user's own bubbles (and tap echoes) in a chat."""
        return bool(self.width) and e.x > self.width * 0.12 and e.x + e.w / 2 > self.width * 0.5

    def on_screen(self, e: Element) -> bool:
        if not self.width or not self.height:
            return True
        cx, cy = e.center
        return 0 <= cx <= self.width and 0 <= cy <= self.height

    def visible(self) -> List[Element]:
        """On screen, not under the navigation bar or a top banner, and not a hidden copy."""
        return [e for e in self._shown if e.index not in self.hidden]

    def _members(self, bar: Element) -> set:
        """Elements that belong to a bar: its descendants (snapshot depth), or - without depth - inside it."""
        if len({e.depth for e in self.elements}) > 1:
            out = set()
            for e in self.elements[bar.index + 1:]:
                if e.depth <= bar.depth:
                    break
                out.add(e.index)
            return out
        return {e.index for e in self.elements if e.index != bar.index and bar.contains(e)}

    def _under_chrome(self, e: Element) -> bool:
        """Old elements left under the navigation bar or a top banner (e.g. a disabled "Continue" at y=18)."""
        if not hasattr(self, "_bars"):
            self._bars = [(b, self._members(b)) for b in self.elements if self.on_screen(b) and (
                b.type == "navigationBar" or (b.type in ("other", "text") and b.id and BANNER_RX.search(b.id)
                                              and b.y < (self.height or 1e9) * 0.25))]
        cx, cy = e.center
        for bar, members in self._bars:
            if e.index == bar.index or e.index in members:
                continue
            if bar.x <= cx <= bar.x + bar.w and cy < bar.y + bar.h:
                return True
        return False

    def overlapping(self) -> List[Element]:
        """Texts and buttons whose frames overlap another one's (not parent/child, not a wrapper with the same
        text). Real bubbles never overlap; stacked hidden copies of old bubbles do."""
        els = [e for e in self._shown if e.text and e.type in TEXT_TYPES + BUTTON_TYPES and not self.is_noise(e)]
        out = set()
        for i, a in enumerate(els):
            for b in els[i + 1:]:
                area = a.overlap(b)
                if area <= 0 or area < 0.25 * min(a.w * a.h, b.w * b.h):
                    continue
                if a.same_frame(b):
                    if norm(a.text) == norm(b.text):
                        continue
                elif a.contains(b) or b.contains(a):
                    continue
                out.update((a.index, b.index))
        return [e for e in els if e.index in out]

    def neighbour(self, e: Element) -> str:
        """The text next to e on the same line, or else the line right below it (e.g. a masked card number)."""
        pool = [o for o in self.visible() if o.text and o.index != e.index and o.type in TEXT_TYPES + BUTTON_TYPES
                and not o.contains(e) and not e.contains(o)]
        cy = e.center[1]
        right = [o for o in pool if abs(o.center[1] - cy) < max(e.h, 10) / 2 and o.x >= e.x + e.w - 1]
        if right:
            return min(right, key=lambda o: o.x).text
        gap = max(e.h, 20.0) * 1.5
        below = [o for o in pool if 0 <= o.y - (e.y + e.h) + 2 <= gap
                 and min(o.x + o.w, e.x + e.w) > max(o.x, e.x)]
        return min(below, key=lambda o: o.y).text if below else ""

    def is_noise(self, e: Element) -> bool:
        """Scroll indicators (thin), and labels matching chat.ignore_labels."""
        if 0 < min(e.w, e.h) <= THIN_PT:
            return True
        return bool(e.text) and any(rx.search(e.text) for rx in self.ignore)

    def carousels(self) -> List[Element]:
        """Horizontal strips (carousels): scroll containers much lower than the screen and at least half as wide."""
        if not self.height or not self.width:
            return []
        return [e for e in self.visible() if e.type in CONTAINER_TYPES
                and e.h <= self.height * 0.45 and e.w >= self.width * 0.5]

    def carousel_texts(self) -> List[Element]:
        boxes = self.carousels()
        return sorted([e for e in self.visible() if e.text and e.type in TEXT_TYPES and not self.is_noise(e)
                       and self._inside_any(e, boxes) and not self._covered_by_button(e)],
                      key=lambda e: (round(e.y), e.x)) if boxes else []

    def _covered_by_button(self, e: Element) -> bool:
        """A text drawn on a button (same label, overlapping frame) is the button's caption, not content."""
        k = norm_label(e.text)
        for b in self.visible():
            if b.type in BUTTON_TYPES and b.index != e.index and norm_label(b.text) == k and k:
                if b.x < e.x + e.w and e.x < b.x + b.w and b.y < e.y + e.h and e.y < b.y + b.h:
                    return True
        return False

    @staticmethod
    def _inside_any(e: Element, boxes: Sequence[Element]) -> bool:
        cx, cy = e.center
        return any(b.index != e.index and b.x <= cx <= b.x + b.w and b.y <= cy <= b.y + b.h for b in boxes)

    # -- chat parts -------------------------------------------------------------------------------
    def composer(self, chat: Dict[str, Any]) -> Optional[Element]:
        ids = set(chat.get("composer_ids") or [])
        inputs = [e for e in self.visible() if e.type in INPUT_TYPES]
        for e in inputs:
            if e.id and e.id in ids:
                return e
        if not inputs:
            return None
        return max(inputs, key=lambda e: e.y + e.h)  # the lowest text input is the chat composer

    def send_button(self, chat: Dict[str, Any], composer: Optional[Element]) -> Optional[Element]:
        buttons = [e for e in self.visible() if e.type == "button"]
        ids = set(chat.get("send_ids") or [])
        labels = {norm(x) for x in chat.get("send_labels") or []}
        for e in buttons:
            if (e.id and e.id in ids) or (e.label and norm(e.label) in labels):
                return e
        if composer is None:
            return None
        # Fallback: the button right of the composer on the same row.
        top, bottom = composer.y - 12, composer.y + composer.h + 12
        row = [e for e in buttons if e.x >= composer.x + composer.w * 0.6 and top <= e.center[1] <= bottom]
        return min(row, key=lambda e: e.x) if row else None

    def is_empty_input(self, e: Element) -> bool:
        v = exact(e.value)
        return v == "" or v == exact(e.placeholder)

    def buttons(self, exclude: Iterable[Optional[Element]] = ()) -> List[Element]:
        skip = {x.index for x in exclude if x is not None}
        return sorted([e for e in self.visible() if e.type in BUTTON_TYPES and e.index not in skip
                       and (e.label or e.id) and not self.is_noise(e)],
                      key=lambda e: (round(e.y), e.x))  # screen order, not accessibility order

    def controls(self, exclude: Iterable[Optional[Element]] = ()) -> List[Element]:
        """Rich components the user can operate: list rows, checkboxes, switches, pickers, selected items."""
        skip = {x.index for x in exclude if x is not None}
        return sorted([e for e in self.visible()
                       if (e.type in CONTROL_TYPES or e.selected) and e.type not in BUTTON_TYPES + CHROME_TYPES
                       and e.index not in skip and (e.text or e.id) and not self.is_noise(e)],
                      key=lambda e: (round(e.y), e.x))

    def _message_candidates(self, exclude: Iterable[Optional[Element]] = ()) -> List[Element]:
        excluded = [x for x in exclude if x is not None]
        skip = {x.index for x in excluded}
        buttons = [e for e in self.visible() if e.type in BUTTON_TYPES]
        chrome = [e for e in self.visible() if e.type in CHROME_TYPES]
        overlays = self.app_alert_elements()
        return [e for e in self.visible()
                if e.type in TEXT_TYPES and e.text.strip() and e.index not in skip
                and not self.is_noise(e)
                and not self._inside_any(e, excluded)          # e.g. a custom placeholder label in the composer
                and not self._inside_any(e, self.carousels())  # carousel cards are reported separately
                and not any(b.index != e.index and b.contains(e) for b in buttons)
                and not self._covered_by_button(e)
                and not any(c.contains(e) for c in chrome)
                and not any(o.index == e.index or o.contains(e) for o in overlays)]

    def actions(self, exclude: Iterable[Optional[Element]] = ()) -> List[Element]:
        """Tappable action cards that iOS exposes as plain views: a full-width, single-line row with a short
        label that is not a sentence (e.g. "New transfer ›"), below the last chat bubble."""
        if not self.width:
            return []
        cands = self._message_candidates(exclude)
        rows = [e for e in cands if e.type == "other" and e.w >= self.width * 0.8 and e.h <= 64
                and "\n" not in e.text and len(e.text.strip()) <= 40
                and not e.text.strip().endswith((".", "?", "!", ":"))]
        if not rows:
            return []
        others = [e for e in cands if not any(r.contains(e) for r in rows)]
        last = max((e.y for e in others), default=-1e9)
        return sorted([r for r in rows if r.y > last], key=lambda e: (round(e.y), e.x))

    def messages(self, exclude: Iterable[Optional[Element]] = ()) -> List[Element]:
        """Text-bearing elements top to bottom, without inputs, button captions, action cards and wrapper
        duplicates."""
        exclude = list(exclude)
        acts = self.actions(exclude)
        cands = [e for e in self._message_candidates(exclude) if not any(a.contains(e) for a in acts)]
        out = []
        for e in cands:
            if e.type in ("other", "cell"):
                inner = [c for c in cands if c is not e and e.contains(c)]
                # a wrapper repeating the text of a child element, or the texts of its children joined
                if any(norm(c.text) == norm(e.text) for c in inner):
                    continue
                if len(inner) > 1 and key(e.text) == key("".join(c.text for c in sorted(inner, key=lambda c: (c.y, c.x)))):
                    continue
            out.append(e)
        return sorted(out, key=lambda e: (round(e.y), e.x))

    def app_alert_elements(self) -> List[Element]:
        """In-app alerts, action sheets and banners/toasts (the system's own alerts are in self.alerts)."""
        return [e for e in self.visible() if e.type in ALERT_TYPES
                or (e.type in ("other", "text") and e.id and BANNER_RX.search(e.id))]

    def app_alerts(self) -> List[Dict[str, Any]]:
        out = []
        for a in self.app_alert_elements():
            inner = [e for e in self.visible() if e.index != a.index and a.contains(e)]
            texts = [e.text for e in inner if e.type not in BUTTON_TYPES and e.text]
            out.append({"kind": "banner" if a.type not in ALERT_TYPES else a.type, "label": a.text or " ".join(texts)[:300],
                        "buttons": ["[%d] %s" % (b.index, b.label or b.id) for b in inner if b.type in BUTTON_TYPES]})
        return out

    def web_view(self) -> bool:
        return any(e.type == "webView" for e in self.visible())

    def typing_elements(self, chat: Dict[str, Any]) -> List[Element]:
        ids = set(chat.get("typing_ids") or [])
        labels = [norm(x) for x in chat.get("typing_labels") or []]
        return [e for e in self.visible() if (e.id and e.id in ids)
                or (labels and any(lbl and lbl in norm(e.text) for lbl in labels))]

    def typing(self, chat: Dict[str, Any]) -> bool:
        return bool(self.typing_elements(chat))

    def find(self, text: str = "", ident: str = "", prefer: Sequence[str] = BUTTON_TYPES) -> List[Element]:
        """Candidates for a tap target: exact id; exact label (any element); then - only for buttons and controls
        and only for labels longer than 4 characters or with several words - whole-word, then substring matches.
        A chat bubble is never picked because it merely contains the text."""
        vis = self.visible()
        if ident:
            hits = [e for e in vis if e.id == ident]
        else:
            t = norm_label(text)
            hits = [e for e in vis if t and (norm_label(e.label) == t or norm_label(e.value) == t)]
            if not hits and t and (len(t) > 4 or " " in t):
                acts = {e.index for e in self.actions()}
                tappable = [e for e in vis if e.type in BUTTON_TYPES + CONTROL_TYPES or e.index in acts]
                word = re.compile(r"(?<!\w)%s(?!\w)" % re.escape(t))
                hits = [e for e in tappable if word.search(norm(e.label)) or word.search(norm(e.value))]
                if not hits:
                    hits = [e for e in tappable if t in norm(e.label) or t in norm(e.value)]
        return sorted(hits, key=lambda e: (e.type not in prefer, -e.y))

    def locate(self, old: Element) -> Optional[Element]:
        same = [e for e in self.visible() if e.same_as(old)]
        if not same:
            return None
        return min(same, key=lambda e: abs(e.y - old.y) + abs(e.x - old.x))

    def signature(self) -> tuple:
        return tuple((e.type, e.text, round(e.y), e.selected, e.enabled) for e in self.visible()
                     if e.text or e.type in CONTROL_TYPES + BUTTON_TYPES)

    def listing(self, limit: int = 120) -> List[str]:
        vis = [e for e in self._shown
               if e.text or e.id or e.type in INPUT_TYPES + BUTTON_TYPES + CONTAINER_TYPES]
        lines = [e.describe() + (" HIDDEN-COPY" if e.index in self.hidden else "") for e in vis[:limit]]
        if len(vis) > limit:
            lines.append("... %d more elements" % (len(vis) - limit))
        return lines


def new_messages(before: Sequence[str], screen: Screen, anchor: str,
                 exclude: Iterable[Optional[Element]] = (), seen: Iterable[str] = (),
                 confirm: Iterable[str] = (), before_user: Optional[Sequence[str]] = None) -> List[str]:
    return [e.text for e in new_message_elements(before, screen, anchor, exclude, seen, confirm, before_user)]


def _confirmed(text: str, confirm: Sequence[str]) -> bool:
    k = key(text)[:60]
    return bool(k) and any(k in c for c in confirm)


def new_message_elements(before: Sequence[str], screen: Screen, anchor: str,
                         exclude: Iterable[Optional[Element]] = (), seen: Iterable[str] = (),
                         confirm: Iterable[str] = (), before_user: Optional[Sequence[str]] = None) -> List[Element]:
    """Bot texts that appeared after the user's action.

    anchor: the text the user sent or the label they tapped. Its echo is found exactly (labels compared
    without iOS's trailing '.'), or by prefix only for a bubble on the user's side.
    - A fresh echo is on screen (more copies than before the action): everything below it is new, also a
      text seen earlier (a sub-menu with the same title as the main menu). A text seen earlier that sits
      below everything else is a hidden copy of an old bubble, unless the bot's evidence (confirm) has it.
    - Otherwise: what is on screen now minus what was there before, and a text already seen earlier in this
      conversation is never new (chat lists keep hidden copies of old bubbles: welcome, date separators).
    """
    exclude = list(exclude)
    msgs = screen.messages(exclude)
    old = {norm(t) for t in seen} | {norm(t) for t in before}
    conf = [key(t) for t in confirm]
    fresh = False
    if anchor:
        runs = anchor_hits(screen, msgs, anchor)
        if runs:
            low = max((r[-1] for r in runs), key=lambda m: m.y)
            mine = before if before_user is None else before_user  # the user's own bubbles before the action
            n = len([ln for ln in anchor.split("\n") if ln.strip()])
            if n <= 1:
                old_runs = sum(1 for t in mine if norm_label(t) == norm_label(anchor))
            else:
                lines = [norm_label(ln) for ln in anchor.split("\n") if ln.strip()]
                old_runs = sum(1 for i in range(len(mine) - n + 1) if [norm_label(t) for t in mine[i:i + n]] == lines)
            fresh = len(runs) > old_runs
            used = {m.index for r in runs for m in r}
            msgs = [m for m in msgs if m.y > low.y + 1 and m.index not in used]
    out: List[Element] = []
    if fresh:
        floor = min((x.y for x in exclude if x is not None), default=screen.height or 1e9)
        tappable = [e.y for e in screen.buttons(exclude) + screen.controls(exclude) + screen.actions(exclude)
                    if e.center[1] < floor]
        for i, m in enumerate(msgs):
            k = norm(m.text)
            if k in old and not _confirmed(m.text, conf):
                later = any(norm(x.text) not in old for x in msgs[i + 1:]) or any(y > m.y for y in tappable)
                if not later:
                    continue  # a trailing copy of an old bubble
            if not out or norm(out[-1].text) != k:  # the same bubble reported twice (wrapper + text)
                out.append(m)
        return out
    left = Counter(norm(t) for t in before)
    for m in msgs:
        k = norm(m.text)
        if k in old and not (anchor and _confirmed(m.text, conf) and left[k] <= 0):
            if left[k] > 0:
                left[k] -= 1
            continue
        if left[k] > 0:
            left[k] -= 1
            continue
        if not out or norm(out[-1].text) != k:
            out.append(m)
    return out


def group_options(new: List[Element], buttons: List[Element], boxes: Sequence[Element] = ()) -> List[List[Element]]:
    """Selectable rows without checkboxes: texts between the bot's question (first new text) and a disabled
    button below them (e.g. Continue). Texts on the same line, or inside the same cell (name above a masked
    number), form one row."""
    disabled = [b for b in buttons if not b.enabled]
    if len(new) < 2 or not disabled:
        return []
    below = [b.y for b in disabled if b.y > new[0].y + new[0].h - 1]
    if not below:
        return []
    limit = min(below)
    cand = sorted([e for e in new[1:] if e.y + e.h <= limit + 1], key=lambda e: (e.y, e.x))
    def box_of(e: Element) -> Optional[int]:
        inside = [b for b in boxes if b.index != e.index and b.contains(e) and not any(b.contains(n) for n in new[:1])]
        return min(inside, key=lambda b: b.w * b.h).index if inside else None

    # Without a cell around a row: lines at the same x stacked closer than the rows are spaced.
    pitches = [b.y - a.y for a, b in zip(cand, cand[1:]) if abs(a.x - b.x) <= 4 and b.y > a.y]
    p_min = min(pitches) if pitches else 0.0

    def stacked(prev: Element, e: Element) -> bool:
        pitch = e.y - prev.y
        return (prev.type == e.type == "text" and max(prev.h, e.h) <= 30 and abs(prev.x - e.x) <= 4
                and 0 < pitch <= 1.5 * min(prev.h, e.h) and pitch <= 1.3 * p_min and len(rows[-1]) < 3)

    rows: List[List[Element]] = []
    for e in cand:
        box = box_of(e)
        if rows and ((box is not None and box == box_of(rows[-1][0]))
                     or e.y < max(x.y + x.h for x in rows[-1]) - 4
                     or (box is None and stacked(rows[-1][-1], e))):
            rows[-1].append(e)
        else:
            rows.append([e])
    return rows
