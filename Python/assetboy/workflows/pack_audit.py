"""Pack ledger audit (Path B v1.6.s3, 2026-05-11).

Walks `state/pack_pipeline/<game_scope>/*.json` ledgers and aggregates
status counts per game + overall. Used by:

  - CLI: `python -m assetboy.cli pack audit`
  - HTTP: GET /api/v1/packs/audit (C# RecipeRoutes.HandleAuditAsync via subprocess)
  - Monorepo facade dashboards (Lane E broker scope)

Output shape:

    {
      "summary": {
        "total_ledgers": 23,
        "by_status": {
          "completed": 12,
          "pending": 5,
          "failed": 6
        }
      },
      "games": {
        "primitive_tech": {
          "total": 9,
          "by_status": {"completed": 3, "pending": 0, "failed": 6}
        },
        "roman_arena": {...},
        "sandbox": {...}
      },
      "ledgers": [
        {"pack_id": "...", "game_scope": "...", "status": "...",
         "current_state": "...", "ledger_path": "...", "updated_at_utc": "..."},
        ...
      ]
    }

Tolerant of broken ledgers (malformed JSON, missing fields) — they're
counted under `by_status: "unreadable"` instead of crashing the report.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from assetboy.library.paths import state_root


PACK_PIPELINE_DIRNAME = "pack_pipeline"


def build_pack_audit_report(
    *,
    include_ledgers: bool = True,
    max_ledgers: int = 1000,
) -> dict[str, Any]:
    """Walk state/pack_pipeline/ and aggregate ledger status.

    Args:
        include_ledgers: if True, include per-ledger summary entries
                         in the `ledgers` list. If False, only the
                         aggregate counts (lighter response).
        max_ledgers:     cap the `ledgers` list length to prevent
                         huge responses from very busy boxes.

    Returns:
        Dict with keys: summary, games, ledgers (if include_ledgers).
        Always returns a valid dict — never raises.
    """
    pipeline_dir = state_root() / PACK_PIPELINE_DIRNAME
    games: dict[str, dict[str, Any]] = {}
    ledgers: list[dict[str, Any]] = []
    overall_status_counter: Counter[str] = Counter()

    if not pipeline_dir.exists():
        return {
            "summary": {"total_ledgers": 0, "by_status": {}},
            "games": {},
            "ledgers": [] if include_ledgers else None,
            "pipeline_dir": str(pipeline_dir),
            "pipeline_dir_exists": False,
        }

    # Layout: state/pack_pipeline/<game_scope>/<pack_id>.json
    for game_dir in sorted(pipeline_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        game_scope = game_dir.name
        game_status_counter: Counter[str] = Counter()
        game_total = 0

        for ledger_file in sorted(game_dir.glob("*.json")):
            game_total += 1
            entry = _read_ledger(ledger_file, game_scope)
            status = entry["status"]
            game_status_counter[status] += 1
            overall_status_counter[status] += 1
            if include_ledgers and len(ledgers) < max_ledgers:
                ledgers.append(entry)

        games[game_scope] = {
            "total": game_total,
            "by_status": dict(game_status_counter),
        }

    return {
        "summary": {
            "total_ledgers": sum(overall_status_counter.values()),
            "by_status": dict(overall_status_counter),
        },
        "games": games,
        "ledgers": ledgers if include_ledgers else None,
        "pipeline_dir": str(pipeline_dir),
        "pipeline_dir_exists": True,
    }


def _read_ledger(ledger_file: Path, game_scope: str) -> dict[str, Any]:
    """Read one ledger file; tolerate broken JSON / missing fields."""
    summary: dict[str, Any] = {
        "pack_id": ledger_file.stem,
        "game_scope": game_scope,
        "ledger_path": str(ledger_file),
        "status": "unreadable",
        "current_state": "",
        "updated_at_utc": "",
    }
    try:
        text = ledger_file.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            summary["status"] = str(data.get("status", "unknown"))
            summary["current_state"] = str(data.get("current_state", ""))
            summary["updated_at_utc"] = str(data.get("updated_at_utc", ""))
            summary["pack_id"] = str(data.get("pack_id", ledger_file.stem))
    except json.JSONDecodeError:
        summary["status"] = "unreadable_json"
    except OSError as exc:
        summary["status"] = f"unreadable_io: {exc}"
    return summary


__all__ = [
    "build_pack_audit_report",
    "PACK_PIPELINE_DIRNAME",
]
