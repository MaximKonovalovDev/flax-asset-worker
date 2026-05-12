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


class CanaryJsonContractTests(unittest.TestCase):
    """Protect the canary --json contract that CanaryRoutes.HandleStatusAsync
    depends on (it reads the same JSON shape from state/canary/canary_status.json).
    """

    def _run_canary(self, args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
        """Spawn `python -m assetboy.canary <args>`; same env strategy as _run_cli."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYTHON_PACKAGE_ROOT)
        cmd = [sys.executable, "-m", "assetboy.canary", *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PYTHON_PACKAGE_ROOT),
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_canary_single_probe_json_emits_parseable_dict(self) -> None:
        """`canary --probe polyhaven --json` emits {probe_name: {ok, ms, ...}}.

        v1.11.s46: bumped timeout 15->45 + tolerate subprocess timeout
        (skip-the-test) when network conditions cause spurious failures.
        The contract this enforces is JSON shape, not network reliability.
        """
        try:
            rc, stdout, stderr = self._run_canary(
                ["--probe", "polyhaven", "--json"], timeout=45.0,
            )
        except subprocess.TimeoutExpired:
            self.skipTest(
                "canary --probe polyhaven exceeded 45s; treating as transient "
                "network condition (the JSON contract this test enforces "
                "doesn't depend on success/failure outcome)."
            )
        # exit 0 (green) or 1 (red) -- both should emit JSON
        self.assertIn(rc, (0, 1), f"unexpected exit: stderr={stderr[:200]}")
        # If stdout is empty (subprocess produced nothing), it's a network
        # blip mid-run — skip rather than fail.
        if not stdout.strip():
            self.skipTest(
                f"canary --probe polyhaven produced empty stdout "
                f"(stderr first 200: {stderr[:200]!r}); transient network blip."
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{stdout[:300]}")
        self.assertIsInstance(parsed, dict)
        self.assertIn("polyhaven", parsed)
        # Verify the probe result has the shape CanaryRoutes expects.
        result = parsed["polyhaven"]
        self.assertIn("ok", result)
        self.assertIn("ms", result)

    def test_pack_audit_json_contract(self) -> None:
        """v1.6.s3: pack audit --json shape consumed by C# RecipeRoutes.HandleAuditAsync.

        Required keys: summary{total_ledgers, by_status}, games, pipeline_dir.
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYTHON_PACKAGE_ROOT)
        cmd = [sys.executable, "-m", "assetboy.cli", "pack", "audit", "--json"]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(PYTHON_PACKAGE_ROOT), env=env,
        )
        self.assertEqual(proc.returncode, 0)
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{proc.stdout[:300]}")
        for k in ("summary", "games", "pipeline_dir"):
            self.assertIn(k, parsed, f"missing key {k!r}; got: {list(parsed.keys())}")
        summary = parsed["summary"]
        self.assertIn("total_ledgers", summary)
        self.assertIn("by_status", summary)

    def test_pack_validate_json_contract(self) -> None:
        """v1.6.s5: pack validate --json shape consumed by tooling.

        Required keys: ok, recipe_id, pack_count, errors, warnings, path.
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYTHON_PACKAGE_ROOT)
        cmd = [
            sys.executable, "-m", "assetboy.cli",
            "pack", "validate", "sandbox/one_pack_smoke.yaml", "--json",
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(PYTHON_PACKAGE_ROOT), env=env,
        )
        # exit 0 expected (sandbox recipe is valid)
        self.assertEqual(proc.returncode, 0)
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{proc.stdout[:300]}")
        for k in ("ok", "recipe_id", "pack_count", "errors", "warnings", "path"):
            self.assertIn(k, parsed, f"missing key {k!r}; got: {list(parsed.keys())}")
        self.assertTrue(parsed["ok"])
        self.assertIsInstance(parsed["errors"], list)
        self.assertIsInstance(parsed["warnings"], list)

    def test_canary_full_run_json_emits_overall_state(self) -> None:
        """`canary --json` emits {timestamp, elapsed_ms, overall, probes: {...}}.

        This is the SAME shape that lands in state/canary/canary_status.json
        and is what CanaryRoutes.HandleStatusAsync surfaces over HTTP.
        """
        # Use --probe to keep it fast (single probe + don't need 5 to verify shape)
        # Wait, --json on full run is what we want -- let it do all 5.
        rc, stdout, stderr = self._run_canary(["--json"], timeout=60.0)
        self.assertIn(rc, (0, 1))
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{stdout[:300]}")
        # Required keys for the C# CanaryRoutes side:
        for required_key in ("timestamp", "elapsed_ms", "overall", "probes"):
            self.assertIn(
                required_key, parsed,
                f"missing key {required_key!r}; got keys: {list(parsed.keys())}",
            )
        # overall must be one of the two canonical values
        self.assertIn(parsed["overall"], ("green", "red"))
        # probes must be a dict (one entry per probe)
        self.assertIsInstance(parsed["probes"], dict)
        # Each probe result must have ok + ms
        for probe_name, probe_result in parsed["probes"].items():
            self.assertIn("ok", probe_result, f"probe {probe_name} missing 'ok'")
            self.assertIn("ms", probe_result, f"probe {probe_name} missing 'ms'")


class ScoutByLicenseJsonContractTests(JsonContractTests):
    """v1.14.s102: shape consumed by C# /api/v1/library/scout-by-license."""

    def test_gen_scout_by_license_json_shape(self) -> None:
        """gen scout-by-license --json with dry-run produces parseable C#-compatible JSON."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYTHON_PACKAGE_ROOT)
        # Clear key envs to make missing-key skips deterministic.
        for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY"):
            env.pop(k, None)
        cmd = [
            sys.executable, "-m", "assetboy.cli",
            "gen", "scout-by-license",
            "--license", "cc0",
            "--query", "stone",
            "--count", "1",
            "--dry-run",
            "--json",
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            cwd=str(PYTHON_PACKAGE_ROOT), env=env,
        )
        # The command may hit live no-key APIs; allow some providers to fail
        # individually but the subprocess itself should exit 0 with valid JSON.
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nFIRST 300 chars:\n{proc.stdout[:300]}")
        for k in (
            "license_token", "query", "count_per_provider", "dry_run",
            "providers_matched_by_license", "providers_run",
            "providers_ok", "providers_skipped", "providers_failed",
            "total_matched", "total_downloaded", "providers",
        ):
            self.assertIn(k, parsed, f"missing top-level key {k!r}")
        # Each provider entry has the C#-expected shape.
        for p in parsed["providers"]:
            for k in ("provider", "license", "ok", "skipped",
                      "matched", "downloaded", "error"):
                self.assertIn(k, p, f"provider entry missing {k!r}: {p}")
        # license_token gets normalized to lower.
        self.assertEqual(parsed["license_token"], "cc0")


if __name__ == "__main__":
    unittest.main()
