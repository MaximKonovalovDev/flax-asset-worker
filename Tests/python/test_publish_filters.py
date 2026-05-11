import unittest

from assetboy.cli_legacy import _filter_publish_packs, _is_example_pack_id


class PublishFilterTests(unittest.TestCase):
    def test_is_example_pack_id_detects_example_prefix(self) -> None:
        self.assertTrue(_is_example_pack_id("RA_PACK_EXAMPLE_UI_01"))
        self.assertFalse(_is_example_pack_id("RA_PACK_WPN_COMBAT_SLICE_01"))

    def test_filter_publish_packs_omits_examples_by_default(self) -> None:
        packs = [
            {"pack_id": "RA_PACK_EXAMPLE_UI_01"},
            {"pack_id": "RA_PACK_WPN_COMBAT_SLICE_01"},
        ]

        filtered, omitted = _filter_publish_packs(packs, include_examples=False)

        self.assertEqual(filtered, [{"pack_id": "RA_PACK_WPN_COMBAT_SLICE_01"}])
        self.assertEqual(omitted, 1)
