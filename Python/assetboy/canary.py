"""External-API smoke canary for FAW.

Hits 5 third-party surfaces FAW depends on with cheap, read-only probes:

    1. PolyHaven   GET https://api.polyhaven.com/assets (textures/natural)
    2. Fab         authenticated /i/library/search via FabHybridDownloader
    3. Epic        local SQLite at VaultCache/FabLibrary/listings_v1.db
    4. Unity Hub   DPAPI-decrypted token + /-/api/purchases page-1
    5. ComfyUI     http://127.0.0.1:8188/system_stats

Writes ``state/canary/canary_status.json`` + a timestamped history file.

Exit code 0 if all green, 1 if any red. Designed to run weekly via
Windows Task Scheduler — see ``scripts/install-canary-scheduler.ps1``.

Usage:
    python -m assetboy.canary                   # full run, human output
    python -m assetboy.canary --json            # full run, JSON to stdout
    python -m assetboy.canary --quiet           # silent except exit code
    python -m assetboy.canary --probe polyhaven # single-provider check

Spec: ``docs/research/CANARY-SPEC-2026-05-10.md`` (in flax-mcp).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable

import requests  # PolyHaven probe (other probes use provider modules)

from assetboy.library.paths import state_root


# --------------------------------------------------------------------------- #
# Schema pins — operator updates these when external providers drift.
# --------------------------------------------------------------------------- #

# Epic Launcher's VaultCache SQLite schema version. PRAGMA user_version on
# C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary\listings_v1.db.
# If Epic ships a Launcher upgrade that bumps this, the canary fails LOUD and
# the operator inspects + bumps the constant here after confirming
# epic_vault.py still reads the new schema correctly.
# Set on first green run by reading the actual value; until then we accept
# anything > 0 to seed the pin.
EXPECTED_EPIC_SCHEMA_VERSION: int | None = 0  # Pinned 2026-05-11 (v1.6.s9)
# Drift catches: if Epic Launcher upgrades the FabLibrary SQLite schema,
# the probe will fail loud. Operator updates EXPECTED_EPIC_SCHEMA_VERSION
# after verifying epic_vault.py reads the new schema correctly. Override
# at runtime via env var EXPECTED_EPIC_SCHEMA_VERSION (handy for testing).
import os as _os
_env_override = _os.getenv("EXPECTED_EPIC_SCHEMA_VERSION", "").strip()
if _env_override:
    try:
        EXPECTED_EPIC_SCHEMA_VERSION = int(_env_override)
    except ValueError:
        pass

POLYHAVEN_MIN_RESULTS = 10  # smoke threshold; api returns 100s for textures/natural


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

@dataclass
class ProbeResult:
    ok: bool
    ms: int = 0
    notes: str | None = None
    error: str | None = None


# --------------------------------------------------------------------------- #
# Probe: PolyHaven  (public REST, no auth)
# --------------------------------------------------------------------------- #

def probe_polyhaven() -> ProbeResult:
    """Hit api.polyhaven.com for one curated textures query. CC0 public API."""
    try:
        from assetboy.execution.polyhaven_runner import POLYHAVEN_API
    except ImportError as exc:
        return ProbeResult(ok=False, error=f"import_failed: {exc}")

    try:
        r = requests.get(
            f"{POLYHAVEN_API}/assets",
            params={"type": "textures", "categories": "natural"},
            timeout=10,
        )
        r.raise_for_status()
        # /assets returns a DICT keyed by slug, not a list with results.
        data = r.json()
        count = len(data) if isinstance(data, dict) else 0
        if count < POLYHAVEN_MIN_RESULTS:
            return ProbeResult(
                ok=False,
                error=f"unexpected_low_count: {count} < {POLYHAVEN_MIN_RESULTS}",
            )
        return ProbeResult(ok=True, notes=f"{count} natural-texture assets")
    except requests.exceptions.RequestException as exc:
        return ProbeResult(ok=False, error=f"http_error: {exc}")
    except (ValueError, KeyError) as exc:
        return ProbeResult(ok=False, error=f"shape_drift: {exc}")


# --------------------------------------------------------------------------- #
# Probe: Fab.com  (authenticated via persisted nodriver session)
# --------------------------------------------------------------------------- #

def probe_fab() -> ProbeResult:
    """Validate Fab auth cookie still works. Fetches page 1 of library/search."""
    try:
        from assetboy.providers.fab_hybrid import (
            FabHybridDownloader,
            fetch_fab_library_page,
        )
    except ImportError as exc:
        return ProbeResult(ok=False, error=f"import_failed: {exc}")

    try:
        downloader = FabHybridDownloader()
        auth_state = downloader.load_auth_state()
        if not auth_state:
            return ProbeResult(ok=False, error="no_auth_state_run_fab_login")

        session = downloader.create_cffi_session(auth_state)
        if not downloader.is_authenticated(session):
            return ProbeResult(
                ok=False,
                error="auth_cookie_expired_run_fab_login",
            )

        # Sample page-1 result count. Fab is cursor-paginated; no aggregate.
        payload = fetch_fab_library_page(session, timeout_seconds=15.0)
        results = payload.get("results") or []
        sample = len(results)
        return ProbeResult(
            ok=True,
            notes=f"auth valid; page1={sample} owned listings",
        )
    except Exception as exc:  # curl_cffi exceptions don't share a common base
        return ProbeResult(ok=False, error=f"probe_failed: {exc}")


# --------------------------------------------------------------------------- #
# Probe: Epic Games  (local SQLite — read-only, no network)
# --------------------------------------------------------------------------- #

def probe_epic() -> ProbeResult:
    """Read VaultCache SQLite: validate schema version + count vault items."""
    try:
        from assetboy.providers.epic_vault import (
            default_local_fab_library_db_path,
        )
    except ImportError as exc:
        return ProbeResult(ok=False, error=f"import_failed: {exc}")

    try:
        db_path = default_local_fab_library_db_path()
    except Exception as exc:
        return ProbeResult(ok=False, error=f"path_resolve_failed: {exc}")

    if not db_path.exists():
        return ProbeResult(
            ok=False,
            error=f"vault_db_not_found: {db_path}",
        )

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            count = conn.execute(
                "SELECT COUNT(*) FROM local_listing"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        return ProbeResult(
            ok=False,
            error=f"schema_drift_table_missing: {exc}",
        )
    except sqlite3.DatabaseError as exc:
        return ProbeResult(ok=False, error=f"db_error: {exc}")

    if (
        EXPECTED_EPIC_SCHEMA_VERSION is not None
        and user_version != EXPECTED_EPIC_SCHEMA_VERSION
    ):
        return ProbeResult(
            ok=False,
            error=(
                f"schema_mismatch: got v{user_version}, "
                f"expected v{EXPECTED_EPIC_SCHEMA_VERSION} "
                "(operator must verify epic_vault.py reads new schema "
                "then bump EXPECTED_EPIC_SCHEMA_VERSION in canary.py)"
            ),
        )

    pin_note = (
        f"v{user_version}"
        if EXPECTED_EPIC_SCHEMA_VERSION is not None
        else f"v{user_version} (unpinned — set EXPECTED_EPIC_SCHEMA_VERSION="
             f"{user_version} in canary.py to pin)"
    )
    return ProbeResult(
        ok=True,
        notes=f"schema {pin_note}; {count} vault items",
    )


# --------------------------------------------------------------------------- #
# Probe: Unity Hub  (DPAPI decrypt + /-/api/purchases page-1)
# --------------------------------------------------------------------------- #

def probe_unity_hub() -> ProbeResult:
    """Validate Local State decrypts and purchases endpoint returns 200."""
    try:
        from assetboy.providers.unity_hub import (
            DEFAULT_UNITY_HUB_LOCAL_STATE_PATH,
            DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH,
            load_unity_hub_tokens,
            list_unity_owned_assets,
        )
    except ImportError as exc:
        return ProbeResult(ok=False, error=f"import_failed: {exc}")

    if not DEFAULT_UNITY_HUB_LOCAL_STATE_PATH.exists():
        return ProbeResult(
            ok=False,
            error=f"unity_hub_local_state_missing: {DEFAULT_UNITY_HUB_LOCAL_STATE_PATH}",
        )
    if not DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH.exists():
        return ProbeResult(
            ok=False,
            error=f"unity_hub_tokens_missing: {DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH}",
        )

    try:
        tokens = load_unity_hub_tokens()
    except Exception as exc:
        return ProbeResult(ok=False, error=f"decrypt_helper_failed: {exc}")

    if not tokens or not tokens.get("accessToken"):
        return ProbeResult(
            ok=False,
            error="decrypt_failed_or_no_access_token (reopen Unity Hub to refresh)",
        )

    try:
        payload = list_unity_owned_assets(rows=1, tokens=tokens, timeout=15)
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            return ProbeResult(
                ok=False,
                error="unity_token_expired_reopen_hub_to_refresh",
            )
        return ProbeResult(ok=False, error=f"http_error: {exc}")
    except Exception as exc:
        return ProbeResult(ok=False, error=f"purchases_call_failed: {exc}")

    results = payload.get("results") or []
    sample = len(results)
    return ProbeResult(
        ok=True,
        notes=f"DPAPI decrypt OK; page1={sample} owned packages",
    )


# --------------------------------------------------------------------------- #
# Probe: ComfyUI  (local :8188)
# --------------------------------------------------------------------------- #

def probe_comfyui() -> ProbeResult:
    """Check ComfyUI is running + report GPU + free VRAM if available."""
    try:
        from assetboy.execution.comfyui_runner import (
            COMFYUI_API,
            is_comfyui_running,
        )
    except ImportError as exc:
        return ProbeResult(ok=False, error=f"import_failed: {exc}")

    if not is_comfyui_running():
        return ProbeResult(
            ok=False,
            error="connection_refused (is ComfyUI running on :8188?)",
        )

    try:
        with urllib.request.urlopen(
            f"{COMFYUI_API}/system_stats", timeout=5
        ) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        return ProbeResult(ok=True, notes=f"running; stats_unavailable: {exc}")

    devices = data.get("devices") or [{}]
    gpu = devices[0]
    gpu_name = gpu.get("name", "GPU?")
    vram_free_b = gpu.get("vram_free", 0)
    vram_free_gb = vram_free_b // (1024 ** 3) if isinstance(vram_free_b, int) else 0
    return ProbeResult(
        ok=True,
        notes=f"running; {gpu_name}; vram_free={vram_free_gb} GB",
    )


# --------------------------------------------------------------------------- #
# Probe registry + runner
# --------------------------------------------------------------------------- #

PROBES: dict[str, Callable[[], ProbeResult]] = {
    "polyhaven": probe_polyhaven,
    "fab": probe_fab,
    "epic": probe_epic,
    "unity_hub": probe_unity_hub,
    "comfyui": probe_comfyui,
}


def _run_one(name: str, probe: Callable[[], ProbeResult]) -> ProbeResult:
    t0 = time.monotonic()
    try:
        result = probe()
    except Exception as exc:
        result = ProbeResult(ok=False, error=f"uncaught: {exc}")
    result.ms = int((time.monotonic() - t0) * 1000)
    return result


def run_all(quiet: bool = False) -> dict:
    start = time.monotonic()
    results: dict[str, dict] = {}
    for name, probe in PROBES.items():
        r = _run_one(name, probe)
        results[name] = asdict(r)
        if not quiet:
            status = "OK " if r.ok else "RED"
            tail = r.notes if r.ok else r.error
            print(f"  [{status}] {name:12} {r.ms:>5} ms  {tail or ''}")
    elapsed_ms = int((time.monotonic() - start) * 1000)
    overall = "green" if all(p["ok"] for p in results.values()) else "red"
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_ms": elapsed_ms,
        "overall": overall,
        "probes": results,
    }


def save_state(state: dict) -> Path:
    """Write latest status + timestamped history under state/canary/.

    Note: ``state_root()`` is called with no args so it resolves against
    ``paths.py``'s own ``__file__`` (whose ``parents[3]`` is the repo root).
    Passing ``canary.py``'s ``__file__`` would resolve one level too high
    because ``canary.py`` is one directory shallower than ``paths.py``.
    """
    state_dir = state_root() / "canary"
    state_dir.mkdir(parents=True, exist_ok=True)
    out = state_dir / "canary_status.json"
    out.write_text(json.dumps(state, indent=2), encoding="utf-8")
    history = state_dir / f"canary_{time.strftime('%Y%m%d_%H%M%S')}.json"
    history.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# History management (v1.7.s12)
# --------------------------------------------------------------------------- #

def _history_dir() -> Path:
    return state_root() / "canary"


def list_history(since_iso: str = "") -> list[dict]:
    """Return per-run history file metadata sorted newest-first.

    Each entry: {path, name, mtime_iso, size_bytes, overall, timestamp}.
    Reads each file's top-level JSON (cheap; files are tiny). Tolerant
    of broken files (marks them with ``error`` field, doesn't crash).
    """
    state_dir = _history_dir()
    if not state_dir.exists():
        return []
    entries: list[dict] = []
    for fp in state_dir.glob("canary_*.json"):
        if fp.name == "canary_status.json":
            continue  # the "latest" symlink-equivalent; not history
        try:
            stat = fp.stat()
        except OSError:
            continue
        entry: dict = {
            "path": str(fp),
            "name": fp.name,
            "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            "size_bytes": stat.st_size,
        }
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
            entry["overall"] = str(doc.get("overall", "unknown"))
            entry["timestamp"] = str(doc.get("timestamp", ""))
        except Exception as exc:
            entry["error"] = str(exc)
        entries.append(entry)

    # Sort newest-first by mtime
    entries.sort(key=lambda e: e.get("mtime_iso", ""), reverse=True)

    # --since filter (operator-friendly: drop entries strictly older than the date)
    if since_iso:
        entries = [
            e for e in entries
            if (e.get("mtime_iso", "") or e.get("timestamp", "")) >= since_iso
        ]

    return entries


def prune_history(keep_last: int) -> dict:
    """Delete all but the most recent N history files. Returns {deleted, kept}.

    Reads sort order from ``list_history()`` (newest-first), keeps the
    first `keep_last`, deletes the rest. Never deletes the
    ``canary_status.json`` "latest" file (excluded by list_history).
    """
    if keep_last < 0:
        keep_last = 0
    entries = list_history()
    to_keep = entries[:keep_last]
    to_delete = entries[keep_last:]
    deleted_paths: list[str] = []
    for entry in to_delete:
        try:
            Path(entry["path"]).unlink()
            deleted_paths.append(entry["path"])
        except OSError:
            continue
    return {
        "deleted": deleted_paths,
        "deleted_count": len(deleted_paths),
        "kept_count": len(to_keep),
        "kept_paths": [e["path"] for e in to_keep],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="assetboy.canary",
        description="External-API smoke test for FAW (5 probes).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit JSON to stdout (no progress lines)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="no progress lines (state file still written)",
    )
    p.add_argument(
        "--probe",
        choices=list(PROBES.keys()),
        help="run a single probe (skips state file write)",
    )
    # v1.7.s12: history management
    p.add_argument(
        "--list-history",
        action="store_true",
        help="list state/canary/canary_*.json history files (newest-first); skip running probes",
    )
    p.add_argument(
        "--since",
        default="",
        help="filter --list-history to entries with mtime >= this ISO date (e.g. 2026-05-01)",
    )
    p.add_argument(
        "--prune",
        type=int,
        default=-1,
        help="delete all but the most recent N history files; skip running probes",
    )
    p.add_argument(
        "--exit-zero",
        action="store_true",
        help=(
            "v1.9.s23: force exit 0 regardless of probe outcome. Useful for CI "
            "hooks that consume the JSON output but shouldn't fail the build "
            "on (e.g.) a transient PolyHaven 503."
        ),
    )
    args = p.parse_args(argv)

    # v1.7.s12 history modes (no probe run)
    if args.list_history:
        entries = list_history(since_iso=args.since)
        if args.json:
            print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        else:
            print(f"canary_history_count={len(entries)}")
            for e in entries:
                overall = e.get("overall", "?")
                ts = e.get("timestamp", e.get("mtime_iso", "?"))
                print(f"canary_history  {ts}  overall={overall}  size={e.get('size_bytes', 0)}  {e['name']}")
        return 0

    if args.prune >= 0:
        result = prune_history(keep_last=args.prune)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"canary_prune_kept={result['kept_count']}")
            print(f"canary_prune_deleted={result['deleted_count']}")
        return 0

    if args.probe:
        result = _run_one(args.probe, PROBES[args.probe])
        if args.json:
            print(json.dumps({args.probe: asdict(result)}, indent=2))
        else:
            status = "OK " if result.ok else "RED"
            tail = result.notes if result.ok else result.error
            print(f"[{status}] {args.probe}: {tail or ''}")
        if args.exit_zero:
            return 0
        return 0 if result.ok else 1

    if not args.quiet and not args.json:
        print("== FAW canary ==")

    state = run_all(quiet=args.quiet or args.json)
    out_path = save_state(state)

    if args.json:
        print(json.dumps(state, indent=2))
    elif not args.quiet:
        print(f"  overall: {state['overall']}")
        print(f"  written: {out_path}")

    if args.exit_zero:
        return 0
    return 0 if state["overall"] == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
