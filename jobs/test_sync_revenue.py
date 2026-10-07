import tempfile
import unittest
from pathlib import Path
from sync_revenue import eligible, checkpoint


class SchedulerTest(unittest.TestCase):
    def test_policy(self):
        policy = {"timezone": "Asia/Taipei", "hours": [8, 11, 14, 17, 20, 23], "allowed": False}
        self.assertFalse(eligible(policy))
        policy["allowed"] = True
        self.assertTrue(eligible(policy))
        policy["timezone"] = "UTC"
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
