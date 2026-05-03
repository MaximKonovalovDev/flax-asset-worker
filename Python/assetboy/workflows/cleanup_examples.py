from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.cleanup import build_cleanup_plan
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.provenance import build_provenance_template
from assetboy.providers.lanes import ProviderLane


@dataclass(frozen=True)
class CleanupExampleSpec:
    pack_id: str
    asset_kind: str
    lane: ProviderLane
    source_adapter: str
    animated: bool
    needs_blender: bool


@dataclass(frozen=True)
class CleanupExamples:
    output_dir: Path
    summary_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "summary_path": str(self.summary_path),
        }


_EXAMPLE_SPECS: tuple[CleanupExampleSpec, ...] = (
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_UI_01",
        asset_kind="ui",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=False,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_MATERIAL_01",
        asset_kind="material",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=False,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_WEAPON_01",
        asset_kind="weapon",
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter="fab",
        animated=False,
        needs_blender=True,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_PROP_01",
        asset_kind="prop",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=True,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_CHARACTER_01",
        asset_kind="character",
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter="mixamo",
        animated=True,
        needs_blender=True,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_ANIMATION_01",
        asset_kind="animation",
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter="mixamo",
        animated=True,
        needs_blender=True,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_MUSIC_01",
        asset_kind="music",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=False,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_SFX_01",
        asset_kind="sfx",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=False,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_MUSEUM_PROP_01",
        asset_kind="prop",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=True,
    ),
    CleanupExampleSpec(
        pack_id="RA_PACK_EXAMPLE_ARCH_01",
        asset_kind="architecture",
        lane=ProviderLane.DIRECT_URL,
        source_adapter="direct_url",
        animated=False,
        needs_blender=True,
    ),
)


def _render_cleanup_checklist(
    spec: CleanupExampleSpec,
    *,
    plan_steps: tuple[str, ...],
    export_targets: tuple[str, ...],
    source_dir: Path,
    payload_target: Path,
) -> str:
    lines = [
        "# Blender Cleanup Checklist",
        "",
        f"- Pack: `{spec.pack_id}`",
        f"- Asset kind: `{spec.asset_kind}`",
        f"- Lane: `{spec.lane.value}`",
        f"- Source adapter: `{spec.source_adapter}`",
        f"- Animated: `{str(spec.animated).lower()}`",
        f"- Source folder: `{source_dir}`",
        f"- Payload target: `{payload_target}`",
        f"- Export targets: `{', '.join(export_targets)}`",
        "",
        "Steps:",
    ]
    lines.extend(f"- {step}" for step in plan_steps)
    lines.extend(
        [
            "",
            "Notes:",
            "- Import each source file from the pack folder.",
            "- Apply cleanup steps in order; validate origin, scale, and naming.",
            "- Export to the target formats and stage into the payload target.",
        ]
    )
    return "\n".join(lines) + "\n"


def emit_cleanup_examples(*, game_scope: str = "roman_arena", output_dir: str | Path | None = None) -> CleanupExamples:
    root_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "cleanup_examples"
    root_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict[str, str]] = {}
    manual_root = manual_drop_dir()

    for spec in _EXAMPLE_SPECS:
        pack_dir = manual_root / spec.pack_id
        payload_target = publish_payload_dir(game_scope=game_scope, pack_id=spec.pack_id)
        provenance = build_provenance_template(
            pack_id=spec.pack_id,
            game_scope=game_scope,
            lane=spec.lane,
            source_adapter=spec.source_adapter,
            payload_target_path=str(payload_target),
            notes=("example pack for cleanup/provenance flow",),
        )
        provenance_path = write_json(pack_dir / "provenance_template.json", provenance)
        payload_target_path = write_text(pack_dir / "payload_target.txt", str(payload_target) + "\n")

        cleanup_plan_path = ""
        cleanup_checklist_path = ""
        cleanup_note_path = ""

        if spec.needs_blender:
            plan = build_cleanup_plan(
                pack_id=spec.pack_id,
                asset_kind=spec.asset_kind,
                source_lane=spec.lane.value,
                animated=spec.animated,
            )
            cleanup_plan_path = str(write_json(pack_dir / "cleanup_plan.json", plan.to_dict()))
            cleanup_checklist_path = str(
                write_text(
                    pack_dir / "cleanup_checklist.md",
                    _render_cleanup_checklist(
                        spec,
                        plan_steps=plan.steps,
                        export_targets=plan.export_decision.export_targets,
                        source_dir=pack_dir,
                        payload_target=payload_target,
                    ),
                )
            )
        else:
            cleanup_note_path = str(
                write_text(
                    pack_dir / "cleanup_note.txt",
                    "\n".join(
                        [
                            "No Blender cleanup required for this pack.",
                            f"Payload target: {payload_target}",
                            "If 3D assets are added later, apply standard cleanup steps before publish.",
                            "",
                        ]
                    ),
                )
            )

        summary[spec.pack_id] = {
            "pack_dir": str(pack_dir),
            "provenance_template": str(provenance_path),
            "payload_target_file": str(payload_target_path),
            "cleanup_plan": cleanup_plan_path,
            "cleanup_checklist": cleanup_checklist_path,
            "cleanup_note": cleanup_note_path,
        }

    summary_path = write_json(root_dir / "cleanup_examples_summary.json", summary)
    return CleanupExamples(output_dir=root_dir, summary_path=summary_path)
