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
# Shared per-pack execution helper (v1.6.s6)
# --------------------------------------------------------------------------- #

def _acquire_and_run_one_pack(
    *,
    pack: dict[str, Any],
    recipe_doc: dict[str, Any],
    dry_run: bool,
    resume: bool,
) -> dict[str, Any]:
    """Acquire source_dir for one pack, then run it through pack_pipeline.

    Extracted from `from_recipe_cmd` per Path B v1.6.s6 (2026-05-11) so the
    new `run-pack` command can reuse the same logic without duplicating it.

    Returns a ledger-shape dict with at least: status, current_state. May
    include: next_step, error, method, provider, drop_dir, ledger_path,
    source_lane, source_dir, reviewed_source_dir, publish_dir, packet_path.

    Three terminal flavors:
      - acquisition failed:        status="failed", current_state="acquisition_failed"
      - awaiting manual drop:      status="pending_manual_drop",
                                   current_state="awaiting_manual_browser_drop"
      - acquisition green:         delegates to pack_pipeline; returns its ledger
    """
    # Lazy imports (keep cli --help fast)
    from assetboy.workflows.acquisition_router import acquire_source_dir
    from assetboy.workflows.pack_pipeline import (
        PipelineContext,
        execute_prepare_pack_dispatched,
    )

    pack_id = pack.get("id", "?")
    recipe_meta = recipe_doc.get("recipe") or {}
    game_scope = recipe_meta.get("game", "unknown")

    acq = acquire_source_dir(pack, recipe_doc, dry_run=dry_run)

    if not acq.ok and not acq.awaiting_manual:
        return {
            "status": "failed",
            "current_state": "acquisition_failed",
            "next_step": "fix recipe + retry",
            "error": acq.error,
            "method": acq.method,
            "provider": acq.provider,
        }
    if acq.awaiting_manual:
        return {
            "status": "pending_manual_drop",
            "current_state": "awaiting_manual_browser_drop",
            "next_step": acq.notes,
            "method": acq.method,
            "provider": acq.provider,
            "drop_dir": str(acq.source_dir) if acq.source_dir else "",
        }

    # Acquisition green — hand source_dir to pack_pipeline
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
        return execute_prepare_pack_dispatched(ctx)
    except Exception as exc:
        return {"status": "failed", "current_state": "failed", "error": str(exc)}


# --------------------------------------------------------------------------- #
# pack from-recipe
# --------------------------------------------------------------------------- #

