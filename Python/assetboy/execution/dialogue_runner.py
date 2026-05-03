from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from assetboy.library.paths import generated_output_root, project_root
from assetboy.provenance.schema import canonicalize_provenance_payload, validate_provenance_payload


# ---------------------------------------------------------------------------
# Dialogue preset lines — Roman Arena NPC voices
# Format: (line_id, text, voice_type, tags)
# ---------------------------------------------------------------------------
DIALOGUE_PRESETS: list[tuple[str, str, str, list[str]]] = [
    # ── Announcer ────────────────────────────────────────────────────────────
    (
        "DIA_ANN_WELCOME",
        "Citizens of Rome! Welcome to the grand arena! Tonight, blood will be spilled!",
        "announcer",
        ["announcer", "roman", "intro"],
    ),
    ("DIA_ANN_FIGHT", "Let the fight begin!", "announcer", ["announcer", "roman", "begin"]),
    (
        "DIA_ANN_VICTORY",
        "The crowd has spoken! A magnificent victory for the champion!",
        "announcer",
        ["announcer", "roman", "victory"],
    ),
    (
        "DIA_ANN_DEFEAT",
        "He falls! The arena claims another soul!",
        "announcer",
        ["announcer", "roman", "defeat"],
    ),
    ("DIA_ANN_ROUND_START", "Round two! Show no mercy!", "announcer", ["announcer", "roman", "round"]),
    # ── Gladiator / Hero ─────────────────────────────────────────────────────
    (
        "DIA_GLB_TAUNT_1",
        "Is that all you have? I have fought beasts stronger than you!",
        "hero",
        ["gladiator", "roman", "taunt"],
    ),
    ("DIA_GLB_PAIN", "Argh! You will pay for that!", "hero", ["gladiator", "roman", "hit"]),
    ("DIA_GLB_VICTORY", "For Rome! For glory!", "hero", ["gladiator", "roman", "victory"]),
    ("DIA_GLB_LOW_HEALTH", "Not yet... I still breathe...", "hero", ["gladiator", "roman", "low_health"]),
    # ── Guard / Captain ──────────────────────────────────────────────────────
    (
        "DIA_GRD_HALT",
        "Halt! No one passes without a permit from the Legate.",
        "male_narrator",
        ["guard", "roman", "npc"],
    ),
    ("DIA_GRD_ALERT", "Intruder! Sound the alarm!", "male_narrator", ["guard", "roman", "alert"]),
    # ── Merchant / Vendor ────────────────────────────────────────────────────
    (
        "DIA_MRC_GREET",
        "Finest weapons and armour in all of Rome, my friend. What do you need?",
        "female_narrator",
        ["merchant", "roman", "shop"],
    ),
    (
        "DIA_MRC_SALE",
        "For you? A special price. Don't tell the others.",
        "female_narrator",
        ["merchant", "roman", "shop"],
    ),
    # ── Crowd ────────────────────────────────────────────────────────────────
    ("DIA_CRD_CHEER", "Kill him! Kill him! Kill him!", "announcer", ["crowd", "roman", "ambience"]),
]

SUPPORTED_PROVIDERS: tuple[str, ...] = ("edge_tts", "elevenlabs")
DEFAULT_PROVIDER = "edge_tts"
DEFAULT_AUDIO_CLASS = "voice_npc"
DEFAULT_ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_ELEVENLABS_TIMEOUT_SEC = 60.0
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

# Voice type → provider-specific voice id
EDGE_TTS_VOICE_MAP: dict[str, str] = {
    "announcer": "en-US-GuyNeural",
    "hero": "en-US-ChristopherNeural",
    "male_narrator": "en-GB-RyanNeural",
    "female_narrator": "en-GB-SoniaNeural",
}

ELEVENLABS_VOICE_MAP: dict[str, str] = {
    "announcer": "ErXwobaYiN019PkySvjV",  # Antoni
    "hero": "TxGEqnHWrfWFTfGW9XjX",  # Josh
    "male_narrator": "pNInz6obpgDQGcFmaJgB",  # Adam
    "female_narrator": "EXAVITQu4vr4xnSDxMaL",  # Bella
}

ELEVENLABS_VOICE_ENV_MAP: dict[str, str] = {
    "announcer": "ELEVENLABS_VOICE_ID_ANNOUNCER",
    "hero": "ELEVENLABS_VOICE_ID_HERO",
    "male_narrator": "ELEVENLABS_VOICE_ID_MALE_NARRATOR",
    "female_narrator": "ELEVENLABS_VOICE_ID_FEMALE_NARRATOR",
}


