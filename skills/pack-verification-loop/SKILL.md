---
description: Review and publish verification loop for AssetBoy packs — ensure nothing ships without provenance and intake-ready packet data
---

# Pack Verification Loop Skill

## When to Use
- Before calling a pack "done"
- Before running `register-packet` or handing to Flax intake
- After a batch completes and results are in the output directory
- When auditing existing packs for completeness

## Verification Checklist

```
[ ] 1. Pack directory exists at the correct source or publish path

[ ] 2. At least 1 asset file is present (GLB/FBX/WAV/SVG etc.)

[ ] 3. provenance.json is present and valid
        → pack_id matches the directory name
        → license is not UNKNOWN or empty
        → source_url is not empty
        → download_date is present

[ ] 4. Cleanup / packet checks passed
        → run-cleanup or run-blender-cleanup completed for 3D packs
        → prepare-pack or register-packet is not reporting missing provenance / payload blockers

[ ] 5. G6 human review completed
        → review sign-off exists in provenance.json or operator notes

[ ] 6. No orphaned generator mesh files remain
        → no raw .obj/.ply left behind when the reviewed pack expects cleaned exports

[ ] 7. Intake validation is clean
        → auto-intake --dry-run does not report blockers for this pack
```

## Verification Commands
```bash
# Inspect the persistent pack ledger
python scripts/cli.py asset-factory pack-status --pack-id <id> --game-scope <scope>

# Dry-run the end-to-end source -> cleanup -> packet flow
python scripts/cli.py asset-factory prepare-pack --pack-id <id> --game-scope <scope> --source-dir <source_dir> --cleanup-mode auto --dry-run

# Validate publish packet readiness
python scripts/cli.py asset-factory check-publish --game <scope>

# Dry-run intake validation for one specific pack
python scripts/cli.py asset-factory auto-intake --pack-id <id> --dry-run
```

## Publish Gate
Only proceed when all of these are true:
1. provenance.json is valid
2. cleanup and packet checks are satisfied
3. human review is done
4. intake validation is clean

If any fail: block publish, fix the blocker, and rerun the loop.

## Recovery
- G1/G2/G3 failure → fix through cleanup, then rerun `prepare-pack` or `pack-status`
- G5 failure → write provenance / packet data, then rerun `prepare-pack` or `register-packet`
- G6 not done → operator review remains manual in the current CLI
- Intake blocker → rerun `check-publish` and `auto-intake --dry-run` after the fix
