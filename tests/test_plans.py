import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, Stack
from simchat.plan import fill_results, format_result, parse_plan

PLAN = """# Test plan: cards
Preconditions: test customer with 2 cards
Source: flows/cards.yml

## Conversation 1: block a card
| Flow | User prompt | Expected | Result |
|---|---|---|---|
| fl_cards | Hello | "Hi! I can help with cards and payments." buttons: "Cards", "Payments" | |
| fl_cards | tap Cards | "Which card?" | |
| fl_cards | tap Debit | "Your debit card is blocked." | |

Some notes between tables.

## Conversation 2: unknown
| # | Flow | User prompt / payload | Expected | Result |
|---|---|---|---|---|
| 9 | fallback | asdf | a polite fallback | |
"""


class PlanFormatTest(unittest.TestCase):
    def test_parse(self):
        p = parse_plan(PLAN)
        self.assertEqual(p["title"], "Test plan: cards")
        self.assertEqual(p["sections"], ["Conversation 1: block a card", "Conversation 2: unknown"])
        self.assertEqual([r["row"] for r in p["rows"]], [1, 2, 3, 4])
        self.assertEqual(p["rows"][1]["prompt"], "tap Cards")
        self.assertEqual(p["rows"][3]["flow"], "fallback")      # extra "#" column is tolerated
        self.assertEqual(p["rows"][3]["prompt"], "asdf")

    def test_fill_keeps_everything_else(self):
        filled = fill_results(PLAN, {1: "success", 4: format_result("fail", "got | an error")})
        self.assertIn("| fl_cards | Hello |", filled)
        self.assertTrue(filled.splitlines()[7].endswith("| success |"))
        self.assertIn("fail: got \\| an error", filled)
        self.assertIn("Some notes between tables.", filled)
        again = parse_plan(filled)
        self.assertEqual(again["rows"][3]["result"], "fail: got \\| an error")
        self.assertEqual(again["rows"][1]["result"], "")

    def test_result_format(self):
        self.assertEqual(format_result("SUCCESS", "evidence is kept in the report"), "success")
        self.assertEqual(format_result("blocked", "mock data missing"), "blocked: mock data missing")
        for bad in (("fail", ""), ("blocked", " "), ("maybe", "x")):
            with self.assertRaises(ValueError):
                format_result(*bad)

    def test_example_plan_parses(self):
        p = parse_plan((ROOT / "tester" / "plans" / "example-plan.md").read_text())
        self.assertGreaterEqual(len(p["rows"]), 3)


class PlanRunTest(unittest.TestCase):
    def setUp(self):
        self.s = Stack()
        self.t = self.s.tester
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = Path(self.tmp.name) / "cards.md"
        self.plan.write_text(PLAN, encoding="utf-8")

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_run_plan_and_fill_results(self):
        st = self.t.start_run(plan=str(self.plan))
        self.assertEqual(len(st["rows"]), 4)
        self.assertEqual(st["conversations"][0], "Conversation 1: block a card")
        self.t.open_app(fresh=True)
        self.t.wait_for_reply()
        self.t.send_message("Hello")
        self.assertEqual(self.t.wait_for_reply()["new_messages"], ["Hi! I can help with cards and payments."])
        self.t.record_result(1, "success")
        self.t.tap(text="Cards")
        self.t.wait_for_reply()
        self.t.record_result(2, "success")
        self.t.tap(text="Debit")
        self.t.wait_for_reply()
        res = self.t.record_result(3, "fail", 'got "Your debit card is blocked." but expected a confirmation first')
        self.assertEqual(res["rows_left"], [4])
        with self.assertRaises(Exception):
            self.t.record_result(7, "success")
        with self.assertRaises(Exception):
            self.t.record_result(4, "blocked")              # blocked needs a reason
        end = self.t.end_run("Row 3 failed, row 4 not run.")
        self.assertEqual(end["verdict"], "FAIL")
        self.assertEqual(end["counts"], {"success": 2, "fail": 1, "blocked": 1})
        self.assertEqual(end["not_run"], [4])
        results = parse_plan(Path(end["results"]).read_text(encoding="utf-8"))
        self.assertEqual([r["result"] for r in results["rows"]],
                         ["success", "success",
                          'fail: got "Your debit card is blocked." but expected a confirmation first',
                          "blocked: not run"])
        self.assertNotIn("results_beside_plan", end)          # plan outside tester/plans: only in the run folder

    def test_verdicts(self):
        self.t.start_run(plan=str(self.plan))
        for row in (1, 2, 3):
            self.t.record_result(row, "success")
        self.t.record_result(4, "blocked", "fallback mock not configured")
        self.assertEqual(self.t.end_run("x")["verdict"], "BLOCKED")
        self.t.start_run(plan=str(self.plan))
        for row in (1, 2, 3, 4):
            self.t.record_result(row, "success")
        self.assertEqual(self.t.end_run("x")["verdict"], "PASS")

    def test_plan_without_table_and_record_without_plan(self):
        bad = Path(self.tmp.name) / "bad.md"
        bad.write_text("# nothing here\n", encoding="utf-8")
        with self.assertRaises(Exception):
            self.t.start_run(plan=str(bad))
        self.t.start_run("free")
        with self.assertRaises(Exception):
            self.t.record_result(1, "success")
        with self.assertRaises(Exception):
            self.t.end_run("no verdict given")

    def test_plans_tool_lists_and_reads(self):
        listing = self.t.plans()
        self.assertIn("example-plan.md", listing["plans"])
        one = self.t.plans("example-plan")
        self.assertTrue(one["rows"])
        self.assertIn("content", one)


if __name__ == "__main__":
    unittest.main()
