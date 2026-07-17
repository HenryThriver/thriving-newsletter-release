import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "prepare_kit_reminder_audience.py"
SPEC = importlib.util.spec_from_file_location("kit_audience", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AudiencePlanTests(unittest.TestCase):
    def test_excludes_confirmed_and_prunes_stale_tag_members(self):
        plan = MODULE.build_plan(
            [
                {"id": 1, "email_address": "one@example.com"},
                {"id": 2, "email_address": "two@example.com"},
                {"id": 3, "email_address": "three@example.com"},
            ],
            {"two@example.com", "external@example.com"},
            [
                {"id": 1, "email_address": "one@example.com"},
                {"id": 2, "email_address": "two@example.com"},
                {"id": 99, "email_address": "inactive@example.com"},
            ],
        )

        self.assertEqual(plan.active_kit_count, 3)
        self.assertEqual(plan.confirmed_resend_count, 2)
        self.assertEqual(plan.overlap_excluded_count, 1)
        self.assertEqual(plan.eligible_count, 2)
        self.assertEqual(plan.add_ids, (3,))
        self.assertEqual(plan.remove_ids, (2, 99))

    def test_refuses_zero_overlap_instead_of_tagging_everyone(self):
        with self.assertRaisesRegex(RuntimeError, "no Kit/Resend overlap"):
            MODULE.build_plan(
                [{"id": 1, "email_address": "one@example.com"}],
                {"other@example.com"},
                [],
            )

    def test_refuses_duplicate_active_kit_addresses(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            MODULE.build_plan(
                [
                    {"id": 1, "email_address": "same@example.com"},
                    {"id": 2, "email_address": "SAME@example.com"},
                ],
                {"same@example.com"},
                [],
            )


if __name__ == "__main__":
    unittest.main()
