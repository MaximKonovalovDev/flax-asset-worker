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

### v1.7.s15 — Quaternius direct_url provider ✅ SHIPPED 2026-05-11 v1.7.3

### v1.7.s11 — MEGA_TOOL_DISPATCH.md ✅ SHIPPED 2026-05-11
### v1.7.s12 — canary history management ✅ SHIPPED 2026-05-11 v1.7.2
### v1.7.s13 — library readiness CLI ✅ SHIPPED 2026-05-11 v1.7.0
### v1.7.s14 — pack diff command ✅ SHIPPED 2026-05-11 v1.7.1

---

## v1.8 backlog (s16-s20) — written 2026-05-11

All 5 v1.7 slices done. 5 more candidates queued:

### v1.8.s16 — `library bulk-install` from manifest (~2 hr)

**Trigger:** operators installing 20+ assets at once shouldn't fire 20 separate `library install` calls. A bulk-install command takes a YAML/JSON manifest and runs them in a batch with per-asset success/fail reporting.

**Scope:**
- `cli/library.py`: new `library bulk-install <manifest>` command.
- Manifest schema: `[{asset_id, provider, category, name}, ...]`.
- Per-asset error isolation: one failure doesn't abort the batch.
- `--json` summary `{total, succeeded, failed, results: [...]}`.

**Tests:** 4-5 (manifest load, partial-failure, all-success, malformed).

**Status:** PENDING.

### v1.8.s17 — `pack export-summary` for shareable status reports (~2 hr)

**Trigger:** operators sharing pack state with collaborators (or AI agents inspecting) want a single condensed report — not 9 separate ledger files. Generate a markdown summary of a recipe's current state.

**Scope:**
- New `workflows/pack_summary.py`: `render_pack_summary(recipe_doc) -> str` returns markdown.
- `cli/pack.py`: new `pack export-summary <recipe>` command.
- Output sections: per-pack status table, missing-source-dir list, manual-drop instructions, retry suggestions.

**Tests:** 3-5.

**Status:** PENDING.

### v1.8.s18 — `gen status-all` aggregate generator availability (~1 hr)

**Trigger:** `gen comfyui status` exists but operators want one-shot "are any of my generators ready?" across all 3 (ComfyUI, sd.cpp, Stable Audio).

**Scope:**
- `cli/gen.py`: new `status-all` command at the gen level (not nested).
- Probes each generator via existing `is_*_available()` helpers + reports status table.

**Tests:** 2-3.

**Status:** PENDING.

### v1.8.s19 — `pack validate-all` batch validator (~1 hr)

**Trigger:** `pack validate <one.yaml>` exists; CI/operator wants `pack validate-all` walking the entire `recipes/` tree.

**Scope:**
- `cli/pack.py`: new `validate-all` command (no positional arg; walks `recipes/`).
- Per-recipe summary + aggregate counters.
- Exit 1 if any recipe has errors.

**Tests:** 3.

**Status:** PENDING.

### v1.8.s16 — library bulk-install ✅ SHIPPED 2026-05-11 v1.8.4
### v1.8.s17 — pack export-summary ✅ SHIPPED 2026-05-11 v1.8.3
### v1.8.s18 — gen status-all ✅ SHIPPED 2026-05-11 v1.8.0
### v1.8.s19 — pack validate-all ✅ SHIPPED 2026-05-11 v1.8.1
### v1.8.s20 — polyhaven_category override ✅ SHIPPED 2026-05-11 v1.8.2

---

## v1.9 backlog (s21-s25) — written 2026-05-11

All 5 v1.8 slices shipped. 5 more candidates queued:

### v1.9.s21 — `pack from-recipe --only <pack_id>` (~1 hr)

**Trigger:** v1.6.s1 added inline-yaml + stdin; v1.6.s3 added audit; v1.6.s8 added rerun-failed. Missing primitive: run ONE specific pack from a multi-pack recipe by id. Use case: "I just want to retry SHARED_MIXAMO_CHR_PLAYER after fixing mixamo auth — not the other 8 packs."

**Scope:**
- `cli/pack.py:from_recipe_cmd`: add `--only <pack_id>` flag (repeatable).
- Filters `packs[]` to just the named ids before the existing loop.
- Mutually compatible with `--skip` (skip wins on overlap).

**Tests:** 3 (single --only, multi --only, --only + --skip overlap).

**Status:** PENDING.

### v1.9.s22 — `library export` snapshot CLI (~2 hr)

