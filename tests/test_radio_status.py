"""Tests for firmware-independent radio-status normalization."""

from __future__ import annotations

import unittest

from custom_components.u5g_control.radio_status import (
    current_mode,
    nsa_is_active,
    sa_is_active,
)


class RadioStatusTests(unittest.TestCase):
    def test_sa_boolean_and_string_values(self) -> None:
        for value in (True, "true", "TRUE"):
            status = {"rat-mode-active": "5G", "5g-sa-mode": value}
            self.assertEqual(current_mode(status), "5G SA")
            self.assertTrue(sa_is_active(status))
            self.assertFalse(nsa_is_active(status))

    def test_nsa_boolean_and_string_values(self) -> None:
        for value in (False, "false", "FALSE"):
            status = {"rat-mode-active": "nr5g", "5g-sa-mode": value}
            self.assertEqual(current_mode(status), "5G NSA")
            self.assertFalse(sa_is_active(status))
            self.assertTrue(nsa_is_active(status))

    def test_explicit_rat_names_and_case(self) -> None:
        self.assertEqual(current_mode({"mode": "5g nSa"}), "5G NSA")
        self.assertEqual(current_mode({"mode": "NR5G-SA"}), "5G SA")
        self.assertEqual(current_mode({"mode": "lte"}), "LTE")

    def test_missing_sa_flag_uses_carrier_aggregation(self) -> None:
        status = {
            "rat-mode-active": "5G",
            "ca-lte": [{"band": 3}],
            "ca-nr": [{"band": 78}],
        }
        self.assertEqual(current_mode(status), "5G NSA")
        self.assertTrue(nsa_is_active(status))


if __name__ == "__main__":
    unittest.main()