@dataclass(frozen=True)
class ElevenLabsConfig:
    api_key: str
    model_id: str
    output_format: str
    timeout_sec: float
    stability: float | None
    similarity_boost: float | None
    style: float | None
    use_speaker_boost: bool | None


@dataclass
class DialogueRunResult:
    line_id: str
    text: str
    voice_type: str
    voice_id: str
    voice_model: str
    provider: str
    output_path: Path
    success: bool
    provenance_path: Path
    metadata_path: Path
    dry_run: bool
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "text": self.text,
            "voice_type": self.voice_type,
            "voice_id": self.voice_id,
            "voice_model": self.voice_model,
            "provider": self.provider,
            "output_path": str(self.output_path),
            "success": self.success,
            "provenance_path": str(self.provenance_path),
            "metadata_path": str(self.metadata_path),
            "dry_run": self.dry_run,
            "error": self.error,
        }


def list_presets() -> list[tuple[str, str, str]]:
    """Return (line_id, voice_type, text) for all built-in presets."""
    return [(lid, vt, text) for lid, text, vt, _ in DIALOGUE_PRESETS]


def run_dialogue_presets(
    *,
    game_scope: str = "roman_arena",
    dry_run: bool = False,
    voice_type_filter: str | None = None,
    tags_filter: list[str] | None = None,
    output_dir: str | Path | None = None,
    provider: str = DEFAULT_PROVIDER,
    audio_class: str = DEFAULT_AUDIO_CLASS,
    operator: str | None = None,
) -> list[DialogueRunResult]:
    """Run all built-in dialogue presets, optionally filtered."""
    resolved_provider = _normalize_provider(provider)
    selected = [
        (lid, text, vt, tags)
        for lid, text, vt, tags in DIALOGUE_PRESETS
        if (not voice_type_filter or vt == voice_type_filter)
        and (not tags_filter or any(t in tags for t in tags_filter))
    ]
    out = _resolve_output_dir(game_scope=game_scope, output_dir=output_dir)

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[DialogueRunner | {mode}] provider={resolved_provider} lines={len(selected)} scope={game_scope}")

    if dry_run:
        results = []
        for lid, text, vt, _ in selected:
            print(f"  {lid} [{vt}/{resolved_provider}]: {text[:60]}...")
            results.append(
                DialogueRunResult(
                    line_id=lid,
                    text=text,
                    voice_type=vt,
                    voice_id=_resolve_voice_id(provider=resolved_provider, voice_type=vt),
                    voice_model=_resolve_voice_model(resolved_provider),
                    provider=resolved_provider,
                    output_path=_output_path(out, lid),
                    success=False,
                    provenance_path=out / "provenance.json",
                    metadata_path=_metadata_path(out, lid),
                    dry_run=True,
                )
            )
        return results

    out.mkdir(parents=True, exist_ok=True)
    resolved_operator = _resolve_operator(operator)
    results = asyncio.run(
        _generate_batch(
            selected,
            out,
            game_scope=game_scope,
            provider=resolved_provider,
            audio_class=audio_class,
            operator=resolved_operator,
        )
    )
    _write_provenance(
        out,
        game_scope=game_scope,
        provider=resolved_provider,
        audio_class=audio_class,
        operator=resolved_operator,
        results=results,
    )
    done = sum(1 for r in results if r.success)
    print(f"  Generated {done}/{len(results)} dialogue lines.")
    return results


def run_dialogue_line(
    *,
    line_id: str,
    text: str,
    voice_type: str = "announcer",
    game_scope: str = "roman_arena",
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    provider: str = DEFAULT_PROVIDER,
    audio_class: str = DEFAULT_AUDIO_CLASS,
    operator: str | None = None,
) -> DialogueRunResult:
    """Generate a single dialogue line."""
    resolved_provider = _normalize_provider(provider)
    out = _resolve_output_dir(game_scope=game_scope, output_dir=output_dir)
    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[DialogueRunner | {mode}] provider={resolved_provider} {line_id} [{voice_type}]: {text[:60]}...")

    if dry_run:
        return DialogueRunResult(
            line_id=line_id,
            text=text,
            voice_type=voice_type,
            voice_id=_resolve_voice_id(provider=resolved_provider, voice_type=voice_type),
            voice_model=_resolve_voice_model(resolved_provider),
            provider=resolved_provider,
            output_path=_output_path(out, line_id),
            success=False,
            provenance_path=out / "provenance.json",
            metadata_path=_metadata_path(out, line_id),
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)
    resolved_operator = _resolve_operator(operator)
    results = asyncio.run(
        _generate_batch(
            [(line_id, text, voice_type, [])],
            out,
            game_scope=game_scope,
            provider=resolved_provider,
            audio_class=audio_class,
            operator=resolved_operator,
        )
    )
    _write_provenance(
        out,
        game_scope=game_scope,
        provider=resolved_provider,
        audio_class=audio_class,
        operator=resolved_operator,
        results=results,
    )
    return results[0]


