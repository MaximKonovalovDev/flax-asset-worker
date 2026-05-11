# flax-asset-worker

Modular asset pipeline for Flax Engine. C# HTTP hub (:8790) + Python sidecar
with Typer CLI (18 sub-apps, 40+ commands), recipe-driven pack runs (5 working
recipes including R1A smoke), 3-lane acquisition router (direct_url /
manual_browser / generator), 19 wired direct_url providers (4 CC0 sites + 10 R1A
public APIs + 5 generators), and a weekly external-API canary.

> **Renamed 2026-05-06:** previously published as `diklaaltman91-ux/faw`.
> Now at `flax-game-studio/flax-asset-worker`.
>
> **Path B refactors 2026-05-10 → 2026-05-11:** slim-down + Typer rewrite
> + acquisition router + 4 generator drivers + C# server endpoints +
> contract regression tests. Net code reduction: **-24,487 LOC** (from
> ~50k to ~25k). Test growth: 26 → **589 passing**.
>
> **R1A public-API integration COMPLETE (v1.10.x + v1.11.x):** 10 new
> public-API providers shipped (Met Museum, Wikimedia, Archive.org,
> Scryfall, Iconify, Pexels, Pixabay, Unsplash, RAWG, Jamendo) with
> THREE invocation paths each (standalone `gen X` CLI, recipe pipeline,
> SOURCE_ADAPTERS lookup). FAW's first VIDEO providers (Pexels+Pixabay).
> FAW's first MUSIC track provider (Jamendo). See
> `docs/COMMIT_READY-assetboi.md` for full slice log + `docs/HEARTBEAT-assetboi.md`
> for operator hibernation summary + `docs/SETUP.md` §5.5 for env-key setup.

## Public-API providers (R1A, v1.10–v1.11)

| Provider | License | Auth | What it returns |
|---|---|---|---|
| Met Museum | CC0 | none | Open Access art works (paintings, sculpture refs) |
| Wikimedia Commons | CC0/CC-BY/SA/PD | none | Massive open-license image corpus |
| Archive.org | CC/PD per item | none | Books, audio, video, images |
| Scryfall | CC-BY-SA-4.0 | none | MTG card art (fantasy creature refs) |
| Iconify | MIT/Apache/CC0/OFL | none | 150+ open-source icon sets |
| Pexels | Pexels License | `PEXELS_API_KEY` | Stock photos + **VIDEOS** |
| Pixabay | CC0-equivalent | `PIXABAY_API_KEY` | Photos+illustrations+vectors+videos |
| Unsplash | Unsplash License | `UNSPLASH_ACCESS_KEY` | Stock photos |
| RAWG.io | reference-only | `RAWG_API_KEY` | Game covers + screenshots (ideation only) |
| Jamendo | CC-BY/SA | `JAMENDO_CLIENT_ID` | **CC MUSIC TRACKS** (3–5min) |

### Quick scout commands

```powershell
# 5 no-key providers in one shot:
python -m assetboy.cli gen all-no-key -q "stone wall" -n 2 --dry-run

# 5 key-required (skips missing keys gracefully) + optional video providers:
python -m assetboy.cli gen all-key -q "fire" --include-video --dry-run

# Single provider examples:
python -m assetboy.cli gen met-museum fetch -q "roman fresco" -n 4
python -m assetboy.cli gen iconify fetch -q "sword" --width 64 -n 20
python -m assetboy.cli gen pexels videos -q "fire crackling" -n 2
python -m assetboy.cli gen jamendo tracks -q "ambient cinematic" -n 3

# End-to-end recipe smoke (5 no-key providers in one recipe):
python -m assetboy.cli pack from-recipe sandbox/r1a_smoke.yaml --dry-run
```

---

## Architecture

