"""Tests for v1.11.s40 R1A provider lane adapters.

Verifies the 10 new entries in providers/lanes.SOURCE_ADAPTERS are
registered with the correct lane (DIRECT_URL) and have sensible
metadata (display_name, source_strategy, notes).
"""

from __future__ import annotations

import unittest


class R1aLaneAdapterRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.providers.lanes import SOURCE_ADAPTERS, ProviderLane
        self.adapters = SOURCE_ADAPTERS
        self.DIRECT_URL = ProviderLane.DIRECT_URL

    def _expected(self) -> list[str]:
        return [
            "met_museum_api",
            "wikimedia_commons_api",
            "archive_org_api",
            "scryfall_api",
            "iconify_api",
            "pexels_api",
            "pixabay_api",
            "unsplash_api",
            "rawg_api",
            "jamendo_api",
            # v1.13.s85 — iNaturalist (11th R1A-class provider)
            "inaturalist_api",
        ]

    def test_all_r1a_adapters_present(self) -> None:
        missing = [aid for aid in self._expected() if aid not in self.adapters]
        self.assertEqual(missing, [], msg=f"missing adapters: {missing}")

    def test_all_r1a_use_direct_url_lane(self) -> None:
        for aid in self._expected():
            with self.subTest(adapter=aid):
                self.assertEqual(self.adapters[aid].lane, self.DIRECT_URL)

    def test_all_r1a_have_display_name_and_strategy(self) -> None:
        for aid in self._expected():
            with self.subTest(adapter=aid):
                a = self.adapters[aid]
                self.assertTrue(a.display_name)
                self.assertTrue(a.source_strategy)
                self.assertTrue(a.notes)

    def test_key_required_adapters_mention_env_var(self) -> None:
        """Adapters that need env keys should mention them in notes."""
        env_var_map = {
            "pexels_api": "PEXELS_API_KEY",
            "pixabay_api": "PIXABAY_API_KEY",
            "unsplash_api": "UNSPLASH_ACCESS_KEY",
            "rawg_api": "RAWG_API_KEY",
            "jamendo_api": "JAMENDO_CLIENT_ID",
        }
        for aid, env_var in env_var_map.items():
            with self.subTest(adapter=aid):
                self.assertIn(env_var, self.adapters[aid].notes)

    def test_no_key_adapters_mention_no_api_key(self) -> None:
        """Adapters that need no key should say so."""
        no_key = [
            "met_museum_api", "wikimedia_commons_api", "archive_org_api",
            "scryfall_api", "iconify_api",
            # v1.13.s85
            "inaturalist_api",
        ]
        for aid in no_key:
            with self.subTest(adapter=aid):
                self.assertIn("No API key", self.adapters[aid].notes)

    def test_rawg_adapter_warns_reference_only(self) -> None:
        rawg = self.adapters["rawg_api"]
        self.assertIn("REFERENCE", rawg.display_name + rawg.notes)

    def test_get_adapter_returns_for_r1a_ids(self) -> None:
        from assetboy.providers.lanes import get_adapter
        for aid in self._expected():
            with self.subTest(adapter=aid):
                got = get_adapter(aid)
                self.assertEqual(got.adapter_id, aid)


if __name__ == "__main__":
    unittest.main()
