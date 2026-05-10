from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from assetboy import cli


class SharedBrowserProfileCliTests(unittest.TestCase):
    @staticmethod
    def _write_seedable_source(root: Path, *, profile_name: str = "Default") -> None:
        (root / "Local State").parent.mkdir(parents=True, exist_ok=True)
        (root / "Local State").write_text('{"os_crypt":{"encrypted_key":"stub"}}', encoding="utf-8")
        profile_root = root / profile_name
        (profile_root / "Network").mkdir(parents=True, exist_ok=True)
        (profile_root / "Network" / "Cookies").write_text("cookie-db", encoding="utf-8")
        (profile_root / "Local Storage" / "leveldb").mkdir(parents=True, exist_ok=True)
        (profile_root / "Local Storage" / "leveldb" / "LOG").write_text("leveldb", encoding="utf-8")
        (profile_root / "IndexedDB" / "https_fab.com_0.indexeddb.leveldb").mkdir(parents=True, exist_ok=True)
        (profile_root / "IndexedDB" / "https_fab.com_0.indexeddb.leveldb" / "MANIFEST-000001").write_text(
            "manifest",
            encoding="utf-8",
        )

    def test_seed_shared_browser_profile_dry_run_reports_copy_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "chrome-user-data"
            target_dir = temp_root / "seeded-profile"
            self._write_seedable_source(source_root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "seed-shared-browser-profile",
                        "--source-root",
                        str(source_root),
                        "--target-dir",
                        str(target_dir),
                        "--dry-run",
                    ]
                )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("shared_browser_profile_status=dry_run", output)
        self.assertIn("shared_browser_profile_source_profile=Default", output)
        self.assertIn("shared_browser_profile_next_action_1=python scripts/cli.py asset-factory fab-auth --reuse-profile", output)
        self.assertFalse(target_dir.exists())

    def test_seed_shared_browser_profile_copies_selected_state_into_default_profile(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "chrome-user-data"
            target_dir = temp_root / "seeded-profile"
            self._write_seedable_source(source_root, profile_name="Profile 7")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "seed-shared-browser-profile",
                        "--source-root",
                        str(source_root),
                        "--source-profile",
                        "Profile 7",
                        "--target-dir",
                        str(target_dir),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue((target_dir / "Local State").exists())
            self.assertTrue((target_dir / "Default" / "Network" / "Cookies").exists())
            self.assertTrue((target_dir / "Default" / "Local Storage" / "leveldb" / "LOG").exists())
            self.assertTrue(
                (
                    target_dir
                    / "Default"
                    / "IndexedDB"
                    / "https_fab.com_0.indexeddb.leveldb"
                    / "MANIFEST-000001"
                ).exists()
            )

        output = stdout.getvalue()
        self.assertIn("shared_browser_profile_status=seeded", output)
        self.assertIn("shared_browser_profile_target_has_state=true", output)

    def test_seed_shared_browser_profile_refuses_to_overwrite_nonempty_target_without_force(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "chrome-user-data"
            target_dir = temp_root / "seeded-profile"
            self._write_seedable_source(source_root)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "placeholder.txt").write_text("existing", encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "seed-shared-browser-profile",
                        "--source-root",
                        str(source_root),
                        "--target-dir",
                        str(target_dir),
                    ]
                )

        self.assertEqual(result, 1)
        self.assertIn("shared_browser_profile_error=Target browser profile already contains data", stdout.getvalue())
