from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.library.paths import download_queue_csv, manual_drop_pack_dir, publish_payload_dir


class ProviderLane(str, Enum):
    DIRECT_URL = "direct_url"
    MANUAL_BROWSER = "manual_browser"
    GENERATOR = "generator"


_LANE_ALIASES: dict[str, ProviderLane] = {
    "direct": ProviderLane.DIRECT_URL,
    "direct-url": ProviderLane.DIRECT_URL,
    "download_queue": ProviderLane.DIRECT_URL,
    "queue": ProviderLane.DIRECT_URL,
    "manual": ProviderLane.MANUAL_BROWSER,
    "manual-browser": ProviderLane.MANUAL_BROWSER,
    "manual_drop": ProviderLane.MANUAL_BROWSER,
    "browser": ProviderLane.MANUAL_BROWSER,
    "gen": ProviderLane.GENERATOR,
    "ai_generator": ProviderLane.GENERATOR,
}

_SOURCE_ADAPTER_ALIASES: dict[str, str] = {
    "unity_asset_store_manual": "unity_asset_store",
}


@dataclass(frozen=True)
class LanePolicy:
    lane: ProviderLane
    description: str
    default_destination: str
    review_required: bool = True


@dataclass(frozen=True)
class SourceAdapter:
    adapter_id: str
    lane: ProviderLane
    display_name: str
    source_strategy: str
    default_profile: str = ""
    notes: str = ""


LANE_POLICIES: dict[ProviderLane, LanePolicy] = {
    ProviderLane.DIRECT_URL: LanePolicy(
        lane=ProviderLane.DIRECT_URL,
        description="Queue direct file URLs for the operator queue runner.",
        default_destination=r"artifacts\quality\asset-download-jobs\queue.csv",
    ),
    ProviderLane.MANUAL_BROWSER: LanePolicy(
        lane=ProviderLane.MANUAL_BROWSER,
        description="User downloads files from browser-gated sources into manual_drop.",
        default_destination=r"artifacts\library\FlaxAssetLibrary\inbox\downloads\manual_drop\<pack_id>",
    ),
    ProviderLane.GENERATOR: LanePolicy(
        lane=ProviderLane.GENERATOR,
        description="Generator or Colab output staged as reviewed payload with provenance.",
        default_destination=r"artifacts\library\FlaxAssetLibrary\publish\flax_intake\<game_scope>\<pack_id>\payload",
    ),
}


