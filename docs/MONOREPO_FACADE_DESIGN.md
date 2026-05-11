# flax-mcp monorepo facade — design doc

> **Audience:** Lane E broker + operator (post-hibernation).
> **assetboi cannot commit to `flax-mcp`** (multi-AI etiquette); this
> doc lives in the standalone repo as a reference for whoever DOES
> own the flax-mcp side of the integration.
>
> **Date:** 2026-05-11 (Path B v1.4.2)

---

## TL;DR

flax-mcp ships a scaffold plugin at `plugins/flax-asset-worker/` that
documents itself as "ASYNC ASSET-IMPORT QUEUING" (per its AGENTS.md
Phase C8 scaffold). As of Path B v1.2.1, the **real** asset worker
lives in this standalone repo (`flax-asset-worker/`) and exposes:

1. A 7-sub-app Typer CLI (`python -m assetboy.cli`).
2. An HTTP server on `:8790` (Flax C# `WorkerHttpServer.cs`).
3. A 3-lane acquisition_router (direct_url / manual_browser / generator).
4. 4 generator providers wired (comfyui, sd.cpp, local_image, stable_audio).
5. Recipe-driven pack runs (primitive_tech, roman_arena, sandbox).

The flax-mcp plugin should become a **thin facade** over the standalone:
expose MCP atomics, route to FAW HTTP `:8790`, surface results back as
MCP tool responses. **No business logic duplication.**

---

## Current state (flax-mcp side)

Per `flax-mcp/plugins/flax-asset-worker/AGENTS.md` (Phase C8 scaffold,
2026-05-09):

- Plugin namespace: `asset_worker/*` + `manage_asset_worker`
- Intended surface: ASYNC ASSET-IMPORT QUEUING (FBX/OBJ etc.)
- Hard stop: "does NOT reimplement asset import"
- Wraps `FlaxEngine.AssetsImportingManager` + adds a deterministic queue

This scaffold predates Path B. The standalone repo evolved past it.

---

## Proposed facade contract

### Atomics to expose (MCP `tool/list`)

```
asset_worker/list_recipes
  Calls: GET http://localhost:8790/api/v1/recipes/list (NEW endpoint)
  Or:    Reads <FAW>/recipes/<game>/*.yaml directly
  Returns: list[{id, game, recipe_id, pack_count, path}]
  Policy: Safe

asset_worker/pack_from_recipe
  Args: { recipe_path: str, dry_run: bool=false, resume: bool=true,
          skip: list[str]=[], only_required: bool=false }
  Calls: POST http://localhost:8790/api/v1/recipes/run
  Returns: { recipe_id, total_packs, completed, failed, results: [...] }
  Policy: Mutating (intent required)

asset_worker/pack_status
  Args: { pack_id: str, game_scope: str="primitive_tech" }
  Calls: GET http://localhost:8790/api/v1/packs/{pack_id}/status?game={game_scope}
  Returns: full ledger dict (status, current_state, next_step, etc.)
  Policy: Safe

asset_worker/library_search
  Args: { query: str, category: str="" }
  Calls: POST http://localhost:8790/api/v1/library/search
  Returns: list of installed asset metadata
  Policy: Safe

asset_worker/library_install
  Args: { asset_id, provider, category, name }
  Calls: POST http://localhost:8790/api/v1/library/install
  Returns: install result
  Policy: Mutating (intent required)

asset_worker/canary_status
  Calls: Read <FAW>/state/canary/canary_status.json
  Returns: { overall, timestamp, probes: {polyhaven, fab, epic, unity_hub, comfyui} }
  Policy: Safe

manage_asset_worker
  MegaTool dispatching to the atomics above by `action` field
  Actions: list_recipes, pack_from_recipe, pack_status, library_search,
           library_install, canary_status
```

### Why HTTP not subprocess

- FAW's C# `WorkerHttpServer.cs` already listens on `:8790`.
- HTTP is bidirectional: facade can poll status without spawning new processes.
- Subprocess (`python -m assetboy.cli pack from-recipe`) is fine for
  one-shot operations but blocks the MCP session for long runs.

### What the facade does NOT do

- Implement any acquisition logic (lives in standalone).
- Run subprocess to invoke runners directly (HTTP forwarding only).
- Cache results (FAW's library DB is the source of truth).
- Re-implement YAML recipe loading (FAW already has that).

---

## Implementation sketch

`flax-mcp/plugins/flax-asset-worker/src/<package>/Atomics/AssetWorker/AssetWorker.cs`:

```csharp
[Tool("asset_worker", "list_recipes", Description = "...", Policy = Policy.Safe)]
public static ToolResult ListRecipes(ToolContext ctx)
{
    using var http = new HttpClient();
    var resp = http.GetStringAsync("http://localhost:8790/api/v1/recipes/list").Result;
    return ToolResult.Ok(JObject.Parse(resp));
}

[Tool("asset_worker", "pack_from_recipe", Description = "...", Policy = Policy.Mutating)]
public static ToolResult PackFromRecipe(ToolContext ctx)
{
    var recipePath = ctx.Arg<string>("recipe_path");
    var dryRun = ctx.Arg<bool>("dry_run", defaultValue: false);
    var resume = ctx.Arg<bool>("resume", defaultValue: true);

    using var http = new HttpClient();
    var payload = new JObject {
        ["recipe_path"] = recipePath,
        ["dry_run"] = dryRun,
        ["resume"] = resume
    };
    var resp = http.PostAsync(
        "http://localhost:8790/api/v1/recipes/run",
        new StringContent(payload.ToString(), Encoding.UTF8, "application/json")
    ).Result;
    return ToolResult.Ok(JObject.Parse(resp.Content.ReadAsStringAsync().Result));
}
```

Same shape for the rest.

### What FAW HTTP side needs to add

Two new endpoints (Path B v1.5 work, also outside assetboi's commit
authority since the C# server is in the standalone repo's Source/ dir
which I CAN commit to):

```
POST /api/v1/recipes/list
  Returns same shape as `python -m assetboy.cli pack list-recipes --json`

POST /api/v1/recipes/run
  Body: { recipe_path, dry_run, resume, skip, only_required }
  Returns: { recipe_id, total_packs, completed, failed, results: [...] }
  Implementation: subprocess to `python -m assetboy.cli pack from-recipe`
  OR direct call into Python via the existing PythonWorkerClient bridge
```

These are pure C# server work — assetboi can ship them in a v1.5
slice next.

---

## Migration path

### Phase A — additive (no breakage)

1. Lane E broker (or operator) adds the 6 facade atomics to
   `flax-mcp/plugins/flax-asset-worker/src/.../AssetWorker.cs`.
2. They expose new tools alongside the existing Phase C8 scaffold's
   `asset_worker/queue_import` etc.
3. AI clients discover both via `tool/list`; new tools route to FAW :8790.

### Phase B — deprecate scaffold

1. Once the new facade is stable (1-2 weeks), mark the Phase C8
   scaffold's atomics as deprecated.
2. Migrate any callers that were using the old surface.

### Phase C — delete scaffold

1. Delete the Phase C8 in-memory queue (was always a stub anyway).
2. flax-mcp plugin is now purely facade.

### Phase D — submodule bump

1. Operator bumps `flax-mcp/external/flax-asset-worker` submodule pin
   from current `0b1ad7d` (pre-Path-B) to current HEAD on
   `flax-game-studio/flax-asset-worker`.
2. This is the gate that makes the FAW v1.2-v1.4 work actually visible
   in flax-mcp's view.

---

## What assetboi CAN ship in v1.5 (still in this repo)

Two server-side additions assetboi has authority to commit:

### 1. New REST endpoints in `Source/Routes/`

- `Source/Routes/RecipeRoutes.cs` (NEW) — handles `/api/v1/recipes/list`
  and `/api/v1/recipes/run`. Routes through to Python sidecar via
  `PythonWorkerClient` (already exists).
- Update `Source/Core/WorkerHttpServer.cs` to register the new routes.

### 2. Python side: emit `--json` output mode universally

Already done in the Typer CLI (every command has `--json` flag).
Server can subprocess `python -m assetboy.cli pack from-recipe ... --json`
and parse the structured output. No new Python code needed.

---

## Open questions for Lane E broker / operator

1. **Submodule pin bump timing.** flax-mcp's `external/flax-asset-worker`
   currently pins `0b1ad7d` (rescue commit). FAW HEAD is now far ahead
   (multiple v1.2-v1.4 tags). Lane E should bump per `git submodule
   update --remote`. **Recommendation:** do this as a dedicated commit
   so Phase A facade work has the right pinned reference.

2. **Phase C8 scaffold deletion.** The in-memory queue scaffold
   shipped 2026-05-09 was a placeholder. Operator's call whether to
   keep it during Phase A facade rollout (for backward compat) or
   delete immediately (cleaner).

3. **Test surface.** flax-mcp's plugin should add C# unit tests that
   mock the HTTP client + verify facade behavior. Out of assetboi's
   scope (different repo) but worth planning.

---

## Reference: FAW endpoints available today (in this repo)

From `Source/Routes/`:

```
GET  /api/v1/health
POST /api/v1/providers/list
POST /api/v1/providers/{id}/download
POST /api/v1/providers/{id}/search
POST /api/v1/lanes/list
POST /api/v1/lanes/{id}/execute       (only quick-import implemented; inlined in v1.1)
POST /api/v1/library/search
POST /api/v1/library/install
POST /api/v1/library/ready
```

Plus what v1.5 should add:

```
POST /api/v1/recipes/list              (NEW; same as `pack list-recipes --json`)
POST /api/v1/recipes/run               (NEW; same as `pack from-recipe --json`)
GET  /api/v1/packs/{pack_id}/status    (NEW; same as `pack status <pack_id>`)
GET  /api/v1/canary/status             (NEW; reads state/canary/canary_status.json)
```

---

(End of doc — 2026-05-11)