@app.command("from-recipe")
def from_recipe_cmd(
    recipe_path: Annotated[
        str,
        typer.Argument(
            help=(
                "Path to a YAML recipe (or a recipe_id resolvable under recipes/). "
                "Pass '-' to read YAML from stdin. Ignored when --inline-yaml is set."
            ),
        ),
    ] = "",
    inline_yaml: Annotated[
        str,
        typer.Option(
            "--inline-yaml",
            help=(
                "YAML recipe content as a string (Path B v1.6.s1). When set, "
                "recipe_path is ignored. Used by the flax-mcp facade to avoid "
                "on-disk recipe dependency."
            ),
        ),
    ] = "",
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

    Recipe source (one of three modes):
      1. File path argument: `pack from-recipe path/to/recipe.yaml`
      2. Stdin: `cat recipe.yaml | pack from-recipe -`
      3. Inline string: `pack from-recipe --inline-yaml "recipe: {...}\\npacks: [...]"`

    Failure semantics:
      * `block_on_missing_required=true` + a required pack red  -> exit 1.
      * `block_on_missing_required=false` -> always exit 0 with summary.
    """
    # ----- Path B v1.6.s1: resolve recipe source (3 modes) ------------------
    doc = None
    source_label = ""

    if inline_yaml:
        # Mode 3: --inline-yaml content takes precedence over recipe_path.
        if yaml is None:
            msg = "pyyaml_not_installed (pip install pyyaml)"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_from_recipe_error={msg}")
            raise typer.Exit(code=1)
        try:
            doc = yaml.safe_load(inline_yaml)
            source_label = "<inline-yaml>"
        except Exception as exc:
            msg = f"inline_yaml_parse_failed: {exc}"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_from_recipe_error={msg}")
            raise typer.Exit(code=1)
    elif recipe_path == "-":
        # Mode 2: stdin
        if yaml is None:
            msg = "pyyaml_not_installed (pip install pyyaml)"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_from_recipe_error={msg}")
            raise typer.Exit(code=1)
        try:
            stdin_text = sys.stdin.read()
            if not stdin_text.strip():
                raise ValueError("stdin is empty")
            doc = yaml.safe_load(stdin_text)
            source_label = "<stdin>"
        except Exception as exc:
            msg = f"stdin_recipe_parse_failed: {exc}"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_from_recipe_error={msg}")
            raise typer.Exit(code=1)
    elif recipe_path:
        # Mode 1: file path (original behavior)
        recipe_path_obj = Path(recipe_path)
        candidates = [
            recipe_path_obj,
            Path.cwd() / recipe_path_obj,
            _recipes_dir() / recipe_path_obj,
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
            source_label = str(resolved)
        except Exception as exc:
            msg = f"recipe_parse_failed: {exc}"
            if json_out:
                json.dump({"error": msg, "path": str(resolved)}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_from_recipe_error={msg}")
            raise typer.Exit(code=1)
    else:
        # No source given
        msg = (
            "missing_recipe_source: pass a path, '-' for stdin, "
            "or use --inline-yaml"
        )
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_from_recipe_error={msg}")
        raise typer.Exit(code=1)

    if not isinstance(doc, dict):
        msg = f"recipe_must_be_a_mapping (got {type(doc).__name__})"
        if json_out:
            json.dump({"error": msg, "source": source_label}, sys.stdout, indent=2)
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

    results: list[dict[str, Any]] = []
    fail_count = 0
    required_fail = False

    for pack in packs:
        pack_id = pack.get("id", "?")
        is_required = pack_id in required_ids
        ledger = _acquire_and_run_one_pack(
            pack=pack,
            recipe_doc=doc,
            dry_run=dry_run,
            resume=resume,
        )

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


# --------------------------------------------------------------------------- #
# pack audit
# --------------------------------------------------------------------------- #

@app.command("audit")
def audit_cmd(
    include_ledgers: Annotated[
        bool,
        typer.Option(
            "--ledgers/--no-ledgers",
            help="Include per-ledger summary entries (default: yes).",
        ),
    ] = True,
    max_ledgers: Annotated[
        int,
        typer.Option(
            "--max",
            help="Cap on number of ledger entries returned (response size).",
        ),
    ] = 1000,
    game: Annotated[
        str,
        typer.Option(
            "--game",
            help="Filter to one game_scope (default: all games).",
        ),
    ] = "",
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Inventory all pack_pipeline ledgers + aggregate status counts.

    Path B v1.6.s3 (2026-05-11). Useful for ops dashboards: shows what
    ran across all games + per-game status breakdown. Tolerant of broken
    ledgers (they're counted under `status: unreadable`).

    The same report is exposed over HTTP at `GET /api/v1/packs/audit`.
    """
    from assetboy.workflows.pack_audit import build_pack_audit_report

    report = build_pack_audit_report(
        include_ledgers=include_ledgers,
        max_ledgers=max_ledgers,
    )

    # Apply --game filter post-hoc (keep the shape unified)
    if game:
        report["games"] = {
            k: v for k, v in (report.get("games") or {}).items() if k == game
        }
        if report.get("ledgers"):
            report["ledgers"] = [
                e for e in report["ledgers"] if e.get("game_scope") == game
            ]
        # Recompute summary for the filtered scope
        from collections import Counter
        filtered_status = Counter()
        for entry in (report.get("ledgers") or []):
            filtered_status[entry.get("status", "unknown")] += 1
        report["summary"] = {
            "total_ledgers": sum(filtered_status.values()),
            "by_status": dict(filtered_status),
            "filtered_to_game": game,
        }

    if json_out:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    summary = report.get("summary", {})
    print(f"pack_audit_pipeline_dir={report.get('pipeline_dir', '?')}")
    print(f"pack_audit_total_ledgers={summary.get('total_ledgers', 0)}")
    by_status = summary.get("by_status") or {}
    for status, count in sorted(by_status.items()):
        print(f"pack_audit_status_{status}={count}")
    games = report.get("games") or {}
    print(f"pack_audit_game_count={len(games)}")
    for game_scope, game_data in sorted(games.items()):
        total = game_data.get("total", 0)
        statuses = game_data.get("by_status") or {}
        status_str = ", ".join(
            f"{s}={c}" for s, c in sorted(statuses.items())
        ) or "(none)"
        print(f"pack_audit_game  {game_scope}  total={total}  {status_str}")


# --------------------------------------------------------------------------- #
# pack validate
# --------------------------------------------------------------------------- #

@app.command("validate")
def validate_cmd(
    recipe_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a YAML recipe (or a recipe_id resolvable under recipes/).",
        ),
    ],
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Treat warnings as errors (exit 1 if any warning).",
        ),
    ] = False,
) -> None:
    """Lint a recipe YAML against the v1 schema.

    Path B v1.6.s5 (2026-05-11). Catches shape bugs BEFORE pack from-recipe
    runs them:
      - missing required fields (id, provider, acquisition_method)
      - unknown acquisition_method (must be one of: direct_url / manual_browser / generator)
      - lane-specific provider whitelist violations (warning)
      - generator packs missing 'prompts: [...]' (error)
      - direct_url packs with no assets[] AND no search_terms[] (error)
      - manual_browser packs with no source_url AND no assets[] (warning)
      - duplicate pack ids within the recipe (error)
      - gates referencing pack ids not in the packs[] list (error)
      - missing recommended fields (asset_kind, license) -> warning only

    Exit code: 0 if ok; 1 if errors; 1 also if --strict and any warnings.
    """
    # Resolve the recipe path: accept absolute, repo-relative, or recipes/<game>/<name>.yaml
    candidates = [
        recipe_path,
        Path.cwd() / recipe_path,
        _recipes_dir() / recipe_path,
    ]
    resolved = next((c for c in candidates if c.exists()), None)
    if resolved is None:
        if json_out:
            json.dump(
                {"ok": False, "error": "recipe_not_found",
                 "candidates": [str(c) for c in candidates]},
                sys.stdout, indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(f"pack_validate_error=recipe_not_found")
            print(f"pack_validate_tried={'; '.join(str(c) for c in candidates)}")
        raise typer.Exit(code=1)

    from assetboy.workflows.recipe_validator import validate_recipe_file

    result = validate_recipe_file(resolved)

    if json_out:
        json.dump(
            {
                "ok": result.ok,
                "recipe_id": result.recipe_id,
                "pack_count": result.pack_count,
                "errors": result.errors,
                "warnings": result.warnings,
                "path": str(resolved),
                "strict_mode": strict,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"pack_validate_path={resolved}")
        print(f"pack_validate_ok={'true' if result.ok else 'false'}")
        print(f"pack_validate_recipe_id={result.recipe_id}")
        print(f"pack_validate_pack_count={result.pack_count}")
        print(f"pack_validate_error_count={len(result.errors)}")
        print(f"pack_validate_warning_count={len(result.warnings)}")
        for idx, err in enumerate(result.errors, start=1):
            print(f"pack_validate_error_{idx}={err}")
        for idx, warn in enumerate(result.warnings, start=1):
            print(f"pack_validate_warning_{idx}={warn}")

    exit_code = 0 if result.ok else 1
    if strict and result.warnings:
        exit_code = 1
    if exit_code:
        raise typer.Exit(code=exit_code)


# --------------------------------------------------------------------------- #
# pack export-summary (v1.8.s17)
# --------------------------------------------------------------------------- #

@app.command("export-summary")
def export_summary_cmd(
    recipe_path: Annotated[
        Path,
        typer.Argument(help="Path to the recipe YAML to summarize."),
    ],
    out: Annotated[
        str,
        typer.Option(
            "--out",
            help="Write the markdown summary to this path (default: stdout).",
        ),
    ] = "",
) -> None:
    """Render a markdown summary of a recipe's current pack state (Path B v1.8.s17).

    Joins the recipe YAML with the latest pack_pipeline ledgers to produce
    a shareable status report. Useful for:
      - PR descriptions ('here's where my recipe stands')
      - Slack/issue updates
      - AI-agent inspection (one doc instead of N ledgers)

    Sections:
      - Status counts
      - Per-pack table (pack_id / provider / method / status / current_state)
      - Manual drops required (if any)
      - Failed packs with errors (if any)
      - Recommended next actions
    """
    # Resolve recipe path
    candidates = [
        recipe_path,
        Path.cwd() / recipe_path,
        _recipes_dir() / recipe_path,
    ]
    resolved = next((c for c in candidates if c.exists()), None)
    if resolved is None:
        print(f"pack_export_summary_error=recipe_not_found")
        print(f"pack_export_summary_tried={'; '.join(str(c) for c in candidates)}")
        raise typer.Exit(code=1)

    try:
        doc = _load_recipe(resolved)
    except Exception as exc:
        print(f"pack_export_summary_error=recipe_parse_failed: {exc}")
        raise typer.Exit(code=1)

    from assetboy.workflows.pack_summary import render_pack_summary
    markdown = render_pack_summary(doc)

    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
        print(f"pack_export_summary_written={out_path}")
        print(f"pack_export_summary_bytes={out_path.stat().st_size}")
    else:
        # Stdout
        sys.stdout.write(markdown)


# --------------------------------------------------------------------------- #
# pack validate-all (v1.8.s19)
# --------------------------------------------------------------------------- #

@app.command("validate-all")
def validate_all_cmd(
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Treat warnings as errors (exit 1 if any warning).",
        ),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Validate every recipe under recipes/ (Path B v1.8.s19).

    Walks the recipes/ tree, runs the v1.6.s5 validator on each recipe,
    and emits an aggregate summary. Useful for CI / pre-push hooks.

    Exit code:
      0 if ALL recipes pass (warnings allowed unless --strict)
      1 if ANY recipe has errors (or --strict and any has warnings)
    """
    from assetboy.workflows.recipe_validator import validate_recipe_file

    recipes_root = _recipes_dir()
    if not recipes_root.exists():
        msg = f"recipes_dir_not_found: {recipes_root}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_validate_all_error={msg}")
        raise typer.Exit(code=1)

    per_recipe: list[dict[str, Any]] = []
    total = 0
    pass_count = 0
    error_count = 0
    warn_count = 0
    aggregate_ok = True

    # Walk recipes/<game>/<recipe>.yaml
    for game_dir in sorted(p for p in recipes_root.iterdir() if p.is_dir()):
        for recipe_file in sorted(game_dir.glob("*.yaml")):
            total += 1
            result = validate_recipe_file(recipe_file)
            this_ok = result.ok
            if strict and result.warnings:
                this_ok = False
            if this_ok:
                pass_count += 1
            else:
                error_count += 1
                aggregate_ok = False
            if result.warnings:
                warn_count += 1
            per_recipe.append({
                "path": str(recipe_file.relative_to(recipes_root)),
                "recipe_id": result.recipe_id,
                "pack_count": result.pack_count,
                "ok": this_ok,
                "errors": result.errors,
                "warnings": result.warnings,
            })

    if json_out:
        json.dump(
            {
                "total": total,
                "passed": pass_count,
                "failed": error_count,
                "with_warnings": warn_count,
                "strict_mode": strict,
                "recipes": per_recipe,
                "aggregate_ok": aggregate_ok,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"pack_validate_all_total={total}")
        print(f"pack_validate_all_passed={pass_count}")
        print(f"pack_validate_all_failed={error_count}")
        print(f"pack_validate_all_with_warnings={warn_count}")
        for entry in per_recipe:
            marker = "OK " if entry["ok"] else "RED"
            warn_hint = (
                f"  warnings={len(entry['warnings'])}"
                if entry["warnings"] else ""
            )
            print(
                f"  [{marker}] {entry['path']:50} "
                f"recipe_id={entry['recipe_id']:35}"
                f"  packs={entry['pack_count']}"
                f"{warn_hint}"
            )
            for err in entry["errors"]:
                print(f"      ERROR: {err}")

    if not aggregate_ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# pack run-pack (v1.6.s6)
# --------------------------------------------------------------------------- #
# pack diff (v1.7.s14)
# --------------------------------------------------------------------------- #

@app.command("diff")
def diff_cmd(
    old_recipe: Annotated[
        Path,
        typer.Argument(help="Path to the OLD recipe YAML (baseline)."),
    ],
    new_recipe: Annotated[
        Path,
        typer.Argument(help="Path to the NEW recipe YAML (compared against old)."),
    ],
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Semantic diff between two recipe YAMLs (Path B v1.7.s14).

    Shows what changed at the pack + recipe + gate level:
      - added / removed packs
      - per-pack changed fields (provider, acquisition_method, license, ...)
      - prompts/assets/search_terms COUNT changes
      - gates required_pack_ids changes

    Unlike a raw `git diff`, this is semantic: a recipe reformat doesn't
    show up; only meaningful changes do.

    Exit code:
      0 = no changes
      1 = changes detected (also when files can't be read/parsed)
    """
    # Resolve both recipe paths (accept absolute / cwd-relative / recipes/<game>/<f>.yaml)
    def _resolve(p: Path) -> Path | None:
        candidates = [p, Path.cwd() / p, _recipes_dir() / p]
        return next((c for c in candidates if c.exists()), None)

    old_resolved = _resolve(old_recipe)
    new_resolved = _resolve(new_recipe)

    if old_resolved is None or new_resolved is None:
        msg = (
            f"recipe_not_found: "
            f"old={'OK' if old_resolved else 'MISSING'} "
            f"new={'OK' if new_resolved else 'MISSING'}"
        )
        if json_out:
            json.dump(
                {
                    "error": msg,
                    "old_recipe": str(old_recipe),
                    "new_recipe": str(new_recipe),
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(f"pack_diff_error={msg}")
        raise typer.Exit(code=1)

    try:
        old_doc = _load_recipe(old_resolved)
        new_doc = _load_recipe(new_resolved)
    except Exception as exc:
        msg = f"recipe_parse_failed: {exc}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_diff_error={msg}")
        raise typer.Exit(code=1)

    from assetboy.workflows.recipe_diff import diff_recipes, diff_result_to_dict

    diff = diff_recipes(old_doc, new_doc)

    if json_out:
        payload = diff_result_to_dict(diff)
        payload["old_recipe"] = str(old_resolved)
        payload["new_recipe"] = str(new_resolved)
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(f"pack_diff_old={old_resolved}")
        print(f"pack_diff_new={new_resolved}")
        print(f"pack_diff_has_changes={'true' if diff.has_changes else 'false'}")
        print(f"pack_diff_added_count={len(diff.added_packs)}")
        for pid in diff.added_packs:
            print(f"pack_diff_added={pid}")
        print(f"pack_diff_removed_count={len(diff.removed_packs)}")
        for pid in diff.removed_packs:
            print(f"pack_diff_removed={pid}")
        print(f"pack_diff_modified_count={len(diff.modified_packs)}")
        for mod in diff.modified_packs:
            print(f"pack_diff_modified  pack_id={mod.pack_id}  fields={len(mod.changed_fields)}")
            for change in mod.changed_fields:
                print(f"  pack_diff_field  {change.field}={change.old!r} -> {change.new!r}")
        if diff.recipe_field_changes:
            print(f"pack_diff_recipe_fields_count={len(diff.recipe_field_changes)}")
            for change in diff.recipe_field_changes:
                print(f"  pack_diff_recipe_field  {change.field}={change.old!r} -> {change.new!r}")
        for gate_key, gate_ids in diff.gate_changes.items():
            for gid in gate_ids:
                print(f"pack_diff_gate  {gate_key}={gid}")

    if diff.has_changes:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# pack rerun-failed (v1.6.s8)
# --------------------------------------------------------------------------- #

@app.command("rerun-failed")
def rerun_failed_cmd(
    recipe_path: Annotated[
        str,
        typer.Option(
            "--recipe",
            help=(
                "Recipe YAML to source pack specs from. The audit names which "
                "packs failed, the recipe provides the pack body to re-fire."
            ),
        ),
    ] = "",
    game: Annotated[
        str,
        typer.Option("--game", help="Filter to one game_scope (default: all)."),
    ] = "",
    skip_acquisition_failures: Annotated[
        bool,
        typer.Option(
            "--skip-acquisition-failures",
            help=(
                "Exclude packs whose current_state is 'acquisition_failed' "
                "(router-level failures, typically config; not pack_pipeline)."
            ),
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan only; don't re-execute."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Re-run all packs that previously failed (Path B v1.6.s8).

    Walks `state/pack_pipeline/<game>/*.json`, finds packs with
    `status=failed`, and re-fires them using the original recipe's pack
    definitions. Useful after fixing a transient config problem (e.g.
    operator added Fab auth, started ComfyUI, set workspace path).

    Requires `--recipe <path>` so the command can look up each failed
    pack's spec by id.

    Without `--skip-acquisition-failures`, includes router-level failures
    (typically the ones most worth retrying after a config fix).
    """
    if not recipe_path:
        msg = "missing_recipe: pass --recipe <path> so we know each pack's spec"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_rerun_failed_error={msg}")
        raise typer.Exit(code=1)

    # Resolve recipe path
    candidates = [
        Path(recipe_path),
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
            print(f"pack_rerun_failed_error={msg}")
        raise typer.Exit(code=1)

    try:
        recipe_doc = _load_recipe(resolved)
    except Exception as exc:
        msg = f"recipe_parse_failed: {exc}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_rerun_failed_error={msg}")
        raise typer.Exit(code=1)

    # Build a pack_id -> pack lookup from the recipe
    pack_by_id = {
        str(p.get("id")): p
        for p in (recipe_doc.get("packs") or [])
        if isinstance(p, dict) and p.get("id")
    }
    recipe_game = (recipe_doc.get("recipe") or {}).get("game", "")
    effective_game_filter = game or recipe_game

    # Find failed packs from the audit
    from assetboy.workflows.pack_audit import find_failed_packs
    failed = find_failed_packs(
        game_filter=effective_game_filter,
        include_acquisition_failed=not skip_acquisition_failures,
    )

    # Cross-reference with recipe -- skip failed packs that aren't in this recipe
    targets: list[dict[str, Any]] = []
    skipped_not_in_recipe: list[str] = []
    for failed_entry in failed:
        pid = failed_entry.get("pack_id", "")
        if pid in pack_by_id:
            targets.append(pack_by_id[pid])
        else:
            skipped_not_in_recipe.append(pid)

    if not targets:
        # Either no failures, or no matching packs in recipe
        summary = {
            "ok": True,
            "recipe": str(resolved),
            "game_filter": effective_game_filter,
            "total_failed_in_audit": len(failed),
            "matched_in_recipe": 0,
            "skipped_not_in_recipe": skipped_not_in_recipe,
            "results": [],
        }
        if json_out:
            json.dump(summary, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_rerun_failed_total_failed_in_audit={len(failed)}")
            print(f"pack_rerun_failed_matched_in_recipe=0")
            for pid in skipped_not_in_recipe:
                print(f"pack_rerun_failed_skipped={pid}")
        return

    # Execute the matched packs
    results: list[dict[str, Any]] = []
    re_success = 0
    re_fail = 0
    for pack in targets:
        pid = pack.get("id", "?")
        ledger = _acquire_and_run_one_pack(
            pack=pack,
            recipe_doc=recipe_doc,
            dry_run=dry_run,
            resume=True,  # always resume; this is a retry
        )
        status = ledger.get("status", "?")
        results.append(
            {
                "pack_id": pid,
                "status": status,
                "current_state": ledger.get("current_state", "?"),
                "error": ledger.get("error"),
            }
        )
        if status in ("completed", "pending_manual_drop"):
            re_success += 1
        else:
            re_fail += 1
        if not json_out:
            marker = "OK " if status == "completed" else (
                "WAIT" if status == "pending_manual_drop" else "RED"
            )
            print(f"  [{marker}] {pid:60} state={ledger.get('current_state', '?')}")

    summary = {
        "ok": re_fail == 0,
        "recipe": str(resolved),
        "game_filter": effective_game_filter,
        "total_failed_in_audit": len(failed),
        "matched_in_recipe": len(targets),
        "skipped_not_in_recipe": skipped_not_in_recipe,
        "rerun_succeeded": re_success,
        "rerun_failed": re_fail,
        "results": results,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"pack_rerun_failed_total={len(targets)}")
        print(f"pack_rerun_failed_succeeded={re_success}")
        print(f"pack_rerun_failed_failed={re_fail}")
        if skipped_not_in_recipe:
            print(f"pack_rerun_failed_skipped_count={len(skipped_not_in_recipe)}")

    if re_fail > 0:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# pack run-pack (v1.6.s6)
# --------------------------------------------------------------------------- #

@app.command("run-pack")
def run_pack_cmd(
    inline_yaml: Annotated[
        str,
        typer.Option(
            "--pack",
            help=(
                "Single-pack YAML body (the inner pack dict, not a full recipe). "
                "Mutually exclusive with --pack-from-stdin."
            ),
        ),
    ] = "",
    pack_from_stdin: Annotated[
        bool,
        typer.Option(
            "--pack-from-stdin",
            help="Read the pack YAML from stdin.",
        ),
    ] = False,
    game_scope: Annotated[
        str,
        typer.Option(
            "--game",
            help="Game scope for the pack (used in ledger path).",
        ),
    ] = "sandbox",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan only; no real downloads/cleanup."),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Skip already-completed stages."),
    ] = True,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Run a single pack through the pack pipeline (Path B v1.6.s6).

    Unlike `pack from-recipe` (which loads a full recipe doc + iterates
    its packs[]), this command takes one pack dict directly. Used by the
    flax-mcp facade to fire one pack at a time, or by operators
    quick-testing a pack without authoring a full recipe.

    Source modes (mutually exclusive):
      --pack '<yaml>'        : inline single-pack YAML body
      --pack-from-stdin      : read pack YAML from stdin

    The pack body must look like one entry from a recipe's packs[] list:
        id: TEST_PACK_01
        provider: polyhaven
        acquisition_method: direct_url
        assets:
          - asset_id: brick_wall_04

    Returns the ledger dict (same shape as `pack status <id>` output).
    """
    if not inline_yaml and not pack_from_stdin:
        msg = "missing_pack_source: pass --pack '<yaml>' or --pack-from-stdin"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_pack_error={msg}")
        raise typer.Exit(code=1)
    if inline_yaml and pack_from_stdin:
        msg = "conflicting_source: pass either --pack OR --pack-from-stdin, not both"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_pack_error={msg}")
        raise typer.Exit(code=1)

    if yaml is None:
        msg = "pyyaml_not_installed"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_pack_error={msg}")
        raise typer.Exit(code=1)

    try:
        if pack_from_stdin:
            stdin_text = sys.stdin.read()
            if not stdin_text.strip():
                raise ValueError("stdin is empty")
            pack_doc = yaml.safe_load(stdin_text)
        else:
            pack_doc = yaml.safe_load(inline_yaml)
    except Exception as exc:
        msg = f"pack_yaml_parse_failed: {exc}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_pack_error={msg}")
        raise typer.Exit(code=1)

    if not isinstance(pack_doc, dict):
        msg = f"pack_must_be_a_mapping (got {type(pack_doc).__name__})"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_pack_error={msg}")
        raise typer.Exit(code=1)

    if not pack_doc.get("id"):
        msg = "pack_missing_id: 'id' field is required"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_pack_error={msg}")
        raise typer.Exit(code=1)

    # Synthesize a minimal recipe doc for the helper
    synthetic_recipe = {"recipe": {"id": "ad_hoc", "game": game_scope}, "packs": [pack_doc]}
    ledger = _acquire_and_run_one_pack(
        pack=pack_doc,
        recipe_doc=synthetic_recipe,
        dry_run=dry_run,
        resume=resume,
    )

    if json_out:
        json.dump(ledger, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        pack_id = pack_doc.get("id", "?")
        status = ledger.get("status", "?")
        print(f"pack_run_pack_id={pack_id}")
        print(f"pack_run_pack_status={status}")
        print(f"pack_run_pack_current_state={ledger.get('current_state', '?')}")
        if ledger.get("error"):
            print(f"pack_run_pack_error={ledger['error']}")
        if ledger.get("next_step"):
            print(f"pack_run_pack_next_step={ledger['next_step']}")

    if ledger.get("status") not in ("completed", "pending_manual_drop"):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
