from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy.library.files import read_json, write_json, write_text
from assetboy.library.paths import colab_profiles_dir, generated_output_root, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


def _slug(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


@dataclass(frozen=True)
class PromptJob:
    job_name: str
    asset_class: str
    prompt: str
    negative_prompt: str = ""
    tags: tuple[str, ...] = ()
    notes: str = ""
    seed: int | None = None
    extra_payload: dict[str, object] = field(default_factory=dict)

    def to_batch_job(
        self,
        *,
        game_scope: str,
        pack_id: str,
        provider: str,
        profile_id: str,
        model_name: str,
        lane: str,
        runtime_class: str,
        cleanup_profile: str,
        payload_target_path: str,
        export_targets: tuple[str, ...],
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "model": model_name,
            "profile_id": profile_id,
            "pack_id": pack_id,
            "game_scope": game_scope,
            "payload_target_path": payload_target_path,
            "cleanup_profile": cleanup_profile,
            "export_targets": list(export_targets),
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        payload.update(self.extra_payload)
        return {
            "job_name": self.job_name,
            "recipe": game_scope,
            "lane": lane,
            "asset_class": self.asset_class,
            "provider": provider,
            "priority": "critical",
            "runtime_class": runtime_class,
            "tags": list(self.tags),
            "payload": payload,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ColabProfile:
    profile_id: str
    adapter_id: str
    display_name: str
    model_name: str
    lane: str
    asset_kind: str
    runtime_class: str
    cleanup_profile: str
    export_targets: tuple[str, ...]
    prompt_guidance: tuple[str, ...]
    provenance_notes: tuple[str, ...]
    review_checklist: tuple[str, ...]
    runbook: tuple[str, ...]
    official_url: str = ""
    access_surface: str = ""
    setup_steps: tuple[str, ...] = ()
    progression_steps: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ColabProfile:
        return cls(
            profile_id=str(payload["profile_id"]),
            adapter_id=str(payload["adapter_id"]),
            display_name=str(payload["display_name"]),
            model_name=str(payload["model_name"]),
            lane=str(payload["lane"]),
            asset_kind=str(payload["asset_kind"]),
            runtime_class=str(payload.get("runtime_class", "long")),
            cleanup_profile=str(payload["cleanup_profile"]),
            export_targets=tuple(str(item) for item in payload.get("export_targets", ["glb", "fbx"])),
            prompt_guidance=tuple(str(item) for item in payload.get("prompt_guidance", [])),
            provenance_notes=tuple(str(item) for item in payload.get("provenance_notes", [])),
            review_checklist=tuple(str(item) for item in payload.get("review_checklist", [])),
            runbook=tuple(str(item) for item in payload.get("runbook", [])),
            official_url=str(payload.get("official_url", "")),
            access_surface=str(payload.get("access_surface", "")),
            setup_steps=tuple(str(item) for item in payload.get("setup_steps", [])),
            progression_steps=tuple(str(item) for item in payload.get("progression_steps", [])),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "adapter_id": self.adapter_id,
            "display_name": self.display_name,
            "model_name": self.model_name,
            "lane": self.lane,
            "asset_kind": self.asset_kind,
            "runtime_class": self.runtime_class,
            "cleanup_profile": self.cleanup_profile,
            "export_targets": list(self.export_targets),
            "prompt_guidance": list(self.prompt_guidance),
            "provenance_notes": list(self.provenance_notes),
            "review_checklist": list(self.review_checklist),
            "runbook": list(self.runbook),
            "official_url": self.official_url,
            "access_surface": self.access_surface,
            "setup_steps": list(self.setup_steps),
            "progression_steps": list(self.progression_steps),
        }


@dataclass(frozen=True)
class GeneratorBatchArtifacts:
    output_dir: Path
    prompt_batch_path: Path
    provenance_template_path: Path
    payload_target_path_file: Path
    review_checklist_path: Path
    cleanup_plan_path: Path
    payload_target_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "prompt_batch_path": str(self.prompt_batch_path),
            "provenance_template_path": str(self.provenance_template_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "review_checklist_path": str(self.review_checklist_path),
            "cleanup_plan_path": str(self.cleanup_plan_path),
            "payload_target_path": str(self.payload_target_path),
        }


def profile_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            path.stem
            for path in colab_profiles_dir().glob("*.json")
            if not path.stem.endswith(".example")
        )
    )


def load_colab_profile(profile_id: str) -> ColabProfile:
    return ColabProfile.from_dict(read_json(colab_profiles_dir() / f"{profile_id}.json"))


def default_prompt_jobs(profile_id: str, *, pack_id: str) -> tuple[PromptJob, ...]:
    if profile_id == "hunyuan3d2.production":
        return (
            PromptJob(
                job_name="roman_gladius_primary",
                asset_class="weapon_mesh",
                prompt="Roman gladius short sword, practical iron blade, wrapped grip, game-ready prop silhouette",
                negative_prompt="sci-fi, gun, firearm, fantasy runes, exaggerated ornaments",
                tags=("roman", "weapon", "gladius"),
                notes=f"Primary blocker candidate for {pack_id}.",
                seed=4101,
            ),
            PromptJob(
                job_name="roman_gladius_alt",
                asset_class="weapon_mesh",
                prompt="Roman legionary gladius with plain scabbard, grounded historical materials, believable proportions",
                negative_prompt="anime, oversized blade, glowing trim, futuristic details",
                tags=("roman", "weapon", "gladius"),
                notes="Alternate silhouette for review if the first pass feels toy-like.",
                seed=4102,
            ),
            PromptJob(
                job_name="roman_training_shield",
                asset_class="weapon_mesh",
                prompt="Roman scutum training shield prop, worn wood and metal rim, production-ready hard surface",
                negative_prompt="sci-fi panels, modern logos, stylized toon shading",
                tags=("roman", "weapon", "shield"),
                notes="Optional fallback if the combat slice needs shield coverage in the same pack.",
                seed=4103,
            ),
        )
    if profile_id == "trellis.secondary":
        return (
            PromptJob(
                job_name="roman_gladius_trellis_retry",
                asset_class="weapon_mesh",
                prompt="Roman gladius reconstructed from reference-style silhouette, practical guard and blade length",
                negative_prompt="futuristic, gun, ornate fantasy embellishments",
                tags=("roman", "weapon", "trellis"),
                notes=f"Secondary generator retry for {pack_id}.",
            ),
        )
    if profile_id == "animationgpt.pilot":
        return (
            PromptJob(
                job_name="combat_gap_slash_attack",
                asset_class="combat_animation_clip",
                prompt="Roman short-sword slash attack clip, grounded stance, one-handed, gameplay-ready telegraph",
                tags=("roman", "combat", "attack"),
                notes=f"Pilot clip batch for {pack_id}.",
                seed=7201,
                extra_payload={"clip_length_sec": 1.4},
            ),
            PromptJob(
                job_name="combat_gap_hit_react",
                asset_class="combat_animation_clip",
                prompt="Roman melee hit-react animation, torso recoil, recover back to guard stance",
                tags=("roman", "combat", "hit_react"),
                seed=7202,
                extra_payload={"clip_length_sec": 1.1},
            ),
            PromptJob(
                job_name="combat_gap_idle_guard",
                asset_class="combat_animation_clip",
                prompt="Roman sword-and-shield idle combat guard loop, ready stance, subtle weight shift",
                tags=("roman", "combat", "idle"),
                seed=7203,
                extra_payload={"clip_length_sec": 2.0, "loop": True},
            ),
        )
    raise KeyError(f"Unknown profile: {profile_id}")


def emit_generator_setup(
    *,
    profile_id: str,
    pack_id: str,
    game_scope: str,
    prompt_jobs: tuple[PromptJob, ...] | None = None,
    output_dir: str | Path | None = None,
    animated: bool = False,
) -> GeneratorBatchArtifacts:
    profile = load_colab_profile(profile_id)
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    cleanup_plan = build_cleanup_plan(
        pack_id=pack_id,
        asset_kind=profile.asset_kind,
        source_lane=ProviderLane.GENERATOR.value,
        animated=animated,
    )
    jobs = prompt_jobs or default_prompt_jobs(profile_id, pack_id=pack_id)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / _slug(profile_id) / _slug(pack_id)
    )
    prompt_batch = {
        "schema_version": "assetboy.colab_batch.v1",
        "batch_id": f"{game_scope}_{_slug(pack_id)}_{_slug(profile_id)}",
        "profile": profile.to_dict(),
        "game_scope": game_scope,
        "pack_id": pack_id,
        "payload_target_path": str(payload_target),
        "jobs": [
            job.to_batch_job(
                game_scope=game_scope,
                pack_id=pack_id,
                provider=profile.adapter_id,
                profile_id=profile.profile_id,
                model_name=profile.model_name,
                lane=profile.lane,
                runtime_class=profile.runtime_class,
                cleanup_profile=profile.cleanup_profile,
                payload_target_path=str(payload_target),
                export_targets=cleanup_plan.export_decision.export_targets or profile.export_targets,
            )
            for job in jobs
        ],
    }
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.GENERATOR,
        source_adapter=profile.adapter_id,
        payload_target_path=str(payload_target),
        notes=profile.provenance_notes,
    )
    provenance["values"]["model_name"] = profile.model_name
    provenance["values"]["profile_id"] = profile.profile_id
    provenance["values"]["cleanup_profile"] = profile.cleanup_profile

    review_lines = [
        f"# {profile.display_name} Review Checklist",
        "",
        f"- Pack: `{pack_id}`",
        f"- Game scope: `{game_scope}`",
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
    review_lines.extend(["", "## Prompt Guidance"])
    review_lines.extend(f"- {line}" for line in profile.prompt_guidance)
    review_lines.extend(["", "## Review Checklist"])
    review_lines.extend(f"- {line}" for line in profile.review_checklist)
    review_lines.extend(["", "## Runbook"])
    review_lines.extend(f"- {line}" for line in profile.runbook)

    prompt_batch_path = write_json(root_dir / "prompt_batch.json", prompt_batch)
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    review_checklist_path = write_text(root_dir / "review_checklist.md", "\n".join(review_lines) + "\n")
    cleanup_plan_path = write_json(root_dir / "cleanup_plan.json", cleanup_plan.to_dict())

    return GeneratorBatchArtifacts(
        output_dir=root_dir,
        prompt_batch_path=prompt_batch_path,
        provenance_template_path=provenance_template_path,
        payload_target_path_file=payload_target_path_file,
        review_checklist_path=review_checklist_path,
        cleanup_plan_path=cleanup_plan_path,
        payload_target_path=payload_target,
    )
