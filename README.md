# flax-asset-worker

Modular asset pipeline for Flax Engine. C# HTTP hub (:8790) +
Python sidecar with Typer CLI, recipe-driven pack runs, and a
weekly external-API canary.

> **Renamed 2026-05-06:** previously published as `diklaaltman91-ux/faw`.
> Now lives at `flax-game-studio/flax-asset-worker` alongside the
> `flax-mcp` monorepo (which subscribes to this repo as
> `external/flax-asset-worker` submodule).
>
> **Path B refactor 2026-05-10:** slim-down + Typer rewrite. See
> `docs/COMMIT_READY-assetboi.md` for the full slice log.

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

## Path B refactor — 9 slices, 2026-05-10

| Slice | Commit | What shipped |
|---|---|---|
| s1 | `16fc55d` | `canary.py` — 5-probe external-API smoke test + 26 unit tests |
| s2 | `a7fb86c` | 16 YAML data parks (Roman specs + presets) + delete orphan tts_runner.py |
| s3 | `7b30892` | Quixel scanner extracted to `providers/quixel_scanner.py` (296 LOC) |
| s4 | `fb2117f` | `AcquisitionMethod` canonical alias for `ProviderLane` |
| s5 | `8d2f16d` | Typer CLI Phase 1: fab + library + import (11 commands) |
| s6 | `00760fc` | Typer CLI Phase 2: unity + epic + gen (22 commands total) |
| s7 | `4b74e7f` | `pack_pipeline.py` Stage enum + dispatch shim (additive; legacy preserved) |
| s8 | `fbb23ba` | `recipes/primitive_tech/first_playable.yaml` + `pack` sub-app (25 commands total) |
| s9 | `0181202` | `recipes/roman/first_playable.yaml` (14 packs ported from data) |

Deferred for future slices (see `docs/COMMIT_READY-assetboi.md`):
- **s2.5**: strip cli.py DEAD-imports + 26 lazy-handler blocks (depends on s10.5)
- **s2.6**: rewire KEEP files to drop dead-bridge deps (provider_readiness, library_map, unity/unreal_runner)
- **s10.5**: mechanical extraction of `pack_pipeline.execute_prepare_pack` legacy body into `STAGE_HANDLERS` + delete legacy `cli.py`
- **s11**: pre-pack acquisition router (`direct_url`/`manual_browser`/`generator` -> `source_dir`)

---

## License

MIT
