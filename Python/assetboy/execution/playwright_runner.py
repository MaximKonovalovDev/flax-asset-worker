""" 
playwright_runner.py — Emits browser automation plans for Playwright MCP.

Reads a browser_job.json emitted by emit_browser_automation_job and drives
a Playwright browser session to navigate, search, and download assets when a
human or MCP client executes the emitted steps.

When Playwright MCP is active in chat, the AI calls these steps directly.

Usage (via CLI):
    python -m assetboy.cli run-browser-job --job-spec path/to/browser_job.json
    python -m assetboy.cli run-mixamo-batch --pack-id RA_PACK_CHR_CORE_SLICE_01 --search "male fighter humanoid base"
    python -m assetboy.cli emit-browser-job --source-adapter fab --pack-id RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01 --source-url https://www.fab.com/ --search-terms "roman arena"
    python -m assetboy.cli run-browser-job --job-spec <generated_fab_browser_job.json>
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import urlopen

from assetboy.library.paths import assetboy_root, generated_output_root, manual_drop_dir
from assetboy.providers.auth_freshness import describe_auth_state_freshness
from assetboy.providers.fab_hybrid import FabHybridDownloader
from assetboy.providers.mixamo_auth import MixamoAuthSession
from assetboy.providers.unity_auth import UnityAuthSession


@dataclass
class BrowserRunResult:
    source_adapter: str
    pack_id: str
    job_spec_path: Path
    download_target: Path
    steps_emitted: list[str]
    dry_run: bool
    executed: bool = False
    execution_mode: str = "plan"
    artifacts_dir: Path | None = None
    browser_profile_dir: Path | None = None
    last_url: str = ""
    attempts: int = 0
    error: str = ""
    repair_command: str = ""
    repair_reason: str = ""
    provider_runbook_id: str = ""

    def to_dict(self) -> dict:
        return {
            "source_adapter": self.source_adapter,
            "pack_id": self.pack_id,
            "job_spec_path": str(self.job_spec_path),
            "download_target": str(self.download_target),
            "steps_emitted": self.steps_emitted,
            "dry_run": self.dry_run,
            "executed": self.executed,
            "execution_mode": self.execution_mode,
            "artifacts_dir": str(self.artifacts_dir) if self.artifacts_dir else None,
            "browser_profile_dir": str(self.browser_profile_dir) if self.browser_profile_dir else None,
            "last_url": self.last_url,
            "attempts": self.attempts,
            "error": self.error,
            "repair_command": self.repair_command,
            "repair_reason": self.repair_reason,
            "provider_runbook_id": self.provider_runbook_id,
        }


@dataclass
class MixamoBatchResult:
    pack_id: str
    search: str
    download_target: Path
    job_spec_path: Path | None = None
    steps: list[dict] = field(default_factory=list)
    dry_run: bool = False
    executed: bool = False
    execution_mode: str = "plan"
    artifacts_dir: Path | None = None
    last_url: str = ""

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "search": self.search,
            "download_target": str(self.download_target),
            "job_spec_path": str(self.job_spec_path) if self.job_spec_path else None,
            "steps": len(self.steps),
            "dry_run": self.dry_run,
            "executed": self.executed,
            "execution_mode": self.execution_mode,
            "artifacts_dir": str(self.artifacts_dir) if self.artifacts_dir else None,
            "last_url": self.last_url,
        }


# ---------------------------------------------------------------------------
# Adapter-specific step builders
# ---------------------------------------------------------------------------

def _steps_for_mixamo(job: dict) -> list[str]:
    search_terms = job.get("search_terms", [])
    first_term = search_terms[0] if search_terms else "roman gladiator"
    dest = job.get("destination", str(manual_drop_dir() / job.get("pack_id", "mixamo_download")))
    return [
        f"Navigate to: https://www.mixamo.com/#/?query={first_term.replace(' ', '+')}",
        "Screenshot — confirm character results loaded",
        "If login modal visible: sign in with Adobe account (already logged in — just confirm session)",
        f"Click the best matching character for: {', '.join(search_terms)}",
        "Screenshot — character loaded in preview",
        "Click 'Download' button",
        "In download dialog: set Format=FBX, Pose=T-pose, With Skin=Yes",
        "Click 'Download' to confirm",
        f"Save file to: {dest}",
        "Screenshot — confirm download completed",
        "Note: preserve exact downloaded filename for provenance",
    ]


def _steps_for_mixamo_animations(job: dict) -> list[str]:
    search_terms = job.get("search_terms", [])
    first_term = search_terms[0] if search_terms else "combat idle"
    dest = job.get("destination", str(manual_drop_dir() / job.get("pack_id", "mixamo_anim")))
    return [
        "Navigate to: https://www.mixamo.com",
        "Screenshot — confirm Mixamo loaded",
        "Click 'Animations' tab at top of character panel",
        f"In animation search box type: {first_term}",
        "Screenshot — confirm animation search results",
        "For each animation in search_terms:",
        f"  Search terms: {', '.join(search_terms)}",
        "  Click the animation to preview on character",
        "  Click 'Download'",
        "  Set: Format=FBX, FPS=30, Skin=Without Skin (animations only)",
        "  Click 'Download' to confirm",
        f"  Save to: {dest}",
        "Screenshot — confirm all downloads completed",
    ]


def _steps_for_fab(job: dict) -> list[str]:
    search_terms = job.get("search_terms", [])
    query = (search_terms[0] if search_terms else "roman").replace(" ", "+")
    dest = job.get("destination", str(manual_drop_dir() / job.get("pack_id", "fab_download")))
    return [
        f"Navigate to: https://www.fab.com/search?q={query}&priceMax=0",
        "Screenshot — confirm Fab free asset search results",
        "If login required: sign in with Epic account (already logged in — confirm session)",
        "Filter by: Free Assets only (priceMax=0 already in URL)",
        "Filter by: 3D Models category if searching for geometry",
        "Screenshot — confirm filtered results",
        "For the top relevant result matching the search terms:",
        "  Click the asset card",
        "  Screenshot — confirm asset detail page loaded",
        "  Verify license: must be free personal/commercial or CC",
        "  Click 'Add to My Library' or 'Get for Free'",
        "  Screenshot — confirm added to library",
        "  Note: actual download happens via Epic Launcher / UEVaultManager",
        f"  Record: product URL, asset name, seller, license → save to {dest}/provenance.txt",
    ]


def _steps_for_unity_asset_store(job: dict) -> list[str]:
    search_terms = job.get("search_terms", [])
    query = (search_terms[0] if search_terms else "roman").replace(" ", "%20")
    dest = job.get("destination", str(manual_drop_dir() / job.get("pack_id", "unity_download")))
    return [
        f"Navigate to: https://assetstore.unity.com/?q={query}&orderBy=1&free=true",
        "Screenshot — confirm Unity Asset Store search results",
        "Filter: free assets, 3D category",
        "For the top relevant result:",
        "  Click the asset",
        "  Screenshot — confirm asset page",
        "  Click 'Add to My Assets'",
        "  Note the asset name, publisher, version for provenance",
        f"  Record to: {dest}/provenance.txt",
        "Note: Download via Unity Editor → Package Manager → My Assets",
    ]


def _steps_for_generic(job: dict) -> list[str]:
    return [
        f"Navigate to: {job.get('source_url', 'https://www.google.com')}",
        "Screenshot",
        f"Search for: {', '.join(job.get('search_terms', []))}",
        f"Download and place in: {job.get('destination', 'manual_drop')}",
        "Record provenance: source URL, license, download date",
    ]


ADAPTER_STEP_BUILDERS = {
    "mixamo": _steps_for_mixamo,
    "mixamo_animations": _steps_for_mixamo_animations,
    "fab": _steps_for_fab,
    "unity_asset_store": _steps_for_unity_asset_store,
}


def _build_steps(job: dict) -> list[str]:
    adapter = job.get("source_adapter", "")
    builder = ADAPTER_STEP_BUILDERS.get(adapter, _steps_for_generic)
    return builder(job)


def _job_search_terms(job: dict) -> list[str]:
    raw_terms = job.get("search_terms", [])
    if isinstance(raw_terms, str):
        raw_terms = [raw_terms]
    return [str(item).strip() for item in raw_terms if str(item).strip()]


def _slugify_hint(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return slug or fallback


_CONTAINS_SELECTOR_RE = re.compile(r":contains\((['\"])(.*?)\1\)")


def _default_browser_profile_dir(adapter: str = "") -> Path:
    normalized = str(adapter).strip().lower()
    if normalized in {"unity_asset_store"}:
        profile_name = "unity_browser_profile"
    elif normalized in {"mixamo", "mixamo_animations"}:
        profile_name = "mixamo_browser_profile"
    else:
        profile_name = "fab_browser_profile"
    return (assetboy_root(__file__) / ".private" / profile_name).resolve()


def _default_auth_state_path(adapter: str) -> Path | None:
    private_root = (assetboy_root(__file__) / ".private").resolve()
    normalized = str(adapter).strip().lower()
    if normalized in {"mixamo", "mixamo_animations"}:
        return private_root / "mixamo_auth_state.json"
    if normalized == "fab":
        return private_root / "fab_auth_state.json"
    if normalized == "unity_asset_store":
        return private_root / "unity_auth_state.json"
    return None


def _interactive_login_recovery_hint(adapter: str) -> str:
    normalized = str(adapter).strip().lower()
    if normalized == "fab":
        return (
            "Next action: run `python scripts/cli.py asset-factory fab-auth --reuse-profile` "
            "and retry the browser job."
        )
    if normalized in {"mixamo", "mixamo_animations"}:
        return (
            "Next action: run `python scripts/cli.py asset-factory mixamo-auth --reuse-profile` "
            "and retry the browser job."
        )
    if normalized == "unity_asset_store":
        return (
            "Next action: run `python scripts/cli.py asset-factory unity-auth --reuse-profile` "
            "and retry the browser job."
        )
    return "Next action: sign in with the provider account in the shared browser profile, then retry."


_REUSE_PROFILE_REPAIR_REASONS = {
    "auth_state_stale",
    "auth_probe_failed",
    "auth_state_not_authenticated",
    "profile_state_present_without_auth_snapshot",
}


def _provider_runbook_id_for_adapter(source_adapter: str) -> str:
    normalized = str(source_adapter or "").strip().lower()
    if normalized == "fab":
        return "fab"
    if normalized in {"mixamo", "mixamo_animations"}:
        return "mixamo"
    if normalized == "unity_asset_store":
        return "unity_asset_store"
    return ""


def _provider_display_name_for_adapter(source_adapter: str) -> str:
    provider_id = _provider_runbook_id_for_adapter(source_adapter)
    if provider_id == "fab":
        return "Fab"
    if provider_id == "mixamo":
        return "Mixamo"
    if provider_id == "unity_asset_store":
        return "Unity Asset Store"
    return str(source_adapter or "").strip() or "Browser"


def _provider_auth_status_for_adapter(source_adapter: str) -> dict[str, object]:
    provider_id = _provider_runbook_id_for_adapter(source_adapter)
    if provider_id == "fab":
        return FabHybridDownloader(debug=False).auth_status()
    if provider_id == "mixamo":
        return MixamoAuthSession(debug=False).auth_status()
    if provider_id == "unity_asset_store":
        return UnityAuthSession().auth_status()
    return {}


def _repair_required_message(*, source_adapter: str, repair_command: str, repair_reason: str, provider_runbook_id: str) -> str:
    provider_name = _provider_display_name_for_adapter(source_adapter)
    reason_text = {
        "auth_state_stale": "saved shared browser auth is stale",
        "auth_probe_failed": "saved shared browser auth could not be validated automatically",
        "auth_state_not_authenticated": "saved shared browser auth is no longer authenticated",
        "profile_state_present_without_auth_snapshot": "the shared browser profile needs a refreshed reusable auth snapshot",
    }.get(repair_reason, "the saved shared browser auth needs repair")
    runbook_command = f"python scripts/cli.py asset-factory print-provider-runbook --provider {provider_runbook_id}"
    return (
        f"{provider_name} browser auth needs repair because {reason_text}. "
        f"Run `{repair_command}` and review `{runbook_command}` before retrying this browser job."
    )


def _browser_auth_repair_payload(job: dict) -> dict[str, object] | None:
    source_adapter = str(job.get("source_adapter", "")).strip()
    provider_runbook_id = _provider_runbook_id_for_adapter(source_adapter)
    if not provider_runbook_id:
        return None

    status = _provider_auth_status_for_adapter(source_adapter)
    if not isinstance(status, dict):
        return None

    repair_command = str(status.get("repair_command", "")).strip()
    repair_reason = str(status.get("repair_reason", "")).strip()
    auth_state_present = bool(status.get("auth_state_exists")) or bool(status.get("browser_profile_has_state"))
    stale = bool(status.get("auth_state_stale"))
    repair_recommended = bool(status.get("repair_recommended"))
    if not repair_command or not auth_state_present:
        return None
    if not stale and not (repair_recommended and repair_reason in _REUSE_PROFILE_REPAIR_REASONS):
        return None

    resolved_reason = repair_reason or ("auth_state_stale" if stale else "auth_repair_required")
    return {
        "repair_command": repair_command,
        "repair_reason": resolved_reason,
        "provider_runbook_id": provider_runbook_id,
        "error": _repair_required_message(
            source_adapter=source_adapter,
            repair_command=repair_command,
            repair_reason=resolved_reason,
            provider_runbook_id=provider_runbook_id,
        ),
    }


def _existing_auth_state_path(job: dict) -> Path | None:
    candidate = _default_auth_state_path(str(job.get("source_adapter", "")))
    if candidate is None or not candidate.exists():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return candidate.resolve()
    if isinstance(payload, dict) and payload.get("authenticated") is False:
        return None
    freshness = describe_auth_state_freshness(auth_state_path=candidate, auth_state=payload if isinstance(payload, dict) else None)
    if bool(freshness.get("auth_state_stale")):
        return None
    return candidate.resolve()


def _should_use_storage_state(job: dict) -> bool:
    adapter = str(job.get("source_adapter", "")).strip().lower()
    # Unity's claim flow depends on cross-domain OAuth handoffs that are more
    # reliable against the real persistent browser profile than a reduced
    # storage_state snapshot.
    # Mixamo downloads also rely on the full saved browser profile. The reduced
    # auth snapshot is good enough to browse, but it can silently miss the
    # final download handoff.
    return adapter not in {"unity_asset_store", "mixamo", "mixamo_animations"}


def _extract_unity_asset_id(job: dict) -> str:
    source_url = str(job.get("source_url", "")).strip()
    if not source_url:
        return ""
    match = re.search(r"-(\d+)(?:[/?#]|$)", source_url)
    return match.group(1) if match else ""


def _is_unity_claim_click_step(step: dict) -> bool:
    if str(step.get("action", "")).strip().lower() != "click":
        return False
    params = step.get("params", {})
    if not isinstance(params, dict):
        return False
    selector = str(params.get("selector", "")).strip().lower()
    return "add to my assets" in selector or "open in unity" in selector


def _artifacts_dir_for_job(spec_path: Path, job: dict) -> Path:
    adapter_slug = _slugify_hint(str(job.get("source_adapter", "")), "adapter")
    pack_slug = _slugify_hint(str(job.get("pack_id", "")), "pack")
    spec_slug = _slugify_hint(spec_path.stem, "browser_job")
    return spec_path.parent / "playwright_exec" / adapter_slug / pack_slug / spec_slug


def _normalize_selector(selector: str) -> str:
    text = str(selector or "").strip()
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        return f':has-text("{match.group(2)}")'

    return _CONTAINS_SELECTOR_RE.sub(_replace, text)


def _console_safe_text(value: object) -> str:
    text = str(value)
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2192": "->",
        "\u21b5": " -> ",
        "\u2026": "...",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    try:
        return text.encode("cp1252", errors="replace").decode("cp1252")
    except Exception:
        return text.encode("ascii", errors="replace").decode("ascii")


def _download_url_to_file(source_url: str, output_path: Path, *, timeout_ms: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = max(float(timeout_ms) / 1000.0, 1.0)
    with urlopen(source_url, timeout=timeout_seconds) as response, output_path.open("wb") as handle:
        handle.write(response.read())


def _unity_page_claim_state(page, product_id: str = "") -> dict[str, object]:
    try:
        state = page.evaluate(
            """
            ({ productId }) => {
                const body = (document.body?.innerText || "").toLowerCase();
                let storageOwned = false;
                try {
                    for (let i = 0; i < localStorage.length; i += 1) {
                        const key = localStorage.key(i) || "";
                        if (!key.startsWith("myAssets-")) {
                            continue;
                        }
                        const raw = localStorage.getItem(key) || "";
                        if (productId && raw.includes(`"${productId}"`)) {
                            storageOwned = true;
                            break;
                        }
                    }
                } catch (_error) {
                    storageOwned = false;
                }
                return {
                    url: window.location.href,
                    purchased: body.includes("you purchased this item"),
                    openInUnity: body.includes("open in unity"),
                    addToMyAssets: body.includes("add to my assets"),
                    myAssetsContainsProduct: storageOwned,
                };
            }
            """,
            {"productId": str(product_id or "")},
        )
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def _capture_page_text(page) -> str:
    try:
        text = page.evaluate(
            """
            () => {
                const raw = document.body?.innerText || "";
                return raw
                    .replace(/\\r/g, "")
                    .replace(/\\u00a0/g, " ")
                    .replace(/[ \\t]+\\n/g, "\\n")
                    .replace(/\\n{3,}/g, "\\n\\n")
                    .trim();
            }
            """
        )
    except Exception:
        return ""
    return str(text).strip() if isinstance(text, str) else ""


def _capture_page_dom(page) -> str:
    try:
        html = page.content()
    except Exception:
        return ""
    return str(html).strip() if isinstance(html, str) else ""


def _html_to_text(html_text: str) -> str:
    text = str(html_text or "")
    if not text.strip():
        return ""
    text = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|li|tr|td|th|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _artifact_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return 0, 0
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return 0, 0
    return int(width), int(height)


def _write_browser_evidence_files(page, *, artifacts_dir: Path, page_text: str = "") -> dict[str, str]:
    payload: dict[str, str] = {}
    page_dom = _capture_page_dom(page)
    if page_dom:
        page_dom_path = artifacts_dir / "page_dom.html"
        page_dom_path.write_text(page_dom, encoding="utf-8")
        payload["page_dom_path"] = str(page_dom_path)
        dom_text = _html_to_text(page_dom)
        if dom_text:
            dom_text_path = artifacts_dir / "page_dom.txt"
            dom_text_path.write_text(dom_text, encoding="utf-8")
            payload["page_dom_text_path"] = str(dom_text_path)

            lines = _normalize_page_lines(dom_text, limit=220)
            dom_metadata = {
                "captured_at": _artifact_timestamp(page_dom_path),
                "line_count": len(lines),
                "license_lines": _matching_page_lines(
                    lines,
                    (
                        "license type",
                        "standard unity asset store eula",
                        "fab standard license",
                        "license",
                        "eula",
                        "creative commons",
                        "cc-by",
                        "cc0",
                    ),
                    limit=12,
                ),
                "ownership_lines": _matching_page_lines(
                    lines,
                    (
                        "you purchased this item",
                        "open in unity",
                        "add to my assets",
                        "add to my library",
                        "owned",
                        "in library",
                        "download",
                        "export",
                    ),
                    limit=12,
                ),
                "visible_actions": _matching_page_lines(
                    lines,
                    (
                        "open in unity",
                        "add to my assets",
                        "add to my library",
                        "claim",
                        "download",
                        "export",
                    ),
                    limit=16,
                ),
                "dom_text_excerpt": dom_text[:8000],
                "page_text_excerpt": str(page_text or "")[:8000],
            }
            dom_metadata_path = artifacts_dir / "page_dom_metadata.json"
            dom_metadata_path.write_text(json.dumps(dom_metadata, indent=2), encoding="utf-8")
            payload["page_dom_metadata_path"] = str(dom_metadata_path)
    try:
        page_screenshot_path = artifacts_dir / "page_screenshot.png"
        page.screenshot(path=str(page_screenshot_path), full_page=True)
    except Exception:
        return payload
    payload["page_screenshot_path"] = str(page_screenshot_path)
    screenshot_meta: dict[str, object] = {
        "filename": page_screenshot_path.name,
        "size_bytes": int(page_screenshot_path.stat().st_size),
        "captured_at": _artifact_timestamp(page_screenshot_path),
    }
    if page_screenshot_path.suffix.lower() == ".png":
        width, height = _png_dimensions(page_screenshot_path)
        if width > 0 and height > 0:
            screenshot_meta["width"] = width
            screenshot_meta["height"] = height
    screenshot_meta_path = artifacts_dir / "page_screenshot_meta.json"
    screenshot_meta_path.write_text(json.dumps(screenshot_meta, indent=2), encoding="utf-8")
    payload["page_screenshot_meta_path"] = str(screenshot_meta_path)
    return payload


def _normalize_page_lines(text: str, *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in str(text or "").replace("\r", "").splitlines():
        normalized = re.sub(r"\s+", " ", raw_line).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        lines.append(normalized)
        if limit is not None and len(lines) >= limit:
            break
    return lines


def _pick_labeled_page_value(lines: list[str], labels: tuple[str, ...]) -> str:
    lowered_labels = tuple(label.strip().lower() for label in labels if label.strip())
    for index, line in enumerate(lines):
        lowered = line.lower()
        for label in lowered_labels:
            if lowered.startswith(label + ":"):
                return line[len(label) + 1 :].strip()
            if lowered == label and index + 1 < len(lines):
                return lines[index + 1].strip()
    return ""


def _matching_page_lines(lines: list[str], tokens: tuple[str, ...], *, limit: int = 8) -> list[str]:
    lowered_tokens = tuple(token.strip().lower() for token in tokens if token.strip())
    matches: list[str] = []
    seen: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if not any(token in lowered for token in lowered_tokens):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        matches.append(line)
        if len(matches) >= limit:
            break
    return matches


def _first_matching_page_line(lines: list[str], tokens: tuple[str, ...]) -> str:
    matches = _matching_page_lines(lines, tokens, limit=1)
    return matches[0] if matches else ""


def _merge_unique_text_values(existing: object, additions: list[str], *, limit: int = 12) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    candidates: list[object] = list(existing) if isinstance(existing, list) else [existing]
    candidates.extend(additions)
    for candidate in candidates:
        text = str(candidate or "").strip()
        lowered = text.lower()
        if not text or lowered in seen:
            continue
        seen.add(lowered)
        merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def _coerce_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value or "").strip()
    return [text] if text else []


def _has_text_values(value: object) -> bool:
    return any(item.strip() for item in _coerce_text_list(value))


def _augment_browser_metadata_from_page_text(
    metadata: dict[str, object],
    *,
    adapter: str,
    product_id: str = "",
    page_text: str,
) -> dict[str, object]:
    lines = _normalize_page_lines(page_text)
    if not lines:
        return dict(metadata)

    result = {str(key): value for key, value in metadata.items()}
    provider_evidence = dict(result.get("provider_evidence", {})) if isinstance(result.get("provider_evidence"), dict) else {}
    if product_id and not str(provider_evidence.get("product_id", "")).strip():
        provider_evidence["product_id"] = str(product_id)

    normalized_adapter = str(adapter or "").strip().lower()
    if normalized_adapter == "fab":
        seller = str(result.get("seller", "")).strip() or _pick_labeled_page_value(lines, ("Publisher", "Seller", "Creator"))
        license_name = str(result.get("license", "")).strip() or _pick_labeled_page_value(
            lines,
            ("License", "License terms", "Selected license"),
        )
        license_lines = _matching_page_lines(lines, ("license", "fab standard license", "creative commons", "cc-by", "cc0"))
        if not license_name and any("fab standard license" in line.lower() for line in license_lines):
            license_name = "Fab Standard License"
        license_snapshot = str(result.get("license_snapshot", "")).strip()
        if not license_snapshot and license_name:
            license_snapshot = f"License: {license_name}"
        if not license_snapshot and license_lines:
            license_snapshot = license_lines[0]
        ownership_lines = _matching_page_lines(
            lines,
            ("owned", "in library", "view in library", "add to my library", "add to library", "claim", "download", "export"),
        )
        visible_actions = _matching_page_lines(
            lines,
            ("download", "export", "claim", "add to my library", "add to library", "view in library", "owned"),
            limit=12,
        )
        download_action = str(result.get("download_action", "")).strip() or _first_matching_page_line(lines, ("download", "export"))
        claim_action = str(result.get("claim_action", "")).strip() or _first_matching_page_line(
            lines,
            ("add to my library", "add to library", "claim"),
        )
        ownership_action = str(result.get("ownership_action", "")).strip() or _first_matching_page_line(
            lines,
            ("owned", "in library", "view in library"),
        )

        if seller and not str(result.get("seller", "")).strip():
            result["seller"] = seller
        if license_name and not str(result.get("license", "")).strip():
            result["license"] = license_name
        if license_snapshot and not str(result.get("license_snapshot", "")).strip():
            result["license_snapshot"] = license_snapshot
        if download_action and not str(result.get("download_action", "")).strip():
            result["download_action"] = download_action
        if claim_action and not str(result.get("claim_action", "")).strip():
            result["claim_action"] = claim_action
        if ownership_action and not str(result.get("ownership_action", "")).strip():
            result["ownership_action"] = ownership_action
        if license_lines and not _has_text_values(result.get("license_lines")):
            result["license_lines"] = license_lines
        if ownership_lines and not _has_text_values(result.get("ownership_lines")):
            result["ownership_lines"] = ownership_lines
        if visible_actions and not _has_text_values(result.get("visible_actions")):
            result["visible_actions"] = visible_actions

        if seller and not str(provider_evidence.get("seller", "")).strip():
            provider_evidence["seller"] = seller
        if license_name and not str(provider_evidence.get("license", "")).strip():
            provider_evidence["license"] = license_name
        if license_snapshot and not str(provider_evidence.get("license_snapshot", "")).strip():
            provider_evidence["license_snapshot"] = license_snapshot
    elif normalized_adapter == "unity_asset_store":
        publisher = str(result.get("publisher", "")).strip() or _pick_labeled_page_value(lines, ("Publisher",))
        version = str(result.get("version", "")).strip() or _pick_labeled_page_value(lines, ("Latest version", "Version"))
        license_name = str(result.get("license", "")).strip() or _pick_labeled_page_value(lines, ("License type", "License"))
        license_lines = _matching_page_lines(lines, ("license type", "standard unity asset store eula", "license", "eula"))
        if not license_name and any("standard unity asset store eula" in line.lower() for line in license_lines):
            license_name = "Standard Unity Asset Store EULA"
        license_snapshot = str(result.get("license_snapshot", "")).strip()
        if not license_snapshot and license_name:
            license_snapshot = f"License type: {license_name}"
        if not license_snapshot and license_lines:
            license_snapshot = license_lines[0]
        ownership_lines = _matching_page_lines(
            lines,
            ("you purchased this item", "open in unity", "add to my assets", "my assets", "owned"),
        )
        visible_actions = _matching_page_lines(lines, ("open in unity", "add to my assets", "my assets", "download"), limit=12)
        purchased = bool(result.get("purchased", False)) or any("you purchased this item" in line.lower() for line in ownership_lines)
        open_in_unity = bool(result.get("openInUnity", False)) or any("open in unity" in line.lower() for line in ownership_lines + visible_actions)
        add_to_my_assets = bool(result.get("addToMyAssets", False)) or any(
            "add to my assets" in line.lower() for line in ownership_lines + visible_actions
        )

        if publisher and not str(result.get("publisher", "")).strip():
            result["publisher"] = publisher
        if version and not str(result.get("version", "")).strip():
            result["version"] = version
        if license_name and not str(result.get("license", "")).strip():
            result["license"] = license_name
        if license_snapshot and not str(result.get("license_snapshot", "")).strip():
            result["license_snapshot"] = license_snapshot
        if purchased:
            result["purchased"] = True
        if open_in_unity:
            result["openInUnity"] = True
        if add_to_my_assets:
            result["addToMyAssets"] = True
        if license_lines and not _has_text_values(result.get("license_lines")):
            result["license_lines"] = license_lines
        if ownership_lines and not _has_text_values(result.get("ownership_lines")):
            result["ownership_lines"] = ownership_lines
        if visible_actions and not _has_text_values(result.get("visible_actions")):
            result["visible_actions"] = visible_actions

        if publisher and not str(provider_evidence.get("publisher", "")).strip():
            provider_evidence["publisher"] = publisher
        if version and not str(provider_evidence.get("version", "")).strip():
            provider_evidence["version"] = version
        if license_name and not str(provider_evidence.get("license", "")).strip():
            provider_evidence["license"] = license_name
        if license_snapshot and not str(provider_evidence.get("license_snapshot", "")).strip():
            provider_evidence["license_snapshot"] = license_snapshot
        if purchased:
            provider_evidence["purchased"] = True
        if open_in_unity:
            provider_evidence["openInUnity"] = True
        if add_to_my_assets:
            provider_evidence["addToMyAssets"] = True

    if "license_lines" in result:
        if not _has_text_values(provider_evidence.get("license_lines")):
            provider_evidence["license_lines"] = _coerce_text_list(result.get("license_lines"))
    if "ownership_lines" in result:
        if not _has_text_values(provider_evidence.get("ownership_lines")):
            provider_evidence["ownership_lines"] = _coerce_text_list(result.get("ownership_lines"))
    if "visible_actions" in result:
        if not _has_text_values(provider_evidence.get("visible_actions")):
            provider_evidence["visible_actions"] = _coerce_text_list(result.get("visible_actions"))

    if provider_evidence:
        result["provider_evidence"] = provider_evidence
    return result


def _capture_browser_page_metadata(page, *, adapter: str, product_id: str = "") -> dict[str, object]:
    page_text = _capture_page_text(page)
    try:
        title = str(page.title() or "").strip()
    except Exception:
        title = ""

    try:
        metadata = page.evaluate(
            """
            ({ adapter, productId }) => {
                const normalize = (value) => String(value || "").replace(/\\s+/g, " ").trim();
                const uniqueValues = (items, limit = 12) => {
                    const seen = new Set();
                    const result = [];
                    for (const item of items || []) {
                        const text = normalize(item);
                        if (!text) {
                            continue;
                        }
                        const lowered = text.toLowerCase();
                        if (seen.has(lowered)) {
                            continue;
                        }
                        seen.add(lowered);
                        result.push(text);
                        if (result.length >= limit) {
                            break;
                        }
                    }
                    return result;
                };
                const firstText = (selectors) => {
                    for (const selector of selectors) {
                        try {
                            const element = document.querySelector(selector);
                            const text = normalize(element?.textContent || "");
                            if (text) {
                                return text;
                            }
                        } catch (_error) {
                        }
                    }
                    return "";
                };
                const firstAction = (tokens) => {
                    const loweredTokens = tokens.map((item) => normalize(item).toLowerCase()).filter(Boolean);
                    const actionNodes = Array.from(document.querySelectorAll("button, a[role='button'], [data-testid*='button']"));
                    for (const node of actionNodes) {
                        const text = normalize(node?.textContent || "");
                        const lowered = text.toLowerCase();
                        if (text && loweredTokens.some((token) => lowered.includes(token))) {
                            return text;
                        }
                    }
                    return "";
                };
                const rawBody = String(document.body?.innerText || "");
                const lines = rawBody
                    .replace(/\\r/g, "")
                    .split(/\\n+/)
                    .map(normalize)
                    .filter(Boolean);
                const body = lines.join("\\n");
                const matchingLines = (tokens, limit = 8) => {
                    const loweredTokens = tokens.map((item) => normalize(item).toLowerCase()).filter(Boolean);
                    return uniqueValues(
                        lines.filter((line) => {
                            const lowered = line.toLowerCase();
                            return loweredTokens.some((token) => lowered.includes(token));
                        }),
                        limit
                    );
                };
                const visibleActions = (limit = 12) => uniqueValues(
                    Array.from(document.querySelectorAll("button, a[role='button'], [data-testid*='button']"))
                        .map((node) => normalize(node?.textContent || "")),
                    limit
                );
                const pickLabeledValue = (labels) => {
                    const normalizedLabels = labels.map((item) => normalize(item).toLowerCase());
                    for (let index = 0; index < lines.length; index += 1) {
                        const line = lines[index];
                        const lowered = line.toLowerCase();
                        for (const label of normalizedLabels) {
                            if (!label) {
                                continue;
                            }
                            if (lowered.startsWith(label + ":")) {
                                return normalize(line.slice(label.length + 1));
                            }
                            if (lowered === label && index + 1 < lines.length) {
                                return lines[index + 1];
                            }
                        }
                    }
                    return "";
                };
                const snippetAround = (labels) => {
                    const loweredLabels = labels.map((item) => normalize(item).toLowerCase()).filter(Boolean);
                    for (const line of lines) {
                        const lowered = line.toLowerCase();
                        if (loweredLabels.some((label) => lowered.includes(label))) {
                            return line;
                        }
                    }
                    return "";
                };

                const payload = {
                    url: window.location.href,
                    title: firstText(["h1", "[data-testid*='title']", "[class*='title']"]) || document.title || "",
                };

                if (adapter === "fab") {
                    payload.seller = firstText([
                        "a[href*='/publishers/']",
                        "a[href*='/seller/']",
                        "a[href*='/sellers/']",
                        "[data-testid*='seller'] a",
                        "[data-testid*='publisher'] a",
                        "[class*='seller'] a",
                        "[class*='publisher'] a"
                    ]) || pickLabeledValue(["Publisher", "Seller", "Creator"]);
                    payload.license = pickLabeledValue(["License", "License terms", "Selected license"]);
                    payload.license_snapshot = snippetAround(["license", "fab standard license", "creative commons", "cc-by", "cc0"]);
                    payload.download_action = firstAction(["download", "export"]);
                    payload.claim_action = firstAction(["add to my library", "add to library", "claim"]);
                    payload.ownership_action = firstAction(["owned", "in library", "view in library"]);
                    payload.license_lines = matchingLines(["license", "fab standard license", "creative commons", "cc-by", "cc0"]);
                    payload.ownership_lines = matchingLines([
                        "owned",
                        "in library",
                        "view in library",
                        "add to my library",
                        "add to library",
                        "claim",
                        "download",
                        "export",
                    ]);
                    payload.visible_actions = visibleActions();
                    payload.provider_evidence = {
                        "product_id": productId || "",
                        "license_lines": payload.license_lines,
                        "ownership_lines": payload.ownership_lines,
                        "visible_actions": payload.visible_actions,
                    };
                } else if (adapter === "unity_asset_store") {
                    payload.publisher = firstText([
                        "a[href*='/publishers/']",
                        "[data-testid*='publisher'] a",
                        "[class*='publisher'] a",
                        "[class*='publisher-name']"
                    ]) || pickLabeledValue(["Publisher"]);
                    payload.version = pickLabeledValue(["Latest version", "Version"]);
                    payload.license = pickLabeledValue(["License type", "License"]) || (
                        body.toLowerCase().includes("standard unity asset store eula")
                            ? "Standard Unity Asset Store EULA"
                            : ""
                    );
                    payload.license_snapshot = snippetAround(["license type", "standard unity asset store eula", "eula"]);
                    let storageOwned = false;
                    try {
                        for (let i = 0; i < localStorage.length; i += 1) {
                            const key = localStorage.key(i) || "";
                            if (!key.startsWith("myAssets-")) {
                                continue;
                            }
                            const raw = localStorage.getItem(key) || "";
                            if (productId && raw.includes(`"${productId}"`)) {
                                storageOwned = true;
                                break;
                            }
                        }
                    } catch (_error) {
                        storageOwned = false;
                    }
                    payload.purchased = body.toLowerCase().includes("you purchased this item");
                    payload.openInUnity = body.toLowerCase().includes("open in unity");
                    payload.addToMyAssets = body.toLowerCase().includes("add to my assets");
                    payload.myAssetsContainsProduct = storageOwned;
                    payload.license_lines = matchingLines(["license type", "standard unity asset store eula", "license", "eula"]);
                    payload.ownership_lines = matchingLines([
                        "you purchased this item",
                        "open in unity",
                        "add to my assets",
                        "my assets",
                        "owned",
                    ]);
                    payload.visible_actions = visibleActions();
                    payload.provider_evidence = {
                        "product_id": productId || "",
                        "license_lines": payload.license_lines,
                        "ownership_lines": payload.ownership_lines,
                        "visible_actions": payload.visible_actions,
                    };
                } else if (adapter === "mixamo" || adapter === "mixamo_animations") {
                    payload.vendor = firstText(["header a[href*='mixamo']", "header img[alt*='Mixamo']"]) || "Mixamo";
                }

                return payload;
            }
            """,
            {"adapter": str(adapter or "").strip().lower(), "productId": str(product_id or "")},
        )
    except Exception:
        metadata = {}

    if not isinstance(metadata, dict):
        metadata = {}
    result = _augment_browser_metadata_from_page_text(
        {str(key): value for key, value in metadata.items()},
        adapter=adapter,
        product_id=product_id,
        page_text=page_text,
    )
    if page_text:
        result["page_text_excerpt"] = page_text[:8000]
    if title and not str(result.get("title", "")).strip():
        result["title"] = title
    return result


def _build_mixamo_character_playwright_steps(job: dict) -> list[dict[str, object]]:
    search_terms = _job_search_terms(job)
    query = search_terms[0] if search_terms else "roman gladiator"
    destination = str(job.get("destination", manual_drop_dir() / job.get("pack_id", "mixamo_download")))
    pack_id = str(job.get("pack_id", "mixamo_character")).strip() or "mixamo_character"
    result_text = str(job.get("result_text", "")).strip()
    if result_text:
        safe_result_text = result_text.replace('"', '\\"')
        result_selector = f'text="{safe_result_text}"'
        result_note = f"Open the Mixamo result card for {result_text}"
    else:
        result_selector = "p.text-capitalize"
        result_note = "Open the first visible Mixamo character result"
    search_url = f"https://www.mixamo.com/#/?page=1&type=Character&query={quote_plus(query)}"
    return [
        {
            "action": "navigate",
            "params": {"url": search_url},
            "note": f"Open Mixamo character search: {query}",
        },
        {
            "action": "wait",
            "params": {"ms": 4000},
            "note": "Wait for Mixamo character results to load",
        },
        {
            "action": "screenshot",
            "params": {},
            "note": "Capture Mixamo character search results",
        },
        {
            "action": "click",
            "params": {"selector": result_selector},
            "note": result_note,
        },
        {
            "action": "click",
            "params": {"selector": "[role='dialog'] button:contains('Use This Character')"},
            "note": "Accept the Mixamo replace-character modal when a different preview body is already loaded",
            "optional": True,
        },
        {
            "action": "wait",
            "params": {"ms": 2500},
            "note": "Wait for the character preview page to settle",
        },
        {
            "action": "screenshot",
            "params": {},
            "note": "Capture the selected Mixamo character preview",
        },
        {
            "action": "click",
            "params": {"selector": "button:contains('Download')"},
            "note": "Open the Mixamo download dialog",
        },
        {
            "action": "click",
            "params": {"selector": "[role='dialog'] button:contains('FBX')", "timeout_ms": 5000},
            "note": "Prefer FBX export when Mixamo exposes the format option",
            "optional": True,
        },
        {
            "action": "click",
            "params": {"selector": "[role='dialog'] button:contains('With Skin')", "timeout_ms": 5000},
            "note": "Prefer With Skin export when the skin toggle is visible",
            "optional": True,
        },
        {
            "action": "click",
            "params": {"selector": "[role='dialog'] button:contains('T-Pose')", "timeout_ms": 5000},
            "note": "Prefer T-pose export when Mixamo exposes the pose option",
            "optional": True,
        },
        {
            "action": "click",
            "params": {"selector": "[role='dialog'] button:contains('Download'), button:contains('Download')"},
            "note": "Confirm the Mixamo character download even if Mixamo keeps the action on the page instead of a modal",
        },
        {
            "action": "download",
            "params": {"dest_dir": destination, "rename_hint": pack_id.lower()},
            "note": f"Save the character FBX into {destination}",
        },
        {
            "action": "note",
            "params": {},
            "note": "Record the final Mixamo product page URL and exact filename in provenance.",
        },
    ]


def _build_mixamo_animation_playwright_steps(job: dict) -> list[dict[str, object]]:
    search_terms = _job_search_terms(job) or ["combat idle"]
    destination = str(job.get("destination", manual_drop_dir() / job.get("pack_id", "mixamo_anim")))
    pack_id = str(job.get("pack_id", "mixamo_animation")).strip() or "mixamo_animation"
    steps: list[dict[str, object]] = [
        {
            "action": "navigate",
            "params": {"url": "https://www.mixamo.com/"},
            "note": "Open Mixamo with the saved Adobe session",
        },
        {
            "action": "wait",
            "params": {"ms": 3000},
            "note": "Wait for the Mixamo home screen to load",
        },
        {
            "action": "click",
            "params": {"selector": "button:contains('Animations'), [role='tab']:contains('Animations')"},
            "note": "Switch to the Animations tab if Mixamo opens on characters first",
            "optional": True,
        },
    ]

    for index, query in enumerate(search_terms, start=1):
        hint = _slugify_hint(query, f"clip_{index:02d}")
        search_url = f"https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack&query={quote_plus(query)}"
        steps.extend(
            [
                {
                    "action": "navigate",
                    "params": {"url": search_url},
                    "note": f"Search Mixamo animations for: {query}",
                },
                {
                    "action": "wait",
                    "params": {"ms": 3500},
                    "note": "Wait for Mixamo animation results to load",
                },
                {
                    "action": "screenshot",
                    "params": {},
                    "note": f"Capture Mixamo animation results for query {index}",
                },
                {
                    "action": "click",
                    "params": {
                        "selector": "a[href*='type=Motion'], [class*='product'] a, [class*='card'] a"
                    },
                    "note": f"Open the first matching animation for: {query}",
                },
                {
                    "action": "wait",
                    "params": {"ms": 2500},
                    "note": "Wait for the animation preview page to settle",
                },
                {
                    "action": "click",
                    "params": {"selector": "button:contains('Download')"},
                    "note": "Open the Mixamo animation download dialog",
                },
                {
                    "action": "click",
                    "params": {"selector": "[role='dialog'] button:contains('FBX')"},
                    "note": "Prefer FBX export when Mixamo exposes the format option",
                    "optional": True,
                },
                {
                    "action": "click",
                    "params": {"selector": "[role='dialog'] button:contains('Without Skin')"},
                    "note": "Prefer animation-only export when the skin toggle is visible",
                    "optional": True,
                },
                {
                    "action": "click",
                    "params": {"selector": "[role='dialog'] button:contains('30 FPS')"},
                    "note": "Prefer 30 FPS export when Mixamo exposes the FPS option",
                    "optional": True,
                },
                {
                    "action": "click",
                    "params": {"selector": "[role='dialog'] button:contains('Download'), button:contains('Download')"},
                    "note": "Confirm the Mixamo animation download even if Mixamo keeps the action on the page instead of a modal",
                },
                {
                    "action": "download",
                    "params": {
                        "dest_dir": destination,
                        "rename_hint": f"{pack_id.lower()}_{hint}",
                    },
                    "note": f"Save the animation FBX into {destination}",
                },
                {
                    "action": "note",
                    "params": {},
                    "note": f"Record the final Mixamo animation page URL for '{query}' in provenance.",
                },
            ]
        )

    return steps


def _build_fab_playwright_steps(job: dict) -> list[dict[str, object]]:
    source_url = str(job.get("source_url", "https://www.fab.com/")).strip() or "https://www.fab.com/"
    search_terms = _job_search_terms(job)
    query = search_terms[0] if search_terms else "roman"
    destination = str(job.get("destination", manual_drop_dir() / job.get("pack_id", "fab_download")))
    pack_id = str(job.get("pack_id", "fab_pack")).strip() or "fab_pack"
    listing_mode = "/listings/" in source_url
    entry_url = source_url if listing_mode else f"https://www.fab.com/search?q={quote_plus(query)}&priceMax=0"

    steps: list[dict[str, object]] = [
        {
            "action": "navigate",
            "params": {"url": entry_url},
            "note": "Open the Fab listing page" if listing_mode else f"Search Fab for: {query}",
        },
        {
            "action": "wait",
            "params": {"ms": 3000},
            "note": "Wait for the Fab page to load",
        },
        {
            "action": "screenshot",
            "params": {},
            "note": "Capture the Fab page before taking action",
        },
    ]

    if not listing_mode:
        steps.extend(
            [
                {
                    "action": "click",
                    "params": {"selector": "a[href*='/listings/']"},
                    "note": "Open the first matching Fab listing",
                },
                {
                    "action": "wait",
                    "params": {"ms": 2500},
                    "note": "Wait for the Fab listing detail page to load",
                },
                {
                    "action": "screenshot",
                    "params": {},
                    "note": "Capture the chosen Fab listing detail page",
                },
            ]
        )

    steps.extend(
        [
            {
                "action": "click",
                "params": {
                    "selector": "button:contains('Download'), button:contains('Add to My Library'), button:contains('Get for Free'), a:contains('Download'), a:contains('Get for Free')"
                },
                "note": "Try the main Fab action button for the chosen listing",
                "optional": True,
            },
            {
                "action": "download",
                "params": {"dest_dir": destination, "rename_hint": pack_id.lower()},
                "note": f"Save any direct Fab file download into {destination}",
                "optional": True,
            },
            {
                "action": "screenshot",
                "params": {},
                "note": "Capture the Fab listing after the claim or download attempt",
                "optional": True,
            },
            {
                "action": "note",
                "params": {},
                "note": "If Fab only exposes Add to My Library, keep the listing URL and route the actual payload through fab-download or Epic acquisition fallback.",
            },
        ]
    )
    return steps


def _build_unity_asset_store_playwright_steps(job: dict) -> list[dict[str, object]]:
    source_url = str(job.get("source_url", "https://assetstore.unity.com/")).strip() or "https://assetstore.unity.com/"
    search_terms = _job_search_terms(job)
    query = search_terms[0] if search_terms else "unity asset"
    destination = str(job.get("destination", manual_drop_dir() / job.get("pack_id", "unity_download")))
    listing_mode = "/packages/" in source_url
    entry_url = source_url if listing_mode else f"https://assetstore.unity.com/?q={quote_plus(query)}&orderBy=1&free=true"

    steps: list[dict[str, object]] = [
        {
            "action": "navigate",
            "params": {"url": entry_url},
            "note": "Open the Unity Asset Store listing" if listing_mode else f"Search Unity Asset Store for: {query}",
        },
        {
            "action": "wait",
            "params": {"ms": 3500},
            "note": "Wait for the Unity Asset Store page to load",
        },
        {
            "action": "screenshot",
            "params": {},
            "note": "Capture the Unity Asset Store page before taking action",
        },
        {
            "action": "click",
            "params": {
                "selector": "button:contains('Accept All Cookies'), button:contains('Accept Cookies')",
                "timeout_ms": 4000,
            },
            "note": "Accept the cookie banner if Unity shows it",
            "optional": True,
        },
    ]

    if not listing_mode:
        steps.extend(
            [
                {
                    "action": "click",
                    "params": {"selector": "a[href*='/packages/']"},
                    "note": "Open the first matching Unity Asset Store listing",
                },
                {
                    "action": "wait",
                    "params": {"ms": 2500},
                    "note": "Wait for the Unity Asset Store listing page to settle",
                },
                {
                    "action": "screenshot",
                    "params": {},
                    "note": "Capture the chosen Unity Asset Store listing",
                },
            ]
        )

    steps.extend(
        [
            {
                "action": "click",
                "params": {
                    "selector": "button:contains('Add to My Assets'), button:contains('Add to My Assets Free'), a:contains('Add to My Assets'), button:contains('Open in Unity'), a:contains('Open in Unity')"
                },
                "note": "Try the main Unity Asset Store claim button for the chosen free listing",
            },
            {
                "action": "wait",
                "params": {"ms": 2500},
                "note": "Wait for the Unity Asset Store claim flow to complete",
            },
            {
                "action": "click",
                "params": {"selector": "button:contains('Continue with Google')", "timeout_ms": 5000},
                "note": "Continue with Google if Unity redirects to the sign-in wall",
                "optional": True,
            },
            {
                "action": "wait",
                "params": {"ms": 2500},
                "note": "Wait for the Google account chooser to appear",
                "optional": True,
            },
            {
                "action": "click",
                "params": {
                    "selector": "div[data-email], li:has-text('@'), div[role='link']:has-text('@')",
                    "timeout_ms": 7000,
                },
                "note": "Choose the already signed-in Google account if Google shows the account chooser",
                "optional": True,
            },
            {
                "action": "wait",
                "params": {"ms": 2500},
                "note": "Wait for the Google consent step to appear",
                "optional": True,
            },
            {
                "action": "click",
                "params": {
                    "selector": "button:contains('Continue'), [role='button']:contains('Continue')",
                    "timeout_ms": 7000,
                },
                "note": "Approve the Google consent step if Unity asks for it",
                "optional": True,
            },
            {
                "action": "wait",
                "params": {"ms": 6000},
                "note": "Wait for Unity to return to the asset page after Google consent",
                "optional": True,
            },
            {
                "action": "screenshot",
                "params": {},
                "note": "Capture the Unity Asset Store listing after the claim attempt",
            },
            {
                "action": "note",
                "params": {},
                "note": f"If the listing was added successfully, the actual package download and import happen later through Unity Hub or Package Manager. Preserve source URL and package details for {destination}.",
            },
        ]
    )
    return steps


ADAPTER_STRUCTURED_STEP_BUILDERS: dict[str, object] = {
    "mixamo": _build_mixamo_character_playwright_steps,
    "mixamo_animations": _build_mixamo_animation_playwright_steps,
    "fab": _build_fab_playwright_steps,
    "unity_asset_store": _build_unity_asset_store_playwright_steps,
}


def build_structured_playwright_steps(job: dict) -> list[dict[str, object]]:
    adapter = str(job.get("source_adapter", "")).strip()
    builder = ADAPTER_STRUCTURED_STEP_BUILDERS.get(adapter)
    if builder is None:
        return []
    return list(builder(job))


def _structured_steps(job: dict) -> list[dict[str, object]]:
    steps = job.get("playwright_steps")
    if isinstance(steps, list):
        return [dict(step) for step in steps if isinstance(step, dict)]
    return []


def _unique_output_path(dest_dir: Path, rename_hint: str, suggested_filename: str) -> Path:
    suffix = Path(suggested_filename or "").suffix or ".bin"
    base_name = rename_hint or Path(suggested_filename or "download").stem or "download"
    candidate = dest_dir / f"{base_name}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = dest_dir / f"{base_name}_{counter:02d}{suffix}"
        counter += 1
    return candidate


def _execute_structured_playwright_job(
    *,
    job: dict,
    spec_path: Path,
    browser_profile_dir: Path,
    headed: bool,
    timeout_ms: int,
) -> dict[str, object]:
    from playwright.sync_api import Error, TimeoutError, sync_playwright

    steps = _structured_steps(job)
    if not steps:
        raise RuntimeError(
            "This job spec is plan-only. Real Playwright execution currently requires a job with structured `playwright_steps`."
        )

    artifacts_dir = _artifacts_dir_for_job(spec_path, job)
    downloads_dir = artifacts_dir / "downloads"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    browser_profile_dir.mkdir(parents=True, exist_ok=True)

    step_log: list[dict[str, object]] = []
    pending_download = None
    last_url = ""
    auth_state_path = _existing_auth_state_path(job)
    execution_mode = "playwright_structured"
    execution_error = ""

    with sync_playwright() as playwright:
        browser = None
        if auth_state_path is not None and _should_use_storage_state(job):
            browser = playwright.chromium.launch(headless=not headed)
            context = browser.new_context(
                accept_downloads=True,
                storage_state=str(auth_state_path),
            )
        else:
            launch_kwargs: dict[str, object] = {
                "user_data_dir": str(browser_profile_dir),
                "headless": not headed,
                "accept_downloads": True,
                "downloads_path": str(downloads_dir),
            }
            if str(job.get("source_adapter", "")).strip().lower() == "unity_asset_store":
                launch_kwargs["channel"] = "chrome"
                launch_kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
                launch_kwargs["user_agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                )
            context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                """
            )

            for index, step in enumerate(steps, start=1):
                action = str(step.get("action", "")).strip().lower()
                params = step.get("params", {})
                if not isinstance(params, dict):
                    params = {}
                step_timeout_ms = int(params.get("timeout_ms", timeout_ms))
                note = str(step.get("note", "")).strip()
                optional = bool(step.get("optional", False))

                entry: dict[str, object] = {
                    "index": index,
                    "action": action,
                    "note": note,
                    "status": "completed",
                    "optional": optional,
                }

                try:
                    if action == "navigate":
                        url = str(params.get("url", "")).strip()
                        page.goto(url, wait_until="domcontentloaded", timeout=step_timeout_ms)
                        last_url = page.url
                    elif action == "screenshot":
                        screenshot_path = artifacts_dir / f"step_{index:02d}.png"
                        try:
                            page.screenshot(
                                path=str(screenshot_path),
                                full_page=True,
                                timeout=step_timeout_ms,
                                animations="disabled",
                            )
                        except (TimeoutError, Error) as exc:
                            entry["screenshot_warning"] = str(exc)
                            try:
                                page.screenshot(
                                    path=str(screenshot_path),
                                    full_page=False,
                                    timeout=min(step_timeout_ms, 5000),
                                    animations="disabled",
                                )
                                entry["screenshot_fallback"] = "viewport"
                            except (TimeoutError, Error) as fallback_exc:
                                entry["screenshot_error"] = str(fallback_exc)
                        entry["screenshot"] = str(screenshot_path)
                    elif action == "click":
                        if (
                            str(job.get("source_adapter", "")).strip().lower() == "unity_asset_store"
                            and not headed
                            and _is_unity_claim_click_step(step)
                        ):
                            unity_product_id = _extract_unity_asset_id(job)
                            pre_claim_state = _unity_page_claim_state(page, unity_product_id)
                            if pre_claim_state:
                                entry["unity_page_claim_state_before"] = pre_claim_state
                            if (
                                bool(pre_claim_state.get("purchased", False))
                                or bool(pre_claim_state.get("openInUnity", False))
                                or bool(pre_claim_state.get("myAssetsContainsProduct", False))
                            ):
                                entry["status"] = "skipped_already_owned"
                                step_log.append(entry)
                                continue
                            try:
                                claim_probe = UnityAuthSession.claim_probe(
                                    context,
                                    page,
                                    unity_product_id,
                                )
                            except Exception as exc:
                                claim_probe = {}
                                entry["unity_claim_probe_error"] = str(exc)
                            entry["unity_claim_probe"] = claim_probe
                            if isinstance(claim_probe, dict) and claim_probe.get("user_entitled", False):
                                entry["status"] = "skipped_already_owned"
                                step_log.append(entry)
                                continue
                        selector = _normalize_selector(str(params.get("selector", "")).strip())
                        if not selector:
                            raise RuntimeError("click step is missing selector")
                        locator = page.locator(selector).first
                        force_click = bool(params.get("force", False))
                        expects_download = index < len(steps) and str(steps[index].get("action", "")).strip().lower() == "download"
                        if expects_download:
                            with page.expect_download(timeout=step_timeout_ms) as download_info:
                                locator.click(timeout=step_timeout_ms, force=force_click)
                            pending_download = download_info.value
                        else:
                            locator.click(timeout=step_timeout_ms, force=force_click)
                        last_url = page.url
                    elif action in {"type", "fill"}:
                        text = str(params.get("text", ""))
                        selector = _normalize_selector(str(params.get("selector", "")).strip())
                        if selector:
                            locator = page.locator(selector).first
                            if action == "fill":
                                locator.fill(text, timeout=step_timeout_ms)
                            else:
                                locator.click(timeout=step_timeout_ms)
                                locator.fill("", timeout=step_timeout_ms)
                                locator.type(text, timeout=step_timeout_ms)
                        else:
                            page.keyboard.type(text)
                        last_url = page.url
                    elif action == "wait":
                        page.wait_for_timeout(int(params.get("ms", 1000)))
                    elif action == "download":
                        dest_dir = Path(str(params.get("dest_dir", downloads_dir))).resolve()
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        rename_hint = str(params.get("rename_hint", "")).strip()
                        dom_attr = str(params.get("dom_attr", "")).strip()
                        dom_selector = _normalize_selector(str(params.get("dom_selector", "")).strip())
                        if dom_attr and dom_selector:
                            locator = page.locator(dom_selector).first
                            raw_value = locator.get_attribute(dom_attr, timeout=step_timeout_ms)
                            if not raw_value:
                                raise RuntimeError(
                                    f"download step could not read attribute '{dom_attr}' from selector '{dom_selector}'"
                                )
                            source_url = urljoin(page.url, raw_value)
                            path_bits = urlparse(source_url).path.rstrip("/").split("/")
                            suggested_filename = path_bits[-1] if path_bits else "download.bin"
                            output_path = _unique_output_path(dest_dir, rename_hint, suggested_filename)
                            _download_url_to_file(source_url, output_path, timeout_ms=step_timeout_ms)
                            entry["download_source_url"] = source_url
                        else:
                            if pending_download is None:
                                pending_download = page.wait_for_event("download", timeout=step_timeout_ms)
                            output_path = _unique_output_path(dest_dir, rename_hint, pending_download.suggested_filename)
                            pending_download.save_as(str(output_path))
                            pending_download = None
                        entry["download_path"] = str(output_path)
                    elif action == "navigate_back":
                        page.go_back(wait_until="domcontentloaded", timeout=step_timeout_ms)
                        last_url = page.url
                    elif action == "note":
                        pass
                    else:
                        raise RuntimeError(f"Unsupported Playwright action '{action}'")
                except (TimeoutError, Error, RuntimeError) as exc:
                    entry["status"] = "skipped_optional" if optional else "failed"
                    entry["error"] = str(exc)
                    step_log.append(entry)
                    if optional:
                        continue
                    raise

                step_log.append(entry)

            if str(job.get("source_adapter", "")).strip().lower() == "unity_asset_store":
                unity_claim_state = _unity_page_claim_state(page, _extract_unity_asset_id(job))
                if isinstance(unity_claim_state, dict):
                    (artifacts_dir / "unity_claim_state.json").write_text(
                        json.dumps(unity_claim_state, indent=2),
                        encoding="utf-8",
                    )
                    final_url = str(unity_claim_state.get("url") or page.url)
                    last_url = final_url or last_url
                    if (
                        not bool(unity_claim_state.get("purchased", False))
                        and not bool(unity_claim_state.get("openInUnity", False))
                        and not bool(unity_claim_state.get("myAssetsContainsProduct", False))
                        and (
                            "accounts.google.com" in final_url
                            or "login.unity.com" in final_url
                            or bool(unity_claim_state.get("addToMyAssets", False))
                        )
                    ):
                        execution_mode = "interactive_required"
                        if not execution_error:
                            execution_error = (
                                "Unity Asset Store claim did not complete; the flow still requires an interactive "
                                "account/consent step."
                            )

            adapter_id = str(job.get("source_adapter", "")).strip().lower()
            page_text = _capture_page_text(page)
            if page_text:
                (artifacts_dir / "page_text.txt").write_text(page_text, encoding="utf-8")
            evidence_paths = _write_browser_evidence_files(page, artifacts_dir=artifacts_dir, page_text=page_text)
            page_metadata = _capture_browser_page_metadata(
                page,
                adapter=adapter_id,
                product_id=_extract_unity_asset_id(job) if adapter_id == "unity_asset_store" else "",
            )
            if adapter_id == "unity_asset_store" and isinstance(unity_claim_state, dict):
                page_metadata.setdefault("purchased", bool(unity_claim_state.get("purchased", False)))
                page_metadata.setdefault("openInUnity", bool(unity_claim_state.get("openInUnity", False)))
                page_metadata.setdefault("addToMyAssets", bool(unity_claim_state.get("addToMyAssets", False)))
                page_metadata.setdefault(
                    "myAssetsContainsProduct",
                    bool(unity_claim_state.get("myAssetsContainsProduct", False)),
                )
            dom_metadata_path_text = str(evidence_paths.get("page_dom_metadata_path", "")).strip()
            if dom_metadata_path_text:
                dom_metadata_path = Path(dom_metadata_path_text)
                if dom_metadata_path.exists():
                    try:
                        dom_metadata_payload = json.loads(dom_metadata_path.read_text(encoding="utf-8"))
                    except Exception:
                        dom_metadata_payload = {}
                    if isinstance(dom_metadata_payload, dict):
                        for key in ("license_lines", "ownership_lines", "visible_actions"):
                            if key in dom_metadata_payload and not _has_text_values(page_metadata.get(key)):
                                page_metadata[key] = _coerce_text_list(dom_metadata_payload.get(key))
                        provider_evidence = (
                            dict(page_metadata.get("provider_evidence", {}))
                            if isinstance(page_metadata.get("provider_evidence"), dict)
                            else {}
                        )
                        for key in ("license_lines", "ownership_lines", "visible_actions"):
                            if key in dom_metadata_payload and not _has_text_values(provider_evidence.get(key)):
                                provider_evidence[key] = _coerce_text_list(dom_metadata_payload.get(key))
                        if provider_evidence:
                            page_metadata["provider_evidence"] = provider_evidence
            screenshot_meta_path_text = str(evidence_paths.get("page_screenshot_meta_path", "")).strip()
            if screenshot_meta_path_text:
                screenshot_meta_path = Path(screenshot_meta_path_text)
                if screenshot_meta_path.exists():
                    try:
                        screenshot_meta_payload = json.loads(screenshot_meta_path.read_text(encoding="utf-8"))
                    except Exception:
                        screenshot_meta_payload = {}
                    if (
                        isinstance(screenshot_meta_payload, dict)
                        and screenshot_meta_payload
                        and (
                            not isinstance(page_metadata.get("page_screenshot_meta"), dict)
                            or not page_metadata.get("page_screenshot_meta")
                        )
                    ):
                        page_metadata["page_screenshot_meta"] = screenshot_meta_payload
            if page_metadata:
                page_metadata_path = artifacts_dir / "page_metadata.json"
                page_metadata_path.write_text(json.dumps(page_metadata, indent=2), encoding="utf-8")

            execution_log_path = artifacts_dir / "execution_log.json"
            execution_log_path.write_text(json.dumps(step_log, indent=2), encoding="utf-8")
            result = {
                "artifacts_dir": artifacts_dir,
                "execution_mode": execution_mode,
                "last_url": last_url or page.url,
                "step_log_path": execution_log_path,
            }
            if page_metadata:
                result["page_metadata"] = page_metadata
                result["page_metadata_path"] = str(artifacts_dir / "page_metadata.json")
            result.update(evidence_paths)
            if str(job.get("source_adapter", "")).strip().lower() == "unity_asset_store":
                result["unity_claim_state"] = unity_claim_state if isinstance(unity_claim_state, dict) else {}
            if execution_error:
                result["error"] = execution_error
            return result
        finally:
            context.close()
            if browser is not None:
                browser.close()


