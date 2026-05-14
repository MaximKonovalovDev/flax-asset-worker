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
from html import escape as html_escape  # v1.41.s234: HTML report rendering
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
    since_days: Annotated[
        int,
        typer.Option(
            "--since-days",
            help=(
                "v1.41.s232: keep only recipes whose updated_utc is within"
                " the last N days. 0 (default) disables. Recipes without"
                " updated_utc are dropped when this filter is active."
            ),
        ),
    ] = 0,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            help=(
                "v1.53.s270: cap output to top N recipes (after filter+"
                "sort+reverse). 0 (default) = no cap."
            ),
        ),
    ] = 0,
    csv_out: Annotated[
        Path,
        typer.Option(
            "--csv",
            help=(
                "v1.55.s275: export recipe catalog as CSV (header:"
                " path,game,recipe_id,pack_count,min_tier). Mutex with --json."
            ),
        ),
    ] = Path(""),
    graph_out: Annotated[
        bool,
        typer.Option(
            "--graph",
            help=(
                "v1.59.s283: emit cross-recipe relation graph (built from"
                " recipe.related_recipes fields) as JSON. Includes"
                " out_edges, in_edges, dangling refs, orphans, is_acyclic,"
                " topo_order. Preempts --json/--csv/text."
            ),
        ),
    ] = False,
    plan_out: Annotated[
        bool,
        typer.Option(
            "--plan",
            help=(
                "v1.64.s293: emit pipeline execution plan honoring topo"
                " order (per recipe: id, depth, pack_count, depends_on)."
                " Cycle -> exit 1 with error. Preempts --json/--csv/text."
            ),
        ),
    ] = False,
    plan_batches: Annotated[
        bool,
        typer.Option(
            "--batches",
            help=(
                "v1.64.s294: with --plan, emit batches (lists of"
                " parallel-executable recipe ids per depth level)."
            ),
        ),
    ] = False,
    mermaid_out: Annotated[
        Path,
        typer.Option(
            "--mermaid",
            help=(
                "v1.65.s295: with --graph, write Mermaid graph syntax"
                " to <path>. Solid arrows for edges, dashed (-.->)"
                " for dangling refs, standalone nodes for orphans."
            ),
        ),
    ] = Path(""),
    graph_stats: Annotated[
        bool,
        typer.Option(
            "--stats",
            help=(
                "v1.65.s296: with --graph, emit stats-only summary"
                " (no edge maps). Includes density, mean degrees,"
                " entry/leaf/orphan counts, is_acyclic, max_depth."
            ),
        ),
    ] = False,
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.60.s285: when used with --graph, render the graph as"
                " standalone HTML (edges table, orphans, dangling refs,"
                " topo order, cycle badge). No effect without --graph."
            ),
        ),
    ] = Path(""),
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

    # v1.59.s283 / s284 — pre-build cross-recipe graph if any graph-dependent
    # filter is in play, or if --graph output mode is requested.
    _graph = None
    _graph_filter_keys = {"is-orphan", "is_orphan", "has-dangling",
                          "has_dangling",
                          # v1.59.s284 — transitive closure filters.
                          "descendants-of", "descendants_of",
                          "ancestors-of", "ancestors_of",
                          # v1.61.s287 — entry-point + depth filters.
                          "is-entry-point", "is_entry_point",
                          "depth-from", "depth_from",
                          # v1.61.s288 — leaf filter.
                          "is-leaf", "is_leaf",
                          # v1.62.s290 — path filter.
                          "on-path", "on_path"}
    # v1.62.s289 — graph-aware sort keys also trigger graph build.
    _graph_sort_keys = {"topo", "depth", "in_degree", "out_degree"}
    _sort_needs_graph = sort.strip().lower() in _graph_sort_keys
    # v1.64.s293 — --plan triggers graph build too.
    _needs_graph = (
        graph_out
        or plan_out
        or _sort_needs_graph
        or any(fn in _graph_filter_keys for fn, _ in parsed_filters)
    )
    if _needs_graph:
        from assetboy.workflows.recipe_graph import build_graph
        _graph = build_graph(recipes_root)

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
        # v1.45.s250 — max-cost-minutes:N -> recipe.cost_minutes <= N
        # (recipes without cost_minutes do NOT match — opt-in budgeting).
        if field_name in ("max-cost-minutes", "max_cost_minutes"):
            try:
                budget = int(value)
            except ValueError:
                return False
            recipe_d = doc.get("recipe") or {}
            cm = recipe_d.get("cost_minutes")
            if not isinstance(cm, int) or isinstance(cm, bool):
                return False
            return cm <= budget
        # v1.46.s251 — min-cost-minutes:N -> recipe.cost_minutes >= N
        # (inverse of max-cost; recipes without cost_minutes do NOT match).
        if field_name in ("min-cost-minutes", "min_cost_minutes"):
            try:
                floor = int(value)
            except ValueError:
                return False
            recipe_d = doc.get("recipe") or {}
            cm = recipe_d.get("cost_minutes")
            if not isinstance(cm, int) or isinstance(cm, bool):
                return False
            return cm >= floor
        # v1.58.s281 — related-recipe:<id> -> recipe.related_recipes
        # contains <id> (exact-match within list, case-insensitive).
        if field_name in ("related-recipe", "related_recipe"):
            recipe_d = doc.get("recipe") or {}
            rr = recipe_d.get("related_recipes")
            if not isinstance(rr, list):
                return False
            target = value.strip().lower()
            return any(
                isinstance(x, str) and x.strip().lower() == target
                for x in rr
            )
        # v1.58.s281 — related-count:N -> recipe has >=N related entries.
        if field_name in ("related-count", "related_count"):
            try:
                threshold = int(value)
            except ValueError:
                return False
            recipe_d = doc.get("recipe") or {}
            rr = recipe_d.get("related_recipes")
            if not isinstance(rr, list):
                return False
            count = len(
                [x for x in rr if isinstance(x, str) and x.strip()]
            )
            return count >= threshold
        # v1.59.s283 — is-orphan / has-dangling read from the pre-built
        # _graph; require _needs_graph to have triggered graph build.
        if field_name in ("is-orphan", "is_orphan"):
            wanted = value.strip().lower() in ("true", "yes", "1")
            if _graph is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return not wanted
            is_orph = rid in _graph.orphans
            return is_orph is wanted
        if field_name in ("has-dangling", "has_dangling"):
            wanted = value.strip().lower() in ("true", "yes", "1")
            if _graph is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return not wanted
            has_dangle = bool(_graph.dangling.get(rid))
            return has_dangle is wanted
        # v1.59.s284 — descendants-of:<id> matches recipes reachable from <id>.
        if field_name in ("descendants-of", "descendants_of"):
            if _graph is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return False
            return rid in _graph.descendants(value.strip())
        # v1.59.s284 — ancestors-of:<id> matches recipes that reach <id>.
        if field_name in ("ancestors-of", "ancestors_of"):
            if _graph is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return False
            return rid in _graph.ancestors(value.strip())
        # v1.61.s287 — is-entry-point:bool matches roots that reference
        # other recipes but nothing references them.
        if field_name in ("is-entry-point", "is_entry_point"):
            wanted = value.strip().lower() in ("true", "yes", "1")
            if _graph is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return not wanted
            is_ep = rid in _graph.entry_points()
            return is_ep is wanted
        # v1.62.s290 — on-path:<src>:<dst> matches recipes on the BFS
        # shortest path from <src> to <dst> (inclusive of endpoints).
        if field_name in ("on-path", "on_path"):
            if _graph is None or ":" not in value:
                return False
            src_id, _, dst_id = value.rpartition(":")
            src_id = src_id.strip()
            dst_id = dst_id.strip()
            if not src_id or not dst_id:
                return False
            path = _graph.path_between(src_id, dst_id)
            if path is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return False
            return rid in path
        # v1.61.s288 — is-leaf:bool matches terminal nodes with incoming
        # edges but no outgoing (or dangling) edges.
        if field_name in ("is-leaf", "is_leaf"):
            wanted = value.strip().lower() in ("true", "yes", "1")
            if _graph is None:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return not wanted
            is_leaf = rid in _graph.leaves()
            return is_leaf is wanted
        # v1.61.s287 — depth-from:<root>:<max-depth> matches recipes whose
        # BFS distance from <root> is <= <max-depth>.
        if field_name in ("depth-from", "depth_from"):
            if _graph is None:
                return False
            # Value shape: "<root_id>:<max_depth>" (use rsplit because root_id
            # could contain : in unusual cases — but recipe ids are usually clean).
            if ":" not in value:
                return False
            root_id, _, max_depth_str = value.rpartition(":")
            try:
                max_depth = int(max_depth_str)
            except ValueError:
                return False
            recipe_d = doc.get("recipe") or {}
            rid = recipe_d.get("id")
            if not isinstance(rid, str):
                return False
            depths = _graph.depth_from(root_id.strip())
            return rid in depths and depths[rid] <= max_depth
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
                # v1.23.s160 / v1.25.s172 / v1.30.s189 / v1.38.s210 /
                # v1.41.s233 / v1.45.s247 / v1.56.s277 / v1.58.s281: misc metadata.
                for meta_key in ("genre", "theme", "style", "tags",
                                  "created_utc", "updated_utc",
                                  "author", "contact", "platform",
                                  "cost_minutes", "engine_version",
                                  "expected_max_assets", "notes",
                                  "related_recipes"):
                    if meta_key in recipe:
                        entry_data[meta_key] = recipe[meta_key]
                # v1.58.s281 — derived related_count from related_recipes list.
                _rr = recipe.get("related_recipes")
                if isinstance(_rr, list):
                    entry_data["related_count"] = len(
                        [x for x in _rr if isinstance(x, str) and x.strip()]
                    )
                else:
                    entry_data["related_count"] = 0
                # v1.40.s230 — last_run_utc derived from pack-pipeline ledger
                # mtimes (most recent across all packs in this recipe).
                try:
                    from assetboy.workflows.pack_pipeline import (
                        _pipeline_state_path as _pipe_path,
                    )
                    game_scope = str(recipe.get("game", game_dir.name))
                    max_mtime = 0.0
                    for pack in (doc.get("packs") or []):
                        if not isinstance(pack, dict):
                            continue
                        pid_p = str(pack.get("id", "") or "")
                        if not pid_p:
                            continue
                        try:
                            led_path = _pipe_path(game_scope, pid_p)
                            if led_path.exists():
                                m = led_path.stat().st_mtime
                                if m > max_mtime:
                                    max_mtime = m
                        except Exception:
                            pass
                    if max_mtime > 0:
                        from datetime import datetime as _dt, timezone as _tz
                        entry_data["last_run_utc"] = (
                            _dt.fromtimestamp(max_mtime, tz=_tz.utc)
                            .isoformat(timespec="seconds")
                        )
                except Exception:
                    # If anything fails, silently omit the field; non-critical.
                    pass
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
    elif sort_norm == "author":
        # v1.57.s279 — alphabetical by author; untagged sort last.
        entries.sort(key=lambda e: (
            e.get("author") is None
            or not str(e.get("author") or "").strip(),
            str(e.get("author", "")).lower(),
            e["path"],
        ))
    elif sort_norm == "related_count":
        # v1.58.s281 — most-connected first (DESC); zero/missing sort last.
        entries.sort(key=lambda e: (
            -int(e.get("related_count", 0) or 0),
            e["path"],
        ))
    elif sort_norm == "topo":
        # v1.62.s289 — order by topological_sort() position; entries not
        # in graph (e.g. unparseable recipes) and cycles sort last.
        if _graph is None:
            # Defensive — _needs_graph should have triggered build.
            from assetboy.workflows.recipe_graph import build_graph
            _graph = build_graph(recipes_root)
        _topo = _graph.topological_sort() or []
        _topo_pos = {rid: i for i, rid in enumerate(_topo)}
        entries.sort(key=lambda e: (
            e.get("recipe_id") not in _topo_pos,
            _topo_pos.get(e.get("recipe_id"), 10_000_000),
            e["path"],
        ))
    elif sort_norm == "depth":
        # v1.62.s289 — order by max-depth-from-any-root; deeper = later.
        # DAGs only — cycle case falls through to "depth=infinity" for all.
        if _graph is None:
            from assetboy.workflows.recipe_graph import build_graph
            _graph = build_graph(recipes_root)
        # Compute per-recipe max depth from any entry_point.
        _per_recipe_depth: dict[str, int] = {}
        if _graph.is_acyclic():
            for entry in _graph.entry_points():
                for rid, d in _graph.depth_from(entry).items():
                    cur = _per_recipe_depth.get(rid, -1)
                    if d > cur:
                        _per_recipe_depth[rid] = d
            # Recipes not reachable from any entry_point (e.g. orphans).
            for rid in _graph.all_ids - _per_recipe_depth.keys():
                _per_recipe_depth[rid] = 0
        entries.sort(key=lambda e: (
            e.get("recipe_id") not in _per_recipe_depth,
            _per_recipe_depth.get(e.get("recipe_id"), 0),
            e["path"],
        ))
    elif sort_norm == "in_degree":
        # v1.62.s289 — least incoming edges first (roots first).
        if _graph is None:
            from assetboy.workflows.recipe_graph import build_graph
            _graph = build_graph(recipes_root)
        entries.sort(key=lambda e: (
            e.get("recipe_id") not in _graph.all_ids,
            len(_graph.in_edges.get(e.get("recipe_id"), set())),
            e["path"],
        ))
    elif sort_norm == "out_degree":
        # v1.62.s289 — least outgoing edges first (leaves first).
        if _graph is None:
            from assetboy.workflows.recipe_graph import build_graph
            _graph = build_graph(recipes_root)
        entries.sort(key=lambda e: (
            e.get("recipe_id") not in _graph.all_ids,
            len(_graph.out_edges.get(e.get("recipe_id"), set())),
            e["path"],
        ))
    elif sort_norm in ("updated_utc", "created_utc", "last_run_utc"):
        # v1.32.s195 / v1.40.s231 — sort by timestamp field (newest first);
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
    elif sort_norm == "cost_minutes":
        # v1.38.s211 — cheapest first; entries without cost_minutes
        # or with non-int values sort last.
        def _cost(e: dict) -> int:
            v = e.get("cost_minutes")
            if isinstance(v, int) and not isinstance(v, bool):
                return v
            return -1  # used in tuple below
        entries.sort(key=lambda e: (
            e.get("cost_minutes") is None
            or not isinstance(e.get("cost_minutes"), int)
            or isinstance(e.get("cost_minutes"), bool),
            _cost(e),
            e["path"],
        ))
    elif sort_norm not in ("", "path"):
        # Unknown sort key -> error.
        msg = (
            f"unknown_sort_key: {sort_norm!r}"
            " (valid: 'path', 'tier', 'name', 'platform',"
            " 'updated_utc', 'created_utc', 'last_run_utc',"
            " 'cost_minutes', 'author', 'related_count',"
            " 'topo', 'depth', 'in_degree', 'out_degree')"
        )
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"pack_list_recipes_error={msg}")
        raise typer.Exit(code=1)

    # v1.41.s232 — --since-days filter (recipes updated within last N days).
    if since_days > 0:
        import time as _t
        from datetime import datetime as _dt2
        cutoff = _t.time() - (since_days * 86400.0)
        def _is_recent(e: dict) -> bool:
            uv = e.get("updated_utc")
            if not isinstance(uv, str):
                return False
            try:
                return _dt2.fromisoformat(uv.strip()).timestamp() >= cutoff
            except (ValueError, TypeError):
                return False
        entries = [e for e in entries if _is_recent(e)]

    # v1.17.s121 — reverse after sort.
    if reverse:
        entries.reverse()

    # v1.53.s270 — --limit caps output after filter+sort+reverse.
    if limit > 0 and len(entries) > limit:
        entries = entries[:limit]

    # v1.64.s293 — --plan emits pipeline execution plan (topo order +
    # per-recipe depth + dependency list). Preempts --graph/--csv/JSON/text.
    # Cycle -> exit 1. Filters apply (entries already trimmed).
    if plan_out:
        if _graph is None:
            from assetboy.workflows.recipe_graph import build_graph
            _graph = build_graph(recipes_root)
        topo = _graph.topological_sort()
        if topo is None:
            msg = "pipeline_plan_failed: cycle detected; topological sort impossible"
            if json_out:
                json.dump({"ok": False, "error": msg},
                          sys.stdout, indent=None if compact else 2)
                sys.stdout.write("\n")
            else:
                print(f"pack_list_recipes_plan_error={msg}")
            raise typer.Exit(code=1)
        # Compute per-recipe depth (max from any entry point).
        per_depth: dict[str, int] = {}
        for entry in _graph.entry_points():
            for rid, d in _graph.depth_from(entry).items():
                if d > per_depth.get(rid, -1):
                    per_depth[rid] = d
        for rid in _graph.all_ids - per_depth.keys():
            per_depth[rid] = 0
        # Build plan entries: filter to those present in `entries` set
        # (so --filter applies), keep topo order.
        present_ids = {e.get("recipe_id"): e for e in entries}
        plan: list[dict] = []
        for rid in topo:
            if rid not in present_ids:
                continue
            e = present_ids[rid]
            plan.append({
                "step": len(plan) + 1,
                "recipe_id": rid,
                "depth": per_depth.get(rid, 0),
                "pack_count": int(e.get("pack_count", 0) or 0),
                "depends_on": sorted(_graph.in_edges.get(rid, set())),
                "game": e.get("game", ""),
            })
        # v1.64.s294 — --batches mode: emit parallel-execution groups.
        if plan_batches:
            raw_batches = _graph.parallel_batches() or []
            # Filter each batch to present_ids (respects --filter).
            filtered: list[list[str]] = []
            for batch in raw_batches:
                kept = [rid for rid in batch if rid in present_ids]
                if kept:
                    filtered.append(kept)
            if json_out:
                json.dump(
                    {
                        "ok": True,
                        "batches": filtered,
                        "total_batches": len(filtered),
                        "total_recipes": sum(len(b) for b in filtered),
                    },
                    sys.stdout,
                    indent=None if compact else 2,
                )
                sys.stdout.write("\n")
            else:
                print(f"pack_list_recipes_plan_batches_total={len(filtered)}")
                for i, batch in enumerate(filtered, 1):
                    print(f"  batch {i:2d} ({len(batch)} parallel): "
                          f"{', '.join(batch)}")
            return
        # CSV emit when path provided.
        plan_csv_str = str(csv_out) if "csv_out" in locals() else ""
        if plan_csv_str and plan_csv_str != ".":
            import csv as _csv
            plan_csv_path = Path(plan_csv_str)
            try:
                plan_csv_path.parent.mkdir(parents=True, exist_ok=True)
                with plan_csv_path.open("w", encoding="utf-8", newline="") as fh:
                    w = _csv.writer(fh)
                    w.writerow([
                        "step", "recipe_id", "depth", "pack_count",
                        "depends_on", "game",
                    ])
                    for p in plan:
                        w.writerow([
                            p["step"], p["recipe_id"], p["depth"],
                            p["pack_count"],
                            ";".join(p["depends_on"]),
                            p["game"],
                        ])
            except Exception as exc:
                print(f"pack_list_recipes_plan_error=csv_write_failed: {exc}")
                raise typer.Exit(code=1)
            print(f"pack_list_recipes_plan_csv_path={plan_csv_path}")
            print(f"pack_list_recipes_plan_csv_rows={len(plan)}")
            return
        # JSON emit.
        if json_out:
            json.dump(
                {"ok": True, "plan": plan, "total_steps": len(plan)},
                sys.stdout, indent=None if compact else 2,
            )
            sys.stdout.write("\n")
        else:
            print(f"pack_list_recipes_plan_total={len(plan)}")
            for p in plan:
                deps = ",".join(p["depends_on"]) if p["depends_on"] else "-"
                print(
                    f"  step={p['step']:2d}  depth={p['depth']:2d}"
                    f"  packs={p['pack_count']:3d}"
                    f"  recipe={p['recipe_id']}  depends_on={deps}"
                )
        return

    # v1.59.s283 — --graph emits cross-recipe adjacency map as JSON.
    # v1.60.s285 — when --graph combined with --html, render HTML report.
    # Preempts --csv / --json / text. Uses pre-built _graph (built once
    # at parse time, before per-recipe scan). Always emits even if
    # entries filtered away (graph is a global view of the catalog).
    if graph_out:
        if _graph is None:
            # Should not happen — _needs_graph triggered build — but
            # defensively rebuild if absent (e.g. operator passed --graph
            # alone without any graph-using filter).
            from assetboy.workflows.recipe_graph import build_graph
            _graph = build_graph(recipes_root)
        gdict = _graph.to_dict()
        # v1.60.s286 — CSV companion when --csv path provided.
        csv_path_str = str(csv_out) if "csv_out" in locals() else ""
        if csv_path_str and csv_path_str != ".":
            import csv as _csv
            csv_p = Path(csv_path_str)
            try:
                csv_p.parent.mkdir(parents=True, exist_ok=True)
                with csv_p.open("w", encoding="utf-8", newline="") as fh:
                    w = _csv.writer(fh)
                    w.writerow(["kind", "from_id", "to_id"])
                    # Edges first (sorted for determinism).
                    for src in sorted(_graph.all_ids):
                        for tgt in sorted(_graph.out_edges.get(src, set())):
                            w.writerow(["edge", src, tgt])
                    # Dangling refs (prefix-marked).
                    for src in sorted(_graph.dangling.keys()):
                        for tgt in sorted(_graph.dangling[src]):
                            w.writerow(["dangling", src, tgt])
                    # Orphan rows.
                    for o in sorted(_graph.orphans):
                        w.writerow(["orphan", o, ""])
            except Exception as exc:
                print(f"pack_list_recipes_error=graph_csv_write_failed: {exc}")
                raise typer.Exit(code=1)
            row_count = (
                gdict["total_edges"]
                + gdict["dangling_count"]
                + gdict["orphan_count"]
            )
            print(f"pack_list_recipes_graph_csv_path={csv_p}")
            print(f"pack_list_recipes_graph_csv_rows={row_count}")
            return
        # v1.65.s295 — Mermaid emit when --mermaid path provided.
        mermaid_str = str(mermaid_out) if "mermaid_out" in locals() else ""
        if mermaid_str and mermaid_str != ".":
            mermaid_path = Path(mermaid_str)
            try:
                mermaid_path.parent.mkdir(parents=True, exist_ok=True)
                mermaid_path.write_text(
                    _graph.to_mermaid(), encoding="utf-8",
                )
            except Exception as exc:
                print(f"pack_list_recipes_error=mermaid_write_failed: {exc}")
                raise typer.Exit(code=1)
            print(f"pack_list_recipes_graph_mermaid_path={mermaid_path}")
            return
        # v1.60.s285 — HTML companion when --html path provided.
        html_str = str(html_out) if "html_out" in locals() else ""
        if html_str and html_str != ".":
            html_path = Path(html_str)
            try:
                html_path.parent.mkdir(parents=True, exist_ok=True)
                # Build edge rows + orphan/dangling lists.
                edge_rows: list[str] = []
                for src in sorted(_graph.all_ids):
                    targets = sorted(_graph.out_edges.get(src, set()))
                    if not targets:
                        continue
                    edge_rows.append(
                        f"<tr><td><code>{html_escape(src)}</code></td>"
                        f"<td>{html_escape(', '.join(targets))}</td></tr>"
                    )
                orphan_html = ", ".join(
                    f"<code>{html_escape(o)}</code>"
                    for o in sorted(_graph.orphans)
                ) or "<em>none</em>"
                dangling_rows: list[str] = []
                for src, missing in sorted(_graph.dangling.items()):
                    missing_html = ", ".join(
                        f"<code>{html_escape(m)}</code>" for m in sorted(missing)
                    )
                    dangling_rows.append(
                        f"<tr><td><code>{html_escape(src)}</code></td>"
                        f"<td>{missing_html}</td></tr>"
                    )
                topo_html = (
                    ", ".join(
                        f"<code>{html_escape(t)}</code>"
                        for t in (gdict.get("topo_order") or [])
                    )
                    if gdict.get("is_acyclic")
                    else "<em class='b-red-text'>cycle detected — no topo order</em>"
                )
                acyclic_badge = (
                    "<span class='b-green'>acyclic</span>"
                    if gdict["is_acyclic"]
                    else "<span class='b-red'>cyclic</span>"
                )
                html = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>FAW Recipe Graph</title>"
                    "<style>"
                    "body{font-family:system-ui,sans-serif;max-width:1100px;"
                    "margin:2em auto;}"
                    "h1{margin-bottom:.2em}h2{margin-top:1.5em}"
                    ".summary{color:#666;margin-bottom:1em}"
                    "table{border-collapse:collapse;width:100%}"
                    "th,td{padding:.4em .6em;border-bottom:1px solid #eee;"
                    "text-align:left;vertical-align:top}"
                    "code{background:#f5f5f5;padding:1px 4px;border-radius:2px;"
                    "font-size:.9em}"
                    ".b-green,.b-red{color:#fff;padding:2px 8px;"
                    "border-radius:3px;font-size:.8em}"
                    ".b-green{background:#2e7d32}"
                    ".b-red{background:#c62828}"
                    ".b-red-text{color:#c62828}"
                    "</style></head><body>"
                    "<h1>FAW Recipe Graph</h1>"
                    "<p class='summary'>"
                    f"Total recipes: {gdict['total_recipes']} &middot; "
                    f"Edges: {gdict['total_edges']} &middot; "
                    f"Dangling: {gdict['dangling_count']} &middot; "
                    f"Orphans: {gdict['orphan_count']} &middot; "
                    f"Status: {acyclic_badge}"
                    "</p>"
                    f"<h2>Topological order</h2><p>{topo_html}</p>"
                    f"<h2>Edges ({gdict['total_edges']})</h2>"
                    "<table><thead><tr><th>From</th><th>To</th></tr></thead>"
                    f"<tbody>{''.join(edge_rows) or '<tr><td colspan=2><em>none</em></td></tr>'}</tbody></table>"
                    f"<h2>Orphans ({gdict['orphan_count']})</h2><p>{orphan_html}</p>"
                    f"<h2>Dangling references ({gdict['dangling_count']})</h2>"
                    + (
                        "<table><thead><tr><th>From</th><th>Missing targets</th>"
                        "</tr></thead><tbody>"
                        + "".join(dangling_rows)
                        + "</tbody></table>"
                        if dangling_rows else "<p><em>none</em></p>"
                    )
                    + "</body></html>"
                )
                html_path.write_text(html, encoding="utf-8")
            except Exception as exc:
                print(f"pack_list_recipes_error=html_write_failed: {exc}")
                raise typer.Exit(code=1)
            print(f"pack_list_recipes_graph_html_path={html_path}")
            return

        # v1.65.s296 — --stats emits compact summary (no edge maps).
        if graph_stats:
            json.dump(
                _graph.stats(),
                sys.stdout,
                indent=None if compact else 2,
            )
            sys.stdout.write("\n")
            return

        json.dump(gdict, sys.stdout, indent=None if compact else 2)
        sys.stdout.write("\n")
        return

    # v1.55.s275 — --csv preempts JSON/text.
    csv_str = str(csv_out)
    if csv_str and csv_str != ".":
        import csv as _csv
        csv_path = Path(csv_str)
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh)
                # v1.55.s276 — extended CSV columns include the operator-
                # useful metadata fields (cost_minutes, engine_version,
                # platform, author). Empty cells when fields absent.
                w.writerow([
                    "path", "game", "recipe_id", "pack_count", "min_tier",
                    "cost_minutes", "engine_version", "platform", "author",
                    "notes", "related_count",
                ])
                for e in entries:
                    # v1.56.s277 — notes truncated to 80 chars + newline-
                    # stripped for CSV one-line-per-row safety.
                    raw_notes = str(e.get("notes", "") or "")
                    notes_csv = raw_notes.replace("\n", " ").replace("\r", " ")
                    if len(notes_csv) > 80:
                        notes_csv = notes_csv[:77] + "..."
                    w.writerow([
                        str(e.get("path", "")),
                        str(e.get("game", "")),
                        str(e.get("recipe_id", "")),
                        int(e.get("pack_count", 0) or 0),
                        e.get("min_tier", ""),
                        e.get("cost_minutes", ""),
                        str(e.get("engine_version", "") or ""),
                        str(e.get("platform", "") or ""),
                        str(e.get("author", "") or ""),
                        notes_csv,
                        int(e.get("related_count", 0) or 0),
                    ])
        except Exception as exc:
            print(f"pack_list_recipes_error=csv_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_list_recipes_csv_path={csv_path}")
        print(f"pack_list_recipes_csv_rows={len(entries)}")
        return

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
    provider_skip: Annotated[
        list[str],
        typer.Option(
            "--provider-skip",
            help=(
                "v1.39.s213: SKIP packs whose provider matches one of these"
                " ids (repeatable). Inverse of --provider-only; applied after."
                " Useful for 'run everything except X'."
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
    cost_budget_minutes: Annotated[
        int,
        typer.Option(
            "--cost-budget",
            help=(
                "v1.38.s212: refuse to run if recipe.cost_minutes exceeds"
                " this budget. 0 (default) = disabled. Recipes without"
                " cost_minutes are NOT blocked (operator opts-in to budget"
                " by setting the field)."
            ),
        ),
    ] = 0,
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.50.s257: write standalone HTML pack-execution report"
                " (per-pack status: completed/failed/pending_manual_drop +"
                " required flag + notes). Preempts JSON/text."
            ),
        ),
    ] = Path(""),
    csv_out: Annotated[
        Path,
        typer.Option(
            "--csv",
            help=(
                "v1.56.s278: write pack-execution results as CSV (header:"
                " pack_id,status,provider,required,notes_truncated)."
            ),
        ),
    ] = Path(""),
    open_html: Annotated[
        bool,
        typer.Option(
            "--open",
            help=(
                "v1.50.s257: with --html, auto-open in system browser."
            ),
        ),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help=(
                "v1.39.s215: single-line JSON output. No effect without --json."
            ),
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

    # v1.38.s212 — enforce --cost-budget (only when both flag and field are set).
    if cost_budget_minutes > 0:
        recipe_cost = recipe_meta.get("cost_minutes")
        if isinstance(recipe_cost, int) and not isinstance(recipe_cost, bool):
            if recipe_cost > cost_budget_minutes:
                msg = (
                    f"cost_budget_exceeded: recipe.cost_minutes={recipe_cost}"
                    f" > --cost-budget={cost_budget_minutes}"
                )
                if json_out:
                    json.dump({"ok": False, "error": msg},
                              sys.stdout, indent=2)
                    sys.stdout.write("\n")
                else:
                    print(f"pack_from_recipe_error={msg}")
                raise typer.Exit(code=1)

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
    # v1.39.s213 — --provider-skip negative filter.
    if provider_skip:
        ps_set = {p.strip().lower() for p in provider_skip if p.strip()}
        packs = [
            p for p in packs
            if str(p.get("provider", "")).strip().lower() not in ps_set
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
    expected_max = recipe_meta.get("expected_max_assets")  # v1.45.s248
    expected_status: dict | None = None
    has_min = (isinstance(expected_min, int)
               and not isinstance(expected_min, bool)
               and expected_min >= 0)
    has_max = (isinstance(expected_max, int)
               and not isinstance(expected_max, bool)
               and expected_max >= 0)
    if has_min or has_max:
        import re as _re
        _DL_PAT = _re.compile(r"downloaded=(\d+)")
        total_downloaded = 0
        for r in results:
            notes = str(r.get("notes", "") or r.get("source_dir", ""))
            for match in _DL_PAT.finditer(notes):
                total_downloaded += int(match.group(1))
        expected_status = {
            "total_downloaded_seen": total_downloaded,
        }
        if has_min:
            expected_status["expected_min_assets"] = expected_min
            expected_status["meets_expected_min"] = total_downloaded >= expected_min
        if has_max:
            # v1.45.s248 — within_expected_max true when seen <= max.
            expected_status["expected_max_assets"] = expected_max
            expected_status["within_expected_max"] = total_downloaded <= expected_max

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

    # v1.56.s278 — --csv preempts HTML/JSON/text.
    csv_str = str(csv_out)
    if csv_str and csv_str != ".":
        import csv as _csv
        csv_path = Path(csv_str)
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh)
                w.writerow(["pack_id", "status", "provider", "required",
                             "notes_truncated"])
                for r in results:
                    pid = str(r.get("pack_id", "?"))
                    notes = str(r.get("notes", "") or "")
                    notes_csv = notes.replace("\n", " ").replace("\r", " ")
                    if len(notes_csv) > 80:
                        notes_csv = notes_csv[:77] + "..."
                    w.writerow([
                        pid,
                        str(r.get("status", "?")),
                        str(r.get("provider", "?")),
                        "true" if pid in required_ids else "false",
                        notes_csv,
                    ])
        except Exception as exc:
            print(f"pack_from_recipe_error=csv_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_from_recipe_csv_path={csv_path}")
        print(f"pack_from_recipe_csv_rows={len(results)}")
        if required_fail and block_on_missing:
            raise typer.Exit(code=1)
        return

    # v1.50.s257 — HTML preempts JSON/text.
    html_str = str(html_out)
    if html_str and html_str != ".":
        html_path = Path(html_str)
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            rows_html: list[str] = []
            for r in results:
                status = r.get("status", "?")
                if status == "completed":
                    status_class = "b-green"
                elif status == "pending_manual_drop":
                    status_class = "b-yellow"
                else:
                    status_class = "b-red"
                pack_id = str(r.get("pack_id", "?"))
                is_required = pack_id in required_ids
                req_badge = (
                    "<span class='b-blue'>required</span>"
                    if is_required else ""
                )
                notes = str(r.get("notes", "") or "")
                # Truncate very long notes.
                if len(notes) > 200:
                    notes = notes[:200] + "..."
                rows_html.append(
                    "<tr>"
                    f"<td>{html_escape(pack_id)}</td>"
                    f"<td><span class='{status_class}'>{html_escape(status)}</span> {req_badge}</td>"
                    f"<td>{html_escape(str(r.get('provider','?')))}</td>"
                    f"<td>{html_escape(notes)}</td>"
                    "</tr>"
                )
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>FAW Pack Execution</title>"
                "<style>"
                "body{font-family:system-ui,sans-serif;max-width:1200px;margin:2em auto;}"
                "h1{margin-bottom:.2em}"
                ".summary{color:#666;margin-bottom:1em}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{padding:.4em .6em;border-bottom:1px solid #eee;text-align:left;vertical-align:top}"
                ".b-green,.b-yellow,.b-red,.b-blue{color:#fff;padding:2px 8px;"
                "border-radius:3px;font-size:.8em;margin-right:.3em}"
                ".b-green{background:#2e7d32}"
                ".b-yellow{background:#f9a825;color:#000}"
                ".b-red{background:#c62828}"
                ".b-blue{background:#1976d2}"
                "</style></head><body>"
                "<h1>FAW Pack Execution</h1>"
                "<p class='summary'>"
                f"Recipe: <code>{html_escape(str(recipe_meta.get('id','?')))}</code> &middot; "
                f"Game: <code>{html_escape(game_scope)}</code> &middot; "
                f"total packs: {len(packs)} &middot; "
                f"completed: {completed_count} &middot; "
                f"failed: {fail_count} &middot; "
                f"required failed: {required_fail}"
                "</p>"
                "<table>"
                "<thead><tr><th>Pack id</th><th>Status</th>"
                "<th>Provider</th><th>Notes</th>"
                "</tr></thead><tbody>"
                + "".join(rows_html)
                + "</tbody></table>"
                "</body></html>"
            )
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            print(f"pack_from_recipe_error=html_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_from_recipe_html_path={html_path}")
        if open_html:
            import platform
            import subprocess
            sys_name = platform.system().lower()
            try:
                if sys_name == "windows":
                    import os
                    os.startfile(str(html_path.resolve()))  # type: ignore[attr-defined]
                elif sys_name == "darwin":
                    subprocess.run(["open", str(html_path.resolve())], check=False)
                else:
                    subprocess.run(["xdg-open", str(html_path.resolve())], check=False)
                print("pack_from_recipe_html_opened=true")
            except Exception as exc:
                print(f"pack_from_recipe_html_open_failed={exc}")
        if required_fail and block_on_missing:
            raise typer.Exit(code=1)
        return

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
        # v1.39.s215 — --compact emits single-line JSON.
        json.dump(payload, sys.stdout, indent=None if compact else 2, default=str)
        sys.stdout.write("\n")
    else:
        print()
        print(f"pack_from_recipe_total={len(packs)}")
        print(f"pack_from_recipe_completed={completed_count}")
        print(f"pack_from_recipe_failed={fail_count}")
        print(f"pack_from_recipe_required_failed={'true' if required_fail else 'false'}")
        if expected_status is not None:
            seen = expected_status["total_downloaded_seen"]
            if "expected_min_assets" in expected_status:
                ok_label = "OK" if expected_status["meets_expected_min"] else "WARN"
                print(
                    f"pack_from_recipe_expected_min_check=[{ok_label}] "
                    f"downloaded={seen} "
                    f"expected_min={expected_status['expected_min_assets']}"
                )
            # v1.45.s248 — also surface max check when present.
            if "expected_max_assets" in expected_status:
                ok_label_max = (
                    "OK" if expected_status["within_expected_max"] else "WARN"
                )
                print(
                    f"pack_from_recipe_expected_max_check=[{ok_label_max}] "
                    f"downloaded={seen} "
                    f"expected_max={expected_status['expected_max_assets']}"
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
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.41.s234: write standalone HTML validation dashboard"
                " (per-recipe status + drilldown to errors/warnings)."
                " Preempts JSON/text."
            ),
        ),
    ] = Path(""),
    open_html: Annotated[
        bool,
        typer.Option(
            "--open",
            help=(
                "v1.41.s234: with --html, auto-open in system browser."
            ),
        ),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help=(
                "v1.39.s216: single-line JSON output. No effect without --json."
            ),
        ),
    ] = False,
    csv_out: Annotated[
        Path,
        typer.Option(
            "--csv",
            help=(
                "v1.56.s278: write validation results as CSV (header:"
                " path,status,error_count,warning_count)."
            ),
        ),
    ] = Path(""),
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

    # v1.65.s295 — graph-level checks: cycle / dangling refs surface as
    # warnings on individual recipes. Strict mode promotes to error.
    try:
        from assetboy.workflows.recipe_graph import build_graph
        _vg = build_graph(recipes_root)
        # Cycle: mark every recipe in any SCC; simpler — flag at top
        # level by recording a synthetic warning on the FIRST recipe
        # entry in topo order (or all if cycle).
        if not _vg.is_acyclic():
            cycle_msg = (
                "graph_cycle: recipe.related_recipes contains a cycle"
                " (no valid topological order)"
            )
            for entry in per_recipe:
                # Mark every recipe involved (defensive — cycle scope
                # is global since topo_sort failed).
                entry.setdefault("warnings", []).append(cycle_msg)
                warn_count += 1
                if strict:
                    entry["ok"] = False
                    aggregate_ok = False
                    error_count += 1
        # Dangling: per-recipe surface.
        for entry in per_recipe:
            rid = entry.get("recipe_id")
            if rid in _vg.dangling:
                missing = sorted(_vg.dangling[rid])
                dangling_msg = (
                    f"graph_dangling: related_recipes points to non-existent"
                    f" id(s): {', '.join(missing)}"
                )
                entry.setdefault("warnings", []).append(dangling_msg)
                warn_count += 1
                if strict:
                    entry["ok"] = False
                    aggregate_ok = False
                    error_count += 1
    except Exception:
        # Graph build is best-effort enhancement; never blocks validation.
        pass

    # v1.56.s278 — --csv preempts HTML/JSON/text.
    csv_str = str(csv_out)
    if csv_str and csv_str != ".":
        import csv as _csv
        csv_path = Path(csv_str)
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh)
                w.writerow(["path", "status", "error_count", "warning_count"])
                for entry in per_recipe:
                    w.writerow([
                        str(entry.get("path", "")),
                        str(entry.get("status", "?")),
                        len(entry.get("errors") or []),
                        len(entry.get("warnings") or []),
                    ])
        except Exception as exc:
            print(f"pack_validate_all_error=csv_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_validate_all_csv_path={csv_path}")
        print(f"pack_validate_all_csv_rows={len(per_recipe)}")
        if not aggregate_ok:
            raise typer.Exit(code=1)
        return

    # v1.41.s234 — HTML dashboard preempts JSON/text.
    html_str = str(html_out)
    if html_str and html_str != ".":
        html_path = Path(html_str)
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            rows_html: list[str] = []
            for entry in per_recipe:
                status = entry.get("status", "?")
                if status == "pass":
                    status_class = "b-green"
                elif status == "warn":
                    status_class = "b-yellow"
                else:
                    status_class = "b-red"
                errors_html = "".join(
                    f"<li class='err'>{html_escape(str(e))}</li>"
                    for e in (entry.get("errors") or [])
                )
                warnings_html = "".join(
                    f"<li class='warn'>{html_escape(str(w))}</li>"
                    for w in (entry.get("warnings") or [])
                )
                drilldown = ""
                if errors_html or warnings_html:
                    drilldown = (
                        "<ul class='drill'>"
                        + errors_html + warnings_html
                        + "</ul>"
                    )
                rows_html.append(
                    "<tr>"
                    f"<td>{html_escape(str(entry.get('path','?')))}</td>"
                    f"<td><span class='{status_class}'>{status}</span></td>"
                    f"<td class='num'>{len(entry.get('errors') or [])}</td>"
                    f"<td class='num'>{len(entry.get('warnings') or [])}</td>"
                    f"<td>{drilldown}</td>"
                    "</tr>"
                )
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>FAW Validate-All</title>"
                "<style>"
                "body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;}"
                "h1{margin-bottom:.2em}"
                ".summary{color:#666;margin-bottom:1em}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{padding:.4em .6em;border-bottom:1px solid #eee;"
                "text-align:left;vertical-align:top}"
                "td.num{text-align:right;font-variant-numeric:tabular-nums}"
                ".b-green,.b-yellow,.b-red{color:#fff;padding:2px 8px;"
                "border-radius:3px;font-size:.8em}"
                ".b-green{background:#2e7d32}"
                ".b-yellow{background:#f9a825;color:#000}"
                ".b-red{background:#c62828}"
                ".drill{margin:0;padding-left:1em;font-size:.85em}"
                ".err{color:#c62828}"
                ".warn{color:#f9a825}"
                "</style></head><body>"
                "<h1>FAW Recipe Validation</h1>"
                "<p class='summary'>"
                f"Total: {total} &middot; passed: {pass_count} &middot; "
                f"failed: {error_count} &middot; with warnings: {warn_count}"
                + (" &middot; strict mode" if strict else "")
                + "</p>"
                "<table>"
                "<thead><tr><th>Recipe</th><th>Status</th>"
                "<th>Errors</th><th>Warnings</th>"
                "<th>Details</th></tr></thead>"
                "<tbody>" + "".join(rows_html) + "</tbody></table>"
                "</body></html>"
            )
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            print(f"pack_validate_all_error=html_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_validate_all_html_path={html_path}")
        if open_html:
            import platform
            import subprocess
            sys_name = platform.system().lower()
            try:
                if sys_name == "windows":
                    import os
                    os.startfile(str(html_path.resolve()))  # type: ignore[attr-defined]
                elif sys_name == "darwin":
                    subprocess.run(["open", str(html_path.resolve())], check=False)
                else:
                    subprocess.run(["xdg-open", str(html_path.resolve())], check=False)
                print("pack_validate_all_html_opened=true")
            except Exception as exc:
                print(f"pack_validate_all_html_open_failed={exc}")
        if not aggregate_ok:
            raise typer.Exit(code=1)
        return

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
            # v1.39.s216 — --compact emits single-line JSON.
            indent=None if compact else 2,
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
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.52.s261: write standalone HTML diff dashboard"
                " (added/removed/modified packs with field-level changes)."
                " Preempts JSON/text."
            ),
        ),
    ] = Path(""),
    open_html: Annotated[
        bool,
        typer.Option(
            "--open",
            help=(
                "v1.52.s261: with --html, auto-open in system browser."
            ),
        ),
    ] = False,
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

    # v1.52.s261 — HTML preempts JSON/text.
    html_str = str(html_out)
    if html_str and html_str != ".":
        html_path = Path(html_str)
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            added_html = "".join(
                f"<li><code>{html_escape(str(p))}</code></li>"
                for p in diff.added_packs
            )
            removed_html = "".join(
                f"<li><code>{html_escape(str(p))}</code></li>"
                for p in diff.removed_packs
            )
            mod_rows: list[str] = []
            for mod in diff.modified_packs:
                changes = "".join(
                    f"<li><code>{html_escape(c.field)}</code>: "
                    f"{html_escape(str(c.old))} &rarr; {html_escape(str(c.new))}</li>"
                    for c in mod.changed_fields
                )
                mod_rows.append(
                    "<tr>"
                    f"<td><code>{html_escape(str(mod.pack_id))}</code></td>"
                    f"<td class='num'>{len(mod.changed_fields)}</td>"
                    f"<td><ul class='changes'>{changes}</ul></td>"
                    "</tr>"
                )
            recipe_changes = ""
            if diff.recipe_field_changes:
                rcs = "".join(
                    f"<li><code>{html_escape(c.field)}</code>: "
                    f"{html_escape(str(c.old))} &rarr; {html_escape(str(c.new))}</li>"
                    for c in diff.recipe_field_changes
                )
                recipe_changes = (
                    f"<h2>Recipe-level changes ({len(diff.recipe_field_changes)})</h2>"
                    f"<ul class='changes'>{rcs}</ul>"
                )
            verdict_class = "b-yellow" if diff.has_changes else "b-green"
            verdict_text = "CHANGES" if diff.has_changes else "NO CHANGES"
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>FAW Recipe Diff</title>"
                "<style>"
                "body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;}"
                "h1{margin-bottom:.2em}"
                "h2{margin-top:1.5em}"
                ".summary{color:#666;margin-bottom:1em}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{padding:.4em .6em;border-bottom:1px solid #eee;text-align:left;vertical-align:top}"
                "td.num{text-align:right;font-variant-numeric:tabular-nums}"
                "ul.changes{margin:0;padding-left:1.2em;font-size:.9em}"
                "code{background:#f5f5f5;padding:1px 4px;border-radius:2px;font-size:.9em}"
                ".b-green,.b-yellow{color:#fff;padding:2px 8px;border-radius:3px;font-size:.8em}"
                ".b-green{background:#2e7d32}"
                ".b-yellow{background:#f9a825;color:#000}"
                "</style></head><body>"
                "<h1>FAW Recipe Diff</h1>"
                "<p class='summary'>"
                f"Old: <code>{html_escape(str(old_resolved))}</code><br>"
                f"New: <code>{html_escape(str(new_resolved))}</code><br>"
                f"Verdict: <span class='{verdict_class}'>{verdict_text}</span> &middot; "
                f"added: {len(diff.added_packs)} &middot; "
                f"removed: {len(diff.removed_packs)} &middot; "
                f"modified: {len(diff.modified_packs)}"
                "</p>"
                + (
                    f"<h2>Added packs ({len(diff.added_packs)})</h2><ul>{added_html}</ul>"
                    if diff.added_packs else ""
                )
                + (
                    f"<h2>Removed packs ({len(diff.removed_packs)})</h2><ul>{removed_html}</ul>"
                    if diff.removed_packs else ""
                )
                + (
                    f"<h2>Modified packs ({len(diff.modified_packs)})</h2>"
                    "<table><thead><tr><th>Pack id</th><th># changes</th>"
                    "<th>Field changes</th></tr></thead>"
                    f"<tbody>{''.join(mod_rows)}</tbody></table>"
                    if diff.modified_packs else ""
                )
                + recipe_changes
                + "</body></html>"
            )
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            print(f"pack_diff_error=html_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_diff_html_path={html_path}")
        if open_html:
            import platform
            import subprocess
            sys_name = platform.system().lower()
            try:
                if sys_name == "windows":
                    import os
                    os.startfile(str(html_path.resolve()))  # type: ignore[attr-defined]
                elif sys_name == "darwin":
                    subprocess.run(["open", str(html_path.resolve())], check=False)
                else:
                    subprocess.run(["xdg-open", str(html_path.resolve())], check=False)
                print("pack_diff_html_opened=true")
            except Exception as exc:
                print(f"pack_diff_html_open_failed={exc}")
        if diff.has_changes:
            raise typer.Exit(code=1)
        return

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
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.50.s258: write standalone HTML rerun report (per-pack"
                " status: succeeded/failed/skipped). Preempts JSON/text."
            ),
        ),
    ] = Path(""),
    csv_out: Annotated[
        Path,
        typer.Option(
            "--csv",
            help=(
                "v1.56.s278: write rerun results as CSV (header:"
                " pack_id,status,state)."
            ),
        ),
    ] = Path(""),
    open_html: Annotated[
        bool,
        typer.Option(
            "--open",
            help=(
                "v1.50.s258: with --html, auto-open in system browser."
            ),
        ),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help=(
                "v1.39.s217: single-line JSON output. No effect without --json."
            ),
        ),
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
            # v1.39.s217 — --compact emits single-line JSON.
            json.dump(summary, sys.stdout, indent=None if compact else 2)
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
    ema_max = recipe_meta.get("expected_max_assets")  # v1.45.s248
    _has_min = isinstance(ema, int) and not isinstance(ema, bool) and ema >= 0
    _has_max = (isinstance(ema_max, int)
                and not isinstance(ema_max, bool) and ema_max >= 0)
    if _has_min or _has_max:
        import re as _re
        _dlp = _re.compile(r"downloaded=(\d+)")
        td = 0
        for r in results:
            notes = str(r.get("notes", "") or r.get("source_dir", "")
                        or r.get("current_state", ""))
            for m in _dlp.finditer(notes):
                td += int(m.group(1))
        expected_status_r = {"total_downloaded_seen": td}
        if _has_min:
            expected_status_r["expected_min_assets"] = ema
            expected_status_r["meets_expected_min"] = td >= ema
        if _has_max:
            expected_status_r["expected_max_assets"] = ema_max
            expected_status_r["within_expected_max"] = td <= ema_max
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

    # v1.56.s278 — --csv preempts HTML/JSON/text.
    csv_str = str(csv_out)
    if csv_str and csv_str != ".":
        import csv as _csv
        csv_path = Path(csv_str)
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh)
                w.writerow(["pack_id", "status", "state"])
                for r in results:
                    w.writerow([
                        str(r.get("pack_id", "?")),
                        str(r.get("status", "?")),
                        str(r.get("current_state", "") or ""),
                    ])
                for pid in deferred_ids:
                    w.writerow([str(pid), "deferred", ""])
        except Exception as exc:
            print(f"pack_rerun_failed_error=csv_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_rerun_failed_csv_path={csv_path}")
        print(f"pack_rerun_failed_csv_rows={len(results) + len(deferred_ids)}")
        if re_fail > 0:
            raise typer.Exit(code=1)
        return

    # v1.50.s258 — HTML preempts JSON/text.
    html_str = str(html_out)
    if html_str and html_str != ".":
        html_path = Path(html_str)
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            rows_html: list[str] = []
            for r in results:
                status = r.get("status", "?")
                if status == "completed":
                    status_class = "b-green"
                elif status == "pending_manual_drop":
                    status_class = "b-yellow"
                else:
                    status_class = "b-red"
                pid = str(r.get("pack_id", "?"))
                rows_html.append(
                    "<tr>"
                    f"<td>{html_escape(pid)}</td>"
                    f"<td><span class='{status_class}'>{html_escape(status)}</span></td>"
                    f"<td>{html_escape(str(r.get('current_state','?') or ''))}</td>"
                    "</tr>"
                )
            deferred_rows = "".join(
                f"<tr><td>{html_escape(pid)}</td>"
                "<td><span class='b-grey'>deferred</span></td>"
                "<td>(--max-attempts cap)</td></tr>"
                for pid in deferred_ids
            )
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>FAW Rerun Failed</title>"
                "<style>"
                "body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;}"
                "h1{margin-bottom:.2em}"
                ".summary{color:#666;margin-bottom:1em}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{padding:.4em .6em;border-bottom:1px solid #eee;text-align:left}"
                ".b-green,.b-yellow,.b-red,.b-grey{color:#fff;padding:2px 8px;"
                "border-radius:3px;font-size:.8em}"
                ".b-green{background:#2e7d32}"
                ".b-yellow{background:#f9a825;color:#000}"
                ".b-red{background:#c62828}"
                ".b-grey{background:#9e9e9e}"
                "</style></head><body>"
                "<h1>FAW Rerun Failed</h1>"
                "<p class='summary'>"
                f"Recipe: <code>{html_escape(str(resolved))}</code> &middot; "
                f"total failed (audit): {len(failed)} &middot; "
                f"matched in recipe: {len(targets) + len(deferred_ids)} &middot; "
                f"rerun succeeded: {re_success} &middot; "
                f"rerun failed: {re_fail} &middot; "
                f"deferred: {len(deferred_ids)}"
                "</p>"
                "<table>"
                "<thead><tr><th>Pack id</th><th>Status</th>"
                "<th>State / Notes</th></tr></thead>"
                "<tbody>" + "".join(rows_html) + deferred_rows + "</tbody>"
                "</table>"
                "</body></html>"
            )
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            print(f"pack_rerun_failed_error=html_write_failed: {exc}")
            raise typer.Exit(code=1)
        print(f"pack_rerun_failed_html_path={html_path}")
        if open_html:
            import platform
            import subprocess
            sys_name = platform.system().lower()
            try:
                if sys_name == "windows":
                    import os
                    os.startfile(str(html_path.resolve()))  # type: ignore[attr-defined]
                elif sys_name == "darwin":
                    subprocess.run(["open", str(html_path.resolve())], check=False)
                else:
                    subprocess.run(["xdg-open", str(html_path.resolve())], check=False)
                print("pack_rerun_failed_html_opened=true")
            except Exception as exc:
                print(f"pack_rerun_failed_html_open_failed={exc}")
        if re_fail > 0:
            raise typer.Exit(code=1)
        return

    if json_out:
        # v1.39.s217 — --compact emits single-line JSON.
        json.dump(summary, sys.stdout, indent=None if compact else 2)
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
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.40.s222: write standalone HTML report (CSS bars +"
                " per-source rows). Mutually exclusive with --json/--csv;"
                " stdout shows only the written path."
            ),
        ),
    ] = Path(""),
    open_html: Annotated[
        bool,
        typer.Option(
            "--open",
            help=(
                "v1.40.s222: when used with --html, auto-open in system"
                " browser (Windows: os.startfile, macOS: open, Linux:"
                " xdg-open). No-op without --html."
            ),
        ),
    ] = False,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help=(
                "v1.36.s206: single-line JSON output. No effect without --json."
            ),
        ),
    ] = False,
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

    # v1.40.s222 — HTML preempts CSV/JSON/text (mutually exclusive).
    html_str = str(html_out)
    if html_str and html_str != ".":
        html_path = Path(html_str)
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            max_bytes = max(
                (int(b.get("bytes", 0) or 0) for b in per_source_view.values()),
                default=0,
            )
            rows_html: list[str] = []
            for src, b in sorted(
                per_source_view.items(),
                key=lambda kv: int(kv[1].get("bytes", 0) or 0),
                reverse=True,
            ):
                bytes_v = int(b.get("bytes", 0) or 0)
                pct = (100.0 * bytes_v / max_bytes) if max_bytes > 0 else 0.0
                rows_html.append(
                    "<tr>"
                    f"<td>{src}</td>"
                    f"<td class='num'>{int(b.get('manifests', 0))}</td>"
                    f"<td class='num'>{int(b.get('downloaded', 0))}</td>"
                    f"<td class='num'>{int(b.get('skipped', 0))}</td>"
                    f"<td class='num'>{int(b.get('failed', 0))}</td>"
                    f"<td class='num'>{bytes_v:,}</td>"
                    f"<td><div class='bar' style='width:{pct:.1f}%'></div></td>"
                    "</tr>"
                )
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>FAW Manifest Stats</title>"
                "<style>"
                "body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;}"
                "h1{margin-bottom:.2em}"
                ".summary{color:#666;margin-bottom:1em}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{padding:.4em .6em;border-bottom:1px solid #eee;text-align:left}"
                "td.num{text-align:right;font-variant-numeric:tabular-nums}"
                ".bar{background:#4a90e2;height:14px;border-radius:2px}"
                "</style></head><body>"
                "<h1>FAW Manifest Stats</h1>"
                "<p class='summary'>"
                f"Manifests scanned: {len(manifests)} &middot; "
                f"Sources: {len(per_source)} &middot; "
                f"Downloaded: {total_downloaded:,} &middot; "
                f"Failed: {total_failed:,} &middot; "
                f"Total bytes: {total_bytes:,}"
                "</p>"
                "<table>"
                "<thead><tr>"
                "<th>Source</th><th>Manifests</th><th>Downloaded</th>"
                "<th>Skipped</th><th>Failed</th><th>Bytes</th>"
                "<th>Bytes proportion</th>"
                "</tr></thead><tbody>"
                + "".join(rows_html)
                + "</tbody></table>"
                f"<p class='summary'>Scan root: <code>{scan_root}</code></p>"
                "</body></html>"
            )
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            msg = f"html_write_failed: {exc}"
            print(f"pack_manifest_stats_error={msg}")
            raise typer.Exit(code=1)
        print(f"pack_manifest_stats_html_path={html_path}")
        if open_html:
            import platform
            import subprocess
            sys_name = platform.system().lower()
            try:
                if sys_name == "windows":
                    import os
                    os.startfile(str(html_path.resolve()))  # type: ignore[attr-defined]
                elif sys_name == "darwin":
                    subprocess.run(["open", str(html_path.resolve())], check=False)
                else:
                    subprocess.run(["xdg-open", str(html_path.resolve())], check=False)
                print("pack_manifest_stats_html_opened=true")
            except Exception as exc:
                print(f"pack_manifest_stats_html_open_failed={exc}")
        return

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
        # v1.36.s206 — --compact emits single-line JSON.
        json.dump(summary, sys.stdout, indent=None if compact else 2)
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