SOURCE_ADAPTERS: dict[str, SourceAdapter] = {
    "direct_url_queue": SourceAdapter(
        adapter_id="direct_url_queue",
        lane=ProviderLane.DIRECT_URL,
        display_name="Direct URL Queue",
        source_strategy="Queue direct-download sources into the shared queue.csv without changing the publish contract.",
        notes="Best for CC0/open-access files where a direct asset URL is already known.",
    ),
    "ambientcg_direct": SourceAdapter(
        adapter_id="ambientcg_direct",
        lane=ProviderLane.DIRECT_URL,
        display_name="ambientCG Direct",
        source_strategy="Use direct ambientCG downloads for CC0 PBR texture sets.",
        notes="Capture the asset page and resolution-specific ZIP URL in provenance.",
    ),
    "font_direct_url": SourceAdapter(
        adapter_id="font_direct_url",
        lane=ProviderLane.DIRECT_URL,
        display_name="Google Fonts Direct",
        source_strategy="Use direct Google Fonts URLs for OFL game fonts.",
        notes="Record the exact font file URL and font family page in provenance.",
    ),
    "game_icons_github": SourceAdapter(
        adapter_id="game_icons_github",
        lane=ProviderLane.DIRECT_URL,
        display_name="game-icons.net GitHub",
        source_strategy="Use the GitHub release ZIP for the full CC BY 3.0 icon set.",
        notes="Record the release URL and attribution string in provenance.",
    ),
    "kenney_direct": SourceAdapter(
        adapter_id="kenney_direct",
        lane=ProviderLane.DIRECT_URL,
        display_name="Kenney Direct",
        source_strategy="Use direct Kenney downloads for CC0 packs and curated presets.",
        notes="Capture the pack page or ZIP URL in provenance.",
    ),
    "kenney_vfx_direct": SourceAdapter(
        adapter_id="kenney_vfx_direct",
        lane=ProviderLane.DIRECT_URL,
        display_name="Kenney VFX Direct",
        source_strategy="Use direct Kenney VFX downloads for CC0 effect packs.",
        notes="Capture the pack page or ZIP URL in provenance.",
    ),
    "quaternius_direct": SourceAdapter(
        adapter_id="quaternius_direct",
        lane=ProviderLane.DIRECT_URL,
        display_name="Quaternius Direct",
        source_strategy="Use direct Quaternius downloads for free game-ready packs.",
        notes="Capture the specific archive URL and pack page in provenance.",
    ),
    "vehicle_direct_url": SourceAdapter(
        adapter_id="vehicle_direct_url",
        lane=ProviderLane.DIRECT_URL,
        display_name="Vehicle Direct URL",
        source_strategy="Use direct vehicle pack URLs for CC0 transport assets.",
        notes="Capture the exact archive URL in provenance.",
    ),
    "mixkit": SourceAdapter(
        adapter_id="mixkit",
        lane=ProviderLane.DIRECT_URL,
        display_name="Mixkit",
        source_strategy="Use direct-download Mixkit assets for quick audio sourcing with provenance capture.",
        notes="Capture the specific asset page and license note for each clip.",
    ),
    "pixabay_audio": SourceAdapter(
        adapter_id="pixabay_audio",
        lane=ProviderLane.DIRECT_URL,
        display_name="Pixabay Audio",
        source_strategy="Use direct-download Pixabay audio where the license terms fit the project.",
        notes="Record clip page, creator, and license note in provenance.",
    ),
    "freesound_audio": SourceAdapter(
        adapter_id="freesound_audio",
        lane=ProviderLane.DIRECT_URL,
        display_name="Freesound",
        source_strategy="Use Freesound clips with per-asset license capture and review.",
        notes="Per-asset license capture is mandatory.",
    ),
    "freesound_browser": SourceAdapter(
        adapter_id="freesound_browser",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Freesound (Manual)",
        source_strategy="Use manual browser downloads for Freesound when login or license confirmation is required.",
        notes="Record per-asset license, author, and download page URL.",
    ),
    "manual_browser_drop": SourceAdapter(
        adapter_id="manual_browser_drop",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Manual Browser Drop",
        source_strategy="Use a reviewed browser/manual download flow, then drop the approved files into the pack inbox.",
        notes="Capture the source page URL, license note, and original filenames in provenance.",
    ),
    "blenderkit": SourceAdapter(
        adapter_id="blenderkit",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="BlenderKit",
        source_strategy="Use BlenderKit inside Blender for subscription-backed sourcing, then export approved assets into AssetBoy cleanup.",
        notes="Record the BlenderKit asset page, author, and export settings in provenance.",
    ),
    "mixamo_manual_browser": SourceAdapter(
        adapter_id="mixamo_manual_browser",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Mixamo Manual Browser",
        source_strategy="Use Mixamo in browser for rigged character bases and stock animation clips.",
        notes="Record the exact Mixamo page, animation ids, and export settings in provenance.",
    ),
    "museum_browser_drop": SourceAdapter(
        adapter_id="museum_browser_drop",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Museum Browser Drop",
        source_strategy="Use museum or open-access browser drops when rights confirmation is manual.",
        notes="Record the object page URL and rights statement in provenance.",
    ),
    "opengameart": SourceAdapter(
        adapter_id="opengameart",
        lane=ProviderLane.DIRECT_URL,
        display_name="OpenGameArt",
        source_strategy="Use OpenGameArt as a fallback open-content source when stronger options fail.",
        notes="Verify pack-level license compatibility before use.",
    ),
    "fab": SourceAdapter(
        adapter_id="fab",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Fab",
        source_strategy="Use browser/manual flow for gated downloads and preserve the product page in provenance.",
        notes="Capture product page, seller, and license wording before downloading.",
    ),
    "fab_auto_claim": SourceAdapter(
        adapter_id="fab_auto_claim",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Fab Auto Claim",
        source_strategy="Use controlled automation on your own account to claim free Fab assets, then download through normal vault paths.",
        notes="Respect marketplace terms and keep claim logs in provenance notes.",
    ),
    "free_games_claimer": SourceAdapter(
        adapter_id="free_games_claimer",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Free Games Claimer",
        source_strategy="Use a self-hosted background claimer on your owned accounts for free drops, then process downloads through AssetBoy.",
        notes="Use only with accounts you own and operate.",
    ),
    "unity_asset_store": SourceAdapter(
        adapter_id="unity_asset_store",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Unity Asset Store",
        source_strategy="Use the browser/manual flow for store-gated packages and unpack them outside the Flax intake path.",
        notes="Record package page, publisher, version, and package archive name.",
    ),
    "mixamo": SourceAdapter(
        adapter_id="mixamo",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Mixamo",
        source_strategy="Use Mixamo for quick rigged human bases and baseline combat animations before generator fallback.",
        notes="Record export settings, character id, and animation ids in provenance.",
    ),
    "museum_page": SourceAdapter(
        adapter_id="museum_page",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Museum Page",
        source_strategy="Use museum object pages when downloads are browser-gated or need manual rights confirmation.",
        notes="Object page URL and rights statement are mandatory provenance fields.",
    ),
    "polyhaven_playwright": SourceAdapter(
        adapter_id="polyhaven_playwright",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Poly Haven Browser",
        source_strategy="Use browser automation for Poly Haven HDRIs and terrain downloads when the direct preset lane is not enough.",
        notes="Record the asset page URL, chosen resolution, and downloaded archive names in provenance.",
    ),
    "unity_engine_bridge": SourceAdapter(
        adapter_id="unity_engine_bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Unity Engine Bridge",
        source_strategy="Download a licensed Unity package, import it into a throwaway Unity project, then export open formats for AssetBoy cleanup and publish.",
        notes="Keep source URL, package name, and license note in provenance; skip code-heavy/editor-only packages by default.",
    ),
    "unreal_engine_bridge": SourceAdapter(
        adapter_id="unreal_engine_bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Unreal Engine Bridge",
        source_strategy="Download a licensed Unreal or Fab package, import it into a throwaway Unreal project, then export open formats for AssetBoy cleanup and publish.",
        notes="Keep source URL, package name, and license note in provenance; skip plugins and code-heavy packages by default.",
    ),
    "uevaultmanager": SourceAdapter(
        adapter_id="uevaultmanager",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="UEVaultManager",
        source_strategy="Download owned Fab/Marketplace vault assets without Epic Launcher, then extract open formats for AssetBoy cleanup and publish.",
        notes="Use only with licensed account ownership; keep vault item id/name and source URL in provenance.",
    ),
    "epic_dummy_project": SourceAdapter(
        adapter_id="epic_dummy_project",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Epic Dummy Project",
        source_strategy="Use a minimal .uproject to pull Fab/Marketplace assets via Epic Launcher without installing Unreal Engine, then extract open formats.",
        notes="Keep dummy project metadata and launcher version selection in provenance.",
    ),
    "asset_ripper": SourceAdapter(
        adapter_id="asset_ripper",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="AssetRipper",
        source_strategy="Extract owned or licensed Unity package content into open formats for cleanup and publish.",
        notes="Use only on owned or licensed content.",
    ),
    "asset_studio": SourceAdapter(
        adapter_id="asset_studio",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="AssetStudio",
        source_strategy="Target specific Unity assets for extraction when full project reconstruction is unnecessary.",
        notes="Use only on owned or licensed content.",
    ),
    "fmodel": SourceAdapter(
        adapter_id="fmodel",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="FModel",
        source_strategy="Extract owned or licensed Unreal content into open formats before cleanup.",
        notes="Use only on owned or licensed content.",
    ),
    "umodel": SourceAdapter(
        adapter_id="umodel",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Umodel",
        source_strategy="Fallback Unreal extraction bridge for older content or FModel gaps.",
        notes="Use only on owned or licensed content.",
    ),
    "cue4parse": SourceAdapter(
        adapter_id="cue4parse",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="CUE4Parse",
        source_strategy="Mass-extract owned/licensed Unreal .uasset content into open/intermediate formats for Blender conversion.",
        notes="Use only on owned or licensed content.",
    ),
    "roman_manual_source": SourceAdapter(
        adapter_id="roman_manual_source",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Roman Manual Source",
        source_strategy="Use manual browser extraction for Roman preset source packs that require operator review.",
        notes="Record the browser source URL and the imported launcher metadata in provenance.",
    ),
    "chatgpt_pro": SourceAdapter(
        adapter_id="chatgpt_pro",
        lane=ProviderLane.GENERATOR,
        display_name="ChatGPT Pro",
        source_strategy="Use ChatGPT Pro for prompt drafting, image generation workflows, and UI iteration.",
        notes="Primary cloud 2D bridge for HUD, menu, and support-texture work.",
    ),
    "google_pro": SourceAdapter(
        adapter_id="google_pro",
        lane=ProviderLane.GENERATOR,
        display_name="Google Pro",
        source_strategy="Use Google Pro as a secondary cloud AI bridge for 2D generation and prompt exploration.",
        notes="Secondary cloud 2D bridge when ChatGPT Pro misses the target look.",
    ),
    "hunyuan_image_colab": SourceAdapter(
        adapter_id="hunyuan_image_colab",
        lane=ProviderLane.GENERATOR,
        display_name="Hunyuan Image Colab",
        source_strategy="Use the Hunyuan image Colab lane for concept sheets, material references, and generator support images.",
        notes="Capture the prompt batch and accepted outputs in provenance.",
    ),
    "comfyui_local": SourceAdapter(
        adapter_id="comfyui_local",
        lane=ProviderLane.GENERATOR,
        display_name="ComfyUI Local",
        source_strategy="Use local RTX3050 ComfyUI workflows for texture remix, upscaling, inpaint, and UI variants.",
        notes="Best local 2D remix bridge.",
    ),
    "edge_tts_local": SourceAdapter(
        adapter_id="edge_tts_local",
        lane=ProviderLane.GENERATOR,
        display_name="Edge TTS Local",
        source_strategy="Use Edge TTS locally for dialogue generation and voice previews.",
        notes="Capture voice and prompt metadata in provenance.",
    ),
    "elevenlabs_api": SourceAdapter(
        adapter_id="elevenlabs_api",
        lane=ProviderLane.GENERATOR,
        display_name="ElevenLabs API",
        source_strategy="Use ElevenLabs through env-based API credentials for production-grade placeholder dialogue and narration.",
        notes="Set ELEVENLABS_API_KEY and optional ELEVENLABS_VOICE_ID_* overrides before live runs.",
    ),
    "animationgpt_colab": SourceAdapter(
        adapter_id="animationgpt_colab",
        lane=ProviderLane.GENERATOR,
        display_name="AnimationGPT Colab",
        source_strategy="Use AnimationGPT Colab for pilot combat animation generation.",
        notes="Capture the notebook/session and prompt details in provenance.",
    ),
    "step1x3d": SourceAdapter(
        adapter_id="step1x3d",
        lane=ProviderLane.GENERATOR,
        display_name="Step1X-3D",
        source_strategy="Use Step1X-3D as the primary open experimentation lane for text/image-to-3D generation.",
        default_profile="step1x3d.open",
        notes="Open-license friendly baseline for repeatable provider-matrix runs.",
    ),
    "topiaxl": SourceAdapter(
        adapter_id="topiaxl",
        lane=ProviderLane.GENERATOR,
        display_name="3DTopia-XL",
        source_strategy="Use 3DTopia-XL for prompt-first prop generation when text-to-3D speed is the priority.",
        default_profile="topiaxl.textfirst",
        notes="Strong text-first backup lane for rapid ideation.",
    ),
    "hunyuan3d2": SourceAdapter(
        adapter_id="hunyuan3d2",
        lane=ProviderLane.GENERATOR,
        display_name="Hunyuan3D-2",
        source_strategy="Use Hunyuan3D-2 for high-fidelity internal evaluation when open-lane providers miss quality targets.",
        default_profile="hunyuan3d2.production",
        notes="Prefer as an eval lane due license constraints in broad/public deployment.",
    ),
    "trellis": SourceAdapter(
        adapter_id="trellis",
        lane=ProviderLane.GENERATOR,
        display_name="TRELLIS",
        source_strategy="Use TRELLIS as a secondary generator lane when Hunyuan cannot hold silhouette or topology.",
        default_profile="trellis.secondary",
        notes="Secondary lane only; keep provenance tied to the exact prompt/image inputs.",
    ),
    "animationgpt": SourceAdapter(
        adapter_id="animationgpt",
        lane=ProviderLane.GENERATOR,
        display_name="AnimationGPT",
        source_strategy="Use AnimationGPT only for combat-gap pilot clips that manual sources cannot cover cleanly.",
        default_profile="animationgpt.pilot",
        notes="Pilot lane only. Use for combat-gap clips, not full animation libraries.",
    ),
    "musicgen": SourceAdapter(
        adapter_id="musicgen",
        lane=ProviderLane.GENERATOR,
        display_name="MusicGen",
        source_strategy="Generate music beds when direct-source libraries cannot supply the needed timing or mood.",
        notes="Capture prompt, duration, and model info in provenance.",
    ),
    "audioldm2": SourceAdapter(
        adapter_id="audioldm2",
        lane=ProviderLane.GENERATOR,
        display_name="AudioLDM2",
        source_strategy="Generate sound effects and ambience when source libraries cannot cover the required timing or mix.",
        notes="Capture prompt, duration, and model info in provenance.",
    ),
    "makehuman_direct": SourceAdapter(
        adapter_id="makehuman_direct",
        lane=ProviderLane.DIRECT_URL,
        display_name="MakeHuman Direct",
        source_strategy="Use MakeHuman source exports and direct asset drops for character baselines.",
        notes="Record the source project or export URL in provenance.",
    ),
    "mixamo_animations": SourceAdapter(
        adapter_id="mixamo_animations",
        lane=ProviderLane.MANUAL_BROWSER,
        display_name="Mixamo Animations",
        source_strategy="Use Mixamo browser animation pulls for combat and locomotion clips.",
        notes="Record the exact animation ids and export settings in provenance.",
    ),
}

