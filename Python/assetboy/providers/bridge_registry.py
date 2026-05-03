from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.library.paths import assetboy_root
from assetboy.providers.lanes import ProviderLane, normalize_lane, require_source_adapter


class BridgeFamily(str, Enum):
    SOURCE_SITE = "source_site"
    BROWSER_AUTOMATION = "browser_automation"
    AI_PROVIDER = "ai_provider"
    ENGINE_BRIDGE = "engine_bridge"
    EXTRACTOR = "extractor"
    COLAB_GENERATOR = "colab_generator"


class AssetCategory(str, Enum):
    # 3D / Mesh
    PROP = "prop"
    WEAPON = "weapon"
    CHARACTER_BASE = "character_base"
    ARCHITECTURE = "architecture"
    VEHICLE = "vehicle"
    TERRAIN = "terrain"
    MUSEUM_PROP = "museum_prop"
    # 2D / Flat
    UI_HUD = "ui_hud"
    ICON = "icon"
    VFX = "vfx"               # particles, explosions, impact sprites
    FONT = "font"              # TTF/OTF game fonts
    SKYBOX = "skybox"          # HDRI / 360 sky maps
    # Motion
    ANIMATION = "animation"
    # Audio
    MUSIC = "music"
    SFX = "sfx"
    DIALOGUE = "dialogue"     # voiced NPC lines / TTS output
    # Surface / Material
    MATERIAL = "material"
    SHADER = "shader"         # Flax shader graphs / material templates


@dataclass(frozen=True)
class BridgeDefinition:
    bridge_id: str
    display_name: str
    family: BridgeFamily
    adapter_id: str
    lane: ProviderLane
    categories: tuple[AssetCategory, ...]
    summary: str
    fallback_bridge_ids: tuple[str, ...] = ()
    automation_runtime: str = ""
    requires_local_engine: bool = False
    requires_local_gpu: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "bridge_id": self.bridge_id,
            "display_name": self.display_name,
            "family": self.family.value,
            "adapter_id": self.adapter_id,
            "lane": self.lane.value,
            "categories": [category.value for category in self.categories],
            "summary": self.summary,
            "fallback_bridge_ids": list(self.fallback_bridge_ids),
            "automation_runtime": self.automation_runtime,
            "requires_local_engine": self.requires_local_engine,
            "requires_local_gpu": self.requires_local_gpu,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CategoryRoute:
    category: AssetCategory
    primary_bridge_id: str
    fallback_bridge_ids: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "primary_bridge_id": self.primary_bridge_id,
            "fallback_bridge_ids": list(self.fallback_bridge_ids),
            "rationale": self.rationale,
        }


class BatchabilityBand(str, Enum):
    BATCHABLE_NOW = "batchable_now"
    BATCHABLE_WITH_MANUAL_STEPS = "batchable_with_manual_steps"
    MANUAL_GAP_FILL = "manual_gap_fill"


@dataclass(frozen=True)
class CategoryBatchability:
    category: AssetCategory
    route: CategoryRoute
    primary_bridge_id: str
    primary_status: BatchabilityBand
    best_bridge_id: str
    best_status: BatchabilityBand
    best_bridge_lane: ProviderLane

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "route": self.route.to_dict(),
            "primary_bridge_id": self.primary_bridge_id,
            "primary_status": self.primary_status.value,
            "best_bridge_id": self.best_bridge_id,
            "best_status": self.best_status.value,
            "best_bridge_lane": self.best_bridge_lane.value,
        }


_SKILL_DOC_PATHS: dict[str, str] = {
    "flax-asset-consumer": r"skills\flax-asset-consumer\SKILL.md",
    "source-intel": r"skills\source-intel\SKILL.md",
    "roman-roadmap": r"skills\roman-roadmap\SKILL.md",
    "pipeline-orchestration": r"skills\pipeline-orchestration\SKILL.md",
    "colab-batch-orchestration": r"skills\colab-batch-orchestration\SKILL.md",
    "bridge-routing": r"skills\bridge-routing\SKILL.md",
    "asset-gate-enforcement": r"skills\asset-gate-enforcement\SKILL.md",
    "pack-verification-loop": r"skills\pack-verification-loop\SKILL.md",
    "continuous-learning": r"skills\continuous-learning\SKILL.md",
    "blender-mcp-automation": r"skills\blender-mcp-automation\SKILL.md",
}

_FAMILY_SKILLS: dict[BridgeFamily, tuple[str, ...]] = {
    BridgeFamily.SOURCE_SITE: ("source-intel", "pack-verification-loop"),
    BridgeFamily.BROWSER_AUTOMATION: ("source-intel", "bridge-routing", "pack-verification-loop"),
    BridgeFamily.AI_PROVIDER: ("bridge-routing", "pipeline-orchestration", "pack-verification-loop"),
    BridgeFamily.ENGINE_BRIDGE: ("flax-asset-consumer", "bridge-routing", "pipeline-orchestration", "pack-verification-loop"),
    BridgeFamily.EXTRACTOR: ("flax-asset-consumer", "bridge-routing", "pack-verification-loop"),
    BridgeFamily.COLAB_GENERATOR: ("bridge-routing", "pipeline-orchestration", "pack-verification-loop"),
}

_BLENDER_HEAVY_CATEGORIES = {
    AssetCategory.PROP,
    AssetCategory.WEAPON,
    AssetCategory.CHARACTER_BASE,
    AssetCategory.ARCHITECTURE,
    AssetCategory.VEHICLE,
    AssetCategory.TERRAIN,
    AssetCategory.MUSEUM_PROP,
    AssetCategory.ANIMATION,
    AssetCategory.MATERIAL,
}

_MANUAL_BROWSER_BATCHABLE_RUNTIME_HINTS = {
    "docker_bot",
    "epic_launcher_dummy_project",
    "playwright_mcp",
    "uevaultmanager_cli",
    "userscript_or_bot",
}

