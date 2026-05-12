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


class MinRequiredPassesTests(unittest.TestCase):
    """v1.20.s141: optional non-negative int recipe.min_required_passes."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc
        self.validate = validate_recipe_doc

    def _doc(self, **recipe_extra):
        return {
            "recipe": {"id": "r", "game": "test", "tags": ["t"], **recipe_extra},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"}, "asset_kind": "x",
                "assets": [{"asset_id": "x"}], "tier": 2,
            }],
        }

    def test_zero_accepted(self) -> None:
        r = self.validate(self._doc(min_required_passes=0))
        self.assertTrue(r.ok)

    def test_positive_accepted(self) -> None:
        r = self.validate(self._doc(min_required_passes=3))
        self.assertTrue(r.ok)

    def test_negative_rejected(self) -> None:
        r = self.validate(self._doc(min_required_passes=-1))
        self.assertFalse(r.ok)
        self.assertTrue(any("non-negative" in e for e in r.errors))

    def test_string_rejected(self) -> None:
        r = self.validate(self._doc(min_required_passes="3"))
        self.assertFalse(r.ok)

    def test_bool_rejected(self) -> None:
        r = self.validate(self._doc(min_required_passes=True))
        self.assertFalse(r.ok)

    def test_absent_no_complaint(self) -> None:
        r = self.validate(self._doc())
        self.assertTrue(r.ok)


class ExpectedMinAssetsTests(unittest.TestCase):
    """v1.18.s130: optional non-negative int recipe.expected_min_assets."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc
        self.validate = validate_recipe_doc

    def _doc(self, **recipe_extra):
        return {
            "recipe": {"id": "r", "game": "test", "tags": ["t"], **recipe_extra},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"}, "asset_kind": "x",
                "assets": [{"asset_id": "x"}], "tier": 2,
            }],
        }

    def test_zero_accepted(self) -> None:
        r = self.validate(self._doc(expected_min_assets=0))
        self.assertTrue(r.ok)

    def test_positive_accepted(self) -> None:
        r = self.validate(self._doc(expected_min_assets=42))
        self.assertTrue(r.ok)

    def test_negative_rejected(self) -> None:
        r = self.validate(self._doc(expected_min_assets=-1))
        self.assertFalse(r.ok)
        self.assertTrue(any("non-negative" in e for e in r.errors))

    def test_string_rejected(self) -> None:
        r = self.validate(self._doc(expected_min_assets="10"))
        self.assertFalse(r.ok)
        self.assertTrue(any("integer" in e for e in r.errors))

    def test_bool_rejected(self) -> None:
        r = self.validate(self._doc(expected_min_assets=True))
        self.assertFalse(r.ok)

    def test_absent_no_complaint(self) -> None:
        r = self.validate(self._doc())
        self.assertTrue(r.ok)

    def test_none_no_complaint(self) -> None:
        r = self.validate(self._doc(expected_min_assets=None))
        self.assertTrue(r.ok)


