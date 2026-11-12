"""Tests for firmware-independent radio-status normalization."""

from __future__ import annotations

import unittest

from custom_components.u5g_control.radio_status import (
    current_mode,
    lte_measurement,
    nsa_is_active,
    rounded_measurement,
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

    def test_no_radio_connection(self) -> None:
        self.assertEqual(current_mode({}), "Not connected")

    def test_lte_measurements_are_hidden_during_sa(self) -> None:
        status = {
            "rat-mode-active": "5G",
            "5g-sa-mode": True,
            "rsrp": -82,
            "rsrq": -15,
            "snr": -2.0,
            "rsrp-nr": -82,
            "rsrq-nr": -15,
            "snr-nr": -2.0,
        }
        self.assertIsNone(lte_measurement(status, "rsrp"))
        self.assertIsNone(lte_measurement(status, "rsrq"))
        self.assertIsNone(lte_measurement(status, "snr"))

    def test_lte_measurements_remain_available_during_nsa_and_lte(self) -> None:
        for status in (
            {"rat-mode-active": "LTE", "rsrp": -90},
            {
                "rat-mode-active": "5G",
                "5g-sa-mode": False,
                "ca-lte": [{"band": 3}],
                "rsrp": -67,
            },
        ):
            with self.subTest(status=status):
                self.assertEqual(lte_measurement(status, "rsrp"), status["rsrp"])

    def test_measurement_rounding_removes_firmware_float_artifacts(self) -> None:
        self.assertEqual(rounded_measurement(3.5999999046325684), 3.6)
        self.assertEqual(rounded_measurement(3.64), 3.6)
        self.assertEqual(rounded_measurement(-0.30000001192092896), -0.3)
        self.assertIsNone(rounded_measurement(None))


if __name__ == "__main__":
    unittest.main()
