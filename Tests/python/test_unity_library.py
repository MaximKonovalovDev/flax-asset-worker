from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from assetboy import cli
from assetboy.providers.unity_library import (
    emit_unity_download_wave,
    parse_unity_download_sheet,
    select_unity_download_wave_jobs,
)


class UnityLibraryTests(unittest.TestCase):
    def test_parse_unity_download_sheet_dedupes_best_first_wave(self) -> None:
        markdown = """# Unity Links

## Wiring / Control / Motion

### Free animation and character content

| Name | Type | URL |
|---|---|---|
| Human Melee Animations FREE | Asset Store | https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785 |
| Unity Input System | GitHub | https://github.com/Unity-Technologies/InputSystem |

## Best First Wave

| Name | Type | URL |
|---|---|---|
| Human Melee Animations FREE | Asset Store | https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785 |
"""
        with TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "unity_links.md"
            source_file.write_text(markdown, encoding="utf-8")
            items = parse_unity_download_sheet(source_file)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"], "animation")
        self.assertTrue(items[0]["exportable"])
        self.assertTrue(items[0]["best_first_wave"])
        self.assertTrue(str(items[0]["pack_id"]).startswith("SHARED_UNITY_ANM_"))

    def test_emit_unity_download_wave_writes_manifest_and_splits_exportable_items(self) -> None:
        markdown = """# Unity Links

## Code / Tooling

### Asset Store tools

| Name | Type | URL |
|---|---|---|
| Odin Inspector and Serializer | Asset Store | https://assetstore.unity.com/packages/tools/utilities/odin-inspector-and-serializer-89041 |

## Wiring / Control / Motion

### Free animation and character content

| Name | Type | URL |
|---|---|---|
| Human Melee Animations FREE | Asset Store | https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785 |
| Adventure Character | Asset Store | https://assetstore.unity.com/packages/3d/characters/humanoids/humans/adventure-character-201384 |
"""
        with TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "unity_links.md"
            output_dir = Path(temp_dir) / "unity_wave"
            project_root = Path(temp_dir) / "UnityProjects"
            source_file.write_text(markdown, encoding="utf-8")

            fake_browser = SimpleNamespace(
                output_dir=output_dir / "browser",
                job_spec_path=output_dir / "browser" / "browser_job.json",
                provenance_template_path=output_dir / "browser" / "provenance_template.json",
                review_checklist_path=output_dir / "browser" / "review_checklist.md",
                payload_target_path_file=output_dir / "browser" / "payload_target.txt",
                download_target_path=output_dir / "browser" / "downloads",
            )
            fake_unity = SimpleNamespace(
                output_dir=output_dir / "unity",
                engine_job_spec_path=output_dir / "unity" / "engine_export_job.json",
                runner_job_path=output_dir / "unity" / "unity_export_runner.json",
                powershell_path=output_dir / "unity" / "run_unity_export.ps1",
                unity_csharp_path=output_dir / "unity" / "AssetBoyUnityExporter.cs",
                blender_handoff_path=output_dir / "unity" / "blender_handoff.json",
                launch_command_path=output_dir / "unity" / "launch_unity_export.txt",
                payload_target_path=output_dir / "unity" / "payload",
                editor_path_hint="C:/Program Files/Unity/Hub/Editor/6000.3.11f1/Editor/Unity.exe",
            )

            with patch("assetboy.providers.unity_library.emit_browser_automation_job", return_value=fake_browser) as emit_browser:
                with patch("assetboy.providers.unity_library.emit_unity_export_runner", return_value=fake_unity) as emit_unity:
                    report = emit_unity_download_wave(
                        source_file=source_file,
                        output_dir=output_dir,
                        project_root=project_root,
                    )
                    self.assertEqual(report["summary"]["asset_store_entries"], 3)
                    self.assertEqual(report["summary"]["browser_jobs_emitted"], 3)
                    self.assertEqual(report["summary"]["unity_export_runners_emitted"], 2)
                    self.assertTrue((output_dir / "unity_download_wave.json").exists())
                    self.assertTrue((output_dir / "unity_download_wave.md").exists())
                    self.assertEqual(emit_browser.call_count, 3)
                    self.assertEqual(emit_unity.call_count, 2)

    @unittest.skip(
        "Path B v1.3 (2026-05-11): legacy `emit-unity-download-wave` "
        "argparse subcommand was removed alongside cli_legacy.py deletion in "
        "s10.5a. The underlying emit_unity_download_wave provider function is "
        "still tested above (test_emit_unity_download_wave_*). A future "
        "Typer-side `unity download-wave` sub-command can re-add an "
        "end-to-end test then."
    )
    def test_cli_emit_unity_download_wave_uses_provider(self) -> None:
        pass

    def test_select_unity_download_wave_jobs_filters_best_first_exportable_category(self) -> None:
        report = {
            "items": [
                {
                    "name": "Human Melee Animations FREE",
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "category": "animation",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785",
                },
                {
                    "name": "Final IK",
                    "pack_id": "SHARED_UNITY_TOOL_FINAL_IK_14290",
                    "category": "tooling",
                    "best_first_wave": True,
                    "exportable": False,
                    "url": "https://assetstore.unity.com/packages/tools/animation/final-ik-14290",
                },
                {
                    "name": "The Courtyard",
                    "pack_id": "SHARED_UNITY_ENV_THE_COURTYARD_49377",
                    "category": "environment",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/essentials/tutorial-projects/the-courtyard-49377",
                },
            ],
            "browser_jobs": [
                {
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "browser_job_spec": "C:/wave/anm/browser_job.json",
                },
                {
                    "pack_id": "SHARED_UNITY_TOOL_FINAL_IK_14290",
                    "browser_job_spec": "C:/wave/finalik/browser_job.json",
                },
                {
                    "pack_id": "SHARED_UNITY_ENV_THE_COURTYARD_49377",
                    "browser_job_spec": "C:/wave/courtyard/browser_job.json",
                },
            ],
        }

        jobs = select_unity_download_wave_jobs(
            report,
            best_first_only=True,
            exportable_only=True,
            categories=("animation",),
        )

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["pack_id"], "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785")

    def test_select_unity_download_wave_jobs_asset_donor_only_skips_tooling(self) -> None:
        report = {
            "items": [
                {
                    "name": "Human Melee Animations FREE",
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "category": "animation",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785",
                },
                {
                    "name": "Final IK",
                    "pack_id": "SHARED_UNITY_TOOL_FINAL_IK_14290",
                    "category": "tooling",
                    "best_first_wave": True,
                    "exportable": False,
                    "url": "https://assetstore.unity.com/packages/tools/animation/final-ik-14290",
                },
                {
                    "name": "The Courtyard",
                    "pack_id": "SHARED_UNITY_ENV_THE_COURTYARD_49377",
                    "category": "environment",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/essentials/tutorial-projects/the-courtyard-49377",
                },
            ],
            "browser_jobs": [
                {
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "browser_job_spec": "C:/wave/anm/browser_job.json",
                },
                {
                    "pack_id": "SHARED_UNITY_TOOL_FINAL_IK_14290",
                    "browser_job_spec": "C:/wave/finalik/browser_job.json",
                },
                {
                    "pack_id": "SHARED_UNITY_ENV_THE_COURTYARD_49377",
                    "browser_job_spec": "C:/wave/courtyard/browser_job.json",
                },
            ],
        }

        jobs = select_unity_download_wave_jobs(
            report,
            best_first_only=True,
            asset_donor_only=True,
        )

        self.assertEqual(
            [job["pack_id"] for job in jobs],
            [
                "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                "SHARED_UNITY_ENV_THE_COURTYARD_49377",
            ],
        )
