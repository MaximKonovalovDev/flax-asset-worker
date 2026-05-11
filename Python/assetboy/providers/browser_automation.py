from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


class BrowserRuntime(str, Enum):
    PLAYWRIGHT_MCP = "playwright_mcp"
    BROWSER_USE = "browser_use"


@dataclass(frozen=True)
class BrowserAutomationJob:
    source_adapter: str
    runtime: BrowserRuntime
    pack_id: str
    game_scope: str
    source_url: str
    search_terms: tuple[str, ...]
    login_required: bool
    destination: Path
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_adapter": self.source_adapter,
            "runtime": self.runtime.value,
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "source_url": self.source_url,
            "search_terms": list(self.search_terms),
            "login_required": self.login_required,
            "destination": str(self.destination),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class BrowserAutomationArtifacts:
    output_dir: Path
    job_spec_path: Path
    provenance_template_path: Path
    review_checklist_path: Path
    payload_target_path_file: Path
    download_target_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "provenance_template_path": str(self.provenance_template_path),
            "review_checklist_path": str(self.review_checklist_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "download_target_path": str(self.download_target_path),
        }


def emit_browser_automation_job(
    *,
    source_adapter: str,
    runtime: BrowserRuntime | str,
    pack_id: str,
    game_scope: str,
    source_url: str,
    search_terms: tuple[str, ...] = (),
    login_required: bool = True,
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
) -> BrowserAutomationArtifacts:
    download_target = manual_drop_dir() / pack_id
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    runtime_value = BrowserRuntime(runtime)
    job = BrowserAutomationJob(
        source_adapter=source_adapter,
        runtime=runtime_value,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        search_terms=search_terms,
        login_required=login_required,
        destination=download_target,
        notes=notes,
    )
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "browser_automation" / source_adapter / pack_id
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter=source_adapter,
        payload_target_path=str(payload_target),
        notes=notes,
    )
    provenance["values"]["source_page_url"] = source_url
    checklist_lines = [
        f"# Browser Automation Checklist: {source_adapter}",
        "",
        f"- Runtime: `{runtime_value.value}`",
        f"- Pack: `{pack_id}`",
        f"- Game scope: `{game_scope}`",
        f"- Source URL: `{source_url}`",
        f"- Download target: `{download_target}`",
        f"- Payload target: `{payload_target}`",
        "",
        "## Operator Steps",
        f"- Sign in if required: `{str(login_required).lower()}`",
        "- Run the browser automation flow against the source page or search terms.",
        "- Preserve the downloaded filenames for provenance.",
        "- Move accepted exports or archives through cleanup before publish.",
    ]
    if search_terms:
        checklist_lines.extend(["", "## Search Terms"])
        checklist_lines.extend(f"- `{term}`" for term in search_terms)

    job_payload = job.to_dict()
    if runtime_value == BrowserRuntime.PLAYWRIGHT_MCP:
        # Path B s2.6b (2026-05-11): playwright_runner is DEAD-pending. The
        # PLAYWRIGHT_MCP runtime now emits a placeholder hint instead of
        # injecting structured steps. Operators using Playwright MCP should
        # invoke it via Microsoft's @playwright/mcp server directly (see
        # PATH_B_DAY11_PLAN.md s11 acquisition router design).
        job_payload["playwright_steps"] = []
        job_payload["playwright_steps_note"] = (
            "Path B v1.2: playwright_runner deprecated; "
            "use @playwright/mcp MCP server via flax-mcp directly."
        )

    job_spec_path = write_json(root_dir / "browser_job.json", job_payload)
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", "\n".join(checklist_lines) + "\n")
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")

    return BrowserAutomationArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        provenance_template_path=provenance_template_path,
        review_checklist_path=review_checklist_path,
        payload_target_path_file=payload_target_path_file,
        download_target_path=download_target,
    )
