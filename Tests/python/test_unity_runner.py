from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import tarfile
import unittest

from assetboy.providers.unity_runner import (
    emit_unity_export_runner,
    extract_open_assets_from_runner_job,
    extract_open_assets_from_unitypackage,
    list_unity_installations,
)


class UnityRunnerTests(unittest.TestCase):
    @staticmethod
    def _write_unitypackage(path: Path, items: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for index, (asset_path, content) in enumerate(items.items(), start=1):
                root = f"{index:032x}"[:32]
                pathname_bytes = asset_path.encode("utf-8") + b"\x00"
                pathname_info = tarfile.TarInfo(f"{root}/pathname")
                pathname_info.size = len(pathname_bytes)
                archive.addfile(pathname_info, io.BytesIO(pathname_bytes))

                asset_info = tarfile.TarInfo(f"{root}/asset")
                asset_info.size = len(content)
                archive.addfile(asset_info, io.BytesIO(content))

                meta_bytes = b"fileFormatVersion: 2\n"
                meta_info = tarfile.TarInfo(f"{root}/asset.meta")
                meta_info.size = len(meta_bytes)
                archive.addfile(meta_info, io.BytesIO(meta_bytes))

    def test_list_unity_installations_detects_editor_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            version_dir = root / "2022.3.20f1"
            editor = version_dir / "Editor" / "Unity.exe"
            editor.parent.mkdir(parents=True, exist_ok=True)
            editor.write_text("", encoding="utf-8")

            installs = list_unity_installations(search_roots=(root,))

            self.assertEqual(len(installs), 1)
            self.assertTrue(installs[0].usable)
            self.assertEqual(installs[0].version, "2022.3.20f1")

    def test_emit_unity_export_runner_writes_runner_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            unity_root = root / "2022.3.20f1"
            editor = unity_root / "Editor" / "Unity.exe"
            editor.parent.mkdir(parents=True, exist_ok=True)
            editor.write_text("", encoding="utf-8")

            blender_root = root / "Blender Foundation" / "Blender 5.0"
            blender_root.mkdir(parents=True, exist_ok=True)
            (blender_root / "blender.exe").write_text("", encoding="utf-8")

            project_path = root / "ThrowawayUnityProject"
            (project_path / "Assets").mkdir(parents=True, exist_ok=True)
            output_dir = root / "generated"

            artifacts = emit_unity_export_runner(
                pack_id="RA_PACK_ENV_ARCH_UNITY_SLICE_01",
                game_scope="roman_arena",
                source_url="https://assetstore.unity.com/packages/example",
                license_note="Licensed Unity package owned by operator.",
                project_path=project_path,
                package_root="Assets/RomanArena",
                asset_paths=("Assets/RomanArena/Models/SM_ArenaWall.fbx",),
                unitypackage_paths=("C:/downloads/RomanArena.unitypackage",),
                source_package_name="Roman Arena Unity Kit",
                asset_kind="architecture",
                output_dir=output_dir,
                unity_search_roots=(root,),
                blender_search_roots=(root / "Blender Foundation",),
            )

            self.assertTrue(artifacts.engine_job_spec_path.exists())
            self.assertTrue(artifacts.runner_job_path.exists())
            self.assertTrue(artifacts.powershell_path.exists())
            self.assertTrue(artifacts.unity_csharp_path.exists())
            self.assertTrue(artifacts.blender_handoff_path.exists())
            self.assertTrue(artifacts.launch_command_path.exists())

            runner_payload = json.loads(artifacts.runner_job_path.read_text(encoding="utf-8"))
            self.assertEqual(runner_payload["project_path"], str(project_path))
            self.assertEqual(runner_payload["package_root"], "Assets/RomanArena")
            self.assertEqual(runner_payload["asset_paths"], ["Assets/RomanArena/Models/SM_ArenaWall.fbx"])
            self.assertEqual(runner_payload["unitypackage_paths"], ["C:/downloads/RomanArena.unitypackage"])
            self.assertEqual(runner_payload["editor_path_hint"], str(editor))
            runner_script = artifacts.powershell_path.read_text(encoding="utf-8")
            self.assertIn('-createProject "$ProjectPath"', runner_script)
            self.assertIn("extract_open_assets_from_runner_job", runner_script)
            unity_csharp = artifacts.unity_csharp_path.read_text(encoding="utf-8")
            self.assertIn("unitypackage_paths", unity_csharp)
            self.assertIn("AssetDatabase.ImportPackage(packagePath, false);", unity_csharp)

            handoff_payload = json.loads(artifacts.blender_handoff_path.read_text(encoding="utf-8"))
            self.assertEqual(handoff_payload["blender_executable_hint"], str(blender_root / "blender.exe"))

    def test_extract_open_assets_from_unitypackage_exports_open_formats(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_path = root / "dummy.unitypackage"
            output_dir = root / "exports"
            self._write_unitypackage(
                package_path,
                {
                    "Assets/Kevin Iglesias/Human Character Dummy/Models/HumanCharacterDummy_M.fbx": b"fbx-bytes",
                    "Assets/Kevin Iglesias/Human Character Dummy/Textures/HumanCharacterDummy_ColorPalette.png": b"png-bytes",
                    "Assets/Kevin Iglesias/Human Character Dummy/Prefabs/HumanDummy.prefab": b"prefab-bytes",
                },
            )

            summary = extract_open_assets_from_unitypackage(
                package_path=package_path,
                output_dir=output_dir,
                package_root="Assets/Kevin Iglesias/Human Character Dummy",
            )

            self.assertEqual(summary["exported_count"], 2)
            self.assertTrue((output_dir / "Models" / "HumanCharacterDummy_M.fbx").exists())
            self.assertTrue((output_dir / "Textures" / "HumanCharacterDummy_ColorPalette.png").exists())
            self.assertFalse((output_dir / "Prefabs" / "HumanDummy.prefab").exists())

    def test_extract_open_assets_from_runner_job_writes_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_path = root / "motions.unitypackage"
            staged_dir = root / "staged"
            runner_json = root / "unity_export_runner.json"
            self._write_unitypackage(
                package_path,
                {
                    "Assets/Kevin Iglesias/Human Animations/Animations/Male/Movement/Jump/HumanM@Jump01.fbx": b"jump",
                    "Assets/Kevin Iglesias/Human Animations/Animations/Male/Movement/Jump/HumanM@Land01.fbx": b"land",
                    "Assets/Kevin Iglesias/Human Animations/Docs/readme.pdf": b"pdf",
                },
            )
            runner_json.write_text(
                json.dumps(
                    {
                        "asset_paths": [],
                        "export_formats": ["fbx", "png", "wav"],
                        "package_root": "Assets/Kevin Iglesias/Human Animations",
                        "staged_export_dir": str(staged_dir),
                        "unitypackage_paths": [str(package_path)],
                    }
                ),
                encoding="utf-8",
            )

            summary = extract_open_assets_from_runner_job(runner_json)

            self.assertEqual(summary["exported_count"], 2)
            self.assertTrue((staged_dir / "Animations" / "Male" / "Movement" / "Jump" / "HumanM@Jump01.fbx").exists())
            export_summary = json.loads((staged_dir / "export_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(export_summary["mode"], "unitypackage_direct_extract")
