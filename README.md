# Presentation Training Coach

An AI-powered web application for practicing presentation delivery. Upload your PowerPoint slides, listen to a "Golden Reference" reading, record yourself, and receive detailed feedback on pronunciation, pacing, filler words, and overall performance — with an optional animated avatar coach and virtual audience.

## Features

### Core Workflow

1. **Upload PPTX** — Drag-and-drop or browse for a `.pptx` file. The app extracts slide images (composited from embedded pictures or rendered as text placeholders), speaker notes, and generates scripts via LLM when notes are missing.

2. **Golden Reference Audio** — Generate a reference reading for any slide using ElevenLabs TTS (or browser speech synthesis as a fallback). Choose from three voice personas:
   - **Professional** — Steady, clear delivery
   - **Casual** — Relaxed, conversational tone
   - **Authoritative** — Confident, commanding presence

3. **Record & Analyze** — Record yourself reading the slide script. The backend transcribes your audio with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (word-level timestamps + confidence scores), then runs a full analysis pipeline:
   - **Pronunciation scoring** — Levenshtein-based alignment of your transcript against the script. Words are flagged red (mispronunciation/skipped) or yellow (low confidence/unclear).
   - **Pacing analysis** — Words-per-minute compared against the reference or a 130 WPM baseline. Assessed as "good," "too fast," or "too slow."
   - **Filler word detection** — Catches "um," "uh," "like," "you know," "basically," "actually," "literally," and others.
   - **Overall score** — Weighted composite of accuracy (50%), clarity (30%), base (20%), minus penalties for fillers and pacing.

4. **Pronunciation Playback** — Click any flagged word to hear the correct pronunciation via ElevenLabs TTS (or browser TTS fallback).

### Dynamic Avatar Coach

Toggle between **Voice Only** and **Avatar Coach** mode via the header. The avatar is a canvas-rendered, stylized character (intentionally cartoon-like to avoid uncanny valley) with smooth lerp-based animation.

**Avatar states:**

| State | Trigger | Visual |
|-------|---------|--------|
| Idle | Default | Breathing, periodic blinking |
| Listening | During recording | Wider eyes, slight head tilt, attentive gaze |
| Thinking | During analysis | Eyes look up-right, animated bouncing dots |
| Speaking | During TTS playback | Lip-sync simulation (oscillating mouth) |
| Encouraging | Score >= 70 | Wide smile, head nods, blush |
| Concerned | Score < 70 | Slight frown, raised inner eyebrows |
| Pause Warning | Long silence detected | Wide eyes, head tilt, "Keep going!" label |
| Pace Warning | Speaking too fast | Wincing expression |
| Filler Warning | Filler word detected | Raised eyebrow |
| Celebrating | New personal best | Big smile, blush, confetti from audience |
| Demonstrating | Pronunciation playback | Focused expression, mouth mirrors audio |

### Virtual Audience

When Avatar Coach mode is active, a panel of 5 audience members appears below the coach avatar. Each member has:

- **Independent personality** — Different skin/hair colors, blink intervals, fidget thresholds
- **Attention system** — Attentive members look at the "speaker" (center), distracted members' eyes wander
- **Fidgeting** — Low-attention members shift and tilt their heads
- **Nodding** — Attentive members occasionally nod along during good delivery
- **Engagement bar** — Collective engagement level (0–100%) displayed visually

**Audience reacts to your delivery:**
- Good energy/pace → engagement rises, more nodding
- Long pauses → engagement drops
- Fast/slow pace → engagement drops
- New personal best → confetti celebration, all members smile

### Real-time Coaching

During recording, a live feedback panel appears showing:

- **Pace indicator** — Estimated WPM via amplitude peak detection (Good / Too Fast / Too Slow)
- **Energy bar** — Real-time volume level
- **Filler counter** — Live count using the Web Speech API for real-time transcription
- **Alert toasts** — Brief notifications for pauses, fillers, and pace issues

The avatar and audience respond to these events in real time (e.g., avatar shows concern during long pauses, audience engagement drops).

### Post-Analysis Spoken Coaching

After analysis, the avatar speaks a comprehensive feedback summary covering:
- Encouraging/coaching message based on your history
- Pacing assessment with specific WPM numbers
- Filler word count and advice
- Pronunciation issue count with direction to click flagged words

### Session Tracking & Gamification

Progress persists across sessions via `localStorage`:

- **Practice streak** — Consecutive days of practice
- **Personal best** — Highest score with celebration animation
- **Progressive difficulty** — Levels based on average score:
  - Beginner (avg < 70)
  - Intermediate (avg 70–85)
  - Expert (avg 85+)
- **Improvement tracking** — Compares recent 3 sessions vs. previous 3
- **Encouraging messages** — Context-aware based on streaks, improvement trends, difficulty level

Stats displayed in a sidebar card: total sessions, day streak, best score, average score, difficulty badge.

### A/B Comparison

Each analysis logs the `coach_mode` (avatar vs. no-avatar) to the server console for comparison studies:
```
[A/B] pres=abc123 slide=0 mode=avatar score=82.5
```

## Architecture

