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
