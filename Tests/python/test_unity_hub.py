from __future__ import annotations

import json
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from assetboy.providers.unity_hub import (
    _decrypt_unity_assetstore_blob,
    build_unity_owned_install_context,
    build_unity_hub_status,
    build_unity_owned_library_map,
    detect_unity_hub_executable,
    download_unity_owned_lightweights,
    download_unity_owned_wave,
    download_unity_owned_package,
    emit_unity_project_ingest_wave,
    get_unity_legacy_download_detail,
    list_unity_hub_projects,
    read_unity_project_cloud_project_id,
)


class UnityHubTests(unittest.TestCase):
    def test_list_unity_hub_projects_reads_projects_v1_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            projects_path = Path(temp_dir) / "projects-v1.json"
            project_dir = Path(temp_dir) / "MyProject"
            project_dir.mkdir()
            payload = {
                "schema_version": "v1",
                "data": {
                    str(project_dir): {
                        "title": "My Project",
                        "path": str(project_dir),
                        "version": "6000.3.11f1",
                        "lastModified": 1234,
                    }
                },
            }
            projects_path.write_text(json.dumps(payload), encoding="utf-8")

            projects = list_unity_hub_projects(projects_path)

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["title"], "My Project")
        self.assertTrue(projects[0]["exists"])

    def test_build_unity_hub_status_reports_projects_and_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "MyProject"
            project_dir.mkdir()
            projects_path = root / "projects-v1.json"
            cache_root = root / "Asset Store-5.x"
            cache_root.mkdir()
            (cache_root / "dummy.unitypackage").write_text("x", encoding="utf-8")
            projects_path.write_text(
                json.dumps(
                    {
                        "schema_version": "v1",
                        "data": {
                            str(project_dir): {
                                "title": "My Project",
                                "path": str(project_dir),
                                "version": "6000.3.11f1",
                                "lastModified": 999,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch("assetboy.providers.unity_hub.list_unity_installations", return_value=()):
                with patch("assetboy.providers.unity_hub.detect_unity_hub_executable", return_value=root / "Unity Hub.exe"):
                    report = build_unity_hub_status(projects_path=projects_path, cache_roots=(cache_root,))

        self.assertEqual(report["project_count"], 1)
        self.assertEqual(report["cache"]["cached_unitypackage_count"], 1)
        self.assertEqual(report["recommended_project_path"], str(project_dir))
        self.assertEqual(report["unity_hub_executable_path"], str(root / "Unity Hub.exe"))
        self.assertIn("auth", report)

    def test_detect_unity_hub_executable_picks_first_existing_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "Missing Unity Hub.exe"
            existing = root / "Unity Hub.exe"
            existing.write_text("hub", encoding="utf-8")

            detected = detect_unity_hub_executable((missing, existing))

        self.assertEqual(detected, existing.resolve())

    def test_read_unity_project_cloud_project_id_from_project_settings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "MyProject"
            settings_dir = project_dir / "ProjectSettings"
            settings_dir.mkdir(parents=True)
            (settings_dir / "ProjectSettings.asset").write_text(
                "PlayerSettings:\n  cloudProjectId: 56e86805-7813-4051-bebf-bd3bb82894f7\n",
                encoding="utf-8",
            )

            cloud_project_id = read_unity_project_cloud_project_id(project_dir)

        self.assertEqual(cloud_project_id, "56e86805-7813-4051-bebf-bd3bb82894f7")

    def test_emit_unity_project_ingest_wave_writes_wave_and_runner_refs(self) -> None:
        report = {
            "items": [
                {
                    "name": "Human Melee Animations FREE",
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "category": "animation",
                    "asset_kind": "character",
                    "best_first_wave": True,
                    "exportable": True,
                    "asset_id": "165785",
                    "url": "https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785",
                }
            ],
            "browser_jobs": [
                {
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "browser_job_spec": "C:/wave/anm/browser_job.json",
                }
            ],
        }
        fake_runner = SimpleNamespace(
            runner_job_path=Path("C:/wave/runner/unity_export_runner.json"),
            powershell_path=Path("C:/wave/runner/run_unity_export.ps1"),
            payload_target_path=Path("C:/wave/payload"),
        )
        fake_install_context = {
            "productId": 165785,
            "localPackagePath": "C:/downloads/HumanMelee.unitypackage",
            "downloadUrl": "https://assetstorev1-prd-cdn.unity3d.com/download/example",
            "downloadKey": "legacy-download-key",
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wave_json = root / "unity_download_wave.json"
            project_path = root / "MyProject"
            project_path.mkdir()
            wave_json.write_text(json.dumps(report), encoding="utf-8")
            with patch("assetboy.providers.unity_hub.emit_unity_export_runner", return_value=fake_runner):
                with patch("assetboy.providers.unity_hub._find_downloaded_unitypackage", return_value=Path("C:/downloads/HumanMelee.unitypackage")):
                    with patch("assetboy.providers.unity_hub.build_unity_owned_install_context", return_value=fake_install_context):
                        with patch("assetboy.providers.unity_hub.list_unity_installations", return_value=()):
                            with patch(
                                "assetboy.providers.unity_hub.detect_unity_hub_executable",
                                return_value=Path("C:/Program Files/Unity Hub/Unity Hub.exe"),
                            ):
                                ingest = emit_unity_project_ingest_wave(
                                    wave_json=wave_json,
                                    project_path=project_path,
                                    output_dir=root / "ingest_wave",
                                )
                        self.assertEqual(ingest["summary"]["selected_jobs"], 1)
                        self.assertEqual(ingest["project_path"], str(project_path))
                        self.assertEqual(ingest["unity_hub_path_hint"], "C:\\Program Files\\Unity Hub\\Unity Hub.exe")
                        self.assertEqual(ingest["cloud_project_id"], "")
                        self.assertEqual(
                            ingest["items"][0]["local_unitypackage_path"],
                            "C:\\downloads\\HumanMelee.unitypackage",
                        )
                        self.assertTrue(ingest["items"][0]["unity_owned_install_context_json"].endswith("unity_owned_install_context.json"))
                        self.assertEqual(ingest["items"][0]["unity_owned_install_context_error"], "")
                        self.assertEqual(
                            ingest["items"][0]["protocol_url"],
                            "com.unity.editor://editor/package-manager/content/165785",
                        )
                        self.assertEqual(
                            ingest["items"][0]["generic_protocol_url"],
                            "com.unity.editor://editor/package-manager/content/165785",
                        )
                        self.assertEqual(
                            ingest["items"][0]["legacy_protocol_url"],
                            "com.unity3d.kharma:content/165785",
                        )
                        self.assertTrue((root / "ingest_wave" / "unity_project_ingest_wave.json").exists())
                        self.assertTrue((root / "ingest_wave" / "run_unity_project_ingest.ps1").exists())
                        script_text = (root / "ingest_wave" / "run_unity_project_ingest.ps1").read_text(encoding="utf-8")
                        self.assertIn('Start-Process -FilePath $UnityEditorPath -ArgumentList @("-projectPath", $ProjectPath)', script_text)
                        self.assertIn('[string]$UnityHubPath = "C:\\Program Files\\Unity Hub\\Unity Hub.exe"', script_text)
                        self.assertIn("[switch]$UseHubProtocolFallback,", script_text)
                        self.assertIn("[switch]$UseGenericProtocolFallback,", script_text)
                        self.assertIn('Start-Process $item.protocol_url', script_text)
                        self.assertIn('Start-Process $item.generic_protocol_url', script_text)
                        self.assertIn('Start-Process -FilePath $UnityHubPath -ArgumentList @($item.protocol_url)', script_text)
                        self.assertTrue((root / "ingest_wave" / "unity_export_runners" / "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785" / "unity_owned_install_context.json").exists())

    def test_emit_unity_project_ingest_wave_claimed_or_owned_only_filters_nested_claim_state(self) -> None:
        report = {
            "items": [
                {
                    "name": "Claimed Pack",
                    "pack_id": "SHARED_UNITY_ANM_CLAIMED_01",
                    "category": "animation",
                    "asset_kind": "animation",
                    "best_first_wave": True,
                    "exportable": True,
                    "asset_id": "165785",
                    "url": "https://assetstore.unity.com/packages/animation/claimed-pack-165785",
                },
                {
                    "name": "Pending Pack",
                    "pack_id": "SHARED_UNITY_ANM_PENDING_02",
                    "category": "animation",
                    "asset_kind": "animation",
                    "best_first_wave": True,
                    "exportable": True,
                    "asset_id": "265786",
                    "url": "https://assetstore.unity.com/packages/animation/pending-pack-265786",
                },
            ],
            "browser_jobs": [
                {
                    "pack_id": "SHARED_UNITY_ANM_CLAIMED_01",
                    "browser_job_spec": "C:/wave/claimed/browser_job.json",
                },
                {
                    "pack_id": "SHARED_UNITY_ANM_PENDING_02",
                    "browser_job_spec": "C:/wave/pending/browser_job.json",
                },
            ],
        }
        fake_runner = SimpleNamespace(
            runner_job_path=Path("C:/wave/runner/unity_export_runner.json"),
            powershell_path=Path("C:/wave/runner/run_unity_export.ps1"),
            payload_target_path=Path("C:/wave/payload"),
        )
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wave_json = root / "unity_download_wave.json"
            project_path = root / "MyProject"
            project_path.mkdir()
            claimed_job = root / "claimed" / "browser_job.json"
            pending_job = root / "pending" / "browser_job.json"
            claimed_job.parent.mkdir(parents=True, exist_ok=True)
            pending_job.parent.mkdir(parents=True, exist_ok=True)
            claimed_job.write_text(json.dumps({"pack_id": "SHARED_UNITY_ANM_CLAIMED_01"}), encoding="utf-8")
            pending_job.write_text(json.dumps({"pack_id": "SHARED_UNITY_ANM_PENDING_02"}), encoding="utf-8")
            claimed_state = claimed_job.parent / "playwright_exec" / "unity_asset_store" / "claimed" / "browser_job" / "unity_claim_state.json"
            pending_state = pending_job.parent / "playwright_exec" / "unity_asset_store" / "pending" / "browser_job" / "unity_claim_state.json"
            claimed_state.parent.mkdir(parents=True, exist_ok=True)
            pending_state.parent.mkdir(parents=True, exist_ok=True)
            claimed_state.write_text(json.dumps({"purchased": True, "openInUnity": True}), encoding="utf-8")
            pending_state.write_text(json.dumps({"purchased": False, "openInUnity": False}), encoding="utf-8")
            packet_dir = root / "asset_library" / "publish" / "flax_intake" / "arena_shared" / "SHARED_UNITY_ANM_CLAIMED_01"
            packet_dir.mkdir(parents=True, exist_ok=True)
            (packet_dir / "packet.json").write_text("{}", encoding="utf-8")
            (packet_dir / "provenance.json").write_text("{}", encoding="utf-8")
            (packet_dir / "handoff_receipt.json").write_text(
                json.dumps(
                    {
                        "pass": True,
                        "status": "validated_pending_mcp",
                        "written_at": "2026-04-04T20:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            report["browser_jobs"][0]["browser_job_spec"] = str(claimed_job)
            report["browser_jobs"][1]["browser_job_spec"] = str(pending_job)
            wave_json.write_text(json.dumps(report), encoding="utf-8")

            with patch("assetboy.providers.unity_hub.asset_library_root", return_value=root / "asset_library"):
                with patch("assetboy.providers.unity_hub.emit_unity_export_runner", return_value=fake_runner):
                    with patch("assetboy.providers.unity_hub._find_downloaded_unitypackage", return_value=None):
                        with patch("assetboy.providers.unity_hub.list_unity_installations", return_value=()):
                            with patch("assetboy.providers.unity_hub.detect_unity_hub_executable", return_value=None):
                                ingest = emit_unity_project_ingest_wave(
                                    wave_json=wave_json,
                                    project_path=project_path,
                                    claimed_or_owned_only=True,
                                    output_dir=root / "ingest_wave",
                                )

        self.assertTrue(ingest["claimed_or_owned_only"])
        self.assertEqual(ingest["summary"]["selected_jobs"], 1)
        self.assertEqual(ingest["summary"]["claimed_or_owned"], 1)
        self.assertEqual(ingest["summary"]["reviewed_packet_ready"], 1)
        self.assertEqual(ingest["summary"]["handoff_ready"], 1)
        self.assertEqual(ingest["summary"]["project_ingest_required"], 0)
        self.assertEqual(len(ingest["items"]), 1)
        self.assertEqual(ingest["items"][0]["pack_id"], "SHARED_UNITY_ANM_CLAIMED_01")
        self.assertTrue(ingest["items"][0]["reviewed_packet_ready"])
        self.assertTrue(ingest["items"][0]["handoff_ready"])
        self.assertTrue(ingest["items"][0]["auto_intake_pass"])
        self.assertEqual(ingest["items"][0]["intake_status"], "handoff_ready")

    def test_build_unity_owned_library_map_uses_live_purchase_payload(self) -> None:
        purchase_payload = {
            "results": [
                {
                    "id": "18968396987816",
                    "packageId": 165785,
                    "displayName": "Human Melee Animations FREE",
                    "grantTime": "2026-03-14T11:01:04Z",
                    "isHidden": False,
                    "isPublisherAsset": False,
                    "tagging": [],
                }
            ]
        }
        with patch("assetboy.providers.unity_hub.load_unity_hub_tokens", return_value={"accessToken": "live-token"}):
            with patch("assetboy.providers.unity_hub._build_unity_hub_auth_report", return_value={"tokens_available": True}):
                with patch("assetboy.providers.unity_hub.list_unity_owned_assets", return_value=purchase_payload):
                    report = build_unity_owned_library_map(page_size=200, max_pages=2)

        self.assertEqual(report["owned_count"], 1)
        self.assertEqual(report["pages_fetched"], 1)
        self.assertEqual(report["items"][0]["package_id"], "165785")
        self.assertEqual(report["items"][0]["display_name"], "Human Melee Animations FREE")

    def test_get_unity_legacy_download_detail_reads_nested_download_payload(self) -> None:
        payload = {
            "result": {
                "download": {
                    "id": "165785",
                    "key": "legacy-download-key",
                    "upload_id": "825254",
                    "url": "https://assetstorev1-prd-cdn.unity3d.com/download/example",
                }
            }
        }
        with patch("assetboy.providers.unity_hub.load_unity_hub_tokens", return_value={"accessToken": "live-token"}):
            with patch("assetboy.providers.unity_hub._unity_api_get_json", return_value=payload):
                report = get_unity_legacy_download_detail("165785")

        self.assertEqual(report["key"], "legacy-download-key")
        self.assertEqual(report["upload_id"], "825254")
        self.assertEqual(report["url"], "https://assetstorev1-prd-cdn.unity3d.com/download/example")

    def test_build_unity_owned_install_context_prefers_legacy_download_metadata(self) -> None:
        product_detail = {
            "displayName": "Human Melee Animations FREE",
            "packageName": "Human Melee Animations FREE",
            "publisherName": "Kevin Iglesias",
            "publisherSupportUrl": "https://example.com/support",
            "publisherWebsiteUrl": "https://example.com",
            "category": "3D/Animations",
            "description": "Description",
            "firstPublishedDate": "2020-01-01T00:00:00Z",
            "publishedDate": "2026-01-01T00:00:00Z",
            "publishNotes": "Notes",
            "assetStoreProductUrl": "https://assetstore.unity.com/packages/example-165785",
            "assetStorePublisherUrl": "https://publisher.example.com",
            "state": "published",
            "versionId": 1180944,
            "versionString": "2.0.2",
            "uploads": {
                "6000.0.59f2": {
                    "downloadS3key": "download/old-key",
                    "uploadS3key": "package_upload/test/HumanMelee.unitypackage",
                }
            },
        }
        update_info = {"165785": {"recommended_min_unity_version": "6000.0.59", "recommended_upload_id": "825254"}}
        legacy_detail = {
            "url": "https://assetstorev1-prd-cdn.unity3d.com/download/example",
            "key": "legacy-download-key",
            "upload_id": "825254",
            "filename_safe_category_name": "Animation",
            "filename_safe_package_name": "Human Melee Animations FREE",
            "filename_safe_publisher_name": "Kevin Iglesias",
        }

        with TemporaryDirectory() as temp_dir:
            local_package = Path(temp_dir) / "HumanMelee.unitypackage"
            local_package.write_bytes(b"pkg")
            with patch("assetboy.providers.unity_hub.load_unity_hub_tokens", return_value={"accessToken": "live-token"}):
                with patch("assetboy.providers.unity_hub.get_unity_product_detail", return_value=product_detail):
                    with patch("assetboy.providers.unity_hub.get_unity_product_update_info", return_value=update_info):
                        with patch("assetboy.providers.unity_hub.get_unity_legacy_download_detail", return_value=legacy_detail):
                            context = build_unity_owned_install_context(
                                product_id="165785",
                                local_package_path=local_package,
                            )

        self.assertEqual(context["productId"], 165785)
        self.assertEqual(context["localPackagePath"], str(local_package))
        self.assertEqual(context["uploadId"], 825254)
        self.assertEqual(context["versionId"], 1180944)
        self.assertEqual(context["categoryName"], "Animation")
        self.assertEqual(context["downloadUrl"], "https://assetstorev1-prd-cdn.unity3d.com/download/example")
        self.assertEqual(context["downloadKey"], "legacy-download-key")

    def test_download_unity_owned_package_streams_to_output_dir(self) -> None:
        product_detail = {
            "displayName": "Human Melee Animations FREE",
            "slug": "human-melee-animations-free-165785",
            "uploads": {
                "6000.0.59f2": {
                    "downloadSize": "12",
                    "downloadS3key": "download/test-download-key",
                    "uploadS3key": "package_upload/test/HumanMelee.unitypackage",
                }
            },
        }
        update_info = {"165785": {"recommended_min_unity_version": "6000.0.59", "recommended_upload_id": "825254"}}
        legacy_detail = {
            "url": "https://assetstorev1-prd-cdn.unity3d.com/download/example",
            "key": "legacy-download-key",
            "upload_id": "825254",
            "filename_safe_category_name": "Animation",
            "filename_safe_package_name": "Human Melee Animations FREE",
            "filename_safe_publisher_name": "Kevin Iglesias",
        }

        class _FakeResponse:
            def __init__(self) -> None:
                self.headers = {"Content-Type": "application/vnd.unity.assetstore", "Content-Length": "12"}

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size: int = 0):
                _ = chunk_size
                yield b"hello "
                yield b"world!"

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            with patch("assetboy.providers.unity_hub.load_unity_hub_tokens", return_value={"accessToken": "live-token"}):
                with patch("assetboy.providers.unity_hub.get_unity_product_detail", return_value=product_detail):
                    with patch("assetboy.providers.unity_hub.get_unity_product_update_info", return_value=update_info):
                        with patch("assetboy.providers.unity_hub.get_unity_legacy_download_detail", return_value=legacy_detail):
                            with patch("assetboy.providers.unity_hub.requests.get", return_value=_FakeResponse()):
                                report = download_unity_owned_package(product_id="165785", output_dir=output_dir)

            self.assertEqual(report["display_name"], "Human Melee Animations FREE")
            self.assertEqual(report["selected_upload_version"], "6000.0.59f2")
            self.assertEqual(report["bytes_written"], 12)
            self.assertEqual(report["final_bytes_written"], 12)
            self.assertFalse(report["decrypted_with_legacy_key"])
            self.assertEqual(report["legacy_download_key"], "legacy-download-key")
            self.assertEqual(report["request_url"], "https://assetstorev1-prd-cdn.unity3d.com/download/example")
            self.assertTrue((output_dir / "HumanMelee.unitypackage").exists())

    def test_download_unity_owned_package_shortens_overlong_filename(self) -> None:
        product_detail = {
            "displayName": "Balancy",
            "slug": "balancy-run-liveops-with-smart-offers-game-events-improve-your-monetization",
            "uploads": {
                "2021.3.11f1": {
                    "downloadSize": "12",
                    "downloadS3key": "download/test-download-key",
                    "uploadS3key": (
                        "package_upload/test/"
                        "00128920_balancy-run-liveops-with-smart-offers-game-events-improve-your-m_2021-3-11_"
                        "91b9a910-5a3f-4d9f-8100-5f9c6c2f67e0.unitypackage"
                    ),
                }
            },
        }
        update_info = {"128920": {"recommended_min_unity_version": "2021.3.11", "recommended_upload_id": "999"}}
        legacy_detail = {
            "url": "https://assetstorev1-prd-cdn.unity3d.com/download/example",
            "key": "",
            "upload_id": "999",
            "filename_safe_category_name": "ToolsGameToolkits",
            "filename_safe_package_name": "Balancy",
            "filename_safe_publisher_name": "Balancy",
        }

        class _FakeResponse:
            def __init__(self) -> None:
                self.headers = {"Content-Type": "application/vnd.unity.assetstore", "Content-Length": "12"}

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size: int = 0):
                _ = chunk_size
                yield b"hello "
                yield b"world!"

        with TemporaryDirectory() as temp_dir:
            long_output_dir = Path(temp_dir) / ("x" * 140)
            with patch("assetboy.providers.unity_hub.load_unity_hub_tokens", return_value={"accessToken": "live-token"}):
                with patch("assetboy.providers.unity_hub.get_unity_product_detail", return_value=product_detail):
                    with patch("assetboy.providers.unity_hub.get_unity_product_update_info", return_value=update_info):
                        with patch("assetboy.providers.unity_hub.get_unity_legacy_download_detail", return_value=legacy_detail):
                            with patch("assetboy.providers.unity_hub.requests.get", return_value=_FakeResponse()):
                                report = download_unity_owned_package(product_id="128920", output_dir=long_output_dir)

            self.assertTrue(Path(report["output_path"]).exists())
            self.assertLess(len(Path(report["output_path"]).name), len(Path(product_detail["uploads"]["2021.3.11f1"]["uploadS3key"]).name))

    def test_decrypt_unity_assetstore_blob_unwraps_legacy_aes_cbc_payload(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except Exception:
            self.skipTest("cryptography unavailable")

        plaintext = gzip.compress(b"hello unity package")
        pad = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad]) * pad
        key = bytes(range(32))
        iv = bytes(range(32, 48))
        key_hex = (key + iv).hex()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()

        decrypted, changed = _decrypt_unity_assetstore_blob(ciphertext, key_hex)

        self.assertTrue(changed)
        self.assertEqual(decrypted, plaintext)

    def test_download_unity_owned_wave_downloads_only_owned_matches(self) -> None:
        report = {
            "items": [
                {
                    "name": "Human Melee Animations FREE",
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "category": "animation",
                    "asset_id": "165785",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785",
                },
                {
                    "name": "Time Ghost: Environment",
                    "pack_id": "SHARED_UNITY_ENV_TIME_GHOST_ENVIRONMENT_298911",
                    "category": "environment",
                    "asset_id": "298911",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/templates/tutorial-projects/time-ghost-environment-298911",
                },
            ],
            "browser_jobs": [
                {
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "browser_job_spec": "C:/wave/anm/browser_job.json",
                },
                {
                    "pack_id": "SHARED_UNITY_ENV_TIME_GHOST_ENVIRONMENT_298911",
                    "browser_job_spec": "C:/wave/env/browser_job.json",
                },
            ],
        }

        def _fake_download(*, product_id: int | str, output_dir: Path, timeout: float = 0, **_: object) -> dict[str, object]:
            _ = timeout
            output_dir.mkdir(parents=True, exist_ok=True)
            package_path = output_dir / f"{product_id}.unitypackage"
            package_path.write_bytes(b"pkg")
            return {
                "product_id": str(product_id),
                "output_path": str(package_path),
                "bytes_written": 3,
                "selected_upload_version": "6000.0.59f2",
            }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wave_json = root / "unity_download_wave.json"
            wave_json.write_text(json.dumps(report), encoding="utf-8")
            with patch(
                "assetboy.providers.unity_hub.build_unity_owned_library_map",
                return_value={"owned_count": 1, "pages_fetched": 1, "error": "", "items": [{"package_id": "165785"}]},
            ):
                with patch("assetboy.providers.unity_hub.download_unity_owned_package", side_effect=_fake_download):
                    wave_report = download_unity_owned_wave(
                        wave_json=wave_json,
                        best_first_only=True,
                        output_dir=root / "owned_wave",
                    )

        self.assertEqual(wave_report["summary"]["selected_jobs"], 2)
        self.assertEqual(wave_report["summary"]["owned_matches"], 1)
        self.assertEqual(wave_report["summary"]["downloaded"], 1)
        self.assertEqual(wave_report["summary"]["not_owned"], 1)
        downloaded = [item for item in wave_report["items"] if item["status"] == "downloaded"]
        self.assertEqual(len(downloaded), 1)
        self.assertTrue(downloaded[0]["output_path"].endswith("165785.unitypackage"))

    def test_download_unity_owned_wave_falls_back_to_cached_owned_map(self) -> None:
        report = {
            "items": [
                {
                    "name": "Human Melee Animations FREE",
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "category": "animation",
                    "asset_id": "165785",
                    "best_first_wave": True,
                    "exportable": True,
                    "url": "https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785",
                }
            ],
            "browser_jobs": [
                {
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "browser_job_spec": "C:/wave/anm/browser_job.json",
                }
            ],
        }

        def _fake_download(*, product_id: int | str, output_dir: Path, timeout: float = 0, **_: object) -> dict[str, object]:
            _ = timeout
            output_dir.mkdir(parents=True, exist_ok=True)
            package_path = output_dir / f"{product_id}.unitypackage"
            package_path.write_bytes(b"pkg")
            return {"product_id": str(product_id), "output_path": str(package_path), "bytes_written": 3}

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wave_json = root / "unity_download_wave.json"
            wave_json.write_text(json.dumps(report), encoding="utf-8")
            cached_dir = root / "cache"
            cached_dir.mkdir()
            (cached_dir / "unity_owned_library_map.json").write_text(
                json.dumps({"owned_count": 1, "pages_fetched": 1, "items": [{"package_id": "165785"}]}),
                encoding="utf-8",
            )
            with patch(
                "assetboy.providers.unity_hub.build_unity_owned_library_map",
                return_value={"owned_count": 0, "pages_fetched": 0, "error": "502 bad gateway", "items": []},
            ):
                with patch("assetboy.providers.unity_hub.generated_output_root", return_value=root):
                    with patch("assetboy.providers.unity_hub.download_unity_owned_package", side_effect=_fake_download):
                        wave_report = download_unity_owned_wave(
                            wave_json=wave_json,
                            output_dir=root / "owned_wave",
                        )

        self.assertEqual(wave_report["summary"]["downloaded"], 1)
        self.assertEqual(wave_report["owned_library_map"]["source"], "cached")
        self.assertTrue(str(wave_report["owned_library_map"]["cached_report_path"]).endswith("unity_owned_library_map.json"))

    def test_download_unity_owned_lightweights_filters_by_expected_size(self) -> None:
        candidate_report = {
            "owned_library": {"owned_count": 3, "pages_fetched": 1, "error": ""},
            "candidate_count": 3,
            "items": [
                {
                    "package_id": "101",
                    "display_name": "Small Pack",
                    "expected_bytes": 10 * 1024 * 1024,
                    "expected_mb": 10.0,
                    "status": "inspected",
                },
                {
                    "package_id": "202",
                    "display_name": "Big Pack",
                    "expected_bytes": 300 * 1024 * 1024,
                    "expected_mb": 300.0,
                    "status": "inspected",
                },
                {
                    "package_id": "303",
                    "display_name": "Unknown Pack",
                    "expected_bytes": 0,
                    "expected_mb": 0.0,
                    "status": "inspected",
                },
            ],
        }

        def _fake_download(*, product_id: int | str, output_dir: Path, timeout: float = 0, **_: object) -> dict[str, object]:
            _ = timeout
            output_dir.mkdir(parents=True, exist_ok=True)
            package_path = output_dir / f"{product_id}.unitypackage"
            package_path.write_bytes(b"pkg")
            return {
                "product_id": str(product_id),
                "output_path": str(package_path),
                "bytes_written": 3,
                "final_bytes_written": 3,
            }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("assetboy.providers.unity_hub.inspect_unity_owned_download_candidates", return_value=candidate_report):
                with patch("assetboy.providers.unity_hub.download_unity_owned_package", side_effect=_fake_download):
                    report = download_unity_owned_lightweights(
                        max_mb=50.0,
                        output_dir=root / "lightweights",
                    )

        self.assertEqual(report["summary"]["owned_items_scanned"], 3)
        self.assertEqual(report["summary"]["eligible_lightweights"], 1)
        self.assertEqual(report["summary"]["downloaded"], 1)
        self.assertEqual(report["summary"]["skipped_large"], 1)
        self.assertEqual(report["summary"]["skipped_unknown_size"], 1)
        downloaded = [item for item in report["items"] if item["status"] == "downloaded"]
        self.assertEqual(len(downloaded), 1)
        self.assertTrue(downloaded[0]["output_path"].endswith("101.unitypackage"))

    def test_download_unity_owned_lightweights_reuses_existing_downloads(self) -> None:
        candidate_report = {
            "owned_library": {"owned_count": 1, "pages_fetched": 1, "error": ""},
            "candidate_count": 1,
            "items": [
                {
                    "package_id": "101",
                    "display_name": "Small Pack",
                    "expected_bytes": 10 * 1024 * 1024,
                    "expected_mb": 10.0,
                    "status": "inspected",
                }
            ],
        }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            download_dir = root / "lightweights" / "downloads" / "101_Small_Pack"
            download_dir.mkdir(parents=True)
            package_path = download_dir / "101.unitypackage"
            package_path.write_bytes(b"pkg")
            report_path = download_dir / "unity_owned_download_101.json"
            report_path.write_text(
                json.dumps(
                    {
                        "product_id": "101",
                        "output_path": str(package_path),
                        "bytes_written": 3,
                        "final_bytes_written": 3,
                    }
                ),
                encoding="utf-8",
            )
            with patch("assetboy.providers.unity_hub.inspect_unity_owned_download_candidates", return_value=candidate_report):
                with patch("assetboy.providers.unity_hub.download_unity_owned_package") as mock_download:
                    report = download_unity_owned_lightweights(
                        max_mb=50.0,
                        output_dir=root / "lightweights",
                    )

        self.assertEqual(report["summary"]["eligible_lightweights"], 1)
        self.assertEqual(report["summary"]["downloaded"], 1)
        self.assertEqual(report["summary"]["reused_existing"], 1)
        self.assertEqual(report["summary"]["failed_download"], 0)
        self.assertEqual(report["items"][0]["status"], "downloaded_existing")
        mock_download.assert_not_called()
