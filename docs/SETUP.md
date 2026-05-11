# flax-asset-worker — Setup Guide

> Walks a new operator from zero to a working asset acquisition pipeline.
> Path B v1.5.3+ (2026-05-11). Tested on Windows 11 + Python 3.12 + RTX 3050 6GB.

---

## TL;DR — 60-second smoke

```powershell
git clone https://github.com/flax-game-studio/flax-asset-worker.git
cd flax-asset-worker
python -m pip install -r Python/assetboy/requirements.txt
$env:PYTHONPATH = "$(pwd)\Python"
python -m assetboy.canary --probe polyhaven
# -> [OK ] polyhaven: <N> natural-texture assets
```

If that prints `[OK]`, you're ready. Now keep reading for the full setup.

---

## 1. Python sidecar — required for everything else

### Install dependencies

```powershell
cd flax-asset-worker\Python\assetboy
python -m pip install -r requirements.txt
# Also needed for Mixamo / Unity Hub browser flows:
python -m playwright install chromium
```

### Sanity-check the install

```powershell
$env:PYTHONPATH = "C:\flax\flax-asset-worker\Python"   # adjust to your clone
python -m assetboy.cli --help
```

Expected output: 7 sub-apps listed (`fab library import unity epic gen pack`).

### Run the test suite (optional but recommended)

```powershell
cd C:\flax\flax-asset-worker
python -m pytest Tests/python -q --tb=no
# Expected: 238 passed, 1 skipped in ~17s
```

---

## 2. Configure your workspace

The pipeline writes downloads + generated assets to an "asset library" that
defaults to `<repo>/artifacts/library/FlaxAssetLibrary/`. To use a different
location (e.g. your actual Flax game project), set:

```powershell
# Option A: env var (recommended; per-shell)
$env:ASSETBOY_FLAX_REPO_ROOT = "C:\path\to\your\flax-game-project"

# Option B: workspace.json (persistent across shells)
@'
{
  "flax_repo_root": "C:\\path\\to\\your\\flax-game-project"
}
'@ | Out-File -FilePath C:\flax\flax-asset-worker\assetboy.workspace.json -Encoding utf8
```

**Self-hosting fallback (v1.3+):** if neither is set, the repo uses its own
root as the workspace. Useful for quick smoke runs; for real game work,
configure properly.

---

## 3. Run the external-API canary

```powershell
python -m assetboy.canary
```

Probes 5 external surfaces:
1. **PolyHaven** — public CC0 REST API (always available)
2. **Fab.com** — needs your fab auth state (run `python -m assetboy.cli fab auth` first)
3. **Epic Launcher** — reads local SQLite at `C:\ProgramData\Epic\...` (skip if no Epic)
4. **Unity Hub** — reads DPAPI-encrypted tokens (skip if no Unity Hub)
5. **ComfyUI** — checks `:8188` is alive (skip if no ComfyUI)

Each probe returns OK / RED with timing. State written to
`state/canary/canary_status.json` for tooling consumption.

### Optional: schedule weekly canary

```powershell
pwsh scripts\install-canary-scheduler.ps1
# Registers a weekly Windows Task Scheduler job.
```

---

## 4. Browse + run recipes

```powershell
python -m assetboy.cli pack list-recipes
# -> 4 recipes available:
#    sandbox_one_pack_smoke         1 pack   (PolyHaven CC0 brick wall)
#    sandbox_generator_smoke        4 packs  (all 4 generator providers)
#    primitive_tech_first_playable  9 packs  (forest survival demo)
#    roman_arena_first_playable    14 packs  (gladiator arena demo)
```

### Dry-run a recipe (no network)

```powershell
python -m assetboy.cli pack from-recipe sandbox/one_pack_smoke.yaml --dry-run
```

### Real-run a recipe (drives actual downloads/generation)

```powershell
python -m assetboy.cli pack from-recipe sandbox/one_pack_smoke.yaml
```

Output legend:
- `[OK ]` — pack completed end-to-end
- `[WAIT]` — pack paused; operator must drop files (manual_browser) OR runner config (generator)
- `[RED ]` — pack failed; check the error

