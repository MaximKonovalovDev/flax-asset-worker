from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AUTH_STATE_STALE_AFTER_HOURS = 72.0


def _parse_iso_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state_saved_at(
    auth_state_path: Path,
    auth_state: dict[str, Any] | None,
) -> tuple[datetime | None, str]:
    payload = auth_state if isinstance(auth_state, dict) else {}
    for key in ("saved_at", "saved_at_utc"):
        parsed = _parse_iso_utc(payload.get(key))
        if parsed is not None:
            return parsed, "payload"
    if auth_state_path.exists():
        return datetime.fromtimestamp(auth_state_path.stat().st_mtime, tz=timezone.utc), "file_mtime"
    return None, "missing"


def describe_auth_state_freshness(
    *,
    auth_state_path: Path,
    auth_state: dict[str, Any] | None,
    stale_after_hours: float = DEFAULT_AUTH_STATE_STALE_AFTER_HOURS,
) -> dict[str, object]:
    saved_at, saved_at_source = _state_saved_at(auth_state_path, auth_state)
    payload: dict[str, object] = {
        "saved_at": "",
        "saved_at_source": saved_at_source,
        "auth_state_age_seconds": 0,
        "auth_state_age_hours": 0.0,
        "auth_state_stale_after_hours": float(stale_after_hours),
        "auth_state_stale": False,
    }
    if saved_at is None:
        return payload

    age_seconds = max((datetime.now(timezone.utc) - saved_at).total_seconds(), 0.0)
    payload["saved_at"] = saved_at.isoformat()
    payload["auth_state_age_seconds"] = int(age_seconds)
    payload["auth_state_age_hours"] = round(age_seconds / 3600.0, 3)
    payload["auth_state_stale"] = bool(age_seconds >= float(stale_after_hours) * 3600.0)
    return payload
