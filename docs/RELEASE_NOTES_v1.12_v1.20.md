# Release notes — v1.12 through v1.20 (post-R1A continuous loop)

> Generated 2026-05-12 during the continuous never-stop run.
> Companion to RELEASE_NOTES_v1.10_v1.11.md (R1A wave canonical reference).

This doc covers the 9 waves that followed R1A complete (v1.10.9):

| Wave | Tag | Headline delivery |
|---|---|---|
| v1.12 | `v1.12-WAVE-COMPLETE` | Async fan-out + 429-retry across all 10 R1A runners + observability (manifest-stats CLI + HTTP) + benchmarking |
| v1.13 | `v1.13-WAVE-COMPLETE` | Live-API smoke tests + iNaturalist (11th) + Open Library (12th) + scout-by-license fan-out + r1a-status --bars/--html + retry budget |
| v1.14 | `v1.14-WAVE-COMPLETE` | JSON contracts + install-r1a-pack (Library bridge) + canary R1A rotation + recipe --sort tier + /library/health |
| v1.15 | (no wave tag) | History snapshots (state/r1a_history) + recipe-mode install + FAW_POLITE_SLEEP_S + iconify list-sets |
| v1.16 | `v1.16-WAVE-COMPLETE` | Polite-sleep applied to all 12 runners + history enrichment + manifest-stats --history + attribution badges + --html --open |
| v1.17 | `v1.17-WAVE-COMPLETE` | all-key history + --reverse + scout-by-license --parallel + output_folder validation + 24 new JSON contract tests (766 milestone) |
| v1.18 | `v1.18-WAVE-COMPLETE` | install-r1a-pack actually copies (was enumerate-only) + manifest-stats --history --since + Open Library --author + RAWG --platforms + expected_min_assets |
| v1.19 | `v1.19-WAVE-COMPLETE` | pack from-recipe honors expected_min_assets + Unsplash --collection + Wikimedia --category walk + r1a-status --csv + 800-test milestone |
| v1.20 | (in progress) | Iconify --prefix + archive-org --collection + recipe min_required_passes |

---

## Key surfaces by category

### Public-API provider catalog (12 total)

- 6 no-key: Met Museum, Wikimedia Commons, Archive.org, Scryfall, Iconify, iNaturalist, Open Library
- 5 key-required: Pexels (photos+videos), Pixabay (photos+videos), Unsplash, RAWG, Jamendo
- 2 generators (gen list-providers catalog): ComfyUI, sd.cpp

Each provider has runner-level + CLI + 3-path integration (CLI command, recipe pipeline, SOURCE_ADAPTERS lookup) per the R1A pattern from v1.10.

### HTTP endpoints (17 total on :8790)

