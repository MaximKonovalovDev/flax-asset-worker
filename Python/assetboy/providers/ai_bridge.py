from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.bridge_registry import AssetCategory
from assetboy.providers.lanes import ProviderLane


@dataclass(frozen=True)
class AIProviderProfile:
    provider_id: str
    display_name: str
    asset_categories: tuple[AssetCategory, ...]
    output_formats: tuple[str, ...]
    runtime_kind: str
    checklist: tuple[str, ...]
    official_url: str = ""
    access_surface: str = ""
    setup_steps: tuple[str, ...] = ()
    progression_steps: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "asset_categories": [category.value for category in self.asset_categories],
            "output_formats": list(self.output_formats),
            "runtime_kind": self.runtime_kind,
            "checklist": list(self.checklist),
            "official_url": self.official_url,
            "access_surface": self.access_surface,
            "setup_steps": list(self.setup_steps),
            "progression_steps": list(self.progression_steps),
            "notes": list(self.notes),
        }


AI_PROVIDER_PROFILES: dict[str, AIProviderProfile] = {
    "chatgpt_pro": AIProviderProfile(
        provider_id="chatgpt_pro",
        display_name="ChatGPT Pro",
        asset_categories=(AssetCategory.UI_HUD, AssetCategory.MATERIAL),
        output_formats=("png",),
        runtime_kind="cloud",
        official_url="https://help.openai.com/en/articles/11128753",
        access_surface="ChatGPT image workflow",
        checklist=(
            "Use ChatGPT Pro to iterate prompts or image outputs for UI and support textures.",
            "Keep the chosen prompt chain in provenance notes.",
        ),
        setup_steps=(
            "Use a ChatGPT Pro workspace where image generation is enabled and keep runs in one thread per pack.",
            "Start with one HUD element prompt at a time, then iterate through image edits instead of regenerating from scratch.",
            "Export approved images to PNG and keep the prompt chain for provenance.",
        ),
        progression_steps=(
            "First pass: establish shape readability at gameplay scale.",
            "Second pass: lock line weight, contrast, and alpha edges for in-engine HUD readability.",
            "Final pass: only minor polish and naming before payload handoff.",
        ),
    ),
    "google_pro": AIProviderProfile(
        provider_id="google_pro",
        display_name="Google Pro",
        asset_categories=(AssetCategory.UI_HUD, AssetCategory.MATERIAL),
        output_formats=("png",),
        runtime_kind="cloud",
        official_url="https://ai.google.dev/gemini-api/docs/image-generation",
        access_surface="Gemini image workflow",
        checklist=(
            "Use as a secondary cloud AI bridge when ChatGPT Pro is not landing the target look.",
            "Keep the chosen prompt chain and accepted variants in provenance notes.",
        ),
        setup_steps=(
            "Use Gemini image generation in one thread per pack so prompt edits stay traceable.",
            "Start with one readable HUD or texture-support element at a time.",
            "Export approved images to PNG and keep the prompt chain for provenance.",
        ),
        progression_steps=(
            "Use this after ChatGPT Pro misses composition, material treatment, or cleanup quality.",
            "Move accepted outputs into ComfyUI only for alpha cleanup, upscale, or remix work.",
        ),
    ),
    "hunyuan_image_colab": AIProviderProfile(
        provider_id="hunyuan_image_colab",
        display_name="HunyuanImage-3.0 Colab",
        asset_categories=(AssetCategory.UI_HUD, AssetCategory.MATERIAL),
        output_formats=("png",),
        runtime_kind="colab",
        official_url="https://github.com/Tencent-Hunyuan/HunyuanImage-3.0",
        access_surface="Google Colab or local Linux notebook running HunyuanImage-3.0",
        checklist=(
            "Generate 2-4 clean variants and reject noisy outputs early.",
            "Preserve prompt and seed/session notes for provenance.",
            "Stage accepted PNG outputs into the reviewed payload target.",
        ),
        setup_steps=(
            "Clone the official HunyuanImage repository and follow its setup instructions.",
            "Keep batch size and resolution modest when running on T4-class GPUs.",
            "Save accepted outputs as PNG and keep the prompt chain for provenance.",
        ),
        progression_steps=(
            "Use this lane for clean reference images when cloud UI generators miss the target style.",
            "Prefer single-subject prompts with clear material and lighting intent.",
            "When needed, generate 3-4 consistent angles for 3D pre-pass reference.",
        ),
        notes=(
            "Use for reference imagery or UI concepts; pass approved references into multi-view pipelines before 3D generation.",
        ),
    ),
    "comfyui_local": AIProviderProfile(
        provider_id="comfyui_local",
        display_name="ComfyUI Local",
        asset_categories=(AssetCategory.UI_HUD, AssetCategory.MATERIAL),
        output_formats=("png", "tga"),
        runtime_kind="local_rtx3050",
        access_surface="Local RTX3050 ComfyUI workflows",
        checklist=(
            "Use local workflows for remix, inpaint, upscale, and texture variation.",
            "Preserve workflow or checkpoint notes in provenance.",
        ),
    ),
    "musicgen": AIProviderProfile(
        provider_id="musicgen",
        display_name="MusicGen",
        asset_categories=(AssetCategory.MUSIC,),
        output_formats=("wav", "mp3", "ogg"),
        runtime_kind="local_or_colab",
        official_url="https://github.com/facebookresearch/audiocraft",
        access_surface="Local or Colab via AudioCraft MusicGen",
        checklist=(
            "Export at least one clean loopable cut and one longer variation.",
            "Capture prompt, duration, seed, and model version in provenance.",
            "Check for clipping and normalize to safe game levels before publish.",
        ),
        setup_steps=(
            "Use the AudioCraft repo (MusicGen) for text-to-music generation.",
            "Start with 20-40s clips and render a loopable segment for gameplay.",
        ),
        progression_steps=(
            "Lock tempo and instrumentation early (e.g., 90-120 BPM, no vocals).",
            "Render multiple seeds, then pick the most stable loop.",
        ),
    ),
    "audioldm2": AIProviderProfile(
        provider_id="audioldm2",
        display_name="AudioLDM2",
        asset_categories=(AssetCategory.SFX, AssetCategory.MUSIC),
        output_formats=("wav",),
        runtime_kind="local_or_colab",
        official_url="https://github.com/haoheliu/AudioLDM2",
        access_surface="Local or Colab via AudioLDM2",
        checklist=(
            "Render 2-3 variations per SFX and keep the cleanest transient.",
            "Capture prompt, duration, seed, and model version in provenance.",
            "Trim silence and normalize levels before publish.",
        ),
        setup_steps=(
            "Use AudioLDM2 for text-to-audio SFX or ambience generation.",
            "Prefer short 2-6s prompts for SFX and 10-20s for ambience beds.",
        ),
        progression_steps=(
            "Start with dry, single-source prompts; add environment later if needed.",
            "Reject noisy or watery artifacts early and re-seed.",
        ),
    ),
}