_BRIDGE_BATCHABILITY_OVERRIDES = {
    "quaternius_direct": BatchabilityBand.BATCHABLE_WITH_MANUAL_STEPS,
}

_BATCHABILITY_RANK = {
    BatchabilityBand.BATCHABLE_NOW: 0,
    BatchabilityBand.BATCHABLE_WITH_MANUAL_STEPS: 1,
    BatchabilityBand.MANUAL_GAP_FILL: 2,
}


def _merge_unique_strings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for group in groups:
        for item in group:
            if item not in ordered:
                ordered.append(item)
    return tuple(ordered)


def skill_doc_path(skill_id: str) -> str:
    relative_path = _SKILL_DOC_PATHS[skill_id]
    return str((assetboy_root(__file__) / relative_path).resolve())


BRIDGE_REGISTRY: dict[str, BridgeDefinition] = {
    "poly_haven": BridgeDefinition(
        bridge_id="poly_haven",
        display_name="Poly Haven",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MATERIAL, AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.TERRAIN, AssetCategory.SKYBOX),
        summary="Direct-download CC0 textures, HDRIs, and some 3D assets.",
    ),
    "blenderkit": BridgeDefinition(
        bridge_id="blenderkit",
        display_name="BlenderKit",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="blenderkit",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.MATERIAL, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE),
        summary="#1 priority paid subscription source. Browse and download directly inside Blender, then export to Flax intake path.",
        notes=(
            "Requires BlenderKit add-on installed in Blender.",
            "Download asset inside Blender, apply, then export as GLB/FBX for intake.",
            "Subscription gives broad coverage across props, environments, materials, and characters.",
            "Check individual asset license — most are CC0 or royalty-free commercial.",
        ),
        fallback_bridge_ids=("poly_haven", "fab_browser"),
    ),
    "ambientcg": BridgeDefinition(
        bridge_id="ambientcg",
        display_name="ambientCG",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="ambientcg_direct",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MATERIAL, AssetCategory.ARCHITECTURE, AssetCategory.TERRAIN),
        summary="Direct-download materials and texture sets for environment work.",
    ),
    "kenney": BridgeDefinition(
        bridge_id="kenney",
        display_name="Kenney.nl",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="kenney_direct",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.PROP, AssetCategory.WEAPON, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE, AssetCategory.UI_HUD, AssetCategory.ICON, AssetCategory.MATERIAL),
        summary="CC0 public domain packs — 3D props, characters, environments, UI sets. 23 preset packs across all genres.",
        notes=(
            "No auth required. Direct ZIP downloads.",
            "Use kenney_runner.py with --use-presets or --tags-filter <genre>.",
            "All content CC0 — no attribution required, commercial use OK.",
        ),
    ),
    "quaternius_direct": BridgeDefinition(
        bridge_id="quaternius_direct",
        display_name="Quaternius",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="quaternius_direct",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.PROP, AssetCategory.WEAPON, AssetCategory.CHARACTER_BASE, AssetCategory.ARCHITECTURE),
        summary="CC0 low-poly packs for characters, weapons, props, and modular environments, but many live pages now resolve through Drive or Itch click-throughs.",
        fallback_bridge_ids=("kenney", "browser_use_generic"),
    ),
    "makehuman_character": BridgeDefinition(
        bridge_id="makehuman_character",
        display_name="MakeHuman Baseline",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="makehuman_direct",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.CHARACTER_BASE,),
        summary="Source or export MakeHuman baselines before layering clothing, heads, and downstream cleanup.",
        fallback_bridge_ids=("mixamo_browser",),
    ),
    "game_icons_net": BridgeDefinition(
        bridge_id="game_icons_net",
        display_name="game-icons.net",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="game_icons_github",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.UI_HUD, AssetCategory.ICON),
        summary="3,000+ SVG game icons under CC BY 3.0. One bulk download covers icon needs for all game scopes.",
        notes=(
            "License: CC BY 3.0 — attribution required: 'Icons by game-icons.net' in game credits.",
            "Use game_icons_runner.py with --filter <category> (combat, magic, ui, scifi, horror, medieval).",
            "Source: GitHub master ZIP — no auth needed.",
        ),
    ),
    "nasa_3d_open": BridgeDefinition(
        bridge_id="nasa_3d_open",
        display_name="NASA 3D Resources",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.PROP, AssetCategory.VEHICLE),
        summary="Public domain 3D models from NASA — spacecraft, rovers, satellites. Great for sci-fi scope.",
        notes=(
            "Source: https://nasa3d.arc.nasa.gov/ — public domain, no license restrictions.",
            "Manually browse and queue direct download URLs for models you want.",
        ),
    ),
    "smithsonian_open_access": BridgeDefinition(
        bridge_id="smithsonian_open_access",
        display_name="Smithsonian Open Access",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSEUM_PROP,),
        summary="Open-access museum references and assets with provenance-friendly rights info.",
    ),
    "the_met_open_access": BridgeDefinition(
        bridge_id="the_met_open_access",
        display_name="The Met Open Access",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSEUM_PROP,),
        summary="Open-access museum source for historical references and object imagery.",
    ),
    "mixkit_audio": BridgeDefinition(
        bridge_id="mixkit_audio",
        display_name="Mixkit Audio",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="mixkit",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSIC, AssetCategory.SFX),
        summary="Direct-download audio source for music beds and SFX.",
        fallback_bridge_ids=("pixabay_audio", "freesound_audio"),
    ),
    "pixabay_audio": BridgeDefinition(
        bridge_id="pixabay_audio",
        display_name="Pixabay Audio",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="pixabay_audio",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSIC, AssetCategory.SFX),
        summary="Direct-download audio source with simple provenance capture.",
    ),
    "freesound_audio": BridgeDefinition(
        bridge_id="freesound_audio",
        display_name="Freesound",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="freesound_audio",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.SFX,),
        summary="Source SFX from Freesound with per-asset license capture.",
    ),
    "opengameart_audio": BridgeDefinition(
        bridge_id="opengameart_audio",
        display_name="OpenGameArt Audio",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="opengameart",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSIC, AssetCategory.SFX),
        summary="Fallback open source for gameplay audio when stronger sources fail.",
    ),
    "opengameart_vfx": BridgeDefinition(
        bridge_id="opengameart_vfx",
        display_name="OpenGameArt VFX",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="opengameart",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.VFX,),
        summary="Open source fallback for particle sheets, spell sprites, and simple effect atlases.",
        fallback_bridge_ids=("browser_use_generic",),
    ),
    "fab_browser": BridgeDefinition(
        bridge_id="fab_browser",
        display_name="Fab Browser Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="fab",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.WEAPON, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE, AssetCategory.UI_HUD, AssetCategory.ICON),
        summary="Browser automation bridge for Fab downloads and provenance capture.",
        automation_runtime="playwright_mcp",
        fallback_bridge_ids=("browser_use_generic",),
    ),
    "fab_auto_claim_bridge": BridgeDefinition(
        bridge_id="fab_auto_claim_bridge",
        display_name="Fab Auto Claim Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="fab_auto_claim",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Auto-claim free Fab assets into account library before download/extract lanes.",
        automation_runtime="userscript_or_bot",
        fallback_bridge_ids=("fab_browser",),
    ),
    "free_games_claimer_bridge": BridgeDefinition(
        bridge_id="free_games_claimer_bridge",
        display_name="Free Games Claimer Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="free_games_claimer",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Background free-drop claim bridge for owned account operations.",
        automation_runtime="docker_bot",
        fallback_bridge_ids=("fab_auto_claim_bridge", "fab_browser"),
    ),
    "unity_store_browser": BridgeDefinition(
        bridge_id="unity_store_browser",
        display_name="Unity Store Browser Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="unity_asset_store",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE),
        summary="Browser automation bridge for Unity Asset Store licensed packages.",
        automation_runtime="playwright_mcp",
    ),
    "mixamo_browser": BridgeDefinition(
        bridge_id="mixamo_browser",
        display_name="Mixamo Browser Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="mixamo_manual_browser",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.CHARACTER_BASE, AssetCategory.ANIMATION),
        summary="Browser automation bridge for rigged character bases and stock animation clips.",
        automation_runtime="playwright_mcp",
        fallback_bridge_ids=("browser_use_generic",),
    ),
    "mixamo_animation_browser": BridgeDefinition(
        bridge_id="mixamo_animation_browser",
        display_name="Mixamo Animation Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="mixamo_animations",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.ANIMATION,),
        summary="Animation-only Mixamo bridge for locomotion, state, react, and combat clip pulls.",
        automation_runtime="playwright_mcp",
        fallback_bridge_ids=("mixamo_browser", "browser_use_generic"),
    ),
    "freesound_browser_audio": BridgeDefinition(
        bridge_id="freesound_browser_audio",
        display_name="Freesound Browser Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="freesound_browser",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.MUSIC, AssetCategory.SFX),
        summary="Browser automation bridge for Freesound when login or license confirmation is required.",
        automation_runtime="playwright_mcp",
    ),
    "museum_browser": BridgeDefinition(
        bridge_id="museum_browser",
        display_name="Museum Browser Bridge",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="museum_page",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.MUSEUM_PROP,),
        summary="Browser automation bridge for museum pages that are gated or need rights confirmation.",
        automation_runtime="browser_use",
    ),
    "browser_use_generic": BridgeDefinition(
        bridge_id="browser_use_generic",
        display_name="Browser Use Generic",
        family=BridgeFamily.BROWSER_AUTOMATION,
        adapter_id="museum_page",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=tuple(category for category in AssetCategory),
        summary="Generic browser automation fallback when site-specific automation is not yet scripted.",
        automation_runtime="browser_use",
    ),
    "chatgpt_pro_ui": BridgeDefinition(
        bridge_id="chatgpt_pro_ui",
        display_name="ChatGPT Pro UI Bridge",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="chatgpt_pro",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.UI_HUD, AssetCategory.ICON, AssetCategory.MATERIAL),
        summary="Generate and iterate UI or prompt packs via ChatGPT Pro workflows.",
    ),
    "google_pro_ui": BridgeDefinition(
        bridge_id="google_pro_ui",
        display_name="Google Pro UI Bridge",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="google_pro",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.UI_HUD, AssetCategory.ICON, AssetCategory.MATERIAL),
        summary="Use Google Pro generation as a secondary UI and concept bridge.",
    ),
    "hunyuan_image_colab_ui": BridgeDefinition(
        bridge_id="hunyuan_image_colab_ui",
        display_name="HunyuanImage Colab Bridge",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="hunyuan_image_colab",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.UI_HUD, AssetCategory.ICON, AssetCategory.MATERIAL),
        summary="Colab-based image generation for UI references and material concepts.",
    ),
    "comfyui_local_ui": BridgeDefinition(
        bridge_id="comfyui_local_ui",
        display_name="ComfyUI Local Bridge",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="comfyui_local",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.UI_HUD, AssetCategory.ICON, AssetCategory.MATERIAL),
        summary="Local RTX3050 ComfyUI bridge for 2D variants, inpaint, and texture remix.",
        requires_local_gpu=True,
    ),
    "musicgen_audio": BridgeDefinition(
        bridge_id="musicgen_audio",
        display_name="MusicGen Audio Bridge",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="musicgen",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.MUSIC,),
        summary="Text-to-music generator bridge for gameplay beds and menus when source libraries fail.",
    ),
    "audioldm2_audio": BridgeDefinition(
        bridge_id="audioldm2_audio",
        display_name="AudioLDM2 Audio Bridge",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="audioldm2",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.SFX, AssetCategory.MUSIC),
        summary="Text-to-audio generator bridge for SFX and ambience gaps.",
    ),
    "zapsplat": BridgeDefinition(
        bridge_id="zapsplat",
        display_name="Zapsplat",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="manual_browser_drop",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.SFX,),
        summary="Large free SFX library — weapons, impacts, ambience, UI. Free account required.",
        notes=(
            "Free tier: download with free account. Attribution may be required on free tier.",
            "Premium removes attribution. Covers game-specific FX very well.",
            "Manual download via browser — drop files to manual_drop/zapsplat/.",
        ),
        fallback_bridge_ids=("freesound_audio", "audioldm2_audio"),
    ),
    "ccmixter_music": BridgeDefinition(
        bridge_id="ccmixter_music",
        display_name="ccMixter",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSIC,),
        summary="Creative Commons music community — CC BY and CC0 tracks. Good for background beds.",
        notes=(
            "API: http://ccmixter.org/api/query?tags=<genre>&limit=20",
            "Mix of CC BY and CC0 — check per-track license before use.",
            "Queue direct MP3 URLs via direct_url_queue.",
        ),
        fallback_bridge_ids=("musicgen_audio",),
    ),
    "gamesounds_xyz": BridgeDefinition(
        bridge_id="gamesounds_xyz",
        display_name="GameSounds.xyz",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.SFX, AssetCategory.MUSIC),
        summary="Free game-specific SFX and music packs. Direct download, no auth for free tier.",
        notes=(
            "Source: https://gamesounds.xyz",
            "Many packs are thematic (dungeon, RPG, platformer, shooter).",
            "License varies per pack — check before bulk download.",
        ),
        fallback_bridge_ids=("freesound_audio", "audioldm2_audio"),
    ),
    "musopen_classical": BridgeDefinition(
        bridge_id="musopen_classical",
        display_name="Musopen",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.MUSIC,),
        summary="Public domain classical music recordings — orchestral, chamber, piano. Great for epic/historic game themes.",
        notes=(
            "Source: https://musopen.org — recordings are public domain (not just compositions).",
            "Perfect fit for Roman arena, medieval, or historic scope.",
            "API available: https://musopen.org/api/",
        ),
        fallback_bridge_ids=("ccmixter_music", "musicgen_audio"),
    ),
    "google_fonts": BridgeDefinition(
        bridge_id="google_fonts",
        display_name="Google Fonts",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="font_direct_url",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.FONT,),
        summary="CC0/OFL game fonts — direct TTF download from Google Fonts GitHub. 15 preset packs: medieval, sci-fi, pixel, horror, fantasy, UI.",
        notes=(
            "License: OFL-1.1 — free commercial use, no ingame attribution required.",
            "Use font_runner.py with --use-presets or --tags-filter <genre>.",
            "Source: github.com/google/fonts raw file URLs — no auth, direct download.",
        ),
    ),
    "kenney_vfx": BridgeDefinition(
        bridge_id="kenney_vfx",
        display_name="Kenney VFX Packs",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="kenney_vfx_direct",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.VFX, AssetCategory.UI_HUD),
        summary="CC0 particle sprites, explosion sheets, magic VFX, and UI effect packs from Kenney.nl.",
        notes=(
            "License: CC0 — no attribution required, commercial use OK.",
            "Use vfx_runner.py with --use-presets or --tags-filter <type>.",
            "Covers: smoke, fire, sparks, explosions, magic glows, 1-bit pixel art UI.",
        ),
    ),
    "animationgpt_colab": BridgeDefinition(
        bridge_id="animationgpt_colab",
        display_name="AnimationGPT Colab",
        family=BridgeFamily.COLAB_GENERATOR,
        adapter_id="animationgpt_colab",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.ANIMATION,),
        summary="Text-to-BVH combat animation generator. 20 preset combat prompts: sword, axe, spear, shield, magic, dodge, death. Outputs BVH → Blender retarget → GLB.",
        notes=(
            "COMBAT ONLY: attack, block, dodge, death, stagger. Not for walk/run/idle — use Mixamo.",
            "Colab A100/V100 recommended. T4 may OOM on large batches.",
            "Output: BVH skeletal animation — needs retargeting to Mixamo rig before Flax import.",
            "Duration control is approximate (±20% frames). Not real-time.",
            "Source: github.com/fyyakaxyy/AnimationGPT — MIT license.",
        ),
        fallback_bridge_ids=("mixamo_browser",),
    ),

    # ── Museum / historical props ────────────────────────────────────────────
    "smithsonian_museum": BridgeDefinition(
        bridge_id="smithsonian_museum",
        display_name="Smithsonian Open Access",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="museum_browser_drop",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.MUSEUM_PROP, AssetCategory.PROP, AssetCategory.WEAPON),
        summary="Smithsonian/NASA public-domain 3D scans — Roman weapons, armour, pottery, busts, spacecraft.",
        notes=(
            "License: Public domain — no attribution required, commercial use OK.",
            "Use museum_runner.py --use-presets to print all navigation targets.",
            "Download via browser at 3d.si.edu or nasa3d.arc.nasa.gov, drop to manual_drop/museum/",
        ),
    ),

    # ── Vehicle packs ────────────────────────────────────────────────────────
    "kenney_vehicle": BridgeDefinition(
        bridge_id="kenney_vehicle",
        display_name="Kenney Vehicle Packs",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="vehicle_direct_url",
        lane=ProviderLane.DIRECT_URL,
        categories=(AssetCategory.VEHICLE,),
        summary="CC0 vehicle packs — cars, trucks, ships, spacecraft, racing. 7 preset packs from Kenney.nl.",
        notes=(
            "License: CC0 — no attribution required, commercial use OK.",
            "Use vehicle_runner.py --use-presets or --tags-filter <type>.",
            "Add confirmed .zip URLs to VEHICLE_DIRECT_ZIPS in vehicle_runner.py.",
        ),
    ),

    # ── Skybox HDRIs ─────────────────────────────────────────────────────────
    "polyhaven_skybox": BridgeDefinition(
        bridge_id="polyhaven_skybox",
        display_name="Poly Haven Skybox HDRIs",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="polyhaven_playwright",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.SKYBOX,),
        summary="CC0 HDRIs — sunny, sunset, night, fog, space, overcast, interior. 8 presets from Poly Haven.",
        notes=(
            "License: CC0. Download via run-skybox-batch CLI command.",
            "Output: .hdr at 2k/4k — import to Flax as SkyLight HDRI.",
        ),
        fallback_bridge_ids=("poly_haven",),
    ),

    # ── Terrain textures ──────────────────────────────────────────────────────
    "polyhaven_terrain": BridgeDefinition(
        bridge_id="polyhaven_terrain",
        display_name="Poly Haven Terrain Textures",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="polyhaven_playwright",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.TERRAIN, AssetCategory.MATERIAL),
        summary="CC0 PBR terrain texture sets — grass, dirt, sand, rock, snow, lava, mud, gravel, forest. 10 biomes.",
        notes=(
            "License: CC0. Use run-terrain-batch CLI command.",
            "Output: 2k PBR sets (albedo, normal, roughness, AO, displacement).",
        ),
        fallback_bridge_ids=("ambientcg", "poly_haven"),
    ),

    # ── Dialogue / NPC voices ─────────────────────────────────────────────────
    "edge_tts_dialogue": BridgeDefinition(
        bridge_id="edge_tts_dialogue",
        display_name="Edge TTS Dialogue",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="edge_tts_local",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.DIALOGUE,),
        summary="NPC dialogue via Azure Neural voices (edge-tts). 14 preset Roman Arena lines: Announcer, Gladiator, Guard, Merchant.",
        notes=(
            "Requires: pip install edge-tts. Free, no API key.",
            "Use dialogue_runner.py --use-presets or --text 'line' --voice announcer.",
            "Output: MP3 in generated/dialogue/<game_scope>/",
            "Voices: GuyNeural (announcer), ChristopherNeural (hero), RyanNeural (guard).",
        ),
    ),
    "elevenlabs_dialogue": BridgeDefinition(
        bridge_id="elevenlabs_dialogue",
        display_name="ElevenLabs Dialogue",
        family=BridgeFamily.AI_PROVIDER,
        adapter_id="elevenlabs_api",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.DIALOGUE,),
        summary="Optional production-grade hosted voice lane for dialogue and callouts with deterministic metadata sidecars.",
        fallback_bridge_ids=("edge_tts_dialogue",),
        notes=(
            "Requires ELEVENLABS_API_KEY in environment.",
            "Optional voice overrides: ELEVENLABS_VOICE_ID_ANNOUNCER, ELEVENLABS_VOICE_ID_HERO, ELEVENLABS_VOICE_ID_MALE_NARRATOR, ELEVENLABS_VOICE_ID_FEMALE_NARRATOR.",
            "Use run-dialogue-batch --provider elevenlabs for explicit provider selection.",
            "Edge-TTS remains the default fallback provider.",
        ),
    ),

    # ── Shader stub (manual) ──────────────────────────────────────────────────
    "shader_manual": BridgeDefinition(
        bridge_id="shader_manual",
        display_name="Shader Manual",
        family=BridgeFamily.SOURCE_SITE,
        adapter_id="manual_browser_drop",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.SHADER,),
        summary="Manual shader collection stub. Shadertoy (GLSL reference), Flax Marketplace, custom Flax C# shaders.",
        notes=(
            "No automated download — shaders are game-engine specific.",
            "Collect .flax shader files in manual_drop/shaders/<game_scope>/",
            "Phase 4: add ComfyUI material→shader or Blender node exporter.",
        ),
    ),

    "hunyuan3d2_3d": BridgeDefinition(
        bridge_id="hunyuan3d2_3d",
        display_name="Hunyuan3D-2 Bridge",
        family=BridgeFamily.COLAB_GENERATOR,
        adapter_id="hunyuan3d2",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.WEAPON, AssetCategory.PROP),
        summary="Primary Colab bridge for hard-surface props and weapons.",
        fallback_bridge_ids=("trellis_3d",),
    ),
    "trellis_3d": BridgeDefinition(
        bridge_id="trellis_3d",
        display_name="TRELLIS Bridge",
        family=BridgeFamily.COLAB_GENERATOR,
        adapter_id="trellis",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.WEAPON, AssetCategory.PROP),
        summary="Secondary Colab bridge when Hunyuan cannot land silhouette or topology.",
    ),
    "animationgpt_gap_fill": BridgeDefinition(
        bridge_id="animationgpt_gap_fill",
        display_name="AnimationGPT Gap Fill",
        family=BridgeFamily.COLAB_GENERATOR,
        adapter_id="animationgpt",
        lane=ProviderLane.GENERATOR,
        categories=(AssetCategory.ANIMATION,),
        summary="Pilot-only combat-gap animation bridge after manual sources fail.",
    ),
    "unity_engine_bridge": BridgeDefinition(
        bridge_id="unity_engine_bridge",
        display_name="Unity Engine Bridge",
        family=BridgeFamily.ENGINE_BRIDGE,
        adapter_id="unity_engine_bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.WEAPON, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE, AssetCategory.ANIMATION),
        summary="Licensed Unity package -> throwaway Unity project -> open-format export.",
        requires_local_engine=True,
        fallback_bridge_ids=("asset_ripper_extract", "asset_studio_extract"),
    ),
    "unreal_engine_bridge": BridgeDefinition(
        bridge_id="unreal_engine_bridge",
        display_name="Unreal Engine Bridge",
        family=BridgeFamily.ENGINE_BRIDGE,
        adapter_id="unreal_engine_bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Licensed Unreal or Fab package -> throwaway Unreal project -> open-format export.",
        requires_local_engine=True,
        fallback_bridge_ids=("fmodel_extract", "umodel_extract"),
    ),
    "fab_uevaultmanager": BridgeDefinition(
        bridge_id="fab_uevaultmanager",
        display_name="Fab UEVaultManager Bridge",
        family=BridgeFamily.ENGINE_BRIDGE,
        adapter_id="uevaultmanager",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Launcher-free bridge for owned Fab/Marketplace vault downloads via UEVaultManager.",
        automation_runtime="uevaultmanager_cli",
        fallback_bridge_ids=("fab_dummy_project", "fmodel_extract"),
    ),
    "fab_dummy_project": BridgeDefinition(
        bridge_id="fab_dummy_project",
        display_name="Fab Dummy Project Bridge",
        family=BridgeFamily.ENGINE_BRIDGE,
        adapter_id="epic_dummy_project",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Fallback bridge that uses a minimal .uproject to pull Fab assets without installing Unreal Engine.",
        automation_runtime="epic_launcher_dummy_project",
        fallback_bridge_ids=("fmodel_extract", "umodel_extract"),
    ),
    "asset_ripper_extract": BridgeDefinition(
        bridge_id="asset_ripper_extract",
        display_name="AssetRipper Extractor",
        family=BridgeFamily.EXTRACTOR,
        adapter_id="asset_ripper",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE, AssetCategory.ANIMATION),
        summary="Unity extractor bridge for reconstructing owned/licensed project content.",
    ),
    "asset_studio_extract": BridgeDefinition(
        bridge_id="asset_studio_extract",
        display_name="AssetStudio Extractor",
        family=BridgeFamily.EXTRACTOR,
        adapter_id="asset_studio",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.CHARACTER_BASE, AssetCategory.ANIMATION),
        summary="Unity targeted extractor bridge for grabbing specific meshes, sprites, and audio.",
    ),
    "fmodel_extract": BridgeDefinition(
        bridge_id="fmodel_extract",
        display_name="FModel Extractor",
        family=BridgeFamily.EXTRACTOR,
        adapter_id="fmodel",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Unreal extractor bridge for owned/licensed UE4/UE5 packages.",
    ),
    "umodel_extract": BridgeDefinition(
        bridge_id="umodel_extract",
        display_name="Umodel Extractor",
        family=BridgeFamily.EXTRACTOR,
        adapter_id="umodel",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Older Unreal extractor bridge and fallback to FModel.",
    ),
    "cue4parse_extract": BridgeDefinition(
        bridge_id="cue4parse_extract",
        display_name="CUE4Parse Extractor",
        family=BridgeFamily.EXTRACTOR,
        adapter_id="cue4parse",
        lane=ProviderLane.MANUAL_BROWSER,
        categories=(AssetCategory.PROP, AssetCategory.ARCHITECTURE, AssetCategory.ANIMATION),
        summary="Mass Unreal extraction bridge that emits PSK/texture intermediates for Blender batch conversion.",
        fallback_bridge_ids=("fmodel_extract", "umodel_extract"),
    ),
}


