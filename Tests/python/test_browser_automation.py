from pathlib import Path
from tempfile import TemporaryDirectory
import json
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from assetboy import cli
from assetboy.execution.freesound_runner import run_freesound_batch
from assetboy.execution.music_runner import run_music_batch
from assetboy.execution.playwright_runner import (
    _artifacts_dir_for_job,
    _capture_browser_page_metadata,
    _default_auth_state_path,
    _default_browser_profile_dir,
    _extract_unity_asset_id,
    _existing_auth_state_path,
    _is_unity_claim_click_step,
    _normalize_selector,
    _should_use_storage_state,
    _write_browser_evidence_files,
    run_browser_job,
    run_mixamo_batch,
)
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job


class _FakeMetadataPage:
    def __init__(self, *, title: str, page_text: str, metadata: dict[str, object]) -> None:
        self._title = title
        self._page_text = page_text
        self._metadata = metadata

    def title(self) -> str:
        return self._title

    def evaluate(self, _script: str, args: dict[str, object] | None = None) -> object:
        if isinstance(args, dict):
            return self._metadata
        return self._page_text

    def content(self) -> str:
        return "<html><body>stub</body></html>"

    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        self._metadata["last_screenshot_path"] = path
        self._metadata["last_screenshot_full_page"] = full_page
        Path(path).write_bytes(b"png")


