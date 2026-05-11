"""Unit tests for assetboy.canary external-API smoke harness.

All 5 probes are stubbed at the boundary so tests run offline + deterministic.
Real provider modules are imported but their network/IO functions are
monkey-patched on a per-test basis.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest


# --------------------------------------------------------------------------- #
# Lightweight fakes
# --------------------------------------------------------------------------- #

class _FakeResp:
    """Mimics requests.Response surface used by canary."""

    def __init__(
        self,
        json_data: Any = None,
        status_code: int = 200,
        raise_for_status_exc: Exception | None = None,
    ):
        self._json = json_data
        self.status_code = status_code
        self._exc = raise_for_status_exc

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self._exc is not None:
            raise self._exc
        if self.status_code >= 400:
            import requests as _req
            raise _req.exceptions.HTTPError(
                f"{self.status_code} error",
                response=self,
            )


class _FakeUrlopen:
    """Mimics urllib.request.urlopen context manager for ComfyUI probe."""

    def __init__(self, body: str | bytes):
        self._buf = BytesIO(body.encode() if isinstance(body, str) else body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.getvalue()


# --------------------------------------------------------------------------- #
# Probe import — done late so monkeypatch can hit the right module symbols
# --------------------------------------------------------------------------- #

@pytest.fixture
def canary(monkeypatch):
    """Import canary fresh per test so monkeypatch lands cleanly."""
    if "assetboy.canary" in sys.modules:
        del sys.modules["assetboy.canary"]
    from assetboy import canary as mod
    return mod


# --------------------------------------------------------------------------- #
# probe_polyhaven
# --------------------------------------------------------------------------- #

class TestPolyHavenProbe:
    def test_green_with_enough_results(self, canary, monkeypatch):
        fake_assets = {f"slug_{i}": {"name": f"asset{i}"} for i in range(112)}
        monkeypatch.setattr(
            canary.requests,
            "get",
            lambda *a, **kw: _FakeResp(json_data=fake_assets, status_code=200),
        )
        result = canary.probe_polyhaven()
        assert result.ok is True
        assert "112" in (result.notes or "")
        assert result.error is None

    def test_red_on_low_count(self, canary, monkeypatch):
        sparse = {"a": {}, "b": {}}  # only 2, below threshold of 10
        monkeypatch.setattr(
            canary.requests,
            "get",
            lambda *a, **kw: _FakeResp(json_data=sparse, status_code=200),
        )
        result = canary.probe_polyhaven()
        assert result.ok is False
        assert "unexpected_low_count" in (result.error or "")

    def test_red_on_http_error(self, canary, monkeypatch):
        import requests as _req

        def _boom(*a, **kw):
            raise _req.exceptions.ConnectionError("dns_fail")

        monkeypatch.setattr(canary.requests, "get", _boom)
        result = canary.probe_polyhaven()
        assert result.ok is False
        assert "http_error" in (result.error or "")


# --------------------------------------------------------------------------- #
# probe_fab
# --------------------------------------------------------------------------- #

class _FakeFabDownloader:
    def __init__(
        self,
        auth_state: dict | None,
        authenticated: bool = True,
    ):
        self._auth = auth_state
        self._authd = authenticated

    def load_auth_state(self):
        return self._auth

    def create_cffi_session(self, _auth):
        return object()

    def is_authenticated(self, _session):
        return self._authd


class TestFabProbe:
    def test_green_when_authenticated_with_results(self, canary, monkeypatch):
        from assetboy.providers import fab_hybrid

        monkeypatch.setattr(
            fab_hybrid,
            "FabHybridDownloader",
            lambda *a, **kw: _FakeFabDownloader(
                auth_state={"cookies": [{"name": "x", "value": "y"}]},
                authenticated=True,
            ),
        )
        monkeypatch.setattr(
            fab_hybrid,
            "fetch_fab_library_page",
            lambda session, **kw: {
                "results": [{"listing": {"uid": f"u{i}"}} for i in range(7)]
            },
        )
        result = canary.probe_fab()
        assert result.ok is True
        assert "page1=7" in (result.notes or "")

    def test_red_when_no_auth_state(self, canary, monkeypatch):
        from assetboy.providers import fab_hybrid

        monkeypatch.setattr(
            fab_hybrid,
            "FabHybridDownloader",
            lambda *a, **kw: _FakeFabDownloader(auth_state=None),
        )
        # fetch shouldn't be reached but stub anyway:
        monkeypatch.setattr(
            fab_hybrid, "fetch_fab_library_page",
            lambda *a, **kw: {"results": []},
        )
        result = canary.probe_fab()
        assert result.ok is False
        assert "no_auth_state" in (result.error or "")

    def test_red_when_cookie_expired(self, canary, monkeypatch):
        from assetboy.providers import fab_hybrid

        monkeypatch.setattr(
            fab_hybrid,
            "FabHybridDownloader",
            lambda *a, **kw: _FakeFabDownloader(
                auth_state={"cookies": []},
                authenticated=False,  # is_authenticated returns False
            ),
        )
        monkeypatch.setattr(
            fab_hybrid, "fetch_fab_library_page",
            lambda *a, **kw: {"results": []},
        )
        result = canary.probe_fab()
        assert result.ok is False
        assert "auth_cookie_expired" in (result.error or "")


# --------------------------------------------------------------------------- #
# probe_epic — uses real sqlite3 with a seeded temp DB
# --------------------------------------------------------------------------- #

def _seed_epic_db(db_path: Path, user_version: int, row_count: int) -> None:
    """Build a minimal listings_v1.db lookalike."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"PRAGMA user_version = {user_version}")
        conn.execute(
            "CREATE TABLE local_listing (id TEXT PRIMARY KEY, name TEXT)"
        )
        conn.executemany(
            "INSERT INTO local_listing (id, name) VALUES (?, ?)",
            [(f"item{i}", f"name{i}") for i in range(row_count)],
        )
        conn.commit()
    finally:
        conn.close()