async def _generate_batch(
    selected: list[tuple[str, str, str, list[str]]],
    out: Path,
    *,
    game_scope: str,
    provider: str,
    audio_class: str,
    operator: str,
) -> list[DialogueRunResult]:
    tasks = [
        _generate_single(
            lid,
            text,
            vt,
            out,
            game_scope=game_scope,
            provider=provider,
            audio_class=audio_class,
            operator=operator,
        )
        for lid, text, vt, _ in selected
    ]
    return list(await asyncio.gather(*tasks))


async def _generate_single(
    line_id: str,
    text: str,
    voice_type: str,
    out: Path,
    *,
    game_scope: str,
    provider: str,
    audio_class: str,
    operator: str,
) -> DialogueRunResult:
    output_path = _output_path(out, line_id)
    metadata_path = _metadata_path(out, line_id)
    provenance_path = out / "provenance.json"
    voice_id = _resolve_voice_id(provider=provider, voice_type=voice_type)
    voice_model = _resolve_voice_model(provider)

    if provider == "elevenlabs":
        success, error = await _generate_elevenlabs(text=text, voice_id=voice_id, output_path=output_path)
    else:
        success, error = await _generate_edge_tts(text=text, voice_id=voice_id, output_path=output_path)

    result = DialogueRunResult(
        line_id=line_id,
        text=text,
        voice_type=voice_type,
        voice_id=voice_id,
        voice_model=voice_model,
        provider=provider,
        output_path=output_path,
        success=success,
        provenance_path=provenance_path,
        metadata_path=metadata_path,
        dry_run=False,
        error=error,
    )
    _write_line_metadata(
        result,
        game_scope=game_scope,
        audio_class=audio_class,
        operator=operator,
    )
    return result


async def _generate_edge_tts(*, text: str, voice_id: str, output_path: Path) -> tuple[bool, str]:
    try:
        import edge_tts
    except ImportError:
        message = "edge-tts is not installed. Run: pip install edge-tts"
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message

    try:
        communicate = edge_tts.Communicate(text, voice_id)
        await communicate.save(str(output_path))
        print(f"  OK  {output_path.name}")
        return True, ""
    except Exception as exc:
        message = str(exc)
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message


async def _generate_elevenlabs(*, text: str, voice_id: str, output_path: Path) -> tuple[bool, str]:
    config = _load_elevenlabs_config()
    if not config.api_key:
        message = "ELEVENLABS_API_KEY is not configured. Set the env var and retry, or use --provider edge_tts."
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message

    if not str(voice_id or "").strip():
        message = "No ElevenLabs voice id was resolved for this dialogue line."
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message

    payload: dict[str, Any] = {
        "text": text,
        "model_id": config.model_id,
    }
    voice_settings: dict[str, Any] = {}
    if config.stability is not None:
        voice_settings["stability"] = config.stability
    if config.similarity_boost is not None:
        voice_settings["similarity_boost"] = config.similarity_boost
    if config.style is not None:
        voice_settings["style"] = config.style
    if config.use_speaker_boost is not None:
        voice_settings["use_speaker_boost"] = config.use_speaker_boost
    if voice_settings:
        payload["voice_settings"] = voice_settings

    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": config.api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=config.timeout_sec) as client:
            response = await client.post(
                url,
                headers=headers,
                params={"output_format": config.output_format},
                json=payload,
            )
            response.raise_for_status()
            output_path.write_bytes(response.content)
        print(f"  OK  {output_path.name}")
        return True, ""
    except httpx.HTTPStatusError as exc:
        details = _extract_http_error(exc.response)
        message = f"ElevenLabs HTTP {exc.response.status_code}: {details}"
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message
    except httpx.TimeoutException:
        message = (
            f"ElevenLabs request timed out after {config.timeout_sec:.1f}s at {ELEVENLABS_API_BASE}. "
            "Verify provider reachability or switch to --provider edge_tts."
        )
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message
    except httpx.ConnectError:
        message = (
            f"ElevenLabs endpoint is unreachable at {ELEVENLABS_API_BASE}. "
            "Check network/API access and retry, or switch to --provider edge_tts."
        )
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message
    except Exception as exc:
        message = str(exc)
        print(f"  FAIL {output_path.stem}: {message}")
        return False, message


