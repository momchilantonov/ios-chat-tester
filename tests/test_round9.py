"""Regression tests for the eighth real run (QA requirements R9-1 ... R9-5)."""

import json
import unittest
from pathlib import Path

import test_install
from helpers import ROOT, Stack
from simchat import driver
from simchat.screen import Screen
from simchat.tester import _missing, _paragraphs
from test_round3 import evidence
from test_round8 import el


def labels(items):
    return [i.split("] ", 1)[1] for i in items]


class Round9Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _ask(self, text, **kw):
        self.t.send_message(text, **kw)
        return self.t.wait_for_reply()

    # R9-1 re-entering a finished flow -----------------------------------------------------------------------
    def test_reentry_after_a_finished_flow(self):
        for with_evidence in (False, True):
            with self.subTest(evidence=with_evidence):
                self.s.close()
                self.setUp()
                if with_evidence:
                    evidence(self.s)
                self.app.real_layout = True
                self.app.keep_rows = True  # the answered picker stays in the history (same caption, rows)
                self.app.answered_buttons = True
                # two copies of the latest echo, same frame, low on screen
                self.app.echo_twins = True
                self.t.open_app(fresh=True)
                self.t.wait_for_reply()
                self._ask("pick")
                self.t.tap(text="Visa ****1111")
                self.t.tap(text="Продължи")
                self.t.wait_for_reply()
                self.t.tap(text="Cancel")
                self.t.wait_for_reply()  # the flow is finished
                # the same start prompt: a new picker, same texts as before
                again = self._ask("pick")
                self.assertEqual(again["new_messages"], ["Select the cards to block:"])
                self.assertEqual(
                    labels(again["options"]), ["Visa ****1111", "Mastercard ****2222"]
                )
                self.assertNotIn("note", again)

    # R9-2 widget markup without text ------------------------------------------------------------------------
    def test_empty_widget_markup_expects_no_text(self):
        self.assertEqual(_paragraphs(["[CHECKBOX None | None | None | None]"]), [])
        self.assertEqual(
            _paragraphs(["Choose your cards:\n[CHECKBOX None | None]"]),
            ["Choose your cards:"],
        )
        self.assertEqual(
            _paragraphs(["[CHECKBOX VISA CLASSIC | None]"]), ["VISA CLASSIC"]
        )
        # markup cut across items
        self.assertEqual(_missing(_paragraphs(["[CHECKBOX None | None"]), []), [])

    # R9-3 two ghost copies at exactly the same frame -------------------------------------------------------
    def test_identical_twin_copies_are_hidden_copy_candidates(self):
        scr = Screen(
            {
                "app_state": "foreground",
                "screen": {"w": 390, "h": 844},
                "elements": [
                    el(
                        "other", "start prompt", 1, 716, 220, 40, 1
                    ),  # two unrelated copies, same frame
                    el("other", "start prompt", 1, 716, 220, 40, 1),
                    el(
                        "other", "Hello", 72, 300, 235, 40, 1
                    ),  # a wrapper and its own text: no copy
                    el("text", "Hello", 72, 300, 235, 40, 2),
                ],
            }
        )
        self.assertEqual([e.index for e in scr.overlapping()], [0, 1])

    def test_twin_ghosts_of_the_echo_are_marked(self):
        self.app.echo_twins = True
        self._ask("hello")
        scr = self.t.screen()
        twins = [
            ln for ln in scr["elements"] if "'hello'" in ln and "HIDDEN-COPY" in ln
        ]
        self.assertEqual(len(twins), 2, scr["elements"])

    # R9-4 the user's own texts in screen() ------------------------------------------------------------------
    def test_screen_marks_the_users_own_messages(self):
        self._ask("hello")
        msgs = self.t.screen()["messages"]
        self.assertIn("you: hello", msgs)
        self.assertIn("Hi! I can help with cards and payments.", msgs)
        self.assertFalse([m for m in msgs if m.startswith("you: Hi!")])


class DriverStateTest(unittest.TestCase):
    """R9-5: the unit tests never touch the real driver's state file; install.py stops only its own clone's."""

    def test_tests_use_a_sandbox_state_file(self):
        self.assertFalse(
            str(driver.STATE_FILE).startswith(str(ROOT)), driver.STATE_FILE
        )

    def test_uninstall_stops_only_its_own_clone_driver(self):
        h = test_install.InstallTest("run_install")
        h.setUp()
        try:
            h.run_install("--bundle-id", "a.b")
            state = h.clone / "tester" / "driver" / ".build" / "driver.json"
            state.parent.mkdir(parents=True, exist_ok=True)
            # nothing listens on port 1
            state.write_text(json.dumps({"pid": 0, "port": 1, "token": "x"}))
            _code, out = h.run_install("--uninstall", "--force")
            self.assertIn("stop     the UI driver process", out)
            # the clone's own stop_driver ran (in its own process)
            self.assertFalse(state.exists())
            self.assertEqual(Path(h.mod.DRIVER_STATE).resolve(), state.resolve())
        finally:
            h.tearDown()


if __name__ == "__main__":
    unittest.main()
