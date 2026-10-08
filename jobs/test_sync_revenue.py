import tempfile
import unittest
from pathlib import Path
from sync_revenue import eligible, checkpoint, pending_reports, deferred_reports


class SchedulerTest(unittest.TestCase):
    def test_pending_reports(self):
        capture={"results":[{"month":"202609","live":{"updated":30,"pending":100}}]}
        self.assertEqual(pending_reports(capture),100)
        self.assertEqual(pending_reports({"skipped":True,"previous":capture}),100)

    def test_expected_deferred_reports_are_visible_and_partial_receipt_upgrades_when_resolved(self):
        reports=[{"companyId":"2880","reason":"financial_summary_pending"}]
        result={"state":"complete","policy":{"date":"20261008","slot":"20261008-10-00"},"completedAt":"2026-10-08T02:00:00Z","results":[],"errors":[],"deferred":reports}
        self.assertEqual(deferred_reports({"skipped":True,"previous":result}),reports)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"receipt.json"
            checkpoint(result,path)
            self.assertIn('"dataStatus": "partial"',path.read_text())
            result["deferred"]=[]
            checkpoint(result,path)
            self.assertIn('"dataStatus": "up-to-date"',path.read_text())
    def test_policy(self):
        policy = {"timezone": "Asia/Taipei", "intervalMinutes": 5,"allDay": True,"allowed": False}
        self.assertFalse(eligible(policy))
        policy["allowed"] = True
        self.assertTrue(eligible(policy))
        policy["timezone"] = "UTC"
        with self.assertRaises(RuntimeError):
            eligible(policy)
        policy["timezone"] = "Asia/Taipei"
        policy["intervalMinutes"] = 3
        with self.assertRaises(RuntimeError):
            eligible(policy)
        policy["intervalMinutes"] = 5
        policy["allDay"] = False
        with self.assertRaises(RuntimeError):
            eligible(policy)

    def test_receipt_written_only_once_per_month_after_success(self):
        result = {"state": "complete", "policy": {"date": "20261007", "slot": "20261007-08"},
                  "completedAt": "2026-10-07T00:01:00Z", "results": [], "errors": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            checkpoint(result, path)
            first = path.read_text()
            result["completedAt"] = "2026-10-07T03:01:00Z"
            checkpoint(result, path)
            self.assertEqual(first, path.read_text())
            result["policy"]["date"] = "20261101"
            result["errors"] = ["official source failed"]
            checkpoint(result, path)
            self.assertEqual(first, path.read_text())
            result["errors"] = []
            checkpoint({"skipped": True, "previous": result}, path)
            self.assertNotEqual(first, path.read_text())


if __name__ == "__main__":
    unittest.main()