```
Flax Editor
├── FlaxMCP                    ← MCP tools, scene editing, chat
│   └── plugins/flax-asset-worker/  ← thin facade -> HTTP :8790
│
├── FAW (C# GamePlugin)        ← HTTP server on :8790
│   ├── Source/Core/           ← plugin entry, HTTP server, config
│   ├── Source/Providers/      ← PolyHaven + Kenney (C# native)
│   ├── Source/Routes/         ← REST endpoints (provider/lane/library)
│   └── Config/                ← providers.json, categories.json
│
└── Python sidecar             ← Python/assetboy/
    ├── canary.py              ← 5-probe external-API weekly smoke test
    ├── cli/                   ← Typer CLI: 7 sub-apps, 25 commands
    │   ├── fab.py             ← Fab.com auth + library + download
    │   ├── library.py         ← FAW :8790 search/install/ready/audit
    │   ├── import_cmd.py      ← drop file or watch folder
    │   ├── unity.py           ← Unity Asset Store auth + owned + download
    │   ├── epic.py            ← Epic Launcher vault + catalog
    │   ├── gen.py             ← ComfyUI / stable-diffusion.cpp
    │   └── pack.py            ← YAML recipe runner
    ├── providers/             ← 20+ provider modules (Fab/Epic/Unity/Mixamo + helpers)
    │   ├── quixel_scanner.py  ← extracted from library_map.py (Path B s3)
    │   ├── lanes.py           ← ProviderLane + AcquisitionMethod (s4 alias)
    │   └── bridge_registry.py ← the brain: ~55 BridgeDefinition entries
    ├── execution/             ← 8 runners (PolyHaven/Kenney/ambientCG/FreeSound/ComfyUI/sd.cpp/Blender/Mixamo)
    ├── workflows/             ← pack_pipeline.py (with new Stage dispatch shim)
    ├── data/                  ← YAML-parked DEAD-file constants (Roman specs, presets)
    └── cli.py                 ← LEGACY 8500-line god-CLI (will be deleted in s10.5)

recipes/                       ← YAML-driven pack runs
├── primitive_tech/first_playable.yaml  ← 9 packs, stone-age forest demo
└── roman/first_playable.yaml           ← 14 packs, gladiator arena
```

---

## Quick start

### Build the C# plugin

1. Copy this repo's `Source/` + `Config/` + `FAW.flaxplugin` into your Flax project's `Source/`.
2. Add `FAW` to plugin references in your `.flaxproj`.
3. Build via `dotnet build` or open in Flax Editor.
4. HTTP server starts automatically on `http://localhost:8790`.

### Install the Python sidecar

```powershell
cd Python\assetboy
python -m pip install -r requirements.txt
python -m playwright install chromium     # for Mixamo/Unity browser flows
```

### Run the canary (weekly smoke test)

```powershell
python -m assetboy.canary                  # full run, exit 0/1
python -m assetboy.canary --probe polyhaven  # single probe
python -m assetboy.canary --json           # tooling-friendly output

# Register weekly Windows Task Scheduler:
pwsh scripts\install-canary-scheduler.ps1
```

### Use the Typer CLI

```powershell
python -m assetboy.cli --help              # 7 sub-apps
python -m assetboy.cli fab auth-status
python -m assetboy.cli library audit
python -m assetboy.cli unity status
python -m assetboy.cli epic status
python -m assetboy.cli gen comfyui status
python -m assetboy.cli pack list-recipes
python -m assetboy.cli pack from-recipe primitive_tech/first_playable.yaml --dry-run
```

### Test the HTTP server with curl

```bash
curl http://localhost:8790/api/v1/health

curl -X POST http://localhost:8790/api/v1/providers/list \
  -H "Content-Type: application/json" -d "{}"

curl -X POST http://localhost:8790/api/v1/library/install \
  -H "Content-Type: application/json" \
  -d '{"asset_id":"brick_wall_01","provider":"polyhaven","category":"texture","name":"Brick Wall"}'

curl -X POST http://localhost:8790/api/v1/library/ready \
  -H "Content-Type: application/json" -d "{}"
```

