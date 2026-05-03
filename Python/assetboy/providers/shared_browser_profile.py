from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from assetboy.library.paths import assetboy_root


_ROOT_FILES: tuple[str, ...] = ("Local State",)
_PROFILE_FILES: tuple[str, ...] = (
    "Network/Cookies",
    "Preferences",
    "Secure Preferences",
)
_PROFILE_DIRS: tuple[str, ...] = (
    "Local Storage",
    "Session Storage",
    "IndexedDB",
    "Shared Storage",
    "WebStorage",
)
_CRITICAL_RELATIVE_TARGETS: frozenset[str] = frozenset(
    {
        "Local State",
        "Default/Network/Cookies",
    }
)


@dataclass(frozen=True)
class SeedPlanEntry:
    source_path: Path
    target_path: Path
    relative_target: str
    required: bool
    is_dir: bool


def default_windows_chrome_user_data_dir() -> Path:
    return (Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data").resolve()


def default_shared_browser_profile_dir(current_file: str | Path | None = None) -> Path:
    return (assetboy_root(current_file) / ".private" / "fab_browser_profile").resolve()


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _validate_force_reset_path(target_dir: Path) -> None:
    resolved = target_dir.resolve()
    anchor = Path(resolved.anchor)
    if resolved == anchor:
        raise RuntimeError(f"Refusing to reset browser profile target at filesystem root: {resolved}")
    if len(resolved.parts) < 3:
        raise RuntimeError(f"Refusing to reset browser profile target with an unsafe path: {resolved}")


def _copy_file(source_path: Path, target_path: Path) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return int(target_path.stat().st_size if target_path.exists() else 0)


def _copy_directory(source_dir: Path, target_dir: Path) -> tuple[int, int]:
    copied_files = 0
    copied_bytes = 0
    for source_path in source_dir.rglob("*"):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        copied_bytes += _copy_file(source_path, target_path)
        copied_files += 1
    return copied_files, copied_bytes


def _build_seed_plan(*, source_root: Path, source_profile: str, target_dir: Path) -> list[SeedPlanEntry]:
    entries: list[SeedPlanEntry] = []

    for relative_name in _ROOT_FILES:
        source_path = source_root / relative_name
        target_path = target_dir / relative_name
        entries.append(
            SeedPlanEntry(
                source_path=source_path,
                target_path=target_path,
                relative_target=relative_name,
                required=relative_name in _CRITICAL_RELATIVE_TARGETS,
                is_dir=False,
            )
        )

    for relative_name in _PROFILE_FILES:
        source_path = source_root / source_profile / relative_name
        target_relative = str(Path("Default") / relative_name)
        target_path = target_dir / target_relative
        entries.append(
            SeedPlanEntry(
                source_path=source_path,
                target_path=target_path,
                relative_target=target_relative,
                required=target_relative in _CRITICAL_RELATIVE_TARGETS,
                is_dir=False,
            )
        )

    for relative_name in _PROFILE_DIRS:
        source_path = source_root / source_profile / relative_name
        target_relative = str(Path("Default") / relative_name)
        target_path = target_dir / target_relative
        entries.append(
            SeedPlanEntry(
                source_path=source_path,
                target_path=target_path,
                relative_target=target_relative,
                required=False,
                is_dir=True,
            )
        )

    return entries


def seed_shared_browser_profile(
    *,
    source_root: str | Path | None = None,
    source_profile: str = "Default",
    target_dir: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    resolved_source_root = Path(source_root).resolve() if source_root is not None else default_windows_chrome_user_data_dir()
    resolved_target_dir = Path(target_dir).resolve() if target_dir is not None else default_shared_browser_profile_dir()
    normalized_source_profile = str(source_profile or "Default").strip() or "Default"

    if not resolved_source_root.exists():
        raise FileNotFoundError(f"Source browser root does not exist: {resolved_source_root}")
    source_profile_dir = resolved_source_root / normalized_source_profile
    if not source_profile_dir.exists():
        raise FileNotFoundError(f"Source browser profile does not exist: {source_profile_dir}")

    if resolved_source_root == resolved_target_dir or _is_relative_to(resolved_target_dir, resolved_source_root):
        raise RuntimeError(
            "Target browser profile directory must not be the same as, or nested inside, the source browser root."
        )

    seed_plan = _build_seed_plan(
        source_root=resolved_source_root,
        source_profile=normalized_source_profile,
        target_dir=resolved_target_dir,
    )

    target_exists = resolved_target_dir.exists()
    target_nonempty = target_exists and any(resolved_target_dir.iterdir())
    if target_nonempty and not force:
        raise RuntimeError(
            f"Target browser profile already contains data: {resolved_target_dir}. Rerun with --force to replace it."
        )

    missing_entries: list[str] = []
    failed_entries: list[dict[str, str]] = []
    copied_files = 0
    copied_bytes = 0
    required_missing: list[str] = []
    required_failed: list[str] = []

    if target_nonempty and force:
        _validate_force_reset_path(resolved_target_dir)
        if not dry_run:
            shutil.rmtree(resolved_target_dir)

    if not dry_run:
        resolved_target_dir.mkdir(parents=True, exist_ok=True)

    for entry in seed_plan:
        if not entry.source_path.exists():
            missing_entries.append(entry.relative_target)
            if entry.required:
                required_missing.append(entry.relative_target)
            continue

        if dry_run:
            if entry.is_dir:
                copied_files += sum(1 for candidate in entry.source_path.rglob("*") if candidate.is_file())
                copied_bytes += sum(
                    int(candidate.stat().st_size)
                    for candidate in entry.source_path.rglob("*")
                    if candidate.is_file()
                )
            else:
                copied_files += 1
                copied_bytes += int(entry.source_path.stat().st_size if entry.source_path.exists() else 0)
            continue

        try:
            if entry.is_dir:
                file_count, byte_count = _copy_directory(entry.source_path, entry.target_path)
                copied_files += file_count
                copied_bytes += byte_count
            else:
                copied_files += 1
                copied_bytes += _copy_file(entry.source_path, entry.target_path)
        except Exception as exc:
            failed_entries.append({"path": entry.relative_target, "error": str(exc)})
            if entry.required:
                required_failed.append(entry.relative_target)

    target_has_state = (
        (resolved_target_dir / "Local State").exists()
        and (resolved_target_dir / "Default" / "Network" / "Cookies").exists()
    )

    success = not required_missing and not required_failed and (target_has_state or dry_run)
    status = "dry_run" if dry_run else ("seeded" if success else "failed")

    return {
        "status": status,
        "success": success,
        "dry_run": dry_run,
        "force": force,
        "source_root": str(resolved_source_root),
        "source_profile": normalized_source_profile,
        "source_profile_dir": str(source_profile_dir),
        "target_dir": str(resolved_target_dir),
        "target_has_state": target_has_state,
        "copied_files": copied_files,
        "copied_bytes": copied_bytes,
        "missing_entries": missing_entries,
        "failed_entries": failed_entries,
        "required_missing_entries": required_missing,
        "required_failed_entries": required_failed,
        "next_actions": [
            "python scripts/cli.py asset-factory fab-auth --reuse-profile",
            "python scripts/cli.py asset-factory mixamo-auth --reuse-profile",
            "python scripts/cli.py asset-factory unity-auth --reuse-profile",
        ],
    }
