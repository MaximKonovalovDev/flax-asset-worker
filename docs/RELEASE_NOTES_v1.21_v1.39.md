# Release notes — v1.21 through v1.39 (continuous never-stop wave block)

> Generated 2026-05-13 during the continuous never-stop run.
> Companion to RELEASE_NOTES_v1.12_v1.20.md (waves 9 in a row post-R1A)
> and RELEASE_NOTES_v1.10_v1.11.md (R1A canonical reference).

This doc covers the **19 waves** shipped after `v1.20-WAVE-COMPLETE`
landed. Cumulative state at v1.39.1 close:

- **268 commits** since baseline `0b1ad7d` (origin verified)
- **251 tags** pushed (75 reference points: 56 slice tags + 19 wave tags)
- **919 effective tests** passing (1 known live-net flake)
- **12 R1A providers**, **18 HTTP endpoints**, **18 Typer sub-apps**
- **0 RULE violations** across all 74 atomic slices in the run

---

## Wave-by-wave headline matrix

| Wave | Tag | Slices | Headline delivery |
|---|---|---|---|
| v1.21 | `v1.21-WAVE-COMPLETE` | s144–s148 | per-pack `pipeline_log` field, gen all-no-key `--provider` filter, Jamendo `--instrument`, pack from-recipe `--provider-only`, rerun-failed honors recipe checks |
| v1.22 | `v1.22-WAVE-COMPLETE` | s149–s155 | list-recipes `--sort name`, install-r1a-pack dedup by file_path, Scryfall `--set`, gen all-key `--provider` filter |
| v1.23 | `v1.23-WAVE-COMPLETE` | s158–s160 | gen met-museum `departments` discovery, manifest-stats `--top N`, recipe `created_utc`/`updated_utc` metadata |
| v1.24 | `v1.24-WAVE-COMPLETE` | s162–s167 | gen `history-tail` + HTTP endpoint, Scryfall `--type`, Pixabay/Pexels `--orientation`, Pixabay videos `--video-type` |
| v1.25 | `v1.25-WAVE-COMPLETE` | s168–s172 | rerun-failed `--max-attempts`, manifest-stats `--min-bytes`, list-providers `--filter kind`, recipe `author`/`contact` |
| v1.26 | `v1.26-WAVE-COMPLETE` | s173–s176 | Wikimedia `--license` family, r1a-status `--provider`, response_ms timing, r1a-status `--sort` |
| v1.27 | `v1.27-WAVE-COMPLETE` | s178–s180 | from-recipe `--max-tier`, r1a-status `last_manifest_utc` field, sort by freshness |
| v1.28 | `v1.28-WAVE-COMPLETE` | s181–s184 | all-no-key/all-key `--bail-on-error`, Pexels/Pixabay videos `--min-duration` |
| v1.29 | `v1.29-WAVE-COMPLETE` | s185–s187 | list-recipes `--filter author/contact`, manifest-stats `--csv`, HEARTBEAT refresh |
| v1.30 | `v1.30-WAVE-COMPLETE` | s189–s191 | recipe `platform` metadata, list-recipes `--filter platform` + `--sort platform` |
| v1.31 | `v1.31-WAVE-COMPLETE` | s193–s194 | r1a-status `--kind` substring + `--env-set-only` |
| v1.32 | `v1.32-WAVE-COMPLETE` | s195–s196 | list-recipes `--sort updated_utc/created_utc`, scout-by-license `--max-providers` |
| v1.33 | `v1.33-WAVE-COMPLETE` | s198–s199 | manifest-stats `--since-days`, list-recipes `--filter has-FIELD` |
| v1.34 | `v1.34-WAVE-COMPLETE` | s200–s202 | `--compact` JSON rolled out across list-recipes, list-providers, r1a-status (SLICE 200 MILESTONE) |
| v1.35 | `v1.35-WAVE-COMPLETE` | s203–s204 | `--compact` extended to all-no-key + all-key |
| v1.36 | `v1.36-WAVE-COMPLETE` | s205–s206 | `--compact` extended to scout-by-license + manifest-stats |
| v1.37 | `v1.37-WAVE-COMPLETE` | s207–s208 | history-tail `--compact` (8th compact command), HEARTBEAT refresh |
| v1.38 | `v1.38-WAVE-COMPLETE` | s210–s212 | recipe `cost_minutes` metadata, list-recipes `--sort cost_minutes`, from-recipe `--cost-budget` guard rail |
| v1.39 | (in progress) | s213+ | from-recipe `--provider-skip` (inverse of `--provider-only`) |

---

## Surface additions by category

### Recipe schema (cumulative, post-R1A)

