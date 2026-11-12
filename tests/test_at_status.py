"""Tests for Sierra Wireless AT status parsing."""

from __future__ import annotations

import unittest

from custom_components.u5g_control.at_status import (
    merge_sierra_lteinfo,
    merge_sierra_nrinfo,
    parse_sierra_lteinfo,
    parse_sierra_nrinfo,
)


NRINFO = """!NRINFO:
Connectivity Mode: SA
NR5G band:       n1                     NR5G Carrier ID: 0
NR5G dl bw:      20 MHz                 NR5G ul bw:      20 MHz
NR5G Tx Power:   17.0                   NR5G Tx chan:    393940
NR5G Rx chan:    431940
NR5G dl MIMO:    4                      NR5G ul MIMO:    1
NR5G(sub6) Rx0 RSSI (dBm):   -47.1      NR5G(sub6) Rx1 RSSI (dBm):   -46.9
NR5G(sub6) Rx2 RSSI (dBm):   -46.0      NR5G(sub6) Rx3 RSSI (dBm):   -44.1
NR5G band:       n78                    NR5G Carrier ID: 1
NR5G dl bw:      40 MHz                 NR5G ul bw:      Unknown
NR5G Tx Power:   ---                    NR5G Tx chan:    0
NR5G Rx chan:    637334
NR5G dl MIMO:    4                      NR5G ul MIMO:    0
NR5G(sub6) Rx0 RSSI (dBm):   -46.8      NR5G(sub6) Rx1 RSSI (dBm):   -45.8
NR5G(sub6) Rx2 RSSI (dBm):   -45.5      NR5G(sub6) Rx3 RSSI (dBm):   -48.0
NR5G RSRP (dBm): -82                    NR5G RSRQ (dB):  -15
NR5G SINR (dB):  -2.0
OK
"""

LTEINFO = """!LTEINFO:
Serving:   EARFCN MCC MNC   TAC      CID Bd D U SNR PCI  RSRQ   RSRP   RSSI RXLV
             1791 234  30 24510 00A37F18  3 4 4   5 160 -12.0  -66.6  -34.9 --
IntraFreq:                                          PCI  RSRQ   RSRP   RSSI RXLV
CA SCell : EARFCN   SCID   Bd  ST  D  U   Mdl  Mul  PCI  RSRP   RSSI   SINR
             1617     58    3   2  4  0     2    0   58 -82.0  -55.5    7.0
WCDMA:     UARFCN ThreshL ThreshH Prio PSC   RSCP  ECN0 RXLV
OK
"""


class SierraNrInfoTests(unittest.TestCase):
    def test_parses_each_carrier_without_misattributing_aggregate_quality(self) -> None:
        carriers = parse_sierra_nrinfo(NRINFO)

        self.assertEqual(len(carriers), 2)
        self.assertEqual(
            carriers[0],
            {
                "band": 1,
                "carrier-id": 0,
                "dl-bw-mhz": 20,
                "ul-bw-mhz": 20,
                "tx-power-dbm": 17,
                "ul-arfcn": 393940,
                "dl-arfcn": 431940,
                "dl-mimo-layers": 4,
                "ul-mimo-layers": 1,
                "rssi-rx0-dbm": -47.1,
                "rssi-rx1-dbm": -46.9,
                "rssi-rx2-dbm": -46.0,
                "rssi-rx3-dbm": -44.1,
                "rssi-dbm": -44.1,
                "rssi-average-dbm": -46.0,
                "primary": True,
            },
        )
        self.assertNotIn("rsrp", carriers[1])
        self.assertNotIn("ul-bw-mhz", carriers[1])
        self.assertEqual(carriers[1]["rssi-dbm"], -45.5)
        self.assertEqual(carriers[1]["rssi-average-dbm"], -46.5)

    def test_merges_with_uiwwand_records_by_band_and_channel(self) -> None:
        status = {
            "ca-nr": [
                {"primary": True, "band": 1, "dl-arfcn": 431940},
                {"primary": False, "band": 78, "dl-arfcn": 637334},
            ]
        }

        merge_sierra_nrinfo(status, NRINFO)

        self.assertEqual(status["ca-nr"][0]["dl-bw-mhz"], 20)
        self.assertEqual(status["ca-nr"][1]["dl-bw-mhz"], 40)
        self.assertEqual(status["ca-nr"][1]["rssi-rx3-dbm"], -48.0)

    def test_builds_carriers_when_uiwwand_omits_them(self) -> None:
        status: dict[str, object] = {}
        merge_sierra_nrinfo(status, NRINFO)
        self.assertEqual([item["band"] for item in status["ca-nr"]], [1, 78])

    def test_not_available_is_empty(self) -> None:
        self.assertEqual(parse_sierra_nrinfo("!NRINFO: Not Available\nOK"), [])

    def test_accepts_numeric_mmw_label_used_by_em92_firmware(self) -> None:
        output = NRINFO.replace("NR5G(sub6) Rx0", "NR5G(mmw) Rx0")
        self.assertEqual(parse_sierra_nrinfo(output)[0]["rssi-rx0-dbm"], -47.1)


class SierraLteInfoTests(unittest.TestCase):
    def test_parses_primary_and_secondary_carriers(self) -> None:
        carriers = parse_sierra_lteinfo(LTEINFO)

        self.assertEqual(len(carriers), 2)
        self.assertEqual(carriers[0]["band"], 3)
        self.assertEqual(carriers[0]["dl-bw-mhz"], 15)
        self.assertEqual(carriers[0]["ul-bw-mhz"], 15)
        self.assertEqual(carriers[0]["rssi-dbm"], -34.9)
        self.assertEqual(carriers[1]["dl-earfcn"], 1617)
        self.assertEqual(carriers[1]["rssi-dbm"], -55.5)

    def test_merges_lte_carriers_by_band_and_channel(self) -> None:
        status = {
            "ca-lte": [
                {"primary": True, "band": 3, "dl-earfcn": 1791},
                {"primary": False, "band": 3, "dl-earfcn": 1617},
            ]
        }

        merge_sierra_lteinfo(status, LTEINFO)

        self.assertEqual(status["ca-lte"][0]["rssi-dbm"], -34.9)
        self.assertEqual(status["ca-lte"][1]["rssi-dbm"], -55.5)
