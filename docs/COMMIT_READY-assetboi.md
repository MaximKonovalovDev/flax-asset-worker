# COMMIT_READY — assetboi (Path B execution)

> Slice log for Path B (FAW cleanup, 10-day plan).
> Owner: assetboi (opencode lane).
> Repo: this one (`flax-asset-worker`). Commits land directly on `main`
> here — multi-AI etiquette applies to `flax-mcp` only.
>
> Format: one append-only block per slice. Use **Edit tool** to append
> (Rule 7: no bash Add-Content > 500 chars).

---

## Slice s1 — Day 1 canary.py (2026-05-10)

**Status:** SHIPPED (uncommitted; staging next).

**Files added:**
- `Python/assetboy/canary.py` (419 lines) — 5-probe external-API smoke test
- `Tests/python/test_canary.py` (581 lines) — 26 unit tests, all offline
- `Tests/python/conftest.py` — rewrote for new `Python/assetboy/` layout (was pointing at non-existent `src/`)
- `.gitignore` — added `state/` + `.pytest_cache/` (artifacts)

**Probes (all reuse real provider modules, no auth re-implementation):**
1. PolyHaven — `requests.get` against `POLYHAVEN_API/assets` (textures/natural). CC0, no auth.
2. Fab — `FabHybridDownloader.load_auth_state()` → `is_authenticated()` → page-1 `/i/library/search` via `fetch_fab_library_page`.
3. Epic — `default_local_fab_library_db_path()` → SQLite `PRAGMA user_version` + `SELECT COUNT(*) FROM local_listing` (read-only, no network).
4. Unity Hub — `load_unity_hub_tokens()` → `list_unity_owned_assets(rows=1)`.
5. ComfyUI — `is_comfyui_running()` → optional `:8188/system_stats` for GPU + free VRAM notes.

**Test results:** 26/26 PASSED in 1.53s.
**Live smoke run on operator machine:**
```
[OK ] polyhaven     1469 ms  155 natural-texture assets
[RED] fab           2014 ms  no_auth_state_run_fab_login          (expected — no fab login yet)
[OK ] epic            16 ms  schema v0 (unpinned); 4 vault items
[RED] unity_hub        0 ms  unity_hub_tokens_missing             (expected — no Unity Hub install)
[RED] comfyui       2094 ms  connection_refused                   (expected — ComfyUI not running)
overall: red
written: C:\flax\flax-asset-worker\state\canary\canary_status.json
```

**Operator action items** (logged here, not blocking):
1. Pin `EXPECTED_EPIC_SCHEMA_VERSION = 0` in `canary.py` after verifying that's the real Launcher schema version (canary will then go red on any future drift).
2. Run `python -m assetboy fab login` once a Fab CLI sub-app exists (Day 5).
3. Optional: install Unity Hub + sign in to enable that probe.