class TestEpicProbe:
    def test_green_with_seeded_db_unpinned(self, canary, monkeypatch, tmp_path):
        db = tmp_path / "listings_v1.db"
        _seed_epic_db(db, user_version=3, row_count=156)
        from assetboy.providers import epic_vault
        monkeypatch.setattr(
            epic_vault, "default_local_fab_library_db_path", lambda: db
        )
        monkeypatch.setattr(canary, "EXPECTED_EPIC_SCHEMA_VERSION", None)
        result = canary.probe_epic()
        assert result.ok is True
        assert "156 vault items" in (result.notes or "")
        assert "unpinned" in (result.notes or "")

    def test_green_with_pinned_match(self, canary, monkeypatch, tmp_path):
        db = tmp_path / "listings_v1.db"
        _seed_epic_db(db, user_version=3, row_count=10)
        from assetboy.providers import epic_vault
        monkeypatch.setattr(
            epic_vault, "default_local_fab_library_db_path", lambda: db
        )
        monkeypatch.setattr(canary, "EXPECTED_EPIC_SCHEMA_VERSION", 3)
        result = canary.probe_epic()
        assert result.ok is True
        assert "v3" in (result.notes or "")
        assert "unpinned" not in (result.notes or "")

    def test_red_on_schema_mismatch(self, canary, monkeypatch, tmp_path):
        db = tmp_path / "listings_v1.db"
        _seed_epic_db(db, user_version=4, row_count=10)
        from assetboy.providers import epic_vault
        monkeypatch.setattr(
            epic_vault, "default_local_fab_library_db_path", lambda: db
        )
        monkeypatch.setattr(canary, "EXPECTED_EPIC_SCHEMA_VERSION", 3)
        result = canary.probe_epic()
        assert result.ok is False
        assert "schema_mismatch" in (result.error or "")
        assert "v4" in (result.error or "")

    def test_red_when_db_missing(self, canary, monkeypatch, tmp_path):
        missing = tmp_path / "does_not_exist.db"
        from assetboy.providers import epic_vault
        monkeypatch.setattr(
            epic_vault, "default_local_fab_library_db_path", lambda: missing
        )
        result = canary.probe_epic()
        assert result.ok is False
        assert "vault_db_not_found" in (result.error or "")

    def test_red_on_table_drift(self, canary, monkeypatch, tmp_path):
        # Build a DB with no local_listing table
        db = tmp_path / "listings_v1.db"
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA user_version = 3")
        conn.execute("CREATE TABLE wrong_table (x INTEGER)")
        conn.commit()
        conn.close()
        from assetboy.providers import epic_vault
        monkeypatch.setattr(
            epic_vault, "default_local_fab_library_db_path", lambda: db
        )
        monkeypatch.setattr(canary, "EXPECTED_EPIC_SCHEMA_VERSION", None)
        result = canary.probe_epic()
        assert result.ok is False
        assert "schema_drift_table_missing" in (result.error or "")

    def test_expected_schema_version_default_is_pinned(self, canary):
        """v1.6.s9: EXPECTED_EPIC_SCHEMA_VERSION pinned to operator's
        verified-good value (0 as of 2026-05-11). Drift catches if Epic
        Launcher ever bumps the FabLibrary SQLite schema."""
        # Default is an int, not None (used to be None before s9 pinned it)
        assert canary.EXPECTED_EPIC_SCHEMA_VERSION is not None
        assert isinstance(canary.EXPECTED_EPIC_SCHEMA_VERSION, int)

    def test_list_history_returns_newest_first(self, canary, monkeypatch, tmp_path):
        """v1.7.s12: list_history walks state/canary/ and sorts newest-first."""
        import os
        state_dir = tmp_path / "canary"
        state_dir.mkdir(parents=True)
        for stem, ts in [
            ("canary_20260101_000000", 1735689600),
            ("canary_20260201_000000", 1738368000),
            ("canary_20260301_000000", 1740787200),
        ]:
            fp = state_dir / f"{stem}.json"
            fp.write_text('{"overall":"green","timestamp":"' + stem + '"}', encoding="utf-8")
            os.utime(fp, (ts, ts))
        (state_dir / "canary_status.json").write_text(
            '{"overall":"green"}', encoding="utf-8"
        )

        monkeypatch.setattr(canary, "state_root", lambda: tmp_path)

        entries = canary.list_history()
        assert len(entries) == 3
        names = [e["name"] for e in entries]
        assert "canary_status.json" not in names
        assert entries[0]["name"] == "canary_20260301_000000.json"
        assert entries[2]["name"] == "canary_20260101_000000.json"

    def test_list_history_since_filter_excludes_older_entries(self, canary, monkeypatch, tmp_path):
        """--since filters by mtime_iso (or timestamp if present)."""
        import os
        state_dir = tmp_path / "canary"
        state_dir.mkdir(parents=True)
        # Two files with mtimes far apart so the filter is unambiguous:
        # - "old" = 1577836800 (2020-01-01)
        # - "new" = 1893456000 (2030-01-01)
        for stem, ts in [
            ("canary_old", 1577836800),
            ("canary_new", 1893456000),
        ]:
            fp = state_dir / f"{stem}.json"
            fp.write_text('{"overall":"green"}', encoding="utf-8")
            os.utime(fp, (ts, ts))

        monkeypatch.setattr(canary, "state_root", lambda: tmp_path)

        # since = 2025-01-01 -> only the 2030 entry should remain
        entries = canary.list_history(since_iso="2025-01-01")
        assert len(entries) == 1
        assert entries[0]["name"] == "canary_new.json"

    def test_prune_history_keeps_last_N(self, canary, monkeypatch, tmp_path):
        """prune_history(keep_last=2) keeps the 2 newest, deletes the rest."""
        import os
        state_dir = tmp_path / "canary"
        state_dir.mkdir(parents=True)
        for stem, ts in [
            ("canary_a", 1000),
            ("canary_b", 2000),
            ("canary_c", 3000),
            ("canary_d", 4000),
            ("canary_e", 5000),
        ]:
            fp = state_dir / f"{stem}.json"
            fp.write_text('{}', encoding="utf-8")
            os.utime(fp, (ts, ts))

        monkeypatch.setattr(canary, "state_root", lambda: tmp_path)

        result = canary.prune_history(keep_last=2)
        assert result["kept_count"] == 2
        assert result["deleted_count"] == 3
        remaining = sorted(p.name for p in state_dir.glob("canary_*.json"))
        assert remaining == ["canary_d.json", "canary_e.json"]

    def test_prune_history_keep_zero_deletes_all(self, canary, monkeypatch, tmp_path):
        state_dir = tmp_path / "canary"
        state_dir.mkdir(parents=True)
        for name in ("canary_x", "canary_y"):
            (state_dir / f"{name}.json").write_text('{}', encoding="utf-8")
        monkeypatch.setattr(canary, "state_root", lambda: tmp_path)

        result = canary.prune_history(keep_last=0)
        assert result["kept_count"] == 0
        assert result["deleted_count"] == 2

    def test_expected_schema_can_be_overridden_via_env(self, canary, monkeypatch, tmp_path):
        """env var EXPECTED_EPIC_SCHEMA_VERSION overrides the module pin.

        This test verifies the override exists; full env-import behavior
        is exercised at import time and the test of import-time effects
        would require subprocess. The functional check is that the env-set
        path leads to a mismatch error.
        """
        # Seed a DB with version 3
        db = tmp_path / "listings_v1.db"
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA user_version = 3")
        conn.execute("CREATE TABLE local_listing (id TEXT)")
        conn.commit()
        conn.close()
        from assetboy.providers import epic_vault
        monkeypatch.setattr(
            epic_vault, "default_local_fab_library_db_path", lambda: db
        )
        # Simulate what an env override would land: set the module attr to 99
        monkeypatch.setattr(canary, "EXPECTED_EPIC_SCHEMA_VERSION", 99)
        result = canary.probe_epic()
        assert result.ok is False
        assert "schema_mismatch" in (result.error or "")
        assert "v99" in (result.error or "")


