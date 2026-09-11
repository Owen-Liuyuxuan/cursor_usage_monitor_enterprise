from __future__ import annotations

import unittest

from cursor_usage_supervisor.service import UsageService


class ServiceTest(unittest.TestCase):
    def test_usage_percent_for_current_plan(self) -> None:
        self.assertEqual(UsageService._usage_percent({
            "billing_model": "usage_based", "plan": {"total_percent": 87}
        }), 87)

    def test_usage_percent_for_legacy_plan(self) -> None:
        self.assertEqual(UsageService._usage_percent({
            "billing_model": "legacy_request_count", "requests": {"used": 250, "limit": 500}
        }), 50)

    def test_error_is_not_interpreted_as_usage(self) -> None:
        self.assertEqual(UsageService._usage_percent({"error": "offline"}), 0)


if __name__ == "__main__":
    unittest.main()