class OutputFolderValidationTests(unittest.TestCase):
    """v1.17.s123: recipe.output_folder soft validation."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc
        self.validate = validate_recipe_doc

    def _doc(self, **recipe_extra):
        return {
            "recipe": {"id": "r", "game": "test", "tags": ["t"], **recipe_extra},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"},
                "asset_kind": "texture",
                "assets": [{"asset_id": "x"}],
                "tier": 2,
            }],
        }

    def test_relative_output_folder_clean(self) -> None:
        r = self.validate(self._doc(output_folder="Content/MyGame/Recipe1"))
        self.assertTrue(r.ok, msg=str(r.errors))
        for w in r.warnings:
            self.assertNotIn("output_folder", w)

    def test_non_string_output_folder_is_error(self) -> None:
        r = self.validate(self._doc(output_folder=42))
        self.assertFalse(r.ok)
        self.assertTrue(any("output_folder" in e and "must be a string" in e for e in r.errors))

    def test_empty_output_folder_is_warning(self) -> None:
        r = self.validate(self._doc(output_folder="   "))
        self.assertTrue(r.ok)
        self.assertTrue(any("output_folder" in w and "empty" in w for w in r.warnings))

    def test_absolute_path_unix_is_warning(self) -> None:
        r = self.validate(self._doc(output_folder="/var/assets/recipe1"))
        self.assertTrue(r.ok)
        self.assertTrue(any("absolute" in w for w in r.warnings))

    def test_absolute_path_windows_drive_is_warning(self) -> None:
        r = self.validate(self._doc(output_folder="C:/proj/assets"))
        self.assertTrue(r.ok)
        self.assertTrue(any("absolute" in w for w in r.warnings))

    def test_backslash_is_warning(self) -> None:
        r = self.validate(self._doc(output_folder="Content\\MyGame\\Recipe"))
        self.assertTrue(r.ok)
        self.assertTrue(any("backslash" in w.lower() for w in r.warnings))

    def test_illegal_chars_is_error(self) -> None:
        r = self.validate(self._doc(output_folder="Content/<bad>"))
        self.assertFalse(r.ok)
        self.assertTrue(any("illegal" in e for e in r.errors))

    def test_output_folder_absent_no_complaint(self) -> None:
        doc = {"recipe": {"id": "r", "game": "t", "tags": ["t"]},
               "packs": [{"id": "P", "provider": "polyhaven",
                          "acquisition_method": "direct_url",
                          "license": {"kind": "cc0"}, "asset_kind": "x",
                          "assets": [{"asset_id": "x"}], "tier": 2}]}
        r = self.validate(doc)
        self.assertTrue(r.ok)
        for w in r.warnings:
            self.assertNotIn("output_folder", w)


class PackTierFieldTests(unittest.TestCase):
    """v1.13.s93: pack.tier int in {0,1,2,3}."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc, auto_fix_warnings
        self.validate = validate_recipe_doc
        self.auto_fix = auto_fix_warnings

    def _pack(self, **extra):
        return {
            "id": "P", "provider": "polyhaven",
            "acquisition_method": "direct_url",
            "license": {"kind": "cc0"},
            "asset_kind": "texture",
            "assets": [{"asset_id": "x"}],
            **extra,
        }

    def _doc(self, **pack_extra):
        return {
            "recipe": {"id": "r", "game": "test", "tags": ["t"]},
            "packs": [self._pack(**pack_extra)],
        }

    def test_tier_0_accepted(self) -> None:
        r = self.validate(self._doc(tier=0))
        self.assertTrue(r.ok, msg=str(r.errors))

    def test_tier_3_accepted(self) -> None:
        r = self.validate(self._doc(tier=3))
        self.assertTrue(r.ok)

    def test_tier_4_rejected(self) -> None:
        r = self.validate(self._doc(tier=4))
        self.assertFalse(r.ok)
        self.assertTrue(any("tier" in e for e in r.errors))

    def test_tier_negative_rejected(self) -> None:
        r = self.validate(self._doc(tier=-1))
        self.assertFalse(r.ok)

    def test_tier_string_rejected(self) -> None:
        r = self.validate(self._doc(tier="0"))
        self.assertFalse(r.ok)
        self.assertTrue(any("integer" in e for e in r.errors))

    def test_tier_bool_rejected(self) -> None:
        """bool is not a valid tier (even though Python treats True as 1)."""
        r = self.validate(self._doc(tier=True))
        self.assertFalse(r.ok)

    def test_tier_absent_no_complaint(self) -> None:
        r = self.validate(self._doc())
        self.assertTrue(r.ok)

    def test_tier_none_no_complaint(self) -> None:
        r = self.validate(self._doc(tier=None))
        self.assertTrue(r.ok)

    def test_auto_fix_fills_default_tier(self) -> None:
        """auto_fix on a pack without tier should fill tier=2."""
        doc = {
            "recipe": {"id": "r", "game": "test", "tags": ["t"]},
            "packs": [self._pack()],  # no tier
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["packs"][0]["tier"], 2)
        self.assertTrue(any("tier=2" in f for f in fixes))

    def test_auto_fix_preserves_existing_tier(self) -> None:
        doc = {
            "recipe": {"id": "r", "game": "test", "tags": ["t"]},
            "packs": [self._pack(tier=0)],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["packs"][0]["tier"], 0)  # preserved
        self.assertFalse(any("tier" in f for f in fixes))


