"""Regression tests for the sixth real run (QA requirements R7-1 ... R7-7)."""
import re
import subprocess
import unittest

from helpers import ROOT, Stack
from simchat.plan import lint_plan, parse_plan
from simchat.tester import ToolError
import test_install
from test_round3 import evidence

CARDS = [["VISA CLASSIC", False], ["DEBIT MASTERCARD", False]]
QUESTION = "Pick one of your cards, please."


def labels(items):
    return [i.split("] ", 1)[1] for i in items]


class Round7Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _ask(self, text, **kw):
        self.t.send_message(text, **kw)
        return self.t.wait_for_reply()

    # R7-1 the user's echo under the nav bar / banner ---------------------------------------------------------
    def test_reentry_with_the_echo_under_the_nav_bar(self):
        self.app.echo_top = 40                      # the app scrolls the user's bubble under the nav bar
        first = self._ask("pick")
        self.assertEqual(first["new_messages"], ["Select the cards to block:"])
        self.t.tap(text="Visa ****1111")
        self.t.tap(text="Продължи")
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Do you want to block the selected cards?"])
        self.t.tap(text="Cancel")
        self.t.wait_for_reply()
        again = self._ask("pick")                   # the same start prompt again: the picker is new
        self.assertEqual(again["new_messages"], ["Select the cards to block:"])
        self.assertEqual(labels(again["options"]), ["Visa ****1111", "Mastercard ****2222"])

    def test_typed_option_name_with_the_reply_behind_a_banner(self):
        evidence(self.s)
        self.s.cfg["chat"]["ignore_labels"] = ["^Demo build$"]
        self.app.toast = "Demo build"               # a banner under the nav bar (y 95-145)
        self.app.echo_top = 40
        self.app.rows_right = True                  # picker rows right of the middle, not at the right edge
        self.app.pick_rows = CARDS
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        first = self._ask("pick")
        self.assertEqual(first["new_messages"], ["Select the cards to block:"])
        rep = self._ask("VISA CLASSIC", allow_button_text=True)
        self.assertEqual(rep["new_messages"], [QUESTION])   # read by scrolling, never the picker row as anchor
        self.assertEqual(labels(rep["options"]), ["VISA CLASSIC", "DEBIT MASTERCARD"])
        self.assertNotIn("evidence_texts_missing", rep)
        self.assertNotIn("app_alerts", rep)                  # the ignored demo banner is no alert

    # R7-2 picker submit -----------------------------------------------------------------------------------
    def test_submit_reports_only_the_confirm_question(self):
        self.app.rows_as_text = True
        self.app.submit_echo = True                 # a 4-line echo: name and number of both cards
        self.app.nav_caption = True                 # a hidden submit button + caption appear near the bar
        self.app.echo_top = 40
        self._ask("pick")
        self.t.tap(text="Visa")
        self.t.tap(text="Mastercard")
        res = self.t.tap(text="Продължи")
        self.assertNotIn("tap_mismatch", res)
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Do you want to block the selected cards?"])
        self.assertEqual(labels(rep["buttons"]), ["Confirm", "Cancel"])

    # R7-3 a ghost with many copies ------------------------------------------------------------------------
    def test_ghost_of_a_frequent_emoji_text_is_marked(self):
        self.app.ghost_band = True
        self.app.offscreen_copies = 13              # more copies than the old driver looked at (12)
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self.assertEqual(self._ask("anything")["new_messages"], ["Anything else I can do for you? 😊"])
        self.assertEqual(self._ask("hello")["new_messages"], ["Hi! I can help with cards and payments."])
        scr = self.t.screen()
        ghosts = [ln for ln in scr["elements"] if "Anything else" in ln and "HIDDEN-COPY" in ln]
        self.assertEqual(len(ghosts), 1, scr["elements"])
        self.assertLessEqual(scr["messages"].count("Anything else I can do for you? 😊"), 1)

    # R7-4 dialog after wait_for_reply ---------------------------------------------------------------------
    def test_dialog_stays_an_alert_after_wait_for_reply(self):
        self._ask("hello")
        self.app.dialog = True
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["app_alerts"][-1]["kind"], "dialog")
        scr = self.t.screen()                        # later: still the dialog, not chat text
        dlg = scr["app_alerts"][-1]
        self.assertEqual(dlg["kind"], "dialog")
        self.assertNotIn("Are you sure you want to end the conversation?", scr["messages"])
        with self.assertRaises(ToolError) as ctx:
            self.t.send_message("hello")
        msg = str(ctx.exception)
        for part in ("dialog", "Are you sure", "Yes", "No", "tap"):
            self.assertIn(part, msg)
        self.t.tap(text="No")
        self.assertIsNotNone(self.t.screen()["composer"])

    # R7-5 planner ----------------------------------------------------------------------------------------
    def test_planner_example_passes_the_plan_check(self):
        text = (ROOT / "templates" / "planner.md").read_text(encoding="utf-8")
        plan = parse_plan(re.search(r"<!-- plan2 -->\s*```markdown\n(.*?)```", text, re.S).group(1))
        self.assertEqual(lint_plan(plan), [])
        prompts = [r["prompt"] for r in plan["rows"]]
        self.assertIn("type: VISA CLASSIC", prompts)
        self.assertIn("warnings", text)

    def test_plan_check_flags_positional_disabled_and_missing_branches(self):
        bad = parse_plan("\n".join([
            "## Conversation 1: picker", "| Flow | User prompt | Expected | Result |", "|---|---|---|---|",
            "| f | I want to block a card | the card list | |",
            "| f | select first row | selected | |",
            "| f | tap Continue with empty selection | re-prompt | |"]))
        warnings = " ".join(lint_plan(bad))
        for part in ("not by position", "disabled control", "type:", "re-entry"):
            self.assertIn(part, warnings)

    # R7-6 stale controls ----------------------------------------------------------------------------------
    def test_answered_continue_is_not_a_current_button(self):
        self.app.answered_buttons = True            # answered buttons stay in the history, disabled
        self._ask("pick")
        self.t.tap(text="Visa ****1111")
        self.t.tap(text="Продължи")
        rep = self.t.wait_for_reply()
        self.assertEqual(labels(rep["buttons"]), ["Confirm", "Cancel"])
        self.assertTrue(any("Продължи" in b for b in rep["stale_buttons"]))
        scr = self.t.screen()
        self.assertFalse([b for b in scr["buttons"] if "Продължи" in b])

    def test_picker_rows_are_options_in_screen_not_messages(self):
        self.app.rows_as_text = True
        self._ask("pick")
        for selected in (False, True):
            scr = self.t.screen()
            self.assertEqual(labels(scr["options"]), ["Visa · ****1111", "Mastercard · ****2222"])
            self.assertFalse({"Visa", "****1111", "Mastercard", "****2222"} & set(scr["messages"]))
            self.assertIn("Select the cards to block:", scr["messages"])
            if not selected:
                self.t.tap(text="Visa")             # Continue becomes enabled: the rows are still options


class LauncherTest(unittest.TestCase):
    """R7-7: the launcher brings its own MCP config and says clearly what -p means."""

    def setUp(self):
        self.h = test_install.InstallTest("run_install")  # its temp copy of the repo, not its tests
        self.h.setUp()
        self.clone, self.app_repo = self.h.clone, self.h.app_repo

    def tearDown(self):
        self.h.tearDown()

    def test_launcher_passes_the_mcp_config(self):
        code, out = self.h.run_install("--name", "my-tester", "--bundle-id", "com.example.App", "--app-repo",
                                     str(self.app_repo), "--yes")
        self.assertEqual(code, 0, out)
        launcher = (self.clone / "tester" / "bin" / "my-tester").read_text()
        cfg = self.clone / "tester" / "bin" / "mcp-config.json"
        self.assertIn("--additional-mcp-config=@%s" % cfg, launcher)
        self.assertIn("simchat", cfg.read_text())
        res = subprocess.run(["bash", "-n", str(self.clone / "tester" / "bin" / "my-tester")], capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        note = [ln for ln in launcher.splitlines() if "echo" in ln]
        self.assertEqual(len(note), 1)
        self.assertIn("run without -p", launcher)


if __name__ == "__main__":
    unittest.main()