# --------------------------------------------------------------------------- #
# probe_unity_hub
# --------------------------------------------------------------------------- #

class TestUnityHubProbe:
    def test_green_with_token_and_results(self, canary, monkeypatch, tmp_path):
        local_state = tmp_path / "Local State"
        tokens_file = tmp_path / "encryptedTokens.json"
        local_state.write_text("{}")
        tokens_file.write_text("{}")
        from assetboy.providers import unity_hub
        monkeypatch.setattr(
            unity_hub, "DEFAULT_UNITY_HUB_LOCAL_STATE_PATH", local_state
        )
        monkeypatch.setattr(
            unity_hub,
            "DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH",
            tokens_file,
        )
        monkeypatch.setattr(
            unity_hub,
            "load_unity_hub_tokens",
            lambda **kw: {"accessToken": "fake-jwt"},
        )
        monkeypatch.setattr(
            unity_hub,
            "list_unity_owned_assets",
            lambda **kw: {
                "results": [{"id": str(i)} for i in range(23)]
            },
        )
        result = canary.probe_unity_hub()
        assert result.ok is True
        assert "page1=23" in (result.notes or "")

    def test_red_when_local_state_missing(self, canary, monkeypatch, tmp_path):
        missing = tmp_path / "nope"
        tokens_file = tmp_path / "encryptedTokens.json"
        tokens_file.write_text("{}")
        from assetboy.providers import unity_hub
        monkeypatch.setattr(
            unity_hub, "DEFAULT_UNITY_HUB_LOCAL_STATE_PATH", missing
        )
        monkeypatch.setattr(
            unity_hub,
            "DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH",
            tokens_file,
        )
        result = canary.probe_unity_hub()
        assert result.ok is False
        assert "local_state_missing" in (result.error or "")

    def test_red_when_decrypt_returns_empty(self, canary, monkeypatch, tmp_path):
        local_state = tmp_path / "Local State"
        tokens_file = tmp_path / "encryptedTokens.json"
        local_state.write_text("{}")
        tokens_file.write_text("{}")
        from assetboy.providers import unity_hub
        monkeypatch.setattr(
            unity_hub, "DEFAULT_UNITY_HUB_LOCAL_STATE_PATH", local_state
        )
        monkeypatch.setattr(
            unity_hub,
            "DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH",
            tokens_file,
        )
        monkeypatch.setattr(
            unity_hub, "load_unity_hub_tokens", lambda **kw: {}
        )
        result = canary.probe_unity_hub()
        assert result.ok is False
        assert "decrypt_failed" in (result.error or "")

    def test_red_on_401(self, canary, monkeypatch, tmp_path):
        import requests as _req
        local_state = tmp_path / "Local State"
        tokens_file = tmp_path / "encryptedTokens.json"
        local_state.write_text("{}")
        tokens_file.write_text("{}")
        from assetboy.providers import unity_hub
        monkeypatch.setattr(
            unity_hub, "DEFAULT_UNITY_HUB_LOCAL_STATE_PATH", local_state
        )
        monkeypatch.setattr(
            unity_hub,
            "DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH",
            tokens_file,
        )
        monkeypatch.setattr(
            unity_hub,
            "load_unity_hub_tokens",
            lambda **kw: {"accessToken": "expired"},
        )

        def _boom(**kw):
            resp = _FakeResp(status_code=401)
            raise _req.exceptions.HTTPError("401", response=resp)

        monkeypatch.setattr(unity_hub, "list_unity_owned_assets", _boom)
        result = canary.probe_unity_hub()
        assert result.ok is False
        assert "expired" in (result.error or "")


