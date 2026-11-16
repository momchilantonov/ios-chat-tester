"""Regression tests for the seventh real run (QA requirements R8-1 ... R8-7). Frames from the real app."""
import importlib.util
import os
import re
import unittest
from pathlib import Path

from helpers import Stack
from simchat.screen import Screen, anchor_hits, new_messages
from simchat.tester import _missing, _paragraphs
import test_install
from test_round3 import evidence

QUESTION = "Pick one of your cards, please."


def el(type_, label, x, y, w, h, depth, **kw):
    return dict({"type": type_, "label": label, "id": "", "value": "", "placeholder": "", "enabled": True,
                 "selected": False, "x": x, "y": y, "w": w, "h": h, "depth": depth}, **kw)


def real_screen():
    """The frames the QA report measured (390x844, nav bar bottom 91)."""
    return Screen({"app_state": "foreground", "screen": {"w": 390, "h": 844}, "elements": [
        el("navigationBar", "", 0, 0, 390, 91, 1),
        el("cell", "", 0, 60, 390, 40, 1),
        el("other", "start prompt", 126, 75, 224, 19, 2),               # the user's echo: ends 40pt from the edge
        el("cell", "", 0, 135, 390, 100, 1),
        el("image", "", 16, 200, 24, 24, 2, id="bot-avatar"),
        el("other", "Here are your cards.", 72, 145, 235, 77, 2),       # the bot's bubble next to its avatar
        el("cell", "", 0, 560, 390, 130, 1),
        el("text", "CARD NAME", 112, 576, 246, 17, 2),                  # a picker row: ends 32pt from the edge
        el("text", "CARD NAME 2", 112, 606, 246, 17, 2),
        el("button", "Continue", 20, 640, 350, 40, 2, enabled=False),   # ... in the same cell as Continue
    ]})


def labels(items):
    return [i.split("] ", 1)[1] for i in items]


