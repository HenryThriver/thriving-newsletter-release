from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/schedule-newsletter.yml"


class ScheduleNewsletterWorkflowTests(unittest.TestCase):
    def test_failed_release_reports_sanitized_diagnostics_before_cleanup(self):
        workflow = WORKFLOW.read_text()

        self.assertIn('report_failure "approval creation"', workflow)
        self.assertIn(
            'report_failure "target verification or scheduling"', workflow
        )
        self.assertIn("[redacted-email]", workflow)
        self.assertIn("[redacted-id]", workflow)
        self.assertIn("[redacted-token]", workflow)
        self.assertIn("tail -n 20", workflow)
        self.assertIn("trap 'rm -f \"$log_path\"' EXIT", workflow)


if __name__ == "__main__":
    unittest.main()
