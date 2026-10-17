#!/usr/bin/env python3
"""Stylometric feature extraction shared by analyze.py and score.py.

`features(text)` returns a flat dict of numeric features. Rates are per 1000
words unless noted, so they are comparable across documents of different
length. The feature set is tuned to capture a personal writing fingerprint,
including deliberate quirks (unusual grammar, comma splices, lowercase "i",
typos) — those are part of a voice, not noise.
"""
from __future__ import annotations

import re
from functools import lru_cache

# ---------------------------------------------------------------------------
# word lists (generic English defaults — the writer-specific signal comes from
# the *rates* stored in profile.json, plus signature n-grams derived from the
# writer's own corpus by analyze.py)
# ---------------------------------------------------------------------------

# classic stylometric function words (rate per 1000 words, prefixed "fw_")
FUNCTION_WORDS = [
    "the", "a", "an", "and", "but", "or", "so", "because", "if", "when",
    "of", "to", "in", "on", "for", "with", "as", "at", "by", "from",
    "that", "this", "it", "is", "are", "was", "were", "be", "will", "would",
    "can", "could", "not", "also", "however", "then", "very", "really", "just",
]

# discourse / signposting markers — counted anywhere and at paragraph starts
DISCOURSE_MARKERS = [
    "firstly", "secondly", "thirdly", "lastly", "finally",
    "however", "also", "besides", "moreover", "furthermore",
    "luckily", "unfortunately", "lately", "nowadays", "these days",
    "in conclusion", "on the other hand", "to sum up", "all in all",
    "so", "and also", "for example", "in my opinion", "honestly",
    "basically", "actually", "okay so", "first of all",
]

HEDGES = [
    "probably", "maybe", "perhaps", "for sure", "surely", "somehow",
    "i think", "i believe", "kind of", "sort of", "might", "may", "i guess",
    "to be fair", "honestly", "i feel like",
]

INTENSIFIERS = [
    "really", "very", "extremely", "strongly", "totally", "absolutely",
    "completely", "way", "so", "too", "quite", "a lot", "tons of", "super",
]

# ordinary words that should never be Capitalised mid-sentence (stray-capital
# quirk detector); proper nouns are deliberately absent
COMMON_WORDS = frozenset(
    FUNCTION_WORDS
    + [w for m in DISCOURSE_MARKERS + HEDGES + INTENSIFIERS for w in m.split()]
    + """
    about after again against all almost always another any because been before
    being between both could did does doing down during each even every few
    first good great had has have having her here him his how its just last
    least less like little long made make many more most much must my never
    new next no nor now often old only other our out over own people same
    should since some something still such than their them there these they
    thing things think those though through time today under until up us
    use used using want was way we well what where which while who why with
    without work world would year years you your important different
    possible problem problems idea ideas example place ways life day days
    """.split()
)

# Words and phrases strongly over-represented in LLM output: the focal words of
# Juzek & Ward 2024 (arXiv 2412.11385) and the excess-vocabulary words of Kobak
# et al. 2024/25 (arXiv 2406.07016), plus common assistant clichés. Scored only
# ABOVE the writer's own baseline. The list drifts as models change — dated
# 2026-10, refresh it periodically.
AI_TELL_PATTERNS = [
    r"delv(?:e|es|ed|ing)", r"showcas(?:e|es|ed|ing)", r"underscor(?:e|es|ed|ing)",
    r"intricate(?:ly)?", r"intricac(?:y|ies)", r"pivotal", r"meticulous(?:ly)?",
    r"realms?", r"groundbreaking", r"garner(?:s|ed|ing)?", r"surpass(?:es|ed|ing)?",
    r"tapestry", r"testament", r"boasts", r"commendable", r"multifaceted",
    r"seamless(?:ly)?", r"leverag(?:e|es|ed|ing)", r"foster(?:s|ed|ing)?",
    r"plethora", r"furthermore", r"moreover", r"ever-evolving", r"unwavering",
    r"paramount", r"in today's (?:fast-paced|digital|modern) world",
    r"it(?:'s| is) (?:worth|important to) not(?:e|ing)",
    r"plays? an? (?:crucial|pivotal|vital|key) role", r"(?:stands|serves) as an?",
    r"navigat(?:e|es|ing) the (?:complex|ever)", r"a rich (?:tapestry|history)",
]
_AI_TELL_RE = re.compile(r"\b(?:" + "|".join(AI_TELL_PATTERNS) + r")\b")

