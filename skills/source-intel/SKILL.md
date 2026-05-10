# source-intel

Use this when choosing where an asset should come from and which lane to use.

## Preferred Order
1. direct-download CC0 and museum/open-access sources
2. manual browser sources with usable licenses
3. generators only for missing assets

## Repo Inspiration Rule
When an upstream repo is only a study source, use the same triage language as the repo-ingestion docs:
- `best steals now` -> a clear local target exists and should be absorbed immediately
- `good but later` -> the repo fits, but it should wait behind higher-value slices
- `steal only the goodies` -> keep one pattern, gate, or workflow and stop before copying the whole stack

If the repo has no clear local target, do not promote it past study mode.

## Strong Sources — Direct Download, Clean License
| Source | Content | License | Runner |
|---|---|---|---|
| Kenney.nl | 3D props, vehicles, UI, VFX, characters | CC0 | `kenney_runner`, `vehicle_runner`, `vfx_runner` |
| Quaternius | Low-poly characters, weapons, environments | CC0 | `quaternius_runner` |
| Google Fonts | TTF/OTF game fonts (medieval, sci-fi, pixel, horror) | OFL-1.1 | `font_runner` |
| ambientCG | PBR materials, HDRIs | CC0 | `direct_url_queue` |
| game-icons.net | 3,000+ SVG game icons | CC BY 3.0 | `game_icons_runner` |
| Smithsonian Open Access | 3D scans — weapons, armour, pottery, busts | Public Domain | `museum_runner` |
| NASA 3D Resources | Spacecraft, rovers, satellites | Public Domain | `museum_runner` |
| Cleveland Museum of Art | Art objects, artifacts | CC0 | `museum_runner` |
| OpenGameArt | VFX sprites, SFX, music | CC0/CC-BY | `vfx_runner` (OGA targets) |

## Manual/Browser Sources — Require Provenance
| Source | Content | Notes |
|---|---|---|
| Fab | Props, architecture, characters | Epic login; run screenshot + format review before claim/download, and classify each listing as `batch-direct`, `library-or-purchase-required`, or `unreal-engine-only` |
| Unity Asset Store | Characters, animation, props | Unity login; throwaway project export |
| Mixamo | Characters, animation clips (walk, run, idle, social) | Adobe login; verify character/clip preview before export |
| Poly Haven | HDRIs, PBR textures, 3D models, terrain, skyboxes | CC0 source, but current repo still emits Playwright/browser job specs for preset waves |
| Sketchfab | Mixed 3D, CC0 museum scans | Only clean-license finds |
| Museum pages | 3D scans, artifacts | Check license per item |
| Freesound | SFX, ambient, voice | CC0/CC-BY only; account required |
| Zapsplat | SFX, impact sounds | Free account; commercial OK |

## Browser Review Rule
Before calling a manual/browser pick good, verify all of these:
1. screenshot the live listing
2. check hero media quality
3. check included formats
4. check price/free state
5. check license terms or site notes
6. check download access friction (`batch-direct`, `library-or-purchase-required`, `unreal-engine-only`)

Use `browser-source-review` when the page is promising but not yet trusted.

## Generator Guidance
| Generator | Best for | Lane | Notes |
|---|---|---|---|
| Hunyuan3D-2 | Weapons, hard-surface props | `generator` → Colab | img-to-3D > text-to-3D |
| TRELLIS | Props, architecture detail | `generator` → Colab | Good for modular env pieces |
| AnimationGPT | **Combat** animation clips ONLY | `generator` → Colab | sword, axe, magic, dodge, death — NOT walk/run |
| MusicGen | Game music beds | `generator` → Colab | W5 worker |
| AudioLDM2 | SFX gaps, ambience | `generator` → Colab | fallback for Freesound gaps |
| edge-tts | NPC dialogue lines | `generator` | Local execution, canonical lane stays `generator` |
| ComfyUI | UI textures, material variants | `generator` | Local execution at 8188, canonical lane stays `generator` |
| sd-cli.exe | Icons, HUD elements, 2D | `generator` | Local execution, canonical lane stays `generator` |

## Font Source Hierarchy
1. `google_fonts` bridge — direct TTF from GitHub, OFL, commercial OK
2. Font Library (fontsquirrel.com) — OFL/GPL, manual download
3. Manual: purchase from commercial foundry if specific style needed

## Audio Sources
1. Mixkit (direct URL, royalty-free, no login)
2. Musopen (direct URL, CC0 recordings of classical — great for Roman)
3. ccMixter (CC-BY, check per track)
4. Freesound (CC0/CC-BY per clip, account required)
5. OpenGameArt (CC0/CC-BY, VFX sounds and basic SFX)
6. edge-tts (NPC dialogue — free, no API key)
7. MusicGen / AudioLDM2 via Colab (generator fallback)

## Avoid
1. Random low-quality asset scraping
2. Unclear licenses or no provenance path
3. Provider-specific flows that break the shared packet contract
4. MetaHuman without per-pack license snapshot and provenance check
5. Shadertoy directly — GLSL shaders need significant adaptation for Flax