class RecipeMetadataFieldTests(unittest.TestCase):
    """v1.11.s51: recipe.genre/theme/style/tags optional metadata fields."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc
        self.validate = validate_recipe_doc

    def _doc(self, **recipe_extra: object) -> dict:
        return {
            "recipe": {"id": "r", "game": "test", **recipe_extra},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"},
                "asset_kind": "texture",
                "assets": [{"asset_id": "x"}],
            }],
        }

    def test_string_genre_accepted(self) -> None:
        r = self.validate(self._doc(genre="rpg"))
        self.assertTrue(r.ok, msg=str(r.errors))

    def test_list_genre_accepted(self) -> None:
        r = self.validate(self._doc(genre=["rpg", "roguelite"]))
        self.assertTrue(r.ok, msg=str(r.errors))

    def test_string_theme_accepted(self) -> None:
        r = self.validate(self._doc(theme="medieval fantasy"))
        self.assertTrue(r.ok)

    def test_style_list_accepted(self) -> None:
        r = self.validate(self._doc(style=["lowpoly", "stylized"]))
        self.assertTrue(r.ok)

    def test_tags_accepted(self) -> None:
        r = self.validate(self._doc(tags=["demo", "first-playable", "v1"]))
        self.assertTrue(r.ok)

    def test_int_genre_is_error(self) -> None:
        r = self.validate(self._doc(genre=42))
        self.assertFalse(r.ok)
        self.assertTrue(any("genre" in e for e in r.errors))

    def test_dict_theme_is_error(self) -> None:
        r = self.validate(self._doc(theme={"primary": "rpg"}))
        self.assertFalse(r.ok)

    def test_mixed_list_entry_is_error(self) -> None:
        r = self.validate(self._doc(tags=["ok", 42, None]))
        self.assertFalse(r.ok)
        # Two non-string entries -> 2 errors.
        tag_errs = [e for e in r.errors if "tags" in e]
        self.assertEqual(len(tag_errs), 2)

    def test_empty_string_metadata_is_warning(self) -> None:
        r = self.validate(self._doc(genre=""))
        self.assertTrue(r.ok)
        self.assertTrue(any("genre" in w and "empty" in w for w in r.warnings))

    def test_empty_string_in_list_is_error(self) -> None:
        r = self.validate(self._doc(tags=["a", "  ", "c"]))
        self.assertFalse(r.ok)
        self.assertTrue(any("tags[1]" in e for e in r.errors))

    def test_metadata_fields_absent_no_complaint(self) -> None:
        r = self.validate(self._doc())  # no metadata fields
        self.assertTrue(r.ok)
        for w in r.warnings:
            self.assertNotIn("genre", w)
            self.assertNotIn("theme", w)
            self.assertNotIn("style", w)
            self.assertNotIn("tags", w)


class RefsFieldTests(unittest.TestCase):
    """v1.11.s36: video_refs / music_refs / icon_refs / reference_image_urls."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc
        self.validate = validate_recipe_doc

    def _base_pack(self, **extra: object) -> dict:
        return {
            "id": "PACK_X", "provider": "polyhaven",
            "acquisition_method": "direct_url",
            "asset_kind": "texture",
            "license": {"kind": "cc0"},
            "assets": [{"asset_id": "x"}],
            **extra,
        }

    def _doc_with(self, pack: dict) -> dict:
        return {"recipe": {"id": "r", "game": "test"}, "packs": [pack]}

    def test_video_refs_accepts_list_of_urls(self) -> None:
        pack = self._base_pack(video_refs=[
            "https://example.com/v1.mp4",
            "https://example.com/v2.mp4",
        ])
        r = self.validate(self._doc_with(pack))
        self.assertTrue(r.ok, msg=str(r.errors))

    def test_music_refs_accepts_local_paths(self) -> None:
        pack = self._base_pack(music_refs=[
            "./music/intro.mp3",
            "C:/sounds/track.flac",
        ])
        r = self.validate(self._doc_with(pack))
        self.assertTrue(r.ok, msg=str(r.errors))

    def test_icon_refs_warns_on_bare_filename(self) -> None:
        """Bare filename (no URL/path marker) -> warning, not error."""
        pack = self._base_pack(icon_refs=["bare_icon.svg"])
        r = self.validate(self._doc_with(pack))
        self.assertTrue(r.ok)
        self.assertTrue(any("URL-shaped" in w for w in r.warnings))

    def test_video_refs_non_list_is_error(self) -> None:
        pack = self._base_pack(video_refs="https://just-a-string.mp4")  # not a list
        r = self.validate(self._doc_with(pack))
        self.assertFalse(r.ok)
        self.assertTrue(any("video_refs" in e and "must be a list" in e for e in r.errors))

    def test_video_refs_non_string_entry_is_error(self) -> None:
        pack = self._base_pack(video_refs=["https://ok.mp4", 42, None])
        r = self.validate(self._doc_with(pack))
        self.assertFalse(r.ok)
        # Should error on idx 1 (int) and idx 2 (None).
        int_errs = [e for e in r.errors if "video_refs[1]" in e]
        none_errs = [e for e in r.errors if "video_refs[2]" in e]
        self.assertTrue(int_errs)
        self.assertTrue(none_errs)

    def test_empty_string_in_refs_is_error(self) -> None:
        pack = self._base_pack(music_refs=["https://ok.mp3", "", "   "])
        r = self.validate(self._doc_with(pack))
        self.assertFalse(r.ok)
        self.assertTrue(any("empty string" in e for e in r.errors))

    def test_refs_field_absent_no_complaint(self) -> None:
        """If a *_refs field is simply omitted, no warning or error fires."""
        pack = self._base_pack()  # no refs fields
        r = self.validate(self._doc_with(pack))
        self.assertTrue(r.ok)
        # Verify no spurious refs warnings.
        for w in r.warnings:
            self.assertNotIn("video_refs", w)
            self.assertNotIn("music_refs", w)
            self.assertNotIn("icon_refs", w)

    def test_refs_field_null_no_complaint(self) -> None:
        """Explicit null/None refs field treated as 'absent'."""
        pack = self._base_pack(video_refs=None, music_refs=None)
        r = self.validate(self._doc_with(pack))
        self.assertTrue(r.ok)

    def test_reference_image_urls_alias_also_validated(self) -> None:
        """reference_image_urls (the pre-v1.11 field) gets the same treatment."""
        pack = self._base_pack(reference_image_urls=["https://x.com/img.jpg"])
        r = self.validate(self._doc_with(pack))
        self.assertTrue(r.ok)

    def test_reference_image_urls_bad_type_is_error(self) -> None:
        pack = self._base_pack(reference_image_urls={"not": "a list"})
        r = self.validate(self._doc_with(pack))
        self.assertFalse(r.ok)


