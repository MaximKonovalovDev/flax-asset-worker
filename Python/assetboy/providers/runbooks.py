from __future__ import annotations

from dataclasses import asdict, dataclass

from assetboy.providers.ai_bridge import AI_PROVIDER_PROFILES
from assetboy.providers.generator import load_colab_profile, profile_ids


@dataclass(frozen=True)
class StaticProviderRunbook:
    provider_id: str
    display_name: str
    provider_family: str
    lane: str
    access_surface: str
    official_url: str = ""
    setup_steps: tuple[str, ...] = ()
    progression_steps: tuple[str, ...] = ()
    checklist: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


STATIC_PROVIDER_RUNBOOKS: dict[str, StaticProviderRunbook] = {
    "direct_url_lane": StaticProviderRunbook(
        provider_id="direct_url_lane",
        display_name="Direct URL Lane",
        provider_family="lane",
        lane="direct_url",
        access_surface="Repo CLI queue and reviewed-packet flow",
        setup_steps=(
            "Confirm `print-provider-readiness --json` shows the direct lane as ready.",
            "Prefer sources where the exact file URL and license page are already known.",
            "Queue downloads through the shared queue instead of dropping raw files straight into Flax.",
        ),
        progression_steps=(
            "Acquire the source archive or files through the queue runner.",
            "Validate the reviewed packet and provenance before Flax intake.",
            "Use `print-pack-readiness --json` to confirm the pack moved from blocked to ready_reviewed.",
        ),
        checklist=(
            "Capture source page URL and exact file URL in provenance.",
            "Keep filenames stable between download, cleanup, and payload handoff.",
            "Use direct_url only when the source is truly direct-download friendly.",
        ),
    ),
    "fab": StaticProviderRunbook(
        provider_id="fab",
        display_name="Fab",
        provider_family="manual_browser",
        lane="manual_browser",
        access_surface="Epic/Fab browser session plus reviewed packet flow",
        official_url="https://www.fab.com/",
        setup_steps=(
            "Run `python scripts/cli.py asset-factory fab-auth --reuse-profile` first.",
            "If there is no existing browser session, rerun with `--allow-browser` from a real interactive desktop terminal and complete the visible Epic/Fab login.",
            "Keep the shared browser profile alive after login so later download jobs can reuse it.",
        ),
        progression_steps=(
            "Use `run-fab-batch` for deterministic listing intake and fallback job emission.",
            "When a listing skips or fails direct download, execute the emitted browser job instead of improvising.",
            "Register the reviewed packet and re-check `print-pack-readiness --json` before Flax intake.",
        ),
        checklist=(
            "Capture product page URL, seller, and license wording in provenance.",
            "Prefer deterministic batch artifacts over ad-hoc downloads.",
            "Treat Fab auth as shared browser state that other provider lanes may reuse.",
        ),
    ),
    "mixamo": StaticProviderRunbook(
        provider_id="mixamo",
        display_name="Mixamo",
        provider_family="manual_browser",
        lane="manual_browser",
        access_surface="Adobe/Mixamo browser workflow",
        official_url="https://www.mixamo.com/",
        setup_steps=(
            "Run `python scripts/cli.py asset-factory mixamo-auth --reuse-profile` first.",
            "If the shared browser profile is empty, rerun with `--allow-browser` from a real interactive desktop terminal and finish the Adobe login in the visible window.",
            "Keep the saved browser profile so animation acquisition does not require repeated sign-ins.",
        ),
        progression_steps=(
            "Acquire the character or animation clip through the browser/manual flow.",
            "Preserve export settings, clip names, and source page URLs in provenance.",
            "Move accepted files into cleanup before reviewed packet registration.",
        ),
        checklist=(
            "Record exact character/animation ids and export options.",
            "Avoid mixing unrelated clips into one pack unless the pack plan explicitly calls for it.",
            "Re-check readiness before assuming the saved session is still valid.",
        ),
    ),
    "unity_asset_store": StaticProviderRunbook(
        provider_id="unity_asset_store",
        display_name="Unity Asset Store",
        provider_family="manual_browser",
        lane="manual_browser",
        access_surface="Unity Asset Store browser login plus local Unity export bridge",
        official_url="https://assetstore.unity.com/",
        setup_steps=(
            "Run `python scripts/cli.py asset-factory unity-auth --reuse-profile` first.",
            "If no shared browser state exists, rerun with `--allow-browser` from a real interactive desktop terminal and finish the Unity sign-in flow.",
            "Confirm at least one usable Unity editor install is detected before planning large acquisition batches.",
        ),
        progression_steps=(
            "Acquire store packages through the browser/manual lane.",
            "Push package extraction and export through the Unity bridge instead of unpacking ad-hoc.",
            "Register the reviewed packet only after export outputs are staged and provenance is complete.",
        ),
        checklist=(
            "Capture package page, publisher, version, and archive name.",
            "Do not treat Asset Store login alone as enough; the Unity export bridge must also be ready.",
            "Prefer deterministic project-ingest or export jobs when a pack needs repeatability.",
        ),
    ),
    "unity_export_bridge": StaticProviderRunbook(
        provider_id="unity_export_bridge",
        display_name="Unity Export Bridge",
        provider_family="engine_bridge",
        lane="manual_browser",
        access_surface="Local Unity editor installation",
        setup_steps=(
            "Install a supported Unity editor through Unity Hub or expose the editor path under the normal search roots.",
            "Confirm `list-unity-installs` shows `usable=true` before planning export work.",
            "Keep one clean export project ready for store package ingest and repeatable export runs.",
        ),
        progression_steps=(
            "Use the bridge job emitters instead of exporting assets manually.",
            "Stage exported meshes, textures, and audio into the reviewed packet boundary.",
            "Feed the reviewed payload into Flax only after cleanup and provenance validation.",
        ),
        checklist=(
            "Prefer one Unity install lane that stays stable for repeated exports.",
            "Treat exported outputs as upstream artifacts, not final Flax truth until packet registration.",
        ),
    ),
    "unreal_export_bridge": StaticProviderRunbook(
        provider_id="unreal_export_bridge",
        display_name="Unreal Export Bridge",
        provider_family="engine_bridge",
        lane="manual_browser",
        access_surface="Local Unreal editor command-line installation",
        setup_steps=(
            "Install a full Unreal editor build, not just launcher stubs or empty version folders.",
            "Confirm `list-unreal-installs` shows a usable command path before planning Unreal export automation.",
            "If a version root exists but no editor binaries are detected, repair or reinstall that Unreal version.",
        ),
        progression_steps=(
            "Emit Unreal export jobs instead of exporting by hand.",
            "Use extraction tools only as fallbacks when the editor bridge is unavailable or too heavy for the pack.",
            "Stage export outputs into cleanup and the reviewed packet boundary before Flax intake.",
        ),
        checklist=(
            "A detected Unreal version folder is not enough; `usable=true` is the real readiness gate.",
            "Keep the project/export path deterministic so repeated runs stay comparable.",
        ),
    ),
    "epic_extraction": StaticProviderRunbook(
        provider_id="epic_extraction",
        display_name="Epic/Fab Extraction",
        provider_family="extractor_bridge",
        lane="manual_browser",
        access_surface="FModel/UModel/CUE4Parse or compatible Unreal extraction helpers",
        setup_steps=(
            "Confirm `print-provider-readiness --json` shows extraction tools or a compatible Unreal path.",
            "Keep Epic launcher cache and Fab library metadata intact when doing owned-library work.",
            "Use extractor tooling only on assets you own and are authorized to process.",
        ),
        progression_steps=(
            "Map owned library state first, then emit deterministic extraction jobs.",
            "Use extraction as a bridge into reviewed packets, not as a direct Flax import shortcut.",
            "Prefer recorded extraction artifacts so later packs can be reproduced.",
        ),
        checklist=(
            "Capture source app/listing identity in provenance.",
            "Keep extraction outputs separate from reviewed payload until cleanup finishes.",
        ),
    ),
    "legendary": StaticProviderRunbook(
        provider_id="legendary",
        display_name="Legendary Bridge",
        provider_family="owned_library",
        lane="manual_browser",
        access_surface="Legendary CLI plus Epic launcher remember-me token",
        setup_steps=(
            "Install `legendary` and confirm the executable is discoverable.",
            "Import Epic auth with `python scripts/cli.py asset-factory legendary-import-auth` if the session is missing.",
            "Use `legendary-status` to confirm the account is visible before batch planning.",
        ),
        progression_steps=(
            "List owned Unreal assets first.",
            "Install or bridge owned assets through deterministic job specs instead of ad-hoc launcher clicks.",
            "Route extracted outputs through reviewed packets and cleanup before Flax intake.",
        ),
        checklist=(
            "Treat Legendary as an owned-library bridge, not a generic downloader.",
            "Keep launcher auth healthy so later sync and install steps stay non-interactive.",
        ),
    ),
    "generator_profiles": StaticProviderRunbook(
        provider_id="generator_profiles",
        display_name="Generator Profiles",
        provider_family="generator",
        lane="generator",
        access_surface="Colab profiles and local/cloud AI provider profiles",
        setup_steps=(
            "Use `print-provider-readiness --json` to see which generator profiles are available.",
            "Pick one profile per pack and keep prompt provenance attached to that pack.",
            "Do not mix generated outputs directly into Flax without reviewed packet registration.",
        ),
        progression_steps=(
            "Emit a generator setup batch for the chosen profile.",
            "Review outputs, cleanup results, and provenance before publish.",
            "Register the reviewed packet and verify readiness progression before Flax intake.",
        ),
        checklist=(
            "Capture prompt, profile/model, and seeds or session notes.",
            "Treat generated outputs as upstream artifacts until the packet is validated.",
        ),
    ),
}


