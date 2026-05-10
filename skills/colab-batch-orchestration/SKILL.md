---
description: Parallel Colab worker orchestration for bulk asset generation batches
---

# Colab Batch Orchestration Skill

## When to Use
- Dispatching a large generation batch across 5 Colab accounts
- Monitoring which workers are idle vs running
- Handling Colab session death and job re-queue
- Planning daily batch targets per worker

## Worker Configuration

| Worker | Colab Account | Primary Generator | Batch Size | Daily Capacity |
|---|---|---|---|---|
| W1 | account_1 | Hunyuan3D-2 (img-to-3D) | 10 assets | ~120 assets |
| W2 | account_2 | Hunyuan3D-2 (text-to-3D) | 10 assets | ~120 assets |
| W3 | account_3 | TRELLIS | 15 assets | ~180 assets |
| W4 | account_4 | AnimationGPT | 8 clips | ~80 clips |
| W5 | account_5 | MusicGen / AudioLDM2 | 20 tracks | ~200 tracks |

**Total daily target**: ~700 generated assets + direct URL lanes filling remaining ~1,100 = ~1,800/day

## Dispatch Pattern

```python
# Dispatcher logic (Phase 3 scheduler)
for worker in workers:
    if worker.is_idle():
        batch = job_queue.pop_next_batch(
            generator=worker.primary_generator,
            size=worker.batch_size,
        )
        worker.dispatch(batch)
```

## Health Check Protocol
1. Before dispatch: ping Colab session endpoint
2. If no response in 30s → session dead → mark worker DEAD
3. Re-queue all pending jobs from dead worker to next available worker
4. Alert operator via print/log — no auto-restart (Colab free tier needs human GPU allocation)

## Retry Rules
- Max retries per asset: **3**
- Retry delay: **exponential backoff** — 60s, 120s, 240s
- After 3 failures: move to `manual_review_queue` with failure reason
- Partial batch success: publish passing assets immediately, re-queue failures

## Latency Handling
- Hunyuan3D-2: ~5–15 min per asset — use async dispatch, never block on single result
- TRELLIS: ~3–10 min per asset
- AnimationGPT: ~8–20 min per clip
- MusicGen: ~30–90 sec per track — can batch many in one session

## Colab Command
```bash
# Submit batch to specific Colab account
python scripts/cli.py asset-factory run-colab-batch \
  --account account_1 \
  --generator hunyuan3d2 \
  --pack-id BATCH_001 \
  --prompts prompts.json \
  --dry-run

# Check worker status
python scripts/cli.py asset-factory colab-worker-status
```

## Free Tier Limits
- Each Colab free account: ~4–6h GPU/day before throttle
- Rotate accounts daily — never exhaust all 5 on the same day
- If all 5 throttled: fall back to direct URL lanes (Kenney, Quaternius, game-icons) to fill the queue
