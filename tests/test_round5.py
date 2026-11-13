"""Regression tests for the fourth real run (QA requirements R5-1 ... R5-11)."""
import json
import re
import unittest

from helpers import ROOT, Stack
from simchat.plan import parse_plan
from simchat.screen import Screen, new_messages
from simchat.tester import ToolError
from test_round3 import evidence

FAQ = ["Paragraph %d of the long answer explains one more aspect of the topic in enough words to need several "
       "lines on a phone screen." % i for i in range(1, 6)]


def raw(*els):
    full = []
    for i, e in enumerate(els):
        full.append(dict({"type": "text", "id": "", "value": "", "placeholder": "", "enabled": True,
                          "selected": False, "w": 200, "h": 40}, **e))
    return {"app_state": "foreground", "screen": {"w": 390, "h": 844}, "elements": full}


class Round5Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _ask(self, text):
        self.t.send_message(text)
        return self.t.wait_for_reply()

    # R5-1 tap lands on another button --------------------------------------------------------------
    def test_hidden_copy_is_not_tapped(self):
        self.app.hidden_copy = "Overdraft"          # invisible old copy drawn over the "Credit card" row
        self._ask("products")
        res = self.t.tap(text="Overdraft")
        self.assertEqual(self.app.received[-1], {"payload": "/overdraft"})
        self.assertEqual(res.get("skipped_hidden_copies"), 1, res)
        self.assertNotIn("tap_mismatch", res)

    def test_wrong_echo_is_a_tap_mismatch(self):
        self.app.hidden_copy = "Overdraft"
        self.app.no_hittable = True                 # an old driver: the hidden copy is picked
        self._ask("products")
        res = self.t.tap(text="Overdraft")
        self.assertEqual(self.app.received[-1], {"payload": "/credit card"})
        self.assertEqual(res["tap_mismatch"], {"asked": "Overdraft", "sent": "Credit card"})
        self.assertIn("INVALID", res["warning"])
        rep = self.t.wait_for_reply()               # the reply belongs to what was really sent
        self.assertEqual(rep["new_messages"], ["Sorry, I did not understand: Credit card"])

    def test_hidden_copy_by_index_is_refused(self):
        self.app.hidden_copy = "Overdraft"
        self._ask("products")
        listing = self.t.screen()["elements"]
        hidden = [ln for ln in listing if "'Overdraft'" in ln and "button" in ln]
        low = max(hidden, key=lambda ln: int(re.search(r",(\d+)\)", ln).group(1)))
        n = len(self.app.received)
        with self.assertRaises(ToolError) as ctx:
            self.t.tap(element=int(re.match(r"\[(\d+)\]", low).group(1)))
        self.assertIn("hidden copy", str(ctx.exception))
        self.assertEqual(len(self.app.received), n)

    # R5-2 the echo of "Keep consent." -------------------------------------------------------------------
    def test_echo_matches_label_with_ios_dot(self):
        scr = Screen(raw({"label": "Keep consent", "x": 200, "y": 300, "w": 150},
                         {"label": "Thanks, your consent is kept.", "x": 10, "y": 360}))
        self.assertEqual(new_messages([], scr, "Keep consent. "), ["Thanks, your consent is kept."])

    def test_chip_tap_echo_is_not_a_bot_message(self):
        self.app.chip_strip = True                  # buttons "Keep consent." with caption texts
        self._ask("consent")
        self.t.tap(text="Keep consent")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Sorry, I did not understand: Keep consent"])

    # R5-3 local "please wait" text ---------------------------------------------------------------------
    def test_interim_text_does_not_end_the_wait(self):
        evidence(self.s)
        self.app.interim = "On it!"                 # drawn by the app at once; the bot answers 1.5 s later
        self.app.reply_delay = 1.5
        rep = self._ask_long("Hello")
        self.assertEqual(rep["new_messages"][-1], "Hi! I can help with cards and payments.")
        self.assertNotIn("local_only", rep)

    def test_interim_labels_are_reported_apart(self):
        evidence(self.s)
        self.s.cfg["chat"]["interim_labels"] = ["^On it!$"]
        self.app.interim = "On it!"
        self.app.reply_delay = 1.5
        rep = self._ask_long("Hello")
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertEqual(rep["interim_messages"], ["On it!"])

    def test_text_without_bot_event_is_local_only(self):
        evidence(self.s)
        self.app.interim = "On it!"
        self.app.reply_delay = 100                  # the bot never answers within the timeout
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply(timeout_s=1.5)
        self.assertEqual(rep["new_messages"], ["On it!"])
        self.assertTrue(rep["local_only"], rep)

    def _ask_long(self, text):
        self.t.send_message(text)
        return self.t.wait_for_reply(timeout_s=8)

    # R5-4 a bot title equal to the start of a long option -------------------------------------------------
    def test_long_option_prefix_does_not_cut_bot_texts(self):
        self.app.long_title_panel = True
        self._ask("long option")
        self.t.tap(text="Show me the details of my current account balance")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Account overview", "Show me the details of my curr (panel)",
                                               "Balance: 1 234 EUR"])

    def test_prefix_only_for_user_side(self):
        long = "Show me the details of my current account balance"
        scr = Screen(raw({"label": "Account overview", "x": 10, "y": 300},
                         {"label": long[:30] + " (panel)", "x": 10, "y": 360},
                         {"label": "Balance", "x": 10, "y": 420}))
        self.assertEqual(new_messages([], scr, long), ["Account overview", long[:30] + " (panel)", "Balance"])

    # R5-5 a new bubble with a text seen before ------------------------------------------------------------
    def test_submenu_with_the_same_title_is_new(self):
        self._ask("main")
        self.t.tap(text="Loans")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Please choose 👇"])
        self.assertEqual([b.split("] ")[1] for b in rep["buttons"]], ["Car loan", "Home loan"])

    def test_trailing_copy_of_an_old_bubble_is_not_new(self):
        scr = Screen(raw({"label": "Welcome", "x": 10, "y": 100},
                         {"label": "Hello", "x": 200, "y": 160, "w": 150},
                         {"label": "Hi there", "x": 10, "y": 220},
                         {"label": "Welcome", "x": 10, "y": 690}))
        self.assertEqual(new_messages(["Welcome"], scr, "Hello", seen=["Welcome"]), ["Hi there"])

    # R5-6 a reply longer than the screen ------------------------------------------------------------------
    def test_long_reply_is_read_from_its_start(self):
        rep = self._ask("faq")
        self.assertEqual(rep["new_messages"], FAQ)
        self.assertGreaterEqual(rep["scrolled_up"], 1)
        self.assertEqual(self.app.offset, 0.0)      # scrolled back down

    def test_evidence_paragraph_not_drawn_is_reported(self):
        evidence(self.s)
        self.app.skip_paragraph = 2                 # the third bubble is never drawn
        rep = self._ask("faq")
        self.assertEqual(rep["new_messages"], FAQ[:2] + FAQ[3:])
        self.assertEqual(rep["evidence_texts_missing"], [FAQ[2]])
        self.assertIn("not rendered", rep["note_missing"])

    # R5-7 tappable action cards ----------------------------------------------------------------------------
    def test_action_card_is_not_a_message(self):
        rep = self._ask("transfer")
        self.assertEqual(rep["new_messages"], ["Here is what I can do for you:"])
        self.assertEqual(len(rep["actions"]), 1)
        self.assertTrue(rep["actions"][0].endswith("New transfer ›"))
        self.t.tap(text="New transfer")
        self.assertEqual(self.app.received[-1], {"payload": "/new transfer"})

    # R5-9 app switch and in-app browser ---------------------------------------------------------------------
    def test_slow_switch_within_the_default_watch(self):
        self.app.switch_delay = 3.0
        self._ask("link")
        res = self.t.tap(text="Open link")
        self.assertTrue(res["left_app"], res)
        self.assertEqual(self.app.state, "foreground")

    def test_in_app_browser_is_reported(self):
        self.app.web_sheet = True
        self._ask("link")
        res = self.t.tap(text="Open link")
        self.assertEqual(res["left_app"], "in_app_browser")
        self.assertIn("Done", res["hint"])
        with self.assertRaises(ToolError) as ctx:
            self.t.send_message("hello")
        self.assertIn("in-app web page", str(ctx.exception))
        self.t.tap(text="Done")
        self.assertIsNotNone(self.t.screen()["composer"])

    # R5-10 a picker option on two lines ---------------------------------------------------------------------
    def test_stacked_texts_in_one_cell_are_one_option(self):
        self.app.rows_stacked = True
        rep = self._ask("pick")
        self.assertEqual([o.split("] ")[1] for o in rep["options"]], ["Visa · ****1111", "Mastercard · ****2222"])

    # R5-11 small ---------------------------------------------------------------------------------------------
    def test_one_session_id_is_not_several_candidates(self):
        evidence(self.s)
        self.t.open_app(fresh=True)
        self.t.send_message("Hello")
        res = self.t.find_session_id()
        self.assertEqual(res["current"], "sess-1")
        self.assertNotIn("hint", res)

    def test_hidden_greeting_copy_is_not_listed_last(self):
        self.app.ghosts = True                      # a hidden copy of the greeting drawn low on screen
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self._ask("Hello")
        self.t.tap(text="Cards")
        self.t.wait_for_reply()
        self.t.tap(text="Debit")
        self.t.wait_for_reply()
        scr = self.t.screen()
        self.assertEqual(scr["messages"][-1], "Your debit card is blocked.")
        self.assertTrue(scr["hidden_copies"])

    def test_in_app_banner_is_an_app_alert(self):
        self.app.toast = "Your session expires in 1 minute"
        scr = self.t.screen()
        self.assertEqual(scr["app_alerts"][0]["label"], "Your session expires in 1 minute")
        self.assertNotIn("Your session expires in 1 minute", scr["messages"])


class PlannerTemplateTest(unittest.TestCase):
    """R5-8: the planner's worked example keeps given prompts runnable and verbatim."""

    def test_worked_example(self):
        text = (ROOT / "templates" / "planner.md").read_text(encoding="utf-8")
        guide = re.search(r"<!-- guide -->\s*```text\n(.*?)```", text, re.S).group(1)
        plan = parse_plan(re.search(r"<!-- plan -->\s*```markdown\n(.*?)```", text, re.S).group(1))
        rows = plan["rows"]
        self.assertEqual(len(rows), 3)
        runnable = [r for r in rows if not r["result"]]
        blocked = [r for r in rows if r["result"].startswith("blocked: needs")]
        self.assertEqual((len(runnable), len(blocked)), (2, 1))
        for r in runnable:
            self.assertIn('"%s"' % r["prompt"], guide)     # copied word for word from the guide
        self.assertIn("precondition:", runnable[1]["expected"])


if __name__ == "__main__":
    unittest.main()
