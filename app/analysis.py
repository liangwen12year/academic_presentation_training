"""Analysis engine: transcription, pronunciation scoring, pacing, filler word detection."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import settings

FILLER_WORDS = {"um", "uh", "uhh", "umm", "er", "ah", "ahh"}

# Whisper model singleton
_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
        )
    return _whisper_model


@dataclass
class WordResult:
    word: str
    start: float
    end: float
    confidence: float


@dataclass
class FlaggedWord:
    word: str  # the expected word
    spoken: str  # what the user actually said
    start: float
    end: float
    confidence: float
    flag: str  # "red" (mispronunciation) or "yellow" (unclear/slurred)
    reason: str


@dataclass
class PacingResult:
    user_wpm: float
    reference_wpm: float
    assessment: str  # "too_fast", "too_slow", "good"
    detail: str


@dataclass
class AnalysisResult:
    transcript: str
    word_results: list[WordResult]
    flagged_words: list[FlaggedWord]
    filler_words: list[dict]
    filler_count: int
    pacing: PacingResult
    duration_seconds: float
    overall_score: float  # 0-100


def transcribe_audio(audio_path: Path) -> tuple[str, list[WordResult], float]:
    """Transcribe audio using faster-whisper with word-level timestamps.

    Returns (full_text, word_results, duration_seconds).
    """
    model = _get_whisper_model()
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language="en",
        repetition_penalty=1.5,
        no_repeat_ngram_size=4,
        condition_on_previous_text=False,
    )

    words: list[WordResult] = []
    full_text_parts: list[str] = []
    duration = 0.0

    for segment in segments:
        full_text_parts.append(segment.text.strip())
        if segment.end > duration:
            duration = segment.end

        if segment.words:
            for w in segment.words:
                words.append(
                    WordResult(
                        word=w.word.strip(),
                        start=w.start,
                        end=w.end,
                        confidence=w.probability,
                    )
                )

    full_text = " ".join(full_text_parts)
    full_text, words = _deduplicate_transcript(full_text, words)

    return full_text, words, duration


def _deduplicate_transcript(text: str, words: list[WordResult]) -> tuple[str, list[WordResult]]:
    """Remove repeated segments from Whisper output."""
    text_words = text.split()
    n = len(text_words)
    if n < 6:
        return text, words

    # Find the longest suffix of the text that matches a prefix
    best = 0
    half = n // 2
    for length in range(3, half + 1):
        suffix = text_words[n - length:]
        prefix = text_words[:length]
        if suffix == prefix:
            best = length

    if best >= 3:
        trimmed = text_words[: n - best]
        text = " ".join(trimmed)
        if words:
            words = words[: len(trimmed)]

    return text, words


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation."""
    return text.lower().translate(str.maketrans("", "", string.punctuation)).strip()


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _align_words(
    script_words: list[str], spoken_words: list[WordResult]
) -> list[tuple[str, WordResult | None]]:
    """Align script words with spoken words using dynamic programming.

    Returns list of (expected_word, matched_spoken_word_or_None).
    """
    n = len(script_words)
    m = len(spoken_words)

    if m == 0:
        return [(w, None) for w in script_words]

    # Build cost matrix
    cost = np.zeros((n + 1, m + 1))
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sw = _normalize(script_words[i - 1])
            uw = _normalize(spoken_words[j - 1].word)
            sub_cost = 0 if sw == uw else _levenshtein_distance(sw, uw) / max(len(sw), len(uw), 1)
            cost[i][j] = min(
                cost[i - 1][j] + 1,  # deletion (word skipped)
                cost[i][j - 1] + 1,  # insertion (extra word spoken)
                cost[i - 1][j - 1] + sub_cost,  # substitution
            )

    # Backtrack
    aligned: list[tuple[str, WordResult | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            sw = _normalize(script_words[i - 1])
            uw = _normalize(spoken_words[j - 1].word)
            sub_cost = 0 if sw == uw else _levenshtein_distance(sw, uw) / max(len(sw), len(uw), 1)

            if cost[i][j] == cost[i - 1][j - 1] + sub_cost:
                aligned.append((script_words[i - 1], spoken_words[j - 1]))
                i -= 1
                j -= 1
            elif cost[i][j] == cost[i - 1][j] + 1:
                aligned.append((script_words[i - 1], None))
                i -= 1
            else:
                j -= 1  # extra spoken word, skip
        elif i > 0:
            aligned.append((script_words[i - 1], None))
            i -= 1
        else:
            j -= 1

    aligned.reverse()
    return aligned


def detect_filler_words(word_results: list[WordResult]) -> list[dict]:
    """Detect filler words in the transcription."""
    fillers = []
    for wr in word_results:
        if _normalize(wr.word) in FILLER_WORDS:
            fillers.append({
                "word": wr.word,
                "start": wr.start,
                "end": wr.end,
            })
    return fillers


def compute_pacing(
    user_duration: float,
    user_word_count: int,
    reference_duration: float | None = None,
    script_word_count: int = 0,
) -> PacingResult:
    """Compute words-per-minute and compare against reference."""
    user_wpm = (user_word_count / user_duration * 60) if user_duration > 0 else 0

    if reference_duration and reference_duration > 0:
        ref_wpm = (script_word_count / reference_duration * 60)
    else:
        ref_wpm = 110.0  # typical academic/professional presentation pace

    ratio = user_wpm / ref_wpm if ref_wpm > 0 else 1.0

    if ratio > 1.45:
        assessment = "a_bit_fast"
        detail = f"You spoke at {user_wpm:.0f} WPM, which is faster than the typical {ref_wpm:.0f} WPM range. Consider slowing down slightly."
    elif ratio < 0.55:
        assessment = "a_bit_slow"
        detail = f"You spoke at {user_wpm:.0f} WPM, which is slower than the typical {ref_wpm:.0f} WPM range. Try picking up the pace a bit."
    else:
        assessment = "good"
        detail = f"Your pace of {user_wpm:.0f} WPM is well within the natural range."

    return PacingResult(
        user_wpm=round(user_wpm, 1),
        reference_wpm=round(ref_wpm, 1),
        assessment=assessment,
        detail=detail,
    )


def analyze_recording(
    audio_path: Path,
    script: str,
    reference_duration: float | None = None,
) -> AnalysisResult:
    """Full analysis pipeline: transcribe, align, score, detect fillers."""
    # 1. Transcribe
    transcript, word_results, duration = transcribe_audio(audio_path)

    # 2. Align with script
    script_words = script.split()
    alignment = _align_words(script_words, word_results)

    # 3. Flag mispronunciations and unclear words
    flagged: list[FlaggedWord] = []
    for expected, spoken in alignment:
        if spoken is None:
            flagged.append(FlaggedWord(
                word=expected,
                spoken="(skipped)",
                start=0, end=0,
                confidence=0,
                flag="red",
                reason="Word was skipped or not spoken.",
            ))
            continue

        expected_norm = _normalize(expected)
        spoken_norm = _normalize(spoken.word)

        if expected_norm == spoken_norm:
            # Correct word — check confidence for clarity
            if spoken.confidence < 0.80:
                flagged.append(FlaggedWord(
                    word=expected,
                    spoken=spoken.word,
                    start=spoken.start,
                    end=spoken.end,
                    confidence=spoken.confidence,
                    flag="yellow",
                    reason=f"Low confidence ({spoken.confidence:.0%}) — word may be slurred or unclear.",
                ))
        else:
            # Different word recognized
            edit_dist = _levenshtein_distance(expected_norm, spoken_norm)
            similarity = 1 - (edit_dist / max(len(expected_norm), len(spoken_norm), 1))

            if similarity > 0.6:
                flagged.append(FlaggedWord(
                    word=expected,
                    spoken=spoken.word,
                    start=spoken.start,
                    end=spoken.end,
                    confidence=spoken.confidence,
                    flag="yellow",
                    reason=f"Recognized as '{spoken.word}' — may be mispronounced or unclear.",
                ))
            else:
                flagged.append(FlaggedWord(
                    word=expected,
                    spoken=spoken.word,
                    start=spoken.start,
                    end=spoken.end,
                    confidence=spoken.confidence,
                    flag="red",
                    reason=f"Mispronunciation: expected '{expected}', heard '{spoken.word}'.",
                ))

    # 4. Filler words
    fillers = detect_filler_words(word_results)

    # 5. Pacing
    pacing = compute_pacing(
        user_duration=duration,
        user_word_count=len(word_results),
        reference_duration=reference_duration,
        script_word_count=len(script_words),
    )

    # 6. Overall score
    total_words = len(script_words)
    red_count = sum(1 for f in flagged if f.flag == "red")
    yellow_count = sum(1 for f in flagged if f.flag == "yellow")
    filler_penalty = min(len(fillers) * 2, 20)
    pacing_penalty = 0 if pacing.assessment == "good" else 10

    # Coverage: what fraction of script words were spoken correctly
    correct_count = total_words - red_count - yellow_count
    coverage = max(0, correct_count / max(total_words, 1))
    # Clarity: penalize unclear words
    clarity = max(0, 1 - (yellow_count / max(total_words, 1)))
    overall = max(0, min(100, coverage * 80 + clarity * 20 - filler_penalty - pacing_penalty))

    return AnalysisResult(
        transcript=transcript,
        word_results=word_results,
        flagged_words=flagged,
        filler_words=fillers,
        filler_count=len(fillers),
        pacing=pacing,
        duration_seconds=round(duration, 2),
        overall_score=round(overall, 1),
    )
