# Release notes — v1.40 through v1.57 (HTML/CSV dashboards + filter/sort polish)

> Generated 2026-05-14 during the BOSS lane-E BIG-SLICE-MANDATE run.
> Companion to RELEASE_NOTES_v1.21_v1.39.md (19-wave continuous-loop summary),
> RELEASE_NOTES_v1.12_v1.20.md (9-wave post-R1A summary), and
> RELEASE_NOTES_v1.10_v1.11.md (R1A canonical reference).

This doc covers the **18 waves** shipped after `v1.39-WAVE-COMPLETE`.

Cumulative state at v1.57.1 close:
- **337 commits** since baseline `0b1ad7d` (origin verified)
- **326 tags** pushed (45 wave milestones + ~140 slice tags)
- **1039 tests** passing
- **45 consecutive wave milestones** (v1.13->v1.57) with **0 RULE violations**
- **13 R1A providers**, **18 HTTP endpoints**, **18 Typer sub-apps**

---

## Wave-by-wave headline matrix

| Wave | Tag | Slices | Headline delivery |
|---|---|---|---|
| v1.40 | `v1.40-WAVE-COMPLETE` | s222-s231 (10) | HTML report rollout (manifest-stats / history-tail / list-providers); Iconify --style; Pexels/Pixabay/Unsplash --min-width/height; Archive.org --year-from/to; recipe last_run_utc; --sort last_run_utc |
| v1.41 | `v1.41-WAVE-COMPLETE` | s232-s234 (3) | list-recipes --since-days; recipe.engine_version; validate-all --html (950-test milestone) |
| v1.42 | `v1.42-WAVE-COMPLETE` | s235-s241 (6) | all-no-key/all-key --retry; history-tail --format csv/markdown; r1a-status --since-days; Pixabay/Pexels videos --min-width/height |
| v1.43 | `v1.43-WAVE-COMPLETE` | s242-s244 (3) | RAWG --min-rating; Met --include-imageless; Wikimedia --min-width/height (min-dim coverage complete) |
| v1.44 | `v1.44-WAVE-COMPLETE` | s245-s246 (2) | Archive.org + Unsplash --license filter |
| v1.45 | `v1.45-WAVE-COMPLETE` | s247-s249 (3) | recipe.expected_max_assets; from-recipe runtime within_expected_max gate; HEARTBEAT |
| v1.46 | `v1.46-WAVE-COMPLETE` | s250-s251 (2) | list-recipes --filter max-cost-minutes + min-cost-minutes (SLICE 250 MILESTONE) |
| v1.47 | `v1.47-WAVE-COMPLETE` | s252-s253 (2) | manifest-stats + list-providers HTML+top/filter compose locks |
| v1.48 | `v1.48-WAVE-COMPLETE` | s254-s255 (2) | scout-by-license + all-no-key --html |
| v1.49 | `v1.49-WAVE-COMPLETE` | s256 (1) | all-key --html |
| **v1.50** | `v1.50-WAVE-COMPLETE` | s257-s258 (2) | **from-recipe + rerun-failed --html. v1.50 MAJOR + 300-tag + 990-test milestones.** |
| v1.51 | `v1.51-WAVE-COMPLETE` | s259-s260 (2) | iconify list-sets + met-museum departments --html |
| v1.52 | `v1.52-WAVE-COMPLETE` | s261-s265 (5) | pack diff --html; metadata empty-list soft-warn; has-FIELD coverage; list-providers --filter license; **1000-test milestone** |
| v1.53 | `v1.53-WAVE-COMPLETE` | s266-s271 (6) | list-providers --sort/--reverse/--limit/--csv; r1a-status --limit; list-recipes --limit |
| v1.54 | `v1.54-WAVE-COMPLETE` | s272-s274 (3) | quadruple compose locks (filter+sort+limit+csv) |
| v1.55 | `v1.55-WAVE-COMPLETE` | s275-s276 (BIG=8+1) | list-recipes --csv; first BIG-SLICE (8 atomics under one tag per BOSS mandate) |
| v1.56 | `v1.56-WAVE-COMPLETE` | s277-s278 (BIG=5+6) | recipe.notes + CSV rollout to remaining 6 cmds. **--csv now spans 10 commands.** |
| v1.57 | (in flight) | s279+ (BIG=6+) | filter/sort polish + author sort + quad compose locks |

---

## Surface additions by category

### --html dashboard coverage (13 commands)

```text
library r1a-status     (v1.13.s97)
pack manifest-stats    (v1.40.s222)
gen history-tail       (v1.40.s223)
gen list-providers     (v1.40.s224)
pack validate-all      (v1.41.s234)
gen scout-by-license   (v1.48.s254)
gen all-no-key         (v1.48.s255)
gen all-key            (v1.49.s256)
pack from-recipe       (v1.50.s257)
pack rerun-failed      (v1.50.s258)
gen iconify list-sets  (v1.51.s259)
gen met-museum dept    (v1.51.s260)
pack diff              (v1.52.s261)
```

All `--html` commands accept `--open` companion flag for auto-launch
in system browser (Win: `os.startfile`, macOS: `open`, Linux: `xdg-open`).

### --csv export coverage (10 commands)

```text
pack manifest-stats    (v1.29.s186, predates wave)
library r1a-status     (v1.19.s135, predates wave)
pack list-recipes      (v1.55.s275)
gen list-providers     (v1.53.s271)
gen all-no-key         (v1.56.s277)
gen scout-by-license   (v1.56.s277)
gen all-key            (v1.56.s278)
pack from-recipe       (v1.56.s278)
pack validate-all      (v1.56.s278)
pack rerun-failed      (v1.56.s278)
```