```
training/
├── app/
│   ├── main.py          # FastAPI app, REST endpoints
│   ├── config.py         # Pydantic settings (env vars, paths)
│   ├── ingestion.py      # PPTX parsing, slide image export, LLM script gen
│   ├── analysis.py       # Whisper transcription, alignment, scoring
│   └── tts.py            # ElevenLabs TTS for reference audio & pronunciation
├── static/
│   ├── css/style.css     # Full UI styling
│   └── js/
│       ├── app.js             # Main application logic, state management
│       ├── avatar.js          # Canvas-based animated avatar (coach)
│       ├── audience.js        # Virtual audience (5 members, engagement system)
│       ├── realtime-coach.js  # Live audio analysis (pace, pauses, fillers)
│       └── session-tracker.js # localStorage persistence, streaks, difficulty
├── templates/
│   └── index.html        # Single-page application
├── uploads/              # Uploaded PPTX files (gitignored)
├── requirements.txt      # Python dependencies
├── run.py                # Entry point (uvicorn with hot reload)
├── .env.example          # Environment variable template
└── .gitignore
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve the SPA |
| POST | `/api/upload` | Upload and parse PPTX |
| POST | `/api/generate-reference` | Generate reference audio for one slide |
| POST | `/api/generate-all-references` | Generate reference audio for all slides |
| POST | `/api/analyze` | Submit recording for analysis |
| POST | `/api/pronounce` | Generate pronunciation audio for a word |
| PUT | `/api/script` | Update a slide's script |
| GET | `/api/session/{id}` | Get session data |

## Setup

### Prerequisites

- Python 3.10+ (tested on 3.13)
- A microphone (for recording)
- A modern browser with Web Speech API support (Chrome recommended for real-time filler detection)

### Installation

```bash
# Clone and enter the project
cd training

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `ELEVENLABS_API_KEY` | Optional | ElevenLabs API key for high-quality TTS. Falls back to browser speech synthesis if not set. |
| `OPENAI_API_KEY` | Optional | OpenAI key for generating scripts when slides lack speaker notes. Falls back to slide text. |
| `GOOGLE_API_KEY` | Optional | Alternative to OpenAI — Google Gemini for script generation. |
| `LLM_PROVIDER` | Optional | `"openai"` (default) or `"gemini"` |
| `WHISPER_MODEL` | Optional | Whisper model size: `tiny`, `base` (default), `small`, `medium`, `large`. Larger = more accurate but slower. |

**The app works with zero API keys** — it degrades gracefully with the following fallback behavior:

| Feature | With Valid API Key | Without Valid API Key |
|---------|-------------------|----------------------|
| **Script Generation** | LLM generates a natural speaker script from slide content (OpenAI GPT-4o-mini or Google Gemini) | Uses raw slide text as the script; if a slide has no text, defaults to "This is slide N." |
| **Golden Reference Audio** | High-quality ElevenLabs TTS with selectable voice personas (Professional, Casual, Authoritative) | Falls back to browser's built-in `SpeechSynthesis` API (voice quality varies by browser/OS). If the browser lacks `SpeechSynthesis`, an alert prompts the user to configure `ELEVENLABS_API_KEY`. |
| **Pronunciation Playback** | Click a flagged word to hear correct pronunciation via ElevenLabs TTS | Falls back to browser `SpeechSynthesis`. If unavailable, pronunciation playback is disabled. |
| **Recording & Analysis** | Fully functional — uses local Whisper model (no API key needed) | Same — Whisper runs locally, no external API required |
| **Avatar Coach & Audience** | Fully functional — runs entirely client-side | Same — no API dependency |
| **Real-time Coaching** | Fully functional — uses Web Audio API and Web Speech API | Same — no API dependency |

> **Note:** A key is considered invalid if it is empty, unset, or starts with `your-` (the placeholder value from `.env.example`). Invalid keys are treated the same as missing keys — the app silently falls back rather than sending bad requests to external APIs.

### Running

```bash
python run.py
```

Open `http://localhost:8000` in your browser.

The server runs with hot reload enabled, so code changes take effect automatically. Upload/audio/slide directories are excluded from reload watching.

## Usage Guide

1. **Upload** — Drop a `.pptx` file onto the upload area
2. **Review script** — Edit the auto-generated script in the text area if needed
3. **Toggle mode** — Click "Avatar Coach" in the header to enable the avatar and virtual audience
4. **Generate reference** — Click "Generate for This Slide" to hear how it should sound
5. **Record** — Click "Start Recording" and read the script aloud
   - Watch the real-time feedback panel for pace, energy, and filler alerts
   - The avatar reacts to your delivery in real time
   - The virtual audience engagement responds to your energy
6. **Analyze** — Click "Analyze Recording" to get full results
   - The avatar speaks a coaching summary
   - Click flagged words to hear correct pronunciation
   - Check your progress in the "Your Progress" stats card
7. **Iterate** — Navigate between slides and repeat. Track your streak and aim to beat your personal best.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Uvicorn |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, CPU int8) |
| Text-to-speech | ElevenLabs API / Browser SpeechSynthesis |
| PPTX parsing | python-pptx + Pillow |
| Script generation | OpenAI GPT-4o-mini / Google Gemini 1.5 Flash |
| Word alignment | Dynamic programming with Levenshtein distance |
| Avatar rendering | HTML5 Canvas 2D (procedural drawing, 60fps) |
| Real-time analysis | Web Audio API (AnalyserNode) + Web Speech API |
| Session persistence | localStorage |
| Styling | Custom CSS with CSS custom properties |

## Research Background

The avatar and audience design is informed by recent HCI research (2024–2025):

- **Stylized over photorealistic**: Cartoon-like avatars score lower on uncanny valley measures (DIS '24 survey of 266 papers)
- **Dynamic > Static > None**: For coaching/tutoring contexts, animated agents improve social presence and engagement
- **Audience simulation**: Virtual audiences provide realistic social pressure without paralyzing anxiety
- **Nonverbal scaffolding**: Animated cues (listening, nodding, concern) guide pacing and reduce awkwardness during latency
- **LLM quality compensates**: Strong conversational quality reduces eeriness perception even with imperfect visuals (arXiv '25)

The A/B mode toggle (Voice Only vs. Avatar Coach) allows controlled comparison of engagement, trust, cognitive load, and objective speaking improvement.
