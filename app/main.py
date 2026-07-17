"""FastAPI application: REST endpoints for the presentation training system."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.config import settings
from app.ingestion import PresentationData, ingest_pptx, ingest_pdf
from app.tts import clone_voice, generate_reference_audio, generate_word_audio, get_cloned_voice_id
from app.analysis import analyze_recording

app = FastAPI(title="Presentation Training Coach")

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))

# In-memory session store (swap for Redis/DB in production)
sessions: dict[str, PresentationData] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/upload")
async def upload_presentation(file: UploadFile = File(...)):
    """Upload a PPTX or PDF file, extract slides and scripts."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith(".pptx") or filename_lower.endswith(".pdf")):
        raise HTTPException(400, "Only .pptx and .pdf files are supported")

    save_path = settings.upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if filename_lower.endswith(".pdf"):
        pres = await ingest_pdf(save_path)
    else:
        pres = await ingest_pptx(save_path)
    sessions[pres.id] = pres

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

    result = analyze_recording(
        audio_path=rec_path,
        script=slide.script,
        reference_duration=ref_duration,
    )

    print(
        f"[A/B] pres={presentation_id} slide={slide_index} "
        f"mode={coach_mode} score={result.overall_score}"
    )

    return {
        "transcript": result.transcript,
        "duration_seconds": result.duration_seconds,
        "overall_score": result.overall_score,
        "pacing": asdict(result.pacing),
        "filler_count": result.filler_count,
        "filler_words": result.filler_words,
        "flagged_words": [asdict(fw) for fw in result.flagged_words],
        "coach_mode": coach_mode,
    }


@app.post("/api/pronounce")
async def pronounce_word(
    presentation_id: str = Form(...),
    word: str = Form(...),
):
    """Generate pronunciation audio for a single word."""
    pres = sessions.get(presentation_id)
    if not pres:
        raise HTTPException(404, "Presentation not found")

    try:
        audio_url = await generate_word_audio(word=word, pres_id=pres.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"audio_url": audio_url, "word": word}


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
