"""Regression tests for the ninth real run (QA requirements R10-1, R10-2)."""
import unittest

from helpers import Stack
from simchat.driver import DriverError
import test_install


def labels(items):
    return [i.split("] ", 1)[1] for i in items]


class Round10Test(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.app = self.s.app

    def tearDown(self):
        self.s.close()

    def _ask(self, text, **kw):
        self.t.send_message(text, **kw)
        return self.t.wait_for_reply()

    # R10-2 the picker's question is never an option ----------------------------------------------------------
    def test_picker_after_a_rejected_text_keeps_its_question_in_messages(self):
        self.app.real_layout = True
        self.app.reject_text = True                 # typed text at the picker: a line, then the picker again
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        first = self._ask("pick")
        self.assertEqual(first["new_messages"], ["Select the cards to block:"])
        self.assertEqual(labels(first["options"]), ["Visa ****1111", "Mastercard ****2222"])
        again = self._ask("blabla")
        self.assertEqual(again["new_messages"], ["Choose from the list, please.", "Select the cards to block:"])
        self.assertEqual(labels(again["options"]), ["Visa ****1111", "Mastercard ****2222"])
        scr = self.t.screen()
        self.assertEqual(labels(scr["options"]), ["Visa ****1111", "Mastercard ****2222"])
        self.assertIn("Select the cards to block:", scr["messages"])

    # R10-1 (optional part) start_driver retries once after "failed to launch" ------------------------------
    def test_start_driver_retries_once_after_a_failed_launch(self):
        calls = []

        class Manager:
            def ensure(self, wait_s):
                calls.append(wait_s)
                if len(calls) == 1:
                    raise DriverError("driver process exited - Simulator device failed to launch xctrunner")
                return {"phase": "ready"}

            def status(self):
                return {"phase": "stopped"}

        self.t.manager = Manager()
        res = self.t.start_driver(wait_s=5)
        self.assertEqual(res["phase"], "ready")
        self.assertIn("failed to launch", res["retried"])
        self.assertEqual(len(calls), 2)


class UninstallSimulatorTest(unittest.TestCase):
    """R10-1: the uninstall test must not remove the driver's runner app from the real simulator."""

    def setUp(self):
        self.h = test_install.InstallTest("run_install")
        self.h.setUp()

    def tearDown(self):
        self.h.tearDown()

    def test_uninstall_runs_simctl_only_through_the_installer(self):
        self.h.mod.Installer._is_mac = staticmethod(lambda: True)   # the macOS path, on any machine
        self.h.booted = ["FAKE-UDID"]
        code, out = self.h.run_install("--bundle-id", "a.b")
        self.assertEqual(code, 0, out)
        code, out = self.h.run_install("--uninstall", "--force")
        self.assertIn(["xcrun", "simctl", "uninstall", "FAKE-UDID", self.h.mod.RUNNER_ID], self.h.simctl_calls)
        self.assertIn("remove   driver runner app", out)


if __name__ == "__main__":
    unittest.main()
