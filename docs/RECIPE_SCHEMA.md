# Recipe schema reference

> Authoritative schema for `recipes/<game>/<recipe>.yaml` documents.
> Maintained alongside `Python/assetboy/workflows/recipe_validator.py`.
> Last update: 2026-05-11 (v1.11.15).

A recipe is a YAML document with two top-level keys:

```yaml
recipe:   # metadata + discovery fields
  ...
packs:    # list of asset packs (this recipe's contents)
  - id: ...
    ...
```

---

## Top-level shape

| Key | Type | Required | Notes |
|---|---|---|---|
| `recipe` | mapping | yes | metadata block (see below) |
| `packs` | list[mapping] | yes | one entry per asset pack |
| `gates` | mapping | no | required/optional pack lists + block_on_missing |
| `vfx`, `scene_setup`, `flax_import`, ... | mapping | no | free-form annotations (not validated) |

---

## `recipe` block

```yaml
recipe:
  id: my_unique_recipe_id            # REQUIRED, unique across all recipes
  schema_version: 2026-05-10.recipe.v1  # informational; not validated
  game: my_game                       # REQUIRED, used for output folder
  description: |                      # optional, free text
    Multi-line description of the recipe.

  # Optional discovery metadata (v1.11.14+). Each field is string OR list[str].
  genre: rpg                          # OR list: ['rpg', 'roguelite']
  theme:                              # list of theme tags
    - medieval
    - fantasy
  style:                              # art-direction tags
    - lowpoly
  tags:                               # free-form tags
    - first-playable
    - demo
```

Discovery queries (v1.11.15+):

```powershell
python -m assetboy.cli pack list-recipes --filter genre:rpg
python -m assetboy.cli pack list-recipes --filter theme:fantasy --filter style:lowpoly
python -m assetboy.cli pack list-recipes --filter tags:demo
```

---

## `packs` list

Each pack must be a mapping. Required keys:

| Key | Type | Notes |
|---|---|---|
| `id` | str | unique within the recipe |
| `provider` | str | must match a registered provider id |
| `acquisition_method` | str | one of: `direct_url`, `manual_browser`, `generator` |

Optional common fields:

| Key | Type | Notes |
|---|---|---|
| `asset_kind` | str | defaults to `prop`; recommended for clarity |
| `license` | mapping | `{kind, commercial_ok, attribution_required, ...}` |
| `search_terms` | list[str] | first entry is the runner search query |
| `assets` | list[mapping or str] | per-asset entries |
| `count` | int | how many items to fetch (R1A providers) |
| `cleanup` | mapping | `{mode: skip|stage|clean}` |
| `gate` | mapping | `{required: bool, reason: str}` |

---

## Acquisition lanes

### `acquisition_method: direct_url`

Provider must be one of (v1.11.15):

```
polyhaven, kenney, ambientcg, freesound, quaternius
met_museum (aliases: met-museum)
wikimedia (aliases: wikimedia_commons)
archive_org (aliases: archive-org, archiveorg)
scryfall
iconify
pexels (aliases: pexels_photos, pexels_videos)
pixabay (aliases: pixabay_photos, pixabay_videos)
unsplash
rawg
jamendo
```

Pack must have either `assets:` or `search_terms:`.

#### Provider-specific optional fields

| Provider | Field | Purpose |
|---|---|---|
| met_museum | `met_department_id` | int filter; e.g. 13 = Greek/Roman |
| archive_org | `archive_mediatype` | `image` / `audio` / `movies` / `texts` |
| scryfall | `scryfall_variant` | `art_crop` / `png` / `large` / etc |
| iconify | `iconify_width` | px width (default 64) |
| iconify | `iconify_color` | hex like `#FFAA00` |
| pexels | `pexels_variant` | `original` / `large` / `medium` / etc |
| pexels | `pexels_max_height` | for video provider (default 1080) |
| pixabay | `pixabay_image_type` | `photo` / `illustration` / `vector` / `all` |
| pixabay | `pixabay_variant` | `largeImageURL` / `webformatURL` / etc |
| unsplash | `unsplash_variant` | `raw` / `full` / `regular` / `small` / `thumb` |
| unsplash | `unsplash_orientation` | `landscape` / `portrait` / `squarish` |
| rawg | `rawg_genres` | comma-separated genre slugs |
| rawg | `rawg_max_screenshots` | int cap per game (default 3) |
| rawg | `rawg_include_screenshots` | bool (default true) |
| jamendo | `jamendo_allow_restrictive` | bool; default false rejects CC-NC/ND |
| polyhaven | `polyhaven_category` | overrides asset_kind inference |

### `acquisition_method: manual_browser`

Provider must be one of:

```
fab, mixamo, unity (aliases: unity_asset_store)
epic (aliases: epic_games, epic_vault)
```

Should have `source_url:` OR `assets:`.

### `acquisition_method: generator`

Provider must be one of:

```
comfyui
local_image (aliases: sd, sd.cpp)
stable_audio_open_small (aliases: stable_audio)
```

Pack must have `prompts: [...]`.

---

## Reference URL list fields (v1.11.0+)

Any pack can optionally carry reference URL lists:

```yaml
- id: PACK_X
  ...
  video_refs:
    - https://example.com/v.mp4
  music_refs:
    - https://example.com/m.mp3
  icon_refs:
    - https://api.iconify.design/foo/bar.svg
  reference_image_urls:
    - https://example.com/ref.jpg
```

Each must be a list of non-empty strings. Entries that don't look
URL-shaped (no http(s)://, no local-path marker like `./`, `C:/`)
trigger a WARNING but not an ERROR.

---

## `gates` block (optional)

```yaml
gates:
  required_pack_ids:
    - PACK_FOO
    - PACK_BAR
  optional_pack_ids:
    - PACK_BAZ
  block_on_missing_required: true
```

Validator catches `required_pack_ids` that reference unknown pack ids.

---

## Validation commands

```powershell
# Single recipe:
python -m assetboy.cli pack validate recipes/<game>/<recipe>.yaml

# Auto-fix common warnings (writes to a new file):
python -m assetboy.cli pack validate recipes/<game>/<recipe>.yaml \
    --fix --out recipes/<game>/<recipe>_fixed.yaml

# All shipped recipes at once:
python -m assetboy.cli pack validate-all
python -m assetboy.cli pack validate-all --json     # for CI
```

---

## Shipped recipes (5)

```
recipes/primitive_tech/first_playable.yaml   genre=survival, theme=prehistoric
recipes/roman/first_playable.yaml            genre=action_combat, theme=ancient_rome
recipes/sandbox/one_pack_smoke.yaml          genre=smoke_test, tags=cc0-only
recipes/sandbox/generator_smoke.yaml         genre=smoke_test, tags=generator-lane
recipes/sandbox/r1a_smoke.yaml               genre=reference_collection, tags=r1a-wave
```

Quick filter:

```powershell
python -m assetboy.cli pack list-recipes --filter tags:smoke-test
# -> 3 sandbox recipes

python -m assetboy.cli pack list-recipes --filter theme:fantasy
# -> r1a_smoke (theme list includes 'fantasy')
```

---

*See `Python/assetboy/workflows/recipe_validator.py` for the
authoritative validator source. See
`Tests/python/test_recipe_validator.py` for the contract-test
catalog (54 tests as of v1.11.15).*