# ---------------------------------------------------------------------------
# run_browser_job — generic job spec execution
# ---------------------------------------------------------------------------

def run_browser_job(
    job_spec_path: str | Path,
    *,
    dry_run: bool = False,
    execute: bool = False,
    headed: bool = True,
    browser_profile_dir: str | Path | None = None,
    timeout_ms: int = 15000,
    retries: int = 1,
) -> BrowserRunResult:
    """
    Emit, preview, or execute a browser automation job from a spec JSON file.
    """
    spec_path = Path(job_spec_path)
    if not spec_path.exists():
        raise FileNotFoundError(f"Browser job spec not found: {spec_path}")

    job = json.loads(spec_path.read_text(encoding="utf-8"))
    source_adapter = job.get("source_adapter", "unknown")
    pack_id = job.get("pack_id", "unknown")
    download_target = Path(job.get("destination", ""))
    deterministic_artifacts_dir = _artifacts_dir_for_job(spec_path, job)

    structured_steps = _structured_steps(job)
    steps = [step.get("note", step.get("action", "")) for step in structured_steps] if structured_steps else _build_steps(job)

    mode = "DRY RUN" if dry_run else "PLAN"
    print(f"[{mode}] Browser job: {source_adapter} -> {pack_id}")
    print(f"Source URL : {_console_safe_text(job.get('source_url', '<none>'))}")
    print(f"Search     : {_console_safe_text(', '.join(job.get('search_terms', [])))}")
    print(f"Destination: {_console_safe_text(download_target)}")
    print(f"Artifacts  : {_console_safe_text(deterministic_artifacts_dir)}")
    print()
    print("=== Playwright Steps ===")
    for i, step in enumerate(steps, 1):
        print(f"  {i:2d}. {_console_safe_text(step)}")
    print()

    if retries < 1:
        raise ValueError("run_browser_job retries must be >= 1.")

    selected_profile_dir = (
        Path(browser_profile_dir).resolve()
        if browser_profile_dir is not None
        else _default_browser_profile_dir(str(source_adapter))
    )
    executed = False
    execution_mode = "plan"
    artifacts_dir: Path | None = None
    last_url = ""
    attempts = 0
    execution_error = ""
    login_required = bool(job.get("login_required", False))

    if execute and dry_run:
        raise ValueError("run_browser_job cannot use execute=True together with dry_run=True.")

    if execute:
        repair_payload = _browser_auth_repair_payload(job)
        if repair_payload is not None:
            execution_mode = "repair_required"
            execution_error = str(repair_payload.get("error", "")).strip()
            print(f">>> Browser auth repair required: {_console_safe_text(execution_error)}")
            return BrowserRunResult(
                source_adapter=source_adapter,
                pack_id=pack_id,
                job_spec_path=spec_path,
                download_target=download_target,
                steps_emitted=steps,
                dry_run=dry_run,
                executed=False,
                execution_mode=execution_mode,
                artifacts_dir=None,
                browser_profile_dir=selected_profile_dir,
                last_url="",
                attempts=0,
                error=execution_error,
                repair_command=str(repair_payload.get("repair_command", "")).strip(),
                repair_reason=str(repair_payload.get("repair_reason", "")).strip(),
                provider_runbook_id=str(repair_payload.get("provider_runbook_id", "")).strip(),
            )
        retry_errors: list[str] = []
        for attempt in range(1, retries + 1):
            attempts = attempt
            try:
                execution = _execute_structured_playwright_job(
                    job=job,
                    spec_path=spec_path,
                    browser_profile_dir=selected_profile_dir,
                    headed=headed,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc)
                retry_errors.append(error_message)
                if attempt < retries:
                    print(f">>> Playwright attempt {attempt}/{retries} failed, retrying: {_console_safe_text(error_message)}")
                    continue
                execution_mode = "failed"
                execution_error = error_message
                break

            artifacts_dir = Path(str(execution["artifacts_dir"]))
            execution_mode = str(execution.get("execution_mode", "playwright_structured"))
            last_url = str(execution.get("last_url", ""))
            execution_error = str(execution.get("error", "")).strip()
            if execution_mode == "interactive_required":
                if not execution_error:
                    execution_error = "Browser flow reached an interactive login or consent gate."
                login_hint = _interactive_login_recovery_hint(str(source_adapter))
                if login_hint and login_hint not in execution_error:
                    execution_error = f"{execution_error} {login_hint}".strip()

            should_retry = False
            if execution_mode == "failed":
                should_retry = attempt < retries
            elif execution_mode == "interactive_required" and login_required:
                should_retry = attempt < retries

            if should_retry:
                retry_reason = execution_error or f"execution_mode={execution_mode}"
                retry_errors.append(retry_reason)
                print(f">>> Playwright attempt {attempt}/{retries} returned {_console_safe_text(retry_reason)}; retrying.")
                continue

            executed = execution_mode not in {"failed", "interactive_required"}
            if not executed and not execution_error:
                execution_error = f"Browser flow ended with execution_mode='{execution_mode}'."
            break

        if retry_errors and not executed and not execution_error:
            execution_error = retry_errors[-1]

        print(f">>> Playwright executed with shared profile: {_console_safe_text(selected_profile_dir)}")
        if artifacts_dir is not None:
            print(f">>> Execution artifacts: {_console_safe_text(artifacts_dir)}")
        if execution_error:
            print(f">>> Execution result: {_console_safe_text(execution_error)}")
    elif not dry_run:
        print(">>> This command emits the browser plan only; it does not execute Playwright itself.")
        print(">>> Use --execute for structured Playwright jobs, or hand the job spec to Playwright MCP / a human operator.")

    return BrowserRunResult(
        source_adapter=source_adapter,
        pack_id=pack_id,
        job_spec_path=spec_path,
        download_target=download_target,
        steps_emitted=steps,
        dry_run=dry_run,
        executed=executed,
        execution_mode=execution_mode,
        artifacts_dir=artifacts_dir,
        browser_profile_dir=selected_profile_dir if execute else None,
        last_url=last_url,
        attempts=attempts,
        error=execution_error,
        repair_command="",
        repair_reason="",
        provider_runbook_id="",
    )


