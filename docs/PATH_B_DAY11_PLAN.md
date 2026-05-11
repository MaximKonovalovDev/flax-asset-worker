# Path B Day 11+ Plan (post-v1.1.0-path-b-cleanup)

> **Date:** 2026-05-10
> **Tag shipped:** `v1.1.0-path-b-cleanup` (commit `2d4bad8`)
> **Follow-up commit:** `aa057a6` (s2.5a cli rename)
> **Author:** assetboi
> **Audience:** future assetboi sessions resuming Path B after Zod-recovery
>             or after operator hibernation; AI brokers needing a
>             read-once continuation map.

This doc replaces "what next?" questions with a written plan. Each
deferred slice below has: trigger, precise scope, file targets, gate
verification, and an estimated subagent budget. Pick the next slice
from this list; do not re-derive from PATH-B-EXECUTION-2026-05-10.md
which is now superseded for follow-up work.

---

## State at end of v1.1.0-path-b-cleanup turn

**11 commits + 1 tag pushed, all gates green.**

| Slice | Commit | Net change |
|---|---|---|
| s0 rescue | `0b1ad7d` | 55 tests + scripts/profiles/skills imported |
| s1 | `16fc55d` | +419 lines canary.py; +581 lines test_canary |
| s2 | `a7fb86c` | +16 YAML data parks; -79 lines tts_runner |
| s3 | `7b30892` | +454 lines quixel_scanner; -340 lines library_map |
| s4 | `fb2117f` | +30 lines AcquisitionMethod alias |
| s5 | `8d2f16d` | +1019 lines cli/{fab,library,import,app} |
| s6 | `00760fc` | +807 lines cli/{unity,epic,gen} |
| s7 | `4b74e7f` | +190 lines pack_pipeline Stage dispatch shim |
| s8 | `fbb23ba` | +780 lines primitive_tech recipe + pack CLI |
| s9 | `0181202` | +800 lines roman_arena recipe (14 packs) |
| s10 | `2d4bad8` | +400 lines README+ROADMAP+inlined LaneRoutes; -250 lines ILane+LaneExecutor+lanes.json |
| s2.5a | `aa057a6` | rename cli.py->cli_legacy.py + 4 test imports |

**Total:** +6,118 lines added / -669 lines deleted across 9 days
of focused refactor. 26/26 canary tests stable throughout.

**Test suite reachable today (post-s2.5a rename):**
- canary: 26 tests green
- test_publish_filters: 2 tests collect (was: red)
- test_generator_emit: 4 tests collect (was: red)
- test_cli_parser_commands: 47 tests collect (was: red)
- 5 others (test_gate_report etc): still red for unrelated `tests.helpers` issue (pre-existing)

**Outstanding inventory** (the 21 DEAD files + cli_legacy.py + 6 KEEP-rewires):
- 5 DEAD workflows: `roman_first_playable.py`, `roman_blockers.py`, `roman_launchers.py`, `roman_source_presets.py`, `pack_family_plan.py` (+ `flax_wrapper.py`, `execution_kit.py`, `audio_examples.py`, `category_examples.py`, `cleanup_examples.py` per peer-opus)
- 10 DEAD execution runners: `animationgpt`, `colab`, `dialogue`, `music`, `vehicle`, `vfx`, `museum`, `font`, `game_icons`, `quaternius`, `playwright_runner`
- 5 DEAD providers: `ai_bridge`, `generator`, `engine_bridge`, `extractor_bridge`, `runbooks`
- `cli_legacy.py` (8500 lines)
- 6 KEEP files needing rewire: `provider_readiness.py`, `library_map.py`, `epic_vault.py`, `unity_runner.py`, `unreal_runner.py`, `browser_automation.py`, `freesound_runner.py`, `pack_pipeline.py`

---

## s2.5b — Strip cli_legacy.py DEAD imports + neuter handlers

**Trigger:** s2.5a renamed `cli.py` to `cli_legacy.py`; nothing dynamically
imports from it via `assetboy.cli` anymore. Now safe to gut DEAD references
inside cli_legacy.py without breaking anything that works today. After this,
cli_legacy.py is just a self-contained-but-unreachable file — no longer
ratcheting any DEAD module alive.

