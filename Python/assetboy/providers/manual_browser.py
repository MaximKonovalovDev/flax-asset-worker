from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.library.paths import manual_drop_dir
from assetboy.providers.lanes import get_adapter


class ManualBrowserSite(str, Enum):
    FAB = "fab"
    UNITY_ASSET_STORE = "unity_asset_store"
    MIXAMO = "mixamo"
    MUSEUM_PAGE = "museum_page"
    FREESOUND = "freesound_browser"


SITE_CHECKLISTS: dict[ManualBrowserSite, tuple[str, ...]] = {
    ManualBrowserSite.FAB: (
        "Capture the Fab product URL before download.",
        "Record seller name and the exact license wording.",
        "Save the downloaded archive into the pack subfolder under manual_drop.",
    ),
    ManualBrowserSite.UNITY_ASSET_STORE: (
        "Capture the Asset Store page URL and package version.",
        "Record the publisher/vendor for provenance.",
        "Keep the original unitypackage or zip name in the task notes.",
    ),
    ManualBrowserSite.MIXAMO: (
        "Capture the character page URL and export settings.",
        "Record whether skin, skeleton, and animations were included.",
        "Preserve the original exported filename for provenance.",
    ),
    ManualBrowserSite.MUSEUM_PAGE: (
        "Capture the object page URL and rights statement.",
        "Record museum name, object title, and accession id if available.",
        "Keep the original downloaded archive name in provenance.",
    ),
    ManualBrowserSite.FREESOUND: (
        "Capture the Freesound asset page URL before download.",
        "Record the exact license type (CC0, CC BY, or CC BY-NC).",
        "Preserve the original filename and any attribution notes.",
    ),
}


@dataclass(frozen=True)
class ManualBrowserRequest:
    pack_id: str
    game_scope: str
    site: ManualBrowserSite
    search_terms: tuple[str, ...]
    source_strategy: str
    fallback_sites: tuple[ManualBrowserSite, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def destination(self) -> Path:
        return manual_drop_dir() / self.pack_id

    def to_dict(self) -> dict[str, object]:
        adapter = get_adapter(self.site.value)
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "lane": adapter.lane.value,
            "source_adapter": self.site.value,
            "destination": str(self.destination.resolve()),
            "search_terms": list(self.search_terms),
            "source_strategy": self.source_strategy,
            "fallback_sites": [site.value for site in self.fallback_sites],
            "checklist": list(SITE_CHECKLISTS[self.site]),
            "notes": list(self.notes),
        }


def build_manual_browser_request(
    *,
    pack_id: str,
    game_scope: str,
    site: ManualBrowserSite,
    search_terms: tuple[str, ...],
    source_strategy: str = "",
    fallback_sites: tuple[ManualBrowserSite, ...] = (),
    notes: tuple[str, ...] = (),
) -> ManualBrowserRequest:
    strategy = source_strategy or get_adapter(site.value).source_strategy
    return ManualBrowserRequest(
        pack_id=pack_id,
        game_scope=game_scope,
        site=site,
        search_terms=search_terms,
        source_strategy=strategy,
        fallback_sites=fallback_sites,
        notes=notes,
    )
