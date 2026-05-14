"""Tests for assetboy.workflows.recipe_diff (Path B v1.7.s14)."""

from __future__ import annotations

import unittest

from assetboy.workflows.recipe_diff import (
    DiffResult,
    diff_recipes,
    diff_result_to_dict,
)


def _r(packs: list[dict], recipe_id: str = "test", game: str = "test") -> dict:
    return {"recipe": {"id": recipe_id, "game": game}, "packs": packs}


class AddedRemovedTests(unittest.TestCase):
    def test_added_pack_detected(self) -> None:
        old = _r([{"id": "A", "provider": "polyhaven"}])
        new = _r([
            {"id": "A", "provider": "polyhaven"},
            {"id": "B", "provider": "kenney"},
        ])
        d = diff_recipes(old, new)
        self.assertEqual(d.added_packs, ["B"])
        self.assertEqual(d.removed_packs, [])

    def test_removed_pack_detected(self) -> None:
        old = _r([
            {"id": "A", "provider": "polyhaven"},
            {"id": "B", "provider": "kenney"},
        ])
        new = _r([{"id": "A", "provider": "polyhaven"}])
        d = diff_recipes(old, new)
        self.assertEqual(d.added_packs, [])
        self.assertEqual(d.removed_packs, ["B"])

    def test_no_changes_returns_empty_diff(self) -> None:
        recipe = _r([{"id": "A", "provider": "polyhaven", "asset_kind": "texture"}])
        d = diff_recipes(recipe, recipe)
        self.assertFalse(d.has_changes)


class ModifiedFieldTests(unittest.TestCase):
    def test_provider_change_detected(self) -> None:
        old = _r([{"id": "A", "provider": "polyhaven"}])
        new = _r([{"id": "A", "provider": "kenney"}])
        d = diff_recipes(old, new)
        self.assertEqual(len(d.modified_packs), 1)
        mod = d.modified_packs[0]
        self.assertEqual(mod.pack_id, "A")
        provider_changes = [c for c in mod.changed_fields if c.field == "provider"]
        self.assertEqual(len(provider_changes), 1)
        self.assertEqual(provider_changes[0].old, "polyhaven")
        self.assertEqual(provider_changes[0].new, "kenney")

    def test_acquisition_method_change_detected(self) -> None:
        old = _r([{"id": "A", "acquisition_method": "direct_url"}])
        new = _r([{"id": "A", "acquisition_method": "generator"}])
        d = diff_recipes(old, new)
        self.assertEqual(len(d.modified_packs), 1)
        changed_fields = [c.field for c in d.modified_packs[0].changed_fields]
        self.assertIn("acquisition_method", changed_fields)

    def test_nested_license_kind_change_detected(self) -> None:
        old = _r([{"id": "A", "license": {"kind": "cc0"}}])
        new = _r([{"id": "A", "license": {"kind": "fab_standard"}}])
        d = diff_recipes(old, new)
        self.assertEqual(len(d.modified_packs), 1)
        license_changes = [
            c for c in d.modified_packs[0].changed_fields if c.field == "license.kind"
        ]
        self.assertEqual(len(license_changes), 1)
        self.assertEqual(license_changes[0].old, "cc0")
        self.assertEqual(license_changes[0].new, "fab_standard")

    def test_prompts_count_change_detected(self) -> None:
        old = _r([{"id": "A", "prompts": [{"text": "p1"}]}])
        new = _r([{"id": "A", "prompts": [{"text": "p1"}, {"text": "p2"}]}])
        d = diff_recipes(old, new)
        self.assertEqual(len(d.modified_packs), 1)
        count_changes = [
            c for c in d.modified_packs[0].changed_fields if c.field == "prompts.count"
        ]
        self.assertEqual(len(count_changes), 1)
        self.assertEqual(count_changes[0].old, 1)
        self.assertEqual(count_changes[0].new, 2)

    def test_assets_count_change_detected(self) -> None:
        old = _r([{"id": "A", "assets": [{"asset_id": "x"}]}])
        new = _r([{"id": "A", "assets": []}])
        d = diff_recipes(old, new)
        self.assertEqual(len(d.modified_packs), 1)
        count_changes = [
            c for c in d.modified_packs[0].changed_fields if c.field == "assets.count"
        ]
        self.assertEqual(count_changes[0].old, 1)
        self.assertEqual(count_changes[0].new, 0)

    def test_unchanged_pack_not_in_modified_list(self) -> None:
        identical_pack = {"id": "X", "provider": "polyhaven", "asset_kind": "texture"}
        old = _r([identical_pack])
        new = _r([dict(identical_pack)])  # copy, same content
        d = diff_recipes(old, new)
        self.assertEqual(d.modified_packs, [])