CATEGORY_ROUTING: dict[AssetCategory, CategoryRoute] = {
    AssetCategory.UI_HUD: CategoryRoute(
        category=AssetCategory.UI_HUD,
        primary_bridge_id="chatgpt_pro_ui",
        fallback_bridge_ids=("google_pro_ui", "hunyuan_image_colab_ui", "comfyui_local_ui", "fab_browser"),
        rationale="UI and HUD should use the strongest cloud 2D bridge first, then fall back to secondary cloud or local cleanup lanes.",
    ),
    AssetCategory.MATERIAL: CategoryRoute(
        category=AssetCategory.MATERIAL,
        primary_bridge_id="ambientcg",
        fallback_bridge_ids=("poly_haven", "hunyuan_image_colab_ui", "comfyui_local_ui"),
        rationale="Materials should start with direct-download CC0 sources, then be remixed locally if needed.",
    ),
    AssetCategory.WEAPON: CategoryRoute(
        category=AssetCategory.WEAPON,
        primary_bridge_id="kenney",
        fallback_bridge_ids=("smithsonian_museum", "quaternius_direct", "fab_browser", "unity_engine_bridge", "hunyuan3d2_3d", "trellis_3d"),
        rationale="Weapons should start with the fastest reusable direct packs, then mature into museum/manual references and paid sources, with generators reserved for gaps.",
    ),
    AssetCategory.PROP: CategoryRoute(
        category=AssetCategory.PROP,
        primary_bridge_id="kenney",
        fallback_bridge_ids=("quaternius_direct", "blenderkit", "fab_browser", "fab_auto_claim_bridge", "free_games_claimer_bridge", "fab_uevaultmanager", "fab_dummy_project", "cue4parse_extract", "unity_engine_bridge", "unreal_engine_bridge", "hunyuan3d2_3d", "trellis_3d"),
        rationale="Props should start with the strongest working direct packs, then move into paid/manual sources for better fidelity, with generators kept as gap fill only.",
    ),
    AssetCategory.CHARACTER_BASE: CategoryRoute(
        category=AssetCategory.CHARACTER_BASE,
        primary_bridge_id="mixamo_browser",
        fallback_bridge_ids=("makehuman_character", "quaternius_direct", "unity_store_browser", "fab_browser", "unity_engine_bridge"),
        rationale="Base humans and rigs should stay manual/source-first before generation.",
    ),
    AssetCategory.ANIMATION: CategoryRoute(
        category=AssetCategory.ANIMATION,
        primary_bridge_id="mixamo_animation_browser",
        fallback_bridge_ids=("mixamo_browser", "fab_auto_claim_bridge", "free_games_claimer_bridge", "fab_uevaultmanager", "fab_dummy_project", "cue4parse_extract", "unity_engine_bridge", "unreal_engine_bridge", "animationgpt_gap_fill"),
        rationale="Stock clips should come from manual or owned-package bridges; AnimationGPT only fills combat gaps.",
    ),
    AssetCategory.MUSIC: CategoryRoute(
        category=AssetCategory.MUSIC,
        primary_bridge_id="mixkit_audio",
        fallback_bridge_ids=("pixabay_audio", "opengameart_audio", "freesound_browser_audio", "musicgen_audio"),
        rationale="Music should use direct source libraries first; AI generation is a fallback when timing or style gaps remain.",
    ),
    AssetCategory.SFX: CategoryRoute(
        category=AssetCategory.SFX,
        primary_bridge_id="mixkit_audio",
        fallback_bridge_ids=("pixabay_audio", "freesound_audio", "freesound_browser_audio", "opengameart_audio", "audioldm2_audio"),
        rationale="SFX should use direct source libraries first; AI generation is a last-resort gap fill.",
    ),
    AssetCategory.MUSEUM_PROP: CategoryRoute(
        category=AssetCategory.MUSEUM_PROP,
        primary_bridge_id="smithsonian_open_access",
        fallback_bridge_ids=("the_met_open_access", "museum_browser"),
        rationale="Museum props should start from open-access or museum-owned sources before generation.",
    ),
    AssetCategory.ARCHITECTURE: CategoryRoute(
        category=AssetCategory.ARCHITECTURE,
        primary_bridge_id="kenney",
        fallback_bridge_ids=("quaternius_direct", "poly_haven", "blenderkit", "fab_browser", "unity_engine_bridge", "fab_auto_claim_bridge", "free_games_claimer_bridge", "fab_uevaultmanager", "fab_dummy_project", "cue4parse_extract", "unreal_engine_bridge", "asset_ripper_extract"),
        rationale="Architecture should start with the strongest working modular direct packs, then mature into paid/manual environment sources and engine-export bridges where needed.",
    ),
    AssetCategory.VEHICLE: CategoryRoute(
        category=AssetCategory.VEHICLE,
        primary_bridge_id="kenney_vehicle",
        fallback_bridge_ids=("nasa_3d_open", "browser_use_generic"),
        rationale="Vehicles should start with clean direct-download libraries before falling back to manual browser hunts.",
    ),
    AssetCategory.TERRAIN: CategoryRoute(
        category=AssetCategory.TERRAIN,
        primary_bridge_id="ambientcg",
        fallback_bridge_ids=("poly_haven", "polyhaven_terrain", "browser_use_generic"),
        rationale="Terrain should start with batchable direct materials and height-friendly texture families, then fall back to Poly Haven browser pulls when needed.",
    ),
    AssetCategory.ICON: CategoryRoute(
        category=AssetCategory.ICON,
        primary_bridge_id="game_icons_net",
        fallback_bridge_ids=("kenney", "chatgpt_pro_ui", "google_pro_ui", "comfyui_local_ui", "browser_use_generic"),
        rationale="Icons should start with broad reusable libraries before any bespoke generation work.",
    ),
    AssetCategory.VFX: CategoryRoute(
        category=AssetCategory.VFX,
        primary_bridge_id="kenney_vfx",
        fallback_bridge_ids=("opengameart_vfx", "browser_use_generic"),
        rationale="VFX should start with reusable CC0 effect atlases before hand-built or generated variants.",
    ),
    AssetCategory.FONT: CategoryRoute(
        category=AssetCategory.FONT,
        primary_bridge_id="google_fonts",
        fallback_bridge_ids=("browser_use_generic",),
        rationale="Fonts should start with clean OFL libraries and only fall back to manual hunting when style demands it.",
    ),
    AssetCategory.SKYBOX: CategoryRoute(
        category=AssetCategory.SKYBOX,
        primary_bridge_id="poly_haven",
        fallback_bridge_ids=("polyhaven_skybox", "browser_use_generic"),
        rationale="Skyboxes should start with batchable CC0 HDRIs, then fall back to browser-driven Poly Haven pulls only when the direct path is not enough.",
    ),
    AssetCategory.DIALOGUE: CategoryRoute(
        category=AssetCategory.DIALOGUE,
        primary_bridge_id="edge_tts_dialogue",
        fallback_bridge_ids=("elevenlabs_dialogue", "browser_use_generic"),
        rationale="Dialogue defaults to local Edge-TTS and can switch to ElevenLabs as an explicit hosted voice lane; browser/manual remains fallback only.",
    ),
    AssetCategory.SHADER: CategoryRoute(
        category=AssetCategory.SHADER,
        primary_bridge_id="shader_manual",
        fallback_bridge_ids=("browser_use_generic",),
        rationale="Shaders remain a manual/support lane until a stronger automated Flax shader bridge exists.",
    ),
}


