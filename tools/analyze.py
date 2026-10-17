#!/usr/bin/env python3
"""Build build/profile.json — your quantitative style fingerprint.

For every feature we store a weighted mean and standard deviation across your
corpus documents. score.py compares a draft against these ranges.

This also auto-derives your *signature phrases* (recurring word n-grams that
show up across multiple of your documents) and stores them in the profile, so
the scorer can check drafts for them.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import stylometry

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
BUILD_DIR = ROOT / "build"

# n-grams made ONLY of these ultra-common words are not signatures
_STOPPY = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "it", "that", "this", "with", "as", "at", "by", "from",
    "be", "will", "would", "can", "has", "have", "had", "i", "we", "you",
    "my", "our", "your", "me", "us", "they", "their", "there",
}


def load_corpus(path: Path) -> list[dict]:
    docs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


def derive_signature_ngrams(texts: list[str], top_k: int = 12) -> list[str]:
    """Find phrases (2-4 word n-grams) that recur across the writer's docs."""
    if len(texts) < 2:
        return []
    min_docs = max(2, round(0.25 * len(texts)))
    doc_grams: list[set] = []
    total: Counter = Counter()
    for t in texts:
        toks = [w.lower() for w in stylometry.words(stylometry._normalize(t))]
        grams = set()
        for n in (2, 3, 4):
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i : i + n])
                grams.add(g)
                total[g] += 1
        doc_grams.append(grams)
    df: Counter = Counter()
    for grams in doc_grams:
        for g in grams:
            df[g] += 1
    cands = [
        g
        for g, c in df.items()
        if c >= min_docs and not all(w in _STOPPY for w in g.split())
    ]
    cands.sort(key=lambda g: (-df[g], -total[g], -len(g)))
    cands = cands[: top_k * 4]
    # drop n-grams that are substrings of an already-kept longer phrase
    final: list[str] = []
    for g in sorted(cands, key=len, reverse=True):
        if any(g in kept for kept in final):
            continue
        final.append(g)
    final.sort(key=lambda g: (-df[g], -total[g]))
    return final[:top_k]


def weighted_stats(values: list[float], weights: list[float]) -> dict[str, float]:
    wsum = sum(weights) or 1.0
    mean = sum(v * w for v, w in zip(values, weights)) / wsum
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / wsum
    return {
        "mean": mean,
        "std": math.sqrt(var),
        "min": min(values),
        "max": max(values),
    }


def aggregate(docs: list[dict], sig: list[str]) -> dict[str, dict[str, float]]:
    per_doc = [
        (stylometry.features(d["text"], sig), d.get("weight", 1.0)) for d in docs
    ]
    keys = per_doc[0][0].keys()
    out = {}
    for k in keys:
        vals = [f[k] for f, _ in per_doc]
        wts = [w for _, w in per_doc]
        out[k] = weighted_stats(vals, wts)
    return out


def build_profile(docs: list[dict]) -> dict:
    sig = derive_signature_ngrams([d["text"] for d in docs])
    profile = {
        "n_docs": len(docs),
        "total_words": sum(d["n_words"] for d in docs),
        # the spelling feature is only comparable when draft and profile were
        # both measured with pyspellchecker; score.py checks this flag
        "spellchecker": stylometry.spellchecker_available(),
        "signature_ngrams": sig,
        "features": aggregate(docs, sig),
        "by_genre": {},
        "docs": [{"name": d["name"], "genre": d["genre"]} for d in docs],
    }
    for genre in sorted({d["genre"] for d in docs}):
        subset = [d for d in docs if d["genre"] == genre]
        profile["by_genre"][genre] = {
            "n_docs": len(subset),
            "features": {k: v["mean"] for k, v in aggregate(subset, sig).items()},
        }
    return profile


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=BUILD_DIR / "corpus.jsonl")
    ap.add_argument("--out", type=Path, default=BUILD_DIR / "profile.json")
    ap.add_argument("--exclude", default=None,
                    help="skip docs whose name contains this substring (leave-one-out tests)")
    args = ap.parse_args()

    if not args.corpus.exists():
        sys.exit(f"corpus not found: {args.corpus} (run tools/corpus_ingest.py first)")

    docs = load_corpus(args.corpus)
    if args.exclude:
        docs = [d for d in docs if args.exclude.lower() not in d["name"].lower()]
    if not docs:
        sys.exit("corpus is empty")

    profile = build_profile(docs)
    sig = profile["signature_ngrams"]
    if args.out.exists():  # keep a calibration written earlier by eval.py
        try:
            old = json.loads(args.out.read_text(encoding="utf-8"))
            if "calibration" in old:
                profile["calibration"] = old["calibration"]
        except (OSError, ValueError):
            pass

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    print(f"Profile written -> {args.out}")
    print(f"  {profile['n_docs']} docs, {profile['total_words']} words")
    if not profile["spellchecker"]:
        print("  (pyspellchecker not installed: spelling-deviation feature disabled)")
    print(f"  signature phrases: {', '.join(repr(s) for s in sig) or '(none found)'}\n")
    headline = [
        "mean_sentence_len", "std_sentence_len", "pct_para_initial_connective",
        "discourse_marker_rate", "first_person_rate", "i_think_rate",
        "hedge_rate", "intensifier_rate", "comma_per_sentence",
        "comma_splice_proxy", "signature_ngram_rate", "exclamation_rate",
        "lowercase_i_rate", "cap_anomaly_rate", "spelling_deviation_rate",
        "contraction_rate", "ai_tell_rate", "em_dash_rate",
    ]
    for k in headline:
        s = profile["features"][k]
        print(f"  {k:<30} {s['mean']:7.2f}  ± {s['std']:6.2f}   [{s['min']:.1f}–{s['max']:.1f}]")


if __name__ == "__main__":
    main()