**Deviations from CANARY-SPEC:**
- Spec assumed `load_fab_auth_cookies()` top-level fn; real surface is `FabHybridDownloader.load_auth_state()`. Canary uses the real surface (no provider helper added).
- Spec assumed `unity_hub_decrypt_master_key` / `unity_hub_decrypt_tokens` public; real are `_load_unity_hub_master_key` / `_decrypt_unity_hub_blob` private. Canary uses `load_unity_hub_tokens()` (the real public entry).
- Spec assumed `tokens["access_token"]`; real key is `tokens["accessToken"]` (camelCase).
- Spec assumed `/-/api/owned-products`; real endpoint is `/-/api/purchases` (wrapped by `list_unity_owned_assets()` which canary uses).
- Spec assumed `requests` for ComfyUI; comfyui_runner uses `urllib`. Canary uses both — `is_comfyui_running()` for liveness, `urllib.request.urlopen` for stats.
- State dir bug found + fixed: `state_root(__file__)` resolved one dir too high because canary.py is shallower than paths.py. Fix: call `state_root()` with no args (defaults to paths.py's own `__file__`).

**Next:** s2 — delete Tier-4 DEAD files per PATH-B §2.

---

## Slice s2 — Day 2 DEAD-file purge (2026-05-10)

**Status:** SHIPPED partial (data parked + 1 file deleted). Full purge deferred to s2.5 (after cli rewrite) + s2.6 (after KEEP-file rewires).

**Peer-opus deep import-trace revealed:** only **1 of 22** listed DEAD files (`tts_runner.py`) is truly safe to delete today. The other 21 are blocked by **KEEP-list code** that imports them — specifically `provider_readiness.py`, `library_map.py`, `unity_runner.py`, `unreal_runner.py`, `browser_automation.py`, `freesound_runner.py`, `pack_pipeline.py` (via `flax_wrapper.py`), `blender_runner.py`, plus the cli.py god-object with 26 lazy-import handler blocks.

**What shipped this slice:**

1. **Created `Python/assetboy/data/` directory** + **one-shot extractor script** `_extract_dead_data.py` that imports every DEAD module + dumps its module-level constants to YAML.
2. **Ran extractor — 10/10 extractors green**, 80+ KB of structured YAML data parked:
   - `roman_first_playable_specs.yaml` (20 KB) — main ROMAN_FIRST_PLAYABLE_SPECS + default-only specs. Source of truth for s9.
   - `animationgpt_presets.yaml` (4 KB) — 20 combat-anim text prompts.
   - `colab_pipelines.yaml` (16 KB) — Hunyuan3D/Trellis pip stacks + verbatim source dump.
   - `dialogue_presets.yaml`, `music_presets.yaml`, `vehicle_presets.yaml`, `vfx_presets.yaml`, `museum_presets.yaml`, `font_presets.yaml`, `game_icons_presets.yaml`, `quaternius_presets.yaml` — runner preset tables.
   - `playwright_presets.yaml` (1.6 KB) — Mixamo character presets + adapter-keys inventory.
   - `provider_profiles.yaml` (18 KB) — AI_PROVIDER_PROFILES + ENGINE_BRIDGE_PROFILES + EXTRACTOR_PROFILES + STATIC_PROVIDER_RUNBOOKS.
   - `pack_family_plan_data.yaml` (1.3 KB) — BROWSER_SOURCE_URLS + SOURCE_PAGE_URLS + DEFAULT_PROFILE_BY_BRIDGE_ID + ENGINE_KIND_BY_BRIDGE_ID.
   - `roman_source_presets.yaml` — per-pack mixamo/helper presets.
3. **Deleted `Python/assetboy/execution/tts_runner.py`** — only file with zero non-DEAD importers (peer-opus verified). The `run-tts-batch` CLI handler at `cli.py:8398` actually uses `dialogue_runner.run_dialogue_line`, not `tts_runner`. Filename was misleading.
4. **Test gate:** 26/26 canary tests still green after deletion.

**Deferred into new slices:**

- **s2.5** — strip cli.py DEAD-imports + delete dead command handlers. Depends on s5/s6 cli rewrite. Will delete 7 eager imports + 26 lazy-import handler blocks.
- **s2.6** — rewire KEEP files to drop dead-bridge deps, then delete bridges. Specifically:
  - `provider_readiness.py` → drop ai_bridge/generator/runbooks deps (load from YAML instead)
  - `library_map.py` + `epic_vault.py` → fold `emit_extractor_job` inline
  - `unity_runner.py` + `unreal_runner.py` → fold `emit_engine_export_job` inline
  - `browser_automation.py` + `freesound_runner.py` → inline playwright_runner helpers
  - `pack_pipeline.py` → drop `flax_wrapper` import (and delete `flax_wrapper.py` + `execution_kit.py`)
  - Then delete: ai_bridge, engine_bridge, extractor_bridge, generator, runbooks, playwright_runner, plus 15 execution runners, plus 4 roman_* workflows.

**Why this is correct:** PATH-B-EXECUTION §2 was written before tracing the import graph. The honest read is that deletion ordering matters — data first, KEEP rewires second, deletes last. Saving data NOW (this slice) means s9 (Roman YAML port) can proceed in parallel with s5+s6 (cli rewrite).

**Files staged for commit:**
- `Python/assetboy/data/_extract_dead_data.py` (new, one-shot extractor)
- `Python/assetboy/data/*.yaml` (16 new YAML files, ~80 KB total)
- `Python/assetboy/execution/tts_runner.py` (deleted)

**Next:** s3 — extract Quixel scanner from `library_map.py` per PATH-B Day 3.