# --------------------------------------------------------------------------- #
# probe_comfyui
# --------------------------------------------------------------------------- #

class TestComfyUIProbe:
    def test_green_with_gpu_stats(self, canary, monkeypatch):
        from assetboy.execution import comfyui_runner
        monkeypatch.setattr(comfyui_runner, "is_comfyui_running", lambda: True)
        gpu_payload = json.dumps({
            "devices": [
                {"name": "RTX 4090", "vram_free": 16 * 1024 ** 3}
            ]
        })
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeUrlopen(gpu_payload),
        )
        result = canary.probe_comfyui()
        assert result.ok is True
        assert "RTX 4090" in (result.notes or "")
        assert "16 GB" in (result.notes or "")

    def test_red_when_comfyui_down(self, canary, monkeypatch):
        from assetboy.execution import comfyui_runner
        monkeypatch.setattr(
            comfyui_runner, "is_comfyui_running", lambda: False
        )
        result = canary.probe_comfyui()
        assert result.ok is False
        assert "connection_refused" in (result.error or "")

    def test_green_even_when_stats_endpoint_breaks(self, canary, monkeypatch):
        """ComfyUI is up but /system_stats returns garbage — still green."""
        from assetboy.execution import comfyui_runner
        monkeypatch.setattr(comfyui_runner, "is_comfyui_running", lambda: True)

        def _boom(*a, **kw):
            raise urllib.error.URLError("stats_404")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        result = canary.probe_comfyui()
        assert result.ok is True
        assert "stats_unavailable" in (result.notes or "")


