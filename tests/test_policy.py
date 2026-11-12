"""Tests for the standalone U5G radio policy engine."""

from __future__ import annotations

import unittest

from custom_components.u5g_control.models import (
    RadioPreference,
    SimProfile,
    format_band_list,
    parse_band_list,
    sim_display_name,
    sim_identifier,
)
from custom_components.u5g_control.policy import (
    PolicyError,
    build_preference,
    infer_mode_flags,
    initial_sim_radio_state,
    should_apply_sim_profile,
    with_band,
)


def profile() -> SimProfile:
    return SimProfile(
        sim_id="abc",
        iccid="8900000000000005244",
        name="O2 [5244]",
        selected_lte_bands={1, 3, 7, 20},
        selected_sa_bands={1, 7, 28, 78},
        selected_nsa_bands={1, 7, 78},
    )


class PolicyTests(unittest.TestCase):
    def test_new_sim_uses_baseline_not_previous_live_masks(self) -> None:
        baseline = RadioPreference(
            mode="5gnr,lte",
            lte_bands={1, 3, 20},
            sa_bands={1, 28, 78, 79},
            nsa_bands={1, 78, 79},
        )
        state = initial_sim_radio_state(
            baseline, 79, 79, {1, 28, 78}, {1, 78}
        )
        self.assertEqual(
            state,
            (True, True, {1, 3, 20}, {1, 28, 78}, {1, 78}),
        )

    def test_disabled_baseline_architecture_seeds_recoverable_bands(self) -> None:
        baseline = RadioPreference(
            mode="5gnr,lte",
            lte_bands={3, 20},
            sa_bands={79},
            nsa_bands={1, 78},
        )
        state = initial_sim_radio_state(
            baseline, 79, 79, {1, 28, 78}, {1, 78}
        )
        self.assertEqual(
            state,
            (False, True, {3, 20}, {1, 28, 78}, {1, 78}),
        )

    def test_profile_is_applied_on_new_or_changed_sim(self) -> None:
        self.assertTrue(
            should_apply_sim_profile(
                is_new=True,
                previous_sim_id="sim-a",
                current_sim_id="sim-b",
                auto_reapply=False,
            )
        )
        self.assertTrue(
            should_apply_sim_profile(
                is_new=False,
                previous_sim_id="sim-a",
                current_sim_id="sim-b",
                auto_reapply=False,
            )
        )
        self.assertFalse(
            should_apply_sim_profile(
                is_new=False,
                previous_sim_id="sim-a",
                current_sim_id="sim-a",
                auto_reapply=False,
            )
        )

    def test_band_parser_and_formatter(self) -> None:
        self.assertEqual(parse_band_list("78,1, 7"), {1, 7, 78})
        self.assertEqual(format_band_list({78, 1, 7}), "1,7,78")

    def test_sim_identity_and_name(self) -> None:
        self.assertEqual(sim_display_name("O2", 234, 10, "8900000000000005244"), "O2 [5244]")
        self.assertEqual(sim_identifier("modem", "123"), sim_identifier("modem", "123"))
        self.assertNotEqual(sim_identifier("modem", "123"), sim_identifier("modem", "124"))

    def test_all_four_mode_combinations(self) -> None:
        item = profile()
        self.assertEqual(build_preference(item, 79).mode, "5gnr,lte")

        item.nsa_enabled = False
        result = build_preference(item, 79)
        self.assertEqual(result.mode, "5gnr")
        self.assertEqual(result.nsa_bands, {79})

        item.sa_enabled = False
        item.nsa_enabled = True
        result = build_preference(item, 79)
        self.assertEqual(result.mode, "5gnr,lte")
        self.assertEqual(result.sa_bands, {79})

        item.nsa_enabled = False
        result = build_preference(item, 79)
        self.assertEqual(result.mode, "lte")
        self.assertEqual(result.sa_bands, {79})
        self.assertEqual(result.nsa_bands, {79})

    def test_infer_mode_flags(self) -> None:
        pref = RadioPreference(mode="5gnr,lte", sa_bands={79}, nsa_bands={1, 78})
        self.assertEqual(infer_mode_flags(pref, 79), (False, True))

    def test_writable_comparison_ignores_network_selection(self) -> None:
        first = RadioPreference(mode="lte", lte_bands={3, 20}, net_selection="automatic")
        second = RadioPreference(mode="lte", lte_bands={3, 20}, net_selection="manual")
        self.assertNotEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.writable_dict(), second.writable_dict())

    def test_disabled_band_cannot_be_selected_for_active_nr(self) -> None:
        item = profile()
        item.selected_sa_bands.add(79)
        with self.assertRaises(PolicyError):
            build_preference(item, 79)

    def test_sa_only_allows_empty_lte_mask(self) -> None:
        item = profile()
        item.nsa_enabled = False
        item.selected_lte_bands = set()
        result = build_preference(item, 79)
        self.assertEqual(result.mode, "5gnr")
        self.assertEqual(result.lte_bands, set())

    def test_sa_only_allows_removing_final_lte_band(self) -> None:
        item = profile()
        item.nsa_enabled = False
        item.selected_lte_bands = {20}
        changed = with_band(item, "lte", 20, False)
        self.assertEqual(changed.selected_lte_bands, set())

    def test_nsa_and_lte_only_require_lte_band(self) -> None:
        item = profile()
        item.selected_lte_bands = set()
        with self.assertRaises(PolicyError):
            build_preference(item, 79)
        item.sa_enabled = False
        item.nsa_enabled = False
        with self.assertRaises(PolicyError):
            build_preference(item, 79)

    def test_profile_persists_restore_placeholder_metadata(self) -> None:
        item = profile()
        item.default_preference_placeholder = 79
        item.last_good_preference_placeholder = 77
        item.current_preference = RadioPreference(mode="5gnr", sa_bands={78})
        item.current_preference_placeholder = 79
        restored = SimProfile.from_dict(item.to_dict())
        self.assertEqual(restored.default_preference_placeholder, 79)
        self.assertEqual(restored.last_good_preference_placeholder, 77)
        self.assertEqual(restored.current_preference.sa_bands, {78})
        self.assertEqual(restored.current_preference_placeholder, 79)

    def test_last_active_band_is_protected(self) -> None:
        item = profile()
        item.selected_sa_bands = {28}
        with self.assertRaises(PolicyError):
            with_band(item, "sa", 28, False)

    def test_disabled_architecture_can_have_empty_saved_mask(self) -> None:
        item = profile()
        item.sa_enabled = False
        item.selected_sa_bands = {28}
        changed = with_band(item, "sa", 28, False)
        self.assertEqual(changed.selected_sa_bands, set())


if __name__ == "__main__":
    unittest.main()
