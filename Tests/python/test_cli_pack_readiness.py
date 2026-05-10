from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from assetboy import cli


class CliPackReadinessTests(unittest.TestCase):
    def test_print_pack_readiness_outputs_machine_readable_progression_json(self) -> None:
        fake_plan = SimpleNamespace(
            game_scope="roman_arena",
            gate_report=SimpleNamespace(pass_state=True),
            tasks=[
                SimpleNamespace(
                    pack_id="RA_PACK_READY",
                    lane=SimpleNamespace(value="manual_browser"),
                    ready_for_flax_packet=True,
                    imported_into_flax=False,
                    audit_findings=(),
                ),
                SimpleNamespace(
                    pack_id="RA_PACK_BLOCKED",
                    lane=SimpleNamespace(value="direct_url"),
                    ready_for_flax_packet=False,
                    imported_into_flax=False,
                    audit_findings=("missing payload",),
                ),
            ],
        )
        shared_rows = [
            {
                "group": "shared_priority",
                "pack_id": "SHARED_IMPORTED_ONLY",
                "alias_pack_ids": ["SHARED_IMPORTED_ONLY"],
                "lane": "shared_pack",
                "state": "imported",
                "ready_reviewed": True,
                "imported": True,
                "gate_pass": False,
                "intake_validated": False,
                "intake_status": "",
                "intake_logged_at": "",
                "scope": "shared",
                "source_pack_id": "SHARED_IMPORTED_ONLY",
                "packet_path": "C:/tmp/packet.json",
                "reason": "",
            },
            {
                "group": "shared_priority",
                "pack_id": "SHARED_GATE_PASS",
                "alias_pack_ids": ["SHARED_GATE_PASS"],
                "lane": "shared_pack",
                "state": "gate_pass",
                "ready_reviewed": True,
                "imported": True,
                "gate_pass": True,
                "intake_validated": True,
                "intake_status": "validated_pending_mcp",
                "intake_logged_at": "2026-04-04T10:00:00+00:00",
                "scope": "shared",
                "source_pack_id": "SHARED_GATE_PASS",
                "packet_path": "C:/tmp/packet.json",
                "reason": "",
            },
        ]

        with patch.object(cli, "_resolve_gate_catalog_paths", return_value=(Path("gate.json"), Path("catalog.json"))):
            with patch.object(cli, "plan_roman_blockers", return_value=fake_plan):
                with patch.object(cli, "_shared_pack_readiness_rows", return_value=shared_rows):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        code = cli._run_print_pack_readiness(None, None, as_json=True)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["blocked"], 1)
        self.assertEqual(payload["summary"]["ready_reviewed"], 1)
        self.assertEqual(payload["summary"]["imported"], 1)
        self.assertEqual(payload["summary"]["gate_pass"], 1)
        self.assertEqual(payload["summary"]["import_pending"], 1)
        self.assertEqual(payload["all_summary"]["total"], 4)
        self.assertEqual(payload["filters"]["states"], [])
        self.assertEqual(payload["filters"]["groups"], [])
        self.assertFalse(payload["filters"]["import_pending_only"])
        self.assertIn("roman_arena", payload["summary_by_group"])
        self.assertIn("shared_priority", payload["summary_by_group"])

        row_by_pack = {row["pack_id"]: row for row in payload["rows"]}
        self.assertEqual(row_by_pack["RA_PACK_READY"]["state"], "ready_reviewed")
        self.assertEqual(row_by_pack["RA_PACK_BLOCKED"]["state"], "blocked")
        self.assertEqual(row_by_pack["SHARED_IMPORTED_ONLY"]["state"], "imported")
        self.assertEqual(row_by_pack["SHARED_GATE_PASS"]["state"], "gate_pass")
        self.assertTrue(row_by_pack["RA_PACK_READY"]["import_pending"])
        self.assertFalse(row_by_pack["SHARED_GATE_PASS"]["import_pending"])

    def test_print_pack_readiness_filters_import_pending_rows(self) -> None:
        fake_plan = SimpleNamespace(
            game_scope="roman_arena",
            gate_report=SimpleNamespace(pass_state=True),
            tasks=[
                SimpleNamespace(
                    pack_id="RA_PACK_READY",
                    lane=SimpleNamespace(value="manual_browser"),
                    ready_for_flax_packet=True,
                    imported_into_flax=False,
                    audit_findings=(),
                ),
                SimpleNamespace(
                    pack_id="RA_PACK_IMPORTED",
                    lane=SimpleNamespace(value="direct_url"),
                    ready_for_flax_packet=True,
                    imported_into_flax=True,
                    audit_findings=(),
                ),
            ],
        )
        shared_rows = [
            {
                "group": "shared_priority",
                "pack_id": "SHARED_GATE_PASS",
                "alias_pack_ids": ["SHARED_GATE_PASS"],
                "lane": "shared_pack",
                "state": "gate_pass",
                "ready_reviewed": True,
                "imported": False,
                "gate_pass": True,
                "intake_validated": True,
                "intake_status": "validated_pending_mcp",
                "intake_logged_at": "2026-04-04T10:00:00+00:00",
                "scope": "shared",
                "source_pack_id": "SHARED_GATE_PASS",
                "packet_path": "C:/tmp/packet.json",
                "reason": "",
            }
        ]

        with patch.object(cli, "_resolve_gate_catalog_paths", return_value=(Path("gate.json"), Path("catalog.json"))):
            with patch.object(cli, "plan_roman_blockers", return_value=fake_plan):
                with patch.object(cli, "_shared_pack_readiness_rows", return_value=shared_rows):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        code = cli._run_print_pack_readiness(
                            None,
                            None,
                            as_json=True,
                            states=["ready_reviewed"],
                            import_pending_only=True,
                        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["import_pending"], 1)
        self.assertEqual(payload["all_summary"]["total"], 3)
        self.assertEqual(payload["filters"]["states"], ["ready_reviewed"])
        self.assertEqual(payload["filters"]["groups"], [])
        self.assertTrue(payload["filters"]["import_pending_only"])
        self.assertEqual([row["pack_id"] for row in payload["rows"]], ["RA_PACK_READY"])

    def test_print_pack_readiness_filters_by_group_and_emits_group_summary(self) -> None:
        shared_rows = [
            {
                "group": "shared_priority",
                "pack_id": "SHARED_BLOCKED",
                "alias_pack_ids": ["SHARED_BLOCKED"],
                "lane": "shared_pack",
                "state": "blocked",
                "ready_reviewed": False,
                "imported": False,
                "gate_pass": False,
                "intake_validated": False,
                "intake_status": "",
                "intake_logged_at": "",
                "scope": "shared",
                "source_pack_id": "SHARED_BLOCKED",
                "packet_path": "",
                "reason": "missing packet",
            }
        ]

        with patch.object(cli, "_resolve_gate_catalog_paths", side_effect=AssertionError("roman gate lookup should be skipped")):
            with patch.object(cli, "plan_roman_blockers", side_effect=AssertionError("roman planning should be skipped")):
                with patch.object(cli, "_shared_pack_readiness_rows", return_value=shared_rows):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        code = cli._run_print_pack_readiness(
                            None,
                            None,
                            as_json=True,
                            groups=["shared_priority"],
                        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["filters"]["groups"], ["shared_priority"])
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["rows"][0]["pack_id"], "SHARED_BLOCKED")
        self.assertEqual(set(payload["summary_by_group"].keys()), {"shared_priority"})
        self.assertEqual(payload["summary_by_group"]["shared_priority"]["blocked"], 1)
        self.assertIsNone(payload["roman_plan_error"])
        self.assertIsNone(payload["gate_path"])
        self.assertIsNone(payload["catalog_path"])

    def test_print_pack_readiness_degrades_when_roman_plan_is_unavailable(self) -> None:
        shared_rows = [
            {
                "group": "shared_priority",
                "pack_id": "SHARED_BLOCKED",
                "alias_pack_ids": ["SHARED_BLOCKED"],
                "lane": "shared_pack",
                "state": "blocked",
                "ready_reviewed": False,
                "imported": False,
                "gate_pass": False,
                "intake_validated": False,
                "intake_status": "",
                "intake_logged_at": "",
                "scope": "shared",
                "source_pack_id": "SHARED_BLOCKED",
                "packet_path": "",
                "reason": "missing packet",
            }
        ]

        with patch.object(cli, "_resolve_gate_catalog_paths", return_value=(Path("missing_gate.json"), Path("catalog.json"))):
            with patch.object(cli, "plan_roman_blockers", side_effect=FileNotFoundError("missing gate")):
                with patch.object(cli, "_shared_pack_readiness_rows", return_value=shared_rows):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        code = cli._run_print_pack_readiness(None, None, as_json=True)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["blocked"], 1)
        self.assertEqual(payload["rows"][0]["pack_id"], "SHARED_BLOCKED")
        self.assertEqual(payload["gate_path"], "missing_gate.json")
        self.assertEqual(payload["catalog_path"], "catalog.json")
        self.assertIn("missing gate", payload["roman_plan_error"])

    def test_shared_pack_readiness_rows_require_import_and_intake_log_for_gate_pass(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            imported_root = root / "imported"
            packet_path = library_root / "publish" / "flax_intake" / "shared" / "SHARED_HIST_ARCH_ROMAN_CORE_01" / "packet.json"
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            (packet_path.parent / "provenance.json").write_text("{}", encoding="utf-8")
            (packet_path.parent / "payload").mkdir(parents=True, exist_ok=True)
            packet_path.write_text("{}", encoding="utf-8")

            with patch.object(
                cli,
                "PRIORITY_SHARED_PACK_ALIASES",
                {"SHARED_HIST_ARCH_ROMAN_CORE_01": ("SHARED_HIST_ARCH_ROMAN_CORE_01",)},
            ):
                with patch.object(cli, "PRIORITY_SHARED_LANES", {"SHARED_HIST_ARCH_ROMAN_CORE_01": "manual_browser"}):
                    with patch.object(cli, "asset_library_root", return_value=library_root):
                        with patch.object(cli, "imported_packs_dir", return_value=imported_root):
                            with patch.object(
                                cli,
                                "validate_packet",
                                return_value=SimpleNamespace(pass_=True, errors=[]),
                            ):
                                with patch.object(cli, "_latest_intake_statuses", return_value={}):
                                    ready_row = cli._shared_pack_readiness_rows()[0]

                                imported_pack_dir = imported_root / "SHARED_HIST_ARCH_ROMAN_CORE_01"
                                imported_pack_dir.mkdir(parents=True, exist_ok=True)
                                with patch.object(cli, "_latest_intake_statuses", return_value={}):
                                    imported_row = cli._shared_pack_readiness_rows()[0]

                                with patch.object(
                                    cli,
                                    "_latest_intake_statuses",
                                    return_value={
                                        ("shared", "SHARED_HIST_ARCH_ROMAN_CORE_01"): {
                                            "pass": True,
                                            "status": "validated_pending_mcp",
                                            "logged_at": "2026-04-04T10:00:00+00:00",
                                        }
                                    },
                                ):
                                    gate_pass_row = cli._shared_pack_readiness_rows()[0]

        self.assertEqual(ready_row["state"], "ready_reviewed")
        self.assertFalse(ready_row["imported"])
        self.assertFalse(ready_row["gate_pass"])
        self.assertFalse(ready_row["intake_validated"])

        self.assertEqual(imported_row["state"], "imported")
        self.assertTrue(imported_row["imported"])
        self.assertFalse(imported_row["gate_pass"])
        self.assertEqual(imported_row["reason"], "awaiting durable auto-intake handoff receipt")

        self.assertEqual(gate_pass_row["state"], "gate_pass")
        self.assertTrue(gate_pass_row["imported"])
        self.assertTrue(gate_pass_row["gate_pass"])
        self.assertTrue(gate_pass_row["intake_validated"])
        self.assertEqual(gate_pass_row["intake_status"], "validated_pending_mcp")

    def test_shared_pack_readiness_prefers_handoff_receipt_over_intake_log(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            imported_root = root / "imported"
            packet_path = library_root / "publish" / "flax_intake" / "shared" / "SHARED_HIST_ARCH_ROMAN_CORE_01" / "packet.json"
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            (packet_path.parent / "provenance.json").write_text("{}", encoding="utf-8")
            (packet_path.parent / "payload").mkdir(parents=True, exist_ok=True)
            packet_path.write_text("{}", encoding="utf-8")
            receipt_path = packet_path.parent / cli.HANDOFF_RECEIPT_FILENAME
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": cli.HANDOFF_RECEIPT_SCHEMA_VERSION,
                        "receipt_kind": "auto_intake",
                        "written_at": "2026-04-04T10:10:00+00:00",
                        "logged_at": "2026-04-04T10:00:00+00:00",
                        "pack_id": "SHARED_HIST_ARCH_ROMAN_CORE_01",
                        "game_scope": "shared",
                        "pass": True,
                        "status": "validated_pending_mcp",
                        "errors": [],
                        "warnings": [],
                        "mcp_call": "assetboy_ops run_intake  pack_id=SHARED_HIST_ARCH_ROMAN_CORE_01  game_scope=shared",
                    }
                ),
                encoding="utf-8",
            )
            imported_pack_dir = imported_root / "SHARED_HIST_ARCH_ROMAN_CORE_01"
            imported_pack_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(
                cli,
                "PRIORITY_SHARED_PACK_ALIASES",
                {"SHARED_HIST_ARCH_ROMAN_CORE_01": ("SHARED_HIST_ARCH_ROMAN_CORE_01",)},
            ):
                with patch.object(cli, "PRIORITY_SHARED_LANES", {"SHARED_HIST_ARCH_ROMAN_CORE_01": "manual_browser"}):
                    with patch.object(cli, "asset_library_root", return_value=library_root):
                        with patch.object(cli, "imported_packs_dir", return_value=imported_root):
                            with patch.object(
                                cli,
                                "validate_packet",
                                return_value=SimpleNamespace(pass_=True, errors=[]),
                            ):
                                with patch.object(
                                    cli,
                                    "_latest_intake_statuses",
                                    return_value={
                                        ("shared", "SHARED_HIST_ARCH_ROMAN_CORE_01"): {
                                            "pass": False,
                                            "status": "validation_failed",
                                            "logged_at": "2026-04-04T09:00:00+00:00",
                                        }
                                    },
                                ):
                                    row = cli._shared_pack_readiness_rows()[0]

        self.assertEqual(row["state"], "gate_pass")
        self.assertTrue(row["gate_pass"])
        self.assertEqual(row["handoff_source"], "handoff_receipt")
        self.assertEqual(row["handoff_receipt_path"], str(receipt_path))
        self.assertEqual(row["intake_status"], "validated_pending_mcp")
        self.assertEqual(row["intake_logged_at"], "2026-04-04T10:00:00+00:00")

    def test_write_intake_log_returns_receipt_paths_and_receipt_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            library_root = root / "library"
            results = [
                {
                    "pack_id": "SHARED_HIST_ARCH_ROMAN_CORE_01",
                    "game_scope": "shared",
                    "pass": True,
                    "errors": [],
                    "warnings": ["warn"],
                    "mcp_call": "assetboy_ops run_intake  pack_id=SHARED_HIST_ARCH_ROMAN_CORE_01  game_scope=shared",
                }
            ]

            with patch.object(cli, "state_root", return_value=state_dir):
                with patch.object(cli, "asset_library_root", return_value=library_root):
                    payload = cli._write_intake_log(results, quiet=True)

            self.assertEqual(payload["log_path"], state_dir / "intake_log.json")
            self.assertEqual(len(payload["receipt_paths"]), 1)
            receipt_path = payload["receipt_paths"][0]
            self.assertTrue(receipt_path.exists())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], cli.HANDOFF_RECEIPT_SCHEMA_VERSION)
            self.assertEqual(receipt["receipt_kind"], "auto_intake")
            self.assertEqual(receipt["pack_id"], "SHARED_HIST_ARCH_ROMAN_CORE_01")
            self.assertEqual(receipt["game_scope"], "shared")
            self.assertTrue(receipt["pass"])
            self.assertEqual(receipt["status"], "validated_pending_mcp")
            self.assertEqual(receipt["warnings"], ["warn"])

    def test_auto_intake_json_includes_handoff_receipt_paths(self) -> None:
        fake_result = SimpleNamespace(
            pass_=True,
            pack_id="SHARED_HIST_ARCH_ROMAN_CORE_01",
            game_scope="shared",
            errors=[],
            warnings=[],
            to_dict=lambda: {
                "pack_id": "SHARED_HIST_ARCH_ROMAN_CORE_01",
                "game_scope": "shared",
                "pass": True,
                "errors": [],
                "warnings": [],
            },
        )

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            library_root = root / "library"
            packet_dir = library_root / "publish" / "flax_intake" / "shared" / "SHARED_HIST_ARCH_ROMAN_CORE_01"
            packet_dir.mkdir(parents=True, exist_ok=True)
            (packet_dir / "packet.json").write_text("{}", encoding="utf-8")

            with patch("assetboy.library.intake_validator.scan_publish_dir", return_value=[{"pack_id": "SHARED_HIST_ARCH_ROMAN_CORE_01", "game_scope": "shared", "has_packet": True}]):
                with patch("assetboy.library.intake_validator.validate_packet", return_value=fake_result):
                    with patch.object(cli, "state_root", return_value=state_dir):
                        with patch.object(cli, "asset_library_root", return_value=library_root):
                            stdout = io.StringIO()
                            with redirect_stdout(stdout):
                                code = cli._run_auto_intake(
                                    game="shared",
                                    pack_id_filter="SHARED_HIST_ARCH_ROMAN_CORE_01",
                                    as_json=True,
                                    include_examples=False,
                                    dry_run=False,
                                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["results"][0]["status"], "validated_pending_mcp")
        self.assertEqual(len(payload["receipt_paths"]), 1)
        self.assertEqual(payload["results"][0]["handoff_receipt_path"], payload["receipt_paths"][0])
