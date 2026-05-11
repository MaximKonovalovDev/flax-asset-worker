# Docs Index — flax-asset-worker

> Master navigation hub. Read this first to find the right doc.
> Last update: 2026-05-11 (v1.11.15 milestone).

---

## I just woke up — what should I read first?

| Question | Doc |
|---|---|
| "What's the project state right now?" | `HEARTBEAT-assetboi.md` (TL;DR at top) |
| "What changed in the v1.10-v1.11 wave?" | `RELEASE_NOTES_v1.10_v1.11.md` |
| "How do I get started as operator?" | `SETUP.md` |
| "What providers are available?" | `RELEASE_NOTES_v1.10_v1.11.md` table at top |
| "How do I write a recipe?" | `RECIPE_SCHEMA.md` |
| "What's the slice-by-slice history?" | `COMMIT_READY-assetboi.md` |

---

## By topic

### Operator onboarding (new to repo)

1. `../README.md` — front-page table + quick scout commands
2. `SETUP.md` — 10-section setup (Python, generators, auth providers, **§5.5 R1A keys**)
3. `RELEASE_NOTES_v1.10_v1.11.md` — what was just added; operator's first commands
4. `RECIPE_SCHEMA.md` — recipe authoring reference

### Authoring a new recipe

1. `RECIPE_SCHEMA.md` — required + optional fields per acquisition lane
2. `../recipes/sandbox/r1a_smoke.yaml` — read this as a working template
3. `pack validate recipes/<game>/<new>.yaml` — catch shape errors before run
4. `pack from-recipe sandbox/r1a_smoke.yaml --dry-run` — try the smoke first

### Hacking on the runner code

1. `RELEASE_NOTES_v1.10_v1.11.md` §Runner shape — uniform contract every R1A runner follows
2. `../Python/assetboy/execution/met_museum_runner.py` — reference (~260 LOC, smallest R1A runner)
3. `../Tests/python/test_met_museum_runner.py` — reference test pattern (mocks urllib)
4. `RECIPE_SCHEMA.md` §"Provider-specific optional fields" — pack-level options to thread through

### Adding a new public-API provider

Mirror the existing R1A pattern in 5 commits:

1. New `Python/assetboy/execution/<name>_runner.py` with `run_X_batch` + tests
2. New sub-app + command in `Python/assetboy/cli/gen.py` + smoke tests
3. `Python/assetboy/workflows/acquisition_router.py` dispatch + `_drive_X` driver
4. `Python/assetboy/workflows/recipe_validator.py` DIRECT_URL_PROVIDERS allowlist
5. `Python/assetboy/providers/lanes.py` SOURCE_ADAPTERS entry

See git log for v1.10.0-v1.10.9 for concrete examples (one tag per provider).

### Debugging a failing recipe

1. `pack validate <recipe>` — first stop, catches schema errors
2. `pack validate-all --json` — sanity check across full catalog
3. `pack from-recipe --dry-run` — runs without network; surfaces router routing bugs
4. `gen list-providers --json` — verify env keys for any key-required providers in the recipe

### CI / regression-guard concerns

1. `../Tests/python/test_*` — 612 tests as of v1.11.15; offline (mocked urllib)
2. `../Tests/python/test_cli_json_contract.py` — JSON shape contracts consumed by C# routes
3. `../Tests/python/conftest.py` — fixture setup (no global mocks; each test is self-contained)
4. `pwsh scripts/setup-r1a-keys.ps1 -List` — verify env-var state for live-API tests

---

## File map (active surfaces)

```
README.md                                front-door (asset-class table + quick start)
docs/
  _INDEX.md                              (this file)
  HEARTBEAT-assetboi.md                  operator wake-up doc (TL;DR + lineage)
  SETUP.md                               operator setup guide (§5.5 R1A keys)
  RECIPE_SCHEMA.md                       authoritative recipe schema
  RELEASE_NOTES_v1.10_v1.11.md           R1A wave canonical reference
  COMMIT_READY-assetboi.md               slice-by-slice append-only ledger
  PATH_B_DAY11_PLAN.md                   backlog organization (older)
  MEGA_TOOL_DISPATCH.md                  Lane E broker dispatch contract (flax-mcp side)
  MONOREPO_FACADE_DESIGN.md              facade plan (older)
  research/
    PUBLIC-APIS-ASSET-MINE-2026-05-11.md R1A catalog source (82 APIs)

Python/assetboy/
  cli/                                    Typer sub-apps (18 of them)
    gen.py                                gen sub-app with all 10 R1A providers
    pack.py                               pack sub-app with list/validate/from-recipe/...
    library.py / fab.py / unity.py / epic.py / import_cmd.py
  execution/                              16 runners
    <provider>_runner.py                  one per provider (mocked-tested)
  providers/
    lanes.py                              SOURCE_ADAPTERS + ProviderLane
    bridge_registry.py                    BridgeDefinition entries (older shape)
  workflows/
    acquisition_router.py                 3-lane dispatch + driver functions
    recipe_validator.py                   YAML schema validation + auto_fix
    pack_pipeline.py                      per-pack 4-stage flow
    flax_wrapper.py                       MCP-side bridge
  library/
    shared_packs.py                       library-side recipe parts (R1A NOT yet registered here)
    paths.py                              filesystem layout

Source/                                   C# side (Flax editor plugin)
  Core/WorkerHttpServer.cs                :8790 HTTP server (13 endpoints)
  Routes/                                 5 route handlers including ProviderRoutes
  Providers/                              C#-native providers (PolyHaven, Kenney)

recipes/                                  5 working YAML recipes
  primitive_tech/first_playable.yaml      survival genre
  roman/first_playable.yaml               action_combat genre
  sandbox/                                3 smoke recipes
    one_pack_smoke.yaml                   1-pack PolyHaven
    generator_smoke.yaml                  4-pack generator lane
    r1a_smoke.yaml                        5-pack R1A no-key (v1.11.6)

scripts/
  setup-r1a-keys.ps1                      interactive env-var setup (v1.11.13)
```

---

## Reading order for next AI session

Coming in fresh? Here's the minimum to be productive:

1. `HEARTBEAT-assetboi.md` (3 min)
2. `RELEASE_NOTES_v1.10_v1.11.md` (8 min)
3. `RECIPE_SCHEMA.md` (5 min)
4. `SETUP.md` §5.5 (2 min)
5. Skim `../README.md` (2 min)

Total: ~20 min of focused reading covers everything the R1A wave shipped.

If you need slice-level history beyond v1.10.0, page through
`COMMIT_READY-assetboi.md` (it's long — ~2300 lines — but navigable by
slice id).

---

*This index is maintained alongside major milestones. If you add a
new top-level doc, update this file in the same commit.*
