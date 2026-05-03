from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from assetboy.providers.lanes import ProviderLane


@dataclass(frozen=True)
class UnresolvedSlot:
    slot: str
    required_tag: str
    preferred_type: str
    required_count: int
    matched_count: int
    remediation: str
    lane: ProviderLane
    name_hints: tuple[str, ...]


@dataclass(frozen=True)
class GateReport:
    path: Path
    recipe: str
    pass_state: bool
    gate_reasons: tuple[str, ...]
    unresolved_slots: tuple[UnresolvedSlot, ...]


def _suggest_lane(required_tag: str, preferred_type: str, slot: str) -> ProviderLane:
    lowered_tag = required_tag.lower()
    lowered_type = preferred_type.lower()
    lowered_slot = slot.lower()

    if "ui" in lowered_tag or "music" in lowered_tag or "sfx" in lowered_tag:
        return ProviderLane.DIRECT_URL

    if "weapon" in lowered_tag or "weapon" in lowered_slot:
        return ProviderLane.GENERATOR

    if lowered_type in {"mesh", "character"} and ("player" in lowered_slot or "player" in lowered_tag):
        return ProviderLane.MANUAL_BROWSER

    return ProviderLane.MANUAL_BROWSER


def load_gate_report(path: str | Path) -> GateReport:
    gate_path = Path(path).resolve()
    data = json.loads(gate_path.read_text(encoding="utf-8-sig"))
    dashboard = data.get("dashboard", {}) or data.get("gate", {}).get("dashboard", {})
    gate_reasons = tuple(data.get("gate_reasons", []) or data.get("gate", {}).get("gate_reasons", []))
    pass_state = bool(data.get("pass", data.get("gate_pass", data.get("gate", {}).get("pass", False))))

    unresolved = []
    for item in dashboard.get("top_blockers", {}).get("manifest_unresolved", []):
        unresolved.append(
            UnresolvedSlot(
                slot=item["slot"],
                required_tag=item["required_tag"],
                preferred_type=item["preferred_type"],
                required_count=int(item["required_count"]),
                matched_count=int(item["matched_count"]),
                remediation=item["remediation"],
                lane=_suggest_lane(item["required_tag"], item["preferred_type"], item["slot"]),
                name_hints=tuple(str(value) for value in item.get("name_hints", [])),
            )
        )

    return GateReport(
        path=gate_path,
        recipe=data.get("recipe", ""),
        pass_state=pass_state,
        gate_reasons=gate_reasons,
        unresolved_slots=tuple(unresolved),
    )


def format_gate_summary(report: GateReport) -> str:
    lines = [
        f"gate_path={report.path}",
        f"recipe={report.recipe}",
        f"pass={str(report.pass_state).lower()}",
        f"gate_reasons={len(report.gate_reasons)}",
        f"unresolved_slots={len(report.unresolved_slots)}",
    ]

    for slot in report.unresolved_slots:
        lines.append(
            " - "
            f"{slot.slot}: tag={slot.required_tag} type={slot.preferred_type} "
            f"count={slot.required_count} lane={slot.lane.value}"
        )

    return "\n".join(lines)
