# Recipe Graph — cross-recipe discovery + analysis

> Added 2026-05-14 (lane-E BIG-SLICE-MANDATE block, waves v1.58–v1.63).
> Covers recipe.related_recipes graph + every graph-aware filter, sort
> key, output format, and HTTP endpoint shipped to date.

## What is the recipe graph?

Every recipe under `recipes/<game>/<file>.yaml` can declare a list of
related recipe ids via the optional `recipe.related_recipes` field
(introduced in v1.58.s281):

```yaml
recipe:
  id: parent_recipe
  game: my_game
  related_recipes:
    - child_recipe_a
    - child_recipe_b
```

These references form a **directed graph** across the entire recipes
tree. Each edge is `from -> to` along an `out_edges` direction. The
graph is built lazily on demand (only when a graph-aware filter / sort
/ output flag is in use).

## Building & inspecting the graph

```pwsh
# Emit graph as JSON (full structure)
pack list-recipes --graph

# Emit graph as HTML (CSS dashboard with badges + topo order)
pack list-recipes --graph --html report.html

# Emit graph as CSV (kind,from_id,to_id with rows for edges/dangling/orphans)
pack list-recipes --graph --csv graph.csv

# Emit graph as Mermaid (.mmd file; render via Mermaid CLI / GitHub / Notion)
pack list-recipes --graph --mermaid graph.mmd

# Single-line JSON (for jq pipes / HTTP transport)
pack list-recipes --graph --compact

# HTTP endpoint (same JSON shape, served on :8790)
GET /api/v1/library/recipe-graph
GET /api/v1/library/recipe-graph?recipes_root=/path/to/custom
GET /api/v1/library/recipe-plan
GET /api/v1/library/recipe-plan?batches=true
GET /api/v1/library/recipe-run-plan
GET /api/v1/library/recipe-run-plan?filter=platform:flax,kind:image
```

## Run-plan executor (v1.66)

`pack run-plan` actually runs the planned recipes in topo order. Real
execution path is currently stubbed (emits
`real_execution_not_implemented_yet` per recipe); the dry-run path is
fully functional and surfaces what WOULD run.

```pwsh
# Dry-run (default) — print plan, no side effects
pack run-plan

# Narrow with --filter (same shape as list-recipes; recipe-level
# fields + has-FIELD)
pack run-plan --filter platform:flax --filter has-author:true

# Real exec (stubbed — emits per-recipe error today)
pack run-plan --no-dry-run

# Halt on first failure (real-exec mode)
pack run-plan --no-dry-run --fail-fast

# Parallel batches (v1.67.s299)
pack run-plan --no-dry-run --max-parallel 4

# HTML execution report (v1.67.s300)
pack run-plan --no-dry-run --html report.html

# Stop after specific recipe completes (v1.67.s300)
pack run-plan --no-dry-run --stop-after r_foo
```

JSON output (v1.67.s300) carries per-step `steps` array with
`duration_ms`, `exit_code`, and `error` fields. HTML format includes
mode badge (DRY-RUN/LIVE), counters, and a steps table.

## Mermaid format

`--mermaid` writes a `graph LR` document (v1.65.s295):

```mermaid
graph LR;
  recipe_a --> recipe_b;
  recipe_a -.-> ghost_id;   %% dashed = dangling reference
  recipe_c;                  %% orphan (isolated node)
```

Solid arrows = real edges; dashed = dangling refs; standalone nodes
= orphans. Ids with non-alphanumeric chars (`-`, `.`, etc.) are
sanitized to `_` (Mermaid syntax requirement). Renders in GitHub,
GitLab, Notion, and the Mermaid Live Editor.

## Pipeline execution planner

`pack list-recipes --plan` (v1.64.s293) emits a topo-ordered execution
plan. Each step record carries `{step, recipe_id, depth, pack_count,
depends_on, game}`. Cycles cause exit 1.

`--plan --batches` (v1.64.s294) groups recipes into parallel-execution
levels. Each batch contains zero-in-degree recipes that can execute
concurrently. Useful for `make -j` style pipelines.

## Validation integration

`pack validate-all` (v1.65.s295) surfaces graph-level issues as
per-recipe warnings:

- `graph_cycle: ...` — cycle detected across recipes
- `graph_dangling: ...` — related_recipes points to non-existent id(s)

Use `--strict` to promote these warnings to errors (non-zero exit).

## JSON contract

The `--graph` output is a single object with these keys (introduced
across v1.59–v1.61 BIG-SLICEs):

| Key | Type | Description |
|---|---|---|
| `out_edges` | `dict[str, list[str]]` | id -> sorted target ids |
| `in_edges` | `dict[str, list[str]]` | id -> sorted referrer ids |
| `all_ids` | `list[str]` | sorted recipe ids in the catalog |
| `dangling` | `dict[str, list[str]]` | id -> sorted missing target ids |
| `orphans` | `list[str]` | sorted ids with no in AND no out edges |
| `total_recipes` | `int` | len(all_ids) |
| `total_edges` | `int` | sum of out_edges sizes (excl dangling) |
| `dangling_count` | `int` | sum of dangling targets |
| `orphan_count` | `int` | len(orphans) |
| `is_acyclic` | `bool` | true when topo-sort succeeds |
| `topo_order` | `list[str] \| null` | dependency-respecting order, or null on cycle |
| `entry_points` | `list[str]` | sorted ids with no incoming edges and at least one outgoing |
| `leaves` | `list[str]` | sorted ids with incoming edges and no outgoing |
| `max_depth` | `int \| null` | longest path length (None on cycle) |