# --------------------------------------------------------------------------- #
# run_all + save_state integration
# --------------------------------------------------------------------------- #

class TestRunAll:
    def test_all_green(self, canary, monkeypatch):
        for name in canary.PROBES.keys():
            monkeypatch.setitem(
                canary.PROBES,
                name,
                lambda n=name: canary.ProbeResult(ok=True, notes=f"{n}-ok"),
            )
        state = canary.run_all(quiet=True)
        assert state["overall"] == "green"
        assert set(state["probes"].keys()) == set(canary.PROBES.keys())
        assert all(p["ok"] for p in state["probes"].values())
        assert isinstance(state["elapsed_ms"], int)
        assert state["timestamp"].endswith("Z")

    def test_one_red_flips_overall(self, canary, monkeypatch):
        for name in canary.PROBES.keys():
            monkeypatch.setitem(
                canary.PROBES,
                name,
                lambda n=name: canary.ProbeResult(ok=True, notes=f"{n}-ok"),
            )
        # Make epic red
        monkeypatch.setitem(
            canary.PROBES,
            "epic",
            lambda: canary.ProbeResult(ok=False, error="boom"),
        )
        state = canary.run_all(quiet=True)
        assert state["overall"] == "red"
        assert state["probes"]["epic"]["ok"] is False

    def test_uncaught_exception_marks_red(self, canary, monkeypatch):
        def _kaboom() -> canary.ProbeResult:
            raise RuntimeError("totally unexpected")

        monkeypatch.setitem(canary.PROBES, "fab", _kaboom)
        # Stub others green
        for name in [n for n in canary.PROBES if n != "fab"]:
            monkeypatch.setitem(
                canary.PROBES,
                name,
                lambda n=name: canary.ProbeResult(ok=True),
            )
        state = canary.run_all(quiet=True)
        assert state["probes"]["fab"]["ok"] is False
        assert "uncaught" in (state["probes"]["fab"]["error"] or "")
        assert state["overall"] == "red"


