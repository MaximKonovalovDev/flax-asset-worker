"""Tests for the Typer CLI's --json output contract (Path B v1.5.1).

The C# server routes in `Source/Routes/RecipeRoutes.cs` subprocess to
`python -m assetboy.cli <subapp> <cmd> --json` and parse the stdout as
JSON. These tests verify that the CLI's --json output:

  1. Is always valid JSON (no garbage text mixed in).
  2. Has the keys the C# side expects.
  3. Matches the contract documented in `MONOREPO_FACADE_DESIGN.md`.

This is a regression catcher for the C# <-> Python boundary. If you
change a Typer command's --json output shape, update both these tests
AND the corresponding C# route handler in lockstep.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


PYTHON_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "Python"


def _run_cli(args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    """Spawn `python -m assetboy.cli <args>` and capture stdout/stderr.

    Inherit the full parent env (so Windows SYSTEMROOT etc. are present)
    but override PYTHONPATH so the spawned process finds our package.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PYTHON_PACKAGE_ROOT)
    cmd = [sys.executable, "-m", "assetboy.cli", *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PYTHON_PACKAGE_ROOT),
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


class JsonContractTests(unittest.TestCase):
    """Verify the --json output keys C# routes depend on."""

    # ----------------------------------------------------------------- #
    # pack list-recipes --json
    # (consumed by C# RecipeRoutes.HandleListAsync)
    # ----------------------------------------------------------------- #

    def test_pack_list_recipes_json_is_parseable(self) -> None:
        rc, stdout, stderr = _run_cli(["pack", "list-recipes", "--json"])
        self.assertEqual(rc, 0, f"non-zero exit: stderr={stderr[:200]}")
        # stdout must be parseable JSON (no garbage mixed in)
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{stdout[:300]}")
        # Expected keys
        self.assertIn("recipes", parsed)
        self.assertIn("count", parsed)
        self.assertIsInstance(parsed["recipes"], list)
        self.assertIsInstance(parsed["count"], int)

    def test_pack_list_recipes_json_entries_have_expected_keys(self) -> None:
        rc, stdout, _ = _run_cli(["pack", "list-recipes", "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(stdout)
        if parsed["count"] == 0:
            self.skipTest("no recipes present; entries shape can't be verified")
        entry = parsed["recipes"][0]
        for required_key in ("game", "recipe_id", "pack_count", "path"):
            self.assertIn(
                required_key, entry,
                f"missing key {required_key!r}; entry: {entry}",
            )

    # ----------------------------------------------------------------- #
    # pack from-recipe ... --json --dry-run
    # (consumed by C# RecipeRoutes.HandleRunAsync)
    # ----------------------------------------------------------------- #

    def test_pack_from_recipe_dry_run_json_is_parseable(self) -> None:
        rc, stdout, stderr = _run_cli([
            "pack", "from-recipe",
            "sandbox/one_pack_smoke.yaml",
            "--dry-run",
            "--json",
        ])
        # In dry-run, even RED packs are reported; exit may be 0 or 1.
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{stdout[:300]}")
        for required_key in (
            "recipe_id", "game", "total_packs", "completed", "failed",
            "required_failed", "block_on_missing_required", "results",
        ):
            self.assertIn(
                required_key, parsed,
                f"missing key {required_key!r}; got: {list(parsed.keys())}",
            )
        self.assertIsInstance(parsed["results"], list)

    def test_pack_from_recipe_results_have_expected_shape(self) -> None:
        rc, stdout, _ = _run_cli([
            "pack", "from-recipe",
            "sandbox/one_pack_smoke.yaml",
            "--dry-run",
            "--json",
        ])
        parsed = json.loads(stdout)
        results = parsed.get("results") or []
        self.assertGreater(len(results), 0, "sandbox should have 1 pack result")
        entry = results[0]
        for k in ("pack_id", "required", "status", "current_state", "next_step"):
            self.assertIn(k, entry, f"missing key {k!r}; entry: {entry}")

    # ----------------------------------------------------------------- #
    # pack status <id> --json
    # (consumed by C# RecipeRoutes.HandlePackStatusAsync)
    # ----------------------------------------------------------------- #

    def test_pack_status_json_returns_a_ledger(self) -> None:
        # The pack may not have been run yet; status should still emit JSON.
        rc, stdout, stderr = _run_cli([
            "pack", "status",
            "SANDBOX_POLY_TEX_BRICK_WALL_01",
            "--game", "sandbox",
            "--json",
        ])
        # exit may be 0 (ledger found) or 1 (no ledger yet); both are
        # non-crash; the C# route inspects exit code separately.
        self.assertIn(rc, (0, 1))
        # Must emit parseable JSON either way.
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nstderr={stderr[:200]}")
        self.assertIsInstance(parsed, dict)

    # ----------------------------------------------------------------- #
    # Smoke: --json mode on every sub-app's safest cmd
    # ----------------------------------------------------------------- #

    def test_fab_auth_status_json_is_parseable(self) -> None:
        """Even on the unconfigured fail-path, output must be JSON."""
        rc, stdout, _ = _run_cli(["fab", "auth-status", "--json"])
        # exit 1 expected when no auth state; output still must be JSON.
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{stdout[:300]}")
        # Should have at least one fab_* field per the cli/fab.py contract.
        # Note: when --json is used, the keys are NOT prefixed with fab_ -
        # the prefix is only for the key=value mode.
        self.assertIsInstance(parsed, dict)
        self.assertGreater(len(parsed), 0)

    def test_unity_status_json_is_parseable(self) -> None:
        """Same pattern: even with no Unity Hub setup, output is JSON."""
        rc, stdout, _ = _run_cli(["unity", "status", "--json"])
        self.assertIn(rc, (0, 1))
        try:
            json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{stdout[:300]}")


if __name__ == "__main__":
    unittest.main()
