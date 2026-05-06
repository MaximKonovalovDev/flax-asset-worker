# flax-asset-worker

Modular asset pipeline plugin for Flax Engine. C# hub (HTTP server on :8790) + Python worker lane.

> **Renamed 2026-05-06:** previously published as `diklaaltman91-ux/faw`;
> now lives at `flax-game-studio/flax-asset-worker` alongside the
> `flax-mcp` monorepo and its sister plugins. The repo is intentionally
> kept separate from the monorepo because it runs out-of-process and
> ships a Python sidecar - see `flax-mcp/AGENTS.md` and ADR 013 for the
> rationale.

## Architecture

```
Flax Editor
├── FlaxMCP (Core)          ← Chat, MCP tools, scene editing
│   └── WorkerHttpClient    ← HTTP → AssetWorker
│
├── FAW (C#)    ← HTTP server on :8790
│   ├── Source/Providers     ← C# providers (PolyHaven, Kenney, ...)
│   ├── Source/Pipeline      ← Lanes (QuickImport, FullPipeline, Batch)
│   └── Source/Routes        ← REST API (/providers, /lanes, /library)
│
└── Python Workers           ← Python/assetboy/ (port planned :8766)
    ├── providers/            ← Auth-heavy flows (Fab, Epic, Unity, Mixamo)
    ├── execution/            ← Blender, Colab, ComfyUI runners
    └── cli.py                ← Legacy CLI (80+ commands)
                                               ├── Categories (Texture, Model, Audio, Animation...)
                                               └── Library (Catalog, Installed, Search)
```

## Quick Start

1. Copy this folder to your Flax project's `Source/` directory
2. Add `FAW` to your project's plugin references
3. Build the project
4. The HTTP server starts automatically on `http://localhost:8790`

## API

```
POST /api/v1/providers/list              → List providers
POST /api/v1/providers/{id}/download     → Download asset
POST /api/v1/providers/{id}/search       → Search provider
POST /api/v1/lanes/list                  → List lanes
POST /api/v1/lanes/{id}/execute          → Execute lane
POST /api/v1/library/search              → Search library
POST /api/v1/library/install             → Install asset
POST /api/v1/library/ready               → List ready assets
GET  /api/v1/health                      → Health check
```

## Test with curl

```bash
# Health check
curl http://localhost:8790/api/v1/health

# List providers
curl -X POST http://localhost:8790/api/v1/providers/list -H "Content-Type: application/json" -d "{}"

# Download from PolyHaven
curl -X POST http://localhost:8790/api/v1/library/install \
  -H "Content-Type: application/json" \
  -d '{"asset_id":"brick_wall_01","provider":"polyhaven","category":"texture","name":"Brick Wall"}'

# List ready assets
curl -X POST http://localhost:8790/api/v1/library/ready -H "Content-Type: application/json" -d "{}"
```

## Providers

| ID | Name | Auth | Categories |
|---|---|---|---|
| polyhaven | PolyHaven | Free | texture, model, hdr |
| kenney | Kenney | Free | texture, model, audio, sprite, font |
| fab | Fab.com | Required | texture, model, audio, material |
| epic | Epic Games | Required | texture, model, audio |
| mixamo | Mixamo | Required | animation |
| freesound | FreeSound | API Key | audio |

## Configuration

Config files in `Config/`:
- `providers.json` — Provider credentials and settings
- `categories.json` — Category routing rules
- `lanes.json` — Lane definitions

## License

MIT