@app.command("run-plan")
def run_plan_cmd(
    recipes_root_override: Annotated[
        str,
        typer.Option(
            "--recipes-root",
            help=(
                "Override the recipes/ scan root (default: auto-detect)."
            ),
        ),
    ] = "",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help=(
                "Plan only — print steps that WOULD run; no pack pipeline"
                " side effects. Default ON (operator must explicitly opt"
                " out via --no-dry-run to execute)."
            ),
        ),
    ] = True,
    fail_fast: Annotated[
        bool,
        typer.Option(
            "--fail-fast",
            help=(
                "Halt on first failed pack; default is keep going and"
                " report all failures at end."
            ),
        ),
    ] = False,
    max_parallel: Annotated[
        int,
        typer.Option(
            "--max-parallel",
            help=(
                "Cap parallel pack executions per batch level. 1"
                " (default) = sequential. Honors RecipeGraph.parallel_batches."
            ),
        ),
    ] = 1,
    filter_: Annotated[
        list[str],
        typer.Option(
            "--filter",
            help=(
                "Recipe filter (same shape as list-recipes --filter)."
                " Repeatable; ANDed."
            ),
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help="Single-line JSON output. No effect without --json.",
        ),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Execute recipes in topological order against pack pipeline (v1.66.s297).

    Builds the recipe graph from related_recipes; emits a plan; runs each
    recipe's from-recipe pipeline in dependency order.

    Cycles -> exit 1 with no execution. --dry-run prints the plan but
    never modifies pack-pipeline state. --max-parallel N + parallel_batches
    enables level-by-level concurrent execution.

    JSON output: {ok, dry_run, plan, executed, failed, errors}.
    """
    from assetboy.workflows.recipe_graph import build_graph

    recipes_root = (
        Path(recipes_root_override) if recipes_root_override.strip()
        else _recipes_dir()
    )
    if not recipes_root.exists():
        msg = f"recipes_dir_not_found: {recipes_root}"
        if json_out:
            json.dump({"ok": False, "error": msg},
                      sys.stdout, indent=None if compact else 2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_plan_error={msg}")
        raise typer.Exit(code=1)

    graph = build_graph(recipes_root)
    topo = graph.topological_sort()
    if topo is None:
        msg = "run_plan_failed: cycle detected in recipe.related_recipes"
        if json_out:
            json.dump({"ok": False, "error": msg, "dry_run": dry_run},
                      sys.stdout, indent=None if compact else 2)
            sys.stdout.write("\n")
        else:
            print(f"pack_run_plan_error={msg}")
        raise typer.Exit(code=1)

    # Parse --filter into (field, value) tuples and reuse list-recipes
    # filter logic to narrow execution set.
    parsed_filters: list[tuple[str, str]] = []
    for f in (filter_ or []):
        if ":" in f:
            fn, _, fv = f.partition(":")
            parsed_filters.append((fn.strip(), fv.strip()))

    # Walk recipes/ to find {recipe_id -> recipe_yaml path}.
    rid_to_path: dict[str, Path] = {}
    if yaml is not None:
        for yml in recipes_root.rglob("*.yaml"):
            try:
                doc = yaml.safe_load(yml.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(doc, dict):
                r = doc.get("recipe") or {}
                rid = r.get("id")
                if isinstance(rid, str) and rid.strip():
                    rid_to_path[rid.strip()] = yml

    # Plan = topo order restricted to recipes we found on disk.
    plan_ids = [rid for rid in topo if rid in rid_to_path]

    # Build executed list (dry-run: just record; real: would invoke pipeline).
    executed: list[dict] = []
    failed_ids: list[str] = []
    errors: list[str] = []

    for rid in plan_ids:
        recipe_path = rid_to_path[rid]
        step = {
            "recipe_id": rid,
            "path": str(recipe_path.relative_to(recipes_root)),
            "dry_run": dry_run,
            "ok": True,
        }
        if dry_run:
            executed.append(step)
        else:
            # Real execution path: defer to from-recipe pipeline.
            # We don't recursively invoke from this command (avoids
            # Typer-in-Typer brittleness); we just emit instructions
            # for the operator/runner. Future work: wire to internal
            # _run_from_recipe helper.
            step["ok"] = False
            step["error"] = "real_execution_not_implemented_yet"
            failed_ids.append(rid)
            errors.append(
                f"{rid}: real execution path stubbed; use --dry-run"
            )
            executed.append(step)
            if fail_fast:
                break

    summary = {
        "ok": len(failed_ids) == 0,
        "dry_run": dry_run,
        "fail_fast": fail_fast,
        "max_parallel": max_parallel,
        "total_planned": len(plan_ids),
        "executed_count": len(executed),
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors,
        "plan": [s["recipe_id"] for s in executed],
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=None if compact else 2)
        sys.stdout.write("\n")
    else:
        marker = "DRY" if dry_run else "RUN"
        print(f"pack_run_plan_mode={marker}")
        print(f"pack_run_plan_total_planned={len(plan_ids)}")
        print(f"pack_run_plan_executed_count={len(executed)}")
        print(f"pack_run_plan_failed_count={len(failed_ids)}")
        for s in executed:
            tag = "[OK ]" if s["ok"] else "[FAIL]"
            print(f"  {tag} {s['recipe_id']:30s} {s['path']}")
        if errors:
            print("pack_run_plan_errors:")
            for e in errors:
                print(f"  {e}")

    if not summary["ok"]:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
