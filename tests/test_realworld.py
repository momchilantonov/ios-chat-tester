"""Regression tests for the problems found on the first real run (real SDK chat in the Simulator)."""
import json
import unittest

from helpers import Stack


class RealWorldTest(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def test_noise_does_not_count_as_a_reply(self):
        # scroll bars, a placeholder label in the composer, hidden copies of old bubbles, a date separator
        self.app.placeholder_label = "Пиши тук"
        self.app.scrollbars = True
        self.app.ghosts = True
        self.app.date_separator = "Днес"
        self.app.reply_delay = 1.0
        self.t.open_app(fresh=True)
        first = self.t.wait_for_reply()
        self.assertEqual(first["new_messages"], ["Днес", "Welcome! How can I help?"])
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertGreaterEqual(rep["waited_s"], 0.9)  # did not return before the real reply
        self.t.tap(text="Cards")
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Which card?"])

    def test_silent_bot_with_noise_is_not_a_reply(self):
        self.app.placeholder_label = "Пиши тук"
        self.app.scrollbars = True
        self.app.ghosts = True
        self.app.silent = True
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply(timeout_s=1.2)
        self.assertFalse(rep["replied"], rep)

    def test_ignore_labels(self):
        self.s.cfg["chat"]["ignore_labels"] = ["^test message \\d+$"]
        self.app.banner = "test message 2"
        self.t.open_app(fresh=True)
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Welcome! How can I help?"])
        self.assertNotIn("test message 2", self.t.screen()["messages"])

    def test_prefilled_composer_is_cleared_before_typing(self):
        self.app.prefill = "test message 2"
        self.t.open_app(fresh=True)
        self.t.send_message("Hello")
        self.assertEqual(self.app.received, [{"text": "Hello"}])

    def test_after_launch_navigation(self):
        self.app.start_on_menu = True
        self.s.cfg["app"]["after_launch"] = ["Open chat"]
        res = self.t.open_app(fresh=True)
        self.assertEqual(res["navigated"], ["Open chat"])
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Welcome! How can I help?"])
        self.s.cfg["app"]["after_launch"] = [{"tap": "Nope", "wait_s": 0.5}]
        with self.assertRaises(Exception) as ctx:
            self.t.open_app(fresh=True)
        self.assertIn("did not appear", str(ctx.exception))

    def test_selectable_rows_and_disabled_continue(self):
        self.t.send_message("pick")
        rep = self.t.wait_for_reply()
        # rows between the question and the disabled Continue come back as options (and as controls)
        self.assertEqual(rep["new_messages"], ["Select the cards to block:"])
        self.assertEqual([o.split("] ", 1)[1] for o in rep["options"]], ["Visa ****1111", "Mastercard ****2222"])
        self.assertTrue(any("(disabled)" in b and "Продължи" in b for b in rep["buttons"]))
        rows = [c for c in rep["controls"] if "Visa" in c]
        self.assertEqual(len(rows), 1)
        idx = int(rows[0].split("]")[0][1:])
        self.t.tap(element=idx)
        scr = self.t.screen()
        self.assertTrue(any("Visa" in e and "SELECTED" in e for e in scr["elements"]))
        self.t.tap(text="Продължи")
        self.assertEqual(self.app.received[-1], {"payload": "/продължи"})

    def test_typing_an_option_label_is_refused(self):
        for as_other in (False, True):
            self.app.qr_as_other = as_other
            self.t.open_app(fresh=True)
            self.t.send_message("Hello")
            rep = self.t.wait_for_reply()
            if as_other:  # not exposed as buttons: the labels show up as text
                self.assertEqual(rep["buttons"], [])
                self.assertIn("Cards", rep["new_messages"])
            with self.assertRaises(Exception) as ctx:
                self.t.send_message("Cards")
            self.assertIn("tap(element=", str(ctx.exception))
            self.assertEqual(self.app.received[-1], {"text": "Hello"})   # nothing was typed or sent
            idx = int(str(ctx.exception).split("tap(element=")[1].split(")")[0])
            self.t.tap(element=idx)                                      # the suggested element works
            self.assertEqual(self.app.received[-1], {"payload": "/cards"})
            expected = ["Which card?", "Debit", "Credit"] if as_other else ["Which card?"]
            self.assertEqual(self.t.wait_for_reply()["new_messages"], expected)

    def test_typing_an_option_label_when_the_plan_says_so(self):
        self.t.send_message("Hello")
        self.t.wait_for_reply()
        self.t.send_message("Cards", allow_button_text=True)
        self.assertEqual(self.app.received[-1], {"text": "Cards"})

    def test_repeating_own_message_is_not_refused(self):
        self.app.silent = True
        self.t.send_message("здравей")
        self.t.send_message("здравей")   # the user's own bubble with the same text is on screen
        self.assertEqual(self.app.received, [{"text": "здравей"}, {"text": "здравей"}])

    def test_session_id_from_app_log_then_fetch(self):
        self.s.simctl.app_log = [
            "2026-11-13 15:01:02.1 Df ChatDemo[1:2] [Kit] connecting",
            "2026-11-13 15:01:03.4 Db ChatDemo[1:2] [Kit] POST /webhook sender_id=\"abc-123-xyz\"",
        ]
        res = self.t.find_session_id()
        self.assertEqual(res["current"], "abc-123-xyz")
        self.assertEqual(res["candidates"][0]["source"], "app_log")
        url = "http://127.0.0.1:8000/conversations/abc-123-xyz"
        self.s.http[url] = json.dumps({"events": []})
        self.assertEqual(self.t.fetch("conversation")["url"], url)
        log = self.t.app_log(since="minutes", grep="webhook")
        self.assertEqual(len(log["lines"]), 1)
        spawn = [c for c in self.s.simctl.calls if c[:3] == ["xcrun", "simctl", "spawn"]][-1]
        self.assertIn('process == "ChatDemo"', spawn)

    def test_session_id_from_bot_log_and_manual(self):
        with open(self.s.log, "a") as fh:
            fh.write("INFO tracker id: conv_777aaa received\nINFO session_id=conv_888bbb\n")
        res = self.t.find_session_id()
        self.assertEqual([c["id"] for c in res["candidates"]], ["conv_888bbb", "conv_777aaa"])
        self.assertIsNone(res["current"])
        with self.assertRaises(Exception):
            self.t.fetch("conversation")
        self.t.set_session_id("conv_888bbb")
        url = "http://127.0.0.1:8000/conversations/conv_888bbb"
        self.s.http[url] = "{}"
        self.assertEqual(self.t.fetch("conversation")["url"], url)
        with self.assertRaises(Exception):
            self.t.set_session_id("bad id with spaces")


if __name__ == "__main__":
    unittest.main()