def list_bridges() -> tuple[BridgeDefinition, ...]:
    return tuple(sorted(BRIDGE_REGISTRY.values(), key=lambda item: item.bridge_id))


def get_bridge(bridge_id: str) -> BridgeDefinition:
    return BRIDGE_REGISTRY[bridge_id]


def bridges_for_category(category: AssetCategory | str) -> tuple[BridgeDefinition, ...]:
    category_value = AssetCategory(category)
    return tuple(
        bridge for bridge in BRIDGE_REGISTRY.values() if category_value in bridge.categories
    )


def get_category_route(category: AssetCategory | str) -> CategoryRoute:
    return CATEGORY_ROUTING[AssetCategory(category)]


def recommended_skill_ids_for_category(category: AssetCategory | str) -> tuple[str, ...]:
    category_value = AssetCategory(category)
    skills = ("source-intel", "bridge-routing", "pack-verification-loop")
    if category_value in _BLENDER_HEAVY_CATEGORIES:
        skills = _merge_unique_strings(skills, ("blender-mcp-automation",))
    if category_value in {AssetCategory.UI_HUD, AssetCategory.ICON, AssetCategory.VFX, AssetCategory.DIALOGUE}:
        skills = _merge_unique_strings(skills, ("pipeline-orchestration",))
    return skills


