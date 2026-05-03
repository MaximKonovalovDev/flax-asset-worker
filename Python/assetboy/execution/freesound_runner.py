"""
freesound_runner.py — Batch SFX downloads from Freesound.org via Playwright MCP.

Freesound.org is the largest CC-licensed sound effect library.
- CC0: completely free, no attribution required
- CC BY: free, attribution needed (saved to provenance)
- CC BY-NC: free non-commercial only — we skip these

Usage (via CLI):
    python -m assetboy.cli run-freesound-batch --search "sword clash metal" --count 10
    python -m assetboy.cli run-freesound-batch --use-presets --dry-run

When Playwright MCP is active, the AI navigates Freesound, filters by CC0/CC-BY,
and downloads audio files directly into FlaxAssetLibrary/inbox.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.library.paths import manual_drop_dir

FREESOUND_BASE = "https://freesound.org"

# ---------------------------------------------------------------------------
# Roman Arena SFX presets
# ---------------------------------------------------------------------------

ROMAN_SFX_PRESETS: list[dict] = [
    {"pack_id": "RA_PACK_SFX_COMBAT_01",     "search": "sword clash metal impact", "tags": ["combat", "weapon", "metal"]},
    {"pack_id": "RA_PACK_SFX_FOOTSTEP_01",   "search": "footstep stone gravel walk", "tags": ["locomotion", "stone", "footstep"]},
    {"pack_id": "RA_PACK_SFX_CROWD_01",      "search": "crowd cheering roar arena", "tags": ["crowd", "ambient", "arena"]},
    {"pack_id": "RA_PACK_SFX_AMBIENT_01",    "search": "wind outdoor ambient desert noon", "tags": ["ambient", "outdoor", "wind"]},
    {"pack_id": "RA_PACK_SFX_IMPACT_01",     "search": "shield bash thud heavy impact body", "tags": ["impact", "combat", "shield"]},
    {"pack_id": "RA_PACK_SFX_WEAPON_01",     "search": "arrow whoosh projectile fly", "tags": ["weapon", "projectile", "whoosh"]},
    {"pack_id": "RA_PACK_SFX_DEATH_01",      "search": "death grunt groan warrior fall", "tags": ["death", "voice", "combat"]},
    {"pack_id": "RA_PACK_SFX_UI_01",         "search": "UI click button select menu chime soft", "tags": ["ui", "menu", "click"]},
    {"pack_id": "RA_PACK_SFX_GATE_01",       "search": "gate door heavy wood creak open", "tags": ["environment", "gate", "wood"]},
    {"pack_id": "RA_PACK_SFX_FIRE_01",       "search": "fire torch flame crackle loop", "tags": ["environment", "fire", "loop"]},
]


@dataclass
class FreesoundBatchResult:
    pack_id: str
    search: str
    output_dir: Path
    job_spec_path: Path | None = None
    steps: list[dict] = field(default_factory=list)
    dry_run: bool = False
    executed: bool = False
    execution_mode: str = "plan"
    artifacts_dir: Path | None = None
    last_url: str = ""

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "search": self.search,
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path) if self.job_spec_path else None,
            "steps": len(self.steps),
            "dry_run": self.dry_run,
            "executed": self.executed,
            "execution_mode": self.execution_mode,
            "artifacts_dir": str(self.artifacts_dir) if self.artifacts_dir else None,
            "last_url": self.last_url,
        }


def _build_freesound_steps(
    search: str,
    count: int,
    pack_id: str,
    output_dir: Path,
    allowed_licenses: list[str],
) -> list[dict]:
    """Structured Playwright steps for Freesound.org batch download."""
    encoded_licenses = "+OR+".join(f'\"{license}\"' for license in allowed_licenses)
    license_filter = f"license%3A%28{encoded_licenses}%29"
    search_url = (
        f"{FREESOUND_BASE}/search/"
        f"?q={search.replace(' ', '+')}"
        f"&f={license_filter}"
        f"&s=Rating+(highest+first)"
    )
    steps = [
        {"action": "navigate", "params": {"url": search_url},
         "note": f"Search Freesound for: {search}  (licenses: {', '.join(allowed_licenses)})"},
        {"action": "screenshot", "params": {}, "note": "Confirm results loaded"},
        {"action": "note", "params": {}, "note": f"Filter: only CC0 or CC BY, top {count} results by rating"},
    ]
    for i in range(1, count + 1):
        steps += [
            {"action": "click",
             "params": {"selector": f":nth-match(a[href*='/sounds/'], {i})"},
             "note": f"Asset {i}: open sound detail page"},
            {"action": "screenshot", "params": {}, "note": f"Asset {i}: confirm sound page loaded"},
            {"action": "note", "params": {},
             "note": f"Asset {i}: verify license = CC0 or CC BY before downloading. If CC BY-NC or All Rights Reserved, SKIP."},
            {"action": "download",
             "params": {
                 "dest_dir": str(output_dir),
                 "rename_hint": f"sfx_{pack_id}_{i:02d}",
                 "dom_selector": "#share-link",
                 "dom_attr": "data-static-file-url",
             },
             "note": f"Asset {i}: save WAV to {output_dir}"},
            {"action": "note", "params": {},
             "note": f"Asset {i}: record to provenance: page URL, author, license, download date"},
            {"action": "navigate_back", "params": {}, "note": f"Asset {i}: back to search results"},
        ]
    steps.append({"action": "note", "params": {},
                  "note": f"Done. {count} SFX saved to {output_dir}. Review provenance before publish."})
    return steps


def run_freesound_batch(
    *,
    search: str = "combat sword metal",
    pack_id: str | None = None,
    game_scope: str = "roman_arena",
    count: int = 10,
    output_dir: str | Path | None = None,
    allowed_licenses: list[str] | None = None,
    dry_run: bool = False,
    use_presets: bool = False,
    execute: bool = False,
    headed: bool = True,
    browser_profile_dir: str | Path | None = None,
    timeout_ms: int = 15000,
) -> list[FreesoundBatchResult]:
    """
    Emit Playwright MCP steps to batch-download SFX from Freesound.org.

    License filter defaults to CC0 and Attribution (CC BY) only.
    CC BY-NC and All Rights Reserved are always skipped.
    """
    if execute and dry_run:
        raise ValueError("run_freesound_batch cannot use execute=True together with dry_run=True.")

    from assetboy.execution.playwright_runner import run_browser_job

    licenses = allowed_licenses or ["Attribution", "Creative Commons 0"]

    if use_presets:
        jobs = ROMAN_SFX_PRESETS
    else:
        pid = pack_id or f"RA_PACK_SFX_{search.replace(' ', '_').upper()[:20]}_01"
        jobs = [{"pack_id": pid, "search": search, "tags": []}]

    results = []
    for job in jobs:
        pid = job["pack_id"]
        s = job["search"]
        out_dir = Path(output_dir) if output_dir else manual_drop_dir() / "freesound" / pid
        out_dir.mkdir(parents=True, exist_ok=True)
        encoded_licenses = "+OR+".join(f'\"{license}\"' for license in licenses)
        license_filter = f"license%3A%28{encoded_licenses}%29"
        search_url = (
            f"{FREESOUND_BASE}/search/"
            f"?q={s.replace(' ', '+')}"
            f"&f={license_filter}"
            f"&s=Rating+(highest+first)"
        )

        steps = _build_freesound_steps(s, count, pid, out_dir, licenses)

        spec = {
            "source_adapter": "freesound_audio",
            "source_url": search_url,
            "search_terms": [s],
            "destination": str(out_dir),
            "source": "freesound",
            "pack_id": pid,
            "game_scope": game_scope,
            "search": s,
            "count": count,
            "licenses": licenses,
            "output_dir": str(out_dir),
            "playwright_steps": steps,
        }
        spec_path = out_dir / "freesound_job.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        browser_result = None
        if execute:
            browser_result = run_browser_job(
                spec_path,
                execute=True,
                headed=headed,
                browser_profile_dir=browser_profile_dir,
                timeout_ms=timeout_ms,
            )

        result = FreesoundBatchResult(
            pack_id=pid, search=s, output_dir=out_dir,
            job_spec_path=spec_path, steps=steps, dry_run=dry_run,
            executed=browser_result.executed if browser_result else False,
            execution_mode=browser_result.execution_mode if browser_result else "plan",
            artifacts_dir=browser_result.artifacts_dir if browser_result else None,
            last_url=browser_result.last_url if browser_result else "",
        )

        mode = "DRY RUN" if dry_run else ("EXECUTED" if execute else "EXECUTION PLAN")
        print(f"\n[{mode}] Freesound SFX: '{s}' -> {pid}")
        print(f"Licenses: {', '.join(licenses)} | Count: {count} | Output: {out_dir}")
        print(f"Job spec: {spec_path}")
        if dry_run or not execute:
            print(f"Playwright steps: {len(steps)}")
            for i, step in enumerate(steps[:5], 1):
                print(f"  {i}. [{step['action']}] {step['note']}")
            if len(steps) > 5:
                print(f"  ... and {len(steps) - 5} more steps")
        if browser_result and browser_result.artifacts_dir is not None:
            print(f"Artifacts: {browser_result.artifacts_dir}")

        results.append(result)

    print(f"\nTotal Freesound batches: {len(results)}")
    return results
