"""Accept every CMU Pronouncing Dictionary pronunciation of a word, not only espeak's.

OpenPronounce compares each word with espeak's single pronunciation plus a short
list of alternates for function words, so valid variants get flagged. ``install()``
adds the CMU pronunciations (and their syllabic-consonant / glottal-t forms) to the
candidates OpenPronounce picks the closest one from.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

import cmudict
import Levenshtein
from openpronounce import phones

ARPABET_TO_IPA = {
    "AA": "ɑ", "AE": "æ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɚ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ",
    "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s",
    "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}
VOWELS = {ARPABET_TO_IPA[v] for v in ("AA", "AE", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY",
                                      "OW", "OY", "UH", "UW")} | {"ə", "ʌ"}


def _to_ipa(arpabet: list[str]) -> list[str]:
    ipa = []
    for symbol in arpabet:
        base, stress = symbol.rstrip("012"), symbol[len(symbol.rstrip("012")):]
        # Unstressed AH is schwa, stressed AH is the STRUT vowel.
        ipa.append("ə" if base == "AH" and stress == "0" else "ʌ" if base == "AH" else ARPABET_TO_IPA[base])
    return ipa


def _reduced_forms(seq: list[str]) -> list[list[str]]:
    """Forms the recognizer also produces: "ə l" -> "əl"/"l̩", "ə n" -> "n̩", "t n̩" -> "ʔ n̩",
    and r-colored vowels as one phone ("ɑ ɹ" -> "ɑɹ"), as espeak and the recognizer write them."""
    rules = [(["ə", "l"], ["əl"]), (["ə", "l"], ["l̩"]), (["ə", "n"], ["n̩"]), (["t", "n̩"], ["ʔ", "n̩"]),
             (["ɑ", "ɹ"], ["ɑɹ"]), (["ɔ", "ɹ"], ["ɔɹ"]), (["ɛ", "ɹ"], ["ɛɹ"]), (["ɪ", "ɹ"], ["ɪɹ"]),
             (["i", "ɹ"], ["ɪɹ"]), (["ʊ", "ɹ"], ["ʊɹ"]), (["u", "ɹ"], ["ʊɹ"]), (["aɪ", "ɚ"], ["aɪɚ"])]
    forms = [seq]
    for old, new in rules:
        for form in list(forms):
            for i in range(len(form) - len(old) + 1):
                after = form[i + len(old)] if i + len(old) < len(form) else None
                # Only before a consonant or at the end: "little", "button", "car", not "hello", "sorry".
                if form[i:i + len(old)] == old and after not in VOWELS:
                    forms.append(form[:i] + new + form[i + len(old):])
    return forms


# Off inside ``disabled()``, to get plain OpenPronounce results for comparison.
_enabled = ContextVar("cmu_variants_enabled", default=True)


@contextmanager
def disabled():
    token = _enabled.set(False)
    try:
        yield
    finally:
        _enabled.reset(token)


@lru_cache(maxsize=1)
def _dictionary() -> dict:
    return cmudict.dict()


@lru_cache(maxsize=8192)
def _cmu_entries(word: str, lang: str = "en") -> tuple[tuple[int, tuple[tuple[str, ...], ...]], ...]:
    """Each CMU entry of ``word`` as (index of the primary-stressed vowel, its normalized forms)."""
    if lang != "en":
        return ()
    entries = []
    for arpabet in _dictionary().get(word.lower(), []):
        vowels = [a for a in arpabet if a[-1].isdigit()]
        primary = next((i for i, a in enumerate(vowels) if a.endswith("1")), -1)
        forms = []
        for form in _reduced_forms(_to_ipa(arpabet)):
            normalized = tuple(phones.normalize_phones(form, lang))
            if normalized not in forms:
                forms.append(normalized)
        entries.append((primary, tuple(forms)))
    return tuple(entries)


def cmu_pronunciations(word: str, lang: str = "en", context: tuple[str, ...] | None = None) -> list[tuple[str, ...]]:
    """CMU pronunciations of ``word`` in OpenPronounce's normalized phones.

    For a heteronym whose entries put the stress on different syllables ("record" noun
    vs verb), only the entries closest to ``context`` are kept: espeak's reading of the
    word in its sentence, which follows the part of speech. Otherwise saying the verb
    where the script has the noun would pass.
    """
    entries = _cmu_entries(word, lang)
    if context is not None and len({primary for primary, _ in entries}) > 1:
        def distance(entry):
            return min(Levenshtein.distance(list(f), list(context)) for f in entry[1])

        best = min(distance(e) for e in entries)
        entries = [e for e in entries if distance(e) == best]
    out = []
    for _, forms in entries:
        out.extend(f for f in forms if f not in out)
    return out


def install() -> None:
    """Make OpenPronounce accept CMU variants in addition to its own candidates."""
    original = phones._pronunciations
    if getattr(original, "with_cmu", False):
        return

    def with_cmu(word, expected_seg, previous_last_phone=None, lang=phones.DEFAULT_LANGUAGE):
        candidates = original(word, expected_seg, previous_last_phone, lang)
        if not _enabled.get():
            return candidates
        for variant in cmu_pronunciations(word, lang, tuple(expected_seg)):
            if list(variant) not in candidates:
                candidates.append(list(variant))
        return candidates

    with_cmu.with_cmu = True
    phones._pronunciations = with_cmu

    original_reports = phones._word_reports

    def with_matched(heard_phones, text_reference, lang=phones.DEFAULT_LANGUAGE):
        """Report each word against the accepted pronunciation it was closest to, not espeak's.

        OpenPronounce already picks that candidate for the per-phone diff but still
        reports espeak's form as ``expected``; this keeps the two consistent and adds
        ``accepted`` (every pronunciation that counts as correct).
        """
        reports = original_reports(heard_phones, text_reference, lang)
        if not _enabled.get():
            return reports
        previous_last_phone = None
        for report in reports:
            espeak = report["expected"]
            candidates = phones._pronunciations(report["word"], espeak, previous_last_phone, lang)
            distances = [Levenshtein.distance(c, report["actual"]) for c in candidates]
            report["expected"] = candidates[distances.index(min(distances))]
            report["accepted"] = candidates
            previous_last_phone = espeak[-1]
        return reports

    phones._word_reports = with_matched