def provider_runbook_ids() -> tuple[str, ...]:
    return tuple(sorted((*STATIC_PROVIDER_RUNBOOKS.keys(), *AI_PROVIDER_PROFILES.keys(), *profile_ids())))


def build_provider_runbook_payload(provider_id: str) -> dict[str, object]:
    if provider_id in STATIC_PROVIDER_RUNBOOKS:
        profile = STATIC_PROVIDER_RUNBOOKS[provider_id]
        payload = asdict(profile)
        payload["review_checklist"] = list(profile.checklist)
        payload["rendered_text"] = render_provider_runbook(provider_id)
        payload.pop("checklist", None)
        return payload

    if provider_id in AI_PROVIDER_PROFILES:
        profile = AI_PROVIDER_PROFILES[provider_id]
        return {
            "provider_id": profile.provider_id,
            "display_name": profile.display_name,
            "provider_family": "ai_provider",
            "runtime_kind": profile.runtime_kind,
            "access_surface": profile.access_surface or "",
            "official_url": profile.official_url or "",
            "asset_categories": [category.value for category in profile.asset_categories],
            "output_formats": list(profile.output_formats),
            "setup_steps": list(profile.setup_steps),
            "progression_steps": list(profile.progression_steps),
            "review_checklist": list(profile.checklist),
            "notes": [],
            "rendered_text": render_provider_runbook(provider_id),
        }

    profile = load_colab_profile(provider_id)
    return {
        "provider_id": profile.profile_id,
        "display_name": profile.display_name,
        "provider_family": "colab_generator",
        "model_name": profile.model_name,
        "lane": profile.lane,
        "asset_kind": profile.asset_kind,
        "access_surface": profile.access_surface or "",
        "official_url": profile.official_url or "",
        "export_targets": list(profile.export_targets),
        "setup_steps": list(profile.setup_steps),
        "progression_steps": list(profile.progression_steps),
        "review_checklist": list(profile.review_checklist),
        "notes": [],
        "rendered_text": render_provider_runbook(provider_id),
    }


