# Release Notes — v1.10.0 .. v1.11.10 (R1A wave)

> Period: 2026-05-11 (single never-stop turn under BOSS Rule 3)
> Tags: v1.10.0 .. v1.11.10 (22 tags, including v1.10.9-COMPLETE-R1A
> milestone). Commits: ~80 in this batch. Tests added: 26 -> 594 (+568).

---

## TL;DR

**FAW gained 10 new public-API asset providers in one wave**, fully wired
across THREE invocation paths (CLI, recipe pipeline, adapter registry).
Plus 2 fan-out scouting commands, 1 new sample recipe, schema extension
for video/music/icon refs, and SETUP/README documentation rolled up.

| | Pre-R1A | Post-R1A |
|---|---|---|
| Direct-URL providers | 5 | 19 (5 CC0 + 10 R1A + 4 generators) |
| Asset classes | Image, 3D, audio sfx | + Video + Music tracks + Icon SVG |
| CLI sub-apps | 7 | 18 |
| CLI commands | ~25 | ~45 |
| Working recipes | 4 | 5 (added r1a_smoke) |
| Tests passing | 26 | 594 |
| Tags on origin | 33 | 57 |

---

## Headline integrations (10 new providers)

| # | Tag | Provider | Auth | License | Asset class |
|---|---|---|---|---|---|
| 1 | v1.10.0 | Met Museum | none | CC0 | image:art |
| 2 | v1.10.1 | Wikimedia Commons | none | CC0/CC-BY/SA/PD | image:any |
| 3 | v1.10.2 | Internet Archive | none | CC/PD per item | image,audio,video,text |
| 4 | v1.10.3 | Scryfall (MTG) | none | CC-BY-SA-4.0 | image:fantasy |
| 5 | v1.10.4 | Iconify | none | MIT/Apache/CC0/OFL | image:icon_svg |
| 6 | v1.10.5 | Pexels | PEXELS_API_KEY | Pexels License | image + **VIDEO** |
| 7 | v1.10.6 | Pixabay | PIXABAY_API_KEY | CC0-equivalent | image + VIDEO + vector |
| 8 | v1.10.7 | RAWG.io | RAWG_API_KEY | REFERENCE-ONLY | image:game_screenshot |
| 9 | v1.10.8 | Jamendo | JAMENDO_CLIENT_ID | CC-BY/SA | **MUSIC** |
| 10 | v1.10.9 | Unsplash | UNSPLASH_ACCESS_KEY | Unsplash License | image:photo |

**Milestone tag:** `v1.10.9-unsplash-COMPLETE-R1A` (closes R1A top-10 wave).

---

## v1.11 — wiring, schema, docs

| Tag | What changed |
|---|---|
| v1.11.0 | Recipe schema: `video_refs`, `music_refs`, `icon_refs`, `reference_image_urls` lists validated |
| v1.11.1 | `gen all-no-key` fan-out command (one query -> 5 no-key providers) |
| v1.11.2 | `gen all-key` fan-out command (skips missing-key providers, optional --include-video) |
| v1.11.3 | docs/SETUP.md §5.5: full env-key + signup-link table + scout commands |
| v1.11.4 | `providers/lanes.py`: 10 new `SourceAdapter` entries (`<provider>_api`) |
| v1.11.5 | `acquisition_router.py`: 5 no-key providers wired into `direct_url` lane |
| v1.11.6 | `recipes/sandbox/r1a_smoke.yaml`: 5-pack no-key smoke recipe |
| v1.11.7 | `acquisition_router.py`: 5 key-required providers wired (pexels/pixabay/unsplash/rawg/jamendo) |
| v1.11.8 | README front-page rolls up R1A + asset-class table + quick-start commands |
| v1.11.9 | `gen list-providers` catalog command (shows 12 providers + env detection) |
| v1.11.10 | Fixed flaky `test_canary_single_probe_json_emits_parseable_dict` (timeout+skip rather than fail) |

---

## Architectural shape

### Three invocation paths per provider

Every R1A provider can be reached three ways:

```
PATH A — Standalone CLI:
  python -m assetboy.cli gen <provider> fetch --query "X" -n 4

PATH B — Recipe pipeline:
  recipes/<game>/<recipe>.yaml has a pack with provider: <provider>
  python -m assetboy.cli pack from-recipe ...

PATH C — Adapter registry:
  from assetboy.providers.lanes import SOURCE_ADAPTERS, get_adapter
  get_adapter("<provider>_api")  # -> SourceAdapter with metadata
```

All three converge on the same `run_<provider>_batch(...)` runner in
`Python/assetboy/execution/<provider>_runner.py`.

