# roman-roadmap

Use this when working on the Roman Arena proving ground or Roman shared-library packs.

## First Goal
Get one believable playable Roman fight working before expanding to full Rome city.
Do not let Roman work expand into random download hunts — every blocker must resolve to a lane + pack_id.

## Current Gate Blockers
| Slot | Preferred Bridge | Lane | CLI shortcut |
|---|---|---|---|
| `player_prefab` | Mixamo → Unity runner | `manual_browser` | `emit-browser-job --source-adapter mixamo` |
| `hud_texture` | ChatGPT Pro | `generator` | `emit-ai-bridge-job --provider chatgpt_pro` |
| `music_clip` | Mixkit / Pixabay | `direct_url` | `emit-audio-examples` |
| `sfx_library` | Freesound / OpenGameArt | `direct_url` | `emit-audio-examples` |
| `weapon_prefab` | Hunyuan3D-2 | `generator` | `run-hunyuan-batch --dry-run` |

## First-Fight Packs (Published)
1. `RA_PACK_ANM_COMBAT_SLICE_01` — combat animations
2. `RA_PACK_WPN_COMBAT_SLICE_01` — weapon mesh
3. `RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01` — arena shell
4. `RA_PACK_TRAP_SLICE_01` — spike trap

## Shared-Pack Direction
| Family | Content | Reuse scope |
|---|---|---|
| `historic_roman_materials_core` | Stone, leather, cloth, plaster, metal | All Roman games |
| `historic_roman_architecture_core` | Arena, arch, wall, stair, trim | Roman and city games |
| `historic_city_streets_core` | Street, curb, stall, awning, prop | City-era games |
| `historic_museum_props_core` | Artifacts, vessels, statues | Museum and historic games |
| `historic_tech_props_core` | Military, mechanical, tool props | Cross-era prototypes |
| `shared_human_base_rigs` | Base bodies, humanoid rigs | All human character games |
| `shared_combat_animation_baseline` | Idle, hit-react, attack clips | All combat games |

## Execution Priority Order
1. `weapon_prefab` → `run-hunyuan-batch` (quickest AI path)
2. `hud_texture` → ChatGPT Pro AI bridge
3. `music_clip` + `sfx_library` → Mixkit / Freesound direct URL
4. `player_prefab` → Mixamo browser session

## Rule
Turn every blocker into an explicit lane + pack task using the CLI.
Never let Roman proof work collapse into undocumented manual downloads.
