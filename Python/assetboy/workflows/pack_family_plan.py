from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, publish_payload_dir
from assetboy.library.shared_packs import SharedPackFamily, get_shared_pack_family, planned_shared_pack_families
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.ai_bridge import AI_PROVIDER_PROFILES, emit_ai_bridge_job
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.bridge_registry import get_bridge
from assetboy.providers.direct_url import build_queue_template_rows, write_queue_rows
from assetboy.providers.engine_bridge import emit_engine_export_job
from assetboy.providers.generator import emit_generator_setup


BROWSER_SOURCE_URLS: dict[str, str] = {
    "mixamo_browser": "https://www.mixamo.com/",
    "fab_browser": "https://www.fab.com/",
    "unity_store_browser": "https://assetstore.unity.com/",
    "museum_browser": "https://3d.si.edu/",
    "freesound_browser_audio": "https://freesound.org/",
    "browser_use_generic": "",
}

SOURCE_PAGE_URLS: dict[str, str] = {
    "poly_haven": "https://polyhaven.com/",
    "ambientcg": "https://ambientcg.com/",
    "kenney": "https://kenney.nl/assets",
    "game_icons_net": "https://game-icons.net/",
    "mixkit_audio": "https://mixkit.co/",
    "freesound_audio": "https://freesound.org/",
    "zapsplat": "https://www.zapsplat.com/",
    "musopen_classical": "https://musopen.org/",
    "ccmixter_music": "https://ccmixter.org/",
    "google_fonts": "https://fonts.google.com/",
    "kenney_vfx": "https://kenney.nl/assets",
    "polyhaven_skybox": "https://polyhaven.com/hdris",
    "polyhaven_terrain": "https://polyhaven.com/textures",
    "smithsonian_museum": "https://3d.si.edu/",
}

DEFAULT_PROFILE_BY_BRIDGE_ID: dict[str, str] = {
    "hunyuan3d2_3d": "hunyuan3d2.production",
    "trellis_3d": "trellis.secondary",
    "animationgpt_colab": "animationgpt.pilot",
    "animationgpt_gap_fill": "animationgpt.pilot",
}

ENGINE_KIND_BY_BRIDGE_ID: dict[str, str] = {
    "unity_engine_bridge": "unity",
    "unreal_engine_bridge": "unreal",
}


@dataclass(frozen=True)
class PackFamilyPlanArtifacts:
    output_dir: Path
    manifest_path: Path
    summary_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "summary_path": str(self.summary_path),
        }


def _selected_families(
    *,
    wave: int | None,
    pack_ids: tuple[str, ...] | None,
) -> tuple[SharedPackFamily, ...]:
    if pack_ids:
        families = tuple(get_shared_pack_family(pack_id) for pack_id in pack_ids)
        if wave is not None:
            families = tuple(family for family in families if family.wave == wave)
        return families
    return planned_shared_pack_families(wave=wave)


def _artifact_root(base_dir: Path, family: SharedPackFamily, bridge_id: str) -> Path:
    return base_dir / family.pack_id / bridge_id