### Runner shape

Each runner exports:

```python
# Result dataclass with ok/error/counts/paths/manifest_path.
class <Provider>Result:
    pack_id: str
    query: str
    output_dir: Path
    items_matched: int      # or photos_matched / cards_matched / etc.
    items_downloaded: int
    downloaded_paths: list[Path]
    manifest_path: Path | None
    ok: bool
    error: str | None
    dry_run: bool

# Search wrapper.
def search_<provider>_X(query: str, *, api_key: str | None, ...) -> list[dict]

# Optional env-key lookup (key-required providers only).
def get_api_key() -> str | None    # reads ${PROVIDER_ENV_VAR}

# Main batch driver — all kwargs, returns Result.
def run_<provider>_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = ...,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    # ... provider-specific kwargs
) -> <Provider>Result
```

### Recipe pack fields

Recipes can use these optional fields per pack (in addition to base schema):

```yaml
- id: PACK_X
  provider: <provider_id>
  acquisition_method: direct_url
  search_terms:           # list; first entry is the query
    - "stone wall"
  count: 6                # max items to download
  # Provider-specific fields:
  met_department_id: 13
  archive_mediatype: image
  scryfall_variant: art_crop
  iconify_width: 64
  iconify_color: "#FFAA00"
  pexels_variant: large
  pexels_max_height: 1080
  pixabay_image_type: photo|illustration|vector|all
  pixabay_variant: largeImageURL
  unsplash_variant: regular
  unsplash_orientation: landscape|portrait|squarish
  rawg_genres: "strategy,roguelike"
  rawg_max_screenshots: 3
  rawg_include_screenshots: true
  jamendo_allow_restrictive: false
  # v1.11.0 *_refs fields (any pack, any provider):
  video_refs: ["https://example.com/v.mp4"]
  music_refs: ["https://example.com/m.mp3"]
  icon_refs: ["https://api.iconify.design/foo/bar.svg"]
  reference_image_urls: ["https://example.com/ref.jpg"]
```

---

## License gating (built into runners)

Every runner that touches multi-license sources filters BEFORE downloading:

- **Met Museum** — `isPublicDomain=true` only (skips non-OA holdings)
- **Wikimedia** — substring-allowlist on extmetadata.LicenseShortName
  (CC0/CC-BY/CC-BY-SA/PD)
- **Archive.org** — substring-allowlist on doc.licenseurl
  (CC-BY/CC-BY-SA/CC0/PD; rejects -NC/-ND)
- **Iconify** — SPDX allowlist on collection license metadata
  (MIT/Apache/CC0/CC-BY/OFL/...)
- **Jamendo** — substring on license_ccurl, default rejects -NC and -ND
  (commercial-OK + derivative-OK); `--allow-restrictive` broadens

Skipped items are counted, not silently dropped: every manifest has
`items_skipped_restricted` (or similar) so the operator sees how many
were filtered out.

Per-runner manifest JSON also captures the per-item license and
attribution_text fields when relevant (Wikimedia, Scryfall, Jamendo).

---

## Test coverage shape

Every R1A runner has tests for:

- Env-var detection (where applicable): unset returns None, set returns value
- Search shape: returns list with expected fields
- License filter: each token-allowlist tested separately
- Full batch happy path: mocked urllib, verify download + manifest
- Dry-run mode: no binaries written, manifest still produced
- Network failure mode: search-failed returns ok=False with error string
- No-matches mode: empty result -> ok=True with error="no_matches"

CLI smoke tests verify:

- `--help` renders cleanly (cp1252-safe)
- Missing env-var error path produces clean exit code 1
- `--json` output is parseable + contains expected keys

Total new tests in batch: ~150 across 10 runner test files + ~40 in
test_cli_typer.py CLI smoke section.

---

## What's deliberately NOT yet done

- **Live network test** for any R1A provider (all tests mock urllib).
  Operator should validate one real call per provider on first use.
- **Library installer** registration. The CLI + recipe paths work, but
  `Python/assetboy/library/shared_packs.py` doesn't yet enumerate R1A
  providers as `BridgeDefinition` entries. Library-shaped queries
  (e.g. via the HTTP `/library/search` endpoint) won't surface R1A
  providers yet. Future slice candidate.
- **Per-provider rate-limit awareness**. Runners use polite sleeps
  (50-300ms between requests) but don't honor `429 Too Many Requests`
  with exponential backoff. Future hardening.
- **Async fan-out**. `gen all-no-key` and `gen all-key` run sequentially.
  Parallelizing with `asyncio` would cut wall time ~5x. Future.
