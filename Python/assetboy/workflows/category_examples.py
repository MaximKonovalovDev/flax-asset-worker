from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import write_json
from assetboy.library.paths import generated_output_root
from assetboy.providers.ai_bridge import emit_ai_bridge_job
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.direct_url import build_queue_template_rows, write_queue_rows
from assetboy.providers.engine_bridge import emit_engine_export_job
from assetboy.providers.generator import emit_generator_setup


@dataclass(frozen=True)
class CategoryExamples:
    output_dir: Path
    summary_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "summary_path": str(self.summary_path),
        }


def _queue_template(
    root_dir: Path,
    *,
    pack_id: str,
    game_scope: str,
    source_adapter: str,
    count: int,
    notes: str,
) -> Path:
    rows = build_queue_template_rows(
        pack_id=pack_id,
        game_scope=game_scope,
        request_count=count,
        source_adapter=source_adapter,
        notes=notes,
    )
    return write_queue_rows(rows, path=root_dir / f"{pack_id}_queue_template.csv")


def emit_category_examples(
    *,
    game_scope: str = "roman_arena",
    output_dir: str | Path | None = None,
) -> CategoryExamples:
    root_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "category_examples"
    root_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict[str, str]] = {}

    summary["ui_hud"] = {
        "generator": str(
            emit_ai_bridge_job(
                provider_id="chatgpt_pro",
                pack_id="RA_PACK_UI_COMBAT_SLICE_01",
                game_scope=game_scope,
                output_dir=root_dir / "ui_hud" / "generator_chatgpt_pro",
            ).output_dir
        ),
        "colab_image": str(
            emit_ai_bridge_job(
                provider_id="hunyuan_image_colab",
                pack_id="RA_PACK_UI_COMBAT_SLICE_01",
                game_scope=game_scope,
                output_dir=root_dir / "ui_hud" / "generator_hunyuan_image",
            ).output_dir
        ),
    }

    summary["material"] = {
        "direct_url": str(
            _queue_template(
                root_dir / "material",
                pack_id="RA_PACK_MAT_SAMPLE_01",
                game_scope=game_scope,
                source_adapter="ambientcg",
                count=3,
                notes="Example PBR materials from ambientCG.",
            )
        ),
        "colab_image": str(
            emit_ai_bridge_job(
                provider_id="hunyuan_image_colab",
                pack_id="RA_PACK_MAT_SAMPLE_01",
                game_scope=game_scope,
                output_dir=root_dir / "material" / "generator_hunyuan_image",
            ).output_dir
        ),
    }

    summary["weapon"] = {
        "generator": str(
            emit_generator_setup(
                profile_id="hunyuan3d2.production",
                pack_id="RA_PACK_WPN_COMBAT_SLICE_02",
                game_scope=game_scope,
                output_dir=root_dir / "weapon" / "generator_hunyuan",
            ).output_dir
        )
    }

    summary["prop"] = {
        "generator": str(
            emit_generator_setup(
                profile_id="trellis.secondary",
                pack_id="RA_PACK_PROP_SAMPLE_01",
                game_scope=game_scope,
                output_dir=root_dir / "prop" / "generator_trellis",
            ).output_dir
        )
    }

    summary["character_base"] = {
        "manual_browser": str(
            emit_browser_automation_job(
                source_adapter="mixamo",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id="RA_PACK_CHR_PLAYER_SLICE_03",
                game_scope=game_scope,
                source_url="https://www.mixamo.com/",
                search_terms=("gladiator", "roman", "fighter"),
                login_required=True,
                output_dir=root_dir / "character_base" / "manual_mixamo",
            ).output_dir
        )
    }

    summary["animation"] = {
        "manual_browser": str(
            emit_browser_automation_job(
                source_adapter="mixamo",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id="RA_PACK_ANM_COMBAT_SLICE_02",
                game_scope=game_scope,
                source_url="https://www.mixamo.com/",
                search_terms=("sword", "shield", "combat"),
                login_required=True,
                output_dir=root_dir / "animation" / "manual_mixamo",
            ).output_dir
        )
    }

    summary["music"] = {
        "direct_url": str(
            _queue_template(
                root_dir / "music",
                pack_id="RA_PACK_AUD_MUSIC_SLICE_02",
                game_scope=game_scope,
                source_adapter="mixkit",
                count=2,
                notes="Example music clips from Mixkit or Pixabay.",
            )
        ),
        "generator": str(
            emit_ai_bridge_job(
                provider_id="musicgen",
                pack_id="RA_PACK_AUD_MUSIC_SLICE_02",
                game_scope=game_scope,
                output_dir=root_dir / "music" / "generator_musicgen",
            ).output_dir
        ),
    }

    summary["sfx"] = {
        "direct_url": str(
            _queue_template(
                root_dir / "sfx",
                pack_id="RA_PACK_AUD_SFX_SLICE_02",
                game_scope=game_scope,
                source_adapter="pixabay_audio",
                count=3,
                notes="Example SFX clips from Pixabay or Freesound.",
            )
        ),
        "manual_browser": str(
            emit_browser_automation_job(
                source_adapter="freesound_browser",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id="RA_PACK_AUD_SFX_SLICE_02",
                game_scope=game_scope,
                source_url="https://freesound.org/",
                search_terms=("sword clash", "shield impact", "crowd cheer"),
                login_required=True,
                output_dir=root_dir / "sfx" / "manual_freesound",
            ).output_dir
        ),
        "generator": str(
            emit_ai_bridge_job(
                provider_id="audioldm2",
                pack_id="RA_PACK_AUD_SFX_SLICE_02",
                game_scope=game_scope,
                output_dir=root_dir / "sfx" / "generator_audioldm2",
            ).output_dir
        ),
    }

    summary["museum_prop"] = {
        "direct_url": str(
            _queue_template(
                root_dir / "museum_prop",
                pack_id="RA_PACK_PROP_MUSEUM_HISTORIC_EXP_01",
                game_scope=game_scope,
                source_adapter="direct_url_queue",
                count=2,
                notes="Example open-access museum assets (Smithsonian, Met).",
            )
        )
    }

    summary["architecture"] = {
        "engine_bridge": str(
            emit_engine_export_job(
                engine="unity",
                pack_id="RA_PACK_ENV_ARCH_SAMPLE_01",
                game_scope=game_scope,
                source_url="https://example.com",
                license_note="licensed package",
                source_package_name="ExampleArchitecturePack",
                asset_kind="architecture",
                output_dir=root_dir / "architecture" / "engine_bridge_unity",
            ).output_dir
        )
    }

    summary_path = write_json(root_dir / "category_examples_summary.json", summary)
    return CategoryExamples(output_dir=root_dir, summary_path=summary_path)