**Trigger:** operator wants to share "here's what's in my library right now" — but there's no atomic snapshot. Walk the C# server's `/library/ready`, dump to a portable JSON/YAML manifest.

**Scope:**
- `cli/library.py`: new `library export <out_path>` command.
- Writes manifest in same shape as `bulk-install` accepts (round-trip).
- `--include-checksums` flag adds sha256 per asset for verification.

**Tests:** 3-4.

**Status:** PENDING.

### v1.9.s23 — `canary --probe <name> --json --exit-zero` for CI hooks (~1 hr)

**Trigger:** canary currently exits 1 on any RED probe — useful locally but bad for CI hooks that want JSON output regardless. Add `--exit-zero` flag.

**Scope:**
- `canary.py`: new `--exit-zero` flag forces exit 0 regardless of probe result.
- Doesn't change JSON shape; just decouples shell exit from probe outcome.

**Tests:** 2 (green path, red path; both exit 0 with --exit-zero).

**Status:** PENDING.

### v1.9.s24 — Recipe linter: auto-fix common warnings (~3 hr)

**Trigger:** `pack validate` emits warnings (especially Mixamo packs missing source_url). Operator iterates: validate -> see warning -> edit YAML -> re-validate. An auto-fix mode would write a sane source_url default for common cases.

**Scope:**
- `workflows/recipe_validator.py`: new `auto_fix_warnings(doc)` function returning a corrected doc + list of fixes applied.
- `cli/pack.py`: `pack validate --fix --out <path>` writes the fixed YAML.
- Auto-fixes: Mixamo packs get `source_url: https://www.mixamo.com/`, missing license blocks get inferred defaults from provider, etc.

**Tests:** 5-6.

**Status:** PENDING.

### v1.9.s25 — `gen comfyui submit-workflow` for arbitrary ComfyUI JSON workflows (~3 hr)

**Trigger:** v1.6.s5 added recipe input_image support; operators still need a primitive to run a fully-custom ComfyUI workflow JSON (e.g. ControlNet pose, IP-Adapter style transfer) outside the recipe flow.

**Scope:**
- `cli/gen.py:comfy_app`: new `submit-workflow <workflow.json>` command.
- Reads workflow JSON, POSTs to `:8188/prompt`, polls `:8188/history/{prompt_id}`, downloads output files.
- `--params key=value` flag for parameterizing the workflow (substitutes into known node fields).

**Tests:** 3-4 (with mock ComfyUI).

**Status:** PENDING.



**Trigger:** acquisition_router `_drive_polyhaven` infers category from `asset_kind` — but operators sometimes want explicit override (e.g. an asset_kind "model" pack that actually downloads an HDRI environment).

**Scope:**
- Recipe schema: optional `polyhaven_category: textures|models|hdris` per pack.
- `_drive_polyhaven`: honor the override if set; else infer.

**Tests:** 2.

**Status:** PENDING.



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

---

## v1.13+ backlog (added 2026-05-12, s89)

Five fresh slice ideas for the next round of the never-stop loop:

- **s90 — `library r1a-status` ASCII bar chart**: when run with `--bars`,
  render a per-provider downloaded-bytes ASCII bar so operator sees
  proportional disk usage across providers in one glance.

- **s91 — Open Library API integration**: openlibrary.org has a public
  JSON API for ~30M books with cover images (CC0-licensed metadata,
  cover images mostly fair-use thumbnails). Useful for bookshelf
  reference plates / RPG library scenes. No API key. Mirror the
  inaturalist pattern.

- **s92 — `pack manifest-stats --since <iso8601>`** filter: limit
  aggregation to manifests with mtime newer than the supplied
  timestamp. Operator can ask "how much did I scout this week?".

- **s93 — recipe pack `tier` field**: optional pack-level int in
  {0, 1, 2, 3} mapping to P0/P1/P2/P3 priority. Validator accepts
  it; `pack list-recipes --filter tier:0` finds critical-only packs.
  Auto-fix tags packs without tier as `tier: 2` default.

- **s94 — `gen scout-by-license <license>`**: query all configured
  providers but only those whose license string contains the requested
  token (e.g. `cc0` returns Met + Pixabay + Iconify-CC0-sets +
  iNaturalist-CC0-subset). Wraps gen list-providers + per-provider
  fetch with a license filter on the result. Single-line operator
  command for "I need strictly CC0 images for shipping art."

Ship order: s90, s91, s92, s93, s94. Each per Rule 2 (max 2 edits
per file). Maintain green tests + tag per slice.

