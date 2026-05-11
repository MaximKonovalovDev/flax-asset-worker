"""Tests for assetboy.execution.stable_audio_runner (Path B v1.4.1)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class StableAudioRunnerTests(unittest.TestCase):

    def setUp(self) -> None:
        from assetboy.execution.stable_audio_runner import (
            STABLE_AUDIO_PRESETS,
            StableAudioBatchResult,
            is_stable_audio_available,
            run_stable_audio_batch,
        )
        self.STABLE_AUDIO_PRESETS = STABLE_AUDIO_PRESETS
        self.StableAudioBatchResult = StableAudioBatchResult
        self.is_stable_audio_available = is_stable_audio_available
        self.run_stable_audio_batch = run_stable_audio_batch

    def test_presets_have_expected_shape(self) -> None:
        """6 starter presets; each (id, prompt, duration_s)."""
        self.assertEqual(len(self.STABLE_AUDIO_PRESETS), 6)
        for preset in self.STABLE_AUDIO_PRESETS:
            self.assertEqual(len(preset), 3)
            preset_id, prompt, duration_s = preset
            self.assertIsInstance(preset_id, str)
            self.assertIsInstance(prompt, str)
            self.assertIsInstance(duration_s, int)
            self.assertGreater(duration_s, 0)
            self.assertLessEqual(duration_s, 30)

    def test_is_available_false_when_env_unset(self) -> None:
        """No model dir / runner bin -> not available."""
        with patch.dict("os.environ", {}, clear=False):
            # Clear our two env vars explicitly
            with patch.dict(
                "os.environ",
                {"STABLE_AUDIO_MODEL_DIR": "", "STABLE_AUDIO_RUNNER_BIN": ""},
                clear=False,
            ):
                self.assertFalse(self.is_stable_audio_available())

    def test_run_dry_run_emits_job_spec(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "stable_audio_out"
            result = self.run_stable_audio_batch(
                pack_id="TEST_PACK",
                prompt="forest at dawn",
                duration_s=11,
                output_dir=out,
                dry_run=True,
            )
            self.assertTrue(result.dry_run)
            self.assertIsNone(result.error)
            self.assertIsNotNone(result.job_spec_path)
            self.assertTrue(result.job_spec_path.exists())

            # Verify spec shape
            spec = json.loads(result.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(spec["pack_id"], "TEST_PACK")
            self.assertEqual(spec["prompt"], "forest at dawn")
            self.assertEqual(spec["duration_s"], 11)
            self.assertEqual(spec["license_kind"], "stability_community")
            self.assertIn("invocation_cmd", spec)

    def test_run_empty_prompt_returns_error(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            result = self.run_stable_audio_batch(
                pack_id="TEST",
                prompt="   ",  # whitespace-only
                output_dir=tmp_dir,
                dry_run=True,
            )
            self.assertIsNotNone(result.error)
            self.assertIn("empty_prompt", result.error)

    def test_run_without_model_or_bin_returns_clean_error(self) -> None:
        """Non-dry-run with no env vars set -> clean 'set env vars' message."""
        with TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out"
            with patch.dict(
                "os.environ",
                {"STABLE_AUDIO_MODEL_DIR": "", "STABLE_AUDIO_RUNNER_BIN": ""},
                clear=False,
            ):
                result = self.run_stable_audio_batch(
                    pack_id="TEST",
                    prompt="forest dawn",
                    output_dir=out,
                    dry_run=False,
                )
            self.assertIsNotNone(result.error)
            self.assertIn("stable_audio_not_available", result.error)
            # Job spec should still be written for manual invocation
            self.assertTrue(result.job_spec_path.exists())


if __name__ == "__main__":
    unittest.main()
