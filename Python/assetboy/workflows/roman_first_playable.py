from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from assetboy.library.paths import asset_library_root, imported_packs_dir
from assetboy.providers.bridge_registry import AssetCategory
from assetboy.providers.lanes import ProviderLane


_ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar", ".unitypackage"}
_MOCK_TOKENS = ("_mock.", "placeholder", "stub", "example")


@dataclass(frozen=True)
class RomanFirstPlayableSpec:
    pack_id: str
    roman_category: str
    priority: str
    expected_contents: tuple[str, ...]
    bootstrap_lane: ProviderLane
    matured_quality_lane: str
    generator_lane: str
    blender_required: bool
    output_formats: tuple[str, ...]
    extra_sidecars: tuple[str, ...]
    shared_family_tags: tuple[str, ...]
    flax_intended_use: str
    default_maturity_label: str
    asset_category: AssetCategory
    bridge_id: str
    source_adapter: str
    source_strategy: str
    fallback_adapters: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    quality_keywords: tuple[str, ...] = ()
    min_keyword_hits: int = 0
    min_payload_files: int = 1
    request_count: int = 1
    accept_archive_payload: bool = False
    asset_kind: str = "mesh"
    animated: bool = False


@dataclass(frozen=True)
class RomanPackAudit:
    pack_id: str
    publish_root: Path
    payload_root: Path
    imported_root: Path
    packet_exists: bool
    provenance_exists: bool
    payload_exists: bool
    imported_exists: bool
    payload_files: tuple[str, ...]
    mock_files: tuple[str, ...]
    archive_files: tuple[str, ...]
    keyword_hits: tuple[str, ...]
    actual_lane: str
    actual_source_adapter: str
    audit_status: str
    maturity_label: str
    ready_for_flax_packet: bool
    blocker_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "publish_root": str(self.publish_root),
            "payload_root": str(self.payload_root),
            "imported_root": str(self.imported_root),
            "packet_exists": self.packet_exists,
            "provenance_exists": self.provenance_exists,
            "payload_exists": self.payload_exists,
            "imported_exists": self.imported_exists,
            "payload_files": list(self.payload_files),
            "mock_files": list(self.mock_files),
            "archive_files": list(self.archive_files),
            "keyword_hits": list(self.keyword_hits),
            "actual_lane": self.actual_lane,
            "actual_source_adapter": self.actual_source_adapter,
            "audit_status": self.audit_status,
            "maturity_label": self.maturity_label,
            "ready_for_flax_packet": self.ready_for_flax_packet,
            "blocker_reasons": list(self.blocker_reasons),
        }


def _pack(
    *,
    pack_id: str,
    roman_category: str,
    priority: str,
    expected_contents: tuple[str, ...],
    bootstrap_lane: ProviderLane,
    matured_quality_lane: str,
    generator_lane: str,
    blender_required: bool,
    output_formats: tuple[str, ...],
    extra_sidecars: tuple[str, ...],
    shared_family_tags: tuple[str, ...],
    flax_intended_use: str,
    default_maturity_label: str,
    asset_category: AssetCategory,
    bridge_id: str,
    source_adapter: str,
    source_strategy: str,
    fallback_adapters: tuple[str, ...] = (),
    search_terms: tuple[str, ...] = (),
    quality_keywords: tuple[str, ...] = (),
    min_keyword_hits: int = 0,
    min_payload_files: int = 1,
    request_count: int = 1,
    accept_archive_payload: bool = False,
    asset_kind: str = "mesh",
    animated: bool = False,
) -> RomanFirstPlayableSpec:
    return RomanFirstPlayableSpec(
        pack_id=pack_id,
        roman_category=roman_category,
        priority=priority,
        expected_contents=expected_contents,
        bootstrap_lane=bootstrap_lane,
        matured_quality_lane=matured_quality_lane,
        generator_lane=generator_lane,
        blender_required=blender_required,
        output_formats=output_formats,
        extra_sidecars=extra_sidecars,
        shared_family_tags=shared_family_tags,
        flax_intended_use=flax_intended_use,
        default_maturity_label=default_maturity_label,
        asset_category=asset_category,
        bridge_id=bridge_id,
        source_adapter=source_adapter,
        source_strategy=source_strategy,
        fallback_adapters=fallback_adapters,
        search_terms=search_terms,
        quality_keywords=quality_keywords,
        min_keyword_hits=min_keyword_hits,
        min_payload_files=min_payload_files,
        request_count=request_count,
        accept_archive_payload=accept_archive_payload,
        asset_kind=asset_kind,
        animated=animated,
    )


