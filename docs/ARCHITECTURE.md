# FAW Architecture

## Overview

FAW is a modular asset pipeline plugin for Flax Engine. It runs an HTTP server
inside the Flax Editor process, exposing a clean JSON-RPC API for asset operations.

## Design Principles

1. **Modular providers** — Each asset source (Fab, Epic, PolyHaven, etc.) is a separate class
   implementing `IAssetProvider`. Add/remove providers without touching core code.
2. **Pipeline lanes** — Processing steps (download, validate, convert, import) are configurable
   lanes. Swap lanes based on asset complexity.
3. **Category routing** — Assets are categorized (texture, model, audio) and routed to the
   best provider automatically.
4. **Asset library** — All downloaded/imported assets are tracked with metadata, SHA-256,
   and provenance. Never lose track of where an asset came from.
5. **HTTP/JSON-RPC** — All communication is HTTP. No Process.Start, no stdout parsing,
   no brittle CLI bridges.

## Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ Flax Editor Process                                          │
│                                                              │
│  ┌─────────────────┐     HTTP/JSON-RPC     ┌──────────────┐ │
│  │   FlaxMCP       │ ────────────────────► │ AssetWorker  │ │
│  │   (Chat, Tools) │ ◄──────────────────── │ (Port 8790)  │ │
│  └─────────────────┘                       └──────┬───────┘ │
│                                                   │          │
│                          ┌────────────────────────┼─────┐    │
│                          │   Provider Registry    │     │    │
│                          │  ┌──────┐ ┌────────┐  │     │    │
│                          │  │Fab   │ │PolyHav │  │     │    │
│                          │  └──┬───┘ └───┬────┘  │     │    │
│                          │     │          │        │     │    │
│                          │  ┌──┴──────────┴──┐     │     │    │
│                          │  │  Lane Executor   │    │     │    │
│                          │  │ Quick | Full    │     │     │    │
│                          │  └───────┬─────────┘     │     │    │
│                          │          │                │     │    │
│                          │  ┌───────┴─────────┐     │     │    │
│                          │  │  Asset Library   │     │     │    │
│                          │  └─────────────────┘     │     │    │
│                          └──────────────────────────┘     │    │
└──────────────────────────────────────────────────────────────┘
```

## Provider Interface

```csharp
public interface IAssetProvider
{
    string Id { get; }                    // "polyhaven", "fab"
    string Name { get; }                  // "PolyHaven"
    AssetCategory[] SupportedCategories { get; }
    bool RequiresAuth { get; }

    Task<DownloadResult> DownloadAsync(string assetId, ProviderConfig config);
    Task<List<AssetSearchResult>> SearchAsync(string query, AssetCategory? category);
    Task<bool> ValidateAsync(string localPath);
}
```

## Lane Pipeline

```csharp
public interface ILane
{
    string Id { get; }                    // "quick-import"
    LaneStepType[] Steps { get; }         // [Download, Validate, Import]

    Task<LaneResult> ExecuteAsync(LaneInput input);
}
```

**Steps:** Download → Validate → Optimize → Convert → Import → Cleanup

**Lanes:**
- `quick-import` — Download → Validate → Import (fast)
- `full-pipeline` — All 6 steps (thorough)
- `batch-process` — Download multiple → Validate all → Import all

## HTTP API

All endpoints return `{ "success": bool, "data": {}, "error": "..." }`.

| Method | Path | Purpose |
|---|---|---|
| GET | /api/v1/health | Server health check |
| POST | /api/v1/providers/list | List all registered providers |
| POST | /api/v1/providers/{id}/download | Download from provider |
| POST | /api/v1/providers/{id}/search | Search provider catalog |
| POST | /api/v1/lanes/list | List available processing lanes |
| POST | /api/v1/lanes/{id}/execute | Execute a processing lane |
| POST | /api/v1/library/search | Search installed assets |
| POST | /api/v1/library/install | Download + import + record |
| POST | /api/v1/library/ready | List ready-to-use assets |

## What We Reused From Existing Code

| Component | Source | Status |
|---|---|---|
| PolyHaven download logic | `scripts/asset_factory/src/assetboy/providers/` | Ported to C# |
| Kenney download logic | `scripts/asset_factory/src/assetboy/providers/` | Ported to C# |
| Category routing | `scripts/asset_factory/src/assetboy/library/` | Ported to JSON config |
| MCP tool pattern | `FlaxMCP/Tools/Assets/GenerateImageTool.cs` | Reused in bridge |
| HTTP client pattern | `GenerateImageTool.cs` | Same pattern, dedicated class |

## What We Threw Away

| Component | Reason |
|---|---|
| `Process.Start("python -m assetboy.cli")` | Replaced with HTTP |
| `assetboy/cli.py` (25k+ lines) | Monolithic, brittle |
| `External/AssetBoy/Brain/` | Unused by C# |
| Duplicate C# validation | Python owned it, now C# owns it |

## Future: Chat Integration

```
User: "Get me a brick wall texture"
  → Chat LLM parses: category=texture, query=brick wall
  → FlaxMCP tool call: POST /api/v1/library/install
  → AssetWorker: ProviderRegistry → PolyHavenProvider.DownloadAsync()
  → AssetWorker: QuickImportLane.ExecuteAsync()
  → Response: { success: true, output_path: "Content/Textures/brick_wall.png" }
  → Chat: "✅ Brick wall texture imported to Content/Textures/"
```
