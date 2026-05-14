"""rawg_runner.py — Batch-fetch game cover art + screenshots from RAWG.io.

RAWG (rawg.io) is a video game database with metadata for 800K+ games.
Free API tier: 20K requests/month. Auth via query-string `?key=<key>`.

Image-license caveat: per RAWG's terms, the API returns URLs to images
hosted on their CDN (background covers from game publishers, screenshots).
THESE IMAGES ARE NOT LICENSED FOR REDISTRIBUTION — they are copyrighted
by the respective game publishers. RAWG permits API access for development
and reference/research use; commercial republication is forbidden.

>>> ASSETBOI USE POLICY (BAKED INTO MANIFEST OUTPUT):
>>>   - INTERNAL REFERENCE / IDEATION ONLY
>>>   - NOT FOR REDISTRIBUTION
>>>   - NOT FOR USE IN SHIPPED GAMES
>>>   - Acceptable: mood boards, genre studies, design analysis,
>>>     ComfyUI img2img seeds destined for transformative output.

Auth: `RAWG_API_KEY` env var. Free signup at https://rawg.io/apidocs.

API endpoints (api.rawg.io/api):
    GET /games?search=<term>&key=<key>&page_size=<n>
        -> {count, results: [{id, name, slug, background_image,
                              short_screenshots: [{id, image}], genres,
                              platforms, ...}]}
    GET /games/{id}?key=<key>
        -> {detailed_description, screenshots_count, ...}

CLI driver: `assetboy gen rawg games --query "roguelike" --count 6`
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.execution.comfyui_runner import manual_drop_dir

RAWG_API = "https://api.rawg.io/api"
USER_AGENT = "flax-asset-worker/1.10 (RAWG reference-only; +https://github.com/flax-game-studio)"
RAWG_API_KEY_ENV = "RAWG_API_KEY"

# Banner displayed in manifest + on stdout to ensure operator sees the
# non-commercial / reference-only nature.
USE_POLICY_NOTICE = (
    "RAWG.IO IMAGES ARE COPYRIGHTED BY GAME PUBLISHERS. "
    "Use is permitted for INTERNAL REFERENCE / IDEATION / RESEARCH ONLY. "
    "DO NOT REDISTRIBUTE; DO NOT INCLUDE IN SHIPPED GAMES."
)


@dataclass
class RawgResult:
    """Outcome of one game-search batch."""

    pack_id: str
    query: str
    output_dir: Path
    games_matched: int = 0
    games_downloaded: int = 0
    screenshots_downloaded: int = 0
    games_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def get_api_key() -> str | None:
    key = os.environ.get(RAWG_API_KEY_ENV, "").strip()
    return key or None


def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    """v1.12.s68: retries HTTP 429/503/502/504 via with_429_retry."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    return with_429_retry(_do_call, max_retries=3, base_delay_s=1.0, cap_delay_s=30.0)