ROMAN_FIRST_PLAYABLE_SPECS: tuple[RomanFirstPlayableSpec, ...] = (
    _pack(
        pack_id="RA_PACK_CHR_CORE_SLICE_01",
        roman_category="characters",
        priority="P0",
        expected_contents=(
            "shared male body/rig",
            "6 heads",
            "shared tunic",
            "shared sandals/footwear",
            "team overlays",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed/manual character and clothing sets",
        generator_lane="small overlay and gap variants only; never duelist-first",
        blender_required=True,
        output_formats=("fbx", "glb", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "rig_notes.md", "preview.png"),
        shared_family_tags=("shared_human_base_rigs",),
        flax_intended_use="shared fighter base plus class loadouts",
        default_maturity_label="experimental",
        asset_category=AssetCategory.CHARACTER_BASE,
        bridge_id="mixamo_browser",
        source_adapter="mixamo",
        source_strategy="Bootstrap the shared male rig/body first, then layer heads, tunic, sandals, and team overlays around the approved base.",
        fallback_adapters=("fab", "unity_asset_store"),
        search_terms=("male humanoid muscular", "fighter male base", "roman fighter base"),
        quality_keywords=("body", "head", "tunic", "sandal", "team"),
        min_keyword_hits=4,
        min_payload_files=5,
        asset_kind="character",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_CHR_SKIRMISHER_SLICE_01",
        roman_category="characters",
        priority="P0",
        expected_contents=("class kit: skirmisher",),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed/manual character and clothing sets",
        generator_lane="small cloth and overlay gap variants only",
        blender_required=True,
        output_formats=("fbx", "glb", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "rig_notes.md", "preview.png"),
        shared_family_tags=(),
        flax_intended_use="javelin skirmisher class silhouette",
        default_maturity_label="experimental",
        asset_category=AssetCategory.CHARACTER_BASE,
        bridge_id="fab_browser",
        source_adapter="fab",
        source_strategy="Use source-first class clothing or kitbash parts around the approved shared body; keep the skirmisher light and readable.",
        fallback_adapters=("mixamo", "unity_asset_store"),
        search_terms=("roman skirmisher tunic javelin", "light fighter wrap"),
        quality_keywords=("skirmisher", "javelin", "light", "wrap"),
        min_keyword_hits=1,
        min_payload_files=1,
        asset_kind="character",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_CHR_SLINGER_SLICE_01",
        roman_category="characters",
        priority="P0",
        expected_contents=("class kit: slinger",),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed/manual character and clothing sets",
        generator_lane="small cloth and pouch gap variants only",
        blender_required=True,
        output_formats=("fbx", "glb", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "rig_notes.md", "preview.png"),
        shared_family_tags=(),
        flax_intended_use="slinger class silhouette and pouch read",
        default_maturity_label="experimental",
        asset_category=AssetCategory.CHARACTER_BASE,
        bridge_id="fab_browser",
        source_adapter="fab",
        source_strategy="Use source-first class clothing or kitbash parts around the approved shared body; make the sling read instantly at match distance.",
        fallback_adapters=("mixamo", "unity_asset_store"),
        search_terms=("roman slinger tunic pouch", "light slinger wrap"),
        quality_keywords=("slinger", "sling", "pouch", "light"),
        min_keyword_hits=1,
        min_payload_files=1,
        asset_kind="character",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_CHR_DUELIST_SLICE_01",
        roman_category="characters",
        priority="P0",
        expected_contents=("class kit: duelist",),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed/manual character and clothing sets",
        generator_lane="not a primary lane for this pack",
        blender_required=True,
        output_formats=("fbx", "glb", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "rig_notes.md", "preview.png"),
        shared_family_tags=(),
        flax_intended_use="duelist class silhouette with stronger Roman read",
        default_maturity_label="experimental",
        asset_category=AssetCategory.CHARACTER_BASE,
        bridge_id="fab_browser",
        source_adapter="fab",
        source_strategy="Avoid generator-first here. Use manual or licensed class parts that keep the duelist historically grounded.",
        fallback_adapters=("mixamo", "unity_asset_store"),
        search_terms=("roman duelist shield tunic", "roman arena duelist"),
        quality_keywords=("duelist", "shield", "roman"),
        min_keyword_hits=1,
        min_payload_files=1,
        asset_kind="character",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
        roman_category="weapons_props",
        priority="P0",
        expected_contents=(
            "light javelin",
            "heavy javelin",
            "short spear",
            "hand sling",
            "sling stone",
            "stone pouch",
            "hardwood club",
            "gladius",
            "scutum",
            "javelin bundle",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed/manual hero weapons",
        generator_lane="carry-prop gap fill only after source-first pass",
        blender_required=True,
        output_formats=("glb", "fbx", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "preview.png"),
        shared_family_tags=("historic_tech_props_core",),
        flax_intended_use="hands, loadouts, and pickups",
        default_maturity_label="experimental",
        asset_category=AssetCategory.WEAPON,
        bridge_id="fab_browser",
        source_adapter="fab",
        source_strategy="Source the core Roman loadout first. Only use generator support for small carry-prop gaps after the hero silhouettes are credible.",
        fallback_adapters=("museum_page", "unity_asset_store"),
        search_terms=("roman weapons pack", "gladius scutum javelin spear sling"),
        quality_keywords=("javelin", "spear", "sling", "stone", "pouch", "club", "gladius", "scutum", "bundle"),
        min_keyword_hits=6,
        min_payload_files=6,
        asset_kind="weapon",
    ),
    _pack(
        pack_id="RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
        roman_category="environment_architecture",
        priority="P0",
        expected_contents=(
            "sandstone bowl arena shell",
            "floor",
            "mound",
            "walls",
            "gate",
            "tunnel",
            "stairs",
            "barriers",
            "columns",
            "shield rack",
            "banners",
            "urns",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed modular Roman kits",
        generator_lane="fill missing shell pieces only after source-first pass",
        blender_required=True,
        output_formats=("glb", "fbx", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "collision_notes.md", "preview.png"),
        shared_family_tags=("historic_roman_architecture_core",),
        flax_intended_use="assemble the playable arena shell",
        default_maturity_label="usable_with_manual_steps",
        asset_category=AssetCategory.ARCHITECTURE,
        bridge_id="fab_browser",
        source_adapter="fab",
        source_strategy="Use a compact Roman-adjacent modular shell first. Keep the pack tight enough to build one honest arena instead of a giant environment dump.",
        fallback_adapters=("unity_asset_store",),
        search_terms=("roman arena modular", "sandstone colosseum bowl"),
        quality_keywords=("arena", "wall", "gate", "stair", "tunnel", "column", "banner", "urn"),
        min_keyword_hits=2,
        min_payload_files=8,
        asset_kind="architecture",
    ),
    _pack(
        pack_id="RA_PACK_TRAP_SLICE_01",
        roman_category="traps",
        priority="P0",
        expected_contents=(
            "spike grate",
            "fire urn",
            "pendulum",
            "portcullis",
            "trigger plate",
            "intact/active/readable states",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="owned/licensed mechanical props",
        generator_lane="fire patch or small damage variants only",
        blender_required=True,
        output_formats=("glb", "fbx", "png", "jpg", "tga"),
        extra_sidecars=("cleanup_plan.json", "state_manifest.json", "preview.png"),
        shared_family_tags=(),
        flax_intended_use="placed hazard states",
        default_maturity_label="experimental",
        asset_category=AssetCategory.PROP,
        bridge_id="fab_browser",
        source_adapter="fab",
        source_strategy="Kitbash the trap families from readable mechanical pieces first. Keep the active and intact states obvious before chasing fidelity.",
        fallback_adapters=("unity_asset_store",),
        search_terms=("spike trap portcullis pendulum trap", "arena trap mechanical"),
        quality_keywords=("spike", "fire", "pendulum", "portcullis", "trigger"),
        min_keyword_hits=4,
        min_payload_files=4,
        asset_kind="prop",
    ),
    _pack(
        pack_id="RA_PACK_MAT_AND_POLISH_SLICE_01",
        roman_category="materials_textures",
        priority="P1",
        expected_contents=("sand", "sandstone", "leather", "wood", "iron", "coarse cloth"),
        bootstrap_lane=ProviderLane.DIRECT_URL,
        matured_quality_lane="licensed scans and curated material families",
        generator_lane="variant fill only after source baselines land",
        blender_required=False,
        output_formats=("png", "jpg", "tga", "hdr", "exr"),
        extra_sidecars=("material_notes.md", "license_snapshot.txt", "preview.png"),
        shared_family_tags=("historic_roman_materials_core",),
        flax_intended_use="sand, sandstone, leather, wood, iron, and cloth materials",
        default_maturity_label="usable_with_manual_steps",
        asset_category=AssetCategory.MATERIAL,
        bridge_id="ambientcg",
        source_adapter="ambientcg",
        source_strategy="Bootstrap with legally clear direct-download materials first. Upgrade to stronger scans later without locking the repo into free forever.",
        fallback_adapters=(),
        search_terms=("sand", "stone", "leather", "wood", "metal", "fabric"),
        quality_keywords=("sand", "stone", "leather", "wood", "metal", "fabric"),
        min_keyword_hits=4,
        min_payload_files=4,
        request_count=6,
        accept_archive_payload=True,
        asset_kind="material",
    ),
    _pack(
        pack_id="RA_PACK_ANM_COMBAT_SLICE_01",
        roman_category="animations",
        priority="P0",
        expected_contents=(
            "shared locomotion",
            "shared state",
            "shared reacts",
            "javelin set",
            "sling set",
            "duelist set",
            "trap react set",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="licensed/manual combat clips",
        generator_lane="AnimationGPT only after source baseline proves the timing",
        blender_required=True,
        output_formats=("fbx", "bvh"),
        extra_sidecars=("retarget_notes.md", "clip_manifest.json", "preview.png"),
        shared_family_tags=("shared_combat_animation_baseline",),
        flax_intended_use="combat graph clips and class action sets",
        default_maturity_label="experimental",
        asset_category=AssetCategory.ANIMATION,
        bridge_id="mixamo_browser",
        source_adapter="mixamo_animations",
        source_strategy="Source grounded locomotion, reacts, throws, and class-specific attacks first. Generator support is for clear gaps only.",
        fallback_adapters=(),
        search_terms=(
            "walk run sprint idle",
            "hit react stumble death",
            "javelin throw attack",
            "sling throw attack",
            "sword shield slash",
            "trap react knockback",
        ),
        quality_keywords=("idle", "run", "react", "javelin", "sling", "duelist", "trap"),
        min_keyword_hits=5,
        min_payload_files=6,
        asset_kind="animation",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_AUD_SFX_SLICE_01",
        roman_category="audio_sfx",
        priority="P0",
        expected_contents=(
            "combat SFX baseline",
            "trap warning/impact baseline",
            "UI/combat feedback baseline",
        ),
        bootstrap_lane=ProviderLane.DIRECT_URL,
        matured_quality_lane="licensed SFX library",
        generator_lane="small accent gap-fill only",
        blender_required=False,
        output_formats=("wav", "ogg", "mp3"),
        extra_sidecars=("mastering_notes.md", "clip_manifest.json"),
        shared_family_tags=(),
        flax_intended_use="combat, trap, and UI cues",
        default_maturity_label="experimental",
        asset_category=AssetCategory.SFX,
        bridge_id="mixkit_audio",
        source_adapter="mixkit",
        source_strategy="Curate a small direct-download baseline that covers weapon impacts, warnings, footsteps, and UI confirms before any generator fill.",
        fallback_adapters=(),
        search_terms=("combat footsteps", "shield impact", "trap warning", "ui confirm"),
        quality_keywords=("impact", "footstep", "trap", "warning", "ui", "fire"),
        min_keyword_hits=3,
        min_payload_files=3,
        request_count=4,
        accept_archive_payload=True,
        asset_kind="audio",
    ),
    _pack(
        pack_id="RA_PACK_AUD_MUSIC_SLICE_01",
        roman_category="music",
        priority="P0",
        expected_contents=("one arena/combat ambience or loop baseline",),
        bootstrap_lane=ProviderLane.DIRECT_URL,
        matured_quality_lane="licensed or owned loop",
        generator_lane="temporary style gap cover only",
        blender_required=False,
        output_formats=("wav", "ogg", "mp3"),
        extra_sidecars=("loop_notes.md", "mastering_notes.md"),
        shared_family_tags=(),
        flax_intended_use="one loopable arena/combat bed",
        default_maturity_label="experimental",
        asset_category=AssetCategory.MUSIC,
        bridge_id="mixkit_audio",
        source_adapter="mixkit",
        source_strategy="Choose one honest loopable arena/combat bed from a legally clear source before considering generator backups.",
        fallback_adapters=(),
        search_terms=("roman combat loop", "arena ambience loop"),
        quality_keywords=("arena", "combat", "loop", "ambience"),
        min_keyword_hits=2,
        min_payload_files=1,
        request_count=1,
        accept_archive_payload=True,
        asset_kind="audio",
    ),
)


_PACK_ID_INDEX = {spec.pack_id: spec for spec in ROMAN_FIRST_PLAYABLE_SPECS}

ROMAN_PACK_DEFAULT_ONLY_SPECS: tuple[RomanFirstPlayableSpec, ...] = (
    _pack(
        pack_id="RA_PACK_COMBAT_PREP_SLICE_01",
        roman_category="combat_presentation",
        priority="P0",
        expected_contents=(
            "coherent Kevin or B-hips body lane",
            "first-person arms candidate",
            "primary spear mesh",
            "idle, walk, run, sprint, strafe, jump begin, jump land",
            "spear carry and combat idle",
            "light polearm melee and heavy melee partial",
            "death plus explicit fallback stagger and throw coverage",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="reviewed coherent Kevin-lane body, arms candidate, spear, and grounded combat clips",
        generator_lane="generator fill is a last resort after coherent source-first coverage",
        blender_required=True,
        output_formats=("fbx", "glb"),
        extra_sidecars=("cleanup_plan.json", "rig_notes.md", "clip_manifest.json", "preview.png"),
        shared_family_tags=("shared_combat_animation_baseline", "shared_human_base_rigs"),
        flax_intended_use="baseline first-person and third-person Roman spear combat lane",
        default_maturity_label="experimental",
        asset_category=AssetCategory.CHARACTER_BASE,
        bridge_id="mixamo_browser",
        source_adapter="mixamo",
        source_strategy="Prefer one coherent Kevin or B-hips lane that already covers locomotion, spear carry, melee, and a usable upper-body arms candidate before filling gaps.",
        fallback_adapters=("fab", "unity_asset_store"),
        search_terms=(
            "Kevin HumanM spear polearm combat",
            "Mixamo spear carry run strafe jump",
            "first person arms polearm combat",
        ),
        quality_keywords=("arms", "spear", "idle", "run", "strafe", "jump", "melee", "death"),
        min_keyword_hits=5,
        min_payload_files=8,
        asset_kind="character",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_COMBAT_PREP_SLICE_02",
        roman_category="combat_presentation",
        priority="P0",
        expected_contents=(
            "true first-person arms or stronger viewmodel lane",
            "same-lane crouch locomotion",
            "same-lane throw windup, release, and recover",
            "same-lane upper and lower hit reacts",
            "same-lane stagger and recovery",
            "same-lane wounded or limp locomotion",
            "weapon grip and left-hand support targets",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="reviewed coherent follow-up combat body and arms lane with the missing authored clips",
        generator_lane="generator fill only after coherent source-first slice-02 search fails",
        blender_required=True,
        output_formats=("fbx", "glb"),
        extra_sidecars=("cleanup_plan.json", "rig_notes.md", "clip_manifest.json", "preview.png"),
        shared_family_tags=("shared_combat_animation_baseline", "shared_human_base_rigs"),
        flax_intended_use="close the missing first-person combat coverage for throw, reacts, wounded, and crouch",
        default_maturity_label="experimental",
        asset_category=AssetCategory.CHARACTER_BASE,
        bridge_id="mixamo_browser",
        source_adapter="mixamo",
        source_strategy="Stay on one coherent humanoid lane and only accept source-first slices that close the crouch, throw, hit-react, and wounded gaps without rig drift.",
        fallback_adapters=("fab", "unity_asset_store"),
        search_terms=(
            "Kevin HumanM crouch throw stagger wounded",
            "Mixamo polearm throw hit react limp",
            "first person arms wounded combat",
        ),
        quality_keywords=("arms", "crouch", "throw", "hit", "stagger", "wounded", "limp"),
        min_keyword_hits=5,
        min_payload_files=6,
        asset_kind="character",
        animated=True,
    ),
    _pack(
        pack_id="RA_PACK_ANM_COMBAT_SLICE_02",
        roman_category="animations",
        priority="P0",
        expected_contents=(
            "throw windup, release, and recover",
            "upper-body hit reacts",
            "lower-body hit reacts",
            "stagger and knockback recovery",
            "wounded or limp locomotion",
            "same-lane crouch locomotion",
        ),
        bootstrap_lane=ProviderLane.MANUAL_BROWSER,
        matured_quality_lane="reviewed combat gap-fill clips on the same Roman humanoid lane",
        generator_lane="AnimationGPT only after source-first clip search proves the gaps are still real",
        blender_required=True,
        output_formats=("fbx", "bvh"),
        extra_sidecars=("retarget_notes.md", "clip_manifest.json", "preview.png"),
        shared_family_tags=("shared_combat_animation_baseline",),
        flax_intended_use="animation-only gap fill for Roman spear combat coverage",
        default_maturity_label="experimental",
        asset_category=AssetCategory.ANIMATION,
        bridge_id="mixamo_browser",
        source_adapter="mixamo_animations",
        source_strategy="Source clip-level throw, react, crouch, and wounded coverage on the same humanoid lane before accepting cross-rig filler.",
        fallback_adapters=(),
        search_terms=(
            "javelin throw windup release recover",
            "hit react stagger knockback",
            "wounded limp crouch locomotion",
        ),
        quality_keywords=("throw", "hit", "stagger", "wounded", "limp", "crouch"),
        min_keyword_hits=4,
        min_payload_files=5,
        asset_kind="animation",
        animated=True,
    ),
)

_ROMAN_PACK_ID_INDEX = {
    spec.pack_id: spec
    for spec in (*ROMAN_FIRST_PLAYABLE_SPECS, *ROMAN_PACK_DEFAULT_ONLY_SPECS)
}


def roman_first_playable_specs() -> tuple[RomanFirstPlayableSpec, ...]:
    return ROMAN_FIRST_PLAYABLE_SPECS


def roman_first_playable_pack_ids() -> tuple[str, ...]:
    return tuple(spec.pack_id for spec in ROMAN_FIRST_PLAYABLE_SPECS)


def get_roman_first_playable_spec(pack_id: str) -> RomanFirstPlayableSpec:
    try:
        return _PACK_ID_INDEX[pack_id]
    except KeyError as exc:
        raise KeyError(f"Unknown Roman first-playable pack: {pack_id}") from exc


def get_roman_pack_spec(pack_id: str) -> RomanFirstPlayableSpec:
    try:
        return _ROMAN_PACK_ID_INDEX[pack_id]
    except KeyError as exc:
        raise KeyError(f"Unknown Roman pack: {pack_id}") from exc


def _is_mock_file(filename: str) -> bool:
    lowered = filename.lower()
    return any(token in lowered for token in _MOCK_TOKENS)


def _is_archive_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in _ARCHIVE_SUFFIXES


def _payload_files(payload_root: Path) -> tuple[str, ...]:
    if not payload_root.exists():
        return ()
    return tuple(sorted(path.name for path in payload_root.iterdir() if path.is_file()))


def _read_provenance_fields(publish_root: Path) -> tuple[str, str]:
    provenance_path = publish_root / "provenance.json"
    if not provenance_path.exists():
        return "unknown", "unknown"
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return "invalid_json", "invalid_json"
    return (
        str(payload.get("lane", "unknown")).strip() or "unknown",
        str(payload.get("source_adapter", "unknown")).strip() or "unknown",
    )


def audit_roman_pack(
    spec: RomanFirstPlayableSpec,
    *,
    game_scope: str = "roman_arena",
    repo_root: str | Path | None = None,
) -> RomanPackAudit:
    publish_root = asset_library_root(repo_root) / "publish" / "flax_intake" / game_scope / spec.pack_id
    payload_root = publish_root / "payload"
    imported_root = imported_packs_dir(repo_root) / spec.pack_id

    payload_files = _payload_files(payload_root)
    packet_exists = (publish_root / "packet.json").exists()
    provenance_exists = (publish_root / "provenance.json").exists()
    payload_exists = payload_root.exists()
    imported_exists = imported_root.exists()
    actual_lane, actual_source_adapter = _read_provenance_fields(publish_root)

    mock_files = tuple(filename for filename in payload_files if _is_mock_file(filename))
    archive_files = tuple(filename for filename in payload_files if _is_archive_file(filename))
    audit_candidates = tuple(filename for filename in payload_files if filename not in mock_files)
    if not spec.accept_archive_payload:
        audit_candidates = tuple(filename for filename in audit_candidates if filename not in archive_files)

    lowered_names = tuple(filename.lower() for filename in audit_candidates)
    keyword_hits = tuple(
        keyword
        for keyword in spec.quality_keywords
        if any(keyword in filename for filename in lowered_names)
    )

    blocker_reasons: list[str] = []
    if not payload_exists:
        blocker_reasons.append("missing payload folder")
    if not packet_exists:
        blocker_reasons.append("missing packet.json")
    if not provenance_exists:
        blocker_reasons.append("missing provenance.json")
    if mock_files:
        blocker_reasons.append(f"mock payload files present: {', '.join(mock_files[:3])}")
    if payload_exists and not packet_exists and not provenance_exists and payload_files:
        blocker_reasons.append("payload exists without review sidecars")
    if payload_files and len(keyword_hits) < spec.min_keyword_hits:
        blocker_reasons.append(
            f"Roman content markers only {len(keyword_hits)}/{spec.min_keyword_hits} strong hits"
        )
    if len(audit_candidates) < spec.min_payload_files and payload_files:
        blocker_reasons.append(
            f"only {len(audit_candidates)} payload files count toward the Roman slice; expected at least {spec.min_payload_files}"
        )
    if packet_exists and provenance_exists and payload_exists and not imported_exists:
        blocker_reasons.append("reviewed packet exists but has not been imported into Flax yet")

    if payload_exists and payload_files and not packet_exists and not provenance_exists:
        audit_status = "payload_only_stub"
        maturity_label = "experimental"
        ready_for_flax_packet = False
    elif not payload_exists and not packet_exists and not provenance_exists:
        audit_status = "missing"
        maturity_label = "planning_only"
        ready_for_flax_packet = False
    elif (
        packet_exists
        and provenance_exists
        and payload_exists
        and not mock_files
        and len(keyword_hits) >= spec.min_keyword_hits
        and len(audit_candidates) >= spec.min_payload_files
    ):
        audit_status = "reviewed_real"
        maturity_label = "usable_with_manual_steps"
        ready_for_flax_packet = True
    else:
        audit_status = "reviewed_but_content_thin"
        maturity_label = spec.default_maturity_label
        ready_for_flax_packet = False

    return RomanPackAudit(
        pack_id=spec.pack_id,
        publish_root=publish_root,
        payload_root=payload_root,
        imported_root=imported_root,
        packet_exists=packet_exists,
        provenance_exists=provenance_exists,
        payload_exists=payload_exists,
        imported_exists=imported_exists,
        payload_files=payload_files,
        mock_files=mock_files,
        archive_files=archive_files,
        keyword_hits=keyword_hits,
        actual_lane=actual_lane,
        actual_source_adapter=actual_source_adapter,
        audit_status=audit_status,
        maturity_label=maturity_label,
        ready_for_flax_packet=ready_for_flax_packet,
        blocker_reasons=tuple(blocker_reasons),
    )


def audit_roman_first_playable(
    *,
    game_scope: str = "roman_arena",
    repo_root: str | Path | None = None,
) -> tuple[RomanPackAudit, ...]:
    return tuple(
        audit_roman_pack(spec, game_scope=game_scope, repo_root=repo_root)
        for spec in ROMAN_FIRST_PLAYABLE_SPECS
    )