# negative parallelism ("not only X but Y", "it's not X, it's Y") — LLMs
# overshoot human rates for this figure
_NEG_PARALLEL_RE = re.compile(
    r"\bnot (?:only|just|merely)\b[^.!?]{0,80}?\bbut\b"
    r"|\bit(?:'s| is) not (?:just |only |merely |about )?[^.!?,]{1,40}, it(?:'s| is)\b"
    r"|\bisn't (?:just|only|merely)\b"
)
# em dashes, plus spaced en dashes / double hyphens used as dashes
_DASH_RE = re.compile(r"—| – | -- ")
# nominalisations — a cheap proxy for the noun-heavy register instruction-tuned
# models favour (Reinhart et al., PNAS 2025; Herbold et al. 2023)
_NOMINAL_RE = re.compile(r"\b[a-z]{3,}(?:tion|sion|ment|ness|ity|ance|ence|ancy|ency)s?\b")

# ---------------------------------------------------------------------------
# tokenisation
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PARA_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]


def split_sentences(text: str) -> list[str]:
    """Sentence split that joins soft-wrapped lines inside a paragraph."""
    out: list[str] = []
    for para in split_paragraphs(text):
        joined = re.sub(r"\s*\n\s*", " ", para)  # unwrap soft line breaks
        for s in _SENT_SPLIT.split(joined):
            s = s.strip()
            if s:
                out.append(s)
    return out


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def _normalize(text: str) -> str:
    # fold typographic apostrophes/quotes so contractions are detected
    return (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )


# ---------------------------------------------------------------------------
# spell checking (optional dependency; degrades gracefully)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _spell():
    try:
        from spellchecker import SpellChecker

        return SpellChecker()
    except Exception:
        return None


def _spelling_deviation_rate(raw_words: list[str], n_words: int) -> float:
    sp = _spell()
    if sp is None:
        return 0.0
    # only check tokens written lowercase (skip Names/ACRONYMS) to reduce noise
    candidates = [w.lower() for w in raw_words if w.islower() and len(w) >= 3]
    if not candidates:
        return 0.0
    unknown = sp.unknown(candidates)
    bad = sum(1 for w in candidates if w in unknown)
    return 1000.0 * bad / n_words


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _phrase_re(phrase: str) -> re.Pattern:
    # whole words only: "so" must not match "some", "a lot" not "a lottery"
    return re.compile(rf"\b{re.escape(phrase)}\b")


def _count_phrases(text_lower: str, phrases) -> int:
    return sum(len(_phrase_re(p).findall(text_lower)) for p in phrases)


def _starts_with_marker(sentence: str, markers) -> bool:
    s = sentence.lower().lstrip("\"'(- ")
    return any(_phrase_re(m).match(s) for m in markers)


def spellchecker_available() -> bool:
    return _spell() is not None


def _cap_anomalies(sentences: list[str], lower_vocab: set[str]) -> list[str]:
    """Mid-sentence Capitalised words that are ordinary words, not names.

    A word counts when its lowercase form is a common English word or appears
    lowercase elsewhere in the same text ("On the other hand, Such lessons").
    Proper nouns ("Tom", "Monday") don't, and neither does a capital right
    after a colon or an opening quote.
    """
    hits = []
    for s in sentences:
        toks = s.split()
        if sum(t[:1].isupper() for t in toks) > len(toks) / 2:
            continue  # a Title Case heading, not a stray capital
        for prev, w in zip(toks, toks[1:]):  # skip the legit sentence-initial word
            if prev.endswith((":", '"', "“")) or w.startswith(('"', "“")):
                continue
            core = w.strip(".,;:!?\"'()[]“”")
            if re.fullmatch(r"[A-Z][a-z]+", core) and (
                core.lower() in COMMON_WORDS or core.lower() in lower_vocab
            ):
                hits.append(core)
    return hits


def ai_tell_hits(text: str) -> list[str]:
    """The AI-tell words/phrases found in text (lowercased, in order)."""
    return [m.group(0) for m in _AI_TELL_RE.finditer(_normalize(text).lower())]