---

## 5. Configure provider authentication (optional, per-provider)

### 5.1 Fab.com (manual_browser lane)

```powershell
# First-time setup: opens a real browser, you log in.
python -m assetboy.cli fab auth --allow-browser

# Subsequent runs use the saved auth state:
python -m assetboy.cli fab auth-status   # exit 0 = authed; 1 = needs re-auth
```

Fab's session lasts a few weeks typically; re-auth when needed.

### 5.2 Unity Hub (manual_browser lane)

```powershell
# 1. Open Unity Hub + sign in (one-time).
# 2. Verify:
python -m assetboy.cli unity status
# Should show DPAPI decrypt OK + access token present.
```

The Python side reads Unity Hub's encrypted tokens from
`%APPDATA%\UnityHub\encryptedTokens.json` via DPAPI.

### 5.3 Epic Launcher (manual_browser lane)

```powershell
# 1. Install Epic Games Launcher + sign in.
# 2. Claim some assets so VaultCache has entries.
# 3. Verify:
python -m assetboy.cli epic status
# Should show schema version + N vault items.
```

### 5.4 Mixamo

Auth via Playwright + Adobe login is needed for Mixamo flows. Browser flow
is handled by the standalone `mixamo_auth.py` provider; covered by tests
but full E2E setup is your call.

---

## 6. Configure generators (for the generator lane)

### 6.1 ComfyUI

```powershell
# 1. Install ComfyUI (any reasonable install -- portable or full)
# 2. Start it: ensure it listens on http://127.0.0.1:8188
# 3. Verify:
python -m assetboy.cli gen comfyui status
# -> gen_comfyui_running=true; gen_comfyui_gpu_name=...
```

Recipe packs with `provider: comfyui` will then route through ComfyUI.

### 6.2 Stable Diffusion (sd.cpp / local_image)

```powershell
# 1. Build or download sd.exe from https://github.com/leejet/stable-diffusion.cpp
# 2. Download SD 1.5 model file (or SDXL if you have VRAM).
# 3. Configure paths in <repo>/profiles/sd_cpp.json (or env vars).
# 4. Run:
python -m assetboy.cli gen sd run "test prompt"
```

Default tuned for RTX 3050 6GB (SD 1.5, 512x512, 20 steps).

### 6.3 Stable Audio Open Small

```powershell
# 1. Download model from https://huggingface.co/stabilityai/stable-audio-open-small
# 2. Set env vars:
$env:STABLE_AUDIO_MODEL_DIR = "C:\path\to\model\dir"
$env:STABLE_AUDIO_RUNNER_BIN = "C:\path\to\your\stable_audio_cli.py"
# 3. Recipe packs with provider: stable_audio_open_small will route through it.
```

The runner binary contract:
```
<bin> --model <model_dir> --prompt "<text>" --duration <s> --out <wav_path>
```

You write this small shim against Stability's diffusers/transformers pipeline.
Path B v1.4.1's `stable_audio_runner.py` deliberately doesn't bundle torch
to keep FAW's import graph light — runner config is your responsibility.

---

## 7. Build + load the C# plugin (for Flax editor integration)

```powershell
# 1. Copy Source/, Config/, and FAW.flaxplugin into:
#    <your-flax-game>/Source/FAW/
# 2. Add `FAW` to your project's plugin references in .flaxproj
# 3. Build:
cd <your-flax-game>
dotnet build
# 4. Open Flax Editor -- the plugin starts an HTTP server on :8790.
```

### Verify HTTP server

```powershell
curl http://localhost:8790/api/v1/health
# -> {"status":"ok", "providers":<N>, ...}
```

### Available endpoints (Path B v1.5.0+)

```
GET  /api/v1/health
POST /api/v1/providers/list
POST /api/v1/providers/{id}/download
POST /api/v1/lanes/list
POST /api/v1/lanes/{id}/execute             (only quick-import implemented)
POST /api/v1/library/search
POST /api/v1/library/install
POST /api/v1/library/ready
POST /api/v1/recipes/list                   (NEW in v1.5.0)
POST /api/v1/recipes/run                    (NEW in v1.5.0)
GET  /api/v1/packs/{pack_id}/status         (NEW in v1.5.0)
GET  /api/v1/canary/status                  (NEW in v1.5.0)
```

