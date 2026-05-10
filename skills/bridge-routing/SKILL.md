---
description: Intelligent bridge routing and gate-fail retry logic for the AssetBoy asset pipeline
---

# Bridge Routing Skill

## When to Use
- Deciding which bridge to try for a given asset category
- A batch came back with gate failures and needs to be re-routed
- A provider is unavailable or rate-limited and needs a fallback
- Planning a new recipe kit and selecting source priorities

## Core Routing Table

| Category | Primary Bridge | Fallback 1 | Fallback 2 | Generator Lane |
|---|---|---|---|---|
| PROP (3D) | `sketchfab` | `kenney` | `quaternius` | `hunyuan3d2_3d` |
| WEAPON | `smithsonian_museum` | `quaternius` | `fab_browser` | `hunyuan3d2_3d` |
| CHARACTER_BASE | `mixamo_browser` | `quaternius` | `kenney` | `hunyuan3d2_3d` |
| ARCHITECTURE | `sketchfab` | `kenney` | `blenderkit` | `trellis_3d` |
| MATERIAL | `poly_haven` | `ambientcg` | `quixel_megascans` | `comfyui_local_ui` |
| UI_HUD | `kenney` | `game_icons_net` | `comfyui_local_ui` | `hunyuan_image_colab_ui` |
| ICON | `game_icons_net` | `kenney` | `fab_browser` | `comfyui_local_ui` |
| SFX | `freesound_api` | `zapsplat` | `gamesounds_xyz` | `audioldm2_audio` |
| MUSIC | `musopen_classical` | `ccmixter_music` | `mixkit_audio` | `musicgen_audio` |
| ANIMATION | `mixamo_browser` | `animationgpt_colab` | `quaternius` | `animationgpt_colab` |
| VEHICLE | `kenney_vehicle` | `sketchfab` | `nasa_3d_open` | `hunyuan3d2_3d` |
| TERRAIN | `polyhaven_terrain` | `ambientcg` | `kenney` | `comfyui_local_ui` |
| MUSEUM_PROP | `smithsonian_museum` | `sketchfab` | `nasa_3d_open` | `hunyuan3d2_3d` |
| FONT | `google_fonts` | — | — | — |
| VFX | `kenney_vfx` | `polyhaven_terrain` | — | `comfyui_local_ui` |
| SKYBOX | `polyhaven_skybox` | `poly_haven` | — | `comfyui_local_ui` |
| DIALOGUE | `edge_tts_dialogue` | `elevenlabs_dialogue` | — | `audioldm2_audio` |
| SHADER | `shader_manual` | — | — | — |

## Gate-Fail Retry Logic (ReAct Pattern)

When a batch returns gate failures, apply this decision tree:

```
G1 FAIL (naming/format) → re-run blender_cleanup step, don't regenerate
G2 FAIL (poly > limit)  → re-submit generator with --low_poly_mode or --simplify
G3 FAIL (no texture)    → route to blender normal-bake step first, then re-gate
G4 FAIL (LOD missing)   → skip if not required for scope, else add LOD suffix and re-gate
G5 FAIL (provenance)    → write provenance.json from template, re-gate
G6 FAIL (visual review) → flag for human review queue, do NOT auto-retry
```

## Bridge Priority Rules
1. **Free-first**: CC0/free direct sources BEFORE any paid bridge
2. **No auth first**: direct URL downloads BEFORE browser/manual lanes
3. **Generator last**: Colab GPU lanes only when no free source covers the gap
4. **Shared packs**: prefer multi-game sources (`kenney`, `game_icons_net`) over game-specific downloads

## Routing Commands
```bash
# Check which bridges cover a category
python scripts/cli.py asset-factory list-bridges --category WEAPON

# Trigger fallback for a failed pack
python scripts/cli.py asset-factory requeue-pack --pack-id <id> --bridge <fallback_bridge>
```

## Notes
- `blenderkit` requires Blender open and add-on installed — not automatable headless
- `quixel_megascans` requires Epic Games login — same session as `fab_browser`
- `nasa_3d_open` = public domain — no restrictions, great for sci-fi scope only
- `google_fonts` = OFL-1.1 — commercial use OK, no ingame attribution required
- `animationgpt_colab` = COMBAT ONLY — walk/run/idle must go to `mixamo_browser`
- `edge_tts_dialogue` requires `pip install edge-tts` — free, no API key
- `elevenlabs_dialogue` requires `ELEVENLABS_API_KEY` and optional voice-id env overrides; use only when hosted provider usage is approved
- `shader_manual` = no auto-download yet — Phase 4. Collect .flax shaders manually
