from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import read_json


@dataclass(frozen=True)
class CatalogSummary:
    path: Path
    scope: str
    generated_at_utc: str
    total_assets: int
    pack_ids: tuple[str, ...]
    by_type: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "scope": self.scope,
            "generated_at_utc": self.generated_at_utc,
            "total_assets": self.total_assets,
            "pack_ids": list(self.pack_ids),
            "by_type": dict(self.by_type),
        }


def load_catalog_summary(path: str | Path) -> CatalogSummary:
    catalog_path = Path(path).resolve()
    payload = read_json(catalog_path)
    scan = payload.get("scan", {})
    assets = scan.get("assets", [])
    pack_ids = sorted(
        {
            str(item.get("relative_path", "")).split("/", 1)[0]
            for item in assets
            if str(item.get("relative_path", "")).strip()
        }
    )
    return CatalogSummary(
        path=catalog_path,
        scope=str(payload.get("scope", "")),
        generated_at_utc=str(payload.get("generated_at_utc", "")),
        total_assets=int(scan.get("summary", {}).get("total", len(assets))),
        pack_ids=tuple(pack_ids),
        by_type={str(key): int(value) for key, value in scan.get("summary", {}).get("by_type", {}).items()},
    )