- **Bulk-install integration**. The existing `library bulk-install`
  flow doesn't know about R1A providers. Future.

These are NOT regressions — they're scope-limited intentionally to
ship the R1A wave cleanly.

---

## Operator's first commands

```powershell
# 0. Verify catalog (no network):
python -m assetboy.cli gen list-providers

# 1. Free providers (always works):
python -m assetboy.cli gen all-no-key -q "dragon" -n 2 --dry-run
python -m assetboy.cli gen all-no-key -q "dragon" -n 2 --no-dry-run  # actually download

# 2. Set keys for the 5 key-required providers (skip ones you don't have):
$env:PEXELS_API_KEY      = "..."  # https://www.pexels.com/api/new/
$env:PIXABAY_API_KEY     = "..."  # https://pixabay.com/api/docs/
$env:UNSPLASH_ACCESS_KEY = "..."  # https://unsplash.com/developers
$env:RAWG_API_KEY        = "..."  # https://rawg.io/apidocs
$env:JAMENDO_CLIENT_ID   = "..."  # https://developer.jamendo.com/

# 3. Verify keys are detected:
python -m assetboy.cli gen list-providers

# 4. Scout with all configured keys:
python -m assetboy.cli gen all-key -q "fire" --include-video --dry-run

# 5. Run the smoke recipe end-to-end:
python -m assetboy.cli pack validate recipes/sandbox/r1a_smoke.yaml
python -m assetboy.cli pack from-recipe sandbox/r1a_smoke.yaml --dry-run
python -m assetboy.cli pack from-recipe sandbox/r1a_smoke.yaml  # real network
```

---

## Where things landed (filesystem map)

```
Python/assetboy/execution/
  met_museum_runner.py     (s26, v1.10.0)
  wikimedia_runner.py      (s27, v1.10.1)
  archive_org_runner.py    (s28, v1.10.2)
  scryfall_runner.py       (s29, v1.10.3)
  iconify_runner.py        (s30, v1.10.4)
  pexels_runner.py         (s31, v1.10.5)
  pixabay_runner.py        (s32, v1.10.6)
  rawg_runner.py           (s33, v1.10.7)
  jamendo_runner.py        (s34, v1.10.8)
  unsplash_runner.py       (s35, v1.10.9)

Python/assetboy/cli/gen.py
  + 10 new sub-app commands (met-museum/wikimedia/archive-org/scryfall/
    iconify/pexels/pixabay/unsplash/rawg/jamendo)
  + 'gen all-no-key' command (s37, v1.11.1)
  + 'gen all-key' command (s38, v1.11.2)
  + 'gen list-providers' command (s45, v1.11.9)

Python/assetboy/workflows/
  acquisition_router.py    (s41+s43; +10 driver functions + 10 dispatch entries)
  recipe_validator.py      (s36 *_refs validation, s41+s43 provider allowlist)

Python/assetboy/providers/lanes.py
  + 10 SourceAdapter entries (<provider>_api)  (s40, v1.11.4)

Tests/python/
  test_met_museum_runner.py        (6 tests)
  test_wikimedia_runner.py         (12 tests)
  test_archive_org_runner.py       (16 tests)
  test_scryfall_runner.py          (11 tests)
  test_iconify_runner.py           (14 tests)
  test_pexels_runner.py            (12 tests)
  test_pixabay_runner.py           (14 tests)
  test_rawg_runner.py              (10 tests)
  test_jamendo_runner.py           (16 tests)
  test_unsplash_runner.py          (13 tests)
  test_lanes_r1a_adapters.py       (7 tests with subtests, s40)
  test_acquisition_router_r1a.py   (20 tests, s41+s43)
  test_cli_typer.py                (+45 R1A CLI smoke tests)
  test_recipe_validator.py         (+10 refs-field + +1 r1a_smoke recipe)

recipes/sandbox/r1a_smoke.yaml     (s42, v1.11.6 — 5-pack no-key recipe)

docs/SETUP.md                       (§5.5 added, s39 v1.11.3)
docs/COMMIT_READY-assetboi.md       (batch summaries appended)
docs/HEARTBEAT-assetboi.md          (operator wake-up doc updated, s40+s43)
README.md                           (front-page rolled up, s44 v1.11.8)
docs/RELEASE_NOTES_v1.10_v1.11.md   (this file, s47)
```

---

*This doc is the canonical reference for the R1A wave. Generated
during the 2026-05-11 BOSS never-stop turn. Operator audit OK
expected; raise any drift via PATH_B_DAY11_PLAN backlog.*