# ---------------------------------------------------------------------------
# run_mixamo_batch — direct Mixamo character or animation download
# ---------------------------------------------------------------------------

_MIXAMO_CHARACTER_PRESETS = {
    "RA_PACK_CHR_CORE_SLICE_01": {
        "search_terms": ("vanguard",),
        "result_text": "Vanguard By T. Choonyung",
        "type": "character",
        "notes": "shared male body/rig baseline — export T-pose FBX with skin",
    },
    "RA_PACK_CHR_DUELIST_SLICE_01": {
        "search_terms": ("paladin",),
        "result_text": "Paladin J Nordstrom",
        "type": "character",
        "notes": "temporary non-mock duelist fallback — replace with Roman class kit after Fab/manual sourcing",
    },
    "RA_PACK_CHR_SKIRMISHER_SLICE_01": {
        "search_terms": ("xbot",),
        "result_text": "X Bot",
        "type": "character",
        "notes": "temporary non-mock skirmisher fallback — replace with Roman class kit after Fab/manual sourcing",
    },
    "RA_PACK_CHR_SLINGER_SLICE_01": {
        "search_terms": ("erika archer",),
        "result_text": "Erika Archer",
        "type": "character",
        "notes": "temporary non-mock slinger fallback — replace with Roman class kit after Fab/manual sourcing",
    },
    "RA_PACK_ANM_COMBAT_SLICE_01": {
        "search_terms": (
            "walk run sprint idle",
            "sword shield slash",
            "javelin throw",
            "sling throw attack",
            "hit react stumble death",
            "trap react knockback",
        ),
        "type": "animation",
        "notes": "Roman combat baseline — export FBX animations without skin",
    },
}


