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


def _count_phrases(text_lower: str, phrases) -> int:
    total = 0
    for p in phrases:
        if " " in p:
            total += text_lower.count(p)
        else:
            total += len(re.findall(rf"\b{re.escape(p)}\b", text_lower))
    return total


def _starts_with_marker(sentence: str, markers) -> bool:
    s = sentence.lower().lstrip("\"'(- ")
    return any(s.startswith(m) for m in markers)


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
    # lowercase standalone "i" pronoun
    feats["lowercase_i_rate"] = 1000.0 * len(
        re.findall(r"(?<![A-Za-z])i(?![A-Za-z'])", text)
    ) / n_words
    # mid-sentence Capitalised words (rough proxy for stray capitalisation)
    cap_anomaly = 0
    for s in sentences:
        toks = s.split()
        for w in toks[1:]:  # skip the legit sentence-initial word
            if re.match(r"[A-Z][a-z]+$", w) and w not in ("I",):
                cap_anomaly += 1
    feats["cap_anomaly_rate"] = 1000.0 * cap_anomaly / n_words
    feats["spelling_deviation_rate"] = _spelling_deviation_rate(raw_words, n_words)

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
