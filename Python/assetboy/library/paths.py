from __future__ import annotations

import json
import os
from pathlib import Path


def assetboy_root(current_file: str | Path | None = None) -> Path:
    """Resolve the vendored asset-factory app root from an assetboy source file path."""
    anchor = Path(current_file or __file__).resolve()
    return anchor.parents[3]


def _workspace_config_path(current_file: str | Path | None = None) -> Path:
    return assetboy_root(current_file) / "assetboy.workspace.json"


def _workspace_config(current_file: str | Path | None = None) -> dict[str, object]:
    config_path = _workspace_config_path(current_file)
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8-sig"))


def project_root(current_file: str | Path | None = None) -> Path:
    """Resolve the target Flax workspace root for the vendored asset factory."""
    override = os.getenv("ASSETBOY_FLAX_REPO_ROOT", "").strip()
    if override:
        return Path(override).resolve()

    config_path = _workspace_config_path(current_file)
    data = _workspace_config(current_file)
    configured = str(data.get("flax_repo_root", "")).strip()
    if configured:
        return Path(configured).resolve()

    app_root = assetboy_root(current_file)
    candidates = [app_root.parent]
    if app_root.parent.parent != app_root.parent:
        candidates.append(app_root.parent.parent)
    for candidate in candidates:
        if (candidate / "GameProjectFlax").exists() and (candidate / "AGENTS.md").exists():
            return candidate.resolve()

    raise FileNotFoundError(
        "The vendored asset factory could not resolve the Flax workspace root. "
        f"Checked ASSETBOY_FLAX_REPO_ROOT, `{config_path}`, and parent candidates `{', '.join(str(path) for path in candidates)}`. "
        f"Set ASSETBOY_FLAX_REPO_ROOT or create `{config_path.name}` with "
        "{\"flax_repo_root\": \"C:\\\\path\\\\to\\\\flax repo\"}."
    )


def asset_library_root(repo_root: str | Path | None = None) -> Path:
    """Return the active asset library root, honoring the repo override contract."""
    override = os.getenv("FLAX_ASSET_LIBRARY_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    configured = str(_workspace_config().get("asset_library_root", "")).strip()
    if configured:
        return Path(configured).resolve()
    root = Path(repo_root) if repo_root is not None else project_root()
    return (root / "artifacts" / "library" / "FlaxAssetLibrary").resolve()


def download_queue_csv(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else project_root()
    return (root / "artifacts" / "quality" / "asset-download-jobs" / "queue.csv").resolve()


def manual_drop_dir(repo_root: str | Path | None = None) -> Path:
    return asset_library_root(repo_root) / "inbox" / "downloads" / "manual_drop"


def asset_library_layout_paths(repo_root: str | Path | None = None) -> tuple[Path, ...]:
    root = asset_library_root(repo_root)
    return (
        root,
        root / "inbox",
        root / "inbox" / "downloads",
        root / "inbox" / "downloads" / "manual_drop",
        root / "publish",
        root / "publish" / "flax_intake",
    )


def manual_drop_pack_dir(pack_id: str, repo_root: str | Path | None = None) -> Path:
    normalized_pack_id = str(pack_id).strip()
    if not normalized_pack_id:
        raise ValueError("pack_id is required")
    return manual_drop_dir(repo_root) / normalized_pack_id


def publish_payload_dir(game_scope: str, pack_id: str, repo_root: str | Path | None = None) -> Path:
    if not game_scope or not pack_id:
        raise ValueError("game_scope and pack_id are required")
    return (
        asset_library_root(repo_root)
        / "publish"
        / "flax_intake"
        / game_scope
        / pack_id
        / "payload"
    )


def imported_packs_dir(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else project_root()
    return (root / "GameProjectFlax" / "MyProject" / "Content" / "Imported" / "Packs").resolve()


def docs_root(current_file: str | Path | None = None) -> Path:
    return assetboy_root(current_file) / "docs"


def state_root(current_file: str | Path | None = None) -> Path:
    return assetboy_root(current_file) / "state"


def generated_output_root(current_file: str | Path | None = None) -> Path:
    return state_root(current_file) / "generated"


def colab_profiles_dir(current_file: str | Path | None = None) -> Path:
    return assetboy_root(current_file) / "profiles" / "colab"


def roman_blocker_task_path(current_file: str | Path | None = None) -> Path:
    return state_root(current_file) / "roman_arena_blocker_tasks.json"


def roman_blocker_summary_path(current_file: str | Path | None = None) -> Path:
    return docs_root(current_file) / "roman_blockers_summary.md"
