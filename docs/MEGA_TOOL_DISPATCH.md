# `manage_asset_worker` mega-tool — action dispatch map

> **Audience:** Lane E broker implementing the flax-mcp facade's
> `manage_asset_worker` mega-tool. Copy-paste reference for the
> action enum + per-action argument shape + dispatch target.
>
> **Date:** 2026-05-11 (Path B v1.7.s11)
> **Companion doc:** `docs/MONOREPO_FACADE_DESIGN.md`

---

## Why a mega-tool

flax-mcp's `[MegaTool]` pattern bundles related atomics behind a single
`action` field so AI clients see ONE entry in `tool/list` instead of N.
For asset-worker, the 6+ atomics in `MONOREPO_FACADE_DESIGN.md` all
share the `asset_worker/*` namespace and similar argument shapes — a
prime mega-tool candidate.

## Effective policy resolution

Per `docs/SAFETY.md` mega-tool policy contract: the mega-tool carries a
`Policy.Mutating` base but the kernel resolves the EFFECTIVE policy at
call-time using the atomic's declared policy. Safe sub-actions skip
the intent requirement. Destructive sub-actions require `dryRunId`.

In this mega-tool, the action -> policy map is:

| action | Effective policy | intent? | dryRunId? |
|---|---|---|---|
| `list_recipes` | Safe | no | no |
| `pack_status` | Safe | no | no |
| `canary_status` | Safe | no | no |
| `library_search` | Safe | no | no |
| `library_ready` | Safe | no | no |
| `library_asset` | Safe | no | no |
| `audit` | Safe | no | no |
| `validate` | Safe | no | no |
| `pack_from_recipe` | Mutating | yes | no |
| `pack_run_pack` | Mutating | yes | no |
| `pack_rerun_failed` | Mutating | yes | no |
| `library_install` | Mutating | yes | no |

(No Destructive actions in v1; rollback story is recipe-driven re-runs.)

---

## Action dispatch table

### `list_recipes` (Safe)

**Args:** none

**Returns:** `{ recipes: [{game, recipe_id, pack_count, path}], count }`

**Routes to:** `POST /api/v1/recipes/list`

**CLI source:** `python -m assetboy.cli pack list-recipes --json`

---

### `pack_status` (Safe)

**Args:**
```json
{
  "pack_id": "SHARED_FAB_FOLIAGE_FOREST_BROADLEAF_TREES_01",
  "game_scope": "primitive_tech"           // optional; defaults to primitive_tech
}
```

**Returns:** full ledger dict (status, current_state, next_step, error?, ledger_path, ...)

**Routes to:** `GET /api/v1/packs/{pack_id}/status?game={game_scope}`

**CLI source:** `python -m assetboy.cli pack status <pack_id> --game <scope> --json`

---

### `library_search` (Safe)

**Args:**
```json
{
  "query": "stone wall mossy",
  "category": ""                  // optional filter
}
```

**Returns:** `{ results: [...], count }`

**Routes to:** `POST /api/v1/library/search`

---

### `library_asset` (Safe)

**Args:**
```json
{
  "asset_id": "brick_wall_04"
}
```

**Returns:** `{ success: true, asset: {...} }` or `{ success: false, error: "asset_not_found" }`

**Routes to:** `GET /api/v1/library/asset/{asset_id}`

**CLI source:** `python -m assetboy.cli library asset <asset_id> --json`

---

### `library_ready` (Safe)

**Args:** none

**Returns:** `{ ready_assets: [...], count }`

**Routes to:** `POST /api/v1/library/ready`

---

### `canary_status` (Safe)

**Args:** none

**Returns:** canary_status.json contents (`{timestamp, elapsed_ms, overall, probes: {polyhaven, fab, epic, unity_hub, comfyui}}`)

**Routes to:** `GET /api/v1/canary/status`

