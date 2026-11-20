"""FastAPI application: REST endpoints for the presentation training system."""

from __future__ import annotations

import asyncio
import ctypes
import gc
import json
import re
import shutil
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.config import settings
from app.ingestion import PresentationData, ingest_pptx, ingest_pdf
from app.tts import (
    clone_voice,
    generate_phrase_audio,
    generate_reference_audio,
    generate_word_audio,
    get_cloned_voice_id,
)
from app.analysis import analyze_recording
from app.cmu_variants import ARPABET_TO_IPA
from app.pronunciation import assess_pronunciation, load_model as load_pronunciation_model, lookup_word

app = FastAPI(title="Presentation Training Coach")


@app.on_event("startup")
async def preload_pronunciation_model() -> None:
    # Loading takes a while; do it in the background so the server starts answering right away
    threading.Thread(target=load_pronunciation_model, daemon=True).start()

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))

# In-memory session store (swap for Redis/DB in production)
sessions: dict[str, PresentationData] = {}
upload_jobs: dict[str, dict] = {}
upload_jobs_lock = threading.Lock()
# One analysis at a time: with one CPU, parallel runs aren't faster, and their
# memory peaks (Whisper + the phone model) would add up past the 2 GB instance.
analysis_lock = asyncio.Lock()


def _release_memory() -> None:
    """Return memory freed by an analysis to the OS, so it doesn't creep up across requests."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):  # not glibc (e.g. macOS during development)
        pass


def _presentation_response(pres: PresentationData) -> dict:
    """Serialize presentation data returned after an upload completes."""
    return {
        "presentation_id": pres.id,
        "filename": pres.filename,
        "slide_count": len(pres.slides),
        "slides": [
            {
                "index": s.index,
                "id": s.id,
                "image_url": s.image_path,
                "has_notes": bool(s.notes),
                "script": s.script,
            }
            for s in pres.slides
        ],
    }


def _update_upload_job(job_id: str, **updates) -> None:
    with upload_jobs_lock:
        upload_jobs[job_id].update(updates)


def _run_ingestion(
    save_path: Path,
    is_pdf: bool,
    progress_callback: Callable[[int, int, str], None],
) -> PresentationData:
    ingest = ingest_pdf if is_pdf else ingest_pptx
    return asyncio.run(ingest(save_path, progress_callback))


async def _process_upload_job(job_id: str, save_path: Path, is_pdf: bool) -> None:
    """Run slide ingestion off the event loop while exposing progress to the client."""
    def report(completed: int, total: int, message: str) -> None:
        progress = 10 if not total else 10 + int((completed / total) * 85)
        _update_upload_job(
            job_id,
            status="processing",
            progress=progress,
            message=message,
            completed=completed,
            total=total,
        )

    try:
        presentation = await asyncio.to_thread(_run_ingestion, save_path, is_pdf, report)
        sessions[presentation.id] = presentation
        _update_upload_job(
            job_id,
            status="completed",
            progress=100,
            message="Slides are ready",
            presentation_id=presentation.id,
            completed=1,
            total=1,
        )
    except Exception as exc:
        print(f"[ERROR] Upload processing failed: {exc}")
        _update_upload_job(
            job_id,
            status="failed",
            message="Unable to process this presentation",
            error=str(exc),
        )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/upload")
async def upload_presentation(file: UploadFile = File(...)):
    """Start asynchronous PPTX or PDF processing and return a job identifier."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith(".pptx") or filename_lower.endswith(".pdf")):
        raise HTTPException(400, "Only .pptx and .pdf files are supported")

    save_path = settings.upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job_id = uuid.uuid4().hex
    with upload_jobs_lock:
        upload_jobs[job_id] = {
            "status": "queued",
            "progress": 5,
            "message": "Preparing your presentation",
        }
    asyncio.create_task(_process_upload_job(job_id, save_path, filename_lower.endswith(".pdf")))
    return {"job_id": job_id}


@app.get("/api/upload/{job_id}")
async def get_upload_status(job_id: str):
    """Return the current upload-processing state and final presentation data."""
    with upload_jobs_lock:
        job = upload_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Upload job not found")
        result = dict(job)

    if result["status"] == "completed":
        presentation_id = result.pop("presentation_id")
        presentation = sessions.get(presentation_id)
        if not presentation:
            raise HTTPException(404, "Processed presentation not found")
        result["presentation"] = _presentation_response(presentation)

    return result


