from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.unreal_runner import emit_unreal_export_runner, list_unreal_installations


class UnrealRunnerTests(unittest.TestCase):
    def test_list_unreal_installations_detects_usable_editor_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ue5 = root / "UE_5.3"
            cmd_path = ue5 / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
            gui_path = ue5 / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
            cmd_path.parent.mkdir(parents=True, exist_ok=True)
            cmd_path.write_text("", encoding="utf-8")
            gui_path.write_text("", encoding="utf-8")

            installs = list_unreal_installations(search_roots=(root,))

            self.assertEqual(len(installs), 1)
            self.assertTrue(installs[0].usable)
            self.assertEqual(installs[0].version, "5.3")

    def test_emit_unreal_export_runner_writes_runner_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ue_root = root / "UE_5.3"
            cmd_path = ue_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
            gui_path = ue_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
            cmd_path.parent.mkdir(parents=True, exist_ok=True)
            cmd_path.write_text("", encoding="utf-8")
            gui_path.write_text("", encoding="utf-8")

            blender_root = root / "Blender Foundation" / "Blender 5.0"
            blender_root.mkdir(parents=True, exist_ok=True)
            (blender_root / "blender.exe").write_text("", encoding="utf-8")

            project_file = root / "Throwaway.uproject"
            project_file.write_text("{}", encoding="utf-8")
            output_dir = root / "generated"

            artifacts = emit_unreal_export_runner(
                pack_id="RA_PACK_ENV_ARCH_UE_SLICE_01",
                game_scope="roman_arena",
                source_url="https://www.fab.com/listings/example",
                license_note="Licensed Fab package owned by operator.",
                project_file=project_file,
                package_root="/Game/RomanArena",
                asset_paths=("/Game/RomanArena/Meshes/SM_ArenaWall",),
                source_package_name="Roman Arena UE Kit",
                asset_kind="architecture",
                output_dir=output_dir,
                unreal_search_roots=(root,),
                blender_search_roots=(root / "Blender Foundation",),
            )

            self.assertTrue(artifacts.engine_job_spec_path.exists())
            self.assertTrue(artifacts.runner_job_path.exists())
            self.assertTrue(artifacts.powershell_path.exists())
            self.assertTrue(artifacts.unreal_python_path.exists())
            self.assertTrue(artifacts.blender_handoff_path.exists())
            self.assertTrue(artifacts.launch_command_path.exists())

            runner_payload = json.loads(artifacts.runner_job_path.read_text(encoding="utf-8"))
            self.assertEqual(runner_payload["project_file"], str(project_file))
            self.assertEqual(runner_payload["package_root"], "/Game/RomanArena")
            self.assertEqual(runner_payload["asset_paths"], ["/Game/RomanArena/Meshes/SM_ArenaWall"])
            self.assertEqual(runner_payload["editor_cmd_path_hint"], str(cmd_path))

            handoff_payload = json.loads(artifacts.blender_handoff_path.read_text(encoding="utf-8"))
            self.assertEqual(handoff_payload["blender_executable_hint"], str(blender_root / "blender.exe"))
