"""Tests for entity-ID generation and migration."""

from __future__ import annotations

import unittest

from custom_components.u5g_control.entity_ids import (
    suggested_entity_suffix,
)


class EntityIdTests(unittest.TestCase):
    def test_band_switch_suffixes_include_radio_prefix(self) -> None:
        self.assertEqual(suggested_entity_suffix("switch:lte:1"), "lte_b1")
        self.assertEqual(suggested_entity_suffix("switch:sa:78"), "sa_n78")
        self.assertEqual(suggested_entity_suffix("switch:nsa:1"), "nsa_n1")

    def test_mode_switch_suffix(self) -> None:
        self.assertEqual(
            suggested_entity_suffix("switch:enable_sa"), "enable_5g_sa"
        )