GENERATOR_OBJECTIVE_MATRIX: dict[str, tuple[str, ...]] = {
    "open_experiment": ("step1x3d", "topiaxl", "trellis", "hunyuan3d2"),
    "text_first": ("topiaxl", "step1x3d", "trellis", "hunyuan3d2"),
    "high_fidelity_eval": ("hunyuan3d2", "step1x3d", "topiaxl", "trellis"),
}


def get_adapter(adapter_id: str) -> SourceAdapter:
    return SOURCE_ADAPTERS[adapter_id]


def canonical_source_adapter_id(adapter_id: str) -> str:
    normalized = str(adapter_id).strip()
    if not normalized:
        return normalized

    canonical = normalized.lower().replace("-", "_").replace(" ", "_")
    if canonical in SOURCE_ADAPTERS:
        return canonical

    alias = _SOURCE_ADAPTER_ALIASES.get(canonical)
    if alias:
        return alias

    return normalized


def require_source_adapter(adapter_id: str) -> SourceAdapter:
    normalized_adapter_id = canonical_source_adapter_id(adapter_id)
    if not normalized_adapter_id:
        raise ValueError("source_adapter is required")
    try:
        return SOURCE_ADAPTERS[normalized_adapter_id]
    except KeyError as exc:
        allowed = ", ".join(sorted(SOURCE_ADAPTERS))
        raise ValueError(f"Unsupported source_adapter '{adapter_id}'. Allowed: {allowed}.") from exc


