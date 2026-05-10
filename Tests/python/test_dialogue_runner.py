import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assetboy.execution.dialogue_runner import DialogueRunResult, _write_provenance


class DialogueRunnerTests(unittest.TestCase):
    def test_provenance_uses_canonical_generator_lane(self) -> None:
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            results = [
                DialogueRunResult(
                    line_id="DIA_TEST",
                    text="Test line",
                    voice_type="announcer",
                    voice_id="en-US-GuyNeural",
                    voice_model="azure_neural_voice",
                    provider="edge_tts",
                    output_path=out_dir / "DIA_TEST.mp3",
                    success=True,
                    provenance_path=out_dir / "provenance.json",
                    metadata_path=out_dir / "DIA_TEST.metadata.json",
                    dry_run=False,
                )
            ]
            provenance_path = _write_provenance(
                out_dir,
                game_scope="roman_arena",
                provider="edge_tts",
                audio_class="voice_npc",
                operator="test_operator",
                results=results,
            )
            payload = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["lane"], "generator")
            self.assertEqual(payload["source_adapter"], "edge_tts_local")
