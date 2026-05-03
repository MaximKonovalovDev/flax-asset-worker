from __future__ import annotations

import base64
import binascii
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from assetboy.library.files import ensure_dir, write_json, write_text
from assetboy.library.paths import asset_library_root, generated_output_root
from assetboy.providers.unity_library import _extract_unity_asset_id, select_unity_download_wave_jobs
from assetboy.providers.unity_runner import emit_unity_export_runner, list_unity_installations


DEFAULT_UNITY_HUB_PROJECTS_PATH = Path.home() / "AppData" / "Roaming" / "UnityHub" / "projects-v1.json"
DEFAULT_UNITY_HUB_LOCAL_STATE_PATH = Path.home() / "AppData" / "Roaming" / "UnityHub" / "Local State"
DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH = Path.home() / "AppData" / "Roaming" / "UnityHub" / "encryptedTokens.json"
DEFAULT_UNITY_HUB_EXECUTABLES: tuple[Path, ...] = (
    Path(r"C:\Program Files\Unity Hub\Unity Hub.exe"),
    Path(r"C:\Program Files (x86)\Unity Hub\Unity Hub.exe"),
)
DEFAULT_UNITY_PACKAGE_API_ROOT = "https://packages-v2.unity.com"
DEFAULT_UNITY_PACKAGE_API_FALLBACK_ROOT = "https://packages.unity.com"
DEFAULT_UNITY_ASSETSTORE_CDN_ROOT = "https://assetstorev1-prd-cdn.unity3d.com"
DEFAULT_UNITY_ASSET_CACHE_ROOTS: tuple[Path, ...] = (
    Path.home() / "AppData" / "Roaming" / "Unity" / "Asset Store-5.x",
    Path.home() / "AppData" / "Roaming" / "Unity" / "Asset Store",
    Path.home() / "AppData" / "Roaming" / "UnityHub" / "downloads",
    Path.home() / "AppData" / "Local" / "Unity" / "cache",
)


def _looks_like_plain_unitypackage(data: bytes) -> bool:
    return data.startswith(b"\x1f\x8b") or data.startswith(b"PK")