@app.post("/api/clone-voice")
async def clone_voice_endpoint(
    presentation_id: str = Form(...),
    audio: UploadFile = File(...),
    name: str = Form("My Voice"),
):
    """Upload a voice sample to create a cloned voice persona."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    # Save the voice sample
    clone_dir = settings.audio_dir / pres.id / "clone"
    clone_dir.mkdir(parents=True, exist_ok=True)
    sample_path = clone_dir / f"voice_sample_{audio.filename}"
    with open(sample_path, "wb") as f:
        shutil.copyfileobj(audio.file, f)

    try:
        voice_id = await clone_voice(sample_path, pres.id, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Voice cloning failed: {str(e)}")

    return {"voice_id": voice_id, "name": name}


@app.get("/api/clone-voice-status/{presentation_id}")
async def clone_voice_status(presentation_id: str):
    """Check if a cloned voice exists for this presentation."""
    voice_id = get_cloned_voice_id(presentation_id)
    return {"has_clone": voice_id is not None}


@app.post("/api/generate-reference")
async def gen_reference(
    presentation_id: str = Form(...),
    slide_index: int = Form(...),
    persona: str = Form("professional"),
):
    """Generate golden reference audio for a specific slide."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    if slide_index < 0 or slide_index >= len(pres.slides):
        raise HTTPException(400, "Invalid slide index")

    slide = pres.slides[slide_index]

    try:
        audio_url = await generate_reference_audio(
            script=slide.script,
            pres_id=pres.id,
            slide_index=slide_index,
            persona=persona,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    slide.reference_audio_path = audio_url

    return {"audio_url": audio_url, "slide_index": slide_index}


@app.post("/api/generate-all-references")
async def gen_all_references(
    presentation_id: str = Form(...),
    persona: str = Form("professional"),
):
    """Generate golden reference audio for all slides."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    results = []
    try:
        for slide in pres.slides:
            audio_url = await generate_reference_audio(
                script=slide.script,
                pres_id=pres.id,
                slide_index=slide.index,
                persona=persona,
            )
            slide.reference_audio_path = audio_url
            results.append({"slide_index": slide.index, "audio_url": audio_url})
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"results": results}


@app.post("/api/analyze")
async def analyze(
    presentation_id: str = Form(...),
    slide_index: int = Form(...),
    audio: UploadFile = File(...),
    coach_mode: str = Form("no-avatar"),
):
    """Submit a user recording for analysis against the slide script."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    if slide_index < 0 or slide_index >= len(pres.slides):
        raise HTTPException(400, "Invalid slide index")

    slide = pres.slides[slide_index]

    # Save user audio
    rec_dir = settings.audio_dir / pres.id / "recordings"
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec_path = rec_dir / f"user_slide_{slide_index:03d}.webm"
    with open(rec_path, "wb") as f:
        shutil.copyfileobj(audio.file, f)

    # Get reference duration if available
    ref_duration = None
    if slide.reference_audio_path:
        ref_audio_path = settings.base_dir / slide.reference_audio_path.lstrip("/")
        if ref_audio_path.exists():
            try:
                import librosa

                y, sr = librosa.load(str(ref_audio_path))
                ref_duration = librosa.get_duration(y=y, sr=sr)
            except Exception:
                pass

    # One after the other: both are CPU-bound and running them together would raise peak memory
    async with analysis_lock:
        try:
            result = await asyncio.to_thread(analyze_recording, rec_path, slide.script, ref_duration)
            pronunciation = await asyncio.to_thread(assess_pronunciation, rec_path, slide.script)
        finally:
            _release_memory()

    print(
        f"[A/B] pres={presentation_id} slide={slide_index} "
        f"mode={coach_mode} score={result.overall_score}"
    )

    return {
        "transcript": result.transcript,
        "duration_seconds": result.duration_seconds,
        "overall_score": result.overall_score,
        "coverage_percent": result.coverage_percent,
        "clarity_percent": result.clarity_percent,
        "pacing": asdict(result.pacing),
        "filler_count": result.filler_count,
        "filler_words": result.filler_words,
        "flagged_words": [asdict(fw) for fw in result.flagged_words],
        "pronunciation": pronunciation,
        "coach_mode": coach_mode,
    }


@app.post("/api/pronounce")
async def pronounce_word(
    presentation_id: str = Form(...),
    word: str = Form(...),
    alphabet: str | None = Form(None),
    ph: str | None = Form(None),
):
    """Generate pronunciation audio for a single word, read as ``ph`` when given."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    phonemes = None
    if alphabet and ph:
        valid = (
            all(re.fullmatch(r"[A-Z]{1,2}[012]?", t) and t.rstrip("012") in ARPABET_TO_IPA for t in ph.split())
            if alphabet == "cmu-arpabet"
            else alphabet == "ipa" and len(ph) <= 80 and not re.search(r"[<>&\"\s]", ph)
        )
        if not valid:
            raise HTTPException(400, "Invalid phonemes")
        phonemes = {"alphabet": alphabet, "ph": ph}

    try:
        audio_url = await generate_word_audio(word=word, pres_id=pres.id, phonemes=phonemes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"audio_url": audio_url, "word": word}


@app.post("/api/pronounce-phrase")
async def pronounce_phrase(presentation_id: str = Form(...), text: str = Form(...)):
    """Generate reference audio for a phrase around mispronounced words."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    text = " ".join(text.split())
    if not text or len(text) > 300:
        raise HTTPException(400, "Phrase must be 1-300 characters")

    try:
        audio_url = await generate_phrase_audio(text=text, pres_id=pres.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"audio_url": audio_url}


@app.get("/api/word-pronunciation")
def word_pronunciation(word: str):
    """Phonemes, syllables and stress of a word the user looks up."""
    word = word.strip().replace("\u2019", "'")
    if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]{0,40}", word):
        raise HTTPException(400, "Enter a single English word")
    return lookup_word(word)