class GateTests(unittest.TestCase):
    def test_added_required_pack_id_detected(self) -> None:
        old = {"recipe": {"id": "x", "game": "y"}, "packs": [{"id": "A"}],
               "gates": {"required_pack_ids": ["A"]}}
        new = {"recipe": {"id": "x", "game": "y"},
               "packs": [{"id": "A"}, {"id": "B"}],
               "gates": {"required_pack_ids": ["A", "B"]}}
        d = diff_recipes(old, new)
        self.assertEqual(d.gate_changes.get("added_required_pack_ids"), ["B"])

    def test_removed_required_pack_id_detected(self) -> None:
        old = {"recipe": {"id": "x", "game": "y"}, "packs": [{"id": "A"}, {"id": "B"}],
               "gates": {"required_pack_ids": ["A", "B"]}}
        new = {"recipe": {"id": "x", "game": "y"}, "packs": [{"id": "A"}],
               "gates": {"required_pack_ids": ["A"]}}
        d = diff_recipes(old, new)
        self.assertEqual(d.gate_changes.get("removed_required_pack_ids"), ["B"])


class RecipeFieldChangeTests(unittest.TestCase):
    def test_recipe_description_change_detected(self) -> None:
        old = {"recipe": {"id": "x", "game": "y", "description": "old"}, "packs": []}
        new = {"recipe": {"id": "x", "game": "y", "description": "new"}, "packs": []}
        d = diff_recipes(old, new)
        desc_changes = [c for c in d.recipe_field_changes if c.field == "recipe.description"]
        self.assertEqual(len(desc_changes), 1)


class ToleranceTests(unittest.TestCase):
    def test_none_input_treated_as_empty(self) -> None:
        d = diff_recipes(None, None)  # type: ignore[arg-type]
        self.assertFalse(d.has_changes)

    def test_packs_without_id_ignored(self) -> None:
        old = _r([{"provider": "polyhaven"}])  # no id
        new = _r([{"id": "A", "provider": "polyhaven"}])
        d = diff_recipes(old, new)
        self.assertEqual(d.added_packs, ["A"])  # only valid-id pack counted


class SerializationTests(unittest.TestCase):
    def test_diff_result_to_dict_round_trips_via_json(self) -> None:
        import json
        old = _r([{"id": "A", "provider": "polyhaven"}])
        new = _r([{"id": "A", "provider": "kenney"}, {"id": "B"}])
        d = diff_recipes(old, new)
        as_dict = diff_result_to_dict(d)
        serialized = json.dumps(as_dict)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["added_packs"], ["B"])
        self.assertEqual(parsed["has_changes"], True)
        self.assertEqual(len(parsed["modified_packs"]), 1)


class CliDiffTests(unittest.TestCase):
    """v1.7.s14: pack diff CLI command works against real recipes."""

    def setUp(self) -> None:
        from assetboy.cli.app import app
        from typer.testing import CliRunner
        self.app = app
        self.runner = CliRunner()

    def test_diff_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "diff", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Semantic diff", result.stdout)

    def test_diff_identical_recipes_no_changes(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "diff",
             "sandbox/one_pack_smoke.yaml",
             "sandbox/one_pack_smoke.yaml"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("pack_diff_has_changes=false", result.stdout)

    def test_diff_different_recipes_detected(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "diff",
             "sandbox/one_pack_smoke.yaml",
             "primitive_tech/first_playable.yaml"],
        )
        # exit 1 expected (changes detected)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("pack_diff_has_changes=true", result.stdout)
        # primitive_tech has 9 packs, sandbox has 1; expect 9 added + 1 removed
        self.assertIn("pack_diff_added_count=9", result.stdout)
        self.assertIn("pack_diff_removed_count=1", result.stdout)

    def test_diff_json_mode(self) -> None:
        import json
        result = self.runner.invoke(
            self.app,
            ["pack", "diff",
             "sandbox/one_pack_smoke.yaml",
             "sandbox/one_pack_smoke.yaml",
             "--json"],
        )
        self.assertEqual(result.exit_code, 0)
        parsed = json.loads(result.stdout)
        self.assertFalse(parsed["has_changes"])
        self.assertEqual(parsed["added_packs"], [])

    def test_diff_missing_recipe_errors(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "diff", "missing_a.yaml", "missing_b.yaml"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("recipe_not_found", result.stdout)

    def test_diff_html_no_changes(self) -> None:
        """v1.52.s261: --html writes report; identical recipes exit 0."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "diff.html"
            result = self.runner.invoke(
                self.app,
                ["pack", "diff",
                 "sandbox/one_pack_smoke.yaml",
                 "sandbox/one_pack_smoke.yaml",
                 "--html", str(html_path)],
            )
            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("pack_diff_html_path=", result.stdout)
            self.assertTrue(html_path.exists())
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", body)
            self.assertIn("FAW Recipe Diff", body)
            self.assertIn("NO CHANGES", body)

    def test_diff_html_with_changes_exits_1(self) -> None:
        """--html with detected changes exits 1 and writes file."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "diff.html"
            result = self.runner.invoke(
                self.app,
                ["pack", "diff",
                 "sandbox/one_pack_smoke.yaml",
                 "primitive_tech/first_playable.yaml",
                 "--html", str(html_path)],
            )
            self.assertEqual(result.exit_code, 1)
            self.assertTrue(html_path.exists())
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("CHANGES", body)


if __name__ == "__main__":
    unittest.main()