class Round8Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _ask(self, text, **kw):
        self.t.send_message(text, **kw)
        return self.t.wait_for_reply()

    # R8-1 user side by structure ---------------------------------------------------------------------------
    def test_real_frames_user_side_by_structure(self):
        scr = real_screen()
        side = {e.text: scr.user_side(e) for e in scr.messages(covered=True)}
        self.assertEqual(side, {"start prompt": True, "Here are your cards.": False, "CARD NAME": False,
                                "CARD NAME 2": False})
        self.assertEqual(new_messages([], scr, "start prompt"), ["Here are your cards.", "CARD NAME", "CARD NAME 2"])
        self.assertEqual(anchor_hits(scr, scr.messages(covered=True), "CARD NAME"), [])  # a row is never the anchor
        scr.user_right = 350.0                                      # learned: rows (358) are not the user's
        self.assertFalse(scr.user_side(scr.elements[7]))

    def test_own_prompt_and_chip_echo_are_never_bot_text(self):
        self.app.real_layout = True
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self.assertEqual(self._ask("hello")["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertEqual(self._ask("confirm")["new_messages"], ["Block these cards?"])
        self.t.tap(text="Cancel")                                   # a chip: its echo is the user's
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Sorry, I did not understand: Cancel"])

    def test_reentry_reports_the_new_picker(self):
        self.app.real_layout = True
        self.app.echo_top = 40
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        first = self._ask("pick")
        self.assertEqual(first["new_messages"], ["Select the cards to block:"])
        self.assertEqual(labels(first["options"]), ["Visa ****1111", "Mastercard ****2222"])
        self.t.tap(text="Visa ****1111")
        self.t.tap(text="Продължи")
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Do you want to block the selected cards?"])
        self.t.tap(text="Cancel")
        self.t.wait_for_reply()
        again = self._ask("pick")
        self.assertEqual(again["new_messages"], ["Select the cards to block:"])
        self.assertEqual(labels(again["options"]), ["Visa ****1111", "Mastercard ****2222"])
        scr = self.t.screen()
        self.assertEqual(labels(scr["options"]), ["Visa ****1111", "Mastercard ****2222"])

    # R8-2 replies under the nav bar / banner ---------------------------------------------------------------
    def test_typed_card_name_reply_behind_the_banner(self):
        evidence(self.s)
        self.s.cfg["chat"]["ignore_labels"] = ["^Demo build$"]
        self.app.real_layout = True
        self.app.toast = "Demo build"
        self.app.echo_top = 40
        self.app.pick_rows = [["VISA CLASSIC", False], ["DEBIT MASTERCARD", False]]
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self._ask("pick")
        rep = self._ask("VISA CLASSIC", allow_button_text=True)
        self.assertEqual(rep["new_messages"], [QUESTION])
        self.assertEqual(labels(rep["options"]), ["VISA CLASSIC", "DEBIT MASTERCARD"])
        self.assertNotIn("evidence_texts_missing", rep)
        self.assertNotIn("note", rep)

    # R8-3 widget markup and loose numbers in the evidence check ---------------------------------------------
    def test_widget_markup_and_numbers_are_not_missing(self):
        paras = _paragraphs(["[SELECT Your points\n0.0 PTS]"])
        self.assertEqual(paras, ["Your points", "0.0 PTS"])
        self.assertEqual(_missing(paras, ["Your points", "0, PTS"]), [])
        self.assertEqual(_missing(paras, ["Your points"]), ["0.0 PTS"])         # a real gap is still reported
        self.assertEqual(_missing(["Total 12.50 EUR"], ["Total 12,5 EUR"]), [])

    # R8-4 keyboard focus right after a fresh launch ---------------------------------------------------------
    def test_first_message_after_a_fresh_launch(self):
        self.app.focus_delay = 1.5
        self.t.open_app(fresh=True)
        res = self.t.send_message("hello")
        self.assertTrue(res["confirmed"])
        self.assertEqual(self.app.received, [{"text": "hello"}])

    # R8-5 a bubble that turns into a hidden copy ------------------------------------------------------------
    def test_screen_rechecks_copies_that_became_hidden(self):
        self.app.band_pair = True                   # two overlapping texts above the composer, still real
        self._ask("hello")
        self.assertFalse([ln for ln in self.t.screen()["elements"] if "HIDDEN-COPY" in ln])
        self.app.band_hidden = True                 # same frames, now hidden copies
        scr = self.t.screen()
        hidden = [ln for ln in scr["elements"] if "HIDDEN-COPY" in ln]
        self.assertEqual(len(hidden), 2, scr["elements"])
        self.assertNotIn("Old echo", scr["messages"])


class LauncherPathTest(unittest.TestCase):
    """R8-6: paths compared after resolving symlinks (macOS: /var -> /private/var); R8-7: the planner's -p note."""

    def setUp(self):
        self.h = test_install.InstallTest("run_install")
        self.h.setUp()
        base = Path(self.h.tmp.name)
        self.link = base.parent / (base.name + "-link")
        os.symlink(str(base), str(self.link))                 # reach the clone through a symlink, as /var on macOS
        spec = importlib.util.spec_from_file_location("install_link", self.link / "clone" / "install.py")
        self.h.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.h.mod)

    def tearDown(self):
        os.unlink(str(self.link))
        self.h.tearDown()

    def test_launcher_paths_and_planner_note(self):
        code, out = self.h.run_install("--name", "my-tester", "--bundle-id", "com.example.App", "--yes")
        self.assertEqual(code, 0, out)
        bin_dir = self.link / "clone" / "tester" / "bin"
        launcher = (bin_dir / "my-tester").read_text()
        found = re.search(r"--additional-mcp-config=@'?([^' ]+)", launcher).group(1)
        self.assertEqual(Path(found).resolve(), (bin_dir / "mcp-config.json").resolve())
        planner = (bin_dir / "my-tester-planner").read_text()
        self.assertIn("cannot save", planner)
        self.assertNotIn("cannot save", launcher)


if __name__ == "__main__":
    unittest.main()