@app.post("/api/speak-feedback")
async def speak_feedback(
    presentation_id: str = Form(...),
    text: str = Form(...),
):
    """Generate spoken feedback audio using ElevenLabs TTS."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    try:
        from app.tts import _has_real_key, DEFAULT_VOICES
        if not _has_real_key():
            raise HTTPException(400, "ELEVENLABS_API_KEY not configured")

        from elevenlabs.client import ElevenLabs as ELClient
        client = ELClient(api_key=settings.elevenlabs_api_key)

        audio_iter = client.text_to_speech.convert(
            voice_id=DEFAULT_VOICES["professional"],
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.55,
                "similarity_boost": 0.75,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        )
        audio_bytes = b"".join(audio_iter)

        out_dir = settings.audio_dir / pres.id
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = "feedback_audio.mp3"
        out_path = out_dir / filename
        out_path.write_bytes(audio_bytes)

        return {"audio_url": f"/static/audio/{pres.id}/{filename}"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/self-rating")
async def submit_self_rating(
    presentation_id: str = Form(...),
    slide_index: int = Form(...),
    overall: int = Form(...),
    confidence: int = Form(...),
    ai_score: float = Form(...),
):
    """Save a user's self-assessment rating alongside the AI score."""
    ratings_file = settings.data_dir / "self_ratings.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "presentation_id": presentation_id,
        "slide_index": slide_index,
        "self_overall": overall,
        "self_confidence": confidence,
        "ai_score": ai_score,
    }

    with open(ratings_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return {"ok": True}


@app.get("/api/ratings")
async def get_ratings():
    """Retrieve all self-assessment ratings (for study analysis)."""
    ratings_file = settings.data_dir / "self_ratings.jsonl"
    if not ratings_file.exists():
        return {"ratings": []}

    ratings = []
    for line in ratings_file.read_text().strip().split("\n"):
        if line:
            ratings.append(json.loads(line))

    return {"ratings": ratings}


@app.get("/api/session/{presentation_id}")
async def get_session(presentation_id: str):
    """Get current session data."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    return {
        "presentation_id": pres.id,
        "filename": pres.filename,
        "slide_count": len(pres.slides),
        "slides": [
            {
                "index": s.index,
                "id": s.id,
                "image_url": s.image_path,
                "has_notes": bool(s.notes),
                "script": s.script,
                "reference_audio_url": s.reference_audio_path,
            }
            for s in pres.slides
        ],
    }


@app.put("/api/script")
async def update_script(
    presentation_id: str = Form(...),
    slide_index: int = Form(...),
    script: str = Form(...),
):
    """Allow user to edit the script for a slide."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    if slide_index < 0 or slide_index >= len(pres.slides):
        raise HTTPException(400, "Invalid slide index")

    pres.slides[slide_index].script = script
    return {"ok": True, "slide_index": slide_index}
