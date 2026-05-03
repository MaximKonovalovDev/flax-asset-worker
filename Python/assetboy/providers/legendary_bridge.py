from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def default_legendary_config_dir() -> Path:
    return Path.home() / ".config" / "legendary"


def default_epic_launcher_config_path() -> Path:
    return Path.home() / "AppData" / "Local" / "EpicGamesLauncher" / "Saved" / "Config" / "Windows" / "GameUserSettings.ini"


def default_epic_launcher_windows_editor_config_path() -> Path:
    return Path.home() / "AppData" / "Local" / "EpicGamesLauncher" / "Saved" / "Config" / "WindowsEditor" / "GameUserSettings.ini"


def _extract_remember_me_block(raw: str) -> str:
    lines = raw.splitlines()
    start_index: int | None = None
    collected: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[RememberMe]":
            start_index = index
            collected.append(line)
            continue
        if start_index is None:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        collected.append(line)
    block = "\n".join(collected).strip()
    return block


def _read_config_with_fallbacks() -> tuple[Path, str, Path | None]:
    primary = default_epic_launcher_config_path()
    alternate = default_epic_launcher_windows_editor_config_path()

    if primary.exists():
        raw = primary.read_text(encoding="utf-8", errors="ignore")
        if "[RememberMe]" in raw and "Data=" in raw:
            return primary, raw, None
    if alternate.exists():
        alt_raw = alternate.read_text(encoding="utf-8", errors="ignore")
        if "[RememberMe]" in alt_raw and "Data=" in alt_raw:
            return alternate, alt_raw, primary
    if primary.exists():
        return primary, primary.read_text(encoding="utf-8", errors="ignore"), None
    if alternate.exists():
        return alternate, alternate.read_text(encoding="utf-8", errors="ignore"), primary
    return primary, "", alternate if alternate.exists() else None


def ensure_epic_remember_me_token() -> dict[str, Any]:
    source_path, raw, mirror_target = _read_config_with_fallbacks()
    remember_me_present = "[RememberMe]" in raw
    remember_me_data_present = "Data=" in raw
    report: dict[str, Any] = {
        "source_path": str(source_path),
        "remember_me_present": remember_me_present,
        "remember_me_data_present": remember_me_data_present,
        "mirrored_to_primary": False,
        "primary_path": str(default_epic_launcher_config_path()),
    }
    if not (remember_me_present and remember_me_data_present):
        return report
    if mirror_target is None:
        return report

    block = _extract_remember_me_block(raw)
    if not block:
        return report

    target_raw = ""
    if mirror_target.exists():
        target_raw = mirror_target.read_text(encoding="utf-8", errors="ignore")
        if "[RememberMe]" in target_raw and "Data=" in target_raw:
            report["mirrored_to_primary"] = True
            report["primary_already_had_token"] = True
            return report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = mirror_target.with_name(mirror_target.name + f".bak_{timestamp}")
        shutil.copy2(mirror_target, backup_path)
        report["backup_path"] = str(backup_path)

    if target_raw and not target_raw.endswith("\n"):
        target_raw += "\n"
    if target_raw and not target_raw.endswith("\n\n"):
        target_raw += "\n"
    target_raw += block + "\n"
    mirror_target.parent.mkdir(parents=True, exist_ok=True)
    mirror_target.write_text(target_raw, encoding="utf-8")
    report["mirrored_to_primary"] = True
    return report