def recommended_skill_ids_for_bridge(bridge_id: str) -> tuple[str, ...]:
    bridge = get_bridge(bridge_id)
    skills = _FAMILY_SKILLS.get(bridge.family, ())
    for category in bridge.categories:
        skills = _merge_unique_strings(skills, recommended_skill_ids_for_category(category))
    return skills


def bridge_batchability_band(bridge_id: str) -> BatchabilityBand:
    overridden = _BRIDGE_BATCHABILITY_OVERRIDES.get(bridge_id)
    if overridden is not None:
        return overridden

    bridge = get_bridge(bridge_id)
    if bridge.lane in {ProviderLane.DIRECT_URL, ProviderLane.GENERATOR}:
        return BatchabilityBand.BATCHABLE_NOW
    if bridge.automation_runtime in _MANUAL_BROWSER_BATCHABLE_RUNTIME_HINTS:
        return BatchabilityBand.BATCHABLE_WITH_MANUAL_STEPS
    return BatchabilityBand.MANUAL_GAP_FILL


def category_batchability(category: AssetCategory | str) -> CategoryBatchability:
    category_value = AssetCategory(category)
    route = get_category_route(category_value)
    primary_status = bridge_batchability_band(route.primary_bridge_id)
    best_bridge_id = route.primary_bridge_id
    best_status = primary_status
    best_bridge_lane = get_bridge(route.primary_bridge_id).lane

    for bridge_id in (route.primary_bridge_id, *route.fallback_bridge_ids):
        bridge = get_bridge(bridge_id)
        status = bridge_batchability_band(bridge_id)
        if _BATCHABILITY_RANK[status] < _BATCHABILITY_RANK[best_status]:
            best_bridge_id = bridge_id
            best_status = status
            best_bridge_lane = bridge.lane

    return CategoryBatchability(
        category=category_value,
        route=route,
        primary_bridge_id=route.primary_bridge_id,
        primary_status=primary_status,
        best_bridge_id=best_bridge_id,
        best_status=best_status,
        best_bridge_lane=best_bridge_lane,
    )