def _download_binary(url: str, dest: Path, *, timeout: float = 30.0) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def search_rawg_games(
    query: str,
    *,
    api_key: str,
    page_size: int = 10,
    page: int = 1,
    genres: str | None = None,
    platforms: str | None = None,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /games?search=...; return results list.

    v1.18.s129: optional platforms= filter (comma-separated platform IDs).
    Common platform IDs: 4=PC, 187=PlayStation 5, 18=PlayStation 4,
    1=Xbox One, 186=Xbox Series, 7=Nintendo Switch, 3=iOS, 21=Android.
    """
    params: dict[str, str] = {
        "key": api_key,
        "search": query,
        "page_size": str(max(1, min(page_size, 40))),
        "page": str(page),
    }
    if genres:
        params["genres"] = genres
    if platforms:
        params["platforms"] = platforms
    url = f"{RAWG_API}/games?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("results", []))


def run_rawg_games_batch(
    *,
    query: str,
    api_key: str | None = None,
    pack_id: str | None = None,
    count: int = 6,
    include_screenshots: bool = True,
    max_screenshots_per_game: int = 3,
    genres: str | None = None,
    platforms: str | None = None,
    min_rating: float = 0.0,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.15,
    dry_run: bool = False,
) -> RawgResult:
    """Search RAWG and download cover + (optionally) screenshots.

    Args:
        query: free-text game name / theme.
        api_key: RAWG_API_KEY (falls back to env).
        count: max games to fetch covers for.
        include_screenshots: also download short_screenshots[] per game.
        max_screenshots_per_game: cap screenshots per game (default 3).
        genres: optional comma-separated genre slugs ('roguelike,strategy').
    """
    resolved_pack_id = pack_id or f"RAWG_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "rawg" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = RawgResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        dry_run=dry_run,
    )

    key = api_key or get_api_key()
    if not key:
        result.ok = False
        result.error = f"missing_api_key (set ${RAWG_API_KEY_ENV})"
        return result

    try:
        games = search_rawg_games(
            query, api_key=key, page_size=min(count, 40),
            genres=genres, platforms=platforms,
        )
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.games_matched = len(games)
    if not games:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for game in games:
        if result.games_downloaded >= count:
            break
        if not isinstance(game, dict):
            continue
        # v1.43.s242 — min_rating filter (RAWG 0.0-5.0 scale).
        if min_rating > 0.0:
            try:
                rating = float(game.get("rating", 0.0) or 0.0)
            except (TypeError, ValueError):
                rating = 0.0
            if rating < min_rating:
                continue
        game_id = game.get("id", "")
        name = str(game.get("name", "")) or f"game_{game_id}"
        slug = str(game.get("slug", ""))
        cover_url = str(game.get("background_image", "") or "")
        if not cover_url:
            result.games_failed += 1
            continue

        # Sanitize slug for filenames.
        safe_slug = "".join(c if c.isalnum() or c == "-" else "_" for c in slug)[:60]
        if not safe_slug:
            safe_slug = f"game_{game_id}"

        # Cover image filename.
        cover_suffix = Path(urllib.parse.urlparse(cover_url).path).suffix or ".jpg"
        cover_dest = out_dir / f"{safe_slug}_cover{cover_suffix}"

        game_entry: dict = {
            "game_id": game_id,
            "name": name,
            "slug": slug,
            "released": str(game.get("released", "") or ""),
            "rating": game.get("rating", 0),
            "genres": [g.get("name", "") for g in (game.get("genres") or [])
                       if isinstance(g, dict)],
            "platforms": [
                (p.get("platform") or {}).get("name", "")
                for p in (game.get("platforms") or [])
                if isinstance(p, dict)
            ],
            "cover_url": cover_url,
            "cover_local_path": str(cover_dest),
            "screenshots": [],
            "use_policy": "reference-only; not for redistribution; not for shipped games",
        }

        # Download cover.
        if dry_run:
            game_entry["cover_downloaded"] = False
            result.downloaded_paths.append(cover_dest)
            result.games_downloaded += 1
        else:
            try:
                cover_bytes = _download_binary(cover_url, cover_dest)
                game_entry["cover_downloaded"] = True
                game_entry["cover_bytes"] = cover_bytes
                result.downloaded_paths.append(cover_dest)
                result.games_downloaded += 1
            except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                game_entry["cover_downloaded"] = False
                game_entry["cover_error"] = str(exc)
                result.games_failed += 1
                manifest_entries.append(game_entry)
                continue

        # Download screenshots.
        if include_screenshots:
            shots = game.get("short_screenshots") or []
            for shot in shots[:max_screenshots_per_game]:
                if not isinstance(shot, dict):
                    continue
                shot_url = str(shot.get("image", "") or "")
                if not shot_url:
                    continue
                shot_id = shot.get("id", "")
                shot_suffix = Path(urllib.parse.urlparse(shot_url).path).suffix or ".jpg"
                shot_dest = out_dir / f"{safe_slug}_shot_{shot_id}{shot_suffix}"
                shot_entry: dict = {
                    "shot_id": shot_id,
                    "url": shot_url,
                    "local_path": str(shot_dest),
                }
                if dry_run:
                    shot_entry["downloaded"] = False
                    game_entry["screenshots"].append(shot_entry)
                    result.downloaded_paths.append(shot_dest)
                    result.screenshots_downloaded += 1
                    continue
                try:
                    shot_bytes = _download_binary(shot_url, shot_dest)
                    shot_entry["downloaded"] = True
                    shot_entry["bytes"] = shot_bytes
                    result.downloaded_paths.append(shot_dest)
                    result.screenshots_downloaded += 1
                except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                    shot_entry["downloaded"] = False
                    shot_entry["error"] = str(exc)
                game_entry["screenshots"].append(shot_entry)

        manifest_entries.append(game_entry)

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    manifest = {
        "source": "rawg.io",
        "pack_id": resolved_pack_id,
        "query": query,
        "games_matched": result.games_matched,
        "games_downloaded": result.games_downloaded,
        "screenshots_downloaded": result.screenshots_downloaded,
        "games_failed": result.games_failed,
        "use_policy_notice": USE_POLICY_NOTICE,
        "license_policy_url": "https://rawg.io/apidocs",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "rawg_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "RAWG_API",
    "RAWG_API_KEY_ENV",
    "USE_POLICY_NOTICE",
    "RawgResult",
    "get_api_key",
    "search_rawg_games",
    "run_rawg_games_batch",
]
