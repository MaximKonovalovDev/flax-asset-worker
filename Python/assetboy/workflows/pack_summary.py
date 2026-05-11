"""Recipe pack-state summary (Path B v1.8.s17, 2026-05-11).

Renders a markdown summary of a recipe's current pack state by joining:

  recipe doc (from YAML) --
    \                       --> markdown report
  pack ledger inventory --

For each pack in the recipe, look up the latest ledger (via
read_pack_pipeline_status) and report:
  - status (completed / pending_manual_drop / failed / not_run)
  - acquisition_method + provider
  - manual-drop path if status is awaiting
  - error message if failed
  - next-step hint per pack_pipeline output

Output sections:
  ## Recipe Summary
  ## Per-pack status (table)
  ## Manual drops required
  ## Failed packs (with errors)
  ## Recommended next actions

Shareable: paste into PR description, Slack, GitHub issue.
"""

from __future__ import annotations

from typing import Any


def render_pack_summary(
    recipe_doc: dict[str, Any],
    *,
    fetch_ledger=None,
) -> str:
    """Build a markdown summary of the recipe's current pack state.

    Args:
        recipe_doc:    parsed recipe YAML (dict with `recipe` + `packs`).
        fetch_ledger:  optional callable (pack_id, game_scope) -> ledger dict
                       or None. Defaults to read_pack_pipeline_status.

    Returns:
        Markdown string. Always returns a valid string; tolerant of
        missing recipe fields.
    """
    if fetch_ledger is None:
        from assetboy.workflows.pack_pipeline import read_pack_pipeline_status

        def fetch_ledger(pack_id, game_scope):  # type: ignore[no-redef]
            try:
                return read_pack_pipeline_status(
                    pack_id=pack_id, game_scope=game_scope
                )
            except Exception:
                return None

    recipe_meta = (recipe_doc or {}).get("recipe") or {}
    recipe_id = str(recipe_meta.get("id", "<unknown>"))
    game_scope = str(recipe_meta.get("game", "<unknown>"))
    description = str(recipe_meta.get("description", "")).strip()
    packs = list((recipe_doc or {}).get("packs") or [])

    lines: list[str] = []
    lines.append(f"# Pack Summary: `{recipe_id}`")
    lines.append("")
    lines.append(f"- **Game scope:** `{game_scope}`")
    lines.append(f"- **Pack count:** {len(packs)}")
    if description:
        lines.append(f"- **Description:** {description.splitlines()[0]}")
    lines.append("")

    # ---- Gather per-pack state ----
    pack_states: list[dict[str, Any]] = []
    counters = {"completed": 0, "pending_manual_drop": 0, "failed": 0, "not_run": 0, "other": 0}

    for pack in packs:
        if not isinstance(pack, dict):
            continue
        pid = str(pack.get("id", "?"))
        ledger = fetch_ledger(pid, game_scope) or {}
        if not isinstance(ledger, dict):
            ledger = {}
        # `read_pack_pipeline_status` returns a synthesized ledger when no
        # state exists; detect via the "exists" field.
        has_real_state = bool(ledger.get("exists", False)) or "status" in ledger
        if not has_real_state:
            status = "not_run"
        else:
            status = str(ledger.get("status", "unknown"))

        bucket = status if status in counters else "other"
        counters[bucket] += 1

        pack_states.append({
            "pack_id": pid,
            "provider": pack.get("provider", "?"),
            "acquisition_method": pack.get("acquisition_method", "?"),
            "asset_kind": pack.get("asset_kind", ""),
            "status": status,
            "current_state": str(ledger.get("current_state", "")),
            "next_step": str(ledger.get("next_step", "")),
            "error": ledger.get("error") or "",
            "drop_dir": ledger.get("drop_dir") or "",
        })

    lines.append("## Status counts")
    lines.append("")
    lines.append("| status | count |")
    lines.append("|---|---|")
    for k, v in counters.items():
        if v:
            lines.append(f"| {k} | {v} |")
    lines.append("")

    # ---- Per-pack table ----
    lines.append("## Per-pack status")
    lines.append("")
    lines.append("| pack_id | provider | method | status | current_state |")
    lines.append("|---|---|---|---|---|")
    for s in pack_states:
        marker = {
            "completed": "OK",
            "pending_manual_drop": "WAIT",
            "failed": "RED",
            "not_run": "--",
        }.get(s["status"], "?")
        lines.append(
            f"| `{s['pack_id']}` | `{s['provider']}` | `{s['acquisition_method']}` "
            f"| {marker} `{s['status']}` | `{s['current_state'] or '-'}` |"
        )
    lines.append("")

    # ---- Manual drops needed ----
    manual_drops = [s for s in pack_states if s["status"] == "pending_manual_drop"]
    if manual_drops:
        lines.append("## Manual drops required")
        lines.append("")
        for s in manual_drops:
            lines.append(f"- **`{s['pack_id']}`** (provider: `{s['provider']}`)")
            if s["drop_dir"]:
                lines.append(f"  - Drop files into: `{s['drop_dir']}`")
            if s["next_step"]:
                lines.append(f"  - Next: {s['next_step']}")
        lines.append("")

    # ---- Failed packs ----
    failed = [s for s in pack_states if s["status"] == "failed"]
    if failed:
        lines.append("## Failed packs")
        lines.append("")
        for s in failed:
            lines.append(f"- **`{s['pack_id']}`** ({s['acquisition_method']} / {s['provider']})")
            if s["error"]:
                err_preview = str(s["error"])[:200]
                lines.append(f"  - Error: `{err_preview}`")
            if s["current_state"]:
                lines.append(f"  - State: `{s['current_state']}`")
        lines.append("")

    # ---- Next actions ----
    not_run = counters.get("not_run", 0)
    if not_run > 0 or failed or manual_drops:
        lines.append("## Recommended next actions")
        lines.append("")
        if not_run > 0:
            lines.append(
                f"- {not_run} pack(s) have never run. Try: "
                f"`python -m assetboy.cli pack from-recipe <recipe_path>`"
            )
        if manual_drops:
            lines.append(
                f"- {len(manual_drops)} manual-browser pack(s) waiting for operator drop. "
                "Inspect each `.manual_browser_wait.json` for instructions, then "
                "`pack from-recipe ... --resume`."
            )
        if failed:
            lines.append(
                f"- {len(failed)} pack(s) failed. After fixing the underlying issue "
                "(provider auth, workspace path, runner missing, etc.), run: "
                f"`python -m assetboy.cli pack rerun-failed --recipe <recipe_path>`"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_pack_summary"]
