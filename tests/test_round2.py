"""Regression tests for the second real run (planner + tester against the real chat)."""
import json
import unittest

from helpers import Stack
from simchat.tester import _select


class Round2Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _menu_twice(self):
        self.t.send_message("Hello")
        self.t.wait_for_reply()
        self.t.tap(text="Payments")          # old menu now goes stale
        self.t.wait_for_reply()
        self.t.send_message("hello")          # the same menu is offered again
        self.t.wait_for_reply()

    def test_tap_by_text_prefers_the_newest_copy(self):
        self.app.stale_y = 150                # stale copies above the latest user message
        self._menu_twice()
        res = self.t.tap(text="Cards")
        self.assertNotIn("no_visible_effect", res)
        self.assertEqual(self.app.received[-1], {"payload": "/cards"})

    def test_tap_with_no_effect_is_reported(self):
        self.app.stale_y = 700                # stale copies drawn low - ranking picks one
        self._menu_twice()
        res = self.t.tap(text="Cards")
        self.assertTrue(res.get("no_visible_effect"), res)
        self.assertTrue(res["other_copies"])
        self.assertEqual(self.app.received[-1], {"text": "hello"})   # nothing was sent

    def test_carousel_cards_are_not_messages(self):
        self.app.carousel = ["Card A", "Card B"]
        self.t.open_app(fresh=True)
        self.app.carousel = ["Card A", "Card B"]
        first = self.t.wait_for_reply()
        self.assertEqual(first["new_messages"], ["Welcome! How can I help?"])
        self.assertEqual(first["new_carousel_cards"], ["Card A"])
        idx = int(next(l for l in self.t.screen()["elements"] if " collectionView " in l).split("]")[0][1:])
        self.t.swipe("left", element=idx)
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertNotIn("Card B", rep["new_messages"])

    def _evidence_endpoint(self):
        self.s.cfg["reply_evidence"] = {"endpoint": "conversation", "list": "events",
                                        "match": {"event": "bot"}, "text": "text"}
        url = "http://127.0.0.1:8000/conversations/sess-1"
        self.s.http[url] = lambda: json.dumps({"events": [
            {"event": "bot" if who == "bot" else "user", "text": text + (" Second paragraph." if who == "bot" else "")}
            for who, text in self.app.messages]})
        self.t.set_session_id("sess-1")

    def test_identical_reply_detected_via_endpoint(self):
        self._evidence_endpoint()
        self.t.send_message("foo")
        first = self.t.wait_for_reply()
        self.assertEqual(first["new_messages"], ["Sorry, I did not understand: foo"])
        self.assertEqual(first["evidence_texts"], ["Sorry, I did not understand: foo Second paragraph."])
        self.t.send_message("foo")            # same question -> identical reply
        rep = self.t.wait_for_reply()
        self.assertTrue(rep["replied"], rep)
        self.assertEqual(rep["evidence_new_replies"], 1)
        # Round 5 (R5-5): below the user's new message, the repeated reply is confirmed by the endpoint and
        # reported as a new message (it used to be only a note).
        self.assertEqual(rep["new_messages"], ["Sorry, I did not understand: foo"])
        self.assertNotIn("note", rep)

    def test_without_evidence_identical_reply_is_not_detected(self):
        self.t.send_message("foo")
        self.t.wait_for_reply()
        self.t.send_message("foo")
        self.assertFalse(self.t.wait_for_reply(timeout_s=1.0)["replied"])

    def test_fetch_slices(self):
        doc = {"events": [{"text": str(i)} for i in range(10)]}
        self.assertEqual(_select(doc, "events[-3:].text"), ["7", "8", "9"])
        self.assertEqual(_select(doc, "events[:2]"), [{"text": "0"}, {"text": "1"}])
        self.assertEqual(_select(doc, "events[-1].text"), "9")
        self.assertEqual(_select(doc, "events.*.text")[:2], ["0", "1"])


if __name__ == "__main__":
    unittest.main()


class LinkTest(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_link_opens_another_app_and_app_comes_back(self):
        t = self.s.tester
        t.send_message("link")
        t.wait_for_reply()
        res = t.tap(text="Open link")
        self.assertTrue(res["left_app"])
        self.assertIn("success", res["left_app_note"])
        self.assertTrue(res["reactivated"])
        self.assertEqual(self.s.app.state, "foreground")
        self.assertEqual(t.screen()["app_state"], "foreground")