CSV preempts HTML/JSON/text when set. Notes-field columns are truncated
to 80 chars + newline-stripped for one-line-per-row safety (per s277).

### --compact JSON coverage (11 commands)

All commands with `--json` also accept `--compact` for single-line output
(no indent), suitable for piping into `jq`, `wc`, downstream parsers.

### --sort / --limit / --reverse standardization

| Command | --sort keys |
|---|---|
| `pack list-recipes` | path, tier, name, platform, updated_utc, created_utc, last_run_utc, cost_minutes, **author** (v1.57.s279) |
| `gen list-providers` | id, license, asset_class, env_var |
| `library r1a-status` | bytes, downloaded, response_ms, last_manifest_utc, id |

All three commands accept `--limit N` (cap output after filter+sort)
and `--reverse` (flip ordering).

### Provider-specific filters added

```text
gen pexels photos --orientation --min-width --min-height
gen pixabay photos --orientation --min-width --min-height
gen unsplash photos --orientation --min-width --min-height
gen wikimedia fetch --license --min-width --min-height
gen archive-org fetch --license --year-from --year-to
gen iconify fetch --style
gen pexels videos --min-duration --min-width --min-height
gen pixabay videos --min-duration --min-width --min-height --video-type
gen rawg games --min-rating
gen met-museum fetch --include-imageless
gen scryfall fetch --type
```

### Recipe schema additions (11 optional + 4 derived)

```yaml
# Optional metadata (v1.40 onward)
recipe:
  created_utc: <ISO 8601>     # v1.23.s160
  updated_utc: <ISO 8601>     # v1.23.s160
  author: <string>            # v1.25.s172
  contact: <string>           # v1.25.s172
  platform: <string>          # v1.30.s189
  engine_version: <string>    # v1.41.s233
  cost_minutes: <int>         # v1.38.s210
  expected_max_assets: <int>  # v1.45.s247
  notes: <string>             # v1.56.s277

# Derived/computed (read-only)
  last_run_utc: <ISO 8601>    # v1.40.s230 (from pack-pipeline ledger mtime)
```

### Operational guardrails

```text
gen all-no-key/all-key --bail-on-error --retry N   (v1.28, v1.42)
gen scout-by-license --max-providers N             (v1.32.s196)
pack from-recipe --cost-budget --max-tier          (v1.27, v1.38)
pack rerun-failed --max-attempts N                 (v1.25.s168)
```

### Filter language extensions

- `list-recipes --filter has-FIELD:true/false` — generic presence test
  (v1.33.s199); covers ANY recipe field including new metadata
- `list-recipes --filter max-cost-minutes:N` and `min-cost-minutes:N`
  (v1.46.s250-s251) — budget range queries
- `list-recipes --filter min-tier:N` (v1.20.s139) — priority threshold
- `list-providers --filter kind:audio` / `license:cc0` / `env_var:NAME`
  (v1.25.s170, v1.52.s265, v1.57.s279)
- `r1a-status --filter --kind` / `--env-set-only` / `--since-days`
  (v1.31, v1.42)

---

## Architecture invariants preserved through 18 waves

1. **Single-AI-friendly**: every slice path-explicit; no `git add -A`.
2. **Backward-compatible**: every new flag has a no-op default; every
   new field is optional + soft-validated.
3. **Three-path symmetry**: when a new provider option lands, it threads
   CLI -> runner -> manifest entries -> JSON contract tests.
4. **Test coverage parity**: every slice ships with at least one test;
   BIG-SLICEs ship 5-8 paired tests under one tag.
5. **Wave milestone tags**: every 2-10 slices get a `v1.X-WAVE-COMPLETE`
   tag for rollback granularity (45 such waves to date).
6. **Composition lock tests**: pre-existing flag combinations are tested
   for evaluation-order stability (filter -> sort -> limit -> emit).

---

## BOSS-PING comms channel (filed during v1.42)

- File-based: `docs/verify/BOSS-PING-from-lane-<lane>-<topic>-<date>.md`
- HTTP-based: documented self-deadlock when lane pings own session
  (`docs/parallel/BOSS-PING-HTTP-protocol.md`); file fallback is reliable.
- 3 PINGs filed this run; 2 acknowledged by operator/BOSS.

---

## Milestones crossed in this 18-wave block

- **300-tag milestone** (v1.50.2)
- **310-commit milestone** (v1.48.2)
- **990-test milestone** (v1.50.2)
- **1000-test milestone** (v1.52.4)
- **v1.50 MAJOR milestone** (v1.50-WAVE-COMPLETE)
- **SLICE 250 milestone** (v1.46.1)

---

## Verification recipe

```pwsh
# Test suite
$env:PYTHONPATH = "C:\flax\flax-asset-worker\Python"
python -m pytest Tests/python -q --tb=no

# Origin tip
git rev-parse origin/main
git log --oneline 0b1ad7d..origin/main | Measure-Object -Line

# Wave-tag inventory (v1.4x..v1.5x)
git tag --list "v1.4*-WAVE-COMPLETE" "v1.5*-WAVE-COMPLETE" | Sort-Object
```

Expected at v1.57.1 close: 1039 tests pass / HEAD on `7af0361` /
18 wave-complete tags v1.40-v1.56 plus v1.57.1 slice tag.

---

## Next backlog (v1.58+ candidates)

- Composition test matrix expansion (more triple/quad locks)
- Recipe `recipe.tags` filter substring (currently exact)
- `gen list-providers --html` + `--filter` + `--limit` triple compose
- `--csv` for `gen history-tail` (mirror format=csv toggle into file)
- v2.0 cut decision (operator-only call)
- v2.3 scope (FMOD+DLSS bridges) lands in separate repo per ADR-024
