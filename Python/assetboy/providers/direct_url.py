from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import ensure_dir
from assetboy.library.paths import download_queue_csv, manual_drop_dir


QUEUE_FIELDNAMES: tuple[str, ...] = (
    "job_id",
    "pack_id",
    "game_scope",
    "lane",
    "source_adapter",
    "url",
    "destination",
    "source_page_url",
    "license_url",
    "author_or_vendor",
    "notes",
    "status",
    "last_error",
    "bytes",
    "sha256",
    "started_at_utc",
    "completed_at_utc",
)


def _queue_job_id(pack_id: str, url: str, sequence: int = 0) -> str:
    digest = hashlib.sha1(f"{pack_id}|{url}|{sequence}".encode("utf-8")).hexdigest()[:12]
    return f"assetboy-{digest}"


@dataclass(frozen=True)
class DirectUrlQueueRequest:
    pack_id: str
    game_scope: str
    url: str
    source_adapter: str = "direct_url_queue"
    destination: str = ""
    source_page_url: str = ""
    license_url: str = ""
    author_or_vendor: str = ""
    notes: str = ""
    status: str = "queued"

    def to_row(self, sequence: int = 0) -> dict[str, str]:
        if not self.url.strip():
            raise ValueError("Direct URL queue requests require a non-empty url.")
        destination = self.destination or str((manual_drop_dir() / self.pack_id).resolve())
        return {
            "job_id": _queue_job_id(self.pack_id, self.url, sequence),
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "lane": "direct_url",
            "source_adapter": self.source_adapter,
            "url": self.url,
            "destination": destination,
            "source_page_url": self.source_page_url,
            "license_url": self.license_url,
            "author_or_vendor": self.author_or_vendor,
            "notes": self.notes,
            "status": self.status,
            "last_error": "",
            "bytes": "",
            "sha256": "",
            "started_at_utc": "",
            "completed_at_utc": "",
        }


def build_queue_template_rows(
    *,
    pack_id: str,
    game_scope: str,
    request_count: int,
    source_adapter: str = "direct_url_queue",
    notes: str = "",
) -> list[dict[str, str]]:
    count = max(1, int(request_count))
    destination = str((manual_drop_dir() / pack_id).resolve())
    rows: list[dict[str, str]] = []
    for index in range(count):
        rows.append(
            {
                "job_id": f"TEMPLATE_{pack_id}_{index + 1:02d}",
                "pack_id": pack_id,
                "game_scope": game_scope,
                "lane": "direct_url",
                "source_adapter": source_adapter,
                "url": "",
                "destination": destination,
                "source_page_url": "",
                "license_url": "",
                "author_or_vendor": "",
                "notes": notes,
                "status": "queued",
                "last_error": "",
                "bytes": "",
                "sha256": "",
                "started_at_utc": "",
                "completed_at_utc": "",
            }
        )
    return rows


def ensure_queue_file(path: str | Path | None = None) -> Path:
    queue_path = Path(path) if path is not None else download_queue_csv()
    ensure_dir(queue_path.parent)
    if not queue_path.exists() or queue_path.stat().st_size == 0:
        write_queue_rows([], path=queue_path)
    return queue_path


def write_queue_rows(
    rows: list[dict[str, str]],
    *,
    path: str | Path | None = None,
) -> Path:
    queue_path = Path(path) if path is not None else download_queue_csv()
    ensure_dir(queue_path.parent)
    with queue_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return queue_path


def append_queue_requests(
    requests: list[DirectUrlQueueRequest],
    *,
    path: str | Path | None = None,
) -> Path:
    queue_path = ensure_queue_file(path)
    with queue_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDNAMES)
        for index, request in enumerate(requests):
            writer.writerow(request.to_row(sequence=index))
    return queue_path
