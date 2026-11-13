"""Regression tests for the fifth real run (QA requirements R6-1 ... R6-9)."""
import os
import re
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, Stack
from simchat.plan import parse_plan
from simchat.screen import Screen, group_options, new_messages
from simchat.tester import ToolError
from test_round3 import evidence
from test_round5 import raw


class Round6Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _ask(self, text, **kw):
        self.t.send_message(text)
        return self.t.wait_for_reply(**kw)

    # R6-1 hidden copies ------------------------------------------------------------------------------------
    def test_ghost_band_never_counts(self):
        self.app.ghost_band = True                  # stacked, overlapping, not hittable copies of old texts
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self.assertEqual(self._ask("hello")["new_messages"], ["Hi! I can help with cards and payments."])
        self.t.tap(text="Cards")
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Which card?"])
        rep = self._ask("hello")                    # the identical prompt again -> the identical reply
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        scr = self.t.screen()
        self.assertTrue(any("HIDDEN-COPY" in ln for ln in scr["elements"]))
        self.assertEqual(scr["messages"][-1], "Hi! I can help with cards and payments.")

    # R6-2 anchor only on the user's own bubble --------------------------------------------------------------
    def test_anchor_is_never_an_option_row(self):
        scr = Screen(raw({"label": "Visa Classic", "x": 250, "y": 200, "w": 120},     # the user's message
                         {"label": "You chose:", "x": 10, "y": 260},
                         {"label": "Visa Classic", "x": 16, "y": 320, "h": 20},       # a picker row, lower
                         {"label": "**** 1234", "x": 16, "y": 342, "h": 20}))
        self.assertEqual(new_messages([], scr, "Visa Classic"), ["You chose:", "Visa Classic", "**** 1234"])

    # R6-3 submit echo listing the selected rows -------------------------------------------------------------
    def test_submit_echo_with_selected_rows_is_no_mismatch(self):
        self.app.rows_as_text = True                # rows = two texts (name, number), no cells
        self.app.submit_echo = True                 # "Продължи" echoes the selected cards, one line each
        self._ask("pick")
        self.t.tap(text="Visa")
        self.t.tap(text="Mastercard")
        res = self.t.tap(text="Продължи")
        self.assertNotIn("tap_mismatch", res)
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Do you want to block the selected cards?"])

    # R6-4 the whole reply ----------------------------------------------------------------------------------
    def test_wait_until_every_paragraph_is_drawn(self):
        evidence(self.s)
        self.app.late_delay = 3.0                   # the 2nd bubble appears 3 s after the 1st
        rep = self._ask("two", timeout_s=10)
        self.assertEqual(rep["new_messages"], ["The first part of the answer.", "The second part of the answer."])
        self.assertNotIn("evidence_texts_missing", rep)

    # R6-5 options without cells ----------------------------------------------------------------------------
    def test_stacked_lines_without_cells_form_options(self):
        q = raw({"label": "Which cards?", "x": 10, "y": 230, "h": 20},
                {"label": "CARD NAME", "x": 20, "y": 272, "h": 18}, {"label": "4000****4321", "x": 20, "y": 292, "h": 18},
                {"label": "CARD NAME", "x": 20, "y": 324, "h": 18}, {"label": "4000****1234", "x": 20, "y": 344, "h": 18},
                {"type": "button", "label": "Continue", "x": 20, "y": 400, "enabled": False})
        scr = Screen(q)
        new = scr.messages()
        rows = group_options(new, scr.buttons())
        self.assertEqual([[e.text for e in r] for r in rows], [["CARD NAME", "4000****4321"],
                                                               ["CARD NAME", "4000****1234"]])

    # R6-6 ambiguous tap ------------------------------------------------------------------------------------
    def test_same_label_with_different_details_is_refused(self):
        self.app.rows_as_text = True
        self.app.pick_rows = [["Debit ****1111", False], ["Debit ****2222", False]]
        self._ask("pick")
        n = len([c for c in self.app.commands if c[0] == "tap"])
        with self.assertRaises(ToolError) as ctx:
            self.t.tap(text="Debit")
        amb = ctx.exception.details["ambiguous"]
        self.assertEqual([a.split("] ")[1] for a in amb], ["Debit · ****1111", "Debit · ****2222"])
        self.assertEqual(len([c for c in self.app.commands if c[0] == "tap"]), n)
        self.t.tap(text="Debit · ****2222")         # label + detail picks the row
        self.assertEqual([r[1] for r in self.app.rows], [False, True])

    # R6-7 planner and symlinked sources ---------------------------------------------------------------------
    def test_planner_example_blocks_the_confirm_and_covers_rejections(self):
        text = (ROOT / "templates" / "planner.md").read_text(encoding="utf-8")
        rows = parse_plan(re.search(r"<!-- plan2 -->\s*```markdown\n(.*?)```", text, re.S).group(1))["rows"]
        blocked = [r for r in rows if r["result"]]
        self.assertEqual([(r["prompt"], r["result"]) for r in blocked],
                         [("tap Confirm", "blocked: state-changing - needs operator OK")])
        prompts = [r["prompt"] for r in rows]
        for p in ("tap Cancel", "none of them", "blabla", "no"):
            self.assertIn(p, prompts)
        self.assertFalse([p for p in prompts if "first" in p])   # picker rows by visible text
        self.assertIn("--add-dir", text)

    def test_launcher_adds_symlink_targets(self):
        import sys
        sys.path.insert(0, str(ROOT))
        import install
        with tempfile.TemporaryDirectory() as tmp:
            repo, docs = Path(tmp) / "bot", Path(tmp) / "docs-checkout" / "guides"
            (repo / ".github").mkdir(parents=True)
            docs.mkdir(parents=True)
            os.symlink(str(docs), str(repo / ".github" / "docs"))
            found = install._symlink_targets([str(repo)])
        self.assertEqual([t for t, _ in found], [str(docs.resolve())])

    # R6-8 in-app dialog ------------------------------------------------------------------------------------
    def test_dialog_is_an_app_alert_not_chat(self):
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self.app.dialog = True
        scr = self.t.screen()
        dlg = scr["app_alerts"][-1]
        self.assertEqual(dlg["kind"], "dialog")
        self.assertEqual(dlg["texts"], ["Are you sure you want to end the conversation?"])
        self.assertEqual([b.split("] ")[1] for b in dlg["buttons"]], ["Yes", "No"])
        self.assertNotIn("Are you sure you want to end the conversation?", scr["messages"])
        with self.assertRaises(ToolError) as ctx:
            self.t.send_message("hello")
        self.assertIn("dialog", str(ctx.exception))
        self.t.tap(text="No")
        self.assertIsNotNone(self.t.screen()["composer"])

    # R6-9 under the navigation bar -------------------------------------------------------------------------
    def test_element_under_the_nav_bar_is_not_listed(self):
        self.app.nav_ghost = True
        self._ask("hello")
        scr = self.t.screen()
        self.assertFalse([b for b in scr["buttons"] if "Continue" in b])
        self.assertIn("Assistant", " ".join(scr["elements"]))       # the bar's own title is still there


if __name__ == "__main__":
    unittest.main()