def run_mixamo_batch(
    *,
    pack_id: str | None = None,
    search: str | None = None,
    asset_type: str = "character",
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    use_presets: bool = False,
    execute: bool = False,
    headed: bool = True,
    browser_profile_dir: str | Path | None = None,
    timeout_ms: int = 15000,
) -> list[MixamoBatchResult]:
    """
    Generate Playwright MCP steps for Mixamo character or animation downloads.

    Mixamo is free with an Adobe account. The user is already logged in.
    Characters export as FBX with skin (T-pose).
    Animations export as FBX without skin (retargetable to any humanoid).
    """
    if execute and dry_run:
        raise ValueError("run_mixamo_batch cannot use execute=True together with dry_run=True.")

    if use_presets:
        job_list = [
            {"pack_id": pid, **cfg}
            for pid, cfg in _MIXAMO_CHARACTER_PRESETS.items()
        ]
    elif pack_id and pack_id in _MIXAMO_CHARACTER_PRESETS:
        job_cfg = dict(_MIXAMO_CHARACTER_PRESETS[pack_id])
        if search:
            job_cfg["search_terms"] = (search,)
        if asset_type:
            job_cfg["type"] = asset_type
        job_list = [{"pack_id": pack_id, **job_cfg}]
    elif pack_id and search:
        job_list = [{"pack_id": pack_id, "search_terms": (search,), "type": asset_type, "notes": ""}]
    else:
        # Default: the 4 Roman first-slice character packs
        job_list = [
            {"pack_id": pid, **cfg}
            for pid, cfg in _MIXAMO_CHARACTER_PRESETS.items()
            if cfg["type"] == "character"
        ]

    results = []
    for job_cfg in job_list:
        pid = job_cfg["pack_id"]
        search_terms = tuple(str(item).strip() for item in job_cfg.get("search_terms", ()) if str(item).strip())
        if not search_terms:
            legacy_search = str(job_cfg.get("search", "")).strip()
            search_terms = (legacy_search,) if legacy_search else ()
        search_summary = " | ".join(search_terms)
        jtype = job_cfg.get("type", "character")
        notes = job_cfg.get("notes", "")

        dest = (
            Path(output_dir) if output_dir
            else manual_drop_dir() / "mixamo" / pid
        )
        dest.mkdir(parents=True, exist_ok=True)

        job_dict = {
            "source_adapter": "mixamo" if jtype == "character" else "mixamo_animations",
            "pack_id": pid,
            "game_scope": "roman_arena",
            "source_url": f"https://www.mixamo.com/#/?query={quote_plus(search_terms[0] if search_terms else 'roman gladiator')}",
            "search_terms": list(search_terms),
            "login_required": True,
            "destination": str(dest),
            "notes": [notes] if notes else [],
        }
        result_text = str(job_cfg.get("result_text", "")).strip()
        if result_text:
            job_dict["result_text"] = result_text

        steps = build_structured_playwright_steps(job_dict) or []
        step_preview = [str(step.get("note", step.get("action", ""))) for step in steps] if steps else _build_steps(job_dict)
        job_dict["playwright_steps"] = steps

        spec_path = dest / "mixamo_job.json"
        spec_path.write_text(json.dumps(job_dict, indent=2), encoding="utf-8")

        browser_result: BrowserRunResult | None = None
        if execute:
            browser_result = run_browser_job(
                spec_path,
                execute=True,
                headed=headed,
                browser_profile_dir=browser_profile_dir,
                timeout_ms=timeout_ms,
            )

        result = MixamoBatchResult(
            pack_id=pid,
            search=search_summary,
            download_target=dest,
            job_spec_path=spec_path,
            steps=steps,
            dry_run=dry_run,
            executed=browser_result.executed if browser_result else False,
            execution_mode=browser_result.execution_mode if browser_result else "plan",
            artifacts_dir=browser_result.artifacts_dir if browser_result else None,
            last_url=browser_result.last_url if browser_result else "",
        )

        mode = "DRY RUN" if dry_run else ("EXECUTED" if execute else "EXECUTION PLAN")
        print(f"\n[{mode}] Mixamo {jtype}: {pid}")
        print(f"Search: {search_summary}")
        print(f"Output: {dest}")
        if notes:
            print(f"Notes : {notes}")
        print()
        for i, step in enumerate(step_preview, 1):
            print(f"  {i:2d}. {_console_safe_text(step)}")
        if browser_result and browser_result.artifacts_dir is not None:
            print(f"Artifacts: {browser_result.artifacts_dir}")

        results.append(result)

    print(f"\nTotal Mixamo jobs: {len(results)}")
    return results