def _direct_url_artifacts(
    family: SharedPackFamily,
    *,
    bridge_id: str,
    game_scope: str,
    base_dir: Path,
) -> dict[str, object]:
    bridge = get_bridge(bridge_id)
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=family.pack_id)
    root_dir = _artifact_root(base_dir, family, bridge_id)
    rows = build_queue_template_rows(
        pack_id=family.pack_id,
        game_scope=game_scope,
        request_count=max(1, int(family.request_count)),
        source_adapter=bridge.adapter_id,
        notes=family.seed_strategy,
    )
    queue_template_path = write_queue_rows(rows, path=root_dir / "queue_template.csv")
    provenance = build_provenance_template(
        pack_id=family.pack_id,
        game_scope=game_scope,
        lane=bridge.lane,
        source_adapter=bridge.adapter_id,
        payload_target_path=str(payload_target),
        notes=tuple(
            item
            for item in (
                family.description,
                family.seed_strategy,
                f"Review slice: {family.review_slice}" if family.review_slice else "",
            )
            if item
        ),
    )
    if bridge_id in SOURCE_PAGE_URLS:
        provenance["values"]["source_page_url"] = SOURCE_PAGE_URLS[bridge_id]
    provenance_path = write_json(root_dir / "provenance_template.json", provenance)
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    review_checklist_path = write_text(
        root_dir / "review_checklist.md",
        "\n".join(
            [
                f"# Direct URL Family Checklist: {family.pack_id}",
                "",
                f"- Bridge: `{bridge_id}`",
                f"- Domain: `{family.domain}`",
                f"- Description: {family.description}",
                f"- Request count: `{family.request_count}`",
                f"- Source page: `{SOURCE_PAGE_URLS.get(bridge_id, '') or '<fill during acquisition>'}`",
                f"- Payload target: `{payload_target}`",
                "",
                "## Operator Steps",
                "- Fill queue template URLs with concrete source files.",
                "- Preserve source page URL, license URL, author/vendor, and original filenames.",
                "- Stage accepted files into the payload target only after review.",
                "- Write packet/provenance before counting the family as ready.",
            ]
        )
        + "\n",
    )
    request_summary_path = write_json(
        root_dir / "request_summary.json",
        {
            "pack_id": family.pack_id,
            "bridge_id": bridge_id,
            "adapter_id": bridge.adapter_id,
            "game_scope": game_scope,
            "request_count": family.request_count,
            "seed_strategy": family.seed_strategy,
            "search_terms": list(family.search_terms),
            "review_slice": family.review_slice,
        },
    )
    return {
        "bridge_id": bridge_id,
        "lane": bridge.lane.value,
        "artifact_dir": str(root_dir),
        "queue_template_path": str(queue_template_path),
        "provenance_template_path": str(provenance_path),
        "payload_target_path_file": str(payload_target_path_file),
        "review_checklist_path": str(review_checklist_path),
        "request_summary_path": str(request_summary_path),
    }


def _emit_bridge_artifacts(
    family: SharedPackFamily,
    *,
    bridge_id: str,
    game_scope: str,
    base_dir: Path,
    browser_runtime: BrowserRuntime,
) -> dict[str, object]:
    bridge = get_bridge(bridge_id)
    root_dir = _artifact_root(base_dir, family, bridge_id)

    if bridge.lane.value == "direct_url":
        return _direct_url_artifacts(family, bridge_id=bridge_id, game_scope=game_scope, base_dir=base_dir)

    if bridge.lane.value == "manual_browser":
        if bridge_id in ENGINE_KIND_BY_BRIDGE_ID:
            artifacts = emit_engine_export_job(
                engine=ENGINE_KIND_BY_BRIDGE_ID[bridge_id],
                pack_id=family.pack_id,
                game_scope=game_scope,
                source_url=BROWSER_SOURCE_URLS.get("unity_store_browser", "") if bridge_id == "unity_engine_bridge" else "https://www.fab.com/",
                license_note=family.seed_strategy,
                source_package_name=family.pack_id,
                asset_kind=family.asset_category or family.domain,
                output_dir=root_dir,
                notes=tuple(
                    item
                    for item in (
                        family.description,
                        family.seed_strategy,
                        f"Review slice: {family.review_slice}" if family.review_slice else "",
                    )
                    if item
                ),
            )
            payload = artifacts.to_dict()
            payload["bridge_id"] = bridge_id
            payload["lane"] = bridge.lane.value
            return payload

        artifacts = emit_browser_automation_job(
            source_adapter=bridge.adapter_id,
            runtime=browser_runtime,
            pack_id=family.pack_id,
            game_scope=game_scope,
            source_url=BROWSER_SOURCE_URLS.get(bridge_id, ""),
            search_terms=family.search_terms,
            login_required=True,
            output_dir=root_dir,
            notes=tuple(
                item
                for item in (
                    family.description,
                    family.seed_strategy,
                    f"Review slice: {family.review_slice}" if family.review_slice else "",
                )
                if item
            ),
        )
        payload = artifacts.to_dict()
        payload["bridge_id"] = bridge_id
        payload["lane"] = bridge.lane.value
        return payload

    if bridge.adapter_id in AI_PROVIDER_PROFILES:
        artifacts = emit_ai_bridge_job(
            provider_id=bridge.adapter_id,
            pack_id=family.pack_id,
            game_scope=game_scope,
            output_dir=root_dir,
            notes=tuple(
                item
                for item in (
                    family.description,
                    family.seed_strategy,
                    f"Review slice: {family.review_slice}" if family.review_slice else "",
                )
                if item
            ),
        )
        payload = artifacts.to_dict()
        payload["bridge_id"] = bridge_id
        payload["lane"] = bridge.lane.value
        return payload

    profile_id = DEFAULT_PROFILE_BY_BRIDGE_ID.get(bridge_id)
    if profile_id:
        artifacts = emit_generator_setup(
            profile_id=profile_id,
            pack_id=family.pack_id,
            game_scope=game_scope,
            output_dir=root_dir,
            animated=family.asset_category == "animation",
        )
        payload = artifacts.to_dict()
        payload["bridge_id"] = bridge_id
        payload["lane"] = bridge.lane.value
        payload["profile_id"] = profile_id
        return payload

    stub_path = write_json(
        root_dir / "bridge_stub.json",
        {
            "pack_id": family.pack_id,
            "bridge_id": bridge_id,
            "adapter_id": bridge.adapter_id,
            "lane": bridge.lane.value,
            "reason": "no_artifact_emitter_available",
        },
    )
    return {
        "bridge_id": bridge_id,
        "lane": bridge.lane.value,
        "artifact_dir": str(root_dir),
        "bridge_stub_path": str(stub_path),
    }


