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
EDGE_TOLERANCE_PT = 4.0  # the user's right-aligned bubbles all end at the same x (learned from a sent message)
AVATAR_RX = re.compile(r"avatar", re.IGNORECASE)
BAR_SLACK_PT = 2.0    # an element whose centre is this close below a bar's bottom edge still counts as under it
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
        self.user_right: Optional[float] = None  # right edge of the user's bubbles, once learned (set by the tester)
        self._parent: Dict[int, Optional[int]] = {}
        if len({e.depth for e in self.elements}) > 1:  # the snapshot's tree: each element's nearest listed ancestor
            stack: List[Element] = []
            for e in self.elements:
                while stack and stack[-1].depth >= e.depth:
                    stack.pop()
                self._parent[e.index] = stack[-1].index if stack else None
                stack.append(e)
        self._cell_cache: Dict[int, Optional[Element]] = {}
        on = [e for e in self.elements if self.on_screen(e)]
        self._shown = [e for e in on if not self._under_chrome(e)]
        self._covered = [e for e in on if self._under_chrome(e)]  # under the nav bar or a top banner
        self._covered_idx = {e.index for e in self._covered}
        self._bubbles = [c for c in self.elements if c.type in ("other", "cell")
                         and (not self.width or c.w < 0.9 * self.width)]

    # -- geometry -------------------------------------------------------------------------------
    def cell_of(self, e: Element) -> Optional[Element]:
        """The list cell that holds e (e itself if it is a cell): by the snapshot tree, else the smallest
        cell whose frame contains it."""
        if e.index in self._cell_cache:
            return self._cell_cache[e.index]
        cell: Optional[Element] = None
        if self._parent:
            i: Optional[int] = e.index
            while i is not None:
                if self.elements[i].type == "cell":
                    cell = self.elements[i]
                    break
                i = self._parent.get(i)
        else:
            boxes = [c for c in self.elements if c.type == "cell" and (c.index == e.index or c.contains(e))]
            cell = min(boxes, key=lambda c: c.w * c.h) if boxes else None
        self._cell_cache[e.index] = cell
        return cell

    def _in_cell(self, cell: Element) -> List[Element]:
        if self._parent:
            out = []
            for o in self.elements[cell.index + 1:]:
                if o.depth <= cell.depth:
                    break
                out.append(o)
            return out
        return [o for o in self.elements if o.index != cell.index and cell.contains(o)]

    def bot_cell(self, cell: Element) -> bool:
        """A cell with the bot's avatar (an image at the left or with "avatar" in its id), or with a button (a
        picker with its Continue, quick replies): never the user's own bubble."""
        for o in self._in_cell(cell):
            if o.type == "image" and (AVATAR_RX.search(o.id or o.label or "")
                                      or (self.width and o.center[0] < self.width * 0.2)):
                return True
            if o.type == "button":
                return True
        return False

    def right_edge(self, e: Element) -> float:
        """Right edge of e's bubble: e itself, or a tight wrapper around it (a text inside its bubble)."""
        right = e.x + e.w
        for c in self._bubbles:
            if c.index != e.index and c.w <= e.w + 80 and c.contains(e):
                right = max(right, c.x + c.w)
        return right

    def user_side(self, e: Element) -> bool:
        """The user's own bubbles (and tap echoes). Decided by structure first: a text in a cell that also holds
        the bot's avatar or a button (a picker row next to its Continue) is never the user's. Then: right half of
        the screen; and once the right edge of the user's bubbles is known (learned from a sent message), the
        bubble must end there - picker rows and wide bot bubbles end elsewhere."""
        if not self.width or e.x <= self.width * 0.12 or e.x + e.w / 2 <= self.width * 0.5:
            return False
        cell = self.cell_of(e)
        if cell is not None and self.bot_cell(cell):
            return False
        if self.user_right is not None:
            return abs(self.right_edge(e) - self.user_right) <= EDGE_TOLERANCE_PT
        return True

    def covered(self, e: Element) -> bool:
        """On screen but under the navigation bar or a top banner: the user can't read it."""
        return e.index in self._covered_idx

    def shift_from(self, before: "Screen") -> Optional[float]:
        """How far the chat moved since `before` (points, negative = up): the most common move of the message
        texts that occur exactly once in each whole snapshot (off-screen copies count: a new picker with the same
        caption as an old one is no match). Possible ghost copies are left out - they don't scroll. None when
        the screens share no such text."""
        def uniq(scr: "Screen") -> Dict[tuple, Element]:
            if getattr(scr, "_uniq", None) is None:
                def k(e: Element) -> tuple:
                    return (e.type, norm(e.text), round(e.x), round(e.w), round(e.h))
                total = Counter(k(e) for e in scr.elements if e.text)
                suspects = {e.index for e in scr.overlapping()}
                scr._uniq = {k(m): m for m in scr.messages(covered=True)
                             if m.index not in suspects and total[k(m)] == 1}
            return scr._uniq
        a, b = uniq(before), uniq(self)
        moves = [b[k].y - a[k].y for k in a if k in b]
        if not moves:
            return None
        votes = Counter(round(m / 2.0) for m in moves)  # real bubbles all move by the same amount
        best, n = votes.most_common(1)[0]
        if n == 1 and len(moves) > 2:
            moves.sort()
            return moves[len(moves) // 2]
        return sum(m for m in moves if round(m / 2.0) == best) / n

    def on_screen(self, e: Element) -> bool:
        if not self.width or not self.height:
            return True
        cx, cy = e.center
        return 0 <= cx <= self.width and 0 <= cy <= self.height

    def visible(self, covered: bool = False) -> List[Element]:
        """On screen, not under the navigation bar or a top banner (unless covered=True), not a hidden copy."""
        pool = sorted(self._shown + self._covered, key=lambda e: e.index) if covered else self._shown
        return [e for e in pool if e.index not in self.hidden]

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
            if bar.x <= cx <= bar.x + bar.w and cy < bar.y + bar.h + BAR_SLACK_PT:
                return True
        return False

    def overlapping(self) -> List[Element]:
        """Texts and buttons whose frames overlap another one's (not parent/child, not a wrapper with the same
        text). Real bubbles never overlap; stacked hidden copies of old bubbles do."""
        if getattr(self, "_overlapping", None) is not None:
            return self._overlapping
        els = [e for e in self._shown if e.text and e.type in TEXT_TYPES + BUTTON_TYPES and not self.is_noise(e)]
        out = set()
        for i, a in enumerate(els):
            for b in els[i + 1:]:
                area = a.overlap(b)
                if area <= 0 or area < 0.25 * min(a.w * a.h, b.w * b.h):
                    continue
                if a.same_frame(b):
                    # a wrapper repeating its child's text is no copy; two unrelated elements with the same text
                    # at the same frame are (two ghost copies of an old echo, stacked exactly)
                    if norm(a.text) == norm(b.text) and (not self._parent or self.related(a, b)):
                        continue
                elif a.contains(b) or b.contains(a):
                    continue
                out.update((a.index, b.index))
        self._overlapping = [e for e in els if e.index in out]
        return self._overlapping

    def related(self, a: Element, b: Element) -> bool:
        """One is the other's ancestor in the snapshot tree."""
        for x, y in ((a, b), (b, a)):
            i = self._parent.get(y.index)
            while i is not None:
                if i == x.index:
                    return True
                i = self._parent.get(i)
        return False

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

    def _all_buttons(self) -> List[Element]:
        """Every button on screen - also hidden copies and buttons under a bar: their captions are no content."""
        return [b for b in self._shown + self._covered if b.type in BUTTON_TYPES]

    def _covered_by_button(self, e: Element) -> bool:
        """A text drawn on a button (same label, overlapping frame) is the button's caption, not content."""
        k = norm_label(e.text)
        for b in self._all_buttons():
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

    def _message_candidates(self, exclude: Iterable[Optional[Element]] = (), covered: bool = False) -> List[Element]:
        excluded = [x for x in exclude if x is not None]
        skip = {x.index for x in excluded}
        buttons = self._all_buttons()  # a text inside any button frame (hidden or not) is its caption
        chrome = [e for e in self.visible() if e.type in CHROME_TYPES]
        overlays = self._overlays()
        return [e for e in self.visible(covered)
                if e.type in TEXT_TYPES and e.text.strip() and e.index not in skip
                and not self.is_noise(e)
                and not self._inside_any(e, excluded)          # e.g. a custom placeholder label in the composer
                and not self._inside_any(e, self.carousels())  # carousel cards are reported separately
                and not any(b.index != e.index and b.contains(e) for b in buttons)
                and not self._covered_by_button(e)
                and (self.covered(e) or not any(c.contains(e) for c in chrome))  # covered: not part of the bar
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

    def messages(self, exclude: Iterable[Optional[Element]] = (), covered: bool = False) -> List[Element]:
        """Text-bearing elements top to bottom, without inputs, button captions, action cards and wrapper
        duplicates. covered=True adds the ones under the navigation bar or a top banner: they can be the user's
        own bubble (an anchor), but are never reported as messages."""
        exclude = list(exclude)
        acts = self.actions(exclude)
        cands = [e for e in self._message_candidates(exclude, covered) if not any(a.contains(e) for a in acts)]
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

    def _overlays(self) -> List[Element]:
        return [e for e in self.visible() if e.type in ALERT_TYPES
                or (e.type in ("other", "text") and e.id and BANNER_RX.search(e.id))]

    def app_alert_elements(self) -> List[Element]:
        """In-app alerts, action sheets and banners/toasts (the system's own alerts are in self.alerts); a banner
        matching chat.ignore_labels (a demo-build banner) is not reported."""
        return [e for e in self._overlays() if not self.is_noise(e)]

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
                 confirm: Iterable[str] = (), before_user: Optional[Sequence[str]] = None,
                 own: Sequence[str] = ()) -> List[str]:
    return [e.text for e in new_message_elements(before, screen, anchor, exclude, seen, confirm, before_user, own)
            if not screen.covered(e)]


def _confirmed(text: str, confirm: Sequence[str]) -> bool:
    k = key(text)[:60]
    return bool(k) and any(k in c for c in confirm)


def _own_floor(screen: Screen, msgs: List[Element], own: Sequence[str], mine: Sequence[str]) -> Optional[Element]:
    """The lowest new bubble on the user's side that shows what the user just sent, tapped or selected (e.g. the
    echo of a picker submit, one line per chosen row) - also when the anchor itself is not found."""
    owns = {key(t) for t in own if key(t)}
    left = Counter(norm(t) for t in mine)
    found = []
    for m in msgs:
        if not screen.user_side(m) or key(m.text) not in owns:
            continue
        if left[norm(m.text)] > 0:
            left[norm(m.text)] -= 1  # the same text was on the user's side before the action
            continue
        found.append(m)
    return max(found, key=lambda m: m.y) if found else None


def new_message_elements(before: Sequence[str], screen: Screen, anchor: str,
                         exclude: Iterable[Optional[Element]] = (), seen: Iterable[str] = (),
                         confirm: Iterable[str] = (), before_user: Optional[Sequence[str]] = None,
                         own: Sequence[str] = (), newest_is_echo: bool = False) -> List[Element]:
    """Bot texts that appeared after the user's action. The result can contain elements under the navigation bar
    or a top banner (screen.covered): the caller must not report them as read.

    anchor: the text the user sent or the label they tapped. Its echo is found exactly (labels compared
    without iOS's trailing '.'), or by prefix, only on the user's side - also under a bar (after sending, chat
    lists often scroll the user's bubble to the top).
    - A fresh echo is on screen (more copies than the user's side had before the action): everything below it
      is new, also a text seen earlier (a sub-menu with the same title as the main menu). A text seen earlier
      that sits below everything else is a hidden copy of an old bubble, unless the bot's evidence (confirm)
      has it.
    - newest_is_echo (the bot's evidence already has the reply, so the user's bubble is drawn): the lowest copy
      is the echo even if copies of the same text were there before (re-entering a flow with its start prompt).
    - No fresh echo, but a new bubble on the user's side shows one of `own` (the lines of the user's action,
      the rows selected before a submit): it counts as the echo.
    - Otherwise: what is on screen now minus what was there before, and a text already seen earlier in this
      conversation is never new (chat lists keep hidden copies of old bubbles: welcome, date separators).
    """
    exclude = list(exclude)
    every = screen.messages(exclude, covered=True)
    msgs = every
    old = {norm(t) for t in seen} | {norm(t) for t in before}
    conf = [key(t) for t in confirm]
    fresh = False
    mine = before if before_user is None else before_user  # the user's own bubbles before the action
    if anchor:
        runs = anchor_hits(screen, every, anchor)
        if runs:
            low = max((r[-1] for r in runs), key=lambda m: m.y)
            n = len([ln for ln in anchor.split("\n") if ln.strip()])
            if n <= 1:
                old_runs = sum(1 for t in mine if norm_label(t) == norm_label(anchor))
            else:
                lines = [norm_label(ln) for ln in anchor.split("\n") if ln.strip()]
                old_runs = sum(1 for i in range(len(mine) - n + 1) if [norm_label(t) for t in mine[i:i + n]] == lines)
            fresh = len(runs) > old_runs or newest_is_echo
            used = {m.index for r in runs for m in r}
            msgs = [m for m in every if m.y > low.y + 1 and m.index not in used]
        if not fresh and own:
            floor = _own_floor(screen, every, list(own) + anchor.split("\n"), mine)
            if floor is not None:
                owns = {key(t) for t in own}
                fresh = True
                msgs = [m for m in every if m.y > floor.y + 1 and not (screen.user_side(m) and key(m.text) in owns)]
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
        # a row's own box: not one that also holds the question or a button (that is the whole picker - the real
        # app puts every row and the Continue button into one cell)
        inside = [b for b in boxes if b.index != e.index and b.contains(e) and not any(b.contains(n) for n in new[:1])
                  and not any(b.contains(x) for x in buttons)]
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
