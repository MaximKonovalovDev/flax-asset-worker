---
description: G1–G6 quality gate enforcement rules for all AssetBoy asset packs
---

# Asset Gate Enforcement Skill

## When to Use
- Checking whether a pack is ready to publish
- Diagnosing why a gate check failed
- Choosing the right current CLI command for a gate problem
- Deciding whether to auto-fix or flag for human review

## Current Command Reality
AssetBoy's current CLI does not expose a standalone `run-gate-check` command.
Use the commands below together to enforce the gate policy in this skill.

## Gate Definitions

### G1 — Format & Naming
**Pass when:**
- File is `.glb`, `.fbx`, `.wav`, `.mp3`, `.ogg`, `.svg`, `.png`, `.ttf`, or `.otf`
- Filename: `snake_case`, ASCII only, no spaces
- Mesh prefix: `SM_` (static), `SK_` (skeletal), `T_` (texture), `M_` (material)
- Audio: `SFX_`, `MUS_`, `AMB_` prefix

**Auto-fix**: rename via Blender cleanup runner or Python string rename
**Fail action**: auto-fix then re-run packet checks

### G2 — Geometry Quality (3D assets only)
**Pass when:**
- Poly count ≤ 20k tris for standard props
- Poly count ≤ 50k tris for characters/vehicles
- No negative scale on any mesh object
- Pivot at base-center (Y-up, origin grounded)
- Scale applied (no unapplied transforms)

**Auto-fix**: `run-cleanup` / `run-blender-cleanup`
**Fail action**: simplify in Blender or re-source the asset

### G3 — Texture & Material Integrity
**Pass when:**
- At least 1 texture or material assigned
- No missing/broken texture links
- Normal map present for props > 5k tris (recommended, not hard block)
- UV islands present (not degenerate)

**Auto-fix**: Blender cleanup and texture export planning
**Fail action**: bake or relink textures before packet registration

### G4 — LOD Naming (if LODs required)
**Pass when:**
- If LODs exist: named `_LOD0`, `_LOD1`, `_LOD2`
- LOD0 = highest poly, LOD2 = lowest
- OR no LODs present for packs that do not require them

**Auto-fix**: Blender LOD generation / rename pass
**Fail action**: keep as source-only until the final reviewed pack has honest LOD coverage

### G5 — Provenance
**Pass when:**
- `provenance.json` present in pack directory
- Fields present: `pack_id`, `license`, `source_url`, `download_date`, `source_adapter`
- License is not empty or `UNKNOWN`

**Auto-fix**: generate provenance from known pack metadata
**Fail action**: block packet registration until provenance exists

### G6 — Human Visual Review
**Pass when:**
- Operator has viewed at least 1 representative asset from the pack
- Review sign-off is recorded in provenance or operator notes

**No auto-fix** — this gate requires human eyes
**Fail action**: keep the pack in review state, do not call it done

## Gate Check Command Set
```bash
# 3D packs: plan cleanup + auto-fix work
python scripts/cli.py asset-factory run-cleanup \
  --pack-id RA_PACK_WPN_COMBAT_SLICE_01 \
  --game-scope roman_arena \
  --input-dir <source_dir> \
  --asset-kind weapon \
  --dry-run

# End-to-end pack readiness from source folder to publish packet
python scripts/cli.py asset-factory prepare-pack \
  --pack-id RA_PACK_WPN_COMBAT_SLICE_01 \
  --game-scope roman_arena \
  --source-dir <source_dir> \
  --cleanup-mode auto \
  --dry-run

# Publish packet and intake validation
python scripts/cli.py asset-factory check-publish --game roman_arena
python scripts/cli.py asset-factory auto-intake --pack-id RA_PACK_WPN_COMBAT_SLICE_01 --dry-run
```

## Gate Mapping to Current Commands
- `G1-G4`: use `run-cleanup` / `run-blender-cleanup` for rename, transform, preview, validation, and export planning.
- `G5`: use `prepare-pack`, `write-packet`, or `register-packet` to ensure `provenance.json` and packet data exist.
- `G6`: manual operator review is still outside the current CLI. Record sign-off before final packet promotion.

## Gate Result States
| State | Meaning |
|---|---|
| `PASS` | Cleanup, packet, and intake checks are satisfied |
| `AUTO_FIXED` | Cleanup plan exists and can repair the issue |
| `FAIL_HUMAN` | Needs operator review or a manual DCC fix |
| `BLOCKED` | Missing provenance, payload, or packet contract data |

## Pass Rate Target
- First-pass gate rate target: **≥ 80%** across all generator lanes
- If below 80%: review prompt templates and generator settings before next batch
