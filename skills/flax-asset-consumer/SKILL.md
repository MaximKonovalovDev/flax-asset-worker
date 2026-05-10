# flax-asset-consumer

Use this when the task depends on what Flax should consume versus what the repo-native asset factory should prepare.

## Core Rules
1. Flax assembles scenes and gameplay.
2. The repo-native asset factory prepares reviewed packets and shared library packs.
3. Do not invent a second asset contract.

## Keep Inside Flax
1. scene assembly
2. prefabs
3. lighting and post
4. gameplay scripts and UI wiring
5. navmesh, collisions, triggers
6. animation hookup and VFX/audio placement

## Keep Outside Flax (asset factory job)
| Asset type | asset factory action |
|---|---|
| Hero meshes, props, weapons | acquire → Blender cleanup → publish |
| Modular architecture | acquire → Blender cleanup → publish |
| Characters and clothing | acquire (Mixamo/engine bridge) → cleanup → publish |
| Museum scans | download → provenance → publish |
| Texture/material packs | download → review → publish |
| Audio clips | download → review → publish |
| Non-trivial animation clips | acquire (Mixamo/AnimationGPT) → review → publish |
| Generated assets | Colab run → Blender cleanup → provenance → publish |

## Contract
| Lane | Where it lands |
|---|---|
| `direct_url` | `artifacts/quality/asset-download-jobs/queue.csv` |
| `manual_browser` | `FlaxAssetLibrary/inbox/downloads/manual_drop/` |
| `generator` | `FlaxAssetLibrary/publish/flax_intake/<game_scope>/<pack_id>/payload/` |

Publish and intake stay on the Flax side. The asset factory writes to `flax_intake/`; Flax reads from there.

## What Triggers a Boundary Violation
- Modifying Flax scene files from AssetBoy
- Storing app code inside `FlaxAssetLibrary/`
- Replacing `flax_publish.py` or `flax_intake.py`
- Treating a gate report as an AssetBoy output (it is a Flax output AssetBoy reads)