---

## Providers (current shipped)

| ID | Name | Auth | Lane | C#? | Python? | Categories |
|---|---|---|---|---|---|---|
| polyhaven | PolyHaven | Free CC0 REST | direct_url | yes | yes | texture, model, hdr |
| kenney | Kenney | Free CC0 ZIPs | direct_url | yes | yes | texture, model, audio, sprite, font |
| ambientcg | AmbientCG | Free CC0 PBR | direct_url | — | yes | texture |
| freesound | FreeSound | API key + CC filter | direct_url | — | yes | audio |
| fab | Fab.com | OAuth via nodriver | manual_browser | — | yes | texture, model, audio, animation |
| epic | Epic Launcher | local SQLite + catalog | manual_browser | — | yes | vault items |
| unity | Unity Asset Store | DPAPI tokens | manual_browser | — | yes | model, animation, audio |
| mixamo | Mixamo | Adobe Playwright | manual_browser | — | yes | animation |
| stable_audio_open_small | Stability AI | local 6GB-VRAM | generator | — | yes | audio (ambience) |
| comfyui | ComfyUI :8188 | local | generator | — | yes | texture, model |
| sd.cpp | stable-diffusion.cpp | local CUDA | generator | — | yes | image |

---

## Recipes

YAML-driven pack runs in `recipes/<game>/<recipe>.yaml`. Schema:

```yaml
recipe:
  id: <recipe_id>
  schema_version: "2026-05-10.recipe.v1"
  game: <game_id>
  output_folder: "Content/Recipes/..."

packs:
  - id: <PACK_ID>
    category: model | texture | audio | animation | hdr
    asset_kind: foliage | prop_static | character_animated | surface_pbr | ...
    provider: polyhaven | fab | mixamo | ...
    acquisition_method: direct_url | manual_browser | generator
    license:
      kind: cc0 | fab_standard | mixamo_free | stability_community
      commercial_ok: true
    assets:
      - asset_id: ...           # or listing_uid for Fab, search_terms[] for FreeSound
    cleanup:
      mode: skip | minimal | blender
    flax_import:
      target_subfolder: ...
    gate:
      required: true | false
      reason: "..."

gates:
  required_pack_ids: [...]
  optional_pack_ids: [...]
  block_on_missing_required: true
```

Run:
```powershell
python -m assetboy.cli pack from-recipe primitive_tech/first_playable.yaml --dry-run
python -m assetboy.cli pack from-recipe roman/first_playable.yaml --resume
```

---

## Configuration (C# side)

`Config/providers.json`, `Config/categories.json` — provider settings + category routing for the C# server. The Python sidecar reads its own config from each provider module (e.g. `providers/fab_hybrid.py` persists auth state under `.private/fab_auth_state.json`).

---

## Path B v1.1 → v1.5 refactor — 27 slices, 9 tags (2026-05-10 → 2026-05-11)

### Tags trail (chronological)

| Tag | Commit | What landed |
|---|---|---|
| `v1.1.0-path-b-cleanup` | `2d4bad8` | Path B Day 10: Typer CLI scaffold + 2 recipes + Stage dispatch shim |
| `v1.2.0-leangoods` | `0eb77fa` | DEAD-code purge complete (-21,812 LOC) |
| `v1.2.1-acquisition` | `998350b` | 3-lane acquisition router; recipes end-to-end functional |
| `v1.3.0-green-suite` | `1294e1e` | `paths.py` self-hosting fallback + full green test suite (190 pass) |
| `v1.3.2-comfyui-live` | `ab4092b` | Real ComfyUI workflow execution (replaces v1.2.1 placeholder) |
| `v1.4.0-recipes-trio` | `8c3766a` | Sandbox 1-pack recipe + sd.cpp/local_image driver |
| `v1.4.1-stable-audio` | `536aa32` | Stable Audio Open Small driver (4/4 generator providers complete) |
| `v1.5.0-server-endpoints` | `9d32670` | C# HTTP routes: `/recipes/list`, `/recipes/run`, `/packs/{id}/status`, `/canary/status` |
| `v1.5.3-contract-coverage` | `f597a70` | Python-side regression tests for all 4 C# server endpoints (238 pass) |

