"""Pack sub-app: drive a YAML recipe through the pack pipeline.

Wraps `assetboy.workflows.pack_pipeline.execute_prepare_pack_dispatched`
(the new Stage-dispatch entry from s7). Each pack in the recipe's `packs[]`
becomes one pipeline invocation.

Commands:
    pack from-recipe <recipe.yaml>   -- run every required pack in the recipe
    pack list-recipes                -- inventory available recipes/<game>/<*>.yaml
    pack status <pack_id>            -- inspect the ledger for one pack (read-only)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

try:
    import yaml
except ImportError as _exc:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


app = typer.Typer(
    name="pack",
    help="YAML-recipe-driven pack pipeline runs.",
    add_completion=False,
    no_args_is_help=True,
)


def _load_recipe(recipe_path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML not installed (pip install pyyaml)")
    text = recipe_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"recipe root must be a mapping; got {type(parsed).__name__}")
    return parsed


def _recipes_dir() -> Path:
    """Resolve <repo>/recipes/. Symmetric with library.paths.assetboy_root."""
    # cli/pack.py -> parents[3] is the repo root (flax-asset-worker/)
    here = Path(__file__).resolve()
    return here.parents[3] / "recipes"


# --------------------------------------------------------------------------- #
# pack list-recipes
# --------------------------------------------------------------------------- #

@app.command("list-recipes")
def list_recipes_cmd(
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """List available YAML recipes under recipes/<game>/<*>.yaml."""
    recipes_root = _recipes_dir()
    if not recipes_root.exists():
        msg = f"recipes_dir_not_found: {recipes_root}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_list_recipes_error={msg}")
        raise typer.Exit(code=1)

    entries: list[dict[str, str]] = []
    for game_dir in sorted(p for p in recipes_root.iterdir() if p.is_dir()):
        for recipe_yaml in sorted(game_dir.glob("*.yaml")):
            try:
                doc = _load_recipe(recipe_yaml)
                rid = (doc.get("recipe") or {}).get("id", "?")
                game = (doc.get("recipe") or {}).get("game", game_dir.name)
                pack_count = len((doc.get("packs") or []))
            except Exception as exc:
                rid = "?"
                game = game_dir.name
                pack_count = -1
                _ = exc  # silenced; surfaced as "?" recipe id
            entries.append(
                {
                    "path": str(recipe_yaml.relative_to(recipes_root)),
                    "game": game,
                    "recipe_id": rid,
                    "pack_count": pack_count,
                }
            )

    if json_out:
        json.dump({"recipes": entries, "count": len(entries)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"pack_list_recipes_count={len(entries)}")
        for idx, e in enumerate(entries, start=1):
            print(
                f"pack_list_recipes_entry={idx}  "
                f"game={e['game']}  "
                f"id={e['recipe_id']}  "
                f"packs={e['pack_count']}  "
                f"path={e['path']}"
            )


# --------------------------------------------------------------------------- #
# pack from-recipe
# --------------------------------------------------------------------------- #

@app.command("from-recipe")
def from_recipe_cmd(
    recipe_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a YAML recipe (or a recipe_id resolvable under recipes/).",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Plan + persist ledger only; no real downloads/cleanup.",
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Skip stages whose ledger says they're already complete.",
        ),
    ] = True,
    skip: Annotated[
        list[str],
        typer.Option(
            "--skip",
            help="Pack IDs to skip (repeatable).",
        ),
    ] = None,
    only_required: Annotated[
        bool,
        typer.Option(
            "--only-required",
            help="Run only packs in gates.required_pack_ids.",
        ),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Run every pack in a recipe through the pack pipeline.

    Per-pack execution uses `execute_prepare_pack_dispatched` (s7 entry).
    A summary is printed (or emitted as JSON) at the end with one line per
    pack covering: gate, status, current_state.

    Failure semantics:
      * `block_on_missing_required=true` + a required pack red  -> exit 1.
      * `block_on_missing_required=false` -> always exit 0 with summary.
    """
    # Resolve recipe path: accept absolute, repo-relative, or recipes/<game>/<name>.yaml.
    candidates = [
        recipe_path,
        Path.cwd() / recipe_path,
        _recipes_dir() / recipe_path,
    ]
    resolved = next((c for c in candidates if c.exists()), None)
    if resolved is None:
        msg = f"recipe_not_found: tried {[str(c) for c in candidates]}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_from_recipe_error={msg}")
        raise typer.Exit(code=1)

    try:
        doc = _load_recipe(resolved)
    except Exception as exc:
        msg = f"recipe_parse_failed: {exc}"
        if json_out:
            json.dump({"error": msg, "path": str(resolved)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_from_recipe_error={msg}")
        raise typer.Exit(code=1)

    recipe_meta = doc.get("recipe") or {}
    game_scope = recipe_meta.get("game", "unknown")
    gates = doc.get("gates") or {}
    required_ids = set(gates.get("required_pack_ids") or [])
    block_on_missing = bool(gates.get("block_on_missing_required", True))

    packs = list(doc.get("packs") or [])
    if only_required:
        packs = [p for p in packs if p.get("id") in required_ids]
    if skip:
        skip_set = set(skip)
        packs = [p for p in packs if p.get("id") not in skip_set]

    # Lazy import — keeps `pack --help` fast (avoids flax_wrapper import chain)
    from assetboy.workflows.acquisition_router import acquire_source_dir
    from assetboy.workflows.pack_pipeline import (
        PipelineContext,
        execute_prepare_pack_dispatched,
    )

    results: list[dict[str, Any]] = []
    fail_count = 0
    required_fail = False

    for pack in packs:
        pack_id = pack.get("id", "?")
        is_required = pack_id in required_ids

        # Path B s11 (2026-05-11): pre-pack acquisition router. Maps recipe
        # acquisition_method (direct_url / manual_browser / generator) to a
        # real source_dir BEFORE pack_pipeline runs. Without this every pack
        # went RED because pack_pipeline rejects missing source_dir.
        acq = acquire_source_dir(pack, doc, dry_run=dry_run)

        if not acq.ok and not acq.awaiting_manual:
            # Acquisition failed outright (unsupported provider, runner crash,
            # etc.) -- skip pack_pipeline and record the failure cleanly.
            ledger = {
                "status": "failed",
                "current_state": "acquisition_failed",
                "next_step": "fix recipe + retry",
                "error": acq.error,
                "method": acq.method,
                "provider": acq.provider,
            }
        elif acq.awaiting_manual:
            # manual_browser lane: marker emitted, waiting for operator drop.
            # Not a failure -- pack is paused. Don't run pack_pipeline yet.
            ledger = {
                "status": "pending_manual_drop",
                "current_state": "awaiting_manual_browser_drop",
                "next_step": acq.notes,
                "method": acq.method,
                "provider": acq.provider,
                "drop_dir": str(acq.source_dir) if acq.source_dir else "",
            }
        else:
            # Acquisition green -- hand source_dir to pack_pipeline.
            ctx = PipelineContext(
                pack_id=pack_id,
                game_scope=game_scope,
                source_dir=acq.source_dir,
                bulk_profile=None,
                cleanup_mode=(pack.get("cleanup") or {}).get("mode", "auto"),
                asset_kind=pack.get("asset_kind", "prop"),
                animated=pack.get("asset_kind") in ("character_animated", "animation"),
                dry_run=dry_run,
                resume=resume,
            )
            try:
                ledger = execute_prepare_pack_dispatched(ctx)
            except Exception as exc:
                ledger = {
                    "status": "failed", "current_state": "failed", "error": str(exc),
                }

        status = ledger.get("status", "?")
        results.append(
            {
                "pack_id": pack_id,
                "required": is_required,
                "status": status,
                "current_state": ledger.get("current_state", "?"),
                "next_step": ledger.get("next_step", "?"),
                "ledger_path": ledger.get("ledger_path", ""),
                "error": ledger.get("error"),
                "method": ledger.get("method", ""),  # populated by acquisition router
                "provider": ledger.get("provider", ""),
            }
        )

        # pending_manual_drop is NOT a failure -- it's a green-pause waiting
        # for operator action (per s11 acquisition_router contract).
        if status not in ("completed", "pending_manual_drop"):
            fail_count += 1
            if is_required:
                required_fail = True

        if not json_out:
            tag = "REQ" if is_required else "opt"
            marker = {
                "completed": "OK ",
                "pending_manual_drop": "WAIT",
            }.get(status, "RED")
            print(
                f"  [{marker:4}] [{tag}] {pack_id:60} "
                f"state={ledger.get('current_state', '?')}"
            )

    if json_out:
        payload = {
            "recipe_id": recipe_meta.get("id"),
            "game": game_scope,
            "total_packs": len(packs),
            "completed": sum(1 for r in results if r["status"] == "completed"),
            "failed": fail_count,
            "required_failed": required_fail,
            "block_on_missing_required": block_on_missing,
            "results": results,
        }
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print()
        print(f"pack_from_recipe_total={len(packs)}")
        print(f"pack_from_recipe_completed={sum(1 for r in results if r['status'] == 'completed')}")
        print(f"pack_from_recipe_failed={fail_count}")
        print(f"pack_from_recipe_required_failed={'true' if required_fail else 'false'}")

    if required_fail and block_on_missing:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# pack status
# --------------------------------------------------------------------------- #

@app.command("status")
def status_cmd(
    pack_id: Annotated[
        str, typer.Argument(help="Pack ID (e.g. SHARED_FAB_FOLIAGE_FOREST_...)."),
    ],
    game_scope: Annotated[
        str,
        typer.Option("--game", help="Game scope (default: primitive_tech)."),
    ] = "primitive_tech",
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Read-only ledger inspection for a single pack."""
    from assetboy.workflows.pack_pipeline import read_pack_pipeline_status

    try:
        ledger = read_pack_pipeline_status(pack_id=pack_id, game_scope=game_scope)
    except Exception as exc:
        msg = str(exc)
        if json_out:
            json.dump({"error": msg, "pack_id": pack_id}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_status_error={msg}")
        raise typer.Exit(code=1)

    if json_out:
        json.dump(ledger, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        for k in ("status", "current_state", "next_step", "ready_for_flax_intake",
                  "source_lane", "source_dir", "reviewed_source_dir",
                  "publish_dir", "packet_path", "error", "ledger_path"):
            if k in ledger and ledger[k] is not None:
                print(f"pack_status_{k}={ledger[k]}")


if __name__ == "__main__":
    app()
