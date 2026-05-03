"""
polyhaven_runner.py — Batch-download free CC0 assets from Poly Haven via Playwright MCP.

Poly Haven (polyhaven.com) is 100% CC0-licensed. No login required.
Covers: Textures (PBR), Models (3D props), HDRIs (environment lighting).

Usage (via CLI):
    python -m assetboy.cli run-polyhaven-batch --category textures --search "stone marble" --count 10
    python -m assetboy.cli run-polyhaven-batch --category models --search "roman column" --count 5
    python -m assetboy.cli run-polyhaven-batch --category hdris --search "outdoor sunset" --count 3
    python -m assetboy.cli run-polyhaven-batch --dry-run

When Playwright MCP is active, the runner emits structured instructions that
I (the AI) can use to navigate polyhaven.com and trigger downloads directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.library.paths import generated_output_root, manual_drop_dir

# ---------------------------------------------------------------------------
# Categories and default search presets for Roman Arena
# ---------------------------------------------------------------------------

CATEGORY_API_PATH = {
    "textures": "textures",
    "models": "models",
    "hdris": "hdris",
}

ROMAN_PRESETS: list[dict] = [
    # Textures
    {"category": "textures", "search": "stone brick",    "pack_id": "SHARED_TEX_STONE_BRICK_CORE",    "tags": ["roman", "wall", "stone"]},
    {"category": "textures", "search": "marble",         "pack_id": "SHARED_TEX_MARBLE_CORE",          "tags": ["roman", "floor", "marble"]},
    {"category": "textures", "search": "sand",           "pack_id": "SHARED_TEX_SAND_CORE",            "tags": ["roman", "arena", "sand"]},
    {"category": "textures", "search": "cobblestone",    "pack_id": "SHARED_TEX_COBBLE_CORE",          "tags": ["roman", "road", "ground"]},
    {"category": "textures", "search": "leather",        "pack_id": "SHARED_TEX_LEATHER_CORE",         "tags": ["roman", "armor", "leather"]},
    {"category": "textures", "search": "metal rust",     "pack_id": "SHARED_TEX_METAL_RUST_CORE",      "tags": ["roman", "weapon", "metal"]},
    # Models
    {"category": "models",   "search": "column pillar",  "pack_id": "SHARED_PROP_COLUMN_CORE",         "tags": ["roman", "architecture"]},
    {"category": "models",   "search": "rock boulder",   "pack_id": "SHARED_PROP_ROCK_CORE",           "tags": ["roman", "arena", "prop"]},
    {"category": "models",   "search": "barrel pot",     "pack_id": "SHARED_PROP_VESSEL_CORE",         "tags": ["roman", "prop", "decoration"]},
    # HDRIs
    {"category": "hdris",    "search": "outdoor sunny",  "pack_id": "SHARED_HDRI_OUTDOOR_CORE",        "tags": ["roman", "sky", "lighting"]},
]

# ---------------------------------------------------------------------------
# Skybox presets — HDRIs covering all major game sky conditions (CC0)
# ---------------------------------------------------------------------------
SKYBOX_PRESETS: list[dict] = [
    {"category": "hdris", "search": "outdoor sunny day",     "pack_id": "SHARED_SKY_SUNNY_DAY",   "tags": ["skybox", "sunny", "day"]},
    {"category": "hdris", "search": "golden hour sunset",    "pack_id": "SHARED_SKY_SUNSET",      "tags": ["skybox", "sunset", "warm"]},
    {"category": "hdris", "search": "overcast cloudy grey",  "pack_id": "SHARED_SKY_OVERCAST",    "tags": ["skybox", "overcast", "grey"]},
    {"category": "hdris", "search": "night stars midnight",  "pack_id": "SHARED_SKY_NIGHT",       "tags": ["skybox", "night", "stars"]},
    {"category": "hdris", "search": "foggy misty morning",   "pack_id": "SHARED_SKY_FOG",         "tags": ["skybox", "fog", "horror"]},
    {"category": "hdris", "search": "space stars galaxy",    "pack_id": "SHARED_SKY_SPACE",       "tags": ["skybox", "space", "scifi"]},
    {"category": "hdris", "search": "studio neutral warm",   "pack_id": "SHARED_SKY_STUDIO",      "tags": ["skybox", "studio", "neutral"]},
    {"category": "hdris", "search": "indoor interior warm",  "pack_id": "SHARED_SKY_INTERIOR",    "tags": ["skybox", "indoor", "warm"]},
]

# ---------------------------------------------------------------------------
# Terrain presets — PBR texture sets + terrain props for all biomes (CC0)
# ---------------------------------------------------------------------------
TERRAIN_PRESETS: list[dict] = [
    {"category": "textures", "search": "grass ground",         "pack_id": "TERRAIN_TEX_GRASS",   "tags": ["terrain", "grass", "outdoor"]},
    {"category": "textures", "search": "dirt soil ground",     "pack_id": "TERRAIN_TEX_DIRT",    "tags": ["terrain", "dirt", "ground"]},
    {"category": "textures", "search": "sand desert",          "pack_id": "TERRAIN_TEX_SAND",    "tags": ["terrain", "sand", "roman"]},
    {"category": "textures", "search": "rock cliff stone",     "pack_id": "TERRAIN_TEX_ROCK",    "tags": ["terrain", "rock", "cliff"]},
    {"category": "textures", "search": "snow ice",             "pack_id": "TERRAIN_TEX_SNOW",    "tags": ["terrain", "snow", "winter"]},
    {"category": "textures", "search": "lava volcanic",        "pack_id": "TERRAIN_TEX_LAVA",    "tags": ["terrain", "lava", "fantasy"]},
    {"category": "textures", "search": "mud wet ground",       "pack_id": "TERRAIN_TEX_MUD",     "tags": ["terrain", "mud", "wet"]},
    {"category": "textures", "search": "gravel pebble path",   "pack_id": "TERRAIN_TEX_GRAVEL",  "tags": ["terrain", "gravel", "roman"]},
    {"category": "textures", "search": "forest floor leaves",  "pack_id": "TERRAIN_TEX_FOREST",  "tags": ["terrain", "forest", "organic"]},
    {"category": "models",   "search": "terrain rock cliff",   "pack_id": "TERRAIN_PROP_CLIFF",  "tags": ["terrain", "rock", "prop"]},
]

POLYHAVEN_BASE = "https://polyhaven.com"
POLYHAVEN_API = "https://api.polyhaven.com"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PolyHavenAsset:
    slug: str
    name: str
    category: str
    pack_id: str
    download_url: str
    resolution: str = "2k"
    format: str = "jpg"

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "pack_id": self.pack_id,
            "download_url": self.download_url,
            "resolution": self.resolution,
            "format": self.format,
        }


@dataclass
class PolyHavenBatchResult:
    pack_id: str
    category: str
    search: str
    output_dir: Path
    assets_found: int = 0
    assets_downloaded: list[str] = field(default_factory=list)
    assets_skipped: list[str] = field(default_factory=list)
    dry_run: bool = False
    job_spec_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "category": self.category,
            "search": self.search,
            "output_dir": str(self.output_dir),
            "assets_found": self.assets_found,
            "assets_downloaded": self.assets_downloaded,
            "assets_skipped": self.assets_skipped,
            "dry_run": self.dry_run,
            "job_spec_path": str(self.job_spec_path) if self.job_spec_path else None,
        }


# ---------------------------------------------------------------------------
# Playwright MCP step builders for Poly Haven
# ---------------------------------------------------------------------------

def _build_polyhaven_playwright_steps(
    category: str,
    search: str,
    count: int,
    pack_id: str,
    output_dir: Path,
    resolution: str = "2k",
) -> list[dict]:
    """
    Returns structured Playwright MCP steps that the AI executes directly.
    Each step is a dict with 'action', 'params', and optional 'note'.
    """
    cat_path = CATEGORY_API_PATH.get(category, "textures")
    search_url = f"{POLYHAVEN_BASE}/{cat_path}?s={search.replace(' ', '+')}"
    api_url = f"{POLYHAVEN_API}/assets?type={cat_path}&categories={search.replace(' ', ',')}"

    steps = [
        {
            "action": "navigate",
            "params": {"url": search_url},
            "note": f"Open Poly Haven {category} search: {search}",
        },
        {
            "action": "screenshot",
            "params": {},
            "note": "Capture search results to identify available assets",
        },
        {
            "action": "api_fetch",
            "params": {"url": api_url},
            "note": f"Fetch asset list from Poly Haven API (no auth needed). Get first {count} slugs.",
        },
    ]

    # Per-asset download steps (template — AI fills in actual slugs from API response)
    for i in range(1, count + 1):
        slug_placeholder = f"<slug_{i}>"
        if category == "textures":
            dl_url = f"{POLYHAVEN_BASE}/files/{slug_placeholder}_nor_gl_{resolution}.exr"
            steps += [
                {
                    "action": "navigate",
                    "params": {"url": f"{POLYHAVEN_BASE}/{cat_path}/{slug_placeholder}"},
                    "note": f"Asset {i}: navigate to asset page",
                },
                {
                    "action": "click",
                    "params": {"selector": f"[data-res='{resolution}']"},
                    "note": f"Select {resolution} resolution",
                },
                {
                    "action": "download",
                    "params": {
                        "url_pattern": f"{POLYHAVEN_BASE}/files/{slug_placeholder}_*_{resolution}*",
                        "dest_dir": str(output_dir / slug_placeholder),
                    },
                    "note": f"Download all texture maps ({resolution}): diffuse, normal, roughness, AO",
                },
            ]
        elif category == "models":
            steps += [
                {
                    "action": "navigate",
                    "params": {"url": f"{POLYHAVEN_BASE}/{cat_path}/{slug_placeholder}"},
                    "note": f"Asset {i}: navigate to model page",
                },
                {
                    "action": "download",
                    "params": {
                        "url_pattern": f"{POLYHAVEN_BASE}/files/{slug_placeholder}_{resolution}*",
                        "dest_dir": str(output_dir / slug_placeholder),
                        "prefer_format": "glb",
                    },
                    "note": f"Download GLB model + {resolution} textures",
                },
            ]
        else:  # hdris
            steps += [
                {
                    "action": "navigate",
                    "params": {"url": f"{POLYHAVEN_BASE}/{cat_path}/{slug_placeholder}"},
                    "note": f"Asset {i}: navigate to HDRI page",
                },
                {
                    "action": "download",
                    "params": {
                        "url_pattern": f"{POLYHAVEN_BASE}/files/{slug_placeholder}_{resolution}.hdr",
                        "dest_dir": str(output_dir / slug_placeholder),
                    },
                    "note": f"Download {resolution} HDRI .hdr file",
                },
            ]

    steps.append({
        "action": "note",
        "params": {},
        "note": f"All {count} assets downloaded to {output_dir}. Provenance: CC0 — no attribution required.",
    })
    return steps


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_polyhaven_batch(
    *,
    category: str = "textures",
    search: str = "stone",
    pack_id: str | None = None,
    count: int = 6,
    resolution: str = "2k",
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    use_presets: bool = False,
) -> list[PolyHavenBatchResult]:
    """
    Emit Playwright MCP steps for a Poly Haven batch download.

    When dry_run=True, shows the step plan without executing.
    When the Playwright MCP is active in chat, the AI drives navigation directly.

    use_presets=True runs all built-in Roman Arena presets instead.
    """
    if use_presets:
        jobs = ROMAN_PRESETS
    else:
        resolved_pack_id = pack_id or f"SHARED_{category.upper()}_{search.replace(' ', '_').upper()}_CORE"
        jobs = [{"category": category, "search": search, "pack_id": resolved_pack_id, "tags": []}]

    results = []
    for job in jobs:
        cat = job["category"]
        s = job["search"]
        pid = job["pack_id"]
        out_dir = (
            Path(output_dir) if output_dir
            else manual_drop_dir() / "polyhaven" / pid
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        steps = _build_polyhaven_playwright_steps(
            category=cat,
            search=s,
            count=count,
            pack_id=pid,
            output_dir=out_dir,
            resolution=resolution,
        )

        result = PolyHavenBatchResult(
            pack_id=pid,
            category=cat,
            search=s,
            output_dir=out_dir,
            assets_found=count,
            dry_run=dry_run,
        )

        mode = "DRY RUN" if dry_run else "EXECUTION PLAN"
        print(f"\n[{mode}] Poly Haven {cat}: '{s}' -> {pid}")
        print(f"Resolution: {resolution} | Count: {count} | Output: {out_dir}")
        print()

        job_spec = {
            "source": "polyhaven",
            "pack_id": pid,
            "category": cat,
            "search": s,
            "resolution": resolution,
            "count": count,
            "license": "CC0",
            "output_dir": str(out_dir),
            "playwright_steps": steps,
        }

        spec_path = out_dir / "polyhaven_job.json"
        spec_path.write_text(json.dumps(job_spec, indent=2), encoding="utf-8")
        result.job_spec_path = spec_path

        print(f"Job spec written: {spec_path}")
        print(f"Playwright steps: {len(steps)}")

        if dry_run:
            print("\n--- Step Preview ---")
            for i, step in enumerate(steps, 1):
                print(f"  {i}. [{step['action']}] {step['note']}")
            result.assets_skipped = [f"asset_{i}" for i in range(1, count + 1)]
        else:
            print("\n>>> Feed the job spec to the Playwright MCP server to execute.")
            print(f">>> Or call from chat: 'run polyhaven job at {spec_path}'")
            result.assets_downloaded = [f"<pending_slug_{i}>" for i in range(1, count + 1)]

        results.append(result)

    print(f"\nTotal batches: {len(results)}")
    return results


def run_skybox_presets(
    *,
    count: int = 3,
    resolution: str = "2k",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[PolyHavenBatchResult]:
    """Download HDRI skybox presets from Poly Haven. Each returns a .hdr file."""
    results = []
    for job in SKYBOX_PRESETS:
        if tags_filter and not any(t in job["tags"] for t in tags_filter):
            continue
        results.extend(run_polyhaven_batch(
            category=job["category"],
            search=job["search"],
            pack_id=job["pack_id"],
            count=count,
            resolution=resolution,
            dry_run=dry_run,
        ))
    return results


def run_terrain_presets(
    *,
    count: int = 3,
    resolution: str = "2k",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[PolyHavenBatchResult]:
    """Download PBR terrain textures + terrain props from Poly Haven."""
    results = []
    for job in TERRAIN_PRESETS:
        if tags_filter and not any(t in job["tags"] for t in tags_filter):
            continue
        results.extend(run_polyhaven_batch(
            category=job["category"],
            search=job["search"],
            pack_id=job["pack_id"],
            count=count,
            resolution=resolution,
            dry_run=dry_run,
        ))
    return results
