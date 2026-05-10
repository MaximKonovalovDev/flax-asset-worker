---
description: Learn from batch results to improve prompts, source selection, and gate pass rates over time
---

# Continuous Learning Skill

## When to Use
- After a batch completes, before starting the next one
- When gate pass rates are below 80%
- When building prompt templates for a new asset category
- When deciding whether to add a new bridge or drop a failing one

## What to Learn After Each Batch

### 1. Gate Pass Rate by Source
After every batch, record:
```json
{
  "batch_id": "BATCH_2026_03_19_001",
  "source": "hunyuan3d2_3d",
  "total_assets": 20,
  "g1_pass": 20,
  "g2_pass": 15,
  "g3_pass": 12,
  "g5_pass": 20,
  "g6_pass": 10,
  "first_pass_rate": 0.50,
  "notes": "Poly count too high for props — add --simplify next batch"
}
```

Track this in `knowledge/BATCH_LEARNING_LOG.md` or `data/batch_stats.jsonl`.

### 2. Prompt Improvement Loop
- If G2 fails often → prompt is too detailed → add "low-poly, game-ready mesh" constraint
- If G3 fails often → prompt doesn't specify materials → add "with PBR materials, textured"
- If G6 fails often → visual quality poor → change generator, add style reference

**Apply APE pattern**: score 10 prompts against gate pass rate, keep top 3 as next-batch templates.

### 3. Source Retirement
Retire a bridge from primary routing if:
- < 50% first-pass gate rate over 3 consecutive batches
- Assets consistently fail G6 (visual quality unacceptable)
- Source URL is dead or requires auth that expired

Move retired bridge to `BRIDGE_AUDIT.md` with reason noted.

### 4. Shared Library Gap Analysis
After each game scope's packs are published, run:
```bash
python scripts/cli.py asset-factory print-pack-targets
python scripts/cli.py asset-factory roman-blockers
```

Compare result against shared library:
- If gap is in shared lib → route to shared lib adapter, don't regenerate
- If gap is unique to this scope → generate new, add to scope pack
- If gap appears in 3+ scopes → promote to shared library, retire per-scope versions

### 5. Weekly Score Card
Maintain in `docs/PIPELINE_STATUS.md` or a dedicated learning log linked from it:
```
## Production Scorecard
- Assets generated this week: N
- Gate first-pass rate: N%
- Top failing gate: G2 (poly count)
- Best performing source: kenney (100% CC0, 100% G1)
- Worst performing source: hunyuan3d2 (55% first-pass)
- Shared library reuse rate: N%
```

## Learning Cadence
- After each batch: update `BATCH_LEARNING_LOG.md`
- Weekly: update `docs/PIPELINE_STATUS.md` scorecard
- Monthly: review bridge pass rates, retire poor performers, add new sources

## Target Metrics
| Metric | Target |
|---|---|
| Gate first-pass rate | ≥ 80% |
| Shared library reuse | ≥ 60% |
| Human review time | < 30 min/scope |
| Source diversity (free) | ≥ 5 active CC0 bridges |