def lane_batchability_band(lane: ProviderLane | str) -> BatchabilityBand:
    canonical_lane = normalize_lane(lane)
    if canonical_lane in {ProviderLane.DIRECT_URL, ProviderLane.GENERATOR}:
        return BatchabilityBand.BATCHABLE_NOW
    return BatchabilityBand.BATCHABLE_WITH_MANUAL_STEPS


def validate_bridge_registry() -> tuple[str, ...]:
    errors: list[str] = []

    for bridge in list_bridges():
        try:
            adapter = require_source_adapter(bridge.adapter_id)
        except Exception as exc:
            errors.append(f"{bridge.bridge_id}: unknown adapter '{bridge.adapter_id}' ({exc})")
            continue

        if adapter.lane != bridge.lane:
            errors.append(
                f"{bridge.bridge_id}: lane mismatch bridge={bridge.lane.value} adapter={adapter.lane.value}"
            )

        for fallback_bridge_id in bridge.fallback_bridge_ids:
            if fallback_bridge_id not in BRIDGE_REGISTRY:
                errors.append(f"{bridge.bridge_id}: missing fallback bridge '{fallback_bridge_id}'")

        for skill_id in recommended_skill_ids_for_bridge(bridge.bridge_id):
            if skill_id not in _SKILL_DOC_PATHS:
                errors.append(f"{bridge.bridge_id}: unknown skill '{skill_id}'")
            elif not Path(skill_doc_path(skill_id)).exists():
                errors.append(f"{bridge.bridge_id}: missing skill doc '{skill_doc_path(skill_id)}'")

    for category in AssetCategory:
        route = CATEGORY_ROUTING.get(category)
        if route is None:
            errors.append(f"{category.value}: missing category route")
            continue

        if route.primary_bridge_id not in BRIDGE_REGISTRY:
            errors.append(f"{category.value}: missing primary bridge '{route.primary_bridge_id}'")
        else:
            primary_bridge = get_bridge(route.primary_bridge_id)
            if category not in primary_bridge.categories:
                errors.append(
                    f"{category.value}: primary bridge '{route.primary_bridge_id}' does not cover category"
                )

        for fallback_bridge_id in route.fallback_bridge_ids:
            if fallback_bridge_id not in BRIDGE_REGISTRY:
                errors.append(f"{category.value}: missing fallback bridge '{fallback_bridge_id}'")
                continue
            fallback_bridge = get_bridge(fallback_bridge_id)
            if category not in fallback_bridge.categories:
                errors.append(
                    f"{category.value}: fallback bridge '{fallback_bridge_id}' does not cover category"
                )

        for skill_id in recommended_skill_ids_for_category(category):
            if skill_id not in _SKILL_DOC_PATHS:
                errors.append(f"{category.value}: unknown skill '{skill_id}'")
            elif not Path(skill_doc_path(skill_id)).exists():
                errors.append(f"{category.value}: missing skill doc '{skill_doc_path(skill_id)}'")

    return tuple(errors)
