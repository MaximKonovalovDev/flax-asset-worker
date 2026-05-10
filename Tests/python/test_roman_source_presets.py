from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import os
import unittest
from unittest.mock import patch

from assetboy.workflows.roman_launchers import emit_roman_launcher_manifest
from assetboy.workflows.roman_source_presets import emit_roman_source_presets


class RomanSourcePresetTests(unittest.TestCase):
    def test_emit_roman_source_presets_converts_launchers_into_runnable_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "here"
            launcher_dir = repo_root / "launchers" / "roman_arena"
            scripts_dir = repo_root / "scripts"
            archive_dir = scripts_dir / "archive"
            experimental_dir = scripts_dir / "experimental"
            checklist_dir = repo_root / "docs" / "game-studio" / "projects" / "roman_arena"
            launcher_output_dir = Path(temp_dir) / "launchers_out"
            preset_output_dir = Path(temp_dir) / "presets_out"

            archive_dir.mkdir(parents=True, exist_ok=True)
            experimental_dir.mkdir(parents=True, exist_ok=True)
            checklist_dir.mkdir(parents=True, exist_ok=True)
            launcher_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "flaxmcp-asset-frontdoor-ui.ps1").write_text("# current ui\n", encoding="utf-8")
            (experimental_dir / "flaxmcp-roman-manual-source-helper.ps1").write_text("# current helper\n", encoding="utf-8")
            (checklist_dir / "ENV_SOURCE_CHECKLIST.md").write_text("# Environment\n", encoding="utf-8")

            (launcher_dir / "ROMAN_ENVIRONMENT_ASSETS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "UI_PS=.\\scripts\\flaxmcp-asset-frontdoor-ui.ps1"',
                        'set "QUEUE_FILE=artifacts\\quality\\asset-download-jobs\\queue.csv"',
                        'set "GAME_SCOPE=roman_arena"',
                        'set "PACK_ID=RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_ENVIRONMENT_DOWNLOADS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "HELPER_PS=.\\scripts\\experimental\\flaxmcp-roman-manual-source-helper.ps1"',
                        'set "PACK_ID=RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"',
                        'set "CHECKLIST=knowledge\\game-studio\\projects\\roman_arena\\ENV_SOURCE_CHECKLIST.md"',
                        'pwsh.exe -File "%HELPER_PS%" -SourceUrlList "https://example.com/arena.zip|https://example.com/gallery"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_ANIMATIONS_ASSETS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "UI_PS=.\\scripts\\flaxmcp-asset-frontdoor-ui.ps1"',
                        'set "QUEUE_FILE=artifacts\\quality\\asset-download-jobs\\queue.csv"',
                        'set "GAME_SCOPE=roman_arena"',
                        'set "PACK_ID=RA_PACK_ANM_COMBAT_SLICE_01"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_PLAYER_ASSETS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "UI_PS=.\\scripts\\flaxmcp-asset-frontdoor-ui.ps1"',
                        'set "QUEUE_FILE=artifacts\\quality\\asset-download-jobs\\queue.csv"',
                        'set "GAME_SCOPE=roman_arena"',
                        'set "PACK_ID=RA_PACK_CHR_PLAYER_SLICE_01"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_PLAYER_DOWNLOADS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "HELPER_PS=.\\scripts\\experimental\\flaxmcp-roman-manual-source-helper.ps1"',
                        'set "PACK_ID=RA_PACK_CHR_PLAYER_SLICE_01"',
                        'pwsh.exe -File "%HELPER_PS%" -SourceUrlList "https://example.com/player-pack"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_MAKEHUMAN_DOWNLOADS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'start "" "https://files.example.com/makehuman_base.zip"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            launcher_artifacts = emit_roman_launcher_manifest(
                game_scope="roman_arena",
                output_dir=launcher_output_dir,
                repo_root=repo_root,
            )

            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                preset_artifacts = emit_roman_source_presets(
                    game_scope="roman_arena",
                    output_dir=preset_output_dir,
                    launcher_manifest_path=launcher_artifacts.manifest_path,
                )

            self.assertTrue(preset_artifacts.manifest_path.exists())
            self.assertTrue(preset_artifacts.summary_path.exists())

            payload = json.loads(preset_artifacts.manifest_path.read_text(encoding="utf-8"))
            pack_results = {item["pack_id"]: item for item in payload["pack_results"]}
            helper_results = {item["group"]: item for item in payload["helper_results"]}

            environment = pack_results["RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"]
            self.assertEqual(environment["status"], "emitted")
            self.assertTrue(Path(environment["direct_url_queue"]).exists())
            self.assertEqual(len(environment["browser_job_dirs"]), 1)

            with Path(environment["direct_url_queue"]).open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["pack_id"], "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01")
            self.assertEqual(rows[0]["url"], "https://example.com/arena.zip")

            env_browser_job = json.loads(
                (Path(environment["browser_job_dirs"][0]) / "browser_job.json").read_text(encoding="utf-8")
            )
            self.assertEqual(env_browser_job["source_adapter"], "roman_manual_source")
            self.assertEqual(env_browser_job["source_url"], "https://example.com/gallery")

            animations = pack_results["RA_PACK_ANM_COMBAT_SLICE_01"]
            self.assertEqual(animations["status"], "emitted")
            self.assertEqual(len(animations["browser_job_dirs"]), 1)
            animation_job = json.loads(
                (Path(animations["browser_job_dirs"][0]) / "browser_job.json").read_text(encoding="utf-8")
            )
            self.assertEqual(animation_job["source_adapter"], "mixamo_animations")
            self.assertEqual(animation_job["source_url"], "https://www.mixamo.com/")
            self.assertNotIn("RA_PACK_CHR_PLAYER_SLICE_01", pack_results)

            makehuman = helper_results["makehuman"]
            self.assertEqual(makehuman["status"], "emitted")
            self.assertTrue(Path(makehuman["direct_url_queue"]).exists())
            with Path(makehuman["direct_url_queue"]).open("r", encoding="utf-8", newline="") as handle:
                helper_rows = list(csv.DictReader(handle))
            self.assertEqual(helper_rows[0]["pack_id"], "RA_PACK_CHR_MAKEHUMAN_BASELINE_01")


if __name__ == "__main__":
    unittest.main()