def _mattr(tokens: list[str], window: int = 50) -> float:
    """Moving-average type-token ratio — length-robust vocabulary richness."""
    if not tokens:
        return 0.0
    toks = [t.lower() for t in tokens]
    if len(toks) <= window:
        return len(set(toks)) / len(toks)
    ratios = []
    for i in range(len(toks) - window + 1):
        win = toks[i : i + window]
        ratios.append(len(set(win)) / window)
    return sum(ratios) / len(ratios)


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def features(text: str, signature_ngrams=None) -> dict[str, float]:
    """Extract the feature vector.

    signature_ngrams: the writer's own recurring phrases, derived from their
    corpus by analyze.py and stored in profile.json. Pass the same list when
    scoring a draft so the rates are comparable.
    """
    signature_ngrams = signature_ngrams or []
    text = _normalize(text)
    raw_words = words(text)
    n_words = max(len(raw_words), 1)
    sentences = split_sentences(text)
    n_sent = max(len(sentences), 1)
    paragraphs = split_paragraphs(text)
    n_para = max(len(paragraphs), 1)
    low = text.lower()

    sent_lens = [len(words(s)) for s in sentences]
    mean_sent = sum(sent_lens) / n_sent
    var_sent = sum((x - mean_sent) ** 2 for x in sent_lens) / n_sent
    std_sent = var_sent ** 0.5

    feats: dict[str, float] = {}

    # --- structure -------------------------------------------------------
    feats["mean_sentence_len"] = mean_sent
    feats["std_sentence_len"] = std_sent
    feats["pct_long_sentences"] = 100.0 * sum(1 for x in sent_lens if x > 30) / n_sent
    feats["mean_paragraph_sentences"] = n_sent / n_para
    feats["mean_word_len"] = sum(len(w) for w in raw_words) / n_words
    feats["mattr"] = _mattr(raw_words)

    # --- discourse / openers --------------------------------------------
    feats["discourse_marker_rate"] = (
        1000.0 * _count_phrases(low, DISCOURSE_MARKERS) / n_words
    )
    para_initial = sum(1 for p in paragraphs if _starts_with_marker(p, DISCOURSE_MARKERS))
    feats["pct_para_initial_connective"] = 100.0 * para_initial / n_para
    so_also_and = sum(
        1 for s in sentences if _starts_with_marker(s, ["so", "also", "and"])
    )
    feats["pct_sent_start_so_also_and"] = 100.0 * so_also_and / n_sent
    start_i = sum(1 for s in sentences if re.match(r"\s*I\b", s))
    feats["pct_sent_start_i"] = 100.0 * start_i / n_sent

    # --- punctuation -----------------------------------------------------
    feats["comma_per_sentence"] = text.count(",") / n_sent
    feats["comma_splice_proxy"] = 100.0 * sum(
        1 for s, ln in zip(sentences, sent_lens) if s.count(",") >= 2 and ln > 20
    ) / n_sent
    feats["semicolon_rate"] = 1000.0 * text.count(";") / n_words
    feats["question_rate"] = 1000.0 * text.count("?") / n_words
    feats["exclamation_rate"] = 1000.0 * text.count("!") / n_words

    # --- voice -----------------------------------------------------------
    feats["first_person_rate"] = (
        1000.0
        * _count_phrases(low, ["i", "me", "my", "mine", "we", "our", "us"])
        / n_words
    )
    feats["i_think_rate"] = 1000.0 * _count_phrases(low, ["i think", "i would"]) / n_words
    feats["hedge_rate"] = 1000.0 * _count_phrases(low, HEDGES) / n_words
    feats["intensifier_rate"] = 1000.0 * _count_phrases(low, INTENSIFIERS) / n_words
    feats["signature_ngram_rate"] = (
        1000.0 * _count_phrases(low, signature_ngrams) / n_words
    )

    # --- contractions ----------------------------------------------------
    contractions = len(re.findall(r"\b\w+'(?:t|s|re|ve|ll|d|m)\b", low))
    feats["contraction_rate"] = 1000.0 * contractions / n_words

    # --- quirk markers ---------------------------------------------------
    # lowercase standalone "i" pronoun (not the "i" of "i.e.")
    feats["lowercase_i_rate"] = 1000.0 * len(
        re.findall(r"(?<![A-Za-z.])i(?![A-Za-z']|\.e\.)", text)
    ) / n_words
    # ordinary words Capitalised mid-sentence (stray capitalisation)
    lower_vocab = {w for w in raw_words if w.islower()}
    feats["cap_anomaly_rate"] = (
        1000.0 * len(_cap_anomalies(sentences, lower_vocab)) / n_words
    )
    feats["spelling_deviation_rate"] = _spelling_deviation_rate(raw_words, n_words)

    # --- AI tells (penalised only above the writer's own rate) ------------
    feats["ai_tell_rate"] = 1000.0 * len(_AI_TELL_RE.findall(low)) / n_words
    feats["em_dash_rate"] = 1000.0 * len(_DASH_RE.findall(text)) / n_words
    feats["neg_parallelism_rate"] = 1000.0 * len(_NEG_PARALLEL_RE.findall(low)) / n_words
    feats["nominalization_rate"] = 1000.0 * len(_NOMINAL_RE.findall(low)) / n_words

    # --- function-word vector -------------------------------------------
    from collections import Counter

    counts = Counter(w.lower() for w in raw_words)
    for fw in FUNCTION_WORDS:
        feats[f"fw_{fw}"] = 1000.0 * counts.get(fw, 0) / n_words

    return feats


if __name__ == "__main__":
    import json
    import sys

    src = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()
    print(json.dumps(features(src), indent=2))