@dataclass(frozen=True)
class AIPromptJob:
    job_name: str
    asset_category: AssetCategory
    prompt: str
    negative_prompt: str = ""
    style_notes: tuple[str, ...] = ()
    seed: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "job_name": self.job_name,
            "asset_category": self.asset_category.value,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "style_notes": list(self.style_notes),
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        return payload


@dataclass(frozen=True)
class AIBridgeArtifacts:
    output_dir: Path
    job_spec_path: Path
    provenance_template_path: Path
    review_checklist_path: Path
    payload_target_path_file: Path
    payload_target_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "provenance_template_path": str(self.provenance_template_path),
            "review_checklist_path": str(self.review_checklist_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "payload_target_path": str(self.payload_target_path),
        }


def default_ai_prompt_jobs(provider_id: str, *, pack_id: str) -> tuple[AIPromptJob, ...]:
    if provider_id == "chatgpt_pro":
        return (
            AIPromptJob(
                job_name="roman_crosshair_grounded",
                asset_category=AssetCategory.UI_HUD,
                prompt="Grounded realistic combat-game crosshair for a Roman arena HUD, thin iron ring with subtle bronze tick marks, restrained wear, transparent background, centered, readable at small size, no glow",
                negative_prompt="blurry, text, watermark, fantasy magic, neon hologram, oversized ornament, mobile game ui, sci-fi reticle, background scene",
                style_notes=("grounded", "minimal", "readable", "combat hud"),
                seed=5101,
            ),
            AIPromptJob(
                job_name="roman_damage_vignette_grounded",
                asset_category=AssetCategory.UI_HUD,
                prompt="Grounded realistic damage vignette for a Roman arena combat HUD, peripheral dust, sweat, and subtle blood smear at the screen edges, transparent center, transparent background, readable in motion, restrained intensity",
                negative_prompt="heavy gore, full-screen blood, text, watermark, muddy center, horror poster, fantasy smoke, low contrast",
                style_notes=("grounded", "overlay", "transparent background", "gameplay"),
                seed=5102,
            ),
            AIPromptJob(
                job_name="roman_hit_confirm_marker_grounded",
                asset_category=AssetCategory.UI_HUD,
                prompt="Grounded realistic hit-confirm marker for a Roman melee combat HUD, subtle iron and bronze impact cue, minimal four-point marker, transparent background, crisp and readable, no glow bloom",
                negative_prompt="text, watermark, cartoon burst, fantasy rune, neon, blood splatter, sticker style, busy background",
                style_notes=("grounded", "minimal", "combat feedback"),
                seed=5103,
            ),
        )
    if provider_id == "google_pro":
        return (
            AIPromptJob(
                job_name="roman_crosshair_grounded",
                asset_category=AssetCategory.UI_HUD,
                prompt="Grounded realistic Roman arena combat crosshair, thin forged-iron center mark with restrained bronze accents, transparent background, crisp silhouette, readable at gameplay scale, no bloom",
                negative_prompt="blurry, text, watermark, glow bloom, clutter, fantasy sigil, mobile game ui, sci-fi hologram, background scene",
                style_notes=("grounded", "minimal", "readable", "combat hud"),
                seed=5201,
            ),
            AIPromptJob(
                job_name="roman_damage_vignette_grounded",
                asset_category=AssetCategory.UI_HUD,
                prompt="Grounded realistic Roman combat damage vignette overlay, edge dust and light blood smear only, transparent center, transparent background, readable in motion, restrained and gritty",
                negative_prompt="heavy gore, text, watermark, muddy center, low contrast, horror splash, fantasy smoke, full-screen red wash",
                style_notes=("grounded", "overlay", "transparent background", "gameplay"),
                seed=5202,
            ),
            AIPromptJob(
                job_name="roman_hit_confirm_marker_grounded",
                asset_category=AssetCategory.UI_HUD,
                prompt="Grounded realistic hit-confirm marker for a Roman arena HUD, minimal iron and bronze impact cue, transparent background, sharp clean shape, restrained intensity, no bloom",
                negative_prompt="text, watermark, cartoon burst, fantasy rune, neon, sticker style, blood splatter, clutter",
                style_notes=("grounded", "minimal", "combat feedback"),
                seed=5203,
            ),
        )
    if provider_id == "musicgen":
        return (
            AIPromptJob(
                job_name="roman_arena_combat_theme",
                asset_category=AssetCategory.MUSIC,
                prompt="Roman arena combat theme, tense drums, low strings, sparse brass, no vocals, loopable",
                negative_prompt="vocals, choir, modern synth, EDM",
                style_notes=("120bpm", "30s loop", "gameplay bed"),
                seed=4201,
            ),
            AIPromptJob(
                job_name="roman_menu_ambient",
                asset_category=AssetCategory.MUSIC,
                prompt="Roman ambient menu music, warm strings, light percussion, calm but heroic, no vocals",
                negative_prompt="vocals, heavy drums",
                style_notes=("90bpm", "40s ambient"),
                seed=4202,
            ),
        )
    if provider_id == "audioldm2":
        return (
            AIPromptJob(
                job_name="sfx_sword_clash",
                asset_category=AssetCategory.SFX,
                prompt="single sword clash, dry, short metallic impact",
                negative_prompt="reverb tail, crowd, music",
                style_notes=("2s", "dry"),
                seed=5101,
            ),
            AIPromptJob(
                job_name="sfx_arena_crowd_burst",
                asset_category=AssetCategory.SFX,
                prompt="short arena crowd cheer burst, distant, energetic",
                negative_prompt="music, chanting lyrics",
                style_notes=("4s", "stereo"),
                seed=5102,
            ),
        )
    if provider_id == "hunyuan_image_colab":
        return (
            AIPromptJob(
                job_name="roman_ui_crosshair_reference",
                asset_category=AssetCategory.UI_HUD,
                prompt="Roman arena FPS crosshair, clean center mark, subtle bronze accents, transparent background",
                negative_prompt="text, watermark, blurry, heavy glow",
                style_notes=("clean", "readable", "transparent"),
                seed=6101,
            ),
            AIPromptJob(
                job_name="roman_sandstone_material_reference",
                asset_category=AssetCategory.MATERIAL,
                prompt="Seamless Roman sandstone wall texture, neutral lighting, high detail, tileable",
                negative_prompt="text, watermark, perspective distortion, harsh shadows",
                style_notes=("tileable", "pbr reference"),
                seed=6102,
            ),
        )
    return (
        AIPromptJob(
            job_name=f"{pack_id.lower()}_primary",
            asset_category=AssetCategory.UI_HUD,
            prompt="Game-ready UI asset for the requested pack.",
        ),
    )


