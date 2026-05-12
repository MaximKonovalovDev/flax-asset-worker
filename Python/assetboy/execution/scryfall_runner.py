"""scryfall_runner.py — Batch-fetch CC-BY-SA card art from Scryfall.

Scryfall (scryfall.com) is a Magic: The Gathering card database with a free
public API (no key required). All card images are licensed CC-BY-SA-4.0 by
Wizards of the Coast / Scryfall. ~25K unique cards spanning 30+ years of art.

API conventions (per scryfall.com/docs/api):
    - Rate limit: 50-100 req/sec; require 50-100ms between requests (we use 100ms).
    - Send a User-Agent and Accept: application/json header.

Endpoints used:
    GET /cards/search?q=<query>&unique=art
        -> {data: [{id, name, image_uris: {png, large, normal, small, art_crop},
                    artist, set_name, ...}], has_more, ...}

CLI driver: `assetboy gen scryfall fetch --query "type:dragon" --count 6`

Use cases in FAW:
  - Fantasy art reference plates (creatures, landscapes, spells).
  - Card-game UI mood boards (frame layouts, art-crop framing).
  - ComfyUI img2img seed images for stylized fantasy work.

Image variants per card:
    png       (745x1040) full card with frame    -> good for UI mood
    large     (672x936)  full card with frame
    normal    (488x680)
    small     (146x204)
    art_crop  (varies)   art only (no frame)     -> good for img2img source
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.execution.comfyui_runner import manual_drop_dir

SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "flax-asset-worker/1.10 (CC-BY-SA collector; +https://github.com/flax-game-studio)"

_VALID_IMAGE_VARIANTS = {"png", "large", "normal", "small", "art_crop", "border_crop"}


@dataclass
class ScryfallResult:
    """Outcome of one batch query."""

    pack_id: str
    query: str
    output_dir: Path
    variant: str = "art_crop"
    cards_matched: int = 0
    cards_with_image: int = 0
    cards_downloaded: int = 0
    cards_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    """v1.12.s69: retries 429/503/502/504. 404 passes through (Scryfall
    semantics: empty-result search returns 404 by design)."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    return with_429_retry(_do_call, max_retries=3, base_delay_s=1.0, cap_delay_s=30.0)


def _download_binary(url: str, dest: Path, *, timeout: float = 30.0) -> int:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def search_scryfall_cards(
    query: str,
    *,
    unique: str = "art",
    timeout: float = 20.0,
) -> list[dict]:
    """Run /cards/search; return first page of card records (data list).

    `unique=art` returns each art only once (deduplicates reprints with same art).
    Other valid values: cards, prints. Default 'art' avoids duplicates.

    Note: this hits page 1 only; for larger result sets paginate via has_more+next_page.
    """
    params = {"q": query, "unique": unique}
    url = f"{SCRYFALL_API}/cards/search?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("data", []))


def run_scryfall_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = 6,
    variant: str = "art_crop",
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.1,
    dry_run: bool = False,
) -> ScryfallResult:
    """Search Scryfall and download card images.

    Args:
        query: Scryfall query syntax (e.g. 'type:dragon', 'art:landscape c:r').
        pack_id: pack id for output dir; default derived from query.
        count: max cards to fetch.
        variant: which image_uris variant to download (art_crop is default;
                 use 'png' for full-card with frame, 'large'/'normal' for smaller).
        output_dir: override; default <manual_drop>/scryfall/<pack_id>/.
        polite_sleep_s: delay between image downloads (Scryfall recommends 50-100ms).
        dry_run: when True, hit search but skip binary downloads.
    """
    variant = variant.strip().lower()
    if variant not in _VALID_IMAGE_VARIANTS:
        result = ScryfallResult(
            pack_id=pack_id or "INVALID",
            query=query,
            output_dir=Path(output_dir) if output_dir else Path("."),
            variant=variant,
            ok=False,
            error=f"invalid_variant: {variant!r} not in {sorted(_VALID_IMAGE_VARIANTS)}",
        )
        return result

    resolved_pack_id = pack_id or f"SCRYFALL_{query.replace(' ', '_').replace(':', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "scryfall" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ScryfallResult(
        pack_id=resolved_pack_id,
        query=query,
        output_dir=out_dir,
        variant=variant,
        dry_run=dry_run,
    )

    try:
        cards = search_scryfall_cards(query)
    except urllib.error.HTTPError as exc:
        # Scryfall returns 404 for no-match queries.
        if exc.code == 404:
            result.ok = True
            result.error = "no_matches"
            return result
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.cards_matched = len(cards)
    if not cards:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for card in cards:
        if result.cards_downloaded >= count:
            break
        if not isinstance(card, dict):
            continue

        card_id = str(card.get("id", ""))
        name = str(card.get("name", ""))
        artist = str(card.get("artist", ""))
        set_name = str(card.get("set_name", ""))
        # Two-faced cards have card_faces[*].image_uris instead of top-level.
        image_uris = card.get("image_uris") or {}
        if not image_uris:
            faces = card.get("card_faces") or []
            if faces and isinstance(faces, list) and isinstance(faces[0], dict):
                image_uris = faces[0].get("image_uris") or {}

        if not image_uris.get(variant):
            # No usable image for this variant.
            result.cards_failed += 1
            continue

        result.cards_with_image += 1
        image_url = str(image_uris[variant])

        # Sanitize filename: use card name + id suffix to disambiguate alt-arts.
        safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in name).strip()
        safe_name = safe_name.replace(" ", "_")[:60] or "card"
        suffix = ".png" if variant == "png" else ".jpg"
        filename = f"{safe_name}__{card_id[:8]}{suffix}"
        dest = out_dir / filename

        entry = {
            "card_id": card_id,
            "name": name,
            "artist": artist,
            "set_name": set_name,
            "scryfall_uri": str(card.get("scryfall_uri", "")),
            "variant": variant,
            "source_url": image_url,
            "license": "CC-BY-SA-4.0 (Scryfall card images)",
            "license_url": "https://scryfall.com/docs/api#licensing",
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.cards_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(image_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.cards_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.cards_failed += 1

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    manifest = {
        "source": "scryfall",
        "pack_id": resolved_pack_id,
        "query": query,
        "variant": variant,
        "cards_matched": result.cards_matched,
        "cards_with_image": result.cards_with_image,
        "cards_downloaded": result.cards_downloaded,
        "cards_failed": result.cards_failed,
        "license": "CC-BY-SA-4.0 (Wizards of the Coast / Scryfall)",
        "license_url": "https://scryfall.com/docs/api#licensing",
        "attribution_required": True,
        "attribution_note": (
            "Card images are CC-BY-SA-4.0. Attribute to 'Wizards of the Coast' "
            "and the original artist (see per-entry 'artist' field). "
            "Magic: The Gathering art is also subject to Wizards' fan content "
            "policy: https://company.wizards.com/en/legal/fancontentpolicy"
        ),
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "scryfall_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "SCRYFALL_API",
    "ScryfallResult",
    "search_scryfall_cards",
    "run_scryfall_batch",
]
