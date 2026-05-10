---
description: Live browser-source review for Fab, Mixamo, Poly Haven, and other manual lanes using screenshots, format checks, and harvest ranking before download.
---

# Browser Source Review Skill

## When to Use
- Before claiming or downloading from Fab
- When a browser/manual source looks promising but needs a real visual check
- When ranking multiple listings into `grab now`, `manual later`, or `skip`
- When the source lane is healthy, but the content quality is still uncertain

## Required Checks
1. Open the live listing page.
2. Capture a screenshot under `state/generated/fab_live_review/` or another scoped review folder.
3. Confirm the hero media is actually usable.
4. Confirm included formats.
5. Confirm price / free state.
6. Confirm license terms or source notes.
7. Confirm download access:
   - `batch-direct`
   - `library-or-purchase-required`
   - `unreal-engine-only`
8. Rank the listing.

## Format Preference
1. `fbx`
2. `glb`
3. `gltf`
4. `usdz`
5. `blend`

If the page is Unreal-only or hides the real payload format, do not call it low-friction.

## Ranking
- `grab_now`
  - Good hero media
  - Acceptable license
  - Contains useful formats
  - `batch-direct` access or already-owned direct access
  - Strong fit for the current family or game slice
- `manual_later`
  - Visually promising, but heavier cleanup, purchase/library friction, or uncertain pack purity
- `skip`
  - Weak visuals, unclear licensing, wrong content, or poor formats

Treat `grab_now` as `best steals now`, `manual_later` as `good but later`, and `skip` as `reference_only` unless one specific artifact is still worth keeping.

## Fab Review Loop
```bash
1. Open listing
2. Capture screenshot
3. Read Included formats
4. Read Details / License terms / Free state
5. Record download access:
   - `batch-direct`
   - `library-or-purchase-required`
   - `unreal-engine-only`
6. Record one short verdict:
   - visual read
   - format read
   - friction read
   - rank
```

## Good Fab Signals
- clean modular preview render
- multiple preview angles
- direct `fbx` / `glb` / `gltf`
- `batch-direct` access
- clear free button or straightforward price
- category and tags match the intended family

## Bad Fab Signals
- Unreal-only payload path
- purchase/library friction when the current sprint needs immediate batch harvest
- unclear or missing format details
- weak or misleading preview media
- category mismatch
- too much broad pack clutter for a focused family

## Output Shape
For each reviewed listing, keep:
- listing title
- listing URL
- screenshot path
- included formats
- price/free note
- license note
- download access note
- one-line verdict
- rank: `grab_now`, `manual_later`, or `skip`

## Notes
- This skill does not replace provenance.
- This skill sits before claim/download, not after.
- Use it to avoid filling the library with technically valid but strategically weak packs.
