# FAW Roadmap

## Path B refactor — SHIPPED 2026-05-10 (v1.1.0)

The original v1.0 roadmap below is preserved for historical context. After
the honest review in `docs/research/FAW-HONEST-REVIEW-AND-PATHS-2026-05-10.md`
the operator chose Path B (provider-first, no workflow layer).

### Shipped slices (s1-s9)

| Slice | Commit | What shipped |
|---|---|---|
| s1 | `16fc55d` | `Python/assetboy/canary.py` — weekly external-API smoke test (PolyHaven + Fab + Epic + Unity Hub + ComfyUI) + 26 unit tests |
| s2 | `a7fb86c` | 16 YAML data parks (`assetboy/data/*.yaml`) + delete orphan `tts_runner.py` |
| s3 | `7b30892` | Quixel scanner extracted from `library_map.py` to `providers/quixel_scanner.py` (296 LOC moved, re-exports preserved for back-compat) |
| s4 | `fb2117f` | `AcquisitionMethod` canonical alias for `ProviderLane` (disambiguates from C# `ILane`); bulk rename deferred |
| s5 | `8d2f16d` | Typer CLI Phase 1: `cli/` package + 3 sub-apps (fab + library + import; 11 commands) |
| s6 | `00760fc` | Typer CLI Phase 2: 3 more sub-apps (unity + epic + gen; 22 commands total across 6 sub-apps) |
| s7 | `4b74e7f` | `pack_pipeline.py` Stage enum + `STAGE_HANDLERS` dispatch shim (additive; legacy body preserved with its 10 tests; mechanical extraction deferred to s10.5) |
| s8 | `fbb23ba` | `recipes/primitive_tech/first_playable.yaml` (9 packs) + `pack` sub-app (`list-recipes`/`from-recipe`/`status`; 25 commands total) |
| s9 | `0181202` | `recipes/roman/first_playable.yaml` (14 packs ported from `data/roman_first_playable_specs.yaml`) |

### Slice log

Full per-slice details in `docs/COMMIT_READY-assetboi.md`.

### Deferred slices (post-Path B v1.1)

- **s2.5** — strip `cli.py` DEAD-imports + 26 lazy-handler blocks. Depends on s10.5 (mechanical pack_pipeline extraction must come first).
- **s2.6** — rewire KEEP files to drop dead-bridge deps so 21 DEAD files can finally be deleted: `provider_readiness.py`, `library_map.py`, `epic_vault.py`, `unity_runner.py`, `unreal_runner.py`, `browser_automation.py`, `freesound_runner.py`, `pack_pipeline.py` (via flax_wrapper).
- **s10.5** — mechanical extraction of `pack_pipeline.execute_prepare_pack` legacy body into the 5 `STAGE_HANDLERS` functions; v1 -> v2 ledger compatibility tests; then delete legacy `cli.py`.
- **s11** — pre-pack acquisition router that maps recipe `acquisition_method` (`direct_url` / `manual_browser` / `generator`) to a `source_dir` before `execute_prepare_pack_dispatched` is called. Today recipes correctly load but their packs go RED because there's no source_dir; s11 closes the loop.

### What you can do today

- Weekly canary: `python -m assetboy.canary` — reports per-probe OK/RED + writes `state/canary/canary_status.json`.
- Browse recipes: `python -m assetboy.cli pack list-recipes`.
- Dry-run a recipe: `python -m assetboy.cli pack from-recipe primitive_tech/first_playable.yaml --dry-run`.
- Inspect Fab auth: `python -m assetboy.cli fab auth-status`.
- Inspect Epic vault: `python -m assetboy.cli epic status`.
- Health-check the C# server: `python -m assetboy.cli library audit`.
- Run AI gen status: `python -m assetboy.cli gen comfyui status`.

---

## ✅ Done (v1.0.0 — pre-Path B baseline)

### C# Plugin
- [x] `AssetWorkerPlugin.cs` — GamePlugin entry point
- [x] `WorkerHttpServer.cs` — HTTP server on port 8790, 12 routes
- [x] `WorkerConfig.cs` — Config from JSON + environment variables
- [x] `IAssetProvider.cs` — Provider interface + types
- [x] `ProviderRegistry.cs` — Auto-discovery of providers
- [x] `PolyHavenProvider` — CC0 textures/models/HDRIs (no auth)
- [x] `KenneyProvider` — CC0 game assets + auto-extract (no auth)
- [x] `ILane.cs` — Lane pipeline interface
- [x] `QuickImportLane` — Download → Validate → Import
- [x] `ProviderRoutes.cs` — List/download/search routes
- [x] `LaneRoutes.cs` — List lanes route
- [x] `LibraryRoutes.cs` — Search/install/ready routes
- [x] `Config/providers.json` — 6 provider configs
- [x] `Config/categories.json` — 9 category routing rules
- [x] `Config/lanes.json` — 3 lane definitions

### Python Workers
- [x] Migrated all `scripts/asset_factory/src/assetboy/` to `Python/assetboy/`
- [x] 25+ provider integrations preserved
- [x] Auth flows preserved (Fab/OAuth, Epic/EGS, Unity, Mixamo, etc.)
- [x] CLI preserved (`cli.py` — 7,700 lines, 80+ commands)
- [x] Library, validation, provenance, cleanup, workflow tools

---

## 🚧 In Progress

### C# Providers
- [ ] **AmbientCGProvider** — CC0 PBR textures, no auth
- [ ] **QuaterniusProvider** — CC0 low-poly models, no auth
- [ ] **GameIconsProvider** — CC0 UI icons, no auth

---

## 🎯 Phase 2 — Auth Providers

- [ ] **FabProvider** — Fab.com OAuth (from `Python/assetboy/providers/fab_hybrid.py`)
- [ ] **EpicProvider** — Epic Games vault (from `Python/assetboy/providers/epic_vault.py`)
- [ ] **MixamoProvider** — Mixamo animations (from `Python/assetboy/providers/mixamo_auth.py`)
- [ ] **UnityProvider** — Unity Asset Store (from `Python/assetboy/providers/unity_hub.py`)
- [ ] **FreeSoundProvider** — Audio (from `Python/assetboy/providers/freesound_runner.py`)

---

## 🎯 Phase 3 — Editor UI

- [ ] **AssetBrowserWindow** — Editor window: provider list, search, library
- [ ] **DownloadProgressBar** — Show download/import progress
- [ ] **LibraryView** — Grid view of installed assets with thumbnails
- [ ] **ProviderSettingsPanel** — Configure API keys per provider
- [ ] **One-click Install** — Select → Download → Import → Done

---

## 🎯 Phase 4 — Pipeline

- [ ] **FullPipelineLane** — Download → Validate → Optimize → Convert → Import → Cleanup
- [ ] **BatchProcessLane** — Multiple assets in parallel
- [ ] **BlenderOptimizeStep** — Mesh optimization via Blender (from `Python/assetboy/cleanup/blender_batch.py`)
- [ ] **glTFConvertStep** — Convert any format to glTF for Flax import
- [ ] **TextureResizeStep** — Resize/compress textures for target platform

---

## 🎯 Phase 5 — FlaxMCP Bridge

- [ ] **WorkerHttpClient.cs** (in game-factory) — Clean HTTP client for C# tools
- [ ] **Replace Process.Start** in `AssetBoyOps.Intake.Execution.cs`
- [ ] **Replace Process.Start** in `AssetOpsTool.QueueAndIntake.cs`
- [ ] **Replace Process.Start** in `UnityBridgeOpsTool.cs`
- [ ] **Update `GenerateImageTool.cs`** to route through worker lane

---

## 🎯 Phase 6 — Chat Integration

- [ ] **Asset search** via chat — "find me a stone texture"
- [ ] **Asset install** via chat — "install that brick wall from PolyHaven"
- [ ] **Batch import** via chat — "import all medieval textures from AmbientCG"
- [ ] **Library query** via chat — "what textures do I have installed?"

---

## 🎯 Phase 7 — Python Server

- [ ] **HTTP wrapper** for Python workers (FastAPI on port 8766)
- [ ] **`POST /python/fab/auth`** — Auth flow via Playwright
- [ ] **`POST /python/mixamo/download`** — Animation download + retarget
- [ ] **`POST /python/epic/vault`** — Epic vault inventory + download
- [ ] **`POST /python/generate/image`** — AI image generation (from Colab/ComfyUI runners)
- [ ] **`POST /python/cleanup/optimize`** — Blender mesh optimization

---

## 🎯 Phase 8 — Polish

- [ ] **Unit tests** for all C# providers
- [ ] **Integration tests** — end-to-end download + import
- [ ] **Error recovery** — Retry failed downloads, resume partial
- [ ] **Disk cache** — LRU cache for downloaded assets
- [ ] **Manifest validation** — SHA-256 + provenance checks
- [ ] **Platform variants** — Generate platform-specific textures (mobile, desktop)
- [ ] **Documentation** — API docs, provider guides, contributor guide

---

## 📊 Provider Migration Status

| Provider | Python | C# | Status |
|---|---|---|---|
| PolyHaven | ✅ `polyhaven_runner.py` | ✅ `PolyHavenProvider.cs` | Done |
| Kenney | ✅ `kenney_runner.py` | ✅ `KenneyProvider.cs` | Done |
| AmbientCG | ✅ `ambientcg_runner.py` | ⬜ | Planned |
| Quaternius | ✅ `quaternius_runner.py` | ⬜ | Planned |
| GameIcons | ✅ `game_icons_runner.py` | ⬜ | Planned |
| FreeSound | ✅ `freesound_runner.py` | ⬜ | Planned |
| Fab.com | ✅ `fab_hybrid.py` | ⬜ | Phase 2 |
| Epic/Unreal | ✅ `epic_vault.py` | ⬜ | Phase 2 |
| Mixamo | ✅ `mixamo_auth.py` | ⬜ | Phase 2 |
| Unity | ✅ `unity_hub.py` | ⬜ | Phase 2 |
| Legendary | ✅ `legendary_bridge.py` | ⬜ | Phase 2 |
| Font | ✅ `font_runner.py` | ⬜ | Later |
| Music | ✅ `music_runner.py` | ⬜ | Later |
| VFX | ✅ `vfx_runner.py` | ⬜ | Later |
| TTS | ✅ `tts_runner.py` | ⬜ | Later |
| Vehicle | ✅ `vehicle_runner.py` | ⬜ | Later |
| Dialogue | ✅ `dialogue_runner.py` | ⬜ | Later |
| Museum | ✅ `museum_runner.py` | ⬜ | Later |
| AI Gen | ✅ 5+ runners | ⬜ | Phase 7 |
| Blender | ✅ `blender_runner.py` | ⬜ | Phase 7 |

---

## 🏗️ Architecture Target

```
Flax Editor
├── FlaxMCP (Core)          ← Chat, MCP tools, scene editing
│   └── WorkerHttpClient    ← Calls AssetWorker via HTTP
│
├── FAW (Plugin) ← HTTP server on :8790
│   ├── C# Providers         ← PolyHaven, Kenney, AmbientCG...
│   ├── C# Lanes             ← QuickImport, FullPipeline, Batch
│   └── C# Library           ← Asset catalog + search
│
└── Python Workers (:8766)  ← FastAPI HTTP server
    ├── Auth Providers       ← Fab, Epic, Unity, Mixamo
    ├── AI Generation        ← Colab, ComfyUI, Local
    └── Cleanup              ← Blender optimize, glTF convert
```