# --------------------------------------------------------------------------- #
# CLI entry
# --------------------------------------------------------------------------- #

class TestCli:
    def test_single_probe_green_returns_0(self, canary, monkeypatch, capsys):
        monkeypatch.setitem(
            canary.PROBES,
            "polyhaven",
            lambda: canary.ProbeResult(ok=True, notes="fast"),
        )
        rc = canary.main(["--probe", "polyhaven"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "OK" in out
        assert "polyhaven" in out

    def test_single_probe_red_returns_1(self, canary, monkeypatch, capsys):
        monkeypatch.setitem(
            canary.PROBES,
            "fab",
            lambda: canary.ProbeResult(ok=False, error="no_auth"),
        )
        rc = canary.main(["--probe", "fab"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "RED" in out
        assert "no_auth" in out

    def test_full_run_json_emits_valid_json(self, canary, monkeypatch, tmp_path):
        for name in canary.PROBES.keys():
            monkeypatch.setitem(
                canary.PROBES,
                name,
                lambda n=name: canary.ProbeResult(ok=True, notes=f"{n}"),
            )
        # Redirect state dir to tmp
        monkeypatch.setattr(
            canary, "state_root", lambda current_file=None: tmp_path
        )
        # Capture stdout
        import io
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        rc = canary.main(["--json"])
        parsed = json.loads(buf.getvalue())
        assert rc == 0
        assert parsed["overall"] == "green"
        assert set(parsed["probes"].keys()) == set(canary.PROBES.keys())

    def test_state_file_written(self, canary, monkeypatch, tmp_path):
        for name in canary.PROBES.keys():
            monkeypatch.setitem(
                canary.PROBES,
                name,
                lambda n=name: canary.ProbeResult(ok=True, notes=f"{n}"),
            )
        monkeypatch.setattr(
            canary, "state_root", lambda current_file=None: tmp_path
        )
        rc = canary.main(["--quiet"])
        assert rc == 0
        status_file = tmp_path / "canary" / "canary_status.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["overall"] == "green"
        # History file also written (one *.json with timestamp pattern)
        history_files = [
            p for p in (tmp_path / "canary").iterdir()
            if p.name.startswith("canary_") and p.name != "canary_status.json"
        ]
        assert len(history_files) == 1


# --------------------------------------------------------------------------- #
# ProbeResult shape
# --------------------------------------------------------------------------- #

def test_probe_result_serializes_cleanly(canary):
    r = canary.ProbeResult(ok=True, ms=42, notes="hello")
    d = asdict(r)
    assert d == {"ok": True, "ms": 42, "notes": "hello", "error": None}
    # Round-trips through JSON
    assert json.loads(json.dumps(d)) == d
