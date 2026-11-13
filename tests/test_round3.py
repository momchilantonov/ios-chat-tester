"""Regression tests for the third real run (requirements R1-R11 of the test agent's report)."""
import json
import tempfile
import unittest
from pathlib import Path

from helpers import Stack


def evidence(stack, options_path="buttons"):
    """An event export like a bot's conversation endpoint, built from the fake app's events."""
    stack.cfg["reply_evidence"] = {"endpoint": "conversation", "list": "events", "match": {"type": "bot_reply"},
                                   "text": "text", "options": options_path, "flow": "flow_id"}
    url = "http://127.0.0.1:8000/conversations/sess-1"
    stack.http[url] = lambda: json.dumps({"events": [
        {"type": "bot_reply" if who == "bot" else "user_message", "text": text, "buttons": opts,
         "flow_id": "flow_" + text.split()[0].lower().strip("!?:,.")}
        for who, text, opts in stack.app.events]})
    stack.simctl.app_log = ['2026-11-13 17:00:01 Db ChatDemo[1:2] POST /webhook sender_id="sess-1"']


class Round3Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    # R1 -----------------------------------------------------------------------------------------
    def test_evidence_before_screen_waits_for_the_screen(self):
        evidence(self.s)
        self.app.render_delay = 1.5               # the bot answered; the app draws it 1.5 s later
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertEqual([b.split("] ")[1] for b in rep["buttons"]], ["Cards", "Payments"])
        self.assertNotIn("note", rep)

    # R2 -----------------------------------------------------------------------------------------
    def test_short_text_never_taps_a_bubble_by_substring(self):
        self.app.silent = True
        self.t.send_message("not sure")             # the user's bubble contains "no" inside "not"
        n = len(self.app.commands)
        with self.assertRaises(Exception) as ctx:
            self.t.tap(text="no")
        self.assertIn("nothing on screen matches", str(ctx.exception))
        self.assertFalse([c for c in self.app.commands[n:] if c[0] == "tap"])

    def test_long_label_whole_word_on_buttons_only(self):
        self.t.send_message("menu")
        self.t.wait_for_reply()
        self.t.tap(text="payment")                  # whole word of the button "B payment"
        self.assertEqual(self.app.received[-1], {"payload": "/b payment"})

    # R3 -----------------------------------------------------------------------------------------
    def test_slow_app_switch_after_tap(self):
        self.app.switch_delay = 1.5                 # Safari comes to the front only after 1.5 s
        self.t.send_message("link")
        self.t.wait_for_reply()
        res = self.t.tap(text="Open link")
        self.assertTrue(res["left_app"], res)
        self.assertTrue(res["reactivated"])
        self.assertEqual(self.app.state, "foreground")

    def test_app_left_later_is_caught_by_the_next_screen_read(self):
        self.s.cfg["waits"]["app_switch_s"] = 0.3
        self.app.switch_delay = 1.0
        self.t.send_message("link")
        self.t.wait_for_reply()
        self.assertNotIn("left_app", self.t.tap(text="Open link"))
        import time
        time.sleep(1.1)
        rep = self.t.wait_for_reply(timeout_s=1)
        self.assertTrue(rep["left_app"])
        self.assertEqual(self.app.state, "foreground")

    def test_crashed_app_is_reported_not_relaunched(self):
        self.app.state = "notRunning"
        with self.assertRaises(Exception) as ctx:
            self.t.screen()
        self.assertIn("not running", str(ctx.exception))
        self.assertEqual(self.app.state, "notRunning")

    # R4 -----------------------------------------------------------------------------------------
    def test_session_found_after_first_message_and_per_conversation(self):
        evidence(self.s)
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        sent = self.t.send_message("Hello")
        self.assertEqual(sent["session_id"], "sess-1")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["evidence_new_replies"], 1)          # first turn has evidence too
        self.assertEqual(rep["evidence_flows"], ["flow_hi"])
        # second conversation: several ids in the logs, the newest is taken
        self.t.open_app(fresh=True)
        self.s.simctl.app_log.append('2026-11-13 17:05:01 Db ChatDemo[1:2] POST /webhook sender_id="sess-2"')
        res = self.t.find_session_id()
        self.assertEqual(res["current"], "sess-2")
        self.assertTrue(res["auto_picked"])

    def test_evidence_off_is_said(self):
        self.s.cfg["reply_evidence"] = {"endpoint": "conversation", "list": "events", "match": {}, "text": "text"}
        self.s.cfg["waits"]["session_find_s"] = 0.2
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply()
        self.assertIn("no session id", rep["evidence"])

    # R5 + R6 ------------------------------------------------------------------------------------
    def test_chips_in_a_strip_are_buttons_not_cards(self):
        self.app.chip_strip = True
        self.t.send_message("confirm")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Block these cards?"])
        self.assertEqual(rep.get("new_carousel_cards", []), [])
        self.assertEqual([b.split("] ")[1] for b in rep["buttons"]], ["Confirm.", "Cancel."])
        self.t.tap(text="Confirm")                                 # trailing "." ignored
        self.assertEqual(self.app.received[-1], {"payload": "/confirm"})

    def test_buttons_in_screen_order(self):
        self.app.reverse_order = True
        self.t.send_message("menu")
        rep = self.t.wait_for_reply()
        self.assertEqual([b.split("] ")[1] for b in rep["buttons"]],
                         ["A transfer", "B payment", "C rates", "D limits", "E other"])

    # R8 -----------------------------------------------------------------------------------------
    def test_rows_without_checkboxes_are_options(self):
        self.app.rows_as_text = True
        self.t.send_message("pick")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Select the cards to block:"])
        self.assertEqual([o.split("] ")[1] for o in rep["options"]], ["Visa · ****1111", "Mastercard · ****2222"])
        self.assertTrue(any("Продължи (disabled)" in b for b in rep["buttons"]))
        idx = int(rep["options"][0].split("]")[0][1:])
        self.t.tap(element=idx)
        self.assertTrue(any("Продължи" in b and "disabled" not in b for b in self.t.screen()["buttons"]))

    # R9 -----------------------------------------------------------------------------------------
    def test_options_in_evidence_but_not_on_screen(self):
        evidence(self.s)
        self.t.send_message("Hello")
        self.t.wait_for_reply()
        self.t.tap(text="Cards")
        # the bot sends a third option the app does not draw
        orig = self.s.http["http://127.0.0.1:8000/conversations/sess-1"]
        def doctored():
            doc = json.loads(orig())
            doc["events"][-1]["buttons"] = doc["events"][-1]["buttons"] + ["Virtual"]
            return json.dumps(doc)
        self.s.http["http://127.0.0.1:8000/conversations/sess-1"] = doctored
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["evidence_options_missing"], ["Virtual"])
        self.assertIn("not on screen", rep["note_options"])


class PrefilledPlanTest(unittest.TestCase):
    PLAN = """# Test plan: x
## Conversation 1: a
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| f | Hello | "Hi! I can help with cards and payments." | |
| f | tap first option | "Which card?" | |
| f | Hello | other menu | blocked: needs mock data with 3 cards |
"""

    def test_prefilled_blocked_rows_are_kept(self):
        s = Stack()
        try:
            with tempfile.TemporaryDirectory() as d:
                plan = Path(d) / "p.md"
                plan.write_text(self.PLAN, encoding="utf-8")
                st = s.tester.start_run(plan=str(plan))
                self.assertEqual(st["prefilled_blocked_rows"], [3])
                s.tester.record_result(1, "success")
                s.tester.record_result(2, "success")
                end = s.tester.end_run("done")
                self.assertEqual(end["verdict"], "BLOCKED")
                self.assertEqual(end["not_run"], [])
                self.assertIn("blocked: needs mock data with 3 cards", Path(end["results"]).read_text())
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
