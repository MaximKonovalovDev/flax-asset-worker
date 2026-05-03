from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


class ClaimMethod(str, Enum):
    FAB_AUTO_REDEEMER = "fab_auto_redeemer"
    FREE_GAMES_CLAIMER = "free_games_claimer"


@dataclass(frozen=True)
class MarketplaceClaimJob:
    method: ClaimMethod
    pack_id: str
    game_scope: str
    source_url: str
    source_adapter: str
    target_filter: str
    account_scope: str
    stash_target: Path
    payload_target: Path
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method.value,
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "source_url": self.source_url,
            "source_adapter": self.source_adapter,
            "target_filter": self.target_filter,
            "account_scope": self.account_scope,
            "stash_target": str(self.stash_target),
            "payload_target": str(self.payload_target),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class MarketplaceClaimArtifacts:
    output_dir: Path
    job_spec_path: Path
    review_checklist_path: Path
    provenance_template_path: Path
    command_template_path: Path
    payload_target_path_file: Path
    stash_target_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "review_checklist_path": str(self.review_checklist_path),
            "provenance_template_path": str(self.provenance_template_path),
            "command_template_path": str(self.command_template_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "stash_target_path": str(self.stash_target_path),
        }


def _command_template(job: MarketplaceClaimJob) -> str:
    if job.method == ClaimMethod.FAB_AUTO_REDEEMER:
        return "\n".join(
            [
                "# FAB Asset Auto Redeemer flow (browser userscript/Tampermonkey)",
                "1) Sign in to Fab with licensed Epic account.",
                "2) Open Fab search page with Free filter.",
                "3) Run script button to bulk claim free assets into account library.",
                "",
                "# After claiming, choose download lane:",
                f'python -m assetboy.cli emit-uevaultmanager-job --pack-id {job.pack_id} --game-scope {job.game_scope} --source-url "{job.source_url}" --vault-item "claimed_free_asset"',
            ]
        ) + "\n"
    return "\n".join(
        [
            "# Free Games Claimer flow (Docker bot)",
            "docker --version",
            "docker compose version",
            "git clone https://github.com/vogler/free-games-claimer.git",
            "cd free-games-claimer",
            "cp config.env.example config.env",
            "# Fill account credentials/tokens in config.env according to project docs.",
            "docker compose up -d",
            "",
            "# After auto-claiming, use normal AssetBoy vault/download flow.",
        ]
    ) + "\n"


def emit_marketplace_claim_job(
    *,
    method: ClaimMethod | str,
    pack_id: str,
    game_scope: str,
    source_url: str = "https://www.fab.com/",
    target_filter: str = "free",
    account_scope: str = "epic_account_primary",
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
) -> MarketplaceClaimArtifacts:
    method_value = ClaimMethod(method)
    source_adapter = "fab_auto_claim" if method_value == ClaimMethod.FAB_AUTO_REDEEMER else "free_games_claimer"
    stash_target = manual_drop_dir() / pack_id / "marketplace_claims"
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "marketplace_ops" / method_value.value / pack_id
    )
    job = MarketplaceClaimJob(
        method=method_value,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        source_adapter=source_adapter,
        target_filter=target_filter,
        account_scope=account_scope,
        stash_target=stash_target,
        payload_target=payload_target,
        notes=notes,
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
    provenance["values"]["download_notes"] = (
        "Marketplace claim automation used only on owned/licensed accounts."
    )

    checklist = "\n".join(
        [
            f"# Marketplace Claim Checklist ({method_value.value})",
            "",
            f"- Pack: `{pack_id}`",
            f"- Game scope: `{game_scope}`",
            f"- Source URL: `{source_url}`",
            f"- Filter: `{target_filter}`",
            f"- Account scope: `{account_scope}`",
            f"- Claim stash target: `{stash_target}`",
            f"- Payload target: `{payload_target}`",
            "",
            "## Policy",
            "- Use only your own licensed accounts.",
            "- Respect store terms and rate limits.",
            "- Keep claim logs and source links for provenance.",
        ]
    ) + "\n"

    job_spec_path = write_json(root_dir / "marketplace_claim_job.json", job.to_dict())
    review_checklist_path = write_text(root_dir / "review_checklist.md", checklist)
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    command_template_path = write_text(root_dir / "commands.txt", _command_template(job))
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")

    return MarketplaceClaimArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        review_checklist_path=review_checklist_path,
        provenance_template_path=provenance_template_path,
        command_template_path=command_template_path,
        payload_target_path_file=payload_target_path_file,
        stash_target_path=stash_target,
    )
