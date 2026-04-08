"""ElevenLabs TTS integration for golden reference audio generation."""

from __future__ import annotations

from pathlib import Path

from app.config import settings

# Voice persona presets: (stability, similarity_boost, style)
VOICE_PRESETS = {
    "professional": {"stability": 0.60, "similarity_boost": 0.75, "style": 0.30},
    "casual": {"stability": 0.40, "similarity_boost": 0.65, "style": 0.50},
    "authoritative": {"stability": 0.75, "similarity_boost": 0.80, "style": 0.20},
    "clone": {"stability": 0.50, "similarity_boost": 0.85, "style": 0.20},
}

# Default ElevenLabs voices
DEFAULT_VOICES = {
    "professional": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "casual": "EXAVITQu4vr4xnSDxMaL",  # Bella
    "authoritative": "ErXwobaYiN019PkySvjV",  # Antoni
}

# In-memory store for cloned voice IDs
cloned_voices: dict[str, str] = {}  # pres_id -> voice_id


def _has_real_key() -> bool:
    key = settings.elevenlabs_api_key
    return bool(key) and not key.startswith("your-")


async def clone_voice(audio_path: Path, pres_id: str, name: str = "My Voice") -> str:
    """Clone a voice from an audio sample using ElevenLabs Instant Voice Cloning.

    Returns the cloned voice ID.
    """
    if not _has_real_key():
        raise ValueError(
            "ELEVENLABS_API_KEY is not configured. Set a valid key in .env to clone a voice."
        )

    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    voice = client.clone(
        name=f"Clone-{name}-{pres_id[:6]}",
        files=[str(audio_path)],
        description="Cloned voice for presentation training",
    )

    cloned_voices[pres_id] = voice.voice_id
    print(f"[INFO] Voice cloned: {voice.voice_id} for pres={pres_id}")
    return voice.voice_id


def get_cloned_voice_id(pres_id: str) -> str | None:
    """Get the cloned voice ID for a presentation, if any."""
    return cloned_voices.get(pres_id)


async def generate_reference_audio(
    script: str,
    pres_id: str,
    slide_index: int,
    persona: str = "professional",
) -> str:
    """Generate golden reference audio for a slide script using ElevenLabs.

    Returns the relative URL path to the generated audio file.
    """
    if not _has_real_key():
        raise ValueError(
            "ELEVENLABS_API_KEY is not configured. Set a valid key in .env to generate reference audio."
        )

    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    if persona == "clone":
        voice_id = cloned_voices.get(pres_id)
        if not voice_id:
            raise ValueError("No cloned voice found. Please upload a voice sample first.")
    else:
        voice_id = DEFAULT_VOICES.get(persona, DEFAULT_VOICES["professional"])
    preset = VOICE_PRESETS.get(persona, VOICE_PRESETS["professional"])

    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=script,
        model_id="eleven_multilingual_v2",
        voice_settings={
            "stability": preset["stability"],
            "similarity_boost": preset["similarity_boost"],
            "style": preset["style"],
            "use_speaker_boost": True,
        },
    )

    # Collect audio bytes
    audio_bytes = b"".join(audio_iter)

    out_dir = settings.audio_dir / pres_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"reference_slide_{slide_index:03d}.mp3"
    out_path = out_dir / filename
    out_path.write_bytes(audio_bytes)

    return f"/static/audio/{pres_id}/{filename}"


async def generate_word_audio(
    word: str,
    pres_id: str,
) -> str:
    """Generate pronunciation audio for a single word.

    Used when the user clicks a flagged word to hear the correct pronunciation.
    """
    if not _has_real_key():
        raise ValueError(
            "ELEVENLABS_API_KEY is not configured. Set a valid key in .env to use pronunciation playback."
        )

    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    # Use a clear, slow delivery for pronunciation
    audio_iter = client.text_to_speech.convert(
        voice_id=DEFAULT_VOICES["professional"],
        text=word,
        model_id="eleven_multilingual_v2",
        voice_settings={
            "stability": 0.85,
            "similarity_boost": 0.90,
            "style": 0.10,
            "use_speaker_boost": True,
        },
    )

    audio_bytes = b"".join(audio_iter)

    out_dir = settings.audio_dir / pres_id / "words"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_word = "".join(c if c.isalnum() else "_" for c in word.lower())
    filename = f"{safe_word}.mp3"
    out_path = out_dir / filename

    # Cache: don't regenerate if already exists
    if not out_path.exists():
        out_path.write_bytes(audio_bytes)

    return f"/static/audio/{pres_id}/words/{filename}"
