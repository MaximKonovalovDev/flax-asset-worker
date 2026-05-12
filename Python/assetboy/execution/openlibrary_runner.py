"""openlibrary_runner.py — Batch-fetch book cover images from Open Library.

Open Library (openlibrary.org) is a project of Internet Archive offering
a free JSON API for ~30M+ book records. Cover images are served from
covers.openlibrary.org as JPEGs at three sizes (S/M/L).

No API key, no auth. Polite: ~100 req/min sustained.

License note: Open Library METADATA is CC0. Cover IMAGES are mostly
small fair-use thumbnails uploaded by users/scrapers; treat them as
REFERENCE-ONLY for game use (similar to RAWG: ideation, mood boards,
img2img seeds — NOT for redistribution in shipped games).

API endpoints:
    GET https://openlibrary.org/search.json?q=<term>&limit=<n>
        -> {numFound, docs: [{key, title, author_name, cover_i, ...}]}
    GET https://covers.openlibrary.org/b/id/<cover_i>-L.jpg
        -> JPEG bytes (-S/-M/-L for size variants)

CLI driver: `assetboy gen openlibrary fetch --query "alchemy" --count 6`
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

OPENLIBRARY_API = "https://openlibrary.org"
COVERS_BASE = "https://covers.openlibrary.org"
USER_AGENT = "flax-asset-worker/1.13 (Open Library reference-only collector; +https://github.com/flax-game-studio)"

USE_POLICY_NOTICE = (
    "Open Library cover images are user-uploaded thumbnails treated as "
    "REFERENCE-ONLY. Use for mood boards / ideation / img2img seeds; do NOT "
    "redistribute or include in shipped games."
)

_VALID_SIZES = frozenset({"S", "M", "L"})


@dataclass
class OpenLibraryResult:
    pack_id: str
    query: str
    output_dir: Path
    docs_matched: int = 0
    covers_with_id: int = 0
    covers_downloaded: int = 0
    covers_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    """v1.13.s91: retries 429/503/502/504."""
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


def search_openlibrary(
    query: str,
    *,
    limit: int = 10,
    author: str | None = None,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /search.json; return list of doc dicts.

    v1.18.s128: optional `author` filter uses Open Library's native
    author= parameter instead of generic q= search.
    """
    params: dict[str, str] = {"limit": str(max(1, min(limit, 100)))}
    if author and author.strip():
        params["author"] = author.strip()
        # q is still required by some queries; pass it through anyway.
        if query and query.strip():
            params["q"] = query
    else:
        params["q"] = query
    url = f"{OPENLIBRARY_API}/search.json?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("docs", []))


def run_openlibrary_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = 6,
    size: str = "L",
    author: str | None = None,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.2,
    dry_run: bool = False,
) -> OpenLibraryResult:
    """Search Open Library and download book cover images.

    Args:
        query: free-text (title/author/subject).
        author: v1.18.s128 — optional author filter (uses native author=).
        size: 'S' (~75px) | 'M' (~180px) | 'L' (~500px, default).
        count: max covers to download.
    """
    size = size.strip().upper()
    if size not in _VALID_SIZES:
        return OpenLibraryResult(
            pack_id=pack_id or "INVALID", query=query,
            output_dir=Path(output_dir) if output_dir else Path("."),
            ok=False,
            error=f"invalid_size: {size!r} not in {sorted(_VALID_SIZES)}",
        )

    resolved_pack_id = pack_id or f"OL_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "openlibrary" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = OpenLibraryResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir, dry_run=dry_run,
    )

    try:
        docs = search_openlibrary(query, limit=min(count * 3, 100), author=author)
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.docs_matched = len(docs)
    if not docs:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for doc in docs:
        if result.covers_downloaded >= count:
            break
        if not isinstance(doc, dict):
            continue
        cover_id = doc.get("cover_i")
        if not isinstance(cover_id, int) or cover_id <= 0:
            continue
        result.covers_with_id += 1

        title = str(doc.get("title", "") or "untitled")
        authors = doc.get("author_name") or []
        author_str = (authors[0] if authors else "") if isinstance(authors, list) else ""
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in title.replace(" ", "_"))[:60] or f"cover_{cover_id}"
        dest = out_dir / f"ol_{cover_id}_{safe_title}.jpg"
        cover_url = f"{COVERS_BASE}/b/id/{cover_id}-{size}.jpg"

        entry = {
            "cover_id": cover_id,
            "openlibrary_key": str(doc.get("key", "") or ""),
            "title": title,
            "author": author_str,
            "first_publish_year": doc.get("first_publish_year"),
            "subject": (doc.get("subject") or [])[:5] if isinstance(doc.get("subject"), list) else [],
            "size": size,
            "source_url": cover_url,
            "openlibrary_url": f"{OPENLIBRARY_API}{doc.get('key', '')}",
            "license": "Open Library metadata CC0; cover images reference-only",
            "use_policy": "reference-only; not for redistribution",
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.covers_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(cover_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.covers_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.covers_failed += 1

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    manifest = {
        "source": "openlibrary",
        "pack_id": resolved_pack_id,
        "query": query,
        "size": size,
        "docs_matched": result.docs_matched,
        "covers_with_id": result.covers_with_id,
        "covers_downloaded": result.covers_downloaded,
        "covers_failed": result.covers_failed,
        "use_policy_notice": USE_POLICY_NOTICE,
        "license_policy_url": "https://openlibrary.org/policies",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "openlibrary_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "OPENLIBRARY_API",
    "COVERS_BASE",
    "USE_POLICY_NOTICE",
    "OpenLibraryResult",
    "search_openlibrary",
    "run_openlibrary_batch",
]
