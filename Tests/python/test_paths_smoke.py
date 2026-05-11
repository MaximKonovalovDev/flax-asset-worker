import unittest

from assetboy.library.paths import (
    asset_library_root,
    assetboy_root,
    is_workspace_configured,
    project_root,
)


class PathsSmokeTests(unittest.TestCase):
    """Path B v1.3 (2026-05-11): rebased to standalone flax-asset-worker layout.

    The original tests assumed the legacy game-factory workspace shape
    (assetboy folder named "AssetBoy"/"asset_factory", AGENTS.md +
    GameProjectFlax/ at parent). The s0-rescued standalone repo has a
    different layout; the production code learned a self-hosting fallback
    (project_root -> assetboy_root when no game-factory workspace nearby).
    Tests updated to verify the fallback + accept either layout.
    """

    def test_assetboy_root_resolves_to_repo(self) -> None:
        # Standalone: 'flax-asset-worker'. Legacy game-factory: 'AssetBoy'
        # or 'asset_factory'. All three are valid Path B-era anchors.
        root = assetboy_root()
        self.assertIn(
            root.name,
            {"AssetBoy", "asset_factory", "flax-asset-worker"},
        )

    def test_project_root_resolves_to_a_real_directory(self) -> None:
        # Always returns a real path (never raises post-v1.3 self-hosting
        # fallback). If workspace IS configured the dir should contain a
        # GameProjectFlax/ + AGENTS.md (game-factory shape); if not, it's
        # the standalone repo itself.
        root = project_root()
        self.assertTrue(root.exists() and root.is_dir())
        if is_workspace_configured():
            self.assertTrue(
                (root / "GameProjectFlax").exists() or (root / "AGENTS.md").exists(),
                f"workspace_configured but neither GameProjectFlax/ nor AGENTS.md at {root}",
            )

    def test_asset_library_root_uses_repo_default(self) -> None:
        path = asset_library_root()
        self.assertTrue(
            str(path).endswith(r"artifacts\library\FlaxAssetLibrary")
            or str(path).endswith(r"artifacts/library/FlaxAssetLibrary"),
            f"unexpected asset_library_root: {path}",
        )