def _strip_pkcs7_padding(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad < 1 or pad > 16 or len(data) < pad:
        return data
    if data[-pad:] != bytes([pad]) * pad:
        return data
    return data[:-pad]


def _decrypt_unity_assetstore_blob(blob: bytes, legacy_download_key: str) -> tuple[bytes, bool]:
    key_text = str(legacy_download_key or "").strip()
    if not blob or not key_text:
        return blob, False
    if _looks_like_plain_unitypackage(blob):
        return blob, False
    if not re.fullmatch(r"[0-9A-Fa-f]{96}", key_text):
        return blob, False

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except Exception:
        return blob, False

    try:
        key_bytes = binascii.unhexlify(key_text)
    except Exception:
        return blob, False

    if len(key_bytes) != 48 or len(blob) % 16 != 0:
        return blob, False

    aes_key = key_bytes[:32]
    iv = key_bytes[32:48]
    try:
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(blob) + decryptor.finalize()
    except Exception:
        return blob, False

    decrypted = _strip_pkcs7_padding(decrypted)
    if not _looks_like_plain_unitypackage(decrypted):
        return blob, False
    return decrypted, True


def detect_unity_hub_executable(candidates: tuple[Path, ...] | None = None) -> Path | None:
    for candidate in candidates or DEFAULT_UNITY_HUB_EXECUTABLES:
        if candidate.exists():
            return candidate.resolve()
    return None


def read_unity_project_cloud_project_id(project_path: Path) -> str:
    settings_path = project_path / "ProjectSettings" / "ProjectSettings.asset"
    if not settings_path.exists():
        return ""
    try:
        content = settings_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    match = re.search(r"^[ \t]*cloudProjectId:[ \t]*([0-9a-fA-F-]+)[ \t]*$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def list_unity_hub_projects(projects_path: Path | None = None) -> list[dict[str, Any]]:
    path = projects_path if projects_path is not None else DEFAULT_UNITY_HUB_PROJECTS_PATH
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    data = payload.get("data", {})
    if not isinstance(data, dict):
        return []

    projects: list[dict[str, Any]] = []
    for raw_path, metadata in data.items():
        if not isinstance(metadata, dict):
            continue
        project_path = Path(str(metadata.get("path") or raw_path))
        projects.append(
            {
                "title": str(metadata.get("title") or metadata.get("projectName") or project_path.name),
                "path": str(project_path),
                "version": str(metadata.get("version", "")),
                "architecture": str(metadata.get("architecture", "")),
                "organization_id": str(metadata.get("organizationId", "")),
                "genesis_org_id": str(metadata.get("genesisOrgId", "")),
                "cloud_project_id": str(metadata.get("cloudProjectId", "")),
                "render_pipeline": str(metadata.get("renderPipeline", "")),
                "last_modified": int(metadata.get("lastModified", 0) or 0),
                "exists": project_path.exists(),
            }
        )

    projects.sort(key=lambda item: int(item.get("last_modified", 0)), reverse=True)
    return projects


def scan_unity_asset_cache(cache_roots: tuple[Path, ...] | None = None, *, limit: int = 200) -> dict[str, Any]:
    roots = cache_roots if cache_roots is not None else DEFAULT_UNITY_ASSET_CACHE_ROOTS
    existing_roots: list[str] = []
    files: list[dict[str, Any]] = []
    seen: set[Path] = set()

    for root in roots:
        if not root.exists():
            continue
        existing_roots.append(str(root))
        try:
            for pattern in ("*.unitypackage", "*.tgz", "*.zip"):
                for file_path in root.rglob(pattern):
                    resolved = file_path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    files.append(
                        {
                            "path": str(resolved),
                            "name": resolved.name,
                            "size_bytes": resolved.stat().st_size,
                        }
                    )
                    if len(files) >= limit:
                        break
                if len(files) >= limit:
                    break
        except Exception:
            continue
        if len(files) >= limit:
            break

    files.sort(key=lambda item: (str(item.get("name", "")).lower(), str(item.get("path", "")).lower()))
    return {
        "cache_roots_checked": [str(root) for root in roots],
        "existing_cache_roots": existing_roots,
        "cached_files": files,
        "cached_file_count": len(files),
        "cached_unitypackage_count": sum(1 for item in files if str(item.get("name", "")).lower().endswith(".unitypackage")),
    }


def _safe_datetime_from_epoch_millis(value: Any) -> str:
    try:
        millis = int(value)
    except Exception:
        return ""
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).isoformat()


def _load_unity_hub_master_key(local_state_path: Path | None = None) -> bytes:
    try:
        import win32crypt
    except Exception as exc:  # pragma: no cover - exercised in live environment
        raise RuntimeError("win32crypt is required to decrypt Unity Hub tokens.") from exc

    path = local_state_path if local_state_path is not None else DEFAULT_UNITY_HUB_LOCAL_STATE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    encrypted_key = base64.b64decode(str(payload.get("os_crypt", {}).get("encrypted_key", "")))
    if not encrypted_key.startswith(b"DPAPI"):
        raise RuntimeError("Unity Hub Local State did not contain a DPAPI-wrapped master key.")
    return win32crypt.CryptUnprotectData(encrypted_key[5:], None, None, None, 0)[1]


def _decrypt_unity_hub_blob(blob: bytes, *, local_state_path: Path | None = None) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception as exc:  # pragma: no cover - exercised in live environment
        raise RuntimeError("cryptography is required to decrypt Unity Hub tokens.") from exc

    if not blob.startswith(b"v10") or len(blob) <= 15:
        raise RuntimeError("Unexpected Unity Hub encrypted payload format.")
    master_key = _load_unity_hub_master_key(local_state_path)
    nonce = blob[3:15]
    ciphertext = blob[15:]
    return AESGCM(master_key).decrypt(nonce, ciphertext, None).decode("utf-8")


def load_unity_hub_tokens(
    *,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    tokens_path = encrypted_tokens_path if encrypted_tokens_path is not None else DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH
    if not tokens_path.exists():
        return {}
    try:
        payload = json.loads(tokens_path.read_text(encoding="utf-8", errors="ignore"))
        raw_tokens = payload.get("tokens", {})
        if isinstance(raw_tokens, dict) and isinstance(raw_tokens.get("data"), list):
            blob = bytes(raw_tokens["data"])
        elif isinstance(raw_tokens, dict) and isinstance(raw_tokens.get("data"), str):
            blob = str(raw_tokens["data"]).encode("latin1")
        else:
            return {}
        decrypted = _decrypt_unity_hub_blob(blob, local_state_path=local_state_path)
        tokens = json.loads(decrypted)
    except Exception:
        return {}
    return tokens if isinstance(tokens, dict) else {}


def _build_unity_hub_auth_report(
    *,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    tokens = load_unity_hub_tokens(local_state_path=local_state_path, encrypted_tokens_path=encrypted_tokens_path)
    now_ms = int(time.time() * 1000)
    access_expiration = int(tokens.get("accessTokenExpiration", 0) or 0)
    refresh_expiration = int(tokens.get("refreshTokenExpiration", 0) or 0)
    unity_expiration = int(tokens.get("unityTokenExpiration", 0) or 0)
    return {
        "encrypted_tokens_path": str(encrypted_tokens_path if encrypted_tokens_path is not None else DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH),
        "local_state_path": str(local_state_path if local_state_path is not None else DEFAULT_UNITY_HUB_LOCAL_STATE_PATH),
        "tokens_available": bool(tokens),
        "access_token_present": bool(str(tokens.get("accessToken", "")).strip()),
        "refresh_token_present": bool(str(tokens.get("refreshToken", "")).strip()),
        "unity_token_present": bool(str(tokens.get("unityToken", "")).strip()),
        "access_token_expiration": access_expiration,
        "access_token_expires_at": _safe_datetime_from_epoch_millis(access_expiration),
        "access_token_expired": bool(access_expiration and access_expiration <= now_ms),
        "refresh_token_expiration": refresh_expiration,
        "refresh_token_expires_at": _safe_datetime_from_epoch_millis(refresh_expiration),
        "refresh_token_expired": bool(refresh_expiration and refresh_expiration <= now_ms),
        "unity_token_expiration": unity_expiration,
        "unity_token_expires_at": _safe_datetime_from_epoch_millis(unity_expiration),
        "unity_token_expired": bool(unity_expiration and unity_expiration <= now_ms),
    }


def _unity_access_headers(tokens: dict[str, Any]) -> dict[str, str]:
    access_token = str(tokens.get("accessToken", "")).strip()
    if not access_token:
        raise RuntimeError("Unity Hub access token is missing from the local encrypted token store.")
    return {"Authorization": f"Bearer {access_token}"}


def _unity_api_get_json(
    path: str,
    *,
    tokens: dict[str, Any],
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    roots = [api_root]
    if api_root == DEFAULT_UNITY_PACKAGE_API_ROOT:
        roots.append(DEFAULT_UNITY_PACKAGE_API_FALLBACK_ROOT)

    last_error: Exception | None = None
    for root in roots:
        try:
            response = requests.get(
                f"{root.rstrip('/')}/{path.lstrip('/')}",
                headers=_unity_access_headers(tokens),
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code < 500 or root == roots[-1]:
                raise
        except Exception as exc:
            last_error = exc
            if root == roots[-1]:
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Unity API request failed before any response was returned.")


def list_unity_owned_assets(
    *,
    page: int = 1,
    rows: int = 200,
    tokens: dict[str, Any] | None = None,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    timeout: float = 30.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    resolved_tokens = tokens or load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    payload = _unity_api_get_json(
        "-/api/purchases",
        tokens=resolved_tokens,
        api_root=api_root,
        params={"page": page, "rows": rows},
        timeout=timeout,
    )
    return payload if isinstance(payload, dict) else {"results": []}


def build_unity_owned_library_map(
    *,
    page_size: int = 200,
    max_pages: int = 5,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    timeout: float = 30.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    auth = _build_unity_hub_auth_report(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    tokens = load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    items: list[dict[str, Any]] = []
    pages_fetched = 0
    error_message = ""

    if tokens:
        try:
            for page in range(1, max_pages + 1):
                payload = list_unity_owned_assets(
                    page=page,
                    rows=page_size,
                    tokens=tokens,
                    api_root=api_root,
                    timeout=timeout,
                )
                raw_results = payload.get("results", []) if isinstance(payload, dict) else []
                results = raw_results if isinstance(raw_results, list) else []
                pages_fetched += 1
                for entry in results:
                    if not isinstance(entry, dict):
                        continue
                    items.append(
                        {
                            "id": str(entry.get("id", "")),
                            "package_id": str(entry.get("packageId", "")),
                            "display_name": str(entry.get("displayName", "")),
                            "grant_time": str(entry.get("grantTime", "")),
                            "order_id": str(entry.get("orderId", "")),
                            "is_hidden": bool(entry.get("isHidden")),
                            "is_publisher_asset": bool(entry.get("isPublisherAsset")),
                            "tagging": list(entry.get("tagging", [])) if isinstance(entry.get("tagging", []), list) else [],
                        }
                    )
                if len(results) < page_size:
                    break
        except Exception as exc:
            error_message = str(exc)

    items.sort(key=lambda item: (item.get("display_name", "").lower(), item.get("package_id", "")))
    return {
        "api_root": api_root,
        "page_size": page_size,
        "max_pages": max_pages,
        "pages_fetched": pages_fetched,
        "owned_count": len(items),
        "auth": auth,
        "error": error_message,
        "items": items,
    }


def render_unity_owned_library_map_markdown(report: dict[str, Any]) -> str:
    auth = dict(report.get("auth", {}))
    lines = [
        "# Unity Owned Library Map",
        "",
        f"- API root: `{report.get('api_root', '')}`",
        f"- Tokens available: `{str(bool(auth.get('tokens_available'))).lower()}`",
        f"- Access token present: `{str(bool(auth.get('access_token_present'))).lower()}`",
        f"- Access token expired: `{str(bool(auth.get('access_token_expired'))).lower()}`",
        f"- Pages fetched: `{report.get('pages_fetched', 0)}`",
        f"- Owned items: `{report.get('owned_count', 0)}`",
    ]
    if str(report.get("error", "")).strip():
        lines.append(f"- Error: `{report.get('error', '')}`")
    lines.extend(["", "## Items", ""])
    for item in report.get("items", []) or []:
        lines.append(
            f"- {item.get('display_name', '')} | package_id=`{item.get('package_id', '')}` | grant=`{item.get('grant_time', '')}` | hidden=`{str(bool(item.get('is_hidden'))).lower()}`"
        )
    lines.append("")
    return "\n".join(lines)


def _coerce_positive_int(value: Any) -> int:
    try:
        resolved = int(str(value).strip())
    except Exception:
        return 0
    return resolved if resolved > 0 else 0


def _sanitize_download_folder_name(display_name: str, package_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(display_name).strip()).strip("_")
    token = token[:48].strip("_") or "unity_item"
    package_token = str(package_id).strip() or "unknown"
    return f"{package_token}_{token}"


def _shorten_unitypackage_filename(
    *,
    package_name: str,
    product_id: str,
    slug: str,
    selected_version: str,
    max_stem_length: int = 100,
) -> str:
    raw_name = str(package_name or "").strip() or f"unity_asset_{product_id}.unitypackage"
    path_name = Path(raw_name).name
    suffix = "".join(Path(path_name).suffixes) or ".unitypackage"
    stem = path_name[: -len(suffix)] if suffix and path_name.endswith(suffix) else Path(path_name).stem

    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-")
    if len(safe_stem) <= max_stem_length:
        return f"{safe_stem}{suffix}"

    slug_token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(slug or "").strip()).strip("._-")
    version_token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(selected_version or "").strip()).strip("._-")
    product_token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(product_id or "").strip()).strip("._-") or "unity"
    fallback_stem = "_".join(part for part in (product_token, slug_token[:40], version_token[:20]) if part).strip("._-")
    fallback_stem = fallback_stem[:max_stem_length].strip("._-") or f"unity_asset_{product_token}"
    return f"{fallback_stem}{suffix}"


def _load_existing_unity_owned_download(item_output_dir: Path, package_id: str) -> dict[str, Any] | None:
    report_path = item_output_dir / f"unity_owned_download_{package_id}.json"
    package_paths = sorted(item_output_dir.glob("*.unitypackage"))

    if report_path.exists():
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            resolved = dict(payload)
            output_path = Path(str(resolved.get("output_path", "")).strip()) if str(resolved.get("output_path", "")).strip() else None
            if output_path is None or not output_path.exists():
                if package_paths:
                    resolved["output_path"] = str(package_paths[0])
                    resolved.setdefault("bytes_written", package_paths[0].stat().st_size)
                    resolved.setdefault("final_bytes_written", package_paths[0].stat().st_size)
                    return resolved
            elif output_path.exists():
                return resolved

    if package_paths:
        package_path = package_paths[0]
        size_bytes = package_path.stat().st_size
        return {
            "product_id": str(package_id).strip(),
            "output_path": str(package_path),
            "bytes_written": size_bytes,
            "final_bytes_written": size_bytes,
            "recovered_from_package_only": True,
        }
    return None


def inspect_unity_owned_download_candidates(
    *,
    page_size: int = 200,
    max_pages: int = 5,
    timeout: float = 30.0,
    include_hidden: bool = False,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    owned_map = build_unity_owned_library_map(
        page_size=page_size,
        max_pages=max_pages,
        timeout=timeout,
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    tokens = load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    candidates: list[dict[str, Any]] = []

    if not tokens:
        return {
            "owned_library": owned_map,
            "candidate_count": 0,
            "error": "Unity Hub tokens are not available.",
            "items": candidates,
        }

    for entry in owned_map.get("items", []) or []:
        if not isinstance(entry, dict):
            continue
        if not include_hidden and bool(entry.get("is_hidden")):
            continue

        package_id = str(entry.get("package_id", "")).strip()
        display_name = str(entry.get("display_name", "")).strip()
        candidate = {
            "package_id": package_id,
            "display_name": display_name,
            "grant_time": str(entry.get("grant_time", "")).strip(),
            "is_hidden": bool(entry.get("is_hidden")),
            "publisher_name": "",
            "category_name": "",
            "asset_store_product_url": "",
            "selected_upload_version": "",
            "recommended_min_unity_version": "",
            "expected_bytes": 0,
            "expected_mb": 0.0,
            "package_name": "",
            "status": "inspected",
            "error": "",
        }

        if not package_id:
            candidate["status"] = "failed_inspection"
            candidate["error"] = "owned entry is missing package_id"
            candidates.append(candidate)
            continue

        try:
            product_detail = get_unity_product_detail(
                package_id,
                tokens=tokens,
                timeout=timeout,
            )
            update_map = get_unity_product_update_info(
                package_id,
                tokens=tokens,
                timeout=timeout,
            )
            update_info = update_map.get(package_id, {}) if isinstance(update_map, dict) else {}
            legacy_detail = get_unity_legacy_download_detail(
                package_id,
                tokens=tokens,
                timeout=timeout,
            )
            selected_version, upload = _pick_unity_upload(
                product_detail,
                update_info if isinstance(update_info, dict) else {},
            )
            expected_bytes = _coerce_positive_int(upload.get("downloadSize", 0))
            package_name = Path(str(upload.get("uploadS3key", "")).strip()).name
            if not package_name:
                package_name = str(legacy_detail.get("filename_safe_package_name", "")).strip()
                if package_name and not package_name.lower().endswith(".unitypackage"):
                    package_name = f"{package_name}.unitypackage"
            if not package_name:
                slug = str(product_detail.get("slug", "")).strip() or f"unity_asset_{package_id}"
                package_name = f"{slug}.unitypackage"

            candidate.update(
                {
                    "publisher_name": str(
                        product_detail.get("publisherName", "")
                        or legacy_detail.get("filename_safe_publisher_name", "")
                    ).strip(),
                    "category_name": str(
                        product_detail.get("category", "")
                        or legacy_detail.get("filename_safe_category_name", "")
                    ).strip(),
                    "asset_store_product_url": str(product_detail.get("assetStoreProductUrl", "")).strip(),
                    "selected_upload_version": selected_version,
                    "recommended_min_unity_version": str(
                        update_info.get("recommended_min_unity_version", "")
                    ).strip()
                    if isinstance(update_info, dict)
                    else "",
                    "expected_bytes": expected_bytes,
                    "expected_mb": round(expected_bytes / (1024 * 1024), 2) if expected_bytes > 0 else 0.0,
                    "package_name": package_name,
                }
            )
        except Exception as exc:
            candidate["status"] = "failed_inspection"
            candidate["error"] = str(exc)

        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item.get("status") != "inspected",
            int(item.get("expected_bytes", 0) or 0) <= 0,
            int(item.get("expected_bytes", 0) or 0),
            str(item.get("display_name", "")).lower(),
        )
    )
    return {
        "owned_library": owned_map,
        "candidate_count": len(candidates),
        "error": "",
        "items": candidates,
    }


def render_unity_owned_download_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Unity Owned Download Wave",
        "",
        f"- Wave source: `{report.get('wave_json', '')}`",
        f"- Output dir: `{report.get('output_dir', '')}`",
        f"- Selected jobs: `{summary.get('selected_jobs', 0)}`",
        f"- Owned matches: `{summary.get('owned_matches', 0)}`",
        f"- Downloaded: `{summary.get('downloaded', 0)}`",
        f"- Not owned: `{summary.get('not_owned', 0)}`",
        f"- Failed: `{summary.get('failed', 0)}`",
        "",
        "## Items",
        "",
    ]
    for item in report.get("items", []) or []:
        lines.append(
            "- "
            + f"{item.get('name', '')} | `{item.get('pack_id', '')}` | "
            + f"asset_id=`{item.get('asset_id', '')}` | "
            + f"status=`{item.get('status', '')}` | "
            + f"output=`{item.get('output_path', '')}`"
        )
    lines.append("")
    return "\n".join(lines)


def render_unity_owned_lightweights_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Unity Owned Lightweight Download Wave",
        "",
        f"- Output dir: `{report.get('output_dir', '')}`",
        f"- Max MB: `{summary.get('max_mb', 0)}`",
        f"- Owned items scanned: `{summary.get('owned_items_scanned', 0)}`",
        f"- Candidates inspected: `{summary.get('candidates_inspected', 0)}`",
        f"- Eligible lightweights: `{summary.get('eligible_lightweights', 0)}`",
        f"- Downloaded: `{summary.get('downloaded', 0)}`",
        f"- Reused existing: `{summary.get('reused_existing', 0)}`",
        f"- Skipped large: `{summary.get('skipped_large', 0)}`",
        f"- Skipped unknown size: `{summary.get('skipped_unknown_size', 0)}`",
        f"- Failed inspection: `{summary.get('failed_inspection', 0)}`",
        f"- Failed download: `{summary.get('failed_download', 0)}`",
        "",
        "## Items",
        "",
    ]
    for item in report.get("items", []) or []:
        lines.append(
            "- "
            + f"{item.get('display_name', '')} | package_id=`{item.get('package_id', '')}` | "
            + f"status=`{item.get('status', '')}` | "
            + f"size_mb=`{item.get('expected_mb', 0)}` | "
            + f"output=`{item.get('output_path', '')}`"
        )
    lines.append("")
    return "\n".join(lines)


def _load_cached_unity_owned_library_map() -> dict[str, Any]:
    latest_path: Path | None = None
    latest_report: dict[str, Any] = {}
    try:
        candidates = list(generated_output_root().rglob("unity_owned_library_map.json"))
    except Exception:
        return {}
    for candidate in candidates:
        try:
            report = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(report, dict):
            continue
        owned_count = int(report.get("owned_count", 0) or 0)
        if owned_count <= 0:
            continue
        if latest_path is None or candidate.stat().st_mtime > latest_path.stat().st_mtime:
            latest_path = candidate
            latest_report = report
    if latest_path is None:
        return {}
    merged = dict(latest_report)
    merged["cached_report_path"] = str(latest_path)
    return merged


def _find_downloaded_unitypackage(*, pack_id: str, asset_id: str) -> Path | None:
    candidates: list[Path] = []
    try:
        search_root = generated_output_root()
        if pack_id:
            candidates.extend(search_root.rglob(f"downloads/{pack_id}/*.unitypackage"))
        if asset_id:
            candidates.extend(search_root.rglob(f"*{asset_id}*.unitypackage"))
    except Exception:
        return None
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    existing.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return existing[0]


def download_unity_owned_wave(
    *,
    wave_json: Path,
    best_first_only: bool = False,
    exportable_only: bool = False,
    asset_donor_only: bool = False,
    categories: tuple[str, ...] = (),
    pack_ids: tuple[str, ...] = (),
    limit: int | None = None,
    output_dir: Path | None = None,
    timeout: float = 60.0,
    page_size: int = 200,
    max_pages: int = 5,
) -> dict[str, Any]:
    report = json.loads(Path(wave_json).read_text(encoding="utf-8"))
    selected = select_unity_download_wave_jobs(
        report,
        best_first_only=best_first_only,
        exportable_only=exportable_only,
        asset_donor_only=asset_donor_only,
        categories=categories,
        pack_ids=pack_ids,
        limit=limit,
    )
    actual_output_dir = ensure_dir(output_dir if output_dir is not None else Path(wave_json).parent / "unity_owned_download_wave")
    downloads_root = ensure_dir(actual_output_dir / "downloads")
    owned_map = build_unity_owned_library_map(page_size=page_size, max_pages=max_pages, timeout=timeout)
    owned_map_source = "live"
    if int(owned_map.get("owned_count", 0) or 0) <= 0 and str(owned_map.get("error", "")).strip():
        cached_owned_map = _load_cached_unity_owned_library_map()
        if cached_owned_map:
            owned_map = cached_owned_map
            owned_map_source = "cached"
    owned_lookup = {
        str(item.get("package_id", "")).strip(): dict(item)
        for item in (owned_map.get("items") or [])
        if isinstance(item, dict) and str(item.get("package_id", "")).strip()
    }

    items: list[dict[str, Any]] = []
    for item in selected:
        pack_id = str(item.get("pack_id", "")).strip()
        name = str(item.get("name", "")).strip()
        asset_id = str(item.get("asset_id") or _extract_unity_asset_id(str(item.get("url", "")))).strip()
        item_output_dir = downloads_root / (pack_id or "unity_item")
        entry = {
            "name": name,
            "pack_id": pack_id,
            "asset_id": asset_id,
            "url": str(item.get("url", "")).strip(),
            "owned": bool(asset_id and asset_id in owned_lookup),
            "status": "not_owned",
            "output_path": "",
            "download_report_json": "",
            "error": "",
        }
        if not entry["owned"]:
            items.append(entry)
            continue
        try:
            ensure_dir(item_output_dir)
            download_report = download_unity_owned_package(
                product_id=asset_id,
                output_dir=item_output_dir,
                timeout=timeout,
            )
            report_path = item_output_dir / f"unity_owned_download_{asset_id}.json"
            write_json(report_path, download_report)
            entry["status"] = "downloaded"
            entry["output_path"] = str(download_report.get("output_path", "")).strip()
            entry["download_report_json"] = str(report_path)
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
        items.append(entry)

    summary = {
        "selected_jobs": len(items),
        "owned_matches": sum(1 for item in items if bool(item.get("owned"))),
        "downloaded": sum(1 for item in items if str(item.get("status", "")) == "downloaded"),
        "not_owned": sum(1 for item in items if str(item.get("status", "")) == "not_owned"),
        "failed": sum(1 for item in items if str(item.get("status", "")) == "failed"),
    }
    wave_report = {
        "wave_json": str(wave_json),
        "output_dir": str(actual_output_dir),
        "summary": summary,
        "owned_library_map": {
            "source": owned_map_source,
            "owned_count": owned_map.get("owned_count", 0),
            "pages_fetched": owned_map.get("pages_fetched", 0),
            "error": str(owned_map.get("error", "")).strip(),
            "cached_report_path": str(owned_map.get("cached_report_path", "")).strip(),
        },
        "items": items,
    }
    write_json(actual_output_dir / "unity_owned_download_wave.json", wave_report)
    write_text(actual_output_dir / "unity_owned_download_wave.md", render_unity_owned_download_wave_markdown(wave_report))
    return wave_report


def download_unity_owned_lightweights(
    *,
    max_mb: float = 150.0,
    limit: int | None = None,
    include_hidden: bool = False,
    include_unknown_size: bool = False,
    output_dir: Path | None = None,
    timeout: float = 60.0,
    page_size: int = 200,
    max_pages: int = 5,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    actual_output_dir = ensure_dir(
        output_dir if output_dir is not None else generated_output_root() / "unity_owned_lightweights"
    )
    downloads_root = ensure_dir(actual_output_dir / "downloads")
    candidate_report = inspect_unity_owned_download_candidates(
        page_size=page_size,
        max_pages=max_pages,
        timeout=timeout,
        include_hidden=include_hidden,
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    max_bytes = int(max_mb * 1024 * 1024)

    items: list[dict[str, Any]] = []
    eligible_count = 0
    downloaded_count = 0
    skipped_large = 0
    skipped_unknown = 0
    failed_inspection = 0
    failed_download = 0
    reused_existing = 0

    for candidate in candidate_report.get("items", []) or []:
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        item["output_path"] = ""
        item["download_report_json"] = ""

        status = str(item.get("status", "")).strip() or "inspected"
        if status == "failed_inspection":
            failed_inspection += 1
            items.append(item)
            continue

        expected_bytes = _coerce_positive_int(item.get("expected_bytes", 0))
        eligible = False
        if expected_bytes > 0:
            if expected_bytes <= max_bytes:
                eligible = True
            else:
                item["status"] = "skipped_large"
                skipped_large += 1
        elif include_unknown_size:
            eligible = True
        else:
            item["status"] = "skipped_unknown_size"
            skipped_unknown += 1

        if not eligible:
            items.append(item)
            continue

        if limit is not None and limit > 0 and eligible_count >= limit:
            item["status"] = "skipped_limit"
            items.append(item)
            continue

        eligible_count += 1
        folder_name = _sanitize_download_folder_name(
            str(item.get("display_name", "")),
            str(item.get("package_id", "")),
        )
        item_output_dir = ensure_dir(downloads_root / folder_name)
        existing_report = _load_existing_unity_owned_download(
            item_output_dir=item_output_dir,
            package_id=str(item.get("package_id", "")).strip(),
        )
        if existing_report is not None:
            report_path = item_output_dir / f"unity_owned_download_{item.get('package_id', '')}.json"
            if not report_path.exists():
                write_json(report_path, existing_report)
            item["status"] = "downloaded_existing"
            item["output_path"] = str(existing_report.get("output_path", "")).strip()
            item["download_report_json"] = str(report_path)
            item["bytes_written"] = int(existing_report.get("bytes_written", 0) or 0)
            item["final_bytes_written"] = int(existing_report.get("final_bytes_written", 0) or 0)
            downloaded_count += 1
            reused_existing += 1
            items.append(item)
            continue

        try:
            download_report = download_unity_owned_package(
                product_id=str(item.get("package_id", "")).strip(),
                output_dir=item_output_dir,
                timeout=timeout,
                local_state_path=local_state_path,
                encrypted_tokens_path=encrypted_tokens_path,
            )
            report_path = item_output_dir / f"unity_owned_download_{item.get('package_id', '')}.json"
            write_json(report_path, download_report)
            item["status"] = "downloaded"
            item["output_path"] = str(download_report.get("output_path", "")).strip()
            item["download_report_json"] = str(report_path)
            item["bytes_written"] = int(download_report.get("bytes_written", 0) or 0)
            item["final_bytes_written"] = int(download_report.get("final_bytes_written", 0) or 0)
            downloaded_count += 1
        except Exception as exc:
            item["status"] = "failed_download"
            item["error"] = str(exc)
            failed_download += 1

        items.append(item)

    summary = {
        "max_mb": max_mb,
        "owned_items_scanned": int(candidate_report.get("owned_library", {}).get("owned_count", 0) or 0),
        "candidates_inspected": len(candidate_report.get("items", []) or []),
        "eligible_lightweights": eligible_count,
        "downloaded": downloaded_count,
        "reused_existing": reused_existing,
        "skipped_large": skipped_large,
        "skipped_unknown_size": skipped_unknown,
        "failed_inspection": failed_inspection,
        "failed_download": failed_download,
    }
    report = {
        "output_dir": str(actual_output_dir),
        "summary": summary,
        "candidate_report": {
            "candidate_count": int(candidate_report.get("candidate_count", 0) or 0),
            "owned_count": int(candidate_report.get("owned_library", {}).get("owned_count", 0) or 0),
            "pages_fetched": int(candidate_report.get("owned_library", {}).get("pages_fetched", 0) or 0),
            "error": str(candidate_report.get("owned_library", {}).get("error", "")).strip(),
        },
        "items": items,
    }
    write_json(actual_output_dir / "unity_owned_lightweights.json", report)
    write_text(actual_output_dir / "unity_owned_lightweights.md", render_unity_owned_lightweights_markdown(report))
    return report


def get_unity_product_detail(
    product_id: int | str,
    *,
    tokens: dict[str, Any] | None = None,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    timeout: float = 30.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    resolved_tokens = tokens or load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    payload = _unity_api_get_json(
        f"-/api/product/{int(product_id)}",
        tokens=resolved_tokens,
        api_root=api_root,
        timeout=timeout,
    )
    return payload if isinstance(payload, dict) else {}


def get_unity_product_update_info(
    product_ids: list[int | str] | tuple[int | str, ...] | int | str,
    *,
    tokens: dict[str, Any] | None = None,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    timeout: float = 30.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    if isinstance(product_ids, (str, int)):
        joined_ids = str(product_ids)
    else:
        joined_ids = ",".join(str(item) for item in product_ids)
    resolved_tokens = tokens or load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    payload = _unity_api_get_json(
        "-/api/product-update-info",
        tokens=resolved_tokens,
        api_root=api_root,
        params={"productIds": joined_ids},
        timeout=timeout,
    )
    return payload if isinstance(payload, dict) else {}


def get_unity_legacy_download_detail(
    product_id: int | str,
    *,
    tokens: dict[str, Any] | None = None,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    timeout: float = 30.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    resolved_tokens = tokens or load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    payload = _unity_api_get_json(
        f"-/api/legacy-package-download-info/{int(product_id)}",
        tokens=resolved_tokens,
        api_root=api_root,
        timeout=timeout,
    )
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return {}
    download = result.get("download", {})
    return download if isinstance(download, dict) else {}


def _unity_version_sort_key(version_key: str) -> tuple[Any, ...]:
    parts = re.findall(r"\d+|[A-Za-z]+", version_key)
    normalized: list[Any] = []
    for part in parts:
        normalized.append(int(part) if part.isdigit() else part.lower())
    return tuple(normalized)


def _pick_unity_upload(
    product_detail: dict[str, Any],
    update_info: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    uploads = product_detail.get("uploads", {})
    if not isinstance(uploads, dict) or not uploads:
        return "", {}

    recommended_version_prefix = str(update_info.get("recommended_min_unity_version", "")).strip()
    normalized_entries = [
        (str(version_key), details)
        for version_key, details in uploads.items()
        if isinstance(details, dict)
    ]
    if recommended_version_prefix:
        for version_key, details in normalized_entries:
            if version_key.startswith(recommended_version_prefix):
                return version_key, details
    normalized_entries.sort(key=lambda item: _unity_version_sort_key(item[0]), reverse=True)
    return normalized_entries[0]


def build_unity_owned_install_context(
    *,
    product_id: int | str,
    local_package_path: Path,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    timeout: float = 30.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    tokens = load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    if not tokens:
        raise RuntimeError("Unity Hub tokens are not available. Open Unity Hub once and sign in before building owned install context.")

    product_key = str(product_id).strip()
    product_detail = get_unity_product_detail(
        product_key,
        tokens=tokens,
        api_root=api_root,
        timeout=timeout,
    )
    update_map = get_unity_product_update_info(
        product_key,
        tokens=tokens,
        api_root=api_root,
        timeout=timeout,
    )
    update_info = update_map.get(product_key, {}) if isinstance(update_map, dict) else {}
    legacy_detail = get_unity_legacy_download_detail(
        product_key,
        tokens=tokens,
        api_root=api_root,
        timeout=timeout,
    )
    selected_version, upload = _pick_unity_upload(product_detail, update_info if isinstance(update_info, dict) else {})

    version_id = 0
    try:
        version_id = int(product_detail.get("versionId", 0) or 0)
    except Exception:
        version_id = 0

    upload_id = 0
    try:
        upload_id = int(legacy_detail.get("upload_id", 0) or update_info.get("recommended_upload_id", 0) or 0)
    except Exception:
        upload_id = 0

    return {
        "productId": int(product_key),
        "localPackagePath": str(Path(local_package_path)),
        "uploadId": upload_id,
        "versionId": version_id,
        "versionString": str(product_detail.get("versionString", "")).strip(),
        "supportedVersion": str(update_info.get("recommended_min_unity_version", "")).strip() if isinstance(update_info, dict) else "",
        "selectedUploadVersion": selected_version,
        "displayName": str(product_detail.get("displayName", "") or product_detail.get("name", "")).strip(),
        "packageName": str(
            legacy_detail.get("filename_safe_package_name", "")
            or product_detail.get("packageName", "")
            or product_detail.get("displayName", "")
            or product_detail.get("name", "")
        ).strip(),
        "publisherName": str(
            legacy_detail.get("filename_safe_publisher_name", "")
            or product_detail.get("publisherName", "")
        ).strip(),
        "publisherSupportUrl": str(product_detail.get("publisherSupportUrl", "")).strip(),
        "publisherWebsiteUrl": str(product_detail.get("publisherWebsiteUrl", "")).strip(),
        "categoryName": str(
            legacy_detail.get("filename_safe_category_name", "")
            or product_detail.get("category", "")
        ).strip(),
        "description": str(product_detail.get("description", "")).strip(),
        "firstPublishedDate": str(product_detail.get("firstPublishedDate", "")).strip(),
        "publishedDate": str(product_detail.get("publishedDate", "")).strip(),
        "publishNotes": str(product_detail.get("publishNotes", "")).strip(),
        "assetStoreProductUrl": str(product_detail.get("assetStoreProductUrl", "")).strip(),
        "assetStorePublisherUrl": str(product_detail.get("assetStorePublisherUrl", "")).strip(),
        "state": str(product_detail.get("state", "")).strip(),
        "downloadUrl": str(legacy_detail.get("url", "")).strip(),
        "downloadKey": str(legacy_detail.get("key", "") or upload.get("downloadS3key", "")).strip(),
        "purchaseTime": "",
        "tags": [],
    }


def download_unity_owned_package(
    *,
    product_id: int | str,
    output_dir: Path,
    api_root: str = DEFAULT_UNITY_PACKAGE_API_ROOT,
    cdn_root: str = DEFAULT_UNITY_ASSETSTORE_CDN_ROOT,
    timeout: float = 60.0,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    resolved_output_dir = ensure_dir(output_dir)
    tokens = load_unity_hub_tokens(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    if not tokens:
        raise RuntimeError("Unity Hub tokens are not available. Open Unity Hub once and sign in before downloading owned packages.")

    product_key = str(product_id).strip()
    product_detail = get_unity_product_detail(
        product_key,
        tokens=tokens,
        api_root=api_root,
        timeout=timeout,
    )
    update_map = get_unity_product_update_info(
        product_key,
        tokens=tokens,
        api_root=api_root,
        timeout=timeout,
    )
    legacy_detail = get_unity_legacy_download_detail(
        product_key,
        tokens=tokens,
        api_root=api_root,
        timeout=timeout,
    )
    update_info = update_map.get(product_key, {}) if isinstance(update_map, dict) else {}
    selected_version, upload = _pick_unity_upload(product_detail, update_info if isinstance(update_info, dict) else {})
    download_s3key = str(upload.get("downloadS3key", "")).strip()
    upload_s3key = str(upload.get("uploadS3key", "")).strip()
    legacy_download_url = str(legacy_detail.get("url", "")).strip()
    legacy_download_key = str(legacy_detail.get("key", "")).strip()
    if not download_s3key and not legacy_download_url:
        raise RuntimeError(f"Unity product {product_key} did not expose a downloadable upload entry.")

    package_name = Path(upload_s3key).name if upload_s3key else ""
    if not package_name:
        slug = str(product_detail.get("slug", "")).strip() or f"unity_asset_{product_key}"
        package_name = f"{slug}.unitypackage"
    else:
        slug = str(product_detail.get("slug", "")).strip()
    package_name = _shorten_unitypackage_filename(
        package_name=package_name,
        product_id=product_key,
        slug=slug,
        selected_version=selected_version,
    )
    output_path = resolved_output_dir / package_name
    if legacy_download_url:
        request_url = legacy_download_url
    else:
        request_url = f"{cdn_root.rstrip('/')}/{download_s3key.lstrip('/')}?access_token={quote(str(tokens.get('accessToken', '')).strip())}"
    response = requests.get(request_url, stream=True, timeout=timeout)
    response.raise_for_status()

    raw_chunks: list[bytes] = []
    bytes_written = 0
    for chunk in response.iter_content(chunk_size=1024 * 256):
        if not chunk:
            continue
        raw_chunks.append(chunk)
        bytes_written += len(chunk)

    raw_blob = b"".join(raw_chunks)
    final_blob, decrypted_with_legacy_key = _decrypt_unity_assetstore_blob(raw_blob, legacy_download_key)
    with output_path.open("wb") as handle:
        handle.write(final_blob)

    expected_bytes = int(upload.get("downloadSize", 0) or response.headers.get("Content-Length", 0) or 0)
    return {
        "product_id": product_key,
        "display_name": str(product_detail.get("displayName", "") or product_detail.get("name", "")).strip(),
        "slug": str(product_detail.get("slug", "")).strip(),
        "api_root": api_root,
        "cdn_root": cdn_root,
        "selected_upload_version": selected_version,
        "recommended_upload_id": str(update_info.get("recommended_upload_id", "")).strip() if isinstance(update_info, dict) else "",
        "recommended_min_unity_version": str(update_info.get("recommended_min_unity_version", "")).strip() if isinstance(update_info, dict) else "",
        "download_s3key": download_s3key,
        "upload_s3key": upload_s3key,
        "legacy_download_url": legacy_download_url,
        "legacy_download_key": legacy_download_key,
        "legacy_upload_id": str(legacy_detail.get("upload_id", "")).strip(),
        "legacy_filename_safe_package_name": str(legacy_detail.get("filename_safe_package_name", "")).strip(),
        "legacy_filename_safe_publisher_name": str(legacy_detail.get("filename_safe_publisher_name", "")).strip(),
        "legacy_filename_safe_category_name": str(legacy_detail.get("filename_safe_category_name", "")).strip(),
        "request_url": request_url,
        "output_path": str(output_path),
        "bytes_written": bytes_written,
        "final_bytes_written": len(final_blob),
        "expected_bytes": expected_bytes,
        "content_type": str(response.headers.get("Content-Type", "")).strip(),
        "decrypted_with_legacy_key": decrypted_with_legacy_key,
    }


def build_unity_hub_status(
    *,
    projects_path: Path | None = None,
    cache_roots: tuple[Path, ...] | None = None,
    local_state_path: Path | None = None,
    encrypted_tokens_path: Path | None = None,
) -> dict[str, Any]:
    projects = list_unity_hub_projects(projects_path)
    cache_report = scan_unity_asset_cache(cache_roots)
    installs = [item.to_dict() for item in list_unity_installations()]
    hub_executable = detect_unity_hub_executable()
    recommended_project = projects[0] if projects else {}
    auth = _build_unity_hub_auth_report(
        local_state_path=local_state_path,
        encrypted_tokens_path=encrypted_tokens_path,
    )
    return {
        "projects_path": str(projects_path if projects_path is not None else DEFAULT_UNITY_HUB_PROJECTS_PATH),
        "project_count": len(projects),
        "projects": projects,
        "recommended_project_path": str(recommended_project.get("path", "")),
        "recommended_project_title": str(recommended_project.get("title", "")),
        "unity_hub_executable_path": str(hub_executable) if hub_executable else "",
        "unity_install_count": len(installs),
        "unity_installations": installs,
        "cache": cache_report,
        "auth": auth,
    }


def render_unity_hub_status_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Unity Hub Status",
        "",
        f"- Projects file: `{report.get('projects_path', '')}`",
        f"- Detected projects: `{report.get('project_count', 0)}`",
        f"- Recommended project: `{report.get('recommended_project_title', '')}`",
        f"- Recommended project path: `{report.get('recommended_project_path', '')}`",
        f"- Unity Hub executable: `{report.get('unity_hub_executable_path', '')}`",
        f"- Unity installs: `{report.get('unity_install_count', 0)}`",
        f"- Hub tokens available: `{str(bool(report.get('auth', {}).get('tokens_available'))).lower()}`",
        f"- Access token expired: `{str(bool(report.get('auth', {}).get('access_token_expired'))).lower()}`",
        "",
        "## Projects",
        "",
    ]
    for project in report.get("projects", []) or []:
        lines.append(
            f"- {project.get('title', '')} | version=`{project.get('version', '')}` | exists=`{str(bool(project.get('exists'))).lower()}` | `{project.get('path', '')}`"
        )
    lines.extend(
        [
            "",
            "## Cache",
            "",
            f"- Existing cache roots: `{len(report.get('cache', {}).get('existing_cache_roots', []))}`",
            f"- Cached files sampled: `{report.get('cache', {}).get('cached_file_count', 0)}`",
            f"- Cached unitypackage files: `{report.get('cache', {}).get('cached_unitypackage_count', 0)}`",
            "",
        ]
    )
    for entry in report.get("cache", {}).get("cached_files", [])[:20]:
        lines.append(f"- `{entry.get('name', '')}` | `{entry.get('path', '')}`")
    lines.append("")
    return "\n".join(lines)


def _read_unity_claim_state(browser_job_spec: Path) -> dict[str, Any]:
    exec_root = browser_job_spec.parent / "playwright_exec"
    candidate_paths: list[Path] = []
    direct_path = exec_root / "unity_claim_state.json"
    if direct_path.exists():
        candidate_paths.append(direct_path)
    if exec_root.exists():
        nested_paths = sorted(
            exec_root.glob("**/unity_claim_state.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        candidate_paths.extend(path for path in nested_paths if path not in candidate_paths)

    for claim_state_path in candidate_paths:
        try:
            payload = json.loads(claim_state_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _claimed_or_owned(claim_state: dict[str, Any]) -> bool:
    return bool(
        claim_state.get("purchased")
        or claim_state.get("openInUnity")
        or claim_state.get("myAssetsContainsProduct")
    )


def _read_intake_handoff_state(*, game_scope: str, pack_id: str) -> dict[str, Any]:
    pack_root = asset_library_root() / "publish" / "flax_intake" / game_scope / pack_id
    packet_path = pack_root / "packet.json"
    provenance_path = pack_root / "provenance.json"
    handoff_receipt_path = pack_root / "handoff_receipt.json"

    payload: dict[str, Any] = {
        "packet_path": str(packet_path) if packet_path.exists() else "",
        "provenance_path": str(provenance_path) if provenance_path.exists() else "",
        "handoff_receipt_path": str(handoff_receipt_path) if handoff_receipt_path.exists() else "",
        "reviewed_packet_ready": packet_path.exists(),
        "handoff_ready": False,
        "auto_intake_pass": False,
        "intake_status": "claim_pending_payload",
        "receipt_status": "",
        "receipt_written_at": "",
    }
    if not handoff_receipt_path.exists():
        if packet_path.exists():
            payload["intake_status"] = "reviewed_packet_ready"
        return payload

    try:
        receipt = json.loads(handoff_receipt_path.read_text(encoding="utf-8"))
    except Exception:
        payload["intake_status"] = "handoff_receipt_invalid"
        return payload

    if not isinstance(receipt, dict):
        payload["intake_status"] = "handoff_receipt_invalid"
        return payload

    payload["receipt_status"] = str(receipt.get("status", "")).strip()
    payload["receipt_written_at"] = str(receipt.get("written_at", "")).strip()
    payload["auto_intake_pass"] = bool(receipt.get("pass"))
    payload["handoff_ready"] = bool(receipt.get("pass"))
    payload["intake_status"] = "handoff_ready" if bool(receipt.get("pass")) else (str(receipt.get("status", "")).strip() or "handoff_failed")
    return payload


def _build_ingest_wave_powershell(
    *,
    project_path: Path,
    editor_path_hint: str,
    unity_hub_path_hint: str,
    wave_json_name: str = "unity_project_ingest_wave.json",
) -> str:
    return "\n".join(
        [
            "param(",
            f"  [string]$ProjectPath = \"{project_path}\",",
            f"  [string]$UnityEditorPath = \"{editor_path_hint or '<set Unity.exe path>'}\",",
            f"  [string]$UnityHubPath = \"{unity_hub_path_hint or '<set Unity Hub.exe path>'}\",",
            "  [switch]$SkipEditorLaunch,",
            "  [switch]$UseHubProtocolFallback,",
            "  [switch]$UseGenericProtocolFallback,",
            "  [switch]$UseLegacyProtocolFallback,",
            "  [int]$EditorOpenWaitSeconds = 25,",
            "  [int]$PerAssetDelaySeconds = 8",
            ")",
            "",
            '$ErrorActionPreference = "Stop"',
            '$wave = Get-Content (Join-Path $PSScriptRoot "' + wave_json_name + '") -Raw | ConvertFrom-Json',
            'if (!(Test-Path $ProjectPath)) { throw "Unity project path not found: $ProjectPath" }',
            'if (-not $SkipEditorLaunch) {',
            '  if (!(Test-Path $UnityEditorPath)) { throw "Unity editor executable not found: $UnityEditorPath" }',
            '  Start-Process -FilePath $UnityEditorPath -ArgumentList @("-projectPath", $ProjectPath)',
            '  Start-Sleep -Seconds $EditorOpenWaitSeconds',
            '}',
            'foreach ($item in $wave.items) {',
            '  Write-Host ("Opening Unity handoff for {0} ({1})" -f $item.name, $item.asset_id)',
            '  if ($item.protocol_url) {',
            '    Start-Process $item.protocol_url',
            '  }',
            '  if ($UseGenericProtocolFallback -and $item.generic_protocol_url -and ($item.generic_protocol_url -ne $item.protocol_url)) {',
            '    Start-Process $item.generic_protocol_url',
            '  }',
            '  if ($UseHubProtocolFallback -and (Test-Path $UnityHubPath) -and $item.protocol_url) {',
            '    Start-Process -FilePath $UnityHubPath -ArgumentList @($item.protocol_url)',
            '  }',
            '  if ($UseLegacyProtocolFallback -and $item.legacy_protocol_url) {',
            '    Start-Process $item.legacy_protocol_url',
            '  }',
            '  Start-Sleep -Seconds $PerAssetDelaySeconds',
            '}',
            'Write-Host "Finish package download/import inside Unity Package Manager > My Assets, then run the per-pack export runners in the emitted wave folder."',
            "",
        ]
    )


def emit_unity_project_ingest_wave(
    *,
    wave_json: Path,
    project_path: Path | None = None,
    game_scope: str = "arena_shared",
    best_first_only: bool = False,
    exportable_only: bool = False,
    categories: tuple[str, ...] = (),
    pack_ids: tuple[str, ...] = (),
    limit: int | None = None,
    claimed_or_owned_only: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    report = json.loads(Path(wave_json).read_text(encoding="utf-8"))
    asset_donor_only = best_first_only and not categories and not pack_ids
    selected = select_unity_download_wave_jobs(
        report,
        best_first_only=best_first_only,
        exportable_only=exportable_only or asset_donor_only,
        asset_donor_only=asset_donor_only,
        categories=categories,
        pack_ids=pack_ids,
        limit=limit,
    )

    if project_path is None:
        status = build_unity_hub_status()
        recommended = str(status.get("recommended_project_path", "")).strip()
        if not recommended:
            raise ValueError("No Unity Hub project detected. Pass --project-path explicitly.")
        resolved_project_path = Path(recommended)
    else:
        resolved_project_path = Path(project_path)

    actual_output_dir = output_dir if output_dir is not None else Path(wave_json).parent / "unity_project_ingest_wave"
    ensure_dir(actual_output_dir)
    export_runner_root = actual_output_dir / "unity_export_runners"
    ensure_dir(export_runner_root)

    detected_installs = list_unity_installations()
    editor_path_hint = str(detected_installs[0].editor_path) if detected_installs and detected_installs[0].editor_path else ""
    unity_hub_path_hint = str(detect_unity_hub_executable() or "")
    cloud_project_id = read_unity_project_cloud_project_id(resolved_project_path)

    items: list[dict[str, Any]] = []
    for item in selected:
        asset_id = str(item.get("asset_id") or _extract_unity_asset_id(str(item.get("url", "")))).strip()
        browser_job_spec = Path(str(item.get("browser_job_spec", "")))
        claim_state = _read_unity_claim_state(browser_job_spec)
        runner_output_dir = export_runner_root / str(item.get("pack_id", "unity_item"))
        local_unitypackage = _find_downloaded_unitypackage(
            pack_id=str(item.get("pack_id", "")).strip(),
            asset_id=asset_id,
        )
        claimed_or_owned = _claimed_or_owned(claim_state) or local_unitypackage is not None
        if claimed_or_owned_only and not claimed_or_owned:
            continue
        install_context_path = Path()
        install_context_error = ""
        if local_unitypackage is not None and asset_id:
            try:
                install_context = build_unity_owned_install_context(
                    product_id=asset_id,
                    local_package_path=local_unitypackage,
                )
                install_context_path = runner_output_dir / "unity_owned_install_context.json"
                write_json(install_context_path, install_context)
            except Exception as exc:
                install_context_error = str(exc)
        runner = emit_unity_export_runner(
            pack_id=str(item.get("pack_id", "")).strip(),
            game_scope=game_scope,
            source_url=str(item.get("url", "")).strip(),
            license_note="Licensed Unity Asset Store package claimed/owned by operator.",
            project_path=str(resolved_project_path),
            package_root="Assets",
            asset_paths=tuple(),
            unitypackage_paths=(str(local_unitypackage),) if local_unitypackage is not None else tuple(),
            source_package_name=str(item.get("name", "")).strip(),
            asset_kind=str(item.get("asset_kind", "prop")).strip() or "prop",
            output_dir=runner_output_dir,
        )
        intake_state = _read_intake_handoff_state(
            game_scope=game_scope,
            pack_id=str(item.get("pack_id", "")).strip(),
        )
        items.append(
            {
                "name": str(item.get("name", "")).strip(),
                "pack_id": str(item.get("pack_id", "")).strip(),
                "category": str(item.get("category", "")).strip(),
                "asset_id": asset_id,
                "url": str(item.get("url", "")).strip(),
                "cloud_project_id": cloud_project_id,
                "protocol_url": (
                    f"com.unity.editor://editor/project/{cloud_project_id}/package-manager/content/{asset_id}"
                    if asset_id and cloud_project_id
                    else f"com.unity.editor://editor/package-manager/content/{asset_id}" if asset_id else ""
                ),
                "generic_protocol_url": f"com.unity.editor://editor/package-manager/content/{asset_id}" if asset_id else "",
                "legacy_protocol_url": f"com.unity3d.kharma:content/{asset_id}" if asset_id else "",
                "best_first_wave": bool(item.get("best_first_wave")),
                "claimed_or_owned": claimed_or_owned,
                "local_unitypackage_path": str(local_unitypackage) if local_unitypackage is not None else "",
                "unity_owned_install_context_json": str(install_context_path) if install_context_path else "",
                "unity_owned_install_context_error": install_context_error,
                "unity_claim_state": claim_state,
                "browser_job_spec": str(browser_job_spec),
                "unity_export_runner_json": str(runner.runner_job_path),
                "unity_export_runner_ps1": str(runner.powershell_path),
                "payload_target_path": str(runner.payload_target_path),
                "packet_path": str(intake_state.get("packet_path", "")),
                "provenance_path": str(intake_state.get("provenance_path", "")),
                "handoff_receipt_path": str(intake_state.get("handoff_receipt_path", "")),
                "reviewed_packet_ready": bool(intake_state.get("reviewed_packet_ready")),
                "handoff_ready": bool(intake_state.get("handoff_ready")),
                "auto_intake_pass": bool(intake_state.get("auto_intake_pass")),
                "intake_status": str(intake_state.get("intake_status", "")),
                "receipt_status": str(intake_state.get("receipt_status", "")),
                "receipt_written_at": str(intake_state.get("receipt_written_at", "")),
            }
        )

    summary = {
        "selected_jobs": len(items),
        "claimed_or_owned": sum(1 for item in items if bool(item.get("claimed_or_owned"))),
        "missing_asset_id": sum(1 for item in items if not str(item.get("asset_id", "")).strip()),
        "reviewed_packet_ready": sum(1 for item in items if bool(item.get("reviewed_packet_ready"))),
        "handoff_ready": sum(1 for item in items if bool(item.get("handoff_ready"))),
        "project_ingest_required": sum(1 for item in items if not bool(item.get("handoff_ready"))),
    }
    wave_report = {
        "wave_json": str(wave_json),
        "output_dir": str(actual_output_dir),
        "project_path": str(resolved_project_path),
        "editor_path_hint": editor_path_hint,
        "unity_hub_path_hint": unity_hub_path_hint,
        "cloud_project_id": cloud_project_id,
        "claimed_or_owned_only": claimed_or_owned_only,
        "summary": summary,
        "items": items,
    }
    write_json(actual_output_dir / "unity_project_ingest_wave.json", wave_report)
    write_text(
        actual_output_dir / "run_unity_project_ingest.ps1",
        _build_ingest_wave_powershell(
            project_path=resolved_project_path,
            editor_path_hint=editor_path_hint,
            unity_hub_path_hint=unity_hub_path_hint,
        ),
    )
    write_text(
        actual_output_dir / "unity_project_ingest_wave.md",
        render_unity_project_ingest_wave_markdown(wave_report),
    )
    return wave_report


def render_unity_project_ingest_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Unity Project Ingest Wave",
        "",
        f"- Wave source: `{report.get('wave_json', '')}`",
        f"- Project path: `{report.get('project_path', '')}`",
        f"- Unity editor hint: `{report.get('editor_path_hint', '')}`",
        f"- Unity Hub hint: `{report.get('unity_hub_path_hint', '')}`",
        f"- Cloud project id: `{report.get('cloud_project_id', '')}`",
        f"- Selected jobs: `{summary.get('selected_jobs', 0)}`",
        f"- Claimed or owned: `{summary.get('claimed_or_owned', 0)}`",
        f"- Missing asset ids: `{summary.get('missing_asset_id', 0)}`",
        f"- Reviewed packets ready: `{summary.get('reviewed_packet_ready', 0)}`",
        f"- Durable handoffs ready: `{summary.get('handoff_ready', 0)}`",
        f"- Project ingest still required: `{summary.get('project_ingest_required', 0)}`",
        "",
        "## Items",
        "",
    ]
    for item in report.get("items", []) or []:
        lines.append(
            f"- {item.get('name', '')} | pack=`{item.get('pack_id', '')}` | claimed=`{str(bool(item.get('claimed_or_owned'))).lower()}` | intake=`{item.get('intake_status', '')}` | handoff=`{str(bool(item.get('handoff_ready'))).lower()}` | protocol=`{item.get('protocol_url', '')}` | generic=`{item.get('generic_protocol_url', '')}` | legacy=`{item.get('legacy_protocol_url', '')}`"
        )
    lines.append("")
    return "\n".join(lines)
