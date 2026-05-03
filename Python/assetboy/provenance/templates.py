from __future__ import annotations

from assetboy.provenance.schema import (
    FIELD_GUIDANCE,
    build_template_values,
    provenance_requirements_for,
)


def build_provenance_template(
    *,
    pack_id: str,
    game_scope: str,
    lane: ProviderLane | str,
    source_adapter: str,
    payload_target_path: str,
    notes: tuple[str, ...] = (),
) -> dict[str, object]:
    required_fields = provenance_requirements_for(lane, source_adapter=source_adapter)
    lane_value = getattr(lane, "value", lane)
    lane_value = str(lane_value)
    return {
        "template_version": "assetboy.provenance.v2",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "lane": lane_value,
        "source_adapter": source_adapter,
        "payload_target_path": payload_target_path,
        "required_fields": [
            {"id": field_id, "guidance": FIELD_GUIDANCE.get(field_id, "")}
            for field_id in required_fields
        ],
        "values": build_template_values(
            lane=lane,
            source_adapter=source_adapter,
            payload_target_path=payload_target_path,
            required_fields=required_fields,
        ),
        "notes": list(notes),
    }