---

## v1.14+ backlog (added 2026-05-12, s95)

All v1.13+ slices (s90..s94) SHIPPED. Five fresh ideas for the next round:

- **s96 — `gen scout-by-license` reuse in HTTP**: POST
  `/api/v1/library/scout-by-license` accepting body
  `{"license": "cc0", "query": "...", "count": 2}` so C# clients
  can invoke license-filtered fan-out without subprocess from their
  own process. Mirror v1.12.s73 (manifest/stats) pattern.

- **s97 — provider-readiness HTML report**: `library r1a-status
  --html <path>` writes a standalone HTML file with the bar chart
  rendered as actual CSS bars + per-provider env_set / live_ok
  status. Operator can open in browser instead of reading stdout.

- **s98 — recipe `priority` view**: `pack list-recipes
  --filter min-tier:0` lists recipes whose any pack has tier<=N.
  Combined with v1.11.15 metadata filter for genre/tags etc.
  Needs validator + list-recipes update (one slice).

- **s99 — provider-aware retry budget**: extend
  `_http_retry.with_429_retry` to honor a per-runtime budget
  (env var `FAW_HTTP_RETRY_BUDGET=N`, default 10/min/provider).
  Once exhausted, subsequent 429s pass through immediately to
  avoid hammering rate-limited APIs.

