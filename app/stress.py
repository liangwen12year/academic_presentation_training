"""Expected lexical stress per word, split into syllables.

The phone recognizer hears no stress, so this only says where the stress *should*
be (for display now, and as the target for a later stress detector). It comes
from the CMU pronunciation that matched what was heard (vowels carry 0/1/2), or
from espeak with stress marks for words CMU doesn't have ("LiDAR", "KITTI").
"""

from functools import lru_cache

import Levenshtein
from openpronounce import phones
from phonemizer import phonemize
from phonemizer.separator import Separator

from app.cmu_variants import _dictionary, _reduced_forms, _to_ipa

VOWEL_CHARS = set("aeiouæɑɒɔəɛɜɪʊʌɚɐᵻøyœ")
SYLLABIC_MARK = "̩"  # n̩, l̩

# Consonant clusters English allows at the start of a syllable (maximal onset principle).
LEGAL_ONSETS = {
    ("p", "l"), ("b", "l"), ("k", "l"), ("ɡ", "l"), ("f", "l"), ("s", "l"),
    ("p", "ɹ"), ("b", "ɹ"), ("t", "ɹ"), ("d", "ɹ"), ("k", "ɹ"), ("ɡ", "ɹ"), ("f", "ɹ"), ("θ", "ɹ"), ("ʃ", "ɹ"),
    ("t", "w"), ("d", "w"), ("k", "w"), ("s", "w"), ("ɡ", "w"),
    ("s", "p"), ("s", "t"), ("s", "k"), ("s", "m"), ("s", "n"),
    ("p", "j"), ("b", "j"), ("k", "j"), ("m", "j"), ("f", "j"), ("v", "j"), ("h", "j"),
    ("s", "p", "l"), ("s", "p", "ɹ"), ("s", "t", "ɹ"), ("s", "k", "ɹ"), ("s", "k", "w"), ("s", "k", "j"),
}


def _is_nucleus(phone: str) -> bool:
    return SYLLABIC_MARK in phone or any(c in VOWEL_CHARS for c in phone)


def _is_legal_onset(cluster: tuple[str, ...]) -> bool:
    return (len(cluster) <= 1 and cluster != ("ŋ",)) or cluster in LEGAL_ONSETS


def syllabify(phone_stress: list[tuple[str, int | None]]) -> list[dict]:
    """Group ``(phone, stress)`` pairs into syllables: ``[{"ipa": "teɪ", "stress": 1}, ...]``."""
    nuclei = [i for i, (p, _) in enumerate(phone_stress) if _is_nucleus(p)]
    if not nuclei:
        return [{"ipa": "".join(p for p, _ in phone_stress), "stress": 0}]

    # Syllable i starts at starts[i]; the consonants between two nuclei go to the
    # next syllable's onset as far as English allows, the rest to the previous coda.
    starts = [0]
    for prev, nxt in zip(nuclei, nuclei[1:]):
        cluster = [p for p, _ in phone_stress[prev + 1:nxt]]
        onset = 0
        for k in range(len(cluster) + 1):
            if _is_legal_onset(tuple(cluster[len(cluster) - k:])):
                onset = k
        starts.append(nxt - onset)
    ends = starts[1:] + [len(phone_stress)]

    return [
        {"ipa": "".join(p for p, _ in phone_stress[s:e]), "stress": phone_stress[n][1] or 0}
        for s, e, n in zip(starts, ends, nuclei)
    ]


def _cmu_with_stress(arpabet: list[str]) -> list[tuple[str, int | None]]:
    out = []
    for symbol, ipa in zip(arpabet, _to_ipa(arpabet)):
        digit = symbol[-1]
        out.append((ipa, int(digit) if digit.isdigit() else None))
    return out


@lru_cache(maxsize=8192)
def _espeak_with_stress(word: str) -> tuple[tuple[str, int | None], ...]:
    out = phonemize(word.lower(), language="en-us", backend="espeak", strip=True, with_stress=True,
                    separator=Separator(phone=" ", word="", syllable=""))
    pairs = []
    for token in out.split():
        stress = 1 if "ˈ" in token else 2 if "ˌ" in token else 0
        phone = token.replace("ˈ", "").replace("ˌ", "").replace("ː", "")
        if phone:
            pairs.append((phone, stress if _is_nucleus(phone) else None))
    return tuple(pairs)


def expected_stress(word: str, matched: list[str]) -> tuple[list[dict], str]:
    """Syllables with stress for ``word``, and where the stress came from ("cmu" or "espeak").

    ``matched`` is the accepted pronunciation the word was compared with; when CMU
    lists several (e.g. "either"), the one closest to it is used.
    """
    entries = _dictionary().get(word.lower(), [])
    if entries:
        def distance(arpabet):
            forms = [phones.normalize_phones(f) for f in _reduced_forms(_to_ipa(arpabet))]
            return min(Levenshtein.distance(f, matched) for f in forms)

        best = min(entries, key=distance)
        return syllabify(_cmu_with_stress(best)), "cmu"
    return syllabify(list(_espeak_with_stress(word))), "espeak"
