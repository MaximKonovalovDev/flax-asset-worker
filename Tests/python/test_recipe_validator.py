"""Tests for assetboy.workflows.recipe_validator (Path B v1.6.s5)."""

from __future__ import annotations

import unittest

from assetboy.workflows.recipe_validator import (
    DIRECT_URL_PROVIDERS,
    GENERATOR_PROVIDERS,
    MANUAL_BROWSER_PROVIDERS,
    VALID_ACQUISITION_METHODS,
    validate_recipe_doc,
)


def _ok_recipe() -> dict:
    """Minimal valid recipe shape for happy-path tests."""
    return {
        "recipe": {"id": "test_recipe", "game": "test"},
        "packs": [
            {
                "id": "TP_OK_01",
                "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "asset_kind": "surface_pbr",
                "license": {"kind": "cc0"},
                "assets": [{"asset_id": "brick_wall_01"}],
            },
        ],
    }


class HappyPathTests(unittest.TestCase):
    def test_minimal_valid_recipe_passes(self) -> None:
        r = validate_recipe_doc(_ok_recipe(), "happy.yaml")
        self.assertTrue(r.ok)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.recipe_id, "test_recipe")
        self.assertEqual(r.pack_count, 1)


class RootSchemaTests(unittest.TestCase):
    def test_non_dict_root_errors(self) -> None:
        r = validate_recipe_doc("not a dict", "bad.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("must be a mapping" in e for e in r.errors))

    def test_missing_recipe_block_errors(self) -> None:
        doc = {"packs": []}
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("top-level 'recipe' key" in e for e in r.errors))

    def test_missing_packs_list_errors(self) -> None:
        doc = {"recipe": {"id": "x", "game": "y"}}
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("'packs' must be a list" in e for e in r.errors))

    def test_empty_packs_warns(self) -> None:
        doc = {"recipe": {"id": "x", "game": "y"}, "packs": []}
        r = validate_recipe_doc(doc, "test.yaml")
        # Empty packs is a warning, not an error
        self.assertTrue(r.ok)
        self.assertTrue(any("'packs' list is empty" in w for w in r.warnings))

    def test_missing_recipe_id_errors(self) -> None:
        doc = _ok_recipe()
        doc["recipe"].pop("id")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("recipe.id" in e for e in r.errors))


class PackFieldTests(unittest.TestCase):
    def test_pack_missing_id_errors(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0].pop("id")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("required 'id' field" in e for e in r.errors))

    def test_pack_missing_provider_errors(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0].pop("provider")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("'provider'" in e for e in r.errors))

    def test_duplicate_pack_ids_error(self) -> None:
        doc = _ok_recipe()
        doc["packs"].append(dict(doc["packs"][0]))
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("duplicate pack id" in e for e in r.errors))


class AcquisitionMethodTests(unittest.TestCase):
    def test_unknown_method_errors(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0]["acquisition_method"] = "magic"
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("unknown acquisition_method" in e for e in r.errors))

    def test_canonical_methods_accepted(self) -> None:
        for method in VALID_ACQUISITION_METHODS:
            doc = _ok_recipe()
            doc["packs"][0]["acquisition_method"] = method
            # Add method-specific fields to satisfy other validators:
            if method == "manual_browser":
                doc["packs"][0]["provider"] = "fab"
                doc["packs"][0]["source_url"] = "https://example.com"
                doc["packs"][0].pop("assets", None)
            elif method == "generator":
                doc["packs"][0]["provider"] = "comfyui"
                doc["packs"][0]["prompts"] = [{"text": "test"}]
                doc["packs"][0].pop("assets", None)
            r = validate_recipe_doc(doc, f"test_{method}.yaml")
            self.assertTrue(r.ok, f"{method}: {r.errors}")


class DirectUrlLaneTests(unittest.TestCase):
    def test_direct_url_no_assets_no_search_terms_errors(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0].pop("assets")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(
            any("'assets: [...]' or 'search_terms: [...]'" in e for e in r.errors)
        )

    def test_direct_url_search_terms_only_accepted(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0].pop("assets")
        doc["packs"][0]["search_terms"] = ["axe chop oak"]
        doc["packs"][0]["provider"] = "freesound"
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_direct_url_unknown_provider_warns_not_errors(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0]["provider"] = "mystery_provider"
        r = validate_recipe_doc(doc, "test.yaml")
        # Still ok (we allow unknown providers at validate time; runtime fails clean)
        self.assertTrue(r.ok)
        self.assertTrue(any("not in known direct_url providers" in w for w in r.warnings))


