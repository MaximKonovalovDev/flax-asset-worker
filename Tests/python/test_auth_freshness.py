from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assetboy.providers.auth_freshness import describe_auth_state_freshness


class AuthFreshnessTests(unittest.TestCase):
    def test_payload_saved_at_marks_recent_state_not_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "fab_auth_state.json"
            now = datetime.now(timezone.utc)

            result = describe_auth_state_freshness(
                auth_state_path=auth_state_path,
                auth_state={"saved_at": now.isoformat()},
                stale_after_hours=72.0,
            )

            self.assertEqual(result["saved_at"], now.isoformat())
            self.assertEqual(result["saved_at_source"], "payload")
            self.assertFalse(result["auth_state_stale"])

    def test_payload_saved_at_marks_old_state_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "mixamo_auth_state.json"
            old = datetime.now(timezone.utc) - timedelta(hours=96)

            result = describe_auth_state_freshness(
                auth_state_path=auth_state_path,
                auth_state={"saved_at": old.isoformat()},
                stale_after_hours=72.0,
            )

            self.assertEqual(result["saved_at"], old.isoformat())
            self.assertTrue(result["auth_state_stale"])
            self.assertGreaterEqual(result["auth_state_age_hours"], 96.0 - 0.1)

    def test_file_mtime_is_used_when_payload_has_no_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "unity_auth_state.json"
            auth_state_path.write_text("{}", encoding="utf-8")
            old = datetime.now(timezone.utc) - timedelta(hours=80)
            timestamp = old.timestamp()
            auth_state_path.touch()
            auth_state_path.stat()
            import os
            os.utime(auth_state_path, (timestamp, timestamp))

            result = describe_auth_state_freshness(
                auth_state_path=auth_state_path,
                auth_state={},
                stale_after_hours=72.0,
            )

            self.assertEqual(result["saved_at_source"], "file_mtime")
            self.assertTrue(result["auth_state_stale"])


if __name__ == "__main__":
    unittest.main()
