from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.workflows.roman_launchers import emit_roman_launcher_manifest


class RomanLauncherManifestTests(unittest.TestCase):
    def test_emit_roman_launcher_manifest_imports_pack_and_helper_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "here"
            launcher_dir = repo_root / "launchers" / "roman_arena"
            scripts_dir = repo_root / "scripts"
            archive_dir = scripts_dir / "archive"
            experimental_dir = scripts_dir / "experimental"
            checklist_dir = repo_root / "docs" / "game-studio" / "projects" / "roman_arena"
            output_dir = Path(temp_dir) / "out"

            archive_dir.mkdir(parents=True, exist_ok=True)
            experimental_dir.mkdir(parents=True, exist_ok=True)
            checklist_dir.mkdir(parents=True, exist_ok=True)
            launcher_dir.mkdir(parents=True, exist_ok=True)

            (scripts_dir / "flaxmcp-asset-frontdoor-ui.ps1").write_text("# current ui\n", encoding="utf-8")
            (experimental_dir / "flaxmcp-roman-manual-source-helper.ps1").write_text("# current helper\n", encoding="utf-8")
            (checklist_dir / "WEAPON_SOURCE_CHECKLIST.md").write_text("# Weapons\n", encoding="utf-8")
            (checklist_dir / "MIXAMO_SHARED_BASELINE_CHECKLIST.md").write_text("# Mixamo\n", encoding="utf-8")

            (launcher_dir / "ROMAN_WEAPONS_ASSETS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "UI_PS=.\\scripts\\flaxmcp-asset-frontdoor-ui.ps1"',
                        'set "QUEUE_FILE=artifacts\\quality\\asset-download-jobs\\queue.csv"',
                        'set "GAME_SCOPE=roman_arena"',
                        'set "PACK_ID=RA_PACK_WPN_COMBAT_SLICE_01"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_WEAPONS_DOWNLOADS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "HELPER_PS=.\\scripts\\experimental\\flaxmcp-roman-manual-source-helper.ps1"',
                        'set "PACK_ID=RA_PACK_WPN_COMBAT_SLICE_01"',
                        'set "CHECKLIST=knowledge\\game-studio\\projects\\roman_arena\\WEAPON_SOURCE_CHECKLIST.md"',
                        'pwsh.exe -File "%HELPER_PS%" -SourceUrlList "https://example.com/weapons|https://example.com/weapons-drive"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (launcher_dir / "ROMAN_MIXAMO_BASELINE_DOWNLOADS.bat").write_text(
                "\n".join(
                    [
                        '@echo off',
                        'set "CHECKLIST=.\\knowledge\\game-studio\\projects\\roman_arena\\MIXAMO_SHARED_BASELINE_CHECKLIST.md"',
                        'start "" "https://www.mixamo.com/"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            artifacts = emit_roman_launcher_manifest(
                game_scope="roman_arena",
                output_dir=output_dir,
                repo_root=repo_root,
            )

            self.assertTrue(artifacts.manifest_path.exists())
            self.assertTrue(artifacts.summary_path.exists())
            self.assertTrue((artifacts.source_manifests_dir / "RA_PACK_WPN_COMBAT_SLICE_01.json").exists())

            manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["game_scope"], "roman_arena")
            self.assertEqual(len(manifest["pack_presets"]), 1)
            self.assertEqual(len(manifest["global_helpers"]), 1)

            preset = manifest["pack_presets"][0]
            self.assertEqual(preset["pack_id"], "RA_PACK_WPN_COMBAT_SLICE_01")
            self.assertEqual(preset["asset_launcher"]["mode"], "asset_ui")
            self.assertTrue(preset["asset_launcher"]["recommended_script_exists"])
            self.assertEqual(
                preset["source_manifest"]["source_urls"],
                ["https://example.com/weapons", "https://example.com/weapons-drive"],
            )
            self.assertTrue(
                preset["assetboy_drop_target"].endswith(r"artifacts\library\FlaxAssetLibrary\inbox\downloads\manual_drop\RA_PACK_WPN_COMBAT_SLICE_01")
            )

            helper = manifest["global_helpers"][0]
            self.assertEqual(helper["mode"], "browser_open")
            self.assertEqual(helper["source_urls"], ["https://www.mixamo.com/"])
            self.assertEqual(len(manifest["stale_script_references"]), 0)