def _family_summary_lines(entry: dict[str, object]) -> list[str]:
    family = entry["family"]
    primary = entry["primary"]
    fallbacks = entry.get("fallbacks", [])
    lines = [
        f"## {family['pack_id']}",
        "",
        f"- Wave: `{family.get('wave', 0)}`",
        f"- Domain: `{family['domain']}`",
        f"- Category: `{family.get('asset_category', '') or '<unspecified>'}`",
        f"- Primary bridge: `{primary['bridge_id']}` on `{primary['lane']}`",
        f"- Description: {family['description']}",
        f"- Seed strategy: {family['seed_strategy']}",
    ]
    if family.get("review_slice"):
        lines.append(f"- Review slice: {family['review_slice']}")
    if fallbacks:
        fallback_names = ", ".join(f"`{fallback['bridge_id']}`" for fallback in fallbacks)
        lines.append(f"- Fallbacks: {fallback_names}")
    lines.append("")
    return lines


def emit_pack_family_plan(
    *,
    game_scope: str = "shared",
    wave: int | None = None,
    pack_ids: tuple[str, ...] | None = None,
    output_dir: str | Path | None = None,
    browser_runtime: BrowserRuntime | str = BrowserRuntime.PLAYWRIGHT_MCP,
) -> PackFamilyPlanArtifacts:
    families = _selected_families(wave=wave, pack_ids=pack_ids)
    runtime = BrowserRuntime(browser_runtime)
    wave_label = f"wave_{wave}" if wave is not None else "all_waves"
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "pack_family_plans" / game_scope / wave_label
    )

    entries: list[dict[str, object]] = []
    for family in families:
        if not family.primary_bridge_id:
            continue
        primary = _emit_bridge_artifacts(
            family,
            bridge_id=family.primary_bridge_id,
            game_scope=game_scope,
            base_dir=root_dir,
            browser_runtime=runtime,
        )
        fallbacks = [
            _emit_bridge_artifacts(
                family,
                bridge_id=bridge_id,
                game_scope=game_scope,
                base_dir=root_dir / "fallback",
                browser_runtime=runtime,
            )
            for bridge_id in family.fallback_bridge_ids
        ]
        entries.append(
            {
                "family": family.to_dict(),
                "primary": primary,
                "fallbacks": fallbacks,
            }
        )

    manifest_path = write_json(
        root_dir / "pack_family_plan.json",
        {
            "game_scope": game_scope,
            "wave": wave,
            "family_count": len(entries),
            "families": entries,
        },
    )
    summary_lines = [
        "# Pack Family Plan",
        "",
        f"- Game scope: `{game_scope}`",
        f"- Wave: `{wave if wave is not None else 'all'}`",
        f"- Families: `{len(entries)}`",
        "",
    ]
    for entry in entries:
        summary_lines.extend(_family_summary_lines(entry))
    summary_path = write_text(root_dir / "pack_family_plan.md", "\n".join(summary_lines).rstrip() + "\n")
    return PackFamilyPlanArtifacts(
        output_dir=root_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
    )
