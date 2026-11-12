"""Tests for component-carrier bandwidth normalization."""

from __future__ import annotations

import unittest

from custom_components.u5g_control.carrier import (
    carrier_downlink_width_mhz,
    carrier_uplink_width_mhz,
    carrier_width_mhz,
)


class CarrierWidthTests(unittest.TestCase):
    def test_common_firmware_key_variants(self) -> None:
        for carrier in (
            {"bandwidth": 20},
            {"Bandwidth-MHz": "20 MHz"},
            {"dl_bandwidth": 20},
            {"downlink-bandwidth": "20MHz"},
            {"rx_bw": "20 MHz"},
        ):
            with self.subTest(carrier=carrier):
                self.assertEqual(carrier_width_mhz(carrier), 20)

    def test_nested_bandwidth(self) -> None:
        self.assertEqual(
            carrier_width_mhz({"radio": {"channel": {"width": "100 MHz"}}}),
            100,
        )

    def test_u5g_radio_status_bandwidth_fields(self) -> None:
        lte = {
            "primary": True,
            "band": 3,
            "dl-bw-mhz": 15.0,
            "ul-bw-mhz": 10.0,
            "dl-earfcn": 1791,
        }
        nr = {
            "primary": True,
            "band": 78,
            "dl-bw-mhz": 40.0,
            "ul-bw-mhz": 30.0,
            "dl-arfcn": 646666,
        }

        self.assertEqual(carrier_width_mhz(lte), 15)
        self.assertEqual(carrier_width_mhz(nr), 40)
        self.assertEqual(carrier_downlink_width_mhz(lte), 15)
        self.assertEqual(carrier_uplink_width_mhz(lte), 10)
        self.assertEqual(carrier_downlink_width_mhz(nr), 40)
        self.assertEqual(carrier_uplink_width_mhz(nr), 30)

    def test_downlink_is_preferred_regardless_of_key_order(self) -> None:
        carrier = {"ul-bw-mhz": 10.0, "dl-bw-mhz": 15.0}
        self.assertEqual(carrier_width_mhz(carrier), 15)

    def test_unit_conversion(self) -> None:
        self.assertEqual(carrier_width_mhz({"bandwidth_khz": 20_000}), 20)
        self.assertEqual(carrier_width_mhz({"bandwidth-hz": 20_000_000}), 20)
        self.assertEqual(carrier_width_mhz({"bandwidth": "0.1 GHz"}), 100)

    def test_missing_bandwidth(self) -> None:
        self.assertIsNone(carrier_width_mhz({"band": 3, "arfcn": 1300}))

    def test_uplink_requires_an_explicit_uplink_value(self) -> None:
        self.assertIsNone(carrier_uplink_width_mhz({"bandwidth": "20 MHz"}))
        self.assertEqual(carrier_uplink_width_mhz({"tx_bw": "10 MHz"}), 10)
