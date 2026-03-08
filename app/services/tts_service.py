"""
tts_service.py — ElevenLabs TTS for Social Context whisper scripts.

Voice: "Aria" (ElevenLabs) — warm, slightly hushed, clear diction.
      Perfect for whispered social context delivery.

Urgency levels:
  low    → max stability, slow speed — calm, quiet whisper
  medium → balanced — standard context delivery
  high   → faster, slightly less stable — urgent follow-up reminder
"""

import hashlib
import os
import asyncio
from typing import Optional
from services.logger import get_logger

logger = get_logger(__name__)

# ElevenLabs "Aria" — breathy, warm, whisper-appropriate
SOCIAL_VOICE_ID = "9BWtsMINqrJLrRacOk9x"

URGENCY_SETTINGS = {
    "low": {
        "stability": 0.90,
        "similarity_boost": 0.75,
        "style": 0.10,
        "use_speaker_boost": False,
        "speed": 0.90,
    },
    "medium": {
        "stability": 0.75,
        "similarity_boost": 0.80,
        "style": 0.20,
        "use_speaker_boost": False,
        "speed": 1.00,
    },
    "high": {
        "stability": 0.65,
        "similarity_boost": 0.80,
        "style": 0.30,
        "use_speaker_boost": True,
        "speed": 1.10,
    },
}

# MD5-keyed audio cache — keeps frequently used "not in network" responses fast
_cache: dict[str, Optional[str]] = {}
_CACHE_MAX = 200


class SocialTTSService:
    """ElevenLabs TTS for Social Context whisper delivery."""

    def __init__(self):
        self._eleven_client = None

    async def synthesize(self, text: str, urgency: str = "low") -> Optional[str]:
        """
        Synthesize text to base64 MP3 via ElevenLabs.
        Returns None if ElevenLabs is unavailable (caller plays silent or skips TTS).
        """
        cache_key = hashlib.md5(f"{urgency}:{text}".encode()).hexdigest()
        if cache_key in _cache:
            return _cache[cache_key]

        client = self._get_client()
        if client is None:
            logger.warning("elevenlabs_unavailable", text_preview=text[:50])
            return None

        settings = URGENCY_SETTINGS.get(urgency, URGENCY_SETTINGS["low"])

        try:
            import base64
            audio_bytes = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: b"".join(
                    client.text_to_speech.convert(
                        voice_id=SOCIAL_VOICE_ID,
                        text=text,
                        model_id="eleven_turbo_v2_5",
                        voice_settings={
                            "stability": settings["stability"],
                            "similarity_boost": settings["similarity_boost"],
                            "style": settings["style"],
                            "use_speaker_boost": settings["use_speaker_boost"],
                        },
                        output_format="mp3_44100_128",
                    )
                )
            )

            audio_b64 = base64.b64encode(audio_bytes).decode()

            if len(_cache) >= _CACHE_MAX:
                # Evict oldest entry
                _cache.pop(next(iter(_cache)))
            _cache[cache_key] = audio_b64
            return audio_b64

        except Exception as e:
            logger.error("tts_synthesis_failed", error=str(e), urgency=urgency)
            return None

    def _get_client(self):
        if self._eleven_client is not None:
            return self._eleven_client
        try:
            from elevenlabs import ElevenLabs
            api_key = os.getenv("ELEVENLABS_API_KEY")
            if api_key:
                self._eleven_client = ElevenLabs(api_key=api_key)
        except ImportError:
            pass
        return self._eleven_client