def _write_line_metadata(
    result: DialogueRunResult,
    *,
    game_scope: str,
    audio_class: str,
    operator: str,
) -> Path:
    generated_at = _utc_now_iso()
    payload = {
        "schema_version": "assetboy.audio.dialogue-line.v1",
        "line_id": result.line_id,
        "provider": result.provider,
        "generated_or_imported": "generated",
        "license_or_terms_note": _provider_license(result.provider),
        "license": _provider_license(result.provider),
        "prompt_or_source": result.text,
        "operator": operator,
        "generated_at": generated_at,
        "audio_class": audio_class,
        "game_scope": game_scope,
        "voice_type": result.voice_type,
        "voice_id": result.voice_id,
        "voice_model": result.voice_model,
        "source_adapter": _source_adapter_for_provider(result.provider),
        "lane": "generator",
        "staging_output_path": str(result.output_path.resolve()),
        "output_file": result.output_path.name,
        "success": result.success,
    }
    if result.error:
        payload["error"] = result.error
    result.metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return result.metadata_path


def _write_provenance(
    out_dir: Path,
    *,
    game_scope: str,
    provider: str,
    audio_class: str,
    operator: str,
    results: list[DialogueRunResult],
) -> Path:
    acquired_at = _utc_now_iso()
    payload = {
        "schema_version": "assetboy.provenance.v2",
        "pack_id": f"DIA_{game_scope.upper()}_{provider.upper()}",
        "game_scope": game_scope,
        "source_url": _provider_source_url(provider),
        "license_or_terms_note": _provider_license(provider),
        "license": _provider_license(provider),
        "license_snapshot": _provider_license_snapshot(provider),
        "author_or_vendor": _provider_vendor(provider),
        "acquired_at": acquired_at,
        "lane": "generator",
        "source_adapter": _source_adapter_for_provider(provider),
        "payload_target_path": str(out_dir.resolve()),
        "entitlement_note": _provider_entitlement_note(provider),
        "prompt": "See per-line .metadata.json sidecars for the exact dialogue transcript per output file.",
        "model_name": _provider_model_name(provider),
        "profile_id": f"dialogue.{provider}",
        "notebook_or_session": _provider_session_label(provider),
        "provider": provider,
        "generated_or_imported": "generated",
        "prompt_or_source": "See per-line .metadata.json sidecars for each dialogue transcript.",
        "operator": operator,
        "generated_at": acquired_at,
        "audio_class": audio_class,
        "line_count": len(results),
        "success_count": sum(1 for result in results if result.success),
        "voices_used": sorted({result.voice_type for result in results}),
        "lines": [result.to_dict() for result in results],
    }
    canonical = canonicalize_provenance_payload(payload, keep_extra=True)
    _, errors, warnings = validate_provenance_payload(
        canonical,
        expected_lane="generator",
        expected_payload_target_path=out_dir,
    )
    if errors:
        raise ValueError("Invalid dialogue provenance payload: " + "; ".join(errors))
    if warnings:
        print("  [WARN] dialogue provenance warnings: " + " | ".join(warnings))

    path = out_dir / "provenance.json"
    path.write_text(json.dumps(canonical, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path


def _load_elevenlabs_config() -> ElevenLabsConfig:
    return ElevenLabsConfig(
        api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        model_id=os.getenv("ELEVENLABS_MODEL_ID", DEFAULT_ELEVENLABS_MODEL_ID).strip() or DEFAULT_ELEVENLABS_MODEL_ID,
        output_format=os.getenv("ELEVENLABS_OUTPUT_FORMAT", DEFAULT_ELEVENLABS_OUTPUT_FORMAT).strip()
        or DEFAULT_ELEVENLABS_OUTPUT_FORMAT,
        timeout_sec=_env_float("ELEVENLABS_TIMEOUT_SEC", DEFAULT_ELEVENLABS_TIMEOUT_SEC),
        stability=_env_optional_float("ELEVENLABS_STABILITY"),
        similarity_boost=_env_optional_float("ELEVENLABS_SIMILARITY_BOOST"),
        style=_env_optional_float("ELEVENLABS_STYLE"),
        use_speaker_boost=_env_optional_bool("ELEVENLABS_USE_SPEAKER_BOOST"),
    )


def _resolve_elevenlabs_voice_id(voice_type: str) -> str:
    normalized = str(voice_type or "").strip()
    if not normalized:
        normalized = "announcer"
    env_key = ELEVENLABS_VOICE_ENV_MAP.get(normalized)
    if env_key:
        override = os.getenv(env_key, "").strip()
        if override:
            return override
    return ELEVENLABS_VOICE_MAP.get(normalized, ELEVENLABS_VOICE_MAP["announcer"])


def _resolve_output_dir(*, game_scope: str, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        resolved = Path(output_dir).resolve()
    else:
        resolved = (generated_output_root() / "dialogue" / game_scope).resolve()

    _ensure_output_dir_is_staging(resolved)
    return resolved


def _output_path(out_dir: Path, line_id: str) -> Path:
    return out_dir / f"{line_id}.mp3"


def _metadata_path(out_dir: Path, line_id: str) -> Path:
    return out_dir / f"{line_id}.metadata.json"


def _normalize_provider(provider: str) -> str:
    normalized = str(provider or DEFAULT_PROVIDER).strip().lower().replace("-", "_")
    if normalized not in SUPPORTED_PROVIDERS:
        allowed = ", ".join(SUPPORTED_PROVIDERS)
        raise ValueError(f"Unsupported dialogue provider '{provider}'. Allowed: {allowed}.")
    return normalized


def _resolve_voice_id(*, provider: str, voice_type: str) -> str:
    if provider == "elevenlabs":
        return _resolve_elevenlabs_voice_id(voice_type)
    return EDGE_TTS_VOICE_MAP.get(voice_type, EDGE_TTS_VOICE_MAP["announcer"])


def _resolve_voice_model(provider: str) -> str:
    if provider == "elevenlabs":
        return _load_elevenlabs_config().model_id
    return "azure_neural_voice"


def _resolve_operator(operator: str | None) -> str:
    value = str(operator or "").strip()
    if value:
        return value
    for env_name in ("ASSETBOY_OPERATOR", "USERNAME", "USER"):
        candidate = os.getenv(env_name, "").strip()
        if candidate:
            return candidate
    return "unknown_operator"


def _provider_source_url(provider: str) -> str:
    if provider == "elevenlabs":
        return "https://api.elevenlabs.io/v1/text-to-speech"
    return "https://github.com/rany2/edge-tts"


def _provider_license(provider: str) -> str:
    if provider == "elevenlabs":
        return "ElevenLabs Terms of Service — review account tier and commercial voice rights before shipping."
    return "Microsoft Edge/Azure Neural voice terms — review provider terms before shipping generated voice assets."


def _provider_license_snapshot(provider: str) -> str:
    if provider == "elevenlabs":
        return (
            "Hosted ElevenLabs voice generation. Audio usage rights depend on the configured account, chosen voice, "
            "and active ElevenLabs terms."
        )
    return (
        "Generated with edge-tts using Microsoft neural voices. Commercial/shipping usage must be reviewed against the "
        "current Microsoft terms for the selected voice lane."
    )


def _provider_entitlement_note(provider: str) -> str:
    if provider == "elevenlabs":
        return "Operator must provide a valid ElevenLabs API key and confirm the selected voice/account is approved for project use."
    return "Operator must confirm the selected Microsoft/Edge voice lane is approved for the intended shipping use."


def _provider_vendor(provider: str) -> str:
    if provider == "elevenlabs":
        return "ElevenLabs"
    return "Microsoft Edge TTS"


def _provider_model_name(provider: str) -> str:
    if provider == "elevenlabs":
        return _load_elevenlabs_config().model_id
    return "edge-tts / Azure Neural voices"


def _provider_session_label(provider: str) -> str:
    if provider == "elevenlabs":
        return "assetboy.dialogue_runner.elevenlabs"
    return "assetboy.dialogue_runner.edge_tts"


def _source_adapter_for_provider(provider: str) -> str:
    if provider == "elevenlabs":
        return "elevenlabs_api"
    return "edge_tts_local"


def _ensure_output_dir_is_staging(path: Path) -> None:
    try:
        content_root = (project_root() / "GameProjectFlax" / "MyProject" / "Content").resolve()
    except Exception:
        return

    if _is_relative_to(path, content_root):
        raise ValueError(
            "Dialogue output_dir must point to staging (for example state/generated/dialogue/<game_scope>) "
            "and not directly into GameProjectFlax/MyProject/Content shipping paths."
        )


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _extract_http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "unknown error"
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("status") or "").strip()
            if message:
                return message
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        message = str(payload.get("message") or "").strip()
        if message:
            return message
    return json.dumps(payload, ensure_ascii=False)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_optional_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_optional_bool(name: str) -> bool | None:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None
