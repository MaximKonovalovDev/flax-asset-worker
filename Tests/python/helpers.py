from __future__ import annotations

import json
from pathlib import Path


def write_roman_fixture(root: str | Path) -> tuple[Path, Path]:
    base = Path(root)
    gate_path = base / "roman_gate_fixture.json"
    catalog_path = base / "roman_catalog_fixture.json"

    gate_payload = {
        "recipe": "fps",
        "pass": False,
        "gate_reasons": ["missing gameplay-facing assets"],
        "dashboard": {
            "top_blockers": {
                "manifest_unresolved": [
                    {
                        "slot": "player_prefab",
                        "required_tag": "player character",
                        "preferred_type": "character",
                        "required_count": 1,
                        "matched_count": 0,
                        "remediation": "Acquire a gameplay-ready player base.",
                        "name_hints": ["player", "character", "humanoid"],
                    },
                    {
                        "slot": "hud_texture",
                        "required_tag": "ui hud",
                        "preferred_type": "texture",
                        "required_count": 1,
                        "matched_count": 0,
                        "remediation": "Acquire readable combat HUD textures.",
                        "name_hints": ["hud", "crosshair", "ui"],
                    },
                    {
                        "slot": "music_clip",
                        "required_tag": "music",
                        "preferred_type": "audio",
                        "required_count": 1,
                        "matched_count": 0,
                        "remediation": "Acquire a combat-safe music loop.",
                        "name_hints": ["music", "combat", "loop"],
                    },
                    {
                        "slot": "sfx_library",
                        "required_tag": "sfx",
                        "preferred_type": "audio",
                        "required_count": 3,
                        "matched_count": 0,
                        "remediation": "Acquire footsteps, hit, and swing sounds.",
                        "name_hints": ["sfx", "footsteps", "impact"],
                    },
                    {
                        "slot": "weapon_prefab",
                        "required_tag": "weapon",
                        "preferred_type": "mesh",
                        "required_count": 1,
                        "matched_count": 0,
                        "remediation": "Acquire a usable Roman weapon mesh.",
                        "name_hints": ["weapon", "gladius", "sword"],
                    },
                ]
            }
        },
    }
    catalog_payload = {
        "scope": "roman_arena",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "scan": {
            "summary": {
                "total": 1,
                "by_type": {
                    "Material": 1,
                },
            },
            "assets": [
                {
                    "relative_path": "RA_PACK_MAT_AND_POLISH_SLICE_01/Materials/M_ArenaStone.flax",
                }
            ],
        },
    }

    gate_path.write_text(json.dumps(gate_payload, indent=2) + "\n", encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog_payload, indent=2) + "\n", encoding="utf-8")
    return gate_path, catalog_path