### Slice ledger (all 27 slices)

```
s1     16fc55d  canary.py (5 probes, 26 tests)
s2     a7fb86c  16 YAML data parks + delete orphan tts_runner.py
s3     7b30892  Quixel scanner extracted to providers/quixel_scanner.py
s4     fb2117f  AcquisitionMethod alias for ProviderLane
s5     8d2f16d  Typer CLI Phase 1: fab + library + import (11 cmds)
s6     00760fc  Typer CLI Phase 2: unity + epic + gen (22 cmds total)
s7     4b74e7f  pack_pipeline Stage dispatch shim (additive)
s8     fbb23ba  primitive_tech recipe + pack sub-app (25 cmds total)
s9     0181202  roman_arena recipe (14 packs ported)
s10    2d4bad8  README/ROADMAP refresh + C# ILane inlined; TAG v1.1.0
s2.5a  aa057a6  rename cli.py -> cli_legacy.py (resolve shadowing)
s2.6a  588c901  rewire provider_readiness drop ai_bridge/generator/runbooks
s2.6b  928b252  drop ai_bridge/runbooks from providers/__init__ + neuter playwright
s2.6c  94e501e  flax_wrapper drop 10 DEAD-runner imports + stub _run_bulk_impl
s2.6d  c5839e3  bulk delete 13 DEAD files (-6,176 LOC)
s2.6e  5f8a4fa  delete 9 workflows + blender_runner YAML rewire (-3,075 LOC)
s10.5a 0eb77fa  delete cli_legacy.py + 18 broken tests (-12,443 LOC); TAG v1.2.0
s11    998350b  acquisition router; TAG v1.2.1
v1.3   531a74d  paths.py self-hosting + is_workspace_configured helper
v1.3.0 1294e1e  delete 5 legacy-cli tests; 190 tests pass; TAG v1.3.0
v1.3.1 160134a  test_acquisition_router + test_cli_typer (24 new integration tests)
v1.3.2 ab4092b  real ComfyUI workflow exec wired; TAG v1.3.2
v1.3.3 c88e598  sd.cpp/local_image driver wired
v1.3.4 8c3766a  sandbox/one_pack_smoke.yaml recipe; TAG v1.4.0
v1.4.1 536aa32  Stable Audio Open Small driver; TAG v1.4.1
v1.5.0 9d32670  C# server-side endpoints; TAG v1.5.0
v1.5.1 8b54364  CLI --json contract regression tests
v1.5.2 4824c10  ComfyUI input_image passthrough for img2img recipes
v1.5.3 f597a70  canary --json contract regression tests; TAG v1.5.3
```

Deferred to future slices (see `docs/PATH_B_DAY11_PLAN.md`):
- **s10.5b**: mechanical extraction of `pack_pipeline.execute_prepare_pack` legacy body into populated `STAGE_HANDLERS`. Cosmetic; pack_pipeline works today via legacy body + s7 dispatch shim. **Deferred indefinitely unless real value emerges.**
- **flax-mcp facade implementation**: design doc in `docs/MONOREPO_FACADE_DESIGN.md`. 6 MCP atomics + 1 mega-tool wrapping the v1.5.0 HTTP endpoints. **Owned by Lane E broker** (assetboi can't commit to flax-mcp per multi-AI etiquette).
- **flax-mcp submodule pin bump**: `external/flax-asset-worker` currently pinned at `0b1ad7d` (pre-Path-B). Operator/broker job to bump to current FAW HEAD.

---

## License

MIT
