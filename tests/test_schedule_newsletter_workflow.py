from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/schedule-newsletter.yml"


class ScheduleNewsletterWorkflowTests(unittest.TestCase):
    def test_resend_credential_is_preflighted_before_private_checkout(self):
        workflow = WORKFLOW.read_text()

        preflight = workflow.index("Preflight protected Resend credential")
        private_checkout = workflow.index("Check out exact private release commit")
        install = workflow.index("Install locked dependencies")

        self.assertLess(preflight, private_checkout)
        self.assertLess(preflight, install)
        self.assertIn(
            "python3 scripts/preflight_resend_credential.py",
            workflow,
        )

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
