---
description: Full pipeline orchestration — from Roman blockers or source packs to published packets using the commands that exist today.
---

# Pipeline Orchestration Skill

## When to Use
- Starting a new asset production run for a game scope
- Planning what to source vs what to generate
- Coordinating source lanes, cleanup, and packet registration
- Deciding the order of operations across categories

## Orchestration Flow

```
1. READ CURRENT ROMAN GAPS
   └─ python scripts/cli.py asset-factory print-pack-targets
   └─ python scripts/cli.py asset-factory roman-blockers
   └─ Outputs: honest pack targets + unresolved blocker slots

2. PLAN THE SOURCE WAVE
   └─ python scripts/cli.py asset-factory run-bulk --profile <profile> --game-scope <scope> --dry-run
   └─ Pull existing source packs first, then only source what is still missing

3. REVIEW BROWSER PICKS BEFORE CLAIMING
   └─ For Fab / Mixamo / Poly Haven manual picks, capture screenshots and verify formats first
   └─ Rank each pick: grab_now / manual_later / skip

4. DISPATCH SOURCE LANES
   ── 3D Assets ──────────────────────────────────────────────────
   └─ run-bulk --profile kenney_presets
   └─ run-bulk --profile quaternius_presets
   └─ run-bulk --profile museum_presets
   └─ run-bulk --profile vehicle_presets
   ── 2D / Audio ──────────────────────────────────────────────────
   └─ run-bulk --profile font_presets
   └─ run-bulk --profile vfx_presets
   └─ run-bulk --profile game_icons
   └─ run-dialogue-batch --game-scope <scope>
   └─ run-skybox-batch / run-terrain-batch for current Poly Haven preset waves

5. DISPATCH GENERATOR LANES
   └─ run-animationgpt --use-presets
   └─ run-colab-batch --batch-file <prompt_batch.json>
   └─ run-comfyui-batch for local texture/material gaps
   └─ run-local-image-batch for local UI/icon gaps

6. CLEAN UP 3D OUTPUTS
   └─ python scripts/cli.py asset-factory run-cleanup --pack-id <id> --input-dir <source_dir> --dry-run
   └─ python scripts/cli.py asset-factory run-blender-cleanup --pack-id <id> --input-dir <source_dir>
   └─ The emitted Blender MCP steps cover cleanup, screenshots, validation, and export

7. ADVANCE ONE PACK WITH THE LEDGER
   └─ python scripts/cli.py asset-factory prepare-pack --pack-id <id> --source-dir <source_dir> --cleanup-mode auto --dry-run
   └─ rerun without --dry-run once the source exists
   └─ if cleanup/export is manual, rerun with --resume after artifacts land

8. CHECK PUBLISH / INTAKE READINESS
   └─ python scripts/cli.py asset-factory pack-status --pack-id <id> --game-scope <scope>
   └─ python scripts/cli.py asset-factory check-publish --game <scope>
   └─ python scripts/cli.py asset-factory auto-intake --pack-id <id> --dry-run

9. REGISTER DIRECTLY WHEN NEEDED
   └─ python scripts/cli.py asset-factory register-packet --pack-id <id> --game-scope <scope> --source-dir <source_dir>
   └─ Use this when you already have a cleaned source folder with provenance.json
```

## Parallelism Rules
- Steps 3 and 4 run simultaneously — don't wait for generators before starting source lanes
- Multiple categories can run at once across different workers
- Blender cleanup queue processes independently as results arrive
- Fonts, VFX, Icons, Dialogue usually skip Blender and go straight to provenance + packet checks

## Priority Order Within a Scope
1. Complete any packs already in progress
2. Weapons + Characters first
3. Environment/Architecture + Terrain second
4. UI/Icons/Audio/Fonts/VFX third
5. Materials/Textures last
6. AnimationGPT after character rigs are confirmed

## Scope Bootstrap
```bash
# 1. Check current workspace truth
python scripts/cli.py asset-factory status

# 2. Inspect current Roman targets / blocker slots
python scripts/cli.py asset-factory print-pack-targets
python scripts/cli.py asset-factory roman-blockers

# 3. Dry-run the source wave you want to start
python scripts/cli.py asset-factory run-bulk --profile kenney_presets --game-scope <new_scope> --dry-run
```

## Notes
- Shared library reuse is still the largest multiplier — do not regenerate blindly
- `prepare-pack`, `pack-status`, and `get-job-status` are the current CLI control surface for pack flow
- AnimationGPT BVH output still needs Blender-side retarget / export work before Flax intake
- Dialogue MP3s skip geometry cleanup, but still need provenance and packet registration