def render_provider_runbook(provider_id: str) -> str:
    if provider_id in STATIC_PROVIDER_RUNBOOKS:
        profile = STATIC_PROVIDER_RUNBOOKS[provider_id]
        lines = [
            f"provider_id={profile.provider_id}",
            f"display_name={profile.display_name}",
            f"provider_family={profile.provider_family}",
            f"lane={profile.lane}",
            f"access_surface={profile.access_surface or '<unspecified>'}",
            f"official_url={profile.official_url or '<unspecified>'}",
        ]
        if profile.setup_steps:
            lines.append("setup_steps:")
            lines.extend(f" - {step}" for step in profile.setup_steps)
        if profile.progression_steps:
            lines.append("progression_steps:")
            lines.extend(f" - {step}" for step in profile.progression_steps)
        if profile.checklist:
            lines.append("review_checklist:")
            lines.extend(f" - {line}" for line in profile.checklist)
        if profile.notes:
            lines.append("notes:")
            lines.extend(f" - {line}" for line in profile.notes)
        return "\n".join(lines)

    if provider_id in AI_PROVIDER_PROFILES:
        profile = AI_PROVIDER_PROFILES[provider_id]
        lines = [
            f"provider_id={profile.provider_id}",
            f"display_name={profile.display_name}",
            "provider_family=ai_provider",
            f"runtime_kind={profile.runtime_kind}",
            f"access_surface={profile.access_surface or '<unspecified>'}",
            f"official_url={profile.official_url or '<unspecified>'}",
            f"asset_categories={','.join(category.value for category in profile.asset_categories)}",
            f"output_formats={','.join(profile.output_formats)}",
        ]
        if profile.setup_steps:
            lines.append("setup_steps:")
            lines.extend(f" - {step}" for step in profile.setup_steps)
        if profile.progression_steps:
            lines.append("progression_steps:")
            lines.extend(f" - {step}" for step in profile.progression_steps)
        if profile.checklist:
            lines.append("review_checklist:")
            lines.extend(f" - {line}" for line in profile.checklist)
        return "\n".join(lines)

    profile = load_colab_profile(provider_id)
    lines = [
        f"provider_id={profile.profile_id}",
        f"display_name={profile.display_name}",
        "provider_family=colab_generator",
        f"model_name={profile.model_name}",
        f"lane={profile.lane}",
        f"asset_kind={profile.asset_kind}",
        f"access_surface={profile.access_surface or '<unspecified>'}",
        f"official_url={profile.official_url or '<unspecified>'}",
        f"export_targets={','.join(profile.export_targets)}",
    ]
    if profile.setup_steps:
        lines.append("setup_steps:")
        lines.extend(f" - {step}" for step in profile.setup_steps)
    if profile.progression_steps:
        lines.append("progression_steps:")
        lines.extend(f" - {step}" for step in profile.progression_steps)
    if profile.review_checklist:
        lines.append("review_checklist:")
        lines.extend(f" - {line}" for line in profile.review_checklist)
    return "\n".join(lines)