class BrowserAutomationTests(unittest.TestCase):
    def test_emit_browser_automation_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_browser_automation_job(
                source_adapter="mixamo",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id="RA_PACK_CHR_PLAYER_SLICE_01",
                game_scope="roman_arena",
                source_url="https://www.mixamo.com/example",
                search_terms=("roman gladiator",),
                login_required=True,
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.provenance_template_path.exists())
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["runtime"], "playwright_mcp")
            self.assertEqual(payload["source_adapter"], "mixamo")
            self.assertIn("playwright_steps", payload)
            self.assertEqual(payload["playwright_steps"][0]["action"], "navigate")

    def test_emit_browser_automation_job_adds_structured_steps_for_fab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_browser_automation_job(
                source_adapter="fab",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
                game_scope="roman_arena",
                source_url="https://www.fab.com/search?q=roman+weapon",
                search_terms=("roman weapon",),
                login_required=True,
                output_dir=Path(temp_dir),
            )
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertIn("playwright_steps", payload)
            self.assertEqual(payload["playwright_steps"][0]["action"], "navigate")
            self.assertIn("fab.com/search", payload["playwright_steps"][0]["params"]["url"])

    def test_emit_browser_automation_job_adds_structured_steps_for_unity_asset_store(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_browser_automation_job(
                source_adapter="unity_asset_store",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id="SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395",
                game_scope="arena_shared",
                source_url="https://assetstore.unity.com/packages/3d/characters/humanoids/humans/human-character-dummy-178395",
                search_terms=("Human Character Dummy",),
                login_required=True,
                output_dir=Path(temp_dir),
            )
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertIn("playwright_steps", payload)
            self.assertEqual(payload["playwright_steps"][0]["action"], "navigate")
            self.assertIn("assetstore.unity.com/packages", payload["playwright_steps"][0]["params"]["url"])
            selectors = [step.get("params", {}).get("selector", "") for step in payload["playwright_steps"]]
            self.assertTrue(any("Continue with Google" in selector for selector in selectors))
            self.assertTrue(any("@.+" in selector or "[data-email]" in selector for selector in selectors))
            account_selector = next(
                selector for selector in selectors if "[data-email]" in selector or "has-text('@')" in selector
            )
            self.assertNotIn("text=/", account_selector)


class PlaywrightRunnerTests(unittest.TestCase):
    def test_default_browser_profile_dir_is_adapter_specific(self) -> None:
        self.assertEqual(_default_browser_profile_dir("fab").name, "fab_browser_profile")
        self.assertEqual(_default_browser_profile_dir("unity_asset_store").name, "unity_browser_profile")
        self.assertEqual(_default_browser_profile_dir("mixamo").name, "mixamo_browser_profile")

    def test_artifacts_dir_for_job_scopes_by_adapter_pack_and_spec(self) -> None:
        spec_path = Path("state/generated/jobs/fab_browser_job.json")
        job = {"source_adapter": "fab", "pack_id": "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"}

        artifacts_dir = _artifacts_dir_for_job(spec_path, job)

        self.assertEqual(
            artifacts_dir.as_posix(),
            "state/generated/jobs/playwright_exec/fab/ra_pack_env_sandstone_bowl_slice_01/fab_browser_job",
        )

    def test_capture_browser_page_metadata_preserves_structured_provider_evidence(self) -> None:
        page = _FakeMetadataPage(
            title="Unity Listing",
            page_text="You purchased this item\nLicense type\nStandard Unity Asset Store EULA\nOpen in Unity",
            metadata={
                "url": "https://assetstore.unity.com/packages/example",
                "title": "Human Character Dummy",
                "publisher": "Unity Vendor",
                "license_lines": ["License type: Standard Unity Asset Store EULA"],
                "ownership_lines": ["You purchased this item", "Open in Unity"],
                "visible_actions": ["Open in Unity", "Add to My Assets"],
                "provider_evidence": {
                    "product_id": "178395",
                    "license_lines": ["License type: Standard Unity Asset Store EULA"],
                    "ownership_lines": ["You purchased this item", "Open in Unity"],
                    "visible_actions": ["Open in Unity", "Add to My Assets"],
                },
            },
        )

        metadata = _capture_browser_page_metadata(page, adapter="unity_asset_store", product_id="178395")

        self.assertEqual(metadata["publisher"], "Unity Vendor")
        self.assertEqual(metadata["license_lines"], ["License type: Standard Unity Asset Store EULA"])
        self.assertEqual(metadata["ownership_lines"], ["You purchased this item", "Open in Unity"])
        self.assertEqual(metadata["visible_actions"], ["Open in Unity", "Add to My Assets"])
        self.assertEqual(metadata["provider_evidence"]["product_id"], "178395")
        self.assertIn("You purchased this item", metadata["page_text_excerpt"])

    def test_capture_browser_page_metadata_derives_unity_provider_evidence_from_page_text(self) -> None:
        page = _FakeMetadataPage(
            title="Unity Listing",
            page_text=(
                "Human Character Dummy\n"
                "Publisher\n"
                "Unity Vendor\n"
                "Latest version\n"
                "1.2\n"
                "You purchased this item\n"
                "License type\n"
                "Standard Unity Asset Store EULA\n"
                "Open in Unity\n"
                "Add to My Assets\n"
            ),
            metadata={
                "url": "https://assetstore.unity.com/packages/example",
                "title": "Human Character Dummy",
            },
        )

        metadata = _capture_browser_page_metadata(page, adapter="unity_asset_store", product_id="178395")

        self.assertEqual(metadata["publisher"], "Unity Vendor")
        self.assertEqual(metadata["version"], "1.2")
        self.assertEqual(metadata["license"], "Standard Unity Asset Store EULA")
        self.assertEqual(metadata["license_snapshot"], "License type: Standard Unity Asset Store EULA")
        self.assertTrue(metadata["purchased"])
        self.assertTrue(metadata["openInUnity"])
        self.assertTrue(metadata["addToMyAssets"])
        self.assertIn("You purchased this item", metadata["ownership_lines"])
        self.assertIn("Open in Unity", metadata["visible_actions"])
        self.assertEqual(metadata["provider_evidence"]["product_id"], "178395")
        self.assertTrue(metadata["provider_evidence"]["purchased"])

    def test_capture_browser_page_metadata_derives_fab_provider_evidence_from_page_text(self) -> None:
        page = _FakeMetadataPage(
            title="Fab Listing",
            page_text=(
                "Roman Arch Pack\n"
                "Seller\n"
                "Arena Vendor\n"
                "License\n"
                "Fab Standard License\n"
                "Add to my library\n"
                "Download\n"
                "Export\n"
            ),
            metadata={
                "url": "https://www.fab.com/listings/manual-123",
                "title": "Roman Arch Pack",
            },
        )

        metadata = _capture_browser_page_metadata(page, adapter="fab", product_id="manual-123")

        self.assertEqual(metadata["seller"], "Arena Vendor")
        self.assertEqual(metadata["license"], "Fab Standard License")
        self.assertEqual(metadata["license_snapshot"], "License: Fab Standard License")
        self.assertEqual(metadata["claim_action"], "Add to my library")
        self.assertEqual(metadata["download_action"], "Download")
        self.assertIn("Fab Standard License", metadata["license_lines"])
        self.assertIn("Add to my library", metadata["ownership_lines"])
        self.assertEqual(metadata["provider_evidence"]["product_id"], "manual-123")
        self.assertIn("Export", metadata["provider_evidence"]["visible_actions"])

    def test_write_browser_evidence_files_saves_dom_and_screenshot(self) -> None:
        page = _FakeMetadataPage(
            title="Fab Listing",
            page_text="Owned\nFab Standard License",
            metadata={},
        )

        with TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            payload = _write_browser_evidence_files(page, artifacts_dir=artifacts_dir)
            self.assertEqual(payload["page_dom_path"], str(artifacts_dir / "page_dom.html"))
            self.assertEqual(payload["page_dom_text_path"], str(artifacts_dir / "page_dom.txt"))
            self.assertEqual(payload["page_dom_metadata_path"], str(artifacts_dir / "page_dom_metadata.json"))
            self.assertEqual(payload["page_screenshot_path"], str(artifacts_dir / "page_screenshot.png"))
            self.assertEqual(payload["page_screenshot_meta_path"], str(artifacts_dir / "page_screenshot_meta.json"))
            self.assertTrue((artifacts_dir / "page_dom.html").exists())
            self.assertTrue((artifacts_dir / "page_dom.txt").exists())
            self.assertTrue((artifacts_dir / "page_dom_metadata.json").exists())
            self.assertTrue((artifacts_dir / "page_screenshot.png").exists())
            self.assertTrue((artifacts_dir / "page_screenshot_meta.json").exists())

    def test_mixamo_jobs_resolve_saved_auth_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            private_root = Path(temp_dir) / ".private"
            private_root.mkdir(parents=True, exist_ok=True)
            auth_state = private_root / "mixamo_auth_state.json"
            auth_state.write_text("{}", encoding="utf-8")

            with patch("assetboy.execution.playwright_runner.assetboy_root", return_value=Path(temp_dir)):
                resolved = _existing_auth_state_path({"source_adapter": "mixamo"})

            self.assertEqual(resolved, auth_state.resolve())

    def test_fab_jobs_resolve_saved_auth_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            private_root = Path(temp_dir) / ".private"
            private_root.mkdir(parents=True, exist_ok=True)
            auth_state = private_root / "fab_auth_state.json"
            auth_state.write_text("{}", encoding="utf-8")

            with patch("assetboy.execution.playwright_runner.assetboy_root", return_value=Path(temp_dir)):
                resolved = _existing_auth_state_path({"source_adapter": "fab"})

            self.assertEqual(resolved, auth_state.resolve())

    def test_fab_jobs_reject_stale_saved_auth_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            private_root = Path(temp_dir) / ".private"
            private_root.mkdir(parents=True, exist_ok=True)
            auth_state = private_root / "fab_auth_state.json"
            auth_state.write_text(
                json.dumps(
                    {
                        "authenticated": True,
                        "saved_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            with patch("assetboy.execution.playwright_runner.assetboy_root", return_value=Path(temp_dir)):
                resolved = _existing_auth_state_path({"source_adapter": "fab"})

            self.assertIsNone(resolved)


class BrowserProvenanceHydrationTests(unittest.TestCase):
    def test_hydrate_browser_source_provenance_uses_saved_browser_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "manual_drop" / "SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395"
            artifacts_dir = root / "artifacts"
            job_spec_path = root / "job" / "browser_job.json"
            payload_target = root / "publish" / "shared" / "SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395" / "payload"
            source_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)

            (source_dir / "character.fbx").write_bytes(b"fbx")
            job_spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "unity_asset_store",
                        "pack_id": "SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395",
                        "game_scope": "shared",
                        "source_url": "https://assetstore.unity.com/packages/characters/example",
                        "destination": str(source_dir),
                    }
                ),
                encoding="utf-8",
            )
            (job_spec_path.parent / "payload_target.txt").write_text(str(payload_target), encoding="utf-8")
            (artifacts_dir / "execution_log.json").write_text(
                json.dumps([{"action": "download", "download_path": str(source_dir / "character.fbx")}]),
                encoding="utf-8",
            )
            (artifacts_dir / "page_metadata.json").write_text(
                json.dumps(
                    {
                        "url": "https://assetstore.unity.com/packages/characters/example",
                        "publisher": "Unity Vendor",
                        "license": "Standard Unity Asset Store EULA",
                        "license_snapshot": "License type: Standard Unity Asset Store EULA",
                        "title": "Human Character Dummy",
                        "version": "1.2",
                        "purchased": True,
                        "openInUnity": True,
                        "myAssetsContainsProduct": True,
                    }
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "page_dom.html").write_text("<html><body>Owned</body></html>", encoding="utf-8")
            (artifacts_dir / "page_screenshot.png").write_bytes(b"png")

            hydration = cli._hydrate_browser_source_provenance(
                job_spec_path=job_spec_path,
                artifacts_dir=artifacts_dir,
                last_url="https://assetstore.unity.com/packages/characters/example",
                fallback_pack_id="",
                fallback_game_scope="",
            )

            self.assertEqual(hydration["status"], "completed")
            provenance = json.loads((source_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["author_or_vendor"], "Unity Vendor")
            self.assertEqual(provenance["license"], "Standard Unity Asset Store EULA")
            self.assertEqual(provenance["license_snapshot"], "License type: Standard Unity Asset Store EULA")
            self.assertIn("Unity Asset Store browser capture", provenance["entitlement_note"])
            self.assertIn("page_metadata.json", provenance["entitlement_note"])
            self.assertIn("page_dom.html", provenance["entitlement_note"])
            self.assertIn("page_screenshot.png", provenance["entitlement_note"])
            self.assertIn("Listing title: Human Character Dummy", provenance["download_notes"])
            self.assertIn("Listing version: 1.2", provenance["download_notes"])
            self.assertIn("Browser screenshot: page_screenshot.png", provenance["download_notes"])
            self.assertEqual(hydration["page_dom_path"], str(artifacts_dir / "page_dom.html"))
            self.assertEqual(hydration["page_screenshot_path"], str(artifacts_dir / "page_screenshot.png"))
            self.assertEqual(hydration["page_screenshot_meta"]["filename"], "page_screenshot.png")
            self.assertTrue(hydration["register_packet_ready"])
            self.assertEqual(hydration["provenance_confidence_band"], "high")
            self.assertGreaterEqual(hydration["provenance_confidence_score"], 85)

    def test_hydrate_browser_source_provenance_derives_fields_from_structured_provider_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "manual_drop" / "SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395"
            artifacts_dir = root / "artifacts"
            job_spec_path = root / "job" / "browser_job.json"
            payload_target = root / "publish" / "shared" / "SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395" / "payload"
            source_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)

            (source_dir / "character.fbx").write_bytes(b"fbx")
            job_spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "unity_asset_store",
                        "pack_id": "SHARED_UNITY_HUMAN_CHARACTER_DUMMY_178395",
                        "game_scope": "shared",
                        "source_url": "https://assetstore.unity.com/packages/characters/example",
                        "destination": str(source_dir),
                    }
                ),
                encoding="utf-8",
            )
            (job_spec_path.parent / "payload_target.txt").write_text(str(payload_target), encoding="utf-8")
            (artifacts_dir / "execution_log.json").write_text(
                json.dumps([{"action": "download", "download_path": str(source_dir / "character.fbx")}]),
                encoding="utf-8",
            )
            (artifacts_dir / "page_metadata.json").write_text(
                json.dumps(
                    {
                        "url": "https://assetstore.unity.com/packages/characters/example",
                        "publisher": "Unity Vendor",
                        "license_lines": ["License type: Standard Unity Asset Store EULA"],
                        "ownership_lines": ["You purchased this item", "Open in Unity"],
                        "visible_actions": ["Open in Unity", "Add to My Assets"],
                        "provider_evidence": {
                            "product_id": "178395",
                            "license_lines": ["License type: Standard Unity Asset Store EULA"],
                            "ownership_lines": ["You purchased this item", "Open in Unity"],
                            "visible_actions": ["Open in Unity", "Add to My Assets"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "page_dom.html").write_text("<html><body>Open in Unity</body></html>", encoding="utf-8")
            (artifacts_dir / "page_screenshot.png").write_bytes(b"png")

            hydration = cli._hydrate_browser_source_provenance(
                job_spec_path=job_spec_path,
                artifacts_dir=artifacts_dir,
                last_url="https://assetstore.unity.com/packages/characters/example",
                fallback_pack_id="",
                fallback_game_scope="",
            )

            self.assertEqual(hydration["status"], "completed")
            self.assertEqual(hydration["page_metadata_path"], str(artifacts_dir / "page_metadata.json"))
            self.assertEqual(hydration["page_dom_path"], str(artifacts_dir / "page_dom.html"))
            self.assertEqual(hydration["page_screenshot_path"], str(artifacts_dir / "page_screenshot.png"))
            provenance = json.loads((source_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["license"], "Standard Unity Asset Store EULA")
            self.assertEqual(provenance["license_snapshot"], "License type: Standard Unity Asset Store EULA")
            self.assertIn("Open in Unity", provenance["entitlement_note"])
            self.assertIn("page_metadata.json", provenance["entitlement_note"])
            self.assertIn("Browser screenshot: page_screenshot.png", provenance["download_notes"])
            self.assertTrue(hydration["register_packet_ready"])
            self.assertIn(hydration["provenance_confidence_band"], {"high", "medium"})

    def test_hydrate_browser_source_provenance_promotes_dom_and_screenshot_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "manual_drop" / "SHARED_UNITY_DOM_PROMOTION_01"
            artifacts_dir = root / "artifacts"
            job_spec_path = root / "job" / "browser_job.json"
            payload_target = root / "publish" / "shared" / "SHARED_UNITY_DOM_PROMOTION_01" / "payload"
            source_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)

            (source_dir / "character.fbx").write_bytes(b"fbx")
            job_spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "unity_asset_store",
                        "pack_id": "SHARED_UNITY_DOM_PROMOTION_01",
                        "game_scope": "shared",
                        "source_url": "https://assetstore.unity.com/packages/characters/example-dom",
                        "destination": str(source_dir),
                    }
                ),
                encoding="utf-8",
            )
            (job_spec_path.parent / "payload_target.txt").write_text(str(payload_target), encoding="utf-8")
            (artifacts_dir / "execution_log.json").write_text(
                json.dumps([{"action": "download", "download_path": str(source_dir / "character.fbx")}]),
                encoding="utf-8",
            )
            (artifacts_dir / "page_dom.html").write_text(
                (
                    "<html><body>"
                    "<h1>Human Character Dummy</h1>"
                    "<div>Publisher</div><div>Unity Vendor</div>"
                    "<div>Latest version</div><div>1.2</div>"
                    "<div>License type</div><div>Standard Unity Asset Store EULA</div>"
                    "<div>You purchased this item</div><div>Open in Unity</div>"
                    "</body></html>"
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "page_screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
            (artifacts_dir / "page_dom_metadata.json").write_text(
                json.dumps(
                    {
                        "license_lines": ["License type: Standard Unity Asset Store EULA"],
                        "ownership_lines": ["You purchased this item", "Open in Unity"],
                        "visible_actions": ["Open in Unity", "Add to My Assets"],
                        "provider_evidence": {
                            "license_lines": ["License type: Standard Unity Asset Store EULA"],
                            "ownership_lines": ["You purchased this item", "Open in Unity"],
                            "visible_actions": ["Open in Unity", "Add to My Assets"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "page_screenshot_meta.json").write_text(
                json.dumps(
                    {
                        "filename": "page_screenshot.png",
                        "size_bytes": 32,
                        "captured_at": "2026-04-05T00:00:00+00:00",
                        "width": 1920,
                        "height": 1080,
                    }
                ),
                encoding="utf-8",
            )

            hydration = cli._hydrate_browser_source_provenance(
                job_spec_path=job_spec_path,
                artifacts_dir=artifacts_dir,
                last_url="https://assetstore.unity.com/packages/characters/example-dom",
                fallback_pack_id="",
                fallback_game_scope="",
            )

            self.assertEqual(hydration["status"], "completed")
            provenance = json.loads((source_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["author_or_vendor"], "Unity Vendor")
            self.assertEqual(provenance["license"], "Standard Unity Asset Store EULA")
            self.assertEqual(provenance["license_snapshot"], "License type: Standard Unity Asset Store EULA")
            self.assertIn("Unity Asset Store browser capture", provenance["entitlement_note"])
            self.assertIn("Open in Unity", provenance["entitlement_note"])
            self.assertIn("page_dom.html", provenance["entitlement_note"])
            self.assertIn("page_dom_metadata.json", provenance["entitlement_note"])
            self.assertIn("page_screenshot.png", provenance["entitlement_note"])
            self.assertIn("page_screenshot_meta.json", provenance["entitlement_note"])
            self.assertIn("Listing version: 1.2", provenance["download_notes"])
            self.assertIn("Browser screenshot: page_screenshot.png", provenance["download_notes"])
            self.assertEqual(hydration["page_dom_metadata_path"], str(artifacts_dir / "page_dom_metadata.json"))
            self.assertEqual(hydration["page_screenshot_meta_path"], str(artifacts_dir / "page_screenshot_meta.json"))
            self.assertEqual(hydration["page_screenshot_meta"]["filename"], "page_screenshot.png")
            self.assertTrue(hydration["register_packet_ready"])

    def test_hydrate_browser_source_provenance_flags_operator_fill_when_browser_evidence_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "manual_drop" / "SHARED_UNITY_LOW_CONFIDENCE_01"
            job_spec_path = root / "job" / "browser_job.json"
            payload_target = root / "publish" / "shared" / "SHARED_UNITY_LOW_CONFIDENCE_01" / "payload"
            source_dir.mkdir(parents=True, exist_ok=True)
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)

            (source_dir / "character.fbx").write_bytes(b"fbx")
            (source_dir / "provenance.json").write_text(
                json.dumps(
                    {
                        "source_url": "https://assetstore.unity.com/packages/characters/example-low-confidence",
                        "license": "Standard Unity Asset Store EULA",
                        "license_snapshot": "License type: Standard Unity Asset Store EULA",
                        "author_or_vendor": "Unity Vendor",
                        "acquired_at": "2026-04-05T00:00:00+00:00",
                        "lane": "manual_browser",
                        "source_adapter": "unity_asset_store",
                        "payload_target_path": str(payload_target),
                        "downloaded_filename": "character.fbx",
                        "entitlement_note": "Manual note only.",
                    }
                ),
                encoding="utf-8",
            )
            job_spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "unity_asset_store",
                        "pack_id": "SHARED_UNITY_LOW_CONFIDENCE_01",
                        "game_scope": "shared",
                        "source_url": "https://assetstore.unity.com/packages/characters/example-low-confidence",
                        "destination": str(source_dir),
                    }
                ),
                encoding="utf-8",
            )
            (job_spec_path.parent / "payload_target.txt").write_text(str(payload_target), encoding="utf-8")

            hydration = cli._hydrate_browser_source_provenance(
                job_spec_path=job_spec_path,
                artifacts_dir=None,
                last_url="https://assetstore.unity.com/packages/characters/example-low-confidence",
                fallback_pack_id="",
                fallback_game_scope="",
            )

            self.assertEqual(hydration["status"], "completed")
            self.assertFalse(hydration["register_packet_ready"])
            self.assertTrue(hydration["operator_action_required"])
            self.assertEqual(hydration["operator_action"], "capture_browser_evidence_or_fill_provenance_fields")
            confidence = dict(hydration["provenance_confidence"])
            self.assertTrue(confidence["needs_operator_fill"])
            self.assertIn("browser_artifacts_missing", confidence["reasons"])
            self.assertIn("license_not_backed_by_browser_evidence", confidence["reasons"])
            self.assertEqual(confidence["evidence"]["artifact_file_count"], 0)

    def test_non_authenticated_adapters_do_not_assume_auth_state(self) -> None:
        self.assertIsNone(_default_auth_state_path("mixkit"))

    def test_unity_jobs_resolve_saved_auth_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            private_root = Path(temp_dir) / ".private"
            private_root.mkdir(parents=True, exist_ok=True)
            auth_state = private_root / "unity_auth_state.json"
            auth_state.write_text("{}", encoding="utf-8")

            with patch("assetboy.execution.playwright_runner.assetboy_root", return_value=Path(temp_dir)):
                resolved = _existing_auth_state_path({"source_adapter": "unity_asset_store"})

            self.assertEqual(resolved, auth_state.resolve())

    def test_unity_jobs_ignore_saved_auth_state_when_marked_unauthenticated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            private_root = Path(temp_dir) / ".private"
            private_root.mkdir(parents=True, exist_ok=True)
            auth_state = private_root / "unity_auth_state.json"
            auth_state.write_text('{"authenticated": false, "cookies": [], "origins": []}', encoding="utf-8")

            with patch("assetboy.execution.playwright_runner.assetboy_root", return_value=Path(temp_dir)):
                resolved = _existing_auth_state_path({"source_adapter": "unity_asset_store"})

            self.assertIsNone(resolved)

    def test_unity_jobs_use_persistent_profile_not_storage_state(self) -> None:
        self.assertFalse(_should_use_storage_state({"source_adapter": "unity_asset_store"}))
        self.assertFalse(_should_use_storage_state({"source_adapter": "mixamo"}))

    def test_extract_unity_asset_id_from_store_url(self) -> None:
        self.assertEqual(
            _extract_unity_asset_id(
                {
                    "source_url": "https://assetstore.unity.com/packages/3d/characters/humanoids/humans/human-character-dummy-178395"
                }
            ),
            "178395",
        )

    def test_is_unity_claim_click_step_detects_claim_button(self) -> None:
        self.assertTrue(
            _is_unity_claim_click_step(
                {
                    "action": "click",
                    "params": {"selector": "button:contains('Add to My Assets')"},
                }
            )
        )
        self.assertFalse(
            _is_unity_claim_click_step(
                {
                    "action": "click",
                    "params": {"selector": "button:contains('Accept All Cookies')"},
                }
            )
        )

    def test_run_browser_job_plan_only_dry_run_still_emits_steps(self) -> None:
        with TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "browser_job.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "pack_id": "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                        "source_url": "https://www.fab.com/search?q=roman+arena",
                        "search_terms": ["roman arena"],
                        "destination": str(Path(temp_dir) / "downloads"),
                    }
                ),
                encoding="utf-8",
            )

            result = run_browser_job(spec_path, dry_run=True)

            self.assertFalse(result.executed)
            self.assertEqual(result.execution_mode, "plan")
            self.assertGreater(len(result.steps_emitted), 0)
            self.assertIsNone(result.artifacts_dir)
            self.assertIsNone(result.browser_profile_dir)

    def test_run_browser_job_execute_reports_failed_when_structured_steps_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "browser_job.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "pack_id": "RA_PACK_WPN_COMBAT_SLICE_01",
                        "source_url": "https://www.fab.com/search?q=roman+weapon",
                        "search_terms": ["roman weapon"],
                        "destination": str(Path(temp_dir) / "downloads"),
                    }
                ),
                encoding="utf-8",
            )

            result = run_browser_job(spec_path, execute=True)

            self.assertFalse(result.executed)
            self.assertEqual(result.execution_mode, "failed")
            self.assertEqual(result.attempts, 1)
            self.assertIn("structured `playwright_steps`", result.error)

    def test_run_browser_job_execute_uses_shared_profile_executor(self) -> None:
        with TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "browser_job.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "mixkit",
                        "pack_id": "RA_PACK_AUD_MUSIC_SLICE_01",
                        "source_url": "https://mixkit.co/free-stock-music/",
                        "search_terms": ["arena combat loop"],
                        "destination": str(Path(temp_dir) / "downloads"),
                        "playwright_steps": [
                            {"action": "navigate", "params": {"url": "https://example.com"}, "note": "open"},
                            {"action": "screenshot", "params": {}, "note": "shot"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            artifacts_dir = Path(temp_dir) / "playwright_exec"

            with patch(
                "assetboy.execution.playwright_runner._execute_structured_playwright_job",
                return_value={
                    "artifacts_dir": artifacts_dir,
                    "execution_mode": "playwright_structured",
                    "last_url": "https://example.com",
                },
            ) as fake_execute:
                result = run_browser_job(spec_path, execute=True, headed=False, timeout_ms=4321)

            self.assertTrue(result.executed)
            self.assertEqual(result.execution_mode, "playwright_structured")
            self.assertEqual(result.artifacts_dir, artifacts_dir)
            self.assertEqual(result.last_url, "https://example.com")
            self.assertIsNotNone(result.browser_profile_dir)
            self.assertEqual(result.browser_profile_dir.name, "fab_browser_profile")
            self.assertEqual(result.browser_profile_dir.parent.name, ".private")
            self.assertFalse(fake_execute.call_args.kwargs["headed"])
            self.assertEqual(fake_execute.call_args.kwargs["timeout_ms"], 4321)
            self.assertEqual(
                fake_execute.call_args.kwargs["browser_profile_dir"],
                result.browser_profile_dir,
            )

    def test_run_browser_job_execute_retries_login_required_interactive_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "browser_job.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "pack_id": "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                        "source_url": "https://www.fab.com/search?q=roman+arena",
                        "search_terms": ["roman arena"],
                        "destination": str(Path(temp_dir) / "downloads"),
                        "login_required": True,
                        "playwright_steps": [
                            {"action": "navigate", "params": {"url": "https://example.com"}, "note": "open"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            artifacts_dir = Path(temp_dir) / "playwright_exec" / "fab"

            with patch(
                "assetboy.execution.playwright_runner._execute_structured_playwright_job",
                side_effect=[
                    {
                        "artifacts_dir": artifacts_dir,
                        "execution_mode": "interactive_required",
                        "last_url": "https://example.com/login",
                        "error": "login still required",
                    },
                    {
                        "artifacts_dir": artifacts_dir,
                        "execution_mode": "playwright_structured",
                        "last_url": "https://example.com/download",
                    },
                ],
            ) as fake_execute:
                result = run_browser_job(spec_path, execute=True, retries=2)

            self.assertTrue(result.executed)
            self.assertEqual(result.execution_mode, "playwright_structured")
            self.assertEqual(result.attempts, 2)
            self.assertEqual(result.error, "")
            self.assertEqual(fake_execute.call_count, 2)

    def test_run_browser_job_execute_interactive_required_returns_actionable_login_hint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "browser_job.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "pack_id": "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                        "source_url": "https://www.fab.com/search?q=roman+arena",
                        "search_terms": ["roman arena"],
                        "destination": str(Path(temp_dir) / "downloads"),
                        "login_required": True,
                        "playwright_steps": [
                            {"action": "navigate", "params": {"url": "https://example.com"}, "note": "open"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            artifacts_dir = Path(temp_dir) / "playwright_exec" / "fab"

            with patch(
                "assetboy.execution.playwright_runner._execute_structured_playwright_job",
                return_value={
                    "artifacts_dir": artifacts_dir,
                    "execution_mode": "interactive_required",
                    "last_url": "https://www.fab.com/login",
                },
            ):
                result = run_browser_job(spec_path, execute=True, retries=1)

            self.assertFalse(result.executed)
            self.assertEqual(result.execution_mode, "interactive_required")
            self.assertIn("fab-auth --reuse-profile", result.error)

    def test_run_browser_job_execute_returns_repair_required_before_launch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "browser_job.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "pack_id": "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                        "source_url": "https://www.fab.com/search?q=roman+arena",
                        "search_terms": ["roman arena"],
                        "destination": str(Path(temp_dir) / "downloads"),
                        "login_required": True,
                        "playwright_steps": [
                            {"action": "navigate", "params": {"url": "https://example.com"}, "note": "open"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "assetboy.execution.playwright_runner._browser_auth_repair_payload",
                return_value={
                    "repair_command": "python scripts/cli.py asset-factory fab-auth --reuse-profile",
                    "repair_reason": "auth_state_stale",
                    "provider_runbook_id": "fab",
                    "error": "Fab auth must be repaired.",
                },
            ):
                with patch("assetboy.execution.playwright_runner._execute_structured_playwright_job") as fake_execute:
                    result = run_browser_job(spec_path, execute=True)

            self.assertFalse(result.executed)
            self.assertEqual(result.execution_mode, "repair_required")
            self.assertEqual(result.attempts, 0)
            self.assertEqual(result.repair_reason, "auth_state_stale")
            self.assertEqual(result.repair_command, "python scripts/cli.py asset-factory fab-auth --reuse-profile")
            self.assertEqual(result.provider_runbook_id, "fab")
            fake_execute.assert_not_called()

    def test_normalize_selector_rewrites_contains_to_has_text(self) -> None:
        self.assertEqual(
            _normalize_selector("button:contains('Download')"),
            'button:has-text("Download")',
        )

    def test_run_mixamo_batch_writes_structured_job_spec_without_word_splitting(self) -> None:
        with TemporaryDirectory() as temp_dir:
            results = run_mixamo_batch(
                pack_id="RA_PACK_CHR_CORE_SLICE_01",
                search="male fighter humanoid base",
                output_dir=Path(temp_dir),
                dry_run=True,
            )

            self.assertEqual(len(results), 1)
            payload = json.loads(results[0].job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["search_terms"], ["male fighter humanoid base"])
            self.assertIn("playwright_steps", payload)
            self.assertEqual(payload["playwright_steps"][0]["action"], "navigate")

    def test_run_mixamo_batch_known_pack_uses_preset_result_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            results = run_mixamo_batch(
                pack_id="RA_PACK_CHR_CORE_SLICE_01",
                output_dir=Path(temp_dir),
                dry_run=True,
            )

            self.assertEqual(len(results), 1)
            payload = json.loads(results[0].job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["search_terms"], ["vanguard"])
            self.assertEqual(payload["result_text"], "Vanguard By T. Choonyung")
            self.assertEqual(
                payload["playwright_steps"][3]["params"]["selector"],
                'text="Vanguard By T. Choonyung"',
            )
            self.assertEqual(
                payload["playwright_steps"][4]["params"]["selector"],
                "[role='dialog'] button:contains('Use This Character')",
            )
            self.assertTrue(payload["playwright_steps"][4]["optional"])
            self.assertEqual(
                payload["playwright_steps"][7]["note"],
                "Open the Mixamo download dialog",
            )

    def test_run_mixamo_batch_execute_uses_run_browser_job(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fake_browser_result = unittest.mock.Mock(
                executed=True,
                execution_mode="playwright_structured",
                artifacts_dir=Path(temp_dir) / "playwright_exec",
                last_url="https://www.mixamo.com/",
            )

            with patch(
                "assetboy.execution.playwright_runner.run_browser_job",
                return_value=fake_browser_result,
            ) as fake_run:
                results = run_mixamo_batch(
                    pack_id="RA_PACK_CHR_CORE_SLICE_01",
                    search="male fighter humanoid base",
                    output_dir=Path(temp_dir),
                    execute=True,
                    headed=False,
                    browser_profile_dir=Path(".private/custom_profile"),
                    timeout_ms=7777,
                )

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].executed)
            self.assertEqual(results[0].execution_mode, "playwright_structured")
            self.assertEqual(results[0].artifacts_dir, Path(temp_dir) / "playwright_exec")
            fake_run.assert_called_once()
            self.assertTrue(fake_run.call_args.kwargs["execute"])
            self.assertFalse(fake_run.call_args.kwargs["headed"])
            self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
            self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 7777)

    def test_run_freesound_batch_writes_executable_job_spec(self) -> None:
        with TemporaryDirectory() as temp_dir:
            results = run_freesound_batch(
                search="sword clash metal impact",
                pack_id="RA_PACK_AUD_SFX_SLICE_01",
                count=2,
                output_dir=Path(temp_dir),
                dry_run=True,
            )

            self.assertEqual(len(results), 1)
            payload = json.loads(results[0].job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_adapter"], "freesound_audio")
            self.assertEqual(payload["search_terms"], ["sword clash metal impact"])
            self.assertEqual(payload["destination"], str(Path(temp_dir)))
            self.assertEqual(payload["playwright_steps"][0]["action"], "navigate")
            self.assertEqual(
                payload["playwright_steps"][3]["params"]["selector"],
                ":nth-match(a[href*='/sounds/'], 1)",
            )

    def test_run_freesound_batch_execute_uses_run_browser_job(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fake_browser_result = unittest.mock.Mock(
                executed=True,
                execution_mode="playwright_structured",
                artifacts_dir=Path(temp_dir) / "playwright_exec",
                last_url="https://freesound.org/search/text/?q=sword+clash",
            )

            with patch(
                "assetboy.execution.freesound_runner.run_browser_job",
                return_value=fake_browser_result,
                create=True,
            ):
                with patch(
                    "assetboy.execution.playwright_runner.run_browser_job",
                    return_value=fake_browser_result,
                ) as fake_run:
                    results = run_freesound_batch(
                        search="sword clash metal impact",
                        pack_id="RA_PACK_AUD_SFX_SLICE_01",
                        count=2,
                        output_dir=Path(temp_dir),
                        execute=True,
                        headed=False,
                        browser_profile_dir=Path(".private/custom_profile"),
                        timeout_ms=5555,
                    )

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].executed)
            self.assertEqual(results[0].execution_mode, "playwright_structured")
            fake_run.assert_called_once()
            self.assertTrue(fake_run.call_args.kwargs["execute"])
            self.assertFalse(fake_run.call_args.kwargs["headed"])
            self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
            self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 5555)

    def test_run_music_batch_writes_executable_mixkit_job_spec(self) -> None:
        with TemporaryDirectory() as temp_dir:
            results = run_music_batch(
                source="mixkit",
                search="epic battle",
                pack_id="RA_PACK_AUD_MUSIC_SLICE_01",
                count=2,
                output_dir=Path(temp_dir),
                dry_run=True,
            )

            self.assertEqual(len(results), 1)
            payload = json.loads(results[0].job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_adapter"], "mixkit")
            self.assertEqual(payload["search_terms"], ["epic battle"])
            self.assertEqual(payload["destination"], str(Path(temp_dir)))
            self.assertEqual(payload["playwright_steps"][0]["action"], "navigate")
            self.assertEqual(
                payload["playwright_steps"][3]["params"]["selector"],
                ':nth-match(button:has-text("Download Free Music"), 1)',
            )

    def test_run_music_batch_execute_uses_run_browser_job(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fake_browser_result = unittest.mock.Mock(
                executed=True,
                execution_mode="playwright_structured",
                artifacts_dir=Path(temp_dir) / "playwright_exec",
                last_url="https://mixkit.co/free-stock-music/",
            )

            with patch(
                "assetboy.execution.playwright_runner.run_browser_job",
                return_value=fake_browser_result,
            ) as fake_run:
                results = run_music_batch(
                    source="mixkit",
                    search="epic battle",
                    pack_id="RA_PACK_AUD_MUSIC_SLICE_01",
                    count=2,
                    output_dir=Path(temp_dir),
                    execute=True,
                    headed=False,
                    browser_profile_dir=Path(".private/custom_profile"),
                    timeout_ms=6666,
                )

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].executed)
            self.assertEqual(results[0].execution_mode, "playwright_structured")
            fake_run.assert_called_once()
            self.assertTrue(fake_run.call_args.kwargs["execute"])
            self.assertFalse(fake_run.call_args.kwargs["headed"])
            self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
            self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 6666)


class BrowserCliCommandTests(unittest.TestCase):
    def test_run_browser_job_cli_passes_execution_flags_and_prints_result_fields(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            source_adapter="mixkit",
            pack_id="RA_PACK_AUD_MUSIC_SLICE_01",
            steps_emitted=["open", "download"],
            dry_run=False,
            executed=True,
            execution_mode="playwright_structured",
            browser_profile_dir=Path("scripts/asset_factory/.private/fab_browser_profile"),
            artifacts_dir=Path("scripts/asset_factory/state/generated/playwright_exec"),
            last_url="https://mixkit.co/free-stock-music/",
            attempts=2,
            error="",
        )
        fake_postprocess = {
            "status": "executed",
            "source_dir": "C:/tmp/source_dir",
            "hydration": {
                "status": "completed",
                "provenance_path": "C:/tmp/source_dir/provenance.json",
                "hydration_report_path": "C:/tmp/source_dir/provenance_hydration_report.json",
            },
            "prepare_pack": {
                "current_state": "packeted",
                "packet_path": "C:/tmp/publish/shared/RA_PACK_AUD_MUSIC_SLICE_01/packet.json",
            },
            "auto_intake": {
                "pass": True,
                "handoff_receipt_path": "C:/tmp/publish/shared/RA_PACK_AUD_MUSIC_SLICE_01/handoff_receipt.json",
            },
        }

        with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result) as fake_run:
            with patch.object(cli, "_postprocess_browser_job", return_value=fake_postprocess) as fake_postprocess_call:
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "run-browser-job",
                            "--job-spec",
                            "state/generated/browser_job.json",
                            "--execute",
                            "--headless",
                            "--browser-profile-dir",
                            ".private/custom_profile",
                            "--timeout-ms",
                            "9000",
                            "--retries",
                            "2",
                            "--hydrate-provenance",
                            "--prepare-pack",
                            "--auto-intake",
                            "--cleanup-mode",
                            "skip",
                            "--asset-kind",
                            "character",
                            "--animated",
                            "--packet-status",
                            "reviewed_real",
                        ]
                    )

        self.assertEqual(result, 0)
        fake_run.assert_called_once()
        fake_postprocess_call.assert_called_once()
        self.assertEqual(fake_run.call_args.kwargs["job_spec_path"], Path("state/generated/browser_job.json"))
        self.assertTrue(fake_run.call_args.kwargs["execute"])
        self.assertFalse(fake_run.call_args.kwargs["headed"])
        self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
        self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 9000)
        self.assertEqual(fake_run.call_args.kwargs["retries"], 2)
        self.assertTrue(fake_postprocess_call.call_args.kwargs["auto_intake"])
        output = stdout.getvalue()
        self.assertIn("run_browser_executed=True", output)
        self.assertIn("run_browser_mode=playwright_structured", output)
        self.assertIn("run_browser_attempts=2", output)
        self.assertIn(
            f"run_browser_profile_dir={fake_result.browser_profile_dir}",
            output,
        )
        self.assertIn(
            f"run_browser_artifacts={fake_result.artifacts_dir}",
            output,
        )
        self.assertIn("run_browser_post_status=executed", output)
        self.assertIn("run_browser_hydration_status=completed", output)
        self.assertIn("run_browser_prepare_pack_state=packeted", output)
        self.assertIn("run_browser_auto_intake_pass=true", output)
        self.assertIn("run_browser_handoff_receipt=C:/tmp/publish/shared/RA_PACK_AUD_MUSIC_SLICE_01/handoff_receipt.json", output)

    def test_run_browser_job_cli_returns_nonzero_when_hydration_stays_pending_manual(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            source_adapter="fab",
            pack_id="RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
            steps_emitted=["open", "download"],
            dry_run=False,
            executed=True,
            execution_mode="playwright_structured",
            browser_profile_dir=Path("scripts/asset_factory/.private/fab_browser_profile"),
            artifacts_dir=Path("scripts/asset_factory/state/generated/playwright_exec"),
            last_url="https://www.fab.com/listings/manual-123",
            attempts=1,
            error="",
        )
        fake_postprocess = {
            "status": "pending_manual",
            "error": "Hydrated provenance is incomplete. provenance.license is missing.",
            "source_dir": "C:/tmp/source_dir",
            "hydration": {
                "status": "incomplete",
                "provenance_path": "C:/tmp/source_dir/provenance.json",
                "hydration_report_path": "C:/tmp/source_dir/provenance_hydration_report.json",
            },
        }

        with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result):
            with patch.object(cli, "_postprocess_browser_job", return_value=fake_postprocess):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "run-browser-job",
                            "--job-spec",
                            "state/generated/browser_job.json",
                            "--execute",
                            "--hydrate-provenance",
                        ]
                    )

        self.assertEqual(result, 1)
        output = stdout.getvalue()
        self.assertIn("run_browser_post_status=pending_manual", output)
        self.assertIn("run_browser_post_error=Hydrated provenance is incomplete.", output)

    def test_run_browser_job_cli_returns_nonzero_for_interactive_required_execute_mode(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            source_adapter="fab",
            pack_id="RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
            steps_emitted=["open"],
            dry_run=False,
            executed=False,
            execution_mode="interactive_required",
            browser_profile_dir=Path("scripts/asset_factory/.private/fab_browser_profile"),
            artifacts_dir=Path("scripts/asset_factory/state/generated/playwright_exec"),
            last_url="https://www.fab.com/login",
            attempts=2,
            error="login required",
        )

        with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result):
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "run-browser-job",
                        "--job-spec",
                        "state/generated/browser_job.json",
                        "--execute",
                        "--retries",
                        "2",
                    ]
                )

        self.assertEqual(result, 1)
        output = stdout.getvalue()
        self.assertIn("run_browser_mode=interactive_required", output)
        self.assertIn("run_browser_error=login required", output)

    def test_run_browser_job_cli_returns_nonzero_for_repair_required_execute_mode(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            source_adapter="fab",
            pack_id="RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
            steps_emitted=["open"],
            dry_run=False,
            executed=False,
            execution_mode="repair_required",
            browser_profile_dir=Path("scripts/asset_factory/.private/fab_browser_profile"),
            artifacts_dir=None,
            last_url="",
            attempts=0,
            error="Fab auth must be repaired.",
            repair_reason="auth_state_stale",
            repair_command="python scripts/cli.py asset-factory fab-auth --reuse-profile",
            provider_runbook_id="fab",
        )

        with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result):
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "run-browser-job",
                        "--job-spec",
                        "state/generated/browser_job.json",
                        "--execute",
                    ]
                )

        self.assertEqual(result, 1)
        output = stdout.getvalue()
        self.assertIn("run_browser_mode=repair_required", output)
        self.assertIn("run_browser_repair_reason=auth_state_stale", output)
        self.assertIn("run_browser_repair_command=python scripts/cli.py asset-factory fab-auth --reuse-profile", output)
        self.assertIn("run_browser_provider_runbook=fab", output)

    def test_run_unity_claim_wave_cli_autochains_postprocess_and_ingest_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "unity_claim_wave"
            wave_json = root / "unity_download_wave.json"
            job_spec = root / "browser_jobs" / "SHARED_UNITY_ANM_PACK_01" / "browser_job.json"
            artifacts_dir = root / "artifacts"
            claim_state_path = artifacts_dir / "unity_claim_state.json"
            wave_json.write_text(json.dumps({"items": [], "browser_jobs": []}), encoding="utf-8")
            job_spec.parent.mkdir(parents=True, exist_ok=True)
            job_spec.write_text(json.dumps({"pack_id": "SHARED_UNITY_ANM_PACK_01"}), encoding="utf-8")
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            claim_state_path.write_text(
                json.dumps({"purchased": True, "openInUnity": True, "myAssetsContainsProduct": False}),
                encoding="utf-8",
            )

            fake_run_result = unittest.mock.Mock(
                execution_mode="playwright_structured",
                attempts=2,
                last_url="https://assetstore.unity.com/packages/animation/example",
                artifacts_dir=artifacts_dir,
                browser_profile_dir=Path(".private/unity_profile"),
                error="",
            )
            fake_postprocess = {
                "status": "executed",
                "source_dir": "C:/tmp/source_dir",
                "hydration": {
                    "status": "completed",
                    "provenance_path": "C:/tmp/source_dir/provenance.json",
                    "hydration_report_path": "C:/tmp/source_dir/provenance_hydration_report.json",
                },
                "prepare_pack": {
                    "current_state": "packeted",
                    "packet_path": "C:/tmp/publish/shared/SHARED_UNITY_ANM_PACK_01/packet.json",
                },
                "auto_intake": {
                    "pass": True,
                    "handoff_receipt_path": "C:/tmp/publish/shared/SHARED_UNITY_ANM_PACK_01/handoff_receipt.json",
                },
            }
            fake_ingest_report = {
                "output_dir": str(output_dir / "unity_project_ingest_wave"),
                "project_path": "C:/Users/me/Documents/Unity AssetBoy/ProjectA",
                "summary": {"selected_jobs": 1, "claimed_or_owned": 1},
            }
            selected_items = [
                {
                    "name": "Human Melee Animations",
                    "pack_id": "SHARED_UNITY_ANM_PACK_01",
                    "category": "animation",
                    "url": "https://assetstore.unity.com/packages/animation/example",
                    "browser_job_spec": str(job_spec),
                }
            ]
            stdout = io.StringIO()

            with patch.object(cli, "select_unity_download_wave_jobs", return_value=selected_items):
                with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_run_result) as fake_run:
                    with patch.object(cli, "_postprocess_browser_job", return_value=fake_postprocess) as fake_post:
                        with patch.object(cli, "emit_unity_project_ingest_wave", return_value=fake_ingest_report) as fake_ingest:
                            with redirect_stdout(stdout):
                                result = cli.main(
                                    [
                                        "run-unity-claim-wave",
                                        "--wave-json",
                                        str(wave_json),
                                        "--headless",
                                        "--browser-profile-dir",
                                        ".private/unity_profile",
                                        "--timeout-ms",
                                        "25000",
                                        "--retries",
                                        "2",
                                        "--hydrate-provenance",
                                        "--prepare-pack",
                                        "--auto-intake",
                                        "--cleanup-mode",
                                        "skip",
                                        "--asset-kind",
                                        "animation",
                                        "--packet-status",
                                        "reviewed_real",
                                        "--emit-project-ingest-wave",
                                        "--project-path",
                                        "C:/Users/me/Documents/Unity AssetBoy/ProjectA",
                                        "--game-scope",
                                        "shared",
                                        "--output-dir",
                                        str(output_dir),
                                    ]
                                )

            self.assertEqual(result, 0)
            fake_run.assert_called_once()
            self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/unity_profile"))
            self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 25000)
            self.assertEqual(fake_run.call_args.kwargs["retries"], 2)
            fake_post.assert_called_once()
            self.assertEqual(fake_post.call_args.kwargs["fallback_pack_id"], "SHARED_UNITY_ANM_PACK_01")
            self.assertEqual(fake_post.call_args.kwargs["fallback_game_scope"], "shared")
            self.assertTrue(fake_post.call_args.kwargs["auto_intake"])
            fake_ingest.assert_called_once()
            self.assertTrue(fake_ingest.call_args.kwargs["claimed_or_owned_only"])
            report = json.loads((output_dir / "unity_claim_wave.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["executed"], 1)
            self.assertEqual(report["summary"]["pending_manual"], 0)
            self.assertEqual(report["summary"]["claimed_or_owned"], 1)
            self.assertEqual(report["summary"]["handoff_ready"], 1)
            self.assertEqual(report["project_ingest_wave"]["selected_jobs"], 1)
            self.assertEqual(report["results"][0]["auto_intake_pass"], True)
            self.assertEqual(
                report["results"][0]["handoff_receipt_path"],
                "C:/tmp/publish/shared/SHARED_UNITY_ANM_PACK_01/handoff_receipt.json",
            )
            output = stdout.getvalue()
            self.assertIn("unity_claim_wave_executed=1", output)
            self.assertIn("unity_claim_wave_handoff_ready=1", output)
            self.assertIn("unity_claim_wave_project_ingest_json=", output)

    def test_run_unity_claim_wave_then_print_pack_readiness_reports_gate_pass_progression(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack_id = "SHARED_UNITY_ANM_PACK_01"
            output_dir = root / "unity_claim_wave"
            wave_json = root / "unity_download_wave.json"
            job_spec = root / "browser_jobs" / pack_id / "browser_job.json"
            artifacts_dir = root / "artifacts"
            claim_state_path = artifacts_dir / "unity_claim_state.json"
            library_root = root / "library"
            imported_root = root / "imported"
            packet_dir = library_root / "publish" / "flax_intake" / "shared" / pack_id
            packet_path = packet_dir / "packet.json"
            provenance_path = packet_dir / "provenance.json"
            payload_dir = packet_dir / "payload"
            payload_file = payload_dir / "anim.fbx"
            receipt_path = packet_dir / cli.HANDOFF_RECEIPT_FILENAME

            wave_json.write_text(json.dumps({"items": [], "browser_jobs": []}), encoding="utf-8")
            job_spec.parent.mkdir(parents=True, exist_ok=True)
            job_spec.write_text(json.dumps({"pack_id": pack_id}), encoding="utf-8")
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            claim_state_path.write_text(
                json.dumps({"purchased": True, "openInUnity": True, "myAssetsContainsProduct": False}),
                encoding="utf-8",
            )

            payload_dir.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"fbx")
            packet_path.write_text("{}", encoding="utf-8")
            provenance_path.write_text("{}", encoding="utf-8")
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": cli.HANDOFF_RECEIPT_SCHEMA_VERSION,
                        "receipt_kind": "auto_intake",
                        "written_at": "2026-04-05T01:00:00+00:00",
                        "logged_at": "2026-04-05T01:00:00+00:00",
                        "pack_id": pack_id,
                        "game_scope": "shared",
                        "pass": True,
                        "status": "validated_pending_mcp",
                        "errors": [],
                        "warnings": [],
                        "mcp_call": f"assetboy_ops run_intake  pack_id={pack_id}  game_scope=shared",
                    }
                ),
                encoding="utf-8",
            )
            (imported_root / pack_id).mkdir(parents=True, exist_ok=True)

            fake_run_result = unittest.mock.Mock(
                execution_mode="playwright_structured",
                attempts=1,
                last_url="https://assetstore.unity.com/packages/animation/example",
                artifacts_dir=artifacts_dir,
                browser_profile_dir=Path(".private/unity_profile"),
                error="",
            )
            fake_postprocess = {
                "status": "executed",
                "source_dir": str(packet_dir),
                "hydration": {
                    "status": "completed",
                    "register_packet_ready": True,
                    "provenance_confidence_band": "high",
                    "provenance_confidence_score": 92,
                    "provenance_path": str(provenance_path),
                    "hydration_report_path": str(packet_dir / "provenance_hydration_report.json"),
                },
                "prepare_pack": {
                    "current_state": "packeted",
                    "packet_path": str(packet_path),
                },
                "auto_intake": {
                    "pass": True,
                    "handoff_receipt_path": str(receipt_path),
                },
            }
            selected_items = [
                {
                    "name": "Human Melee Animations",
                    "pack_id": pack_id,
                    "category": "animation",
                    "url": "https://assetstore.unity.com/packages/animation/example",
                    "browser_job_spec": str(job_spec),
                }
            ]
            stdout_claim = io.StringIO()

            with patch.object(cli, "select_unity_download_wave_jobs", return_value=selected_items):
                with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_run_result):
                    with patch.object(cli, "_postprocess_browser_job", return_value=fake_postprocess):
                        with redirect_stdout(stdout_claim):
                            claim_code = cli.main(
                                [
                                    "run-unity-claim-wave",
                                    "--wave-json",
                                    str(wave_json),
                                    "--headless",
                                    "--hydrate-provenance",
                                    "--prepare-pack",
                                    "--auto-intake",
                                    "--cleanup-mode",
                                    "skip",
                                    "--asset-kind",
                                    "animation",
                                    "--packet-status",
                                    "reviewed_real",
                                    "--game-scope",
                                    "shared",
                                    "--output-dir",
                                    str(output_dir),
                                ]
                            )

            self.assertEqual(claim_code, 0)
            claim_report = json.loads((output_dir / "unity_claim_wave.json").read_text(encoding="utf-8"))
            self.assertEqual(claim_report["summary"]["executed"], 1)
            self.assertEqual(claim_report["summary"]["handoff_ready"], 1)
            self.assertEqual(claim_report["summary"]["register_packet_ready"], 1)
            self.assertTrue(claim_report["results"][0]["register_packet_ready"])
            self.assertEqual(claim_report["results"][0]["handoff_receipt_path"], str(receipt_path))

            fake_plan = unittest.mock.Mock(
                game_scope="roman_arena",
                gate_report=unittest.mock.Mock(pass_state=True),
                tasks=[],
            )
            stdout_readiness = io.StringIO()
            with patch.object(cli, "_resolve_gate_catalog_paths", return_value=(Path("gate.json"), Path("catalog.json"))):
                with patch.object(cli, "plan_roman_blockers", return_value=fake_plan):
                    with patch.object(cli, "PRIORITY_SHARED_PACK_ALIASES", {pack_id: (pack_id,)}):
                        with patch.object(cli, "PRIORITY_SHARED_LANES", {pack_id: "manual_browser"}):
                            with patch.object(cli, "asset_library_root", return_value=library_root):
                                with patch.object(cli, "imported_packs_dir", return_value=imported_root):
                                    with patch.object(
                                        cli,
                                        "validate_packet",
                                        return_value=unittest.mock.Mock(pass_=True, errors=[]),
                                    ):
                                        with patch.object(cli, "_latest_intake_statuses", return_value={}):
                                            with redirect_stdout(stdout_readiness):
                                                readiness_code = cli._run_print_pack_readiness(
                                                    None,
                                                    None,
                                                    as_json=True,
                                                    groups=["shared_priority"],
                                                )

            self.assertEqual(readiness_code, 0)
            readiness_payload = json.loads(stdout_readiness.getvalue())
            self.assertEqual(readiness_payload["summary"]["gate_pass"], 1)
            self.assertEqual(readiness_payload["summary"]["blocked"], 0)
            self.assertEqual(len(readiness_payload["rows"]), 1)
            row = readiness_payload["rows"][0]
            self.assertEqual(row["pack_id"], pack_id)
            self.assertEqual(row["state"], "gate_pass")
            self.assertTrue(row["gate_pass"])
            self.assertEqual(row["handoff_source"], "handoff_receipt")
            self.assertEqual(row["handoff_receipt_path"], str(receipt_path))

    def test_run_mixamo_batch_cli_passes_execution_flags(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            pack_id="RA_PACK_CHR_CORE_SLICE_01",
            search="male fighter humanoid base",
            steps=[{"action": "navigate"}],
            executed=True,
            execution_mode="playwright_structured",
            artifacts_dir=Path("scripts/asset_factory/state/generated/mixamo_exec"),
        )

        with patch("assetboy.execution.playwright_runner.run_mixamo_batch", return_value=[fake_result]) as fake_run:
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "run-mixamo-batch",
                        "--pack-id",
                        "RA_PACK_CHR_CORE_SLICE_01",
                        "--search",
                        "male fighter humanoid base",
                        "--execute",
                        "--headless",
                        "--browser-profile-dir",
                        ".private/custom_profile",
                        "--timeout-ms",
                        "9000",
                    ]
                )

        self.assertEqual(result, 0)
        fake_run.assert_called_once()
        self.assertTrue(fake_run.call_args.kwargs["execute"])
        self.assertFalse(fake_run.call_args.kwargs["headed"])
        self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
        self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 9000)
        output = stdout.getvalue()
        self.assertIn("executed=True mode=playwright_structured", output)
        self.assertIn(f"mixamo_artifacts={fake_result.artifacts_dir}", output)

    def test_run_freesound_batch_cli_passes_execution_flags(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            pack_id="RA_PACK_AUD_SFX_SLICE_01",
            search="sword clash metal impact",
            steps=[{"action": "navigate"}],
            executed=True,
            execution_mode="playwright_structured",
            artifacts_dir=Path("scripts/asset_factory/state/generated/freesound_exec"),
        )

        with patch("assetboy.execution.freesound_runner.run_freesound_batch", return_value=[fake_result]) as fake_run:
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "run-freesound-batch",
                        "--pack-id",
                        "RA_PACK_AUD_SFX_SLICE_01",
                        "--search",
                        "sword clash metal impact",
                        "--execute",
                        "--headless",
                        "--browser-profile-dir",
                        ".private/custom_profile",
                        "--timeout-ms",
                        "5000",
                    ]
                )

        self.assertEqual(result, 0)
        fake_run.assert_called_once()
        self.assertTrue(fake_run.call_args.kwargs["execute"])
        self.assertFalse(fake_run.call_args.kwargs["headed"])
        self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
        self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 5000)
        output = stdout.getvalue()
        self.assertIn("executed=True mode=playwright_structured", output)
        self.assertIn(f"freesound_artifacts={fake_result.artifacts_dir}", output)

    def test_run_music_batch_cli_passes_execution_flags(self) -> None:
        stdout = io.StringIO()
        fake_result = unittest.mock.Mock(
            pack_id="RA_PACK_AUD_MUSIC_SLICE_01",
            source="mixkit",
            steps=[{"action": "navigate"}],
            executed=True,
            execution_mode="playwright_structured",
            artifacts_dir=Path("scripts/asset_factory/state/generated/music_exec"),
        )

        with patch("assetboy.execution.music_runner.run_music_batch", return_value=[fake_result]) as fake_run:
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "run-music-batch",
                        "--source",
                        "mixkit",
                        "--pack-id",
                        "RA_PACK_AUD_MUSIC_SLICE_01",
                        "--search",
                        "epic battle",
                        "--execute",
                        "--headless",
                        "--browser-profile-dir",
                        ".private/custom_profile",
                        "--timeout-ms",
                        "6000",
                    ]
                )

        self.assertEqual(result, 0)
        fake_run.assert_called_once()
        self.assertTrue(fake_run.call_args.kwargs["execute"])
        self.assertFalse(fake_run.call_args.kwargs["headed"])
        self.assertEqual(fake_run.call_args.kwargs["browser_profile_dir"], Path(".private/custom_profile"))
        self.assertEqual(fake_run.call_args.kwargs["timeout_ms"], 6000)
        output = stdout.getvalue()
        self.assertIn("executed=True mode=playwright_structured", output)
        self.assertIn(f"music_artifacts={fake_result.artifacts_dir}", output)