def detect_legendary_executable() -> Path | None:
    candidates: list[str | Path] = [
        shutil.which("legendary"),
        shutil.which("legendary.exe"),
        Path.home() / "AppData" / "Roaming" / "Python" / "Python312" / "Scripts" / "legendary.exe",
        Path.home() / "AppData" / "Roaming" / "Python" / "Python311" / "Scripts" / "legendary.exe",
        Path.home() / "AppData" / "Roaming" / "Python" / "Python310" / "Scripts" / "legendary.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def read_epic_launcher_session_state(config_path: str | Path | None = None) -> dict[str, Any]:
    if config_path is not None:
        path = Path(config_path)
        raw = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        fallback_path: Path | None = None
    else:
        path, raw, fallback_path = _read_config_with_fallbacks()
    report: dict[str, Any] = {
        "config_path": str(path),
        "exists": path.exists(),
        "remember_me_present": False,
        "remember_me_data_present": False,
    }
    if fallback_path is not None:
        report["primary_config_path"] = str(fallback_path)
    if not path.exists():
        return report
    report["remember_me_present"] = "[RememberMe]" in raw
    report["remember_me_data_present"] = "Data=" in raw
    return report


def run_legendary_command(
    args: list[str],
    *,
    timeout_seconds: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    exe_path = detect_legendary_executable()
    if exe_path is None:
        raise FileNotFoundError("legendary executable not found")
    return subprocess.run(
        [str(exe_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def build_legendary_status_report(*, timeout_seconds: float = 45.0) -> dict[str, Any]:
    session = read_epic_launcher_session_state()
    exe_path = detect_legendary_executable()
    report: dict[str, Any] = {
        "legendary_path": str(exe_path) if exe_path is not None else "",
        "session": session,
        "status": {},
        "exit_code": None,
        "stderr": "",
        "stdout": "",
    }
    if exe_path is None:
        report["error"] = "legendary executable not found"
        return report
    try:
        result = run_legendary_command(["status", "--offline", "--json"], timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        report["error"] = "legendary status timed out"
        report["exit_code"] = 124
        return report
    report["exit_code"] = result.returncode
    report["stderr"] = result.stderr
    report["stdout"] = result.stdout
    if result.returncode == 0:
        try:
            report["status"] = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            report["error"] = "invalid legendary status json"
    else:
        report["error"] = "legendary status failed"
    return report


def import_legendary_auth(*, timeout_seconds: float = 60.0) -> dict[str, Any]:
    sync_report = ensure_epic_remember_me_token()
    session = read_epic_launcher_session_state()
    exe_path = detect_legendary_executable()
    report: dict[str, Any] = {
        "legendary_path": str(exe_path) if exe_path is not None else "",
        "session": session,
        "sync": sync_report,
        "exit_code": None,
        "stderr": "",
        "stdout": "",
    }
    if exe_path is None:
        report["error"] = "legendary executable not found"
        return report
    try:
        result = run_legendary_command(["auth", "--import"], timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        report["error"] = "legendary auth import timed out"
        report["exit_code"] = 124
        return report
    report["exit_code"] = result.returncode
    report["stderr"] = result.stderr
    report["stdout"] = result.stdout
    if result.returncode != 0:
        report["error"] = "legendary auth import failed"
    return report


def list_legendary_ue_assets(
    *,
    include_ue: bool = True,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    session = read_epic_launcher_session_state()
    exe_path = detect_legendary_executable()
    report: dict[str, Any] = {
        "legendary_path": str(exe_path) if exe_path is not None else "",
        "session": session,
        "records": [],
        "summary": {
            "total_records": 0,
            "has_titles": 0,
        },
        "exit_code": None,
        "stderr": "",
        "stdout": "",
    }
    if exe_path is None:
        report["error"] = "legendary executable not found"
        return report
    args = ["list", "--json"]
    if include_ue:
        args.append("--include-ue")
    try:
        result = run_legendary_command(args, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        report["error"] = "legendary list timed out"
        report["exit_code"] = 124
        return report
    report["exit_code"] = result.returncode
    report["stderr"] = result.stderr
    report["stdout"] = result.stdout
    if result.returncode != 0:
        report["error"] = "legendary list failed"
        return report
    try:
        records = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        report["error"] = "invalid legendary list json"
        return report
    normalized = records if isinstance(records, list) else []
    report["records"] = normalized
    report["summary"] = {
        "total_records": len(normalized),
        "has_titles": sum(1 for item in normalized if str(item.get("app_title", "")).strip() or str(item.get("metadata", {}).get("title", "")).strip()),
    }
    return report


def install_legendary_asset(
    app_name: str,
    *,
    base_path: str | Path,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    exe_path = detect_legendary_executable()
    report: dict[str, Any] = {
        "legendary_path": str(exe_path) if exe_path is not None else "",
        "app_name": app_name,
        "base_path": str(Path(base_path)),
        "exit_code": None,
        "stderr": "",
        "stdout": "",
    }
    if exe_path is None:
        report["error"] = "legendary executable not found"
        return report
    try:
        result = run_legendary_command(
            ["install", app_name, "--download-only", "--base-path", str(Path(base_path))],
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["error"] = "legendary install timed out"
        report["exit_code"] = 124
        return report
    report["exit_code"] = result.returncode
    report["stderr"] = result.stderr
    report["stdout"] = result.stdout
    if result.returncode != 0:
        report["error"] = "legendary install failed"
    return report
