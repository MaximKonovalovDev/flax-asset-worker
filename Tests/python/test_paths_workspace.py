from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from assetboy.library import paths


class WorkspacePathTests(unittest.TestCase):
    def test_project_root_uses_workspace_json_when_env_override_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "AssetBoy"
            app_root.mkdir(parents=True, exist_ok=True)
            repo_root = Path(temp_dir) / "here"
            repo_root.mkdir(parents=True, exist_ok=True)
            workspace_path = app_root / "assetboy.workspace.json"
            workspace_path.write_text(
                '{\n  "flax_repo_root": "' + str(repo_root).replace("\\", "\\\\") + '"\n}\n',
                encoding="utf-8",
            )

            with patch.object(paths, "assetboy_root", return_value=app_root):
                with patch.dict("os.environ", {"ASSETBOY_FLAX_REPO_ROOT": ""}, clear=False):
                    self.assertEqual(paths.project_root(), repo_root.resolve())

    def test_project_root_falls_back_to_assetboy_root_when_no_workspace(self) -> None:
        """Path B v1.3 (2026-05-11): project_root no longer raises when
        nothing is configured; it self-hosts at assetboy_root() instead.

        Old contract (game-factory era): FileNotFoundError mentioning
        ``assetboy.workspace.json``. Standalone FAW doesn't need a
        workspace config to function — its own repo IS the workspace.
        """
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "AssetBoy"
            app_root.mkdir(parents=True, exist_ok=True)

            with patch.object(paths, "assetboy_root", return_value=app_root):
                with patch.dict("os.environ", {"ASSETBOY_FLAX_REPO_ROOT": ""}, clear=False):
                    # No longer raises -- returns assetboy_root() itself.
                    result = paths.project_root()
                    self.assertEqual(result, app_root.resolve())
                    # is_workspace_configured() correctly reports False here.
                    self.assertFalse(paths.is_workspace_configured())

    def test_asset_library_root_uses_workspace_json_override_when_env_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "AssetBoy"
            app_root.mkdir(parents=True, exist_ok=True)
            library_root = Path(temp_dir) / "Google Drive" / "AssetBoyLibrary"
            workspace_path = app_root / "assetboy.workspace.json"
            workspace_path.write_text(
                '{\n'
                '  "flax_repo_root": "C:\\\\ignored",\n'
                '  "asset_library_root": "' + str(library_root).replace("\\", "\\\\") + '"\n'
                '}\n',
                encoding="utf-8",
            )

            with patch.object(paths, "assetboy_root", return_value=app_root):
                with patch.dict("os.environ", {"FLAX_ASSET_LIBRARY_ROOT": ""}, clear=False):
                    self.assertEqual(paths.asset_library_root(), library_root.resolve())

    def test_asset_library_layout_paths_include_manual_drop_and_publish_roots(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir) / "library"
            with patch.object(paths, "asset_library_root", return_value=library_root.resolve()):
                layout = paths.asset_library_layout_paths()

        self.assertEqual(layout[0], library_root.resolve())
        self.assertIn((library_root / "inbox" / "downloads" / "manual_drop").resolve(), layout)
        self.assertIn((library_root / "publish" / "flax_intake").resolve(), layout)
