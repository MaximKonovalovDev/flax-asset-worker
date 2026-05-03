"""
music_runner.py — Music acquisition via Mixkit (direct) and Suno/Udio (Playwright AI gen).

Three music sources:
    1. Mixkit (mixkit.co) — free commercial license, direct MP3 download via Playwright
    2. Suno (suno.ai) — AI-generated music, 50 free songs/day, Playwright-driven
    3. Udio (udio.com) — AI-generated music, free tier, Playwright-driven

Usage (via CLI):
    python -m assetboy.cli run-music-batch --use-presets --dry-run
    python -m assetboy.cli run-music-batch --source suno --prompt "epic roman arena drums battle" --pack-id RA_PACK_MUS_COMBAT_01
    python -m assetboy.cli run-music-batch --source mixkit --search "epic battle" --count 3
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.library.paths import manual_drop_dir

MIXKIT_BASE = "https://mixkit.co/free-stock-music"
SUNO_BASE = "https://suno.ai"
UDIO_BASE = "https://www.udio.com"

# ---------------------------------------------------------------------------
# Roman Arena Music presets
# ---------------------------------------------------------------------------

ROMAN_MUSIC_PRESETS: list[dict] = [
    {
        "pack_id": "RA_PACK_MUS_COMBAT_01",
        "title": "Combat Theme",
        "source": "suno",
        "prompt": "epic roman gladiator battle theme, war drums, brass fanfare, intense orchestral, no vocals, loop-friendly",
        "tags": ["combat", "orchestral", "battle", "drums"],
    },
    {
        "pack_id": "RA_PACK_MUS_AMBIENT_01",
        "title": "Arena Ambient",
        "source": "suno",
        "prompt": "ancient roman arena ambient atmosphere, crowd murmur, light strings, warm midday sun, subtle tension, no melody",
        "tags": ["ambient", "atmosphere", "crowd", "loop"],
    },
    {
        "pack_id": "RA_PACK_MUS_VICTORY_01",
        "title": "Victory Fanfare",
        "source": "suno",
        "prompt": "short roman victory fanfare, trumpet brass, triumphant, 10 seconds, no vocals, ancient roman feel",
        "tags": ["victory", "fanfare", "short", "brass"],
    },
    {
        "pack_id": "RA_PACK_MUS_MENU_01",
        "title": "Main Menu Theme",
        "source": "suno",
        "prompt": "ancient roman epic main menu music, cinematic orchestral, grand, building strings and drums, no vocals",
        "tags": ["menu", "cinematic", "orchestral", "intro"],
    },
    {
        "pack_id": "RA_PACK_MUS_DEATH_01",
        "title": "Defeat Sting",
        "source": "suno",
        "prompt": "short dramatic defeat sting, sad descending melody, ancient roman feel, under 8 seconds, no vocals",
        "tags": ["defeat", "sting", "short", "sad"],
    },
    {
        "pack_id": "RA_PACK_MUS_MIXKIT_01",
        "title": "Battle Stock Track",
        "source": "mixkit",
        "search": "epic battle action adventure",
        "tags": ["battle", "action", "stock"],
    },
]


@dataclass
class MusicBatchResult:
    pack_id: str
    source: str
    prompt_or_search: str
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
            "source": self.source,
            "prompt_or_search": self.prompt_or_search,
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path) if self.job_spec_path else None,
            "steps": len(self.steps),
            "dry_run": self.dry_run,
            "executed": self.executed,
            "execution_mode": self.execution_mode,
            "artifacts_dir": str(self.artifacts_dir) if self.artifacts_dir else None,
            "last_url": self.last_url,
        }


# ---------------------------------------------------------------------------
# Step builders per source
# ---------------------------------------------------------------------------

def _build_suno_steps(prompt: str, pack_id: str, output_dir: Path) -> list[dict]:
    return [
        {"action": "navigate", "params": {"url": SUNO_BASE},
         "note": "Open Suno.ai (logged in with Google account)"},
        {"action": "screenshot", "params": {}, "note": "Confirm Suno loaded"},
        {"action": "click", "params": {"selector": "textarea[placeholder*='describe']"},
         "note": "Click the prompt text area"},
        {"action": "type", "params": {"text": prompt},
         "note": f"Enter prompt: {prompt[:80]}..."},
        {"action": "click", "params": {"selector": "button[aria-label*='Create'], button[data-testid*='create']"},
         "note": "Click Create / Generate button"},
        {"action": "wait", "params": {"ms": 15000},
         "note": "Wait ~15s for generation to complete"},
        {"action": "screenshot", "params": {}, "note": "Confirm tracks generated (should show 2 variations)"},
        {"action": "click", "params": {"selector": "button[aria-label*='download'], [data-testid*='download']"},
         "note": "Click download on the best variation"},
        {"action": "download", "params": {"dest_dir": str(output_dir), "rename_hint": pack_id},
         "note": f"Save MP3 to {output_dir}"},
        {"action": "screenshot", "params": {}, "note": "Confirm downloaded"},
        {"action": "note", "params": {},
         "note": f"Provenance: Suno.ai generated, prompt logged, Suno ToS allows personal/game use"},
    ]


def _build_udio_steps(prompt: str, pack_id: str, output_dir: Path) -> list[dict]:
    return [
        {"action": "navigate", "params": {"url": UDIO_BASE},
         "note": "Open Udio.com"},
        {"action": "screenshot", "params": {}, "note": "Confirm Udio loaded"},
        {"action": "click", "params": {"selector": "textarea, input[type=text]"},
         "note": "Click the prompt input"},
        {"action": "type", "params": {"text": prompt},
         "note": f"Enter prompt: {prompt[:80]}..."},
        {"action": "click", "params": {"selector": "button[type=submit], button:contains('Generate')"},
         "note": "Click Generate"},
        {"action": "wait", "params": {"ms": 20000}, "note": "Wait for generation"},
        {"action": "screenshot", "params": {}, "note": "Confirm output ready"},
        {"action": "click", "params": {"selector": "[aria-label*='download'], .download-btn"},
         "note": "Download the best track"},
        {"action": "download", "params": {"dest_dir": str(output_dir), "rename_hint": pack_id},
         "note": f"Save to {output_dir}"},
    ]


def _build_mixkit_steps(search: str, count: int, pack_id: str, output_dir: Path) -> list[dict]:
    url = f"{MIXKIT_BASE}/?q={search.replace(' ', '+')}"
    steps = [
        {"action": "navigate", "params": {"url": url},
         "note": f"Open Mixkit free music search: {search}"},
        {"action": "screenshot", "params": {}, "note": "Confirm results loaded"},
        {"action": "note", "params": {},
         "note": f"Mixkit license: free for commercial use including games"},
    ]
    for i in range(1, count + 1):
        steps += [
            {"action": "click",
             "params": {"selector": f':nth-match(button:has-text("Download Free Music"), {i})'},
             "note": f"Track {i}: click Free Download"},
            {"action": "download",
             "params": {"dest_dir": str(output_dir), "rename_hint": f"music_{pack_id}_{i:02d}"},
             "note": f"Track {i}: save MP3 to {output_dir}"},
            {"action": "note", "params": {}, "note": f"Track {i}: record track title and Mixkit URL for provenance"},
        ]
    return steps


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_music_batch(
    *,
    source: str = "suno",
    prompt: str | None = None,
    search: str | None = None,
    pack_id: str | None = None,
    game_scope: str = "roman_arena",
    count: int = 2,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    use_presets: bool = False,
    execute: bool = False,
    headed: bool = True,
    browser_profile_dir: str | Path | None = None,
    timeout_ms: int = 15000,
) -> list[MusicBatchResult]:
    """
    Emit Playwright MCP steps to acquire music for a pack.

    source options: 'suno', 'udio', 'mixkit'
    """
    if execute and dry_run:
        raise ValueError("run_music_batch cannot use execute=True together with dry_run=True.")

    from assetboy.execution.playwright_runner import run_browser_job

    if use_presets:
        jobs = ROMAN_MUSIC_PRESETS
    else:
        pid = pack_id or f"RA_PACK_MUS_CUSTOM_01"
        q = prompt or search or "epic battle orchestral"
        jobs = [{"pack_id": pid, "source": source, "prompt": q, "search": q, "tags": []}]

    results = []
    for job in jobs:
        pid = job["pack_id"]
        src = job.get("source", source)
        out_dir = Path(output_dir) if output_dir else manual_drop_dir() / "music" / pid
        out_dir.mkdir(parents=True, exist_ok=True)

        p = job.get("prompt") or job.get("search", "")
        source_url = SUNO_BASE
        if src == "suno":
            steps = _build_suno_steps(p, pid, out_dir)
            search_terms = [p]
        elif src == "udio":
            steps = _build_udio_steps(p, pid, out_dir)
            source_url = UDIO_BASE
            search_terms = [p]
        else:
            steps = _build_mixkit_steps(job.get("search", p), count, pid, out_dir)
            source_url = f"{MIXKIT_BASE}/?q={job.get('search', p).replace(' ', '+')}"
            search_terms = [job.get("search", p)]

        spec = {
            "source_adapter": src,
            "source_url": source_url,
            "search_terms": search_terms,
            "destination": str(out_dir),
            "source": src,
            "pack_id": pid,
            "game_scope": game_scope,
            "prompt_or_search": p,
            "count": count if src == "mixkit" else 1,
            "output_dir": str(out_dir),
            "playwright_steps": steps,
        }
        spec_path = out_dir / "music_job.json"
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

        result = MusicBatchResult(
            pack_id=pid, source=src, prompt_or_search=p,
            output_dir=out_dir, job_spec_path=spec_path,
            steps=steps, dry_run=dry_run,
            executed=browser_result.executed if browser_result else False,
            execution_mode=browser_result.execution_mode if browser_result else "plan",
            artifacts_dir=browser_result.artifacts_dir if browser_result else None,
            last_url=browser_result.last_url if browser_result else "",
        )

        mode = "DRY RUN" if dry_run else ("EXECUTED" if execute else "EXECUTION PLAN")
        print(f"\n[{mode}] Music [{src}]: {pid}")
        print(f"Prompt/Search: {p[:70]}...")
        print(f"Output: {out_dir}")
        if dry_run or not execute:
            for i, step in enumerate(steps[:4], 1):
                print(f"  {i}. [{step['action']}] {step['note']}")
            if len(steps) > 4:
                print(f"  ... and {len(steps) - 4} more steps")
        if browser_result and browser_result.artifacts_dir is not None:
            print(f"Artifacts: {browser_result.artifacts_dir}")

        results.append(result)

    print(f"\nTotal music jobs: {len(results)}")
    return results