**CLI source:** `python -m assetboy.canary --json` (writes state/canary/canary_status.json which the C# route reads)

---

### `audit` (Safe)

**Args:**
```json
{
  "game": "",                     // optional filter; default: all games
  "include_ledgers": true,        // default true
  "max": 1000                     // ledger list cap
}
```

**Returns:** `{ summary, games, ledgers, pipeline_dir }`

**Routes to:** `GET /api/v1/packs/audit?game={game}&include_ledgers={bool}&max={int}`

**CLI source:** `python -m assetboy.cli pack audit --json` (+ optional `--game`, `--no-ledgers`, `--max`)

---

### `validate` (Safe)

**Args:**
```json
{
  "recipe_path": "primitive_tech/first_playable.yaml",
  "strict": false                 // treat warnings as errors
}
```

**Returns:** `{ ok, recipe_id, pack_count, errors, warnings, path }`

**Routes to:** *(no HTTP endpoint yet — invoke via subprocess to `python -m assetboy.cli pack validate <path> --json`)*

---

### `pack_from_recipe` (Mutating; **intent required**)

**Args:**
```json
{
  "intent": "human-readable reason for this run",
  "recipe_path": "primitive_tech/first_playable.yaml",
  "recipe_yaml": "",              // OR provide inline YAML
  "dry_run": false,
  "resume": true,
  "only_required": false,
  "skip": []
}
```

`recipe_path` OR `recipe_yaml` (not both). `recipe_yaml` is forwarded to
the CLI's `--inline-yaml` flag (v1.6.s1).

**Returns:** `{ recipe_id, game, total_packs, completed, failed, required_failed, results: [...] }`

**Routes to:** `POST /api/v1/recipes/run`

**CLI source:** `python -m assetboy.cli pack from-recipe <path or -> --json [--dry-run] [--inline-yaml ...]`

---

### `pack_run_pack` (Mutating; **intent required**)

**Args:**
```json
{
  "intent": "human-readable reason",
  "pack_yaml": "id: TEST\nprovider: polyhaven\n...",
  "pack": { "id": "...", ... },    // OR JSON dict (server converts to YAML)
  "game_scope": "sandbox",
  "dry_run": false,
  "resume": true
}
```

`pack_yaml` OR `pack` (not both).

**Returns:** full ledger dict + `cli_exit_code`

**Routes to:** `POST /api/v1/packs/run-pack`

**CLI source:** `python -m assetboy.cli pack run-pack --pack <yaml> --game <scope> --json`

---

### `pack_rerun_failed` (Mutating; **intent required**)

**Args:**
```json
{
  "intent": "rerun after fab auth refresh",
  "recipe_path": "roman/first_playable.yaml",
  "game": "",                              // optional filter
  "skip_acquisition_failures": false,
  "dry_run": false
}
```

**Returns:** `{ ok, recipe, game_filter, total_failed_in_audit, matched_in_recipe, skipped_not_in_recipe, rerun_succeeded, rerun_failed, results: [...] }`

**Routes to:** *(no HTTP endpoint yet — subprocess to `python -m assetboy.cli pack rerun-failed --recipe <path> --json`)*

---

### `library_install` (Mutating; **intent required**)

**Args:**
```json
{
  "intent": "human reason",
  "asset_id": "brick_wall_01",
  "provider": "polyhaven",
  "category": "texture",
  "name": "Brick Wall 01"          // optional; defaults to asset_id
}
```

**Returns:** `{ success, asset: {...}, message }`

**Routes to:** `POST /api/v1/library/install`

**CLI source:** `python -m assetboy.cli library install <asset_id> --provider <id> --category <cat> --name <n> --json`

---

## C# wiring sketch (Lane E reference)

```csharp
[MegaTool("manage_asset_worker", "asset_worker",
    Description = "Asset pipeline operations: recipes, packs, library, canary.",
    Policy = Policy.Mutating)]
public static class ManageAssetWorker
{
    private static readonly HttpClient _http = new() {
        BaseAddress = new Uri("http://localhost:8790"),
    };

    [Tool("asset_worker", "manage_asset_worker", IsMega = true)]
    public static ToolResult Dispatch(ToolContext ctx)
    {
        var action = ctx.Arg<string>("action") ?? "";
        return action switch
        {
            "list_recipes"     => ListRecipes(ctx),
            "pack_status"      => PackStatus(ctx),
            "library_search"   => LibrarySearch(ctx),
            "library_asset"    => LibraryAsset(ctx),
            "library_ready"    => LibraryReady(ctx),
            "canary_status"    => CanaryStatus(ctx),
            "audit"            => Audit(ctx),
            "validate"         => Validate(ctx),
            "pack_from_recipe" => PackFromRecipe(ctx),   // policy gate runs first
            "pack_run_pack"    => PackRunPack(ctx),
            "pack_rerun_failed"=> PackRerunFailed(ctx),
            "library_install"  => LibraryInstall(ctx),
            _ => ToolResult.Error($"unknown_action: {action}",
                                  "expected one of: " +
                                  "list_recipes, pack_status, library_search, library_asset, " +
                                  "library_ready, canary_status, audit, validate, " +
                                  "pack_from_recipe, pack_run_pack, pack_rerun_failed, library_install"),
        };
    }
    // ... per-action thin HttpClient wrappers ...
}
```

Each per-action method:
1. Reads `ctx` args via `ctx.Arg<T>(...)`.
2. Builds the HTTP request (GET / POST).
3. Awaits `_http.SendAsync(...)`.
4. Parses JSON response with Newtonsoft.Json.Linq.JObject.Parse.
5. Returns `ToolResult.Ok(jobject)` or `ToolResult.Error(...)` on non-2xx.

The kernel's effective-policy resolution (per `docs/SAFETY.md` ADR-018)
walks the action table to find the per-atomic policy AND enforces
intent/dryRunId per the Mutating sub-action's declared policy. Safe
sub-actions skip those checks.

---

(End of dispatch map — v1.7.s11 2026-05-11)
