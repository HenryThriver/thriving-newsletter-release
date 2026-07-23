from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
import importlib.util
import unittest
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/preflight_resend_credential.py"
SPEC = importlib.util.spec_from_file_location("preflight_resend_credential", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SEGMENT_ID = "11111111-1111-4111-8111-111111111111"


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class PreflightResendCredentialTests(unittest.TestCase):
    def test_success_requires_authenticated_read_of_confirmed_segment(self):
        observed = {}

        def opener(request, timeout):
            observed["url"] = request.full_url
            observed["authorization"] = request.get_header("Authorization")
            observed["timeout"] = timeout
            return FakeResponse()

        MODULE.preflight(
            {
                "RESEND_API_KEY": "re_test_only",
                "RESEND_SEGMENT_CONFIRMED_ID": SEGMENT_ID,
            },
            opener=opener,
        )

        self.assertEqual(
            observed["url"], f"https://api.resend.com/segments/{SEGMENT_ID}"
        )
        self.assertEqual(observed["authorization"], "Bearer re_test_only")
        self.assertEqual(observed["timeout"], 15)

    def test_missing_credential_fails_before_network_access(self):
        def opener(_request, _timeout):
            self.fail("network should not be called")

        with self.assertRaisesRegex(MODULE.PreflightError, "RESEND_API_KEY is missing"):
            MODULE.preflight(
                {"RESEND_SEGMENT_CONFIRMED_ID": SEGMENT_ID},
                opener=opener,
            )

    def test_provider_rejection_is_actionable_and_response_body_is_never_exposed(self):
        private_provider_body = (
            b'{"message":"re_actual_secret for private-person@example.com is invalid"}'
        )

        def opener(request, timeout):
            self.assertEqual(timeout, 15)
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                BytesIO(private_provider_body),
            )

        with self.assertRaises(MODULE.PreflightError) as caught:
            MODULE.preflight(
                {
                    "RESEND_API_KEY": "re_actual_secret",
                    "RESEND_SEGMENT_CONFIRMED_ID": SEGMENT_ID,
                },
                opener=opener,
            )

        message = str(caught.exception)
        self.assertIn("Private 1Password vault", message)
        self.assertNotIn("re_actual_secret", message)
        self.assertNotIn("private-person@example.com", message)
        self.assertNotIn(SEGMENT_ID, message)

    def test_cli_failure_prints_only_sanitized_message(self):
        original_preflight = MODULE.preflight

        def rejected(_environment):
            raise MODULE.PreflightError("safe failure")

        MODULE.preflight = rejected
        stdout = StringIO()
        stderr = StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = MODULE.main()
        finally:
            MODULE.preflight = original_preflight

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "ERROR: safe failure\n")


if __name__ == "__main__":
    unittest.main()
