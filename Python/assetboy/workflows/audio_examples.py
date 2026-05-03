from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import write_json
from assetboy.library.paths import generated_output_root
from assetboy.providers.ai_bridge import emit_ai_bridge_job
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.direct_url import build_queue_template_rows, write_queue_rows


@dataclass(frozen=True)
class AudioPipelineExamples:
    output_dir: Path
    direct_url_queue_template: Path
    manual_browser_job_dir: Path
    musicgen_job_dir: Path
    audioldm2_job_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "direct_url_queue_template": str(self.direct_url_queue_template),
            "manual_browser_job_dir": str(self.manual_browser_job_dir),
            "musicgen_job_dir": str(self.musicgen_job_dir),
            "audioldm2_job_dir": str(self.audioldm2_job_dir),
        }


def emit_audio_pipeline_examples(
    *,
    game_scope: str = "roman_arena",
    output_dir: str | Path | None = None,
) -> AudioPipelineExamples:
    root_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "audio_pipeline_examples"
    root_dir.mkdir(parents=True, exist_ok=True)

    queue_rows = []
    queue_rows.extend(
        build_queue_template_rows(
            pack_id="RA_PACK_AUD_MUSIC_SLICE_02",
            game_scope=game_scope,
            request_count=2,
            source_adapter="mixkit",
            notes="Example music clips from Mixkit or Pixabay.",
        )
    )
    queue_rows.extend(
        build_queue_template_rows(
            pack_id="RA_PACK_AUD_SFX_SLICE_02",
            game_scope=game_scope,
            request_count=3,
            source_adapter="pixabay_audio",
            notes="Example SFX clips from Pixabay or Freesound.",
        )
    )
    queue_template_path = write_queue_rows(queue_rows, path=root_dir / "direct_url_queue_template.csv")

    manual_job = emit_browser_automation_job(
        source_adapter="freesound_browser",
        runtime=BrowserRuntime.PLAYWRIGHT_MCP,
        pack_id="RA_PACK_AUD_SFX_SLICE_02",
        game_scope=game_scope,
        source_url="https://freesound.org/",
        search_terms=("sword clash", "arena crowd", "shield impact"),
        login_required=True,
        output_dir=root_dir / "manual_browser_freesound",
    )

    musicgen_job = emit_ai_bridge_job(
        provider_id="musicgen",
        pack_id="RA_PACK_AUD_MUSIC_SLICE_02",
        game_scope=game_scope,
        output_dir=root_dir / "generator_musicgen",
    )

    audioldm2_job = emit_ai_bridge_job(
        provider_id="audioldm2",
        pack_id="RA_PACK_AUD_SFX_SLICE_02",
        game_scope=game_scope,
        output_dir=root_dir / "generator_audioldm2",
    )

    summary_path = root_dir / "audio_examples_summary.json"
    write_json(
        summary_path,
        {
            "direct_url_queue_template": str(queue_template_path),
            "manual_browser_job_dir": str(manual_job.output_dir),
            "musicgen_job_dir": str(musicgen_job.output_dir),
            "audioldm2_job_dir": str(audioldm2_job.output_dir),
        },
    )

    return AudioPipelineExamples(
        output_dir=root_dir,
        direct_url_queue_template=queue_template_path,
        manual_browser_job_dir=manual_job.output_dir,
        musicgen_job_dir=musicgen_job.output_dir,
        audioldm2_job_dir=audioldm2_job.output_dir,
    )
