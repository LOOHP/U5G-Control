"""Tests for privacy-conscious diagnostic redaction."""

import unittest

from custom_components.u5g_control.privacy import redact_diagnostics


class PrivacyTests(unittest.TestCase):
    def test_redacts_case_and_separator_variants(self) -> None:
        result = redact_diagnostics(
            {
                "cell-id": 1,
                "cell_id": 2,
                "cellId": 3,
                "CELL_ID": 4,
                "physical-cell-id": 5,
                "ARFCN": 6,
                "band": "n78",
            }
        )

        self.assertTrue(
            all(result[key] == "REDACTED" for key in result if key != "band")
        )
        self.assertEqual(result["band"], "n78")

    def test_redacts_nested_values_without_redacting_safe_fields(self) -> None:
        result = redact_diagnostics(
            {"carriers": [{"pci": 123, "tac": "abcd", "band": "b3"}]}
        )

        self.assertEqual(
            result,
            {
                "carriers": [
                    {"pci": "REDACTED", "tac": "REDACTED", "band": "b3"}
                ]
            },
        )