def emit_ai_bridge_job(
    *,
    provider_id: str,
    pack_id: str,
    game_scope: str,
    prompt_jobs: tuple[AIPromptJob, ...] | None = None,
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
) -> AIBridgeArtifacts:
    profile = AI_PROVIDER_PROFILES[provider_id]
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    jobs = prompt_jobs or default_ai_prompt_jobs(provider_id, pack_id=pack_id)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "ai_bridge" / provider_id / pack_id
    )
    spec = {
        "provider": profile.to_dict(),
        "pack_id": pack_id,
        "game_scope": game_scope,
        "payload_target_path": str(payload_target),
        "jobs": [job.to_dict() for job in jobs],
    }
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.GENERATOR,
        source_adapter=provider_id,
        payload_target_path=str(payload_target),
        notes=notes or profile.notes,
    )
    provenance["values"]["model_name"] = profile.display_name
    review_lines = [
        f"# {profile.display_name} Checklist",
        "",
        f"- Pack: `{pack_id}`",
        f"- Game scope: `{game_scope}`",
        f"- Runtime: `{profile.runtime_kind}`",
        f"- Access surface: `{profile.access_surface or '<unspecified>'}`",
        f"- Payload target: `{payload_target}`",
        "",
    ]
    if profile.official_url:
        review_lines.append(f"- Official reference: `{profile.official_url}`")
    if profile.setup_steps:
        review_lines.extend(["", "## Setup"])
        review_lines.extend(f"- {line}" for line in profile.setup_steps)
    if profile.progression_steps:
        review_lines.extend(["", "## Progression"])
        review_lines.extend(f"- {line}" for line in profile.progression_steps)
    review_lines.extend(
        [
            "",
        "## Review",
        ]
    )
    review_lines.extend(f"- {line}" for line in profile.checklist)

    job_spec_path = write_json(root_dir / "ai_bridge_job.json", spec)
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", "\n".join(review_lines) + "\n")
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")

    return AIBridgeArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        provenance_template_path=provenance_template_path,
        review_checklist_path=review_checklist_path,
        payload_target_path_file=payload_target_path_file,
        payload_target_path=payload_target,
    )