When fetched via HTTP, the wrapper also adds `success: true` at the
top level.

## Filters (`--filter`)

All 9 graph-aware filters auto-trigger a graph build. Use with
`pack list-recipes`:

| Filter | Effect |
|---|---|
| `is-orphan:true/false` | recipes with no in AND no out edges (v1.59.s283) |
| `has-dangling:true/false` | recipes pointing to non-existent ids (v1.59.s283) |
| `descendants-of:<id>` | recipes reachable from `<id>` via out_edges (v1.59.s284) |
| `ancestors-of:<id>` | recipes that reach `<id>` via out_edges (v1.59.s284) |
| `is-entry-point:true/false` | non-orphan roots (in=0, out>=1) (v1.61.s287) |
| `depth-from:<root>:<n>` | BFS distance from `<root>` is `<=` `<n>` (v1.61.s287) |
| `is-leaf:true/false` | terminal nodes (in>=1, out=0) (v1.61.s288) |
| `related-recipe:<id>` | recipes with `<id>` in their related_recipes (v1.58.s281) |
| `related-count:<n>` | recipes with `>=<n>` valid related entries (v1.58.s281) |
| `on-path:<src>:<dst>` | recipes on shortest path from src to dst (v1.62.s290) |

## Sort keys (`--sort`)

The 4 graph-aware sort keys all auto-build the graph:

| Sort key | Effect |
|---|---|
| `topo` | topological order; cycles fall to path-alpha (v1.62.s289) |
| `depth` | max depth from any entry point; deeper later (v1.62.s289) |
| `in_degree` | least incoming edges first (roots first) (v1.62.s289) |
| `out_degree` | least outgoing edges first (leaves first) (v1.62.s289) |

Pair with `--reverse` to flip ordering, `--limit N` to cap output.

## CSV format

`pack list-recipes --graph --csv <path>` writes a 3-column CSV:

```csv
kind,from_id,to_id
edge,parent,child_a
edge,parent,child_b
dangling,parent,nonexistent_target
orphan,isolated_recipe,
```

Mixed-kind format lets you `grep`/`awk` for specific types or load
into a DataFrame for joins with other reports.

## HTML format

`pack list-recipes --graph --html <path>` writes a CSS-styled report:

- Header summary with edge/orphan/dangling counts + acyclic/cyclic badge
- Topological order list (or red warning on cycle)
- Edges table sorted by `from` id alpha
- Orphans list
- Dangling references table

The `--open` flag auto-launches the file in the system browser.

## Module API (Python)

```python
from assetboy.workflows.recipe_graph import build_graph, RecipeGraph

g: RecipeGraph = build_graph(Path("recipes/"))

# Direct attribute access
g.out_edges["parent"]   # set[str]
g.in_edges["child_a"]   # set[str]
g.orphans               # set[str]
g.dangling              # dict[str, set[str]]

# Derived queries
g.descendants("hub")          # set[str] — transitive closure forward
g.ancestors("leaf")           # set[str] — transitive closure backward
g.depth_from("root")          # dict[str, int] — BFS distance map
g.entry_points()              # set[str]
g.leaves()                    # set[str]
g.is_acyclic()                # bool
g.topological_sort()          # list[str] | None
g.max_depth()                 # int | None
g.path_between("a", "z")      # list[str] | None — BFS shortest path
g.has_path("a", "z")          # bool

# JSON-friendly serialization
g.to_dict()                   # dict[str, Any]
```

## Validator behavior

`recipe.related_recipes` is **optional**. Validator soft-warns on:

- non-list value (`related_recipes: "single_id"` -> warning)
- empty list (`related_recipes: []` -> warning)
- non-string entries (`related_recipes: [42]` -> warning)
- empty string entries (`related_recipes: ["", "valid"]` -> warning)

It never errors — invalid entries are silently filtered when the graph
builds.

Dangling references (pointing to non-existent recipe ids) are NOT
warnings at validation time — they're only detected when the graph is
built (a global operation). Use `pack list-recipes --filter
has-dangling:true` to find them.

## Use cases

1. **Pipeline ordering**: `--sort topo` then process the recipes in order.
2. **Impact analysis**: `--filter ancestors-of:my_recipe` shows what
   would break if `my_recipe` changes.
3. **Reachability check**: `--filter descendants-of:entry_point` walks
   forward from a known root.
4. **Cleanup**: `--filter is-orphan:true` finds disconnected recipes
   ready for archive/delete.
5. **Dependency repair**: `--filter has-dangling:true` finds broken
   references; cross-reference with validate-all for full picture.
6. **CI gate**: `--graph` JSON `is_acyclic` field can fail a CI check
   if cycles introduced.

## See also

- `RELEASE_NOTES_v1.40_v1.57.md` — HTML/CSV/filter polish predating graph
- `docs/RECIPE_SCHEMA.md` — full recipe field reference
- `HEARTBEAT-assetboi.md` — current state pointer
