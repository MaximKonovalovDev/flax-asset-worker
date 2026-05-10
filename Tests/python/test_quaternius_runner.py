"""
test_quaternius_runner.py — Smoke tests for the Quaternius direct-download runner.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from assetboy.execution.quaternius_runner import (
    QUATERNIUS_PRESETS,
    list_presets,
    run_quaternius_batch,
    run_quaternius_presets,
)


class QuaterniusRunnerTests(unittest.TestCase):

    def test_list_presets_returns_five_entries(self) -> None:
        presets = list_presets()
        self.assertEqual(len(presets), 5)
        for pid, url, desc in presets:
            self.assertTrue(pid.startswith("SHARED_QUAT_"), f"Bad pack_id prefix: {pid}")
            self.assertTrue(url.startswith("https://"), f"Bad URL: {url}")
            self.assertGreater(len(desc), 5, "Description too short")

    def test_preset_list_matches_constant(self) -> None:
        self.assertEqual(len(QUATERNIUS_PRESETS), 5)

    def test_dry_run_writes_no_files(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "quat_dry"
            result = run_quaternius_batch(
                pack_id="SHARED_QUAT_ULTIMATE_WEAPONS_01",
                source_url="https://quaternius.com/packs/ultimateweapons.html",
                output_dir=out,
                dry_run=True,
            )
            self.assertTrue(result.dry_run)
            self.assertEqual(len(result.files_extracted), 0)
            self.assertEqual(result.pack_id, "SHARED_QUAT_ULTIMATE_WEAPONS_01")
            # provenance.json should NOT be written in dry-run
            self.assertFalse((out / "provenance.json").exists())

    def test_dry_run_presets_returns_five_results(self) -> None:
        results = run_quaternius_presets(game_scope="shared", dry_run=True)
        self.assertEqual(len(results), 5)
        for r in results:
            self.assertTrue(r.dry_run)
            self.assertEqual(len(r.files_extracted), 0)


if __name__ == "__main__":
    unittest.main()