**Precise scope (from peer-opus s2 import-trace):**

### 7 eager imports at top of cli_legacy.py (REMOVE)

```python
Line  41: from assetboy.providers.ai_bridge import AI_PROVIDER_PROFILES, emit_ai_bridge_job
Line  56: from assetboy.providers.engine_bridge import EngineBridgeKind, emit_engine_export_job
Line  78: from assetboy.providers.extractor_bridge import ExtractorTool, emit_extractor_job
Line  79: from assetboy.providers.generator import emit_generator_setup
Line 107: from assetboy.providers.runbooks import build_provider_runbook_payload, provider_runbook_ids, render_provider_runbook
Line 138: from assetboy.workflows.roman_blockers import format_planned_blockers, plan_roman_blockers, write_plan_outputs
Line 139: from assetboy.workflows.roman_first_playable import get_roman_pack_spec
Line 131: from assetboy.workflows.flax_wrapper import (SUPPORTED_BULK_PROFILES, execute_register_packet, execute_run_bulk, execute_run_cleanup, ...)
```

### 26 lazy imports inside command handlers (REMOVE + neuter handlers)

```python
Line 2153: from assetboy.providers.generator import profile_ids
Line 2197: from assetboy.execution.colab_runner import submit_batch_to_colab
Line 2199: from assetboy.execution.playwright_runner import run_browser_job, run_mixamo_batch
Line 2201: from assetboy.providers.generator import emit_generator_setup
Line 2791: from assetboy.workflows.roman_launchers import emit_roman_launcher_manifest
Line 2806: from assetboy.workflows.roman_source_presets import emit_roman_source_presets
Line 3721: from assetboy.workflows.pack_family_plan import emit_pack_family_plan
Line 3958: from assetboy.execution.playwright_runner import run_browser_job
Line 5779: from assetboy.execution.playwright_runner import _augment_browser_metadata_from_page_text, _extract_unity_asset_id
Line 6597: from assetboy.execution.playwright_runner import run_browser_job
Line 7732: from assetboy.providers.generator import emit_generator_setup
Line 7733: from assetboy.execution.colab_runner import submit_batch_to_colab
Line 7756: from assetboy.execution.colab_runner import submit_batch_to_colab
Line 7773: from assetboy.execution.playwright_runner import run_browser_job
Line 7953: from assetboy.execution.playwright_runner import run_mixamo_batch
Line 8002: from assetboy.execution.music_runner import run_music_batch
Line 8049: from assetboy.execution.quaternius_runner import (...)
Line 8220: from assetboy.execution.game_icons_runner import (...)
Line 8240: from assetboy.execution.font_runner import (...)
Line 8271: from assetboy.execution.vfx_runner import (...)
Line 8306: from assetboy.execution.animationgpt_runner import (...)
Line 8325: from assetboy.execution.museum_runner import (...)
Line 8343: from assetboy.execution.vehicle_runner import (...)
Line 8398: from assetboy.execution.dialogue_runner import run_dialogue_line
Line 8427: from assetboy.execution.dialogue_runner import (...)
```

### Strategy (Rule 2 thrash-avoidance)

**Do NOT** edit cli_legacy.py 30+ times in this slice. Instead:

1. **One subagent call (peer-opus or perplexity-flash):** ask for a single
   structured Python patch script that does all 33 import strips + handler
   neuters in one pass. Output should be a `_temp/strip_dead_imports.py`
   that:
   - Opens cli_legacy.py
   - For each of the 33 import lines: comment them out as `# DEAD-IMPORT: from ...` (preserves provenance)
   - For each handler block (`if args.command == "<dead-cmd>": ... return 1`): replace body with `if args.command == "<dead-cmd>": print("dead_command={cmd}"); return 1`
   - Writes the new file
2. **One Edit/Write to apply the script's output to cli_legacy.py.**
3. **Verify:** `python -c "import assetboy.cli_legacy"` succeeds (no DEAD-imports left to fail import).
4. Commit + push.

