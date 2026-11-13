import json
import unittest

from helpers import Stack


class TesterTest(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester

    def tearDown(self):
        self.s.close()

    def test_status_ok_shape(self):
        st = self.t.status()
        self.assertEqual(st["driver"]["phase"], "ready")
        self.assertEqual(st["simulator"]["udid"], "SIM-1")
        self.assertEqual(st["app_state"], "foreground")
        self.assertIn("scenarios", st)

    def test_welcome_then_send_and_reply_with_buttons(self):
        self.t.open_app(fresh=True)
        first = self.t.wait_for_reply()
        self.assertEqual(first["new_messages"], ["Welcome! How can I help?"])
        res = self.t.send_message("Hello")
        self.assertTrue(res["confirmed"])
        rep = self.t.wait_for_reply()
        self.assertTrue(rep["replied"])
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertEqual([b.split("] ", 1)[1] for b in rep["buttons"]], ["Cards", "Payments"])
        self.assertEqual(self.s.app.received, [{"text": "Hello"}])

    def test_unicode_message(self):
        self.t.send_message("Здравей")
        rep = self.t.wait_for_reply()
        self.assertEqual(rep["new_messages"], ["Hi! I can help with cards and payments."])
        self.assertEqual(self.s.app.received, [{"text": "Здравей"}])

    def test_tap_quick_reply_by_index_sends_payload(self):
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply()
        idx = int(rep["buttons"][0].split("]")[0][1:])
        self.t.tap(element=idx)
        rep2 = self.t.wait_for_reply()
        self.assertEqual(rep2["new_messages"], ["Which card?"])
        self.assertEqual(self.s.app.received[-1], {"payload": "/cards"})

    def test_tap_by_text(self):
        self.t.send_message("Hello")
        self.t.wait_for_reply()
        self.t.tap(text="payments")
        self.assertEqual(self.s.app.received[-1], {"payload": "/payments"})

    def test_stale_index_is_refused(self):
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply()
        idx = int(rep["buttons"][0].split("]")[0][1:])
        self.s.app.buttons = []  # the buttons vanish after the agent saw them
        with self.assertRaises(Exception) as ctx:
            self.t.tap(element=idx)
        self.assertIn("no longer on screen", str(ctx.exception))
        self.assertEqual(self.s.app.received, [{"text": "Hello"}])

    def test_readback_retries_once_then_sends(self):
        self.s.app.mangle_typing = 1
        res = self.t.send_message("Hello")
        self.assertTrue(res["confirmed"])
        self.assertEqual(self.s.app.received, [{"text": "Hello"}])

    def test_readback_failure_sends_nothing(self):
        self.s.app.mangle_typing = 5
        with self.assertRaises(Exception) as ctx:
            self.t.send_message("Hello")
        self.assertIn("did not read back", str(ctx.exception))
        self.assertEqual(self.s.app.received, [])
        self.assertEqual(self.s.app.value, "")

    def test_send_button_missing(self):
        self.s.app.send_label = ""
        with self.assertRaises(Exception) as ctx:
            self.t.send_message("Hello")
        self.assertIn("Send button not found", str(ctx.exception))
        self.assertEqual(self.s.app.received, [])
        self.assertEqual(self.s.app.value, "")

    def test_send_button_found_by_position_when_label_unknown(self):
        self.s.app.send_label = "Изпрати"
        self.t.send_message("Hello")
        self.assertEqual(self.s.app.received, [{"text": "Hello"}])

    def test_silent_bot_times_out(self):
        self.s.app.silent = True
        self.t.send_message("Hello")
        rep = self.t.wait_for_reply(timeout_s=0.6)
        self.assertFalse(rep["replied"])
        self.assertTrue(rep["timed_out"])

    def test_screen_listing(self):
        scr = self.t.screen()
        self.assertIn("Welcome! How can I help?", scr["messages"])
        self.assertIn("textView", scr["composer"])
        self.assertIn("'Send'", scr["send_button"])

    def test_run_lifecycle_and_verdict_rules(self):
        st = self.t.start_run("greeting")
        self.t.send_message("Hello")
        self.t.wait_for_reply()
        self.t.check("bot greets", True, "Hi! I can help with cards and payments.")
        self.t.check("offers loans", False, "no loans button")
        end = self.t.end_run("PASS", "summary")
        self.assertEqual(end["verdict"], "FAIL")
        from pathlib import Path
        run_dir = Path(st["run_dir"])
        for f in ("journal.jsonl", "run.json", "transcript.json", "log-bot.txt"):
            self.assertTrue((run_dir / f).exists(), f)
        transcript = json.loads((run_dir / "transcript.json").read_text())
        self.assertEqual(transcript[0], {"from": "user", "text": "Hello"})
        self.t.start_run("empty")
        self.assertEqual(self.t.end_run("PASS", "nothing")["verdict"], "INCONCLUSIVE")
        self.t.start_run("blocked")
        self.assertEqual(self.t.end_run("BLOCKED", "bot down")["verdict"], "BLOCKED")

    def test_check_needs_evidence_and_run(self):
        with self.assertRaises(Exception):
            self.t.check("x", True, "e")
        self.t.start_run("r")
        with self.assertRaises(Exception):
            self.t.check("x", True, "  ")

    def test_write_file_is_confined(self):
        st = self.t.start_run("w")
        ok = self.t.write_file(st["run_dir"] + "/report.md", "# r")
        self.assertTrue(ok["written"].endswith("report.md"))
        for bad in ("../../etc/x.md", "/tmp/x.md", st["run_dir"] + "/x.sh"):
            with self.assertRaises(Exception):
                self.t.write_file(bad, "x")

    def test_fetch_local_only_vars_path_and_saved(self):
        url = "http://127.0.0.1:8000/conversations/abc%20d"
        self.s.http[url] = json.dumps({"events": [{"event": "user", "text": "Hello"}, {"event": "bot", "text": "Hi"}]})
        self.t.start_run("f")
        res = self.t.fetch("conversation", vars={"session_id": "abc d"}, path="events[-1].text")
        self.assertEqual(json.loads(res["data"]), "Hi")
        self.assertTrue(res["saved"].endswith(".json"))
        self.assertEqual(json.loads(self.t.fetch("conversation", {"session_id": "abc d"}, "events.*.event")["data"]),
                         ["user", "bot"])
        for bad in (("remote", {}), ("conversation", {}), ("nope", {})):
            with self.assertRaises(Exception):
                self.t.fetch(*bad)

    def test_read_log_since_turn(self):
        self.t.start_run("logs")
        with open(self.s.log, "a") as fh:
            fh.write("before turn\n")
        self.t.send_message("Hello")
        with open(self.s.log, "a") as fh:
            fh.write("handled message\nERROR something broke\n")
        res = self.t.read_log(since="turn")
        self.assertEqual(res["lines"], ["handled message", "ERROR something broke"])
        self.assertEqual(res["error_count"], 1)
        self.assertIn("before turn", self.t.read_log(since="run")["lines"])
        self.assertEqual(self.t.read_log(since="run", grep="broke")["lines"], ["ERROR something broke"])

    def test_driver_down_is_a_clear_error(self):
        self.s.server.close()
        with self.assertRaises(Exception) as ctx:
            self.t.screen()
        self.assertIn("start_driver", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
