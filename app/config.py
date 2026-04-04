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

    base_dir: Path = Path(__file__).resolve().parent.parent
    upload_dir: Path = base_dir / "uploads"
    static_dir: Path = base_dir / "static"
    audio_dir: Path = static_dir / "audio"
    slides_dir: Path = static_dir / "slides"

    class Config:
        env_file = ".env"
        extra = "ignore"

    def ensure_dirs(self) -> None:
        for d in (self.upload_dir, self.audio_dir, self.slides_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