**Estimated effort:** 1 subagent call + 1 file write + 1 commit. ≤30 min.

**Gate verification:**
- `import assetboy.cli_legacy` succeeds.
- 26 canary tests still green.
- 3 collect-able cli-importing tests still green (test_publish_filters, test_generator_emit, test_cli_parser_commands).

---

## s2.6 — Rewire 6 KEEP files + delete 21 DEAD files

**Trigger:** s2.5b complete. cli_legacy.py no longer holds DEAD-module
references alive. The remaining blockers are 6 KEEP-list provider/workflow
files that import from DEAD modules.

**Precise scope (peer-opus s2 verdict matrix):**

### KEEP-file rewires (6 files, ~50 LOC each)

| KEEP file | DEAD dep to drop | Strategy |
|---|---|---|
| `providers/provider_readiness.py` | `ai_bridge`, `generator`, `runbooks` | Load `AI_PROVIDER_PROFILES` from `data/provider_profiles.yaml` (parked in s2). Inline `profile_ids` constant. Delete runbook reference (no real users). |
| `providers/library_map.py` | `extractor_bridge` (`ExtractorTool`, `emit_extractor_job`) | Inline `emit_extractor_job` helper into library_map (it's ~30 LOC). |
| `providers/epic_vault.py` | `extractor_bridge` (same) | Same inline. |
| `providers/unity_runner.py` | `engine_bridge` (`emit_engine_export_job`) | Inline ~30 LOC helper. |
| `providers/unreal_runner.py` | `engine_bridge` (same) | Same inline. |
| `providers/browser_automation.py` | `playwright_runner` (lazy `build_structured_playwright_steps`) | Inline OR delete that helper if no real users. |
| `execution/freesound_runner.py` | `playwright_runner` (lazy `run_browser_job`) | Stub: replace lazy import with `raise NotImplementedError("freesound browser flow disabled in v1.1+; use direct API")`. |
| `workflows/pack_pipeline.py` | `flax_wrapper` (import block lines 19-24) | Inline only the 4 names actually used: `SUPPORTED_BULK_PROFILES`, `execute_register_packet`, `execute_run_bulk`, `execute_run_cleanup`. flax_wrapper itself goes to DEAD-set; the 4 functions either inline into pack_pipeline (small) or split into their own files. |

### DEAD-file deletes (21 files, sequential)

After all KEEP rewires verify (one canary run + targeted import-check), delete:

**Workflows (5 + 5 added by peer-opus = 10):**
- `workflows/roman_first_playable.py` (data already in `data/roman_first_playable_specs.yaml`)
- `workflows/roman_blockers.py`
- `workflows/roman_launchers.py`
- `workflows/roman_source_presets.py`
- `workflows/pack_family_plan.py` (data in `data/pack_family_plan_data.yaml`)
- `workflows/flax_wrapper.py` (10 DEAD-runner imports neutralized)
- `workflows/execution_kit.py`
- `workflows/audio_examples.py`
- `workflows/category_examples.py`
- `workflows/cleanup_examples.py`

**Execution runners (10):**
- `execution/animationgpt_runner.py` (data in `data/animationgpt_presets.yaml`)
- `execution/colab_runner.py` (data in `data/colab_pipelines.yaml`)
- `execution/dialogue_runner.py` (data in `data/dialogue_presets.yaml`)
- `execution/music_runner.py` (data in `data/music_presets.yaml`)
- `execution/vehicle_runner.py` (data in `data/vehicle_presets.yaml`)
- `execution/vfx_runner.py` (data in `data/vfx_presets.yaml`)
- `execution/museum_runner.py` (data in `data/museum_presets.yaml`)
- `execution/font_runner.py` (data in `data/font_presets.yaml`)
- `execution/game_icons_runner.py` (data in `data/game_icons_presets.yaml`)
- `execution/quaternius_runner.py` (data in `data/quaternius_presets.yaml`)
- `execution/playwright_runner.py` (data in `data/playwright_presets.yaml`)

**Providers (5):**
- `providers/ai_bridge.py` (data in `data/provider_profiles.yaml`)
- `providers/generator.py`
- `providers/engine_bridge.py` (data in `data/provider_profiles.yaml`)
- `providers/extractor_bridge.py` (data in `data/provider_profiles.yaml`)
- `providers/runbooks.py` (data in `data/provider_profiles.yaml`)

### Strategy

s2.6 is too big for one slice. Split into:

- **s2.6a:** rewire `provider_readiness.py`, `library_map.py`, `epic_vault.py`. One peer-opus call to produce 3-file patch plan. Two Write calls + canary run. Commit.
- **s2.6b:** rewire `unity_runner.py`, `unreal_runner.py`, `browser_automation.py`, `freesound_runner.py`. Same shape.
- **s2.6c:** rewire `pack_pipeline.py` flax_wrapper dep. Delete `flax_wrapper.py` + `execution_kit.py`. Canary run.
- **s2.6d:** delete the 10 execution runners + 4 roman_* workflows + 5 DEAD providers. Bulk Remove-Item operations; one canary run after; one commit.

**Estimated effort:** 4 slices × ≤2hr each = ~8hr total. Spread across 1-2 days.

---

## s10.5 — Mechanical pack_pipeline body extraction + delete cli_legacy.py

**Trigger:** s2.6 complete; cli_legacy.py is the only DEAD-import holder
left; pack_pipeline.py's flax_wrapper dep is resolved.

**Scope (per peer-opus s7 refactor map):**

1. Extract `execute_prepare_pack` body (lines 60-286 of current
   pack_pipeline.py) into 5 stage handler functions:
   - `_stage_bulk_source(state, ctx) -> StageResult`
   - `_stage_source_summary(state, ctx) -> StageResult`
   - `_stage_cleanup(state, ctx) -> StageResult`
   - `_stage_reviewed_source(state, ctx) -> StageResult` (canonical-glTF inline)
   - `_stage_register_packet(state, ctx) -> StageResult`
2. Populate `STAGE_HANDLERS` dict (was empty placeholder in s7).
3. Rewrite `execute_prepare_pack` body to call the new dispatch loop.
4. Add 3 new tests per peer-opus risk list:
   - `test_v1_ledger_load_roundtrip`
   - `test_cleanup_pause_called_once`
   - `test_degraded_canonicalization_still_publishes`
5. Run full pytest. Must keep:
   - All 10 existing `test_pack_pipeline.py` tests green
   - 3 new tests green
   - 26 canary tests green
6. Delete `cli_legacy.py` (now self-contained, no external imports left).
7. Tag `v1.1.1-pack-pipeline-clean`.

**Estimated effort:** 1 day of careful work. Highest-risk slice in the
follow-up backlog because of the 9 subtle behaviors peer-opus catalogued.

---

## s11 — Pre-pack acquisition router

**Trigger:** s10.5 complete. Pack pipeline is clean. Now wire real
acquisition.

**Scope:** new module `Python/assetboy/workflows/acquisition_router.py`:

```python
def acquire_source_dir(pack: dict, recipe: dict) -> Path:
    """Map a recipe pack to a source_dir before pack_pipeline runs.

    Reads pack["acquisition_method"]:
      - direct_url       -> call provider runner (polyhaven/kenney/ambientcg/freesound)
      - manual_browser   -> emit a wait-marker file + open browser if available
      - generator        -> route to comfyui_runner or local_image_runner or stable_audio
      
    Returns the path the operator should pass as source_dir to
    execute_prepare_pack_dispatched.
    """
```

CLI integration in `cli/pack.py:from_recipe_cmd`:
```python
ctx = PipelineContext(...)
ctx.source_dir = acquire_source_dir(pack, recipe)  # NEW
result = execute_prepare_pack_dispatched(ctx)
```

After s11 lands, `python -m assetboy.cli pack from-recipe primitive_tech/first_playable.yaml` no longer goes RED on every pack — direct_url packs (PolyHaven, Kenney, AmbientCG, FreeSound) actually download; manual_browser packs (Fab, Mixamo, Unity, Epic) emit a wait-marker the operator drops files into; generator packs (Stable Audio Open, ComfyUI) actually run.

**Estimated effort:** 1 day.

---

## v1.6 backlog (post-v1.5.5 — operator approved 2026-05-11)

5 candidate slices, ranked by ROI:

### v1.6.s1 — `pack from-yaml-string` CLI command (~2 hr)

**Trigger:** flax-mcp facade needs to send recipe content inline (over HTTP)
rather than depending on the recipe file being on the FAW server's disk.

**Scope:**
- Add `--inline-yaml <yaml_text>` flag to `pack from-recipe` (or new sub-command).
- Alternatively: read recipe YAML from stdin when `recipe_path` is `-`.
- Server-side `RecipeRoutes.HandleRunAsync` already accepts `recipe_path`;
  add support for `recipe_yaml_text` field in the JSON body.

**Tests:** 3-4 (inline YAML, stdin YAML, malformed YAML error, large YAML).

**Status:** PENDING.

### v1.6.s2 — `GET /api/v1/library/asset/{id}` single-asset metadata (~2 hr)

**Trigger:** facade needs to inspect one asset's full metadata (license, provenance, file paths) — current routes only support substring search + full dump.

**Scope:**
- New C# route handler `LibraryRoutes.HandleGetAssetAsync(asset_id)`.
- Routes `GET /api/v1/library/asset/{asset_id}` → reads from asset library DB.
- Returns 404 with clean error when asset_id not found.

**Tests:** 3-4 (real asset lookup, unknown id, malformed id).

**Status:** PENDING.

### v1.6.s3 — `GET /api/v1/packs/audit` ledger inventory (~2 hr)

**Trigger:** monorepo facade dashboard needs "show me all pack runs across all games."

**Scope:**
- New C# route handler `RecipeRoutes.HandleAuditAsync()`.
- Walks `state/pack_pipeline/*.json` ledgers, aggregates by (game_scope, status).
- Returns `{games: {primitive_tech: {total: 9, completed: 3, failed: 6, pending: 0}, ...}, total: N}`.

**Tests:** 3-4 (empty state dir, mixed ledgers, malformed ledger handled gracefully).

**Status:** PENDING.

### v1.6.s4 — Quaternius + OpenGameArt direct_url providers (~3-4 hr)

**Trigger:** the direct_url lane currently only has 4 CC0 providers. Quaternius (low-poly models) and OpenGameArt (mixed-license catalog) are useful additions.

**Scope:**
- New `providers/quaternius_provider.py` + `providers/oga_provider.py` (or C# equivalents).
- Wire into `acquisition_router._acquire_direct_url`.
- License manifest: Quaternius CC0; OGA per-asset (filter at intake).

**Tests:** 4-6 (per-provider download path + license filter).

**Risks:** OGA has scrape-only catalog (no clean REST); needs HTML parsing.

**Status:** PENDING.

### v1.6.s5 — Recipe schema validator ✅ SHIPPED 2026-05-11 v1.6.0

### v1.6.s1 — pack from-recipe inline-yaml ✅ SHIPPED 2026-05-11 v1.6.1

### v1.6.s3 — pack audit endpoint ✅ SHIPPED 2026-05-11 v1.6.2

### v1.6.s2 — single-asset lookup ✅ SHIPPED 2026-05-11 v1.6.3

### v1.6.s6 — pack run-pack single-pack execution ✅ SHIPPED 2026-05-11 v1.6.5

### v1.6.s7 — POST /api/v1/packs/run-pack ✅ SHIPPED 2026-05-11 v1.6.6

### v1.6.s8 — pack rerun-failed ✅ SHIPPED 2026-05-11 v1.6.7

### v1.6.s9 — Pin EXPECTED_EPIC_SCHEMA_VERSION ✅ SHIPPED 2026-05-11 v1.6.8

---

## v1.7 backlog (s11-s15) — written 2026-05-11

5 more candidate slices, ranked by ROI:

### v1.7.s11 — `manage_asset_worker` mega-tool atomics map doc (~1 hr)

**Trigger:** `MONOREPO_FACADE_DESIGN.md` lists 6 MCP atomics + 1 mega-tool. The mega-tool's action -> atomic dispatch table is implicit. Make it explicit so the Lane E broker can copy-paste the wiring.

**Scope:** new `docs/MEGA_TOOL_DISPATCH.md` with the canonical action enum + per-action argument shape + per-action target atomic + per-action policy class (Safe / Mutating / Destructive).

**Tests:** N/A (doc-only).

**Status:** PENDING.

### v1.7.s12 — `canary --since` flag + history pruning (~2 hr)

**Trigger:** `state/canary/canary_*.json` history accumulates one file per run. Operator running weekly canary for a year = 52 files. Add `--since <iso_date>` to list recent runs + `--prune <N>` to keep only the last N history files.

**Scope:**
- `canary.py`: new `--list-history`, `--since`, `--prune` flags.
- New CLI sub-command `python -m assetboy.canary history --prune 50`.

**Tests:** 3-4 (history file emit, since filter, prune cap).

**Status:** PENDING.

### v1.7.s13 — `provider readiness` CLI command (~2 hr)

**Trigger:** Path B has `providers/provider_readiness.py` with `build_provider_readiness_report()` (KEEP, rewired in s2.6a) but no CLI surface. Add `python -m assetboy.cli library readiness` (under library sub-app) so operators can quickly see "what's set up vs missing" without writing Python.

**Scope:**
- `cli/library.py`: new `readiness` command.
- `--json` + per-provider summary in human mode.

**Tests:** 2-3 (smoke, --json shape).

**Status:** PENDING.

### v1.7.s14 — Recipe diff command (~3 hr)

**Trigger:** When operators iterate on recipes (e.g. add 3 packs, change provider on 2), git diff shows raw YAML changes but not "what packs are new / removed / changed shape." A semantic diff helps.

**Scope:**
- New `workflows/recipe_diff.py`: `diff_recipes(old_doc, new_doc) -> DiffResult` with `added_packs`, `removed_packs`, `modified_packs` (per-field change list).
- `cli/pack.py`: new `pack diff <old.yaml> <new.yaml>` command.

**Tests:** 5-6 (added/removed/modified cases).

**Status:** PENDING.

### v1.7.s15 — Quaternius direct_url provider (the s4 carve-out) (~3 hr)

**Trigger:** v1.6.s4 was "Quaternius + OGA"; the OGA half is complex (HTML scraping + per-asset license parsing). Ship Quaternius alone — CC0, predictable ZIP URLs, similar pattern to Kenney.

**Scope:**
- `execution/quaternius_runner.py` (REVIVE — was DEAD in s2.6d, but a clean rewrite is doable now): ZIP download + extract.
- `acquisition_router._drive_quaternius` handler.
- Wire into `DIRECT_URL_PROVIDERS` whitelist in recipe_validator.

**Tests:** 4-5 (download URL resolution, ZIP extract, invalid pack_id, license manifest).

**Status:** PENDING.



`Python/assetboy/workflows/recipe_validator.py` + `pack validate` CLI command.
Lints recipe YAML against the v1 schema. 27 tests + integration tests against all 4 shipped recipes. Caught 16 legitimate warnings in primitive_tech + roman recipes (Mixamo packs missing `source_url`).

Commit: TBD this slice. Test suite: 242 → 269.

## Resumption protocol

Future assetboi turns reading this doc:

1. **Read this doc + `COMMIT_READY-assetboi.md` first.** They are the
   ground truth for "where Path B is right now."
2. Pick the next slice from the order: s2.5b -> s2.6a -> s2.6b -> s2.6c -> s2.6d -> s10.5 -> s11.
3. Do not re-derive from `docs/research/PATH-B-EXECUTION-2026-05-10.md`
   for follow-up slices; that doc is the v1.1.0 plan, not the follow-up plan.
4. Each slice: COMMIT_READY append via Edit (Rule 7) + commit per FAW etiquette (path-explicit, never `-A`).
5. If a slice grows past Rule 2 (3+ edits to same file), STOP and use peer-opus
   for a single batched fix-plan first.

(End of document — 2026-05-10.)
