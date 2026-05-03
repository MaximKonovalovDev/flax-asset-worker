import os
import sys
import json
import asyncio
import logging
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Fallback reliable English voices
DEFAULT_VOICES = {
    "announcer": "en-US-GuyNeural",
    "female_narrator": "en-GB-SoniaNeural",
    "male_narrator": "en-GB-RyanNeural",
    "hero": "en-US-ChristopherNeural"
}

class TtsRunner:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    async def generate_speech(self, text: str, output_filename: str, voice_type: str = "announcer") -> Optional[Path]:
        """
        Generates TTS audio using edge-tts.
        """
        try:
            import edge_tts
        except ImportError:
            logger.error("edge-tts is not installed. Run: pip install edge-tts")
            return None

        voice_id = DEFAULT_VOICES.get(voice_type, DEFAULT_VOICES["announcer"])
        output_path = self.output_dir / output_filename
        
        logger.info(f"Generating TTS (Voice: {voice_id}) -> {output_path}")
        logger.debug(f"Text: {text}")
        
        try:
            communicate = edge_tts.Communicate(text, voice_id)
            await communicate.save(str(output_path))
            logger.info(f"Successfully saved {output_path.name}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to generate TTS: {e}")
            return None

    def generate_batch_sync(self, batch_file: Path) -> List[Path]:
        """
        Synchronous wrapper for batch generation.
        Expects a JSON file with a list of dicts: [{"text": "...", "filename": "...", "voice": "..."}]
        """
        try:
            with open(batch_file, "r", encoding="utf-8") as f:
                jobs = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read batch file: {e}")
            return []
            
        return asyncio.run(self._process_batch(jobs))
        
    async def _process_batch(self, jobs: List[Dict[str, Any]]) -> List[Path]:
        results = []
        for job in jobs:
            text = job.get("text", "")
            filename = job.get("filename", "output.mp3")
            voice = job.get("voice", "announcer")
            if not text:
                continue
                
            path = await self.generate_speech(text, filename, voice)
            if path:
                results.append(path)
        return results

    def generate_single_sync(self, text: str, filename: str, voice: str) -> Optional[Path]:
        return asyncio.run(self.generate_speech(text, filename, voice))