class AutoFixWarningsTests(unittest.TestCase):
    """v1.9.s24: auto_fix_warnings(doc) -> (fixed_doc, fixes_list)."""

    def setUp(self) -> None:
        from assetboy.workflows.recipe_validator import auto_fix_warnings
        self.auto_fix = auto_fix_warnings

    def test_manual_browser_missing_source_url_gets_default(self) -> None:
        """Fab pack with no source_url -> default https://www.fab.com/"""
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{
                "id": "PACK_FAB",
                "provider": "fab",
                "acquisition_method": "manual_browser",
                "asset_kind": "model",
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertIn("https://www.fab.com/", fixed["packs"][0].get("source_url", ""))
        self.assertTrue(any("source_url" in f for f in fixes))

    def test_missing_license_block_filled_per_provider(self) -> None:
        """polyhaven without license -> cc0 default."""
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{
                "id": "PACK_PH",
                "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "asset_kind": "texture",
                "assets": [{"asset_id": "x"}],
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["packs"][0]["license"]["kind"], "cc0")
        self.assertTrue(fixed["packs"][0]["license"]["commercial_ok"])
        self.assertTrue(any("license" in f for f in fixes))

    def test_missing_asset_kind_gets_default_prop(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{
                "id": "PACK_NO_KIND",
                "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"},
                "assets": [{"asset_id": "x"}],
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["packs"][0]["asset_kind"], "prop")

    def test_already_valid_pack_unchanged_minus_minor(self) -> None:
        """Pack with all fields including tier (v1.13.s93) -> no fix; recipe tags set -> no fill."""
        doc = {
            "recipe": {"id": "x", "game": "test", "tags": ["preset"]},  # tags set -> no auto-fill
            "packs": [{
                "id": "PACK_OK",
                "provider": "fab",
                "acquisition_method": "manual_browser",
                "asset_kind": "model",
                "license": {"kind": "fab_standard"},
                "source_url": "https://www.fab.com/listings/abc",
                "tier": 1,  # v1.13.s93: set tier to prevent auto-fill
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        # Source_url preserved exactly
        self.assertEqual(fixed["packs"][0]["source_url"], "https://www.fab.com/listings/abc")
        self.assertEqual(fixed["packs"][0]["license"]["kind"], "fab_standard")
        self.assertEqual(fixed["packs"][0]["tier"], 1)
        self.assertEqual(fixed["recipe"]["tags"], ["preset"])
        self.assertEqual(fixes, [])

    def test_recipe_missing_tags_gets_auto_tagged(self) -> None:
        """v1.13.s81: recipe without tags -> auto-fill ['auto-tagged']."""
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"},
                "asset_kind": "texture",
                "assets": [{"asset_id": "x"}],
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["recipe"]["tags"], ["auto-tagged"])
        self.assertTrue(any("auto-tagged" in f for f in fixes))

    def test_recipe_existing_tags_preserved(self) -> None:
        """Operator-set tags should NOT be overwritten."""
        doc = {
            "recipe": {"id": "x", "game": "test", "tags": ["custom"]},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"},
                "asset_kind": "texture",
                "assets": [{"asset_id": "x"}],
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["recipe"]["tags"], ["custom"])
        self.assertFalse(any("auto-tagged" in f for f in fixes))

    def test_recipe_empty_tags_list_gets_auto_filled(self) -> None:
        """Operator set tags=[] explicitly -> still fill with default."""
        doc = {
            "recipe": {"id": "x", "game": "test", "tags": []},
            "packs": [{
                "id": "P", "provider": "polyhaven",
                "acquisition_method": "direct_url",
                "license": {"kind": "cc0"},
                "asset_kind": "texture",
                "assets": [{"asset_id": "x"}],
            }],
        }
        fixed, fixes = self.auto_fix(doc)
        self.assertEqual(fixed["recipe"]["tags"], ["auto-tagged"])

    def test_non_dict_doc_returns_unchanged(self) -> None:
        fixed, fixes = self.auto_fix("not a dict")  # type: ignore[arg-type]
        self.assertEqual(fixed, "not a dict")
        self.assertEqual(fixes, [])


class RealRecipeIntegrationTests(unittest.TestCase):
    """Sanity-check that all shipped recipes pass validation."""

    def test_sandbox_one_pack_smoke_passes(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_file
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        recipe = repo_root / "recipes" / "sandbox" / "one_pack_smoke.yaml"
        r = validate_recipe_file(recipe)
        self.assertTrue(r.ok, f"errors: {r.errors}")

    def test_sandbox_r1a_smoke_passes(self) -> None:
        """v1.11.s42: 5-pack R1A no-key smoke recipe must validate clean."""
        from assetboy.workflows.recipe_validator import validate_recipe_file
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        recipe = repo_root / "recipes" / "sandbox" / "r1a_smoke.yaml"
        r = validate_recipe_file(recipe)
        self.assertTrue(r.ok, f"errors: {r.errors}")
        self.assertEqual(r.pack_count, 5)
        # All 5 R1A no-key providers should appear, and license blocks
        # should suppress the no-license warning for ALL packs.
        license_warnings = [w for w in r.warnings if "license" in w.lower()]
        self.assertEqual(license_warnings, [], msg=f"unexpected license warnings: {license_warnings}")

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
