# AssetBoy Skills Index

These are the local starter skills for chats opened from the repo-local asset workspace at `scripts/asset_factory/`.

## Read First
1. `..\knowledge\BOOTSTRAP_CONTEXT.md`
2. `..\docs\PIPELINE_GUIDE.md`

## Skills

### Domain Skills
1. `flax-asset-consumer`
   - file: `flax-asset-consumer\SKILL.md`
   - use for: downstream Flax boundary, packet contract, intake/proof split
2. `source-intel`
   - file: `source-intel\SKILL.md`
   - use for: source choice, licensing posture, provider-lane choice
3. `browser-source-review`
   - file: `browser-source-review\SKILL.md`
   - use for: live Fab/Mixamo/Poly Haven screenshot review, format check, and grab-now vs skip ranking
4. `roman-roadmap`
   - file: `roman-roadmap\SKILL.md`
   - use for: Roman-first proof priorities and shared-pack planning

### Orchestration Skills
5. `pipeline-orchestration`
   - file: `pipeline-orchestration\SKILL.md`
   - use for: full production run from blocker or family plan to reviewed packet
6. `colab-batch-orchestration`
   - file: `colab-batch-orchestration\SKILL.md`
   - use for: Colab session health, retries, batch planning
7. `bridge-routing`
   - file: `bridge-routing\SKILL.md`
   - use for: internal category routing and fallback chains

### Quality Skills
8. `asset-gate-enforcement`
   - file: `asset-gate-enforcement\SKILL.md`
   - use for: gate rules and pass criteria
9. `pack-verification-loop`
   - file: `pack-verification-loop\SKILL.md`
   - use for: pre-publish checklist and recovery paths
10. `continuous-learning`
   - file: `continuous-learning\SKILL.md`
   - use for: prompt improvement, source retirement, and weekly gap analysis

### DCC Skills
11. `blender-mcp-automation`
   - file: `blender-mcp-automation\SKILL.md`
   - use for: Blender MCP cleanup, preview capture, validation, LOD generation, and export guidance

## Fast Routing
1. upstream/downstream boundary question -> `flax-asset-consumer`
2. source and license choice -> `source-intel`
3. live Fab/Mixamo/Poly Haven review -> `browser-source-review`
4. which bridge to use -> `bridge-routing`
5. Roman-first priority question -> `roman-roadmap`
6. publish-readiness question -> `pack-verification-loop`
7. Blender cleanup or DCC QA question -> `blender-mcp-automation`

## Category Mapping

AssetBoy now speaks in 13 upstream categories.
Internal routing can stay more detailed.

| Upstream category | Internal routing buckets |
|---|---|
| `materials_textures` | `material`, `skybox` |
| `environment_architecture` | `architecture`, `prop` |
| `terrain_inputs` | `terrain` |
| `characters` | `character_base` |
| `weapons_props` | `weapon`, `prop` |
| `animations` | `animation` |
| `audio_sfx` | `sfx` |
| `music` | `music` |
| `ui_source` | `ui_hud`, `icon`, `font` |
| `vfx_source` | `vfx` |
| `vehicles_machines` | `vehicle` |
| `dialogue_voice` | `dialogue` |
| `museum_reference` | `museum_prop` |

Support-only internal route:
`shader` stays downstream/support work, not a primary upstream AssetBoy category.