def write_publish_pack(
    repo_root: str | Path,
    pack_id: str,
    *,
    payload_files: list[str],
    packet: bool,
    provenance: bool,
    imported: bool,
    game_scope: str = "roman_arena",
) -> Path:
    repo_path = Path(repo_root)
    publish_root = (
        repo_path
        / "artifacts"
        / "library"
        / "FlaxAssetLibrary"
        / "publish"
        / "flax_intake"
        / game_scope
        / pack_id
    )
    payload_root = publish_root / "payload"
    payload_root.mkdir(parents=True, exist_ok=True)

    for filename in payload_files:
        target = payload_root / filename
        target.write_text(f"fixture:{pack_id}:{filename}\n", encoding="utf-8")

    if packet:
        (publish_root / "packet.json").write_text(
            json.dumps(
                {
                    "pack_id": pack_id,
                    "game_scope": game_scope,
                    "packet_status": "reviewed",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if provenance:
        (publish_root / "provenance.json").write_text(
            json.dumps(
                {
                    "pack_id": pack_id,
                    "game_scope": game_scope,
                    "lane": "manual_browser",
                    "source_adapter": "fixture",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if imported:
        imported_root = (
            repo_path
            / "GameProjectFlax"
            / "MyProject"
            / "Content"
            / "Imported"
            / "Packs"
            / pack_id
        )
        imported_root.mkdir(parents=True, exist_ok=True)
        (imported_root / "imported.txt").write_text("imported\n", encoding="utf-8")

    return publish_root


def write_roman_first_playable_fixture(root: str | Path) -> tuple[Path, Path, Path]:
    base = Path(root)
    repo_root = base / "flax_repo"
    gate_path = repo_root / "artifacts" / "quality" / "asset-gates" / "roman_arena_fps_gate_2026-03-24.json"
    catalog_path = repo_root / "FlaxMCP" / "generated" / "asset_catalogs" / "roman_arena.json"

    gate_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    pack_layouts = {
        "RA_PACK_CHR_CORE_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": [
                "makehuman_system_assets_cc0.zip",
                "RA_PACK_CHR_CORE_SLICE_01_mock.fbx",
                "shirts03_ccby.zip",
                "shoes02_ccby.zip",
            ],
        },
        "RA_PACK_CHR_SKIRMISHER_SLICE_01": {
            "packet": False,
            "provenance": False,
            "imported": False,
            "payload_files": ["RA_PACK_CHR_SKIRMISHER_SLICE_01_mock.fbx"],
        },
        "RA_PACK_CHR_SLINGER_SLICE_01": {
            "packet": False,
            "provenance": False,
            "imported": False,
            "payload_files": ["RA_PACK_CHR_SLINGER_SLICE_01_mock.fbx"],
        },
        "RA_PACK_CHR_DUELIST_SLICE_01": {
            "packet": False,
            "provenance": False,
            "imported": False,
            "payload_files": ["RA_PACK_CHR_DUELIST_SLICE_01_mock.fbx"],
        },
        "RA_PACK_WPN_COMBAT_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": [
                "RA_PACK_WPN_COMBAT_SLICE_01_mock.glb",
                "sword_clean.fbx",
                "sword_clean.glb",
                "sword.glb",
            ],
        },
        "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": [
                "arena_sandstone_bowl.glb",
                "arena_wall_curved.glb",
                "arena_gate_arch.glb",
                "arena_stair.glb",
                "arena_tunnel_spawn.glb",
                "arena_column_broken.glb",
                "arena_banner_set.png",
                "arena_urn_cluster.glb",
            ],
        },
        "RA_PACK_TRAP_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": [
                "RA_PACK_TRAP_SLICE_01_mock.glb",
                "spike_trap_01.glb",
                "spike_trap_01.fbx",
            ],
        },
        "RA_PACK_MAT_AND_POLISH_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": [
                "Ground055S_2K-JPG.zip",
                "Bricks008_2K-JPG.zip",
                "Leather034D_2K-JPG.zip",
                "Planks034A_2K-JPG.zip",
                "Metal052A_2K-JPG.zip",
                "Fabric031_2K-JPG.zip",
            ],
        },
        "RA_PACK_ANM_COMBAT_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": [
                "anm_idle_clean.fbx",
                "anm_run_clean.fbx",
                "anm_impact_clean.fbx",
                "anm_sword_shield_slash_clean.fbx",
                "anm_death_clean.fbx",
            ],
        },
        "RA_PACK_AUD_SFX_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": ["kenney_impact-sounds.zip"],
        },
        "RA_PACK_AUD_MUSIC_SLICE_01": {
            "packet": True,
            "provenance": True,
            "imported": True,
            "payload_files": ["kenney_music-jingles.zip"],
        },
    }

    for pack_id, layout in pack_layouts.items():
        write_publish_pack(
            repo_root,
            pack_id,
            payload_files=list(layout["payload_files"]),
            packet=bool(layout["packet"]),
            provenance=bool(layout["provenance"]),
            imported=bool(layout["imported"]),
        )

    gate_path.write_text(
        json.dumps(
            {
                "recipe": "fps",
                "pass": True,
                "gate_reasons": [],
                "dashboard": {
                    "counts": {
                        "manifest_unresolved_slots": 0,
                    },
                    "top_blockers": {
                        "manifest_unresolved": [],
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    catalog_assets = [
        {"relative_path": f"{pack_id}/payload/{payload_files[0]}"}
        for pack_id, payload_files in (
            ("RA_PACK_CHR_CORE_SLICE_01", ["makehuman_system_assets_cc0.zip"]),
            ("RA_PACK_CHR_SKIRMISHER_SLICE_01", ["RA_PACK_CHR_SKIRMISHER_SLICE_01_mock.fbx"]),
            ("RA_PACK_CHR_SLINGER_SLICE_01", ["RA_PACK_CHR_SLINGER_SLICE_01_mock.fbx"]),
            ("RA_PACK_CHR_DUELIST_SLICE_01", ["RA_PACK_CHR_DUELIST_SLICE_01_mock.fbx"]),
            ("RA_PACK_WPN_COMBAT_SLICE_01", ["sword_clean.glb"]),
            ("RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01", ["arena_sandstone_bowl.glb"]),
            ("RA_PACK_TRAP_SLICE_01", ["spike_trap_01.glb"]),
            ("RA_PACK_MAT_AND_POLISH_SLICE_01", ["Ground055S_2K-JPG.zip"]),
            ("RA_PACK_ANM_COMBAT_SLICE_01", ["anm_idle_clean.fbx"]),
            ("RA_PACK_AUD_SFX_SLICE_01", ["kenney_impact-sounds.zip"]),
            ("RA_PACK_AUD_MUSIC_SLICE_01", ["kenney_music-jingles.zip"]),
        )
    ]
    catalog_path.write_text(
        json.dumps(
            {
                "scope": "roman_arena",
                "generated_at_utc": "2026-03-24T00:00:00Z",
                "scan": {
                    "summary": {
                        "total": len(catalog_assets),
                        "by_type": {"Pack": len(catalog_assets)},
                    },
                    "assets": catalog_assets,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return repo_root, gate_path, catalog_path