Notable additions since R1A:
- `POST /api/v1/providers/list-gen` (v1.11.s48)
- `POST /api/v1/manifest/stats` (v1.12.s73)
- `POST /api/v1/library/r1a-status` (v1.12.s76; gained `check_live` body in v1.13.s82)
- `POST /api/v1/library/scout-by-license` (v1.13.s96)
- `POST /api/v1/library/health` (v1.14.s106 — unified C# registry + Python r1a-status)

### CLI commands added post-R1A

```
gen all-no-key            fan-out across no-key providers (--parallel + --write-history)
gen all-key               fan-out across keyed providers (--parallel + --write-history)
gen bench-fanout          sequential vs parallel speedup demo
gen list-providers        catalog with env-set detection (--filter env_set/env_var)
gen scout-by-license      filter providers by license token + fan out (--parallel)
gen iconify list-sets     browse 150+ icon sets with SPDX license
library r1a-status        combined env + on-disk readiness (--bars, --check-live, --html, --csv)
library install-r1a-pack  manifest -> Library/ bridge (--recipe whole-recipe mode)
pack manifest-stats       aggregate disk manifests OR history snapshots (--source, --since, --history)
pack list-recipes         metadata filter + tier sort + reverse (--filter, --sort, --reverse)
```

### Recipe schema additions

```yaml
recipe:
  # ...
  genre / theme / style / tags: optional discovery metadata (string OR list[str])
  output_folder:               soft-validated (illegal chars / abs path warns)
  expected_min_assets:         int >= 0, pipeline emits OK/WARN post-run
  min_required_passes:         int >= 0, pipeline counts completed packs

packs:
  - # ...
    tier:                      int 0..3 (P0..P3 priority; auto_fix fills tier=2)
    video_refs / music_refs / icon_refs / reference_image_urls:
                                lists of URL-shaped strings (validated)
```

### Provider-specific CLI flags

| Provider | New flag | Wave |
|---|---|---|
| Unsplash | `--orientation`, `--collection` | v1.10 + v1.19 |
| Pixabay | `--image-type`, `--variant` | v1.10 |
| Pexels | `--variant`, `--max-height` (videos) | v1.10 |
| RAWG | `--genres`, `--platforms` | v1.10 + v1.18 |
| Iconify | `--width`, `--color`, `--prefix`, `--skip-license-check` | v1.10 + v1.20 |
| Archive.org | `--mediatype`, `--collection` | v1.10 + v1.20 |
| Wikimedia | `--category` (walks members) | v1.19 |
| Open Library | `--size`, `--author` | v1.13 + v1.18 |
| Jamendo | `--allow-restrictive` | v1.10 |

### Resilience + observability

- `with_429_retry` helper wraps every runner's HTTP call (v1.12.s66-s69)
- `FAW_HTTP_RETRY_BUDGET` env caps process-wide retry sleeps (v1.13.s99)
- `FAW_POLITE_SLEEP_S` env overrides per-runner polite_sleep_s (v1.15.s110, applied v1.16.s114)
- ThreadPoolExecutor parallel mode on all fan-out commands (v1.12.s64+v1.12.s65+v1.17.s122)
- 30+ JSON contract tests verify Python emit / C# parse compatibility (v1.14.s102 + v1.17.s124 + v1.19.s136)

---

## Cumulative metrics across this loop

| Snapshot | Commits since baseline | Tags | Tests |
|---|---|---|---|
| v1.10.9 (R1A complete) | 89 | 39 | 545 |
| v1.11.11 | 117 | 58 | 594 |
| v1.12.12 | 132 | 78 | 637 |
| v1.13.16 | 153 | 96 | 692 |
| v1.14.4 | 159 | 102 | 713 |
| v1.15.3 | 165 | 108 | 725 |
| v1.16.4 | 175 | 117 | 731 |
| v1.17.3 | 184 | 126 | 742 |
| v1.18.4 | 196 | 138 | 781 |
| v1.19.3 | 204 | 145 | 790 |
| **v1.20.2** | **211** | **154** | **812** |

Approximately **122 commits, 115 tags, +267 tests** added since R1A milestone.

---

## What's stable + what's intentionally minimal

**Stable + tested:**
- All 12 provider runners (mocked + 13 opt-in live smoke tests)
- 3-path invocation (CLI / recipe pipeline / SOURCE_ADAPTERS) for every R1A provider
- HTTP contract for 17 endpoints (subprocess pattern; C# clients see consistent JSON)
- Recipe schema validator (75+ test cases)

**Intentionally minimal:**
- No multi-page pagination yet (each provider returns first-page only)
- No bulk recipe sweep command (`pack from-all-recipes`)
- No video provider for non-key path (only Pexels + Pixabay videos require keys)
- No retry-budget telemetry export (counter is in-process only)
- v1.15 lacks an explicit wave-end milestone tag (skipped; covered by v1.16)

---

## Reading order for next session

1. `HEARTBEAT-assetboi.md` (top-of-loop state — single source of truth)
2. This doc (`RELEASE_NOTES_v1.12_v1.20.md`)
3. `RELEASE_NOTES_v1.10_v1.11.md` (R1A wave canonical reference)
4. `RECIPE_SCHEMA.md` (recipe authoring guide)
5. `SETUP.md` §5.5 (R1A keys + scout commands)
6. `PATH_B_DAY11_PLAN.md` v1.20+ section (backlog for s142+)

Total: ~30 min focused reading covers v1.10 → v1.20 (10 waves, ~210 commits).