```yaml
recipe:
  id: ...
  game: ...
  # v1.11+ discovery metadata
  genre: <string>
  theme: <string|list>
  style: <string>
  tags: [<string>...]
  # v1.13+ priority
  tier: 0..3                    # P0=critical .. P3=optional
  # v1.17+ portability
  output_folder: <relative-path>
  # v1.18+ acceptance criteria
  expected_min_assets: <int>
  # v1.20+ pass quorum
  min_required_passes: <int>
  # v1.23+ provenance
  created_utc: <ISO 8601 string>
  updated_utc: <ISO 8601 string>
  # v1.25+ ownership
  author: <string>
  contact: <string>
  # v1.30+ target engine
  platform: flax|unity|unreal|godot|web|any|<custom>
  # v1.38+ budget hint
  cost_minutes: <non-negative int>

packs:
  - id: ...
    provider: ...
    # v1.21+ structured ledger
    pipeline_log: [{stage, status, ts_utc}...]   # populated at runtime
    # v1.13+ priority (pack-level too)
    tier: 0..3
    # *_refs from v1.11+ (video_refs / music_refs / icon_refs / reference_image_urls)
```

All new fields are **soft-validated**: missing or wrong-shape values produce
warnings (`auto_fix_warnings` can promote some), never hard errors, so old
recipes keep validating.

### CLI commands gained between v1.21 and v1.39

```text
gen met-museum departments   list all 17 Met departments (v1.23.s158)
gen history-tail             rolling per-provider stats from r1a_history (v1.24.s162)
```

### CLI flags added

`gen` sub-app:
```
all-no-key  --provider, --bail-on-error, --compact
all-key     --provider, --bail-on-error, --compact
scout-by-license  --max-providers, --compact
list-providers    --filter kind:..., --compact
history-tail      --kind, --last, --compact
scryfall fetch    --type
pixabay photos    --orientation
pixabay videos    --video-type, --min-duration
pexels photos     --orientation
pexels videos     --min-duration
jamendo tracks    --instrument
wikimedia fetch   --license (cc0/pd/cc-by/cc-by-sa)
```

`pack` sub-app:
```
from-recipe       --provider-only, --provider-skip, --max-tier,
                  --cost-budget
list-recipes      --sort name|tier|platform|updated_utc|created_utc|
                  cost_minutes, --filter has-FIELD:bool,
                  --filter author:..., --filter contact:...,
                  --filter platform:..., --recipes-root,
                  --reverse, --compact
manifest-stats    --top N, --min-bytes, --since-days, --csv, --compact
rerun-failed      --max-attempts
```

`library` sub-app:
```
r1a-status        --provider, --kind, --env-set-only, --sort
                  bytes|downloaded|response_ms|last_manifest_utc|id,
                  --compact; live_response_ms + last_manifest_utc fields
                  added to per-provider rows
```

### HTTP endpoints (18 total on :8790)

New since v1.20:
- `GET /api/v1/gen/history-tail` (v1.24.s163) — read-only aggregation of
  `state/r1a_history/*.json` snapshots; query params `?last=N&kind=...`

### --compact JSON rollout (v1.34–v1.37)

Eight commands now accept `--compact` for single-line JSON output (no
indent), suitable for piping into `jq`, `wc`, downstream parsers:

```
pack list-recipes --json --compact          # v1.34.s200 — SLICE 200 MILESTONE
gen list-providers --json --compact         # v1.34.s201
library r1a-status --json --compact         # v1.34.s202
gen all-no-key --json --compact             # v1.35.s203
gen all-key --json --compact                # v1.35.s204
gen scout-by-license --json --compact       # v1.36.s205
pack manifest-stats --json --compact        # v1.36.s206
gen history-tail --json --compact           # v1.37.s207
```

In all 8 the indent argument flips between `None` (compact) and `2`
(default pretty). No effect when `--json` is absent.

---

## Architecture invariants preserved through 19 waves

1. **Single-AI-friendly**: every slice path-explicit (no `git add -A`).
2. **Backward-compatible**: every new flag has a no-op default; every
   new field is optional + soft-validated.
3. **Three-path symmetry**: when a new provider option lands, it threads
   CLI → runner → manifest entries → JSON contract tests.
4. **Test coverage parity**: every slice ships with at least one test;
   most ship 1–5.
5. **Wave milestone tags**: every 2–5 slices get a `v1.X-WAVE-COMPLETE`
   tag for rollback granularity (19 such waves in this block).

---

## Verification recipe

```pwsh
# Test suite
$env:PYTHONPATH = "C:\flax\flax-asset-worker\Python"
python -m pytest Tests/python -q --tb=no

# Origin tip
git rev-parse origin/main
git log --oneline 0b1ad7d..origin/main | Measure-Object -Line

# Tag inventory
git tag --list "v1.2*-WAVE-COMPLETE" "v1.3*-WAVE-COMPLETE" | Sort-Object
```

Expected at v1.39.1 close: 919 effective pass (1 live-net flake) /
HEAD on `63bb2bc` / 19 wave-complete tags v1.21–v1.38 plus v1.39.1
slice tag.

---

## Next backlog (v1.40+ candidates)

- `pack from-recipe --compact`, `pack validate-all --compact`,
  `pack rerun-failed --compact` (complete the compact rollout)
- `pack manifest-stats --html` (mirror r1a-status --html)
- `recipe.last_run_utc` derived from ledger (read-only field)
- `gen all-no-key --provider-skip` / `gen all-key --provider-skip`
  (mirror s213 to fan-out commands)
- Additional metadata helpers (Met `--has-images-only`, Iconify
  `--style outline|filled|duotone`, Archive.org `--collection`)
- Periodic HEARTBEAT refresh (~every 15 slices closed)
