import unittest

from assetboy.library.paths import asset_library_root, assetboy_root, project_root


class PathsSmokeTests(unittest.TestCase):
    def test_assetboy_root_ends_at_app_folder(self) -> None:
        root = assetboy_root()
        self.assertIn(root.name, {"AssetBoy", "asset_factory"})

    def test_project_root_ends_at_workspace(self) -> None:
        root = project_root()
        self.assertTrue((root / "AGENTS.md").exists())
        self.assertTrue((root / "GameProjectFlax").exists())

    def test_asset_library_root_uses_repo_default(self) -> None:
        path = asset_library_root()
        self.assertTrue(str(path).endswith(r"artifacts\library\FlaxAssetLibrary"))
