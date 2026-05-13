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
    filter_: Annotated[
        list[str],
        typer.Option(
            "--filter",
            help=(
                "Filter by recipe metadata: 'genre:rpg', 'theme:fantasy', "
                "'style:lowpoly', 'tags:smoke-test'. Repeatable; all filters "
                "AND together. Matches against string OR list-entry fields."
            ),
        ),
    ] = None,
    sort: Annotated[
        str,
        typer.Option(
            "--sort",
            help=(
                "v1.14.s105 / v1.22.s151: sort recipes by 'tier'"
                " (most-critical-first; min pack tier; untiered last),"
                " 'name' (alphabetical by recipe_id), or 'path'"
                " (default: directory order)."
            ),
        ),
    ] = "path",
    reverse: Annotated[
        bool,
        typer.Option(
            "--reverse",
            help=(
                "v1.17.s121: reverse the sorted order. Combined with"
                " --sort tier yields least-critical-first."
            ),
        ),
    ] = False,
    recipes_root_override: Annotated[
        str,
        typer.Option(
            "--recipes-root",
            help=(
                "v1.23.s160: override the recipes/ scan root (default:"
                " auto-detect repo recipes/). Useful for tests + custom"
                " catalogs."
            ),
        ),
    ] = "",
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help=(
                "v1.34.s200: emit single-line JSON (no indentation)."
                " Useful for piping to jq / shell tools. No effect"
                " without --json."
            ),
        ),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """List available YAML recipes under recipes/<game>/<*>.yaml.

    v1.11.s53: supports --filter for metadata-driven discovery.
    Examples:
      pack list-recipes --filter genre:rpg
      pack list-recipes --filter theme:fantasy --filter style:lowpoly
      pack list-recipes --filter tags:smoke-test --json
    """
    recipes_root = (
        Path(recipes_root_override) if recipes_root_override.strip()
        else _recipes_dir()
    )
    if not recipes_root.exists():
        msg = f"recipes_dir_not_found: {recipes_root}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_list_recipes_error={msg}")
        raise typer.Exit(code=1)

    # Parse --filter 'field:value' pairs.
    parsed_filters: list[tuple[str, str]] = []
    for f in (filter_ or []):
        if ":" not in f:
            msg = f"bad_filter_shape: {f!r} (expected 'field:value')"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_list_recipes_error={msg}")
            raise typer.Exit(code=1)
        field_name, _, value = f.partition(":")
        parsed_filters.append((field_name.strip(), value.strip()))

    def _matches_filter(doc: dict, field_name: str, value: str) -> bool:
        """True if filter matches.

        Recipe-level fields: string equals or list-entry equals.
        v1.13.s98 — special pack-level filter: 'min-tier:N' matches recipes
        whose any pack has tier <= N (e.g. min-tier:0 finds recipes with
        critical packs).
        """
        # Pack-level: min-tier:N -> any pack has tier <= N.
        if field_name in ("min-tier", "min_tier"):
            try:
                threshold = int(value)
            except ValueError:
                return False
            packs = doc.get("packs") or []
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                t = pack.get("tier")
                if isinstance(t, int) and not isinstance(t, bool) and t <= threshold:
                    return True
            return False
        # v1.33.s199 — has-FIELD:true/false presence test (any recipe meta).
        if field_name.startswith("has-") or field_name.startswith("has_"):
            target = field_name[4:].strip().lower()
            wanted_present = value.strip().lower() in ("true", "yes", "1")
            recipe_d = doc.get("recipe") or {}
            val = recipe_d.get(target)
            is_present = (
                val is not None and (
                    not isinstance(val, str) or val.strip() != ""
                )
            )
            return is_present is wanted_present
        # Recipe-level fields.
        recipe = doc.get("recipe") or {}
        field_val = recipe.get(field_name)
        if field_val is None:
            return False
        # v1.29.s185 — author / contact use substring (case-insensitive)
        # since exact-match is impractical for human strings.
        if field_name in ("author", "contact"):
            if isinstance(field_val, str):
                return value.strip().lower() in field_val.strip().lower()
            return False
        if isinstance(field_val, str):
            return field_val.strip().lower() == value.strip().lower()
        if isinstance(field_val, list):
            return any(
                isinstance(e, str) and e.strip().lower() == value.strip().lower()
                for e in field_val
            )
        return False

    entries: list[dict] = []
    for game_dir in sorted(p for p in recipes_root.iterdir() if p.is_dir()):
        for recipe_yaml in sorted(game_dir.glob("*.yaml")):
            try:
                doc = _load_recipe(recipe_yaml)
                recipe = doc.get("recipe") or {}
                rid = recipe.get("id", "?")
                game = recipe.get("game", game_dir.name)
                pack_count = len((doc.get("packs") or []))
                # Apply --filter (AND across all filters).
                if parsed_filters:
                    if not all(
                        _matches_filter(doc, fn, fv)
                        for fn, fv in parsed_filters
                    ):
                        continue
                # Capture metadata for output too.
                entry_data: dict = {
                    "path": str(recipe_yaml.relative_to(recipes_root)),
                    "game": game,
                    "recipe_id": rid,
                    "pack_count": pack_count,
                }
                # v1.14.s105 — compute min_tier across packs for --sort tier.
                tier_values = []
                for pp in (doc.get("packs") or []):
                    if isinstance(pp, dict):
                        t = pp.get("tier")
                        if isinstance(t, int) and not isinstance(t, bool):
                            tier_values.append(t)
                if tier_values:
                    entry_data["min_tier"] = min(tier_values)
                # v1.23.s160 / v1.25.s172 / v1.30.s189: misc metadata.
                for meta_key in ("genre", "theme", "style", "tags",
                                  "created_utc", "updated_utc",
                                  "author", "contact", "platform"):
                    if meta_key in recipe:
                        entry_data[meta_key] = recipe[meta_key]
                entries.append(entry_data)
            except Exception as exc:
                # Skip malformed recipes silently in list (validate-all reports them).
                _ = exc
                if parsed_filters:
                    continue
                entries.append({
                    "path": str(recipe_yaml.relative_to(recipes_root)),
                    "game": game_dir.name,
                    "recipe_id": "?",
                    "pack_count": -1,
                })

    # v1.14.s105 — apply --sort.
    sort_norm = sort.strip().lower()
    if sort_norm == "tier":
        # Recipes with no min_tier sort last (treat as +inf).
        entries.sort(key=lambda e: (e.get("min_tier") is None, e.get("min_tier", 999), e["path"]))
    elif sort_norm == "name":
        # v1.22.s151 — alphabetical by recipe_id (then by path tiebreak).
        entries.sort(key=lambda e: (str(e.get("recipe_id", "")).lower(), e["path"]))
    elif sort_norm == "platform":
        # v1.30.s191 — alphabetical by platform; untagged sort last.
        entries.sort(key=lambda e: (
            e.get("platform") is None,
            str(e.get("platform", "")).lower(),
            e["path"],
        ))
    elif sort_norm in ("updated_utc", "created_utc"):
        # v1.32.s195 — sort by timestamp field (newest first);
        # entries without that field sort last.
        ts_key = sort_norm
        from datetime import datetime as _dt_now
        def _ts_to_epoch(v: object) -> float:
            if not isinstance(v, str):
                return -1.0
            try:
                return _dt_now.fromisoformat(v.strip()).timestamp()
            except (ValueError, TypeError):
                return -1.0
        entries.sort(key=lambda e: (
            e.get(ts_key) is None,
            -_ts_to_epoch(e.get(ts_key)),
            e["path"],
        ))
    elif sort_norm not in ("", "path"):
        # Unknown sort key -> error.
        msg = (
            f"unknown_sort_key: {sort_norm!r}"
            " (valid: 'path', 'tier', 'name', 'platform',"
            " 'updated_utc', 'created_utc')"
        )
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_list_recipes_error={msg}")
        raise typer.Exit(code=1)

    # v1.17.s121 — reverse after sort.
    if reverse:
        entries.reverse()

    if json_out:
        out = {
            "recipes": entries,
            "count": len(entries),
            "filters_applied": [f"{fn}:{fv}" for fn, fv in parsed_filters],
            "sort": sort_norm or "path",
            "reverse": reverse,
        }
        # v1.34.s200 — --compact emits single-line JSON.
        json.dump(out, sys.stdout, indent=None if compact else 2)
        sys.stdout.write("\n")
    else:
        print(f"pack_list_recipes_count={len(entries)}")
        if parsed_filters:
            print(f"pack_list_recipes_filters={','.join(f'{fn}:{fv}' for fn, fv in parsed_filters)}")
        if sort_norm and sort_norm != "path":
            print(f"pack_list_recipes_sort={sort_norm}")
        for idx, e in enumerate(entries, start=1):
            extras: list[str] = []
            for k in ("genre", "theme", "style", "tags"):
                if k in e:
                    v = e[k]
                    if isinstance(v, list):
                        v = ",".join(v)
                    extras.append(f"{k}={v}")
            extras_str = "  " + "  ".join(extras) if extras else ""
            print(
                f"pack_list_recipes_entry={idx}  "
                f"game={e['game']}  "
                f"id={e['recipe_id']}  "
                f"packs={e['pack_count']}  "
                f"path={e['path']}{extras_str}"
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

    # v1.21.s144 — pipeline_log records the stages this pack traversed.
    from datetime import datetime, timezone
    pipeline_log: list[dict] = []

    def _log(stage: str, status: str) -> None:
        pipeline_log.append({
            "stage": stage,
            "status": status,
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    _log("acquire_start", "running")
    acq = acquire_source_dir(pack, recipe_doc, dry_run=dry_run)

    if not acq.ok and not acq.awaiting_manual:
        _log("acquire", "failed")
        return {
            "status": "failed",
            "current_state": "acquisition_failed",
            "next_step": "fix recipe + retry",
            "error": acq.error,
            "method": acq.method,
            "provider": acq.provider,
            "pipeline_log": pipeline_log,
        }
    if acq.awaiting_manual:
        _log("acquire", "awaiting_manual_drop")
        return {
            "status": "pending_manual_drop",
            "current_state": "awaiting_manual_browser_drop",
            "next_step": acq.notes,
            "method": acq.method,
            "provider": acq.provider,
            "drop_dir": str(acq.source_dir) if acq.source_dir else "",
            "pipeline_log": pipeline_log,
        }
    _log("acquire", "ok")

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
    _log("pipeline_dispatch", "running")
    try:
        ledger = execute_prepare_pack_dispatched(ctx)
        _log("pipeline_dispatch", str(ledger.get("status", "unknown")))
        # Merge pipeline_log into returned ledger (don't clobber if pipeline
        # added its own).
        existing_log = ledger.get("pipeline_log") or []
        if isinstance(existing_log, list):
            ledger["pipeline_log"] = pipeline_log + existing_log
        else:
            ledger["pipeline_log"] = pipeline_log
        return ledger
    except Exception as exc:
        _log("pipeline_dispatch", f"crashed: {exc}")
        return {
            "status": "failed", "current_state": "failed",
            "error": str(exc), "pipeline_log": pipeline_log,
        }


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
    only: Annotated[
        list[str],
        typer.Option(
            "--only",
            help=(
                "Run ONLY these pack IDs (repeatable; v1.9.s21). "
                "Use to target a single pack from a multi-pack recipe."
            ),
        ),
    ] = None,
    only_required: Annotated[
        bool,
        typer.Option(
            "--only-required",
            help="Run only packs in gates.required_pack_ids.",
        ),
    ] = False,
    provider_only: Annotated[
        list[str],
        typer.Option(
            "--provider-only",
            help=(
                "v1.21.s147: run ONLY packs whose provider matches one of"
                " these ids (repeatable). E.g. --provider-only iconify"
                " --provider-only met_museum."
            ),
        ),
    ] = None,
    max_tier: Annotated[
        int,
        typer.Option(
            "--max-tier",
            help=(
                "v1.26.s178: run only packs whose tier is <= N (P0=0..P3=3)."
                " Default -1 = no tier filter. Composes with --only /"
                " --provider-only."
            ),
        ),
    ] = -1,
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
    # v1.9.s21: --only filter (most-restrictive; applied before --only-required + --skip)
    if only:
        only_set = set(only)
        packs = [p for p in packs if p.get("id") in only_set]
    if only_required:
        packs = [p for p in packs if p.get("id") in required_ids]
    # v1.21.s147 — --provider-only filter (case-insensitive).
    if provider_only:
        po_set = {p.strip().lower() for p in provider_only if p.strip()}
        packs = [
            p for p in packs
            if str(p.get("provider", "")).strip().lower() in po_set
        ]
    # v1.26.s178 — --max-tier filter (P0=0..P3=3); packs missing tier kept.
    if max_tier >= 0:
        if max_tier > 3:
            msg = f"max_tier_out_of_range: {max_tier} (expected 0..3 or -1)"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_from_recipe_error={msg}")
            raise typer.Exit(code=1)
        packs = [
            p for p in packs
            if not isinstance(p.get("tier"), int)
               or isinstance(p.get("tier"), bool)
               or int(p["tier"]) <= max_tier
        ]
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
                # v1.21.s144 — propagate pipeline_log for triage.
                "pipeline_log": ledger.get("pipeline_log", []),
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

    # v1.19.s132 — honor recipe.expected_min_assets.
    # Parse 'downloaded=N' patterns from each ledger.notes to sum.
    expected_min = recipe_meta.get("expected_min_assets")
    expected_status: dict | None = None
    if isinstance(expected_min, int) and not isinstance(expected_min, bool) and expected_min >= 0:
        import re as _re
        _DL_PAT = _re.compile(r"downloaded=(\d+)")
        total_downloaded = 0
        for r in results:
            notes = str(r.get("notes", "") or r.get("source_dir", ""))
            for match in _DL_PAT.finditer(notes):
                total_downloaded += int(match.group(1))
        meets = total_downloaded >= expected_min
        expected_status = {
            "expected_min_assets": expected_min,
            "total_downloaded_seen": total_downloaded,
            "meets_expected_min": meets,
        }

    # v1.20.s141 — honor recipe.min_required_passes.
    completed_count = sum(1 for r in results if r["status"] == "completed")
    min_passes = recipe_meta.get("min_required_passes")
    min_passes_status: dict | None = None
    if isinstance(min_passes, int) and not isinstance(min_passes, bool) and min_passes >= 0:
        min_passes_status = {
            "min_required_passes": min_passes,
            "completed_seen": completed_count,
            "meets_min_passes": completed_count >= min_passes,
        }

    if json_out:
        payload = {
            "recipe_id": recipe_meta.get("id"),
            "game": game_scope,
            "total_packs": len(packs),
            "completed": completed_count,
            "failed": fail_count,
            "required_failed": required_fail,
            "block_on_missing_required": block_on_missing,
            "results": results,
        }
        if expected_status is not None:
            payload["expected_min_check"] = expected_status
        if min_passes_status is not None:
            payload["min_required_passes_check"] = min_passes_status
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print()
        print(f"pack_from_recipe_total={len(packs)}")
        print(f"pack_from_recipe_completed={completed_count}")
        print(f"pack_from_recipe_failed={fail_count}")
        print(f"pack_from_recipe_required_failed={'true' if required_fail else 'false'}")
        if expected_status is not None:
            ok_label = "OK" if expected_status["meets_expected_min"] else "WARN"
            print(
                f"pack_from_recipe_expected_min_check=[{ok_label}] "
                f"downloaded={expected_status['total_downloaded_seen']} "
                f"expected_min={expected_status['expected_min_assets']}"
            )
        if min_passes_status is not None:
            ok2 = "OK" if min_passes_status["meets_min_passes"] else "WARN"
            print(
                f"pack_from_recipe_min_passes_check=[{ok2}] "
                f"completed={min_passes_status['completed_seen']} "
                f"min_required={min_passes_status['min_required_passes']}"
            )

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
    fix: Annotated[
        bool,
        typer.Option(
            "--fix",
            help=(
                "v1.9.s24: auto-apply fixes for common warnings (missing "
                "source_url, license, asset_kind). Requires --out."
            ),
        ),
    ] = False,
    out: Annotated[
        str,
        typer.Option(
            "--out",
            help="Output path for --fix mode. Required if --fix is set.",
        ),
    ] = "",
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

    # v1.9.s24: --fix path - apply auto-fixes and write to --out
    if fix:
        if not out:
            msg = "fix_requires_out: --fix needs --out <path> for the fixed recipe"
            if json_out:
                json.dump({"error": msg, "ok": False}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_validate_error={msg}")
            raise typer.Exit(code=1)
        from assetboy.workflows.recipe_validator import auto_fix_warnings
        try:
            doc = _load_recipe(resolved)
        except Exception as exc:
            msg = f"recipe_reload_for_fix_failed: {exc}"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_validate_error={msg}")
            raise typer.Exit(code=1)
        fixed_doc, fixes_applied = auto_fix_warnings(doc)
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml
            out_path.write_text(
                yaml.safe_dump(fixed_doc, sort_keys=False, allow_unicode=True, width=120),
                encoding="utf-8",
            )
        except ImportError:
            msg = "pyyaml_not_installed"
            print(f"pack_validate_error={msg}")
            raise typer.Exit(code=1)
        if json_out:
            json.dump({
                "ok": True,
                "fix_mode": True,
                "fixes_applied": fixes_applied,
                "fix_count": len(fixes_applied),
                "out_path": str(out_path),
                "out_bytes": out_path.stat().st_size,
            }, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_validate_fix_applied_count={len(fixes_applied)}")
            for idx, f in enumerate(fixes_applied, start=1):
                print(f"pack_validate_fix_{idx}={f}")
            print(f"pack_validate_fix_out_path={out_path}")
            print(f"pack_validate_fix_out_bytes={out_path.stat().st_size}")
        # Auto-fix mode exits 0 if fixed (operator should then re-validate)
        return

    exit_code = 0 if result.ok else 1
    if strict and result.warnings:
        exit_code = 1
    if exit_code:
        raise typer.Exit(code=exit_code)


# --------------------------------------------------------------------------- #
# pack validate-all (v1.8.s19)
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
    max_attempts: Annotated[
        int,
        typer.Option(
            "--max-attempts",
            help=(
                "v1.25.s168: cap how many packs to retry in one invocation"
                " (0 = unlimited, default). When set and there are more"
                " failed packs than this, only the first N are run; the"
                " rest are listed in 'deferred' in the summary."
            ),
        ),
    ] = 0,
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

    # v1.25.s168 — apply --max-attempts cap.
    deferred_ids: list[str] = []
    if max_attempts > 0 and len(targets) > max_attempts:
        deferred = targets[max_attempts:]
        targets = targets[:max_attempts]
        deferred_ids = [str(p.get("id", "?")) for p in deferred]

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

    # v1.21.s148 — honor recipe.expected_min_assets + min_required_passes
    # post-rerun. Same logic as from_recipe_cmd.
    recipe_meta = recipe_doc.get("recipe") or {}
    expected_status_r: dict | None = None
    min_passes_status_r: dict | None = None
    ema = recipe_meta.get("expected_min_assets")
    if isinstance(ema, int) and not isinstance(ema, bool) and ema >= 0:
        import re as _re
        _dlp = _re.compile(r"downloaded=(\d+)")
        td = 0
        for r in results:
            notes = str(r.get("notes", "") or r.get("source_dir", "")
                        or r.get("current_state", ""))
            for m in _dlp.finditer(notes):
                td += int(m.group(1))
        expected_status_r = {
            "expected_min_assets": ema,
            "total_downloaded_seen": td,
            "meets_expected_min": td >= ema,
        }
    mrp = recipe_meta.get("min_required_passes")
    if isinstance(mrp, int) and not isinstance(mrp, bool) and mrp >= 0:
        min_passes_status_r = {
            "min_required_passes": mrp,
            "completed_seen": re_success,
            "meets_min_passes": re_success >= mrp,
        }

    summary = {
        "ok": re_fail == 0,
        "recipe": str(resolved),
        "game_filter": effective_game_filter,
        "total_failed_in_audit": len(failed),
        "matched_in_recipe": len(targets) + len(deferred_ids),
        "skipped_not_in_recipe": skipped_not_in_recipe,
        "rerun_succeeded": re_success,
        "rerun_failed": re_fail,
        "max_attempts": max_attempts if max_attempts > 0 else None,
        "deferred": deferred_ids,
        "results": results,
    }
    if expected_status_r is not None:
        summary["expected_min_check"] = expected_status_r
    if min_passes_status_r is not None:
        summary["min_required_passes_check"] = min_passes_status_r

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"pack_rerun_failed_total={len(targets)}")
        print(f"pack_rerun_failed_succeeded={re_success}")
        print(f"pack_rerun_failed_failed={re_fail}")
        if skipped_not_in_recipe:
            print(f"pack_rerun_failed_skipped_count={len(skipped_not_in_recipe)}")
        if deferred_ids:
            print(f"pack_rerun_failed_deferred_count={len(deferred_ids)}")
        if expected_status_r is not None:
            lbl = "OK" if expected_status_r["meets_expected_min"] else "WARN"
            print(
                f"pack_rerun_failed_expected_min_check=[{lbl}] "
                f"downloaded={expected_status_r['total_downloaded_seen']} "
                f"expected_min={expected_status_r['expected_min_assets']}"
            )
        if min_passes_status_r is not None:
            lbl = "OK" if min_passes_status_r["meets_min_passes"] else "WARN"
            print(
                f"pack_rerun_failed_min_passes_check=[{lbl}] "
                f"completed={min_passes_status_r['completed_seen']} "
                f"min_required={min_passes_status_r['min_required_passes']}"
            )

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


# --------------------------------------------------------------------------- #
# pack manifest-stats  (v1.12.s72)
# --------------------------------------------------------------------------- #

@app.command("manifest-stats")
def manifest_stats_cmd(
    root_dir: Annotated[
        Path,
        typer.Option(
            "--root",
            help="Directory to scan for *_manifest.json files (default: manual_drop_dir).",
        ),
    ] = Path(""),
    source_filter: Annotated[
        str,
        typer.Option(
            "--source",
            help=(
                "v1.12.s77: filter to one source only (e.g. 'met_museum',"
                " 'wikimedia_commons', 'iconify'). Substring-match on the"
                " manifest 'source' field."
            ),
        ),
    ] = "",
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help=(
                "v1.13.s92: include only manifests with mtime newer than this"
                " ISO 8601 timestamp (e.g. '2026-05-01' or '2026-05-12T00:00:00')."
                " Useful to scope stats to 'this week' or 'today'."
            ),
        ),
    ] = "",
    since_days: Annotated[
        int,
        typer.Option(
            "--since-days",
            help=(
                "v1.33.s198: relative-time variant of --since;"
                " include manifests modified within the last N days."
                " 0 (default) = disabled. Mutex-friendly with --since"
                " (if both set, since-days takes priority)."
            ),
        ),
    ] = 0,
    history: Annotated[
        bool,
        typer.Option(
            "--history",
            help=(
                "v1.16.s116: instead of scanning disk manifests, aggregate"
                " state/r1a_history/*.json fan-out snapshots. Useful for"
                " 'how many scout runs across what providers over time'."
            ),
        ),
    ] = False,
    top: Annotated[
        int,
        typer.Option(
            "--top",
            help=(
                "v1.23.s159: show only the top N providers by total bytes"
                " (descending). 0 = show all (default)."
            ),
        ),
    ] = 0,
    min_bytes: Annotated[
        int,
        typer.Option(
            "--min-bytes",
            help=(
                "v1.25.s169: hide providers whose total bytes is below"
                " this threshold. 0 (default) shows all. Useful to ignore"
                " tiny manifests after a failed scout pass."
            ),
        ),
    ] = 0,
    csv_out: Annotated[
        Path,
        typer.Option(
            "--csv",
            help=(
                "v1.29.s186: write per-source rows as CSV to this path."
                " Mutually exclusive with --json. Header:"
                " source,manifests,downloaded,skipped,failed,bytes."
            ),
        ),
    ] = Path(""),
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Aggregate stats across all R1A manifests on disk (Path B v1.12.s72).

    Walks `<manual_drop>/<provider>/<pack_id>/<provider>_manifest.json` files
    written by R1A runners and reports:
      - per-provider download/skip/fail counts
      - total bytes (sum of `bytes` fields in manifest entries)
      - manifests scanned + by-source breakdown

    Useful for tracking how much R1A scouting has actually landed on disk.

    Examples:
      assetboy pack manifest-stats
      assetboy pack manifest-stats --root C:/some/other/path
      assetboy pack manifest-stats --json
    """
    from assetboy.execution.comfyui_runner import manual_drop_dir

    # v1.16.s116 — --history mode: aggregate state/r1a_history snapshots.
    if history:
        history_root = Path("state") / "r1a_history"
        if not history_root.exists():
            msg = f"history_root_not_found: {history_root}"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_manifest_stats_error={msg}")
            raise typer.Exit(code=1)

        # v1.18.s127 — parse --since for history mode too.
        since_epoch_h: float | None = None
        if since.strip():
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(since.strip())
                since_epoch_h = dt.timestamp()
            except ValueError as exc:
                msg = f"invalid_since_timestamp: {since!r} ({exc})"
                if json_out:
                    json.dump({"error": msg}, sys.stdout, indent=2)
                    sys.stdout.write("\n")
                else:
                    print(f"pack_manifest_stats_error={msg}")
                raise typer.Exit(code=1)

        hist_files = sorted(history_root.glob("*.json"))
        runs = 0
        kinds_count: dict[str, int] = {}
        per_provider: dict[str, dict] = {}
        total_wall_s = 0.0
        filtered_out = 0
        for hf in hist_files:
            # v1.18.s127 — mtime filter in history mode.
            if since_epoch_h is not None:
                try:
                    if hf.stat().st_mtime < since_epoch_h:
                        filtered_out += 1
                        continue
                except OSError:
                    filtered_out += 1
                    continue
            try:
                doc = json.loads(hf.read_text(encoding="utf-8"))
            except Exception:
                continue
            runs += 1
            kind = str(doc.get("kind", "unknown"))
            kinds_count[kind] = kinds_count.get(kind, 0) + 1
            ws = doc.get("wall_time_s")
            if isinstance(ws, (int, float)):
                total_wall_s += float(ws)
            for p in (doc.get("providers") or []):
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("provider", "unknown"))
                bucket = per_provider.setdefault(pid, {
                    "runs": 0, "ok_runs": 0,
                    "total_matched": 0, "total_downloaded": 0,
                })
                bucket["runs"] += 1
                if p.get("ok"):
                    bucket["ok_runs"] += 1
                bucket["total_matched"] += int(p.get("matched", 0) or 0)
                bucket["total_downloaded"] += int(p.get("downloaded", 0) or 0)

        summary = {
            "mode": "history",
            "history_root": str(history_root),
            "snapshots_scanned": len(hist_files),
            "snapshots_filtered_out": filtered_out,  # v1.18.s127
            "since_filter": since.strip() or None,   # v1.18.s127
            "runs_total": runs,
            "kinds": kinds_count,
            "total_wall_time_s": round(total_wall_s, 3),
            "by_provider": per_provider,
        }
        if json_out:
            json.dump(summary, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_manifest_stats_mode=history")
            print(f"pack_manifest_stats_snapshots_scanned={len(hist_files)}")
            print(f"pack_manifest_stats_runs_total={runs}")
            print(f"pack_manifest_stats_total_wall_time_s={total_wall_s:.2f}")
            print("Per-provider (across all snapshots):")
            for pid, b in sorted(per_provider.items()):
                print(
                    f"  {pid:14s} runs={b['runs']:3d} ok={b['ok_runs']:3d} "
                    f"matched={b['total_matched']:5d} dl={b['total_downloaded']:5d}"
                )
        return

    scan_root = root_dir if str(root_dir) else manual_drop_dir()
    if not scan_root.exists():
        msg = f"root_dir_not_found: {scan_root}"
        if json_out:
            json.dump({"error": msg, "root": str(scan_root)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_manifest_stats_error={msg}")
        raise typer.Exit(code=1)

    # Find every *_manifest.json under scan_root (any depth).
    manifests = sorted(scan_root.rglob("*_manifest.json"))

    per_source: dict[str, dict] = {}
    total_downloaded = 0
    total_failed = 0
    total_skipped = 0
    total_bytes = 0

    norm_filter = source_filter.strip().lower() if source_filter else ""

    # v1.13.s92 / v1.33.s198 — parse --since* into POSIX timestamp.
    since_epoch: float | None = None
    if since_days > 0:
        # v1.33.s198 — relative-time: now - N days.
        import time as _t
        since_epoch = _t.time() - (since_days * 86400.0)
    elif since.strip():
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(since.strip())
            since_epoch = dt.timestamp()
        except ValueError as exc:
            msg = f"invalid_since_timestamp: {since!r} ({exc})"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"pack_manifest_stats_error={msg}")
            raise typer.Exit(code=1)

    for mf in manifests:
        # v1.13.s92 — mtime filter.
        if since_epoch is not None:
            try:
                if mf.stat().st_mtime < since_epoch:
                    continue
            except OSError:
                continue
        try:
            doc = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        src = str(doc.get("source", "unknown"))
        # v1.12.s77 — source filter (substring, case-insensitive).
        if norm_filter and norm_filter not in src.lower():
            continue
        bucket = per_source.setdefault(src, {
            "manifests": 0,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "bytes": 0,
        })
        bucket["manifests"] += 1

        # Different runners use slightly different count fields; sum the ones we know.
        for k in ("objects_downloaded", "files_downloaded", "items_downloaded",
                  "cards_downloaded", "icons_downloaded", "tracks_downloaded",
                  "photos_downloaded", "games_downloaded"):
            v = doc.get(k)
            if isinstance(v, int):
                bucket["downloaded"] += v
                total_downloaded += v
        for k in ("objects_skipped_non_pd", "files_skipped_restricted",
                  "items_skipped_restricted", "icons_skipped_restricted",
                  "tracks_skipped_restricted"):
            v = doc.get(k)
            if isinstance(v, int):
                bucket["skipped"] += v
                total_skipped += v
        for k in ("objects_failed", "files_failed", "items_failed",
                  "cards_failed", "icons_failed", "tracks_failed",
                  "photos_failed", "games_failed"):
            v = doc.get(k)
            if isinstance(v, int):
                bucket["failed"] += v
                total_failed += v

        # Sum per-entry bytes if present.
        for entry in (doc.get("entries") or []):
            if isinstance(entry, dict):
                b = entry.get("bytes")
                if isinstance(b, int):
                    bucket["bytes"] += b
                    total_bytes += b

    # v1.23.s159 — --top N restricts by_source to N largest by bytes.
    per_source_view = per_source
    top_truncated = False
    if top > 0 and len(per_source) > top:
        ranked = sorted(per_source.items(),
                        key=lambda kv: kv[1].get("bytes", 0), reverse=True)
        per_source_view = dict(ranked[:top])
        top_truncated = True

    # v1.25.s169 — --min-bytes hides providers below the threshold.
    min_bytes_filtered = 0
    if min_bytes > 0:
        before_n = len(per_source_view)
        per_source_view = {
            src: b for src, b in per_source_view.items()
            if int(b.get("bytes", 0) or 0) >= min_bytes
        }
        min_bytes_filtered = before_n - len(per_source_view)

    summary = {
        "root": str(scan_root),
        "manifests_scanned": len(manifests),
        "manifests_after_filter": sum(b["manifests"] for b in per_source.values()),
        "source_filter": norm_filter or None,
        "since_filter": since.strip() or None,  # v1.13.s92
        "since_days_filter": since_days if since_days > 0 else None,  # v1.33.s198
        "sources_seen": len(per_source),
        "total_downloaded": total_downloaded,
        "total_skipped": total_skipped,
        "total_failed": total_failed,
        "total_bytes": total_bytes,
        "top_filter": top if top > 0 else None,
        "top_truncated": top_truncated,
        "min_bytes_filter": min_bytes if min_bytes > 0 else None,
        "min_bytes_filtered_count": min_bytes_filtered,
        "by_source": per_source_view,
    }

    # v1.29.s186 — CSV preempts JSON / text (mutually exclusive).
    csv_str = str(csv_out)
    if csv_str and csv_str != ".":
        import csv as _csv
        out_path = Path(csv_str)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["source", "manifests", "downloaded",
                        "skipped", "failed", "bytes"])
            for src, b in sorted(per_source_view.items()):
                w.writerow([
                    src,
                    int(b.get("manifests", 0)),
                    int(b.get("downloaded", 0)),
                    int(b.get("skipped", 0)),
                    int(b.get("failed", 0)),
                    int(b.get("bytes", 0)),
                ])
        if json_out:
            # Also emit JSON path note for tooling.
            json.dump(
                {"csv_path": str(out_path), "rows": len(per_source_view)},
                sys.stdout, indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(f"pack_manifest_stats_csv_path={out_path}")
            print(f"pack_manifest_stats_csv_rows={len(per_source_view)}")
        return

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"pack_manifest_stats_root={scan_root}")
        print(f"pack_manifest_stats_manifests_scanned={len(manifests)}")
        print(f"pack_manifest_stats_sources_seen={len(per_source)}")
        print(f"pack_manifest_stats_total_downloaded={total_downloaded}")
        print(f"pack_manifest_stats_total_skipped={total_skipped}")
        print(f"pack_manifest_stats_total_failed={total_failed}")
        print(f"pack_manifest_stats_total_bytes={total_bytes}")
        if top_truncated:
            print(f"pack_manifest_stats_top_filter={top}")
        if per_source_view:
            print()
            # When --top is set, sort by bytes desc; else alpha.
            iter_items = (
                sorted(per_source_view.items(),
                       key=lambda kv: kv[1].get("bytes", 0), reverse=True)
                if top > 0
                else sorted(per_source_view.items())
            )
            for src, b in iter_items:
                print(
                    f"  {src:24s} manifests={b['manifests']:3d}  "
                    f"downloaded={b['downloaded']:5d}  "
                    f"skipped={b['skipped']:4d}  "
                    f"failed={b['failed']:3d}  bytes={b['bytes']:>12d}"
                )


if __name__ == "__main__":
    app()