- **s100 — milestone tag v1.14-WAVE-COMPLETE**: capstone tag plus
  HEARTBEAT/RELEASE_NOTES refresh once s96..s99 ship. Symbolic
  150-commit milestone (we're at 149 as of v1.13.12).

Ship order: s96, s97, s98, s99, s100.

---

## v1.14+ backlog (added 2026-05-12, s101)

All v1.14+ s96..s100 SHIPPED. Five fresh ideas:

- **s102 — scout-by-license HTTP test coverage**: pytest-level smoke
  test invoking the C# subprocess wrapper via the python CLI directly
  (since the C# server isn't running in pytest). Verify the JSON shape
  C# parses matches what the runner emits.

- **s103 — `library install-r1a-pack <pack_id>` CLI**: take an entry
  from a manifest file and copy its `local_path` file(s) into the
  Library/ directory, registering them in asset_library.json. Bridges
  R1A scouting -> long-term project library.

- **s104 — canary R1A probe rotation**: extend Python/assetboy/canary.py
  with a 6th probe that calls one R1A provider per run on rotation
  (Met -> Wikimedia -> Archive.org -> ...). Keeps R1A health visible
  to the weekly canary without adding 10 simultaneous probes.

- **s105 — recipe ordering by tier**: `pack list-recipes --sort tier`
  returns recipes ordered by min-tier across their packs (most
  critical first). Helps operator prioritize.

- **s106 — provider-health JSON endpoint**: `/api/v1/library/health`
  combines library r1a-status --check-live (live probes) + the C#-
  native ProviderRegistry health into a unified health report.

Ship order: s102, s103, s104, s105, s106.

---

## v1.15+ backlog (added 2026-05-12, s107)

All v1.14+ s102..s106 SHIPPED. Five fresh ideas:

- **s108 — `gen all-no-key --since-history`**: track each fan-out
  run's per-provider results in `state/r1a_history/<date>.json`.
  Operator can later `pack manifest-stats --since-history` to see
  trend lines. Minimal: write file alongside the existing manifests.

- **s109 — recipe-aware `library install-r1a-pack` mode**: when
  passed `--recipe <yaml>`, automatically resolve which packs in
  the recipe correspond to known R1A manifests on disk and install
  them all in one shot (vs one manifest per call).

- **s110 — provider `polite_sleep_s` override env var**: each runner
  hardcodes a polite sleep (200-500ms). Add `FAW_POLITE_SLEEP_S=0.05`
  to globally tune. Useful for local-cache scenarios with no rate-
  limit concern.

- **s111 — Iconify icon-set browser**: `gen iconify list-sets`
  shows the 150+ icon sets with their SPDX license. Operator can
  browse before queries. Iconify's `/collections` endpoint
  (already used internally) becomes a first-class CLI surface.

- **s112 — milestone v1.14-WAVE-COMPLETE tag** + HEARTBEAT/RELEASE
  notes refresh once s108..s111 ship.

Ship order: s108, s109, s110, s111, s112.

---

## v1.16+ backlog (added 2026-05-12, s113)

All v1.15+ s108..s111 + s112 milestone SHIPPED. Five fresh ideas:

- **s114 — apply FAW_POLITE_SLEEP_S sweep to all 12 R1A runners**:
  v1.15.s110 shipped the helper; now wire `get_polite_sleep_s(...)`
  into each runner's existing `time.sleep(polite_sleep_s)` call.
  Touches 12 files lightly; one slice with peer-opus delegation if
  it grows.

- **s115 — `gen all-no-key --write-history` enriched manifest**:
  include parallel flag, wall time, and command line that produced
  each snapshot. Useful for reproducibility.

- **s116 — `pack manifest-stats --history`**: a dual mode that
  reads `state/r1a_history/*.json` snapshots instead of disk
  manifests. Operator sees "what scouts ran across providers
  over time" rather than "what files are on disk now".

- **s117 — Iconify icon-set badge in fetch output**: when an icon
  is downloaded, the manifest entry already has its SPDX. Surface
  `attribution_required` per icon in stdout output of `gen iconify
  fetch` (currently only manifest captures it).

- **s118 — `library r1a-status --html --open`**: convenience flag
  that calls `os.startfile()` on Windows / `open` on macOS to
  auto-open the generated HTML in the system browser.

Ship order: s114, s115, s116, s117, s118.

---

## v1.17+ backlog (added 2026-05-12, s119)

All v1.16+ s114..s118 SHIPPED. Five fresh ideas:

- **s120 — `gen all-key --write-history`**: mirror v1.15.s108's
  history snapshot for the keyed fan-out. Same shape but kind=
  'all_key'. Then v1.16.s116's --history mode aggregates both
  natively (since it groups by kind).

- **s121 — `pack list-recipes --sort path` explicit + `pack
  list-recipes --reverse`**: explicit sort key + reversal flag.
  Useful with --sort tier --reverse (least-critical first).

- **s122 — `gen scout-by-license` parallel mode**: like
  all-no-key/all-key. The scout-by-license loop is currently
  sequential. ThreadPoolExecutor speed-up applies.

- **s123 — recipe `output_folder` validation**: validator catches
  recipes whose `output_folder` contains illegal path chars or
  starts with absolute path on non-Windows. Soft warning, not error.

- **s124 — milestone v1.16-WAVE-COMPLETE + 750-test stretch**:
  capstone tag once s120..s123 ship. Approach 750 tests.

Ship order: s120, s121, s122, s123, s124.

---

## v1.18+ backlog (added 2026-05-12, s125)

All v1.17+ s120..s124 SHIPPED. Five fresh ideas:

- **s126 — `library install-r1a-pack --recipe` actually copies**:
  s109 enumerates+validates only. Extend to actually invoke the
  per-manifest install path for each resolved manifest.

- **s127 — `pack manifest-stats --history --since <iso>`**: extend
  --history mode with mtime filter (which it doesn't currently
  honor; --since only filters disk-manifest mode).

- **s128 — Open Library author search**: `gen openlibrary fetch
  --author <name>` filters by author at the API level instead of
  generic text search.

- **s129 — `gen rawg games --platform <slug>`**: RAWG search
  supports platform filter natively. Surface as flag (e.g. only
  PC games, only Switch games).

- **s130 — recipe `expected_min_assets` field**: optional int
  on recipe root. After `pack from-recipe` completes, compare
  total_downloaded against this; emit ledger warning if below.

Ship order: s126, s127, s128, s129, s130.

---

## v1.19+ backlog (added 2026-05-12, s131)

All v1.18+ s126..s130 SHIPPED. Five fresh ideas:

- **s132 — `pack from-recipe` honors expected_min_assets**: post-run,
  if `recipe.expected_min_assets` is set, compare against the total
  downloaded count and emit a ledger warning (status='under_expected')
  if below. Surfaces in `pack audit` output.

- **s133 — `gen unsplash photos --collection <id>`**: Unsplash search
  supports collection filter. Useful for curated theme buckets.

- **s134 — `gen wikimedia fetch --category <name>`**: MediaWiki API
  supports category-walk (`list=categorymembers`). Far more focused
  than free-text search for asset prospecting.

- **s135 — `library r1a-status --csv <path>`**: dump per-provider rows
  to a CSV file. Spreadsheet-friendly alternative to --json.

- **s136 — milestone v1.18-WAVE-COMPLETE + 800-test stretch**: capstone
  once s132..s135 ship. 19 more tests to reach 800.

Ship order: s132, s133, s134, s135, s136.

---

## v1.20+ backlog (added 2026-05-12, s137)

All v1.19+ s132..s136 SHIPPED. 800-test milestone hit. Five fresh ideas:

- **s138 — Iconify `--prefix <set>` filter**: scope `gen iconify fetch`
  to a specific icon set (e.g. only `game-icons:` results). Iconify
  search API supports prefix filter via `query=prefix:term` syntax.

- **s139 — pack from-recipe pipeline writes per-pack pipeline log**:
  each pack ledger gains a `pipeline_log` field listing every stage
  it traversed (acquire, validate, install, complete) with timestamps.
  Useful for triage of "where did this pack get stuck?"

- **s140 — `gen archive-org fetch --collection <id>`**: archive.org
  advanced search supports collection: prefix. Surface as flag for
  scoping to e.g. `prelinger`, `librivoxaudio`, `image_collection`.

- **s141 — recipe schema `min_required_passes` integer**: like
  `expected_min_assets` but counts how many packs must end in
  `completed` status. Lets a recipe say "I need at least 3 of my
  5 optional packs to succeed."

- **s142 — milestone v1.19-WAVE-COMPLETE (already shipped) + DOC SWEEP**:
  refresh RELEASE_NOTES_v1.10_v1.11.md with v1.18-v1.19 deltas, since
  it's currently frozen at the R1A wave milestone.

Ship order: s138, s139, s140, s141, s142.

---

## v1.21+ backlog (added 2026-05-12, s143)

All v1.20+ s138, s140, s141, s142 SHIPPED (s139 per-pack pipeline_log
moved here). Five fresh ideas:

- **s144 — per-pack `pipeline_log` field**: each pack ledger gains
  a `pipeline_log` list of {stage, status, ts_utc} entries traversed
  during from-recipe. Surfaces in `pack status` + `pack audit`.

- **s145 — `gen all-no-key --provider <id>,<id>` filter**: narrow
  fan-out to a subset of providers (e.g. `--provider met_museum,iconify`
  hits only those two instead of all 6).

- **s146 — Jamendo `--instrument <name>`**: Jamendo API has tags.instruments
  filter natively; exposes guitar-only, piano-only etc. searches.

- **s147 — pack from-recipe `--provider-only <id>`**: like the
  manifest-level `--only <pack>` but at provider scope. Run only
  the iconify packs in a recipe; skip the rest.

- **s148 — `pack rerun-failed --recipe <yaml>` honors expected_min
  + min_required_passes too**: bring the v1.18/v1.20 fields into the
  rerun pipeline so an operator can rerun after partial success and
  see whether they've now met the threshold.

Ship order: s144, s145, s146, s147, s148.

---

## v1.22+ backlog (added 2026-05-12, s149)

All v1.21+ s144..s148 SHIPPED. Five fresh ideas:

- **s150 — `gen all-no-key --history-tail <N>`**: read the last N
  history snapshots and emit a stdout summary of trend per provider
  (avg matched + downloaded + ok-rate). Quick "how's my scout doing
  this week?" view without parsing JSON.

- **s151 — `pack list-recipes --sort name`**: third sort key
  (alphabetical by recipe_id). Already have path + tier.

- **s152 — `library install-r1a-pack` dedup by file_path**: when
  registering rows in asset_library.json, skip entries whose
  file_path already appears. Currently each call appends, so
  rerunning produces duplicate rows.

- **s153 — Scryfall `--set <code>`**: scope to one MTG set (e.g.
  `set:cmm` for Commander Masters). Scryfall API supports this
  natively via query syntax 'set:<code>'.

- **s154 — v1.20 wave milestone tag was renamed v1.20-WAVE-COMPLETE
  (shipped); v1.21+ pending milestone after s149-s153**.

Ship order: s150, s151, s152, s153, s154.

---

## v1.23+ backlog (added 2026-05-12, s156)

All v1.22+ s151..s153 SHIPPED (s150 history-tail and s154 milestone moved
in/out). Five fresh ideas:

- **s157 — `gen all-no-key --history-tail <N>`**: read last N
  history snapshots from state/r1a_history/all_no_key_*.json and
  emit per-provider rolling stats (avg matched, avg downloaded, ok-rate).
  Single CLI command for "what's my scout trend looking like?"

- **s158 — Met Museum `--department-list` discovery command**: hit
  `/departments` to list all 17 Met departments with their IDs.
  Operator can browse before passing --department to fetch.

- **s159 — `pack manifest-stats --top <N>`**: when many providers
  are present, sort by total_bytes desc and show only top N rows.
  Useful for "what's hogging my disk?".

- **s160 — recipe schema `created_utc` / `updated_utc` metadata**:
  optional ISO 8601 timestamps. Validator accepts; pack list-recipes
  shows them as extras when present.

- **s161 — milestone v1.22-WAVE-COMPLETE already shipped (s154
  combined); v1.23-WAVE-COMPLETE after s157-s160 ship**.

Ship order: s157, s158, s159, s160, s161.

---

## v1.40+ backlog (added 2026-05-13, s221)

State at s221 close: **271 commits since 0b1ad7d, 254 tags, 926 tests,
26 consecutive wave milestones (v1.13->v1.38) with 0 RULE violations**.
v1.39 wave closes with s221. v1.40+ candidates organized by theme:

### A. HTML/dashboard surface (mirror r1a-status patterns)

- **s222 — `pack manifest-stats --html <path>`**: render per-source
  bars + total bytes badge as standalone HTML. Twin to
  r1a-status --html (v1.13.s97). Adds --open companion flag.

- **s223 — `gen history-tail --html <path>`**: trend-line per provider
  over the last N runs. Adds --since-days filter, --open helper.

- **s224 — `gen list-providers --html <path>`**: catalog dashboard
  with license SPDX + env-set status. CSS badge per asset_class.

### B. More provider-specific filters

- **s225 — Met Museum `--has-images-only`**: filter the search to
  only objects with downloadable images (already implicit; surface as
  explicit flag to skip image-less hits).

- **s226 — Iconify `--style outline|filled|duotone|two-tone`**:
  add a post-search filter on icon style heuristic (set-name prefix
  pattern: `mdi-outline:`, `mdi-filled:`, etc.).

- **s227 — Archive.org `--year-from/--year-to`**: filter on
  Internet Archive `year` facet (1500..2026). Useful for narrowing
  historical-art queries.

- **s228 — Pexels/Pixabay/Unsplash `--min-width/--min-height`**:
  filter low-resolution hits at search time. Pexels supports
  `min_width` / `min_height` natively.

### C. Recipe ergonomics

- **s229 — `recipe.last_run_utc` derived field**: surface in
  list-recipes JSON when a pack pipeline ledger exists; read-only
  (computed from `state/pack_pipeline/<game>/<id>.json` mtime).

- **s230 — `pack validate-all --html <path>`**: validation
  dashboard with per-recipe pass/fail/warning counts + drilldown
  to error messages. CSS color coding.

- **s231 — `pack list-recipes --since-days N`**: filter by
  updated_utc <= N days ago (only recipes touched recently). Mirrors
  manifest-stats --since-days (v1.33.s198).

- **s232 — recipe schema `recipe.engine_version`**: optional
  string ('1.6', '6.0', '2026.1'); validator warns on non-string;
  surfaces in list-recipes.

### D. Operational polish

- **s233 — `library r1a-status --refresh`**: force re-probe even
  when --check-live is omitted. Helpful after a flaky probe.

- **s234 — `gen all-no-key --retry <N>`** + **all-key --retry**:
  per-provider retry-on-error counter inside the fan-out loop.
  Composes with --bail-on-error.

- **s235 — `pack manifest-stats --json --gauge`**: emit
  `total_bytes_gib`/`total_files_thousand` precomputed fields for
  dashboards.

- **s236 — `gen history-tail --format csv|markdown`**: output
  format toggle. Markdown table for paste-into-issue, CSV for
  Excel/Sheets ingestion.

### E. Milestones

- **s237 — v1.40-WAVE-COMPLETE**: cut after s222-s225 ship (4-slice
  HTML/dashboard wave).

- **s238 — v1.41-WAVE-COMPLETE**: cut after s226-s228 ship
  (provider-filter wave).

- **s239 — v1.42-WAVE-COMPLETE**: cut after s229-s232 ship (recipe
  ergonomics wave).

- **s240 — v1.43-WAVE-COMPLETE**: cut after s233-s236 ship
  (operational polish wave).

- **s241 — v2.0 cut decision**: operator-only call. By s240 close
  the surface will be feature-complete for the "shipping Path B
  assistant" use case. v2.0 would mean: stable API contract,
  comprehensive docs, formal SemVer commitment.

Ship order: A->B->C->D (one wave per theme). Each theme can be
postponed indefinitely without breaking anything.

### Standing rule: HEARTBEAT refresh every ~15 slices closed.
