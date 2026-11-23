"""Phone-level pronunciation assessment (OpenPronounce phone recognizer + CMU variants).

Each script word is compared with the phones heard for it. A word is flagged when they
differ from every accepted pronunciation (espeak's, OpenPronounce's function-word
alternates and the CMU dictionary's, see ``cmu_variants``): red when its most certain
wrong phone has confidence >= RED_CONFIDENCE, yellow below. Each word also gets its
expected stress (``stress``) and where it is in the recording, for playback.

Long recordings are recognized in chunks cut at quiet points, so memory stays bounded
by the chunk length (wav2vec2's attention grows with the square of the input length).
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from openpronounce import compare_phones, load_audio, phones
from openpronounce.speech import _words as script_words  # same split OpenPronounce uses

from app import cmu_variants
from app.stress import _cmu_with_stress, _espeak_with_stress, expected_stress, syllabify, tts_phonemes

cmu_variants.install()

SAMPLE_RATE = 16000
# wav2vec2 emits one frame of posteriors per 20 ms (320 samples) of audio.
FRAME_SAMPLES = 320
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
# Chunks are cut at the quietest 20 ms in the last SEARCH_SECONDS before CHUNK_SECONDS.
CHUNK_SECONDS = 20
SEARCH_SECONDS = 4
# A flagged word is red when one of its wrong phones has at least this confidence, yellow otherwise.
RED_CONFIDENCE = 0.8
# Margin around a word's phones when cutting it out of the recording, so its edges aren't clipped.
WORD_PADDING_SECONDS = 0.08

# One recognition at a time: two in parallel would double the peak memory.
_inference_lock = threading.Lock()


def load_model() -> None:
    """Load the ~1.2 GB phone model and the CMU dictionary (slow, so done once at startup)."""
    # Under the lock, so a request arriving meanwhile waits instead of loading a second copy
    with _inference_lock:
        phones._load_model()
        cmu_variants._dictionary()


def _cut_points(waveform: np.ndarray) -> list[int]:
    """Sample offsets splitting ``waveform`` into chunks of at most CHUNK_SECONDS + SEARCH_SECONDS.

    Cuts are multiples of FRAME_SAMPLES from the previous cut, so frame times stay aligned.
    """
    chunk, search = CHUNK_SECONDS * SAMPLE_RATE, SEARCH_SECONDS * SAMPLE_RATE
    cuts = [0]
    # Keep the last chunk at least SEARCH_SECONDS long
    while len(waveform) - cuts[-1] > chunk + search:
        lo = cuts[-1] + chunk - search
        window = waveform[lo:lo + search]
        energy = np.square(window).reshape(-1, FRAME_SAMPLES).mean(axis=1)
        cuts.append(lo + int(energy.argmin()) * FRAME_SAMPLES)
    cuts.append(len(waveform))
    return cuts


def _recognize(waveform: np.ndarray) -> phones.PhoneRecognition:
    """``openpronounce.recognize_phones``, with the frame posteriors computed chunk by chunk."""
    cuts = _cut_points(waveform)
    posteriors = [phones.phone_log_posteriors(waveform[a:b]) for a, b in zip(cuts, cuts[1:])]
    processor, _ = phones._load_model()
    return phones.decode_ctc(np.concatenate(posteriors), phones.phone_vocab(), processor.tokenizer.pad_token_id)


def _word_times(recognition, text: str, duration: float) -> dict[int, tuple[float, float]]:
    """Start and end (seconds) of each word in the recording, keyed by word position.

    A word spans the frames of the heard phones aligned with its expected phones; a
    word with no heard phone gets the gap between its neighbours (as OpenPronounce does).
    """
    _, groups = phones.get_expected_phones(text)
    expected = [p for g in groups for p in g]
    alignment = phones._align(expected, recognition.phones)
    n_frames = len(recognition.log_posteriors)
    times, offset = {}, 0
    for position, group in enumerate(groups):
        if not group:
            continue
        indices = range(offset, offset + len(group))
        offset += len(group)
        matched = sorted(set().union(*(alignment[i] for i in indices)))
        if matched:
            start, end = recognition.spans[matched[0]][0], recognition.spans[matched[-1]][1]
        else:
            before = [j for i in range(indices[0]) for j in alignment[i]]
            after = [j for i in range(indices[-1] + 1, len(expected)) for j in alignment[i]]
            start = recognition.spans[max(before)][1] if before else 0
            end = recognition.spans[min(after)][0] if after else n_frames
        times[position] = (round(max(0.0, start * FRAME_SECONDS - WORD_PADDING_SECONDS), 2),
                           round(min(duration, end * FRAME_SECONDS + WORD_PADDING_SECONDS), 2))
    return times


def _assess(recognition, text: str, duration: float) -> dict:
    result = compare_phones(recognition, text)
    # Which accepted pronunciation each word was compared with (see cmu_variants).
    reports_by_position = {r["position"]: r for r in phones._word_reports(recognition, text)}
    times = _word_times(recognition, text, duration)

    words = []
    for i, (word, espeak) in enumerate(zip(script_words(text), result["expected_phones"])):
        report = reports_by_position.get(i)
        matched = report["expected"] if report else espeak
        syllables, stress_source, phonemes = expected_stress(word, matched)
        mispronounced = bool(report) and report["distance"] > 0
        # Confidence of the most certain wrong phone: red when sure, yellow when it may be noise.
        confidence = round(max((p["confidence"] for p in report["phones"]), default=0), 3) if mispronounced else None
        words.append({
            "index": i,
            "word": word,
            "expected": "".join(matched),
            "accepted": list(dict.fromkeys("".join(c) for c in report.get("accepted", [matched]))) if report else [],
            "heard": "".join(report["actual"]) if mispronounced else None,
            "mispronounced": mispronounced,
            "level": ("red" if confidence >= RED_CONFIDENCE else "yellow") if mispronounced else None,
            "confidence": confidence,
            "phones": report["phones"] if report else [],
            "syllables": syllables,  # expected stress only; the recognizer hears none
            "stress_source": stress_source,
            "tts_phonemes": phonemes,  # for the reference audio to say exactly this pronunciation
            "start": times.get(i, (None, None))[0],  # where the word is in the recording (seconds)
            "end": times.get(i, (None, None))[1],
        })

    return {
        "phone_error_rate": result["phone_error_rate"],
        "words": words,
        "duration_seconds": duration,
    }


def assess_pronunciation(audio_path: Path, script: str) -> dict | None:
    """Assess ``audio_path`` against ``script`` word by word; None when it fails."""
    # Curly apostrophes (common in LLM output) are not word characters: "won’t" would split into "won" + "t".
    text = script.replace("’", "'").replace("‘", "'")
    if not text.strip():
        return None
    try:
        waveform = load_audio(str(audio_path))
        with _inference_lock:
            recognition = _recognize(waveform)
        return _assess(recognition, text, round(len(waveform) / SAMPLE_RATE, 2))
    except Exception as e:  # noqa: BLE001 - the rest of the analysis is still useful
        print(f"[WARN] Pronunciation assessment failed: {e}")
        return None


def lookup_word(word: str) -> dict:
    """Pronunciations of a single word with syllables and stress, for the word lookup.

    Every CMU dictionary entry (a heteronym like "record" has one per part of speech),
    or espeak's pronunciation when CMU doesn't have the word.
    """
    entries = cmu_variants._dictionary().get(word.lower(), [])
    if entries:
        pronunciations = [(syllabify(_cmu_with_stress(arpabet)), arpabet) for arpabet in entries]
        source = "cmu"
    else:
        pronunciations = [(syllabify(list(_espeak_with_stress(word))), None)]
        source = "espeak"
    return {
        "word": word,
        "source": source,
        "pronunciations": [
            {"ipa": "".join(syl["ipa"] for syl in syllables), "syllables": syllables,
             "tts_phonemes": tts_phonemes(syllables, arpabet)}
            for syllables, arpabet in pronunciations
        ],
    }


def lookup_text(text: str) -> dict:
    """Pronunciation of what the user looks up: a word (``lookup_word``) or a phrase.

    For a phrase, each word gets the CMU entry closest to espeak's reading of it in the
    phrase, so a heteronym follows its part of speech ("a record" vs "to record").
    """
    words, groups = phones.get_expected_phones(text)
    # espeak's words are lowercased: show the words as the user typed them
    typed = script_words(text)
    if len(typed) == len(words):
        words = typed
    if len(words) == 1:
        return {"kind": "word", **lookup_word(words[0])}
    entries = []
    for word, espeak in zip(words, groups):
        syllables, source, phonemes = expected_stress(word, espeak)
        entries.append({"word": word, "ipa": "".join(syl["ipa"] for syl in syllables), "syllables": syllables,
                        "source": source, "tts_phonemes": phonemes})
    # The phrase is read as typed, punctuation included, for natural intonation
    return {"kind": "phrase", "text": text, "words": entries}