class GeneratorLaneTests(unittest.TestCase):
    def _gen_recipe(self) -> dict:
        return {
            "recipe": {"id": "gen_test", "game": "test"},
            "packs": [
                {
                    "id": "TP_GEN_01",
                    "provider": "comfyui",
                    "acquisition_method": "generator",
                    "asset_kind": "surface_pbr",
                    "license": {"kind": "comfyui_workflow_dependent"},
                    "prompts": [{"text": "stone wall mossy"}],
                },
            ],
        }

    def test_generator_with_prompts_passes(self) -> None:
        r = validate_recipe_doc(self._gen_recipe(), "test.yaml")
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_generator_no_prompts_errors(self) -> None:
        doc = self._gen_recipe()
        doc["packs"][0].pop("prompts")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(any("'prompts: [...]'" in e for e in r.errors))


class ManualBrowserLaneTests(unittest.TestCase):
    def _mb_recipe(self) -> dict:
        return {
            "recipe": {"id": "mb_test", "game": "test"},
            "packs": [
                {
                    "id": "TP_MB_01",
                    "provider": "fab",
                    "acquisition_method": "manual_browser",
                    "asset_kind": "model",
                    "license": {"kind": "fab_standard"},
                    "source_url": "https://www.fab.com/listings/abc",
                },
            ],
        }

    def test_manual_browser_with_source_url_passes(self) -> None:
        r = validate_recipe_doc(self._mb_recipe(), "test.yaml")
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_manual_browser_no_source_no_assets_warns(self) -> None:
        doc = self._mb_recipe()
        doc["packs"][0].pop("source_url")
        r = validate_recipe_doc(doc, "test.yaml")
        # Only a warning, not an error (manual_browser can in principle work
        # without source_url if operator knows where to drop files)
        self.assertTrue(r.ok)
        self.assertTrue(
            any("'source_url' or 'assets: [...]'" in w for w in r.warnings)
        )


class GateTests(unittest.TestCase):
    def test_gates_referencing_unknown_pack_ids_error(self) -> None:
        doc = _ok_recipe()
        doc["gates"] = {
            "required_pack_ids": ["TP_OK_01", "TP_NOT_PRESENT_01"],
        }
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertFalse(r.ok)
        self.assertTrue(
            any("TP_NOT_PRESENT_01" in e for e in r.errors)
        )

    def test_gates_referencing_known_pack_ids_ok(self) -> None:
        doc = _ok_recipe()
        doc["gates"] = {
            "required_pack_ids": ["TP_OK_01"],
            "optional_pack_ids": [],
        }
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_gates_non_dict_warns(self) -> None:
        doc = _ok_recipe()
        doc["gates"] = "not a dict"
        r = validate_recipe_doc(doc, "test.yaml")
        # Warning, not error (gates is optional)
        self.assertTrue(r.ok)
        self.assertTrue(any("'gates' should be a mapping" in w for w in r.warnings))


class WarningsTests(unittest.TestCase):
    def test_missing_asset_kind_warns(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0].pop("asset_kind")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertTrue(r.ok)
        self.assertTrue(any("no 'asset_kind' set" in w for w in r.warnings))

    def test_missing_license_warns(self) -> None:
        doc = _ok_recipe()
        doc["packs"][0].pop("license")
        r = validate_recipe_doc(doc, "test.yaml")
        self.assertTrue(r.ok)
        self.assertTrue(any("no 'license' block" in w for w in r.warnings))


class RealRecipeIntegrationTests(unittest.TestCase):
    """Sanity-check that all shipped recipes pass validation."""

    def test_sandbox_one_pack_smoke_passes(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_file
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        recipe = repo_root / "recipes" / "sandbox" / "one_pack_smoke.yaml"
        r = validate_recipe_file(recipe)
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_sandbox_generator_smoke_passes(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_file
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        recipe = repo_root / "recipes" / "sandbox" / "generator_smoke.yaml"
        r = validate_recipe_file(recipe)
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_primitive_tech_first_playable_passes(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_file
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        recipe = repo_root / "recipes" / "primitive_tech" / "first_playable.yaml"
        r = validate_recipe_file(recipe)
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_roman_first_playable_passes(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_file
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        recipe = repo_root / "recipes" / "roman" / "first_playable.yaml"
        r = validate_recipe_file(recipe)
        self.assertTrue(r.ok, f"errors: {r.errors}")


if __name__ == "__main__":
    unittest.main()