The 4 NEW endpoints subprocess to `python -m assetboy.cli` and return
the JSON output. See `docs/MONOREPO_FACADE_DESIGN.md` for the flax-mcp
facade integration plan.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: assetboy` | PYTHONPATH not set | `$env:PYTHONPATH = "<repo>\Python"` |
| `pip install` fails on `nodriver` | needs Microsoft Visual C++ Build Tools | Install MS VC++ Build Tools 2019+ |
| `playwright install chromium` slow | first-time download ~300MB | Wait; it's a one-time cost |
| Fab auth-status: `auth_state_exists=false` | First time setup | Run `python -m assetboy.cli fab auth --allow-browser` |
| Unity status: `decrypt_failed` | Unity Hub not signed in | Open Unity Hub + sign in |
| Epic status: `vault_db_not_found` | Epic Launcher not installed | Install Epic Games Launcher |
| ComfyUI status: `connection_refused` | ComfyUI not running | Start ComfyUI on :8188 |
| `pack from-recipe` all RED | Workspace not configured | `$env:ASSETBOY_FLAX_REPO_ROOT = "<your-flax-project>"` |
| Test suite has skipped tests | Expected | 1 skip is intentional (legacy emit-unity-download-wave CLI command, deleted) |

---

## 9. Where things live (filesystem map)

```
flax-asset-worker/
├── Python/assetboy/
│   ├── cli/              ← Typer CLI (7 sub-apps; v1.5.x)
│   ├── canary.py         ← Weekly smoke test (5 probes)
│   ├── data/             ← 16 parked YAML files (Roman specs + presets)
│   ├── execution/        ← 8 KEEP runners (polyhaven/kenney/ambientcg/freesound/comfyui/local_image/stable_audio/blender/mixamo_glb/gdrive_mcp)
│   ├── providers/        ← 14 KEEP providers (Fab/Epic/Unity/Mixamo/bridge_registry/lanes/quixel_scanner/library_map/...)
│   ├── workflows/        ← pack_pipeline + acquisition_router + gate_report
│   └── library/          ← paths, asset_metadata, packet_writer, etc.
├── Source/               ← C# plugin (Flax GamePlugin)
│   ├── Core/             ← WorkerHttpServer (:8790), config, Python bridge
│   ├── Providers/        ← C# providers (PolyHaven + Kenney)
│   └── Routes/           ← REST handlers (Provider/Lane/Library/Recipe/Canary)
├── Config/               ← providers.json + categories.json
├── recipes/
│   ├── primitive_tech/   ← 9-pack forest survival demo recipe
│   ├── roman/            ← 14-pack gladiator arena demo recipe
│   └── sandbox/          ← 2 smoke recipes (one_pack + generator_smoke)
├── Tests/python/         ← 238 tests
├── docs/                 ← This guide + COMMIT_READY + HEARTBEAT + MONOREPO_FACADE_DESIGN
├── state/                ← Per-machine runtime state (gitignored)
│   ├── canary/           ← canary_status.json + history
│   └── pack_pipeline/    ← Pack execution ledgers
├── README.md
├── ROADMAP.md
└── requirements.txt (under Python/assetboy/)
```

---

## 10. Going further

- Read **`docs/COMMIT_READY-assetboi.md`** for the per-slice history.
- Read **`docs/HEARTBEAT-assetboi.md`** for the operator-friendly state summary.
- Read **`docs/MONOREPO_FACADE_DESIGN.md`** if integrating into flax-mcp.
- Read **`docs/PATH_B_DAY11_PLAN.md`** for follow-up slice plans.
- Check **`Python/assetboy/data/*.yaml`** for parked legacy data (Roman specs, generator presets).
- Tests in **`Tests/python/test_*.py`** are good documentation by example.

---

(End of guide — Path B v1.5.3+ 2026-05-11)