def normalize_lane(lane: ProviderLane | str) -> ProviderLane:
    if isinstance(lane, ProviderLane):
        return lane

    raw_value = str(lane).strip()
    if not raw_value:
        allowed = ", ".join(item.value for item in ProviderLane)
        raise ValueError(f"lane is required. Allowed: {allowed}.")

    normalized_value = raw_value.lower().replace(" ", "_")
    if normalized_value in ProviderLane._value2member_map_:
        return ProviderLane(normalized_value)

    alias = _LANE_ALIASES.get(normalized_value)
    if alias is not None:
        return alias

    allowed = ", ".join(item.value for item in ProviderLane)
    raise ValueError(f"Unsupported lane '{lane}'. Allowed: {allowed}.")


def canonical_lane_value(lane: ProviderLane | str) -> str:
    return normalize_lane(lane).value


def adapters_for_lane(lane: ProviderLane) -> tuple[SourceAdapter, ...]:
    return tuple(adapter for adapter in SOURCE_ADAPTERS.values() if adapter.lane == lane)


def rank_generator_adapters(objective: str = "open_experiment") -> tuple[SourceAdapter, ...]:
    normalized_objective = str(objective or "").strip().lower()
    ranked_ids = GENERATOR_OBJECTIVE_MATRIX.get(normalized_objective)
    if not ranked_ids:
        ranked_ids = GENERATOR_OBJECTIVE_MATRIX["open_experiment"]
    ranked = []
    for adapter_id in ranked_ids:
        adapter = SOURCE_ADAPTERS.get(adapter_id)
        if adapter and adapter.lane == ProviderLane.GENERATOR:
            ranked.append(adapter)
    return tuple(ranked)


def resolve_lane_destination(
    lane: ProviderLane | str,
    *,
    pack_id: str = "",
    game_scope: str = "roman_arena",
) -> Path:
    canonical_lane = normalize_lane(lane)
    if canonical_lane == ProviderLane.DIRECT_URL:
        return download_queue_csv()
    if canonical_lane == ProviderLane.MANUAL_BROWSER:
        return manual_drop_pack_dir(pack_id)
    if not pack_id:
        raise ValueError("pack_id is required for generator destinations")
    return publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
