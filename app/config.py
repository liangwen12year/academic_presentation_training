from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    elevenlabs_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    llm_provider: str = "openai"  # "openai" or "gemini"
    whisper_model: str = "base"  # tiny, base, small, medium, large

    # Set SPEAKER_SCRIPT_PROMPT_PATH to enable image-based script generation.
    # A relative path is resolved from base_dir when the presentation is read.
    speaker_script_prompt_path: Path | None = None
    speaker_script_model: str = "gpt-5.4-mini"
    speaker_script_reasoning_effort: str | None = None
    speaker_script_max_output_tokens: int = 1600

    base_dir: Path = Path(__file__).resolve().parent.parent
    upload_dir: Path = base_dir / "uploads"
    static_dir: Path = base_dir / "static"
    audio_dir: Path = static_dir / "audio"
    slides_dir: Path = static_dir / "slides"
    data_dir: Path = base_dir / "data"

    class Config:
        env_file = ".env"
        extra = "ignore"

    def ensure_dirs(self) -> None:
        for d in (self.upload_dir, self.audio_dir, self.slides_dir, self.data_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
