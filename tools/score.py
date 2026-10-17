#!/usr/bin/env python3
"""Score how closely a draft matches the writer's style fingerprint.

    python3 tools/score.py draft.md                      # readable report
    python3 tools/score.py draft.md --json               # machine-readable

Output: overall 0-100 (style similarity minus an AI-tell penalty), band,
pass/fail, per-feature detail, and ranked actionable notes — each pointing at
the sentences to change — telling the writing agent exactly what to fix.
The pass target defaults to the value tools/eval.py calibrated into
profile.json, else 80.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import stylometry

SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_DIR = SCRIPT_DIR.parent / "build"
DEFAULT_TARGET = 80.0


def default_profile() -> Path:
    """profile.json lives in build/ in the repo layout, in assets/ in a
    packaged skill (scripts/score.py -> ../assets/profile.json), or next to
    this script in an older flat bundle."""
    for cand in (
        BUILD_DIR / "profile.json",
        SCRIPT_DIR.parent / "assets" / "profile.json",
        SCRIPT_DIR / "profile.json",
    ):
        if cand.exists():
            return cand
    return BUILD_DIR / "profile.json"


# curated, identity-bearing features and their weight in the overall score.
# (the function-word vector is handled separately via cosine, below.)
WEIGHTS = {
    "mean_sentence_len": 1.0,
    "std_sentence_len": 0.5,
    "pct_long_sentences": 0.5,
    "mean_paragraph_sentences": 0.5,
    "mean_word_len": 0.5,
    "mattr": 0.5,
    "discourse_marker_rate": 1.5,
    "pct_para_initial_connective": 1.0,
    "pct_sent_start_so_also_and": 0.5,
    "comma_per_sentence": 0.75,
    "comma_splice_proxy": 1.0,
    "first_person_rate": 1.5,
    "i_think_rate": 1.0,
    "hedge_rate": 1.0,
    "intensifier_rate": 0.75,
    "signature_ngram_rate": 1.0,
    "contraction_rate": 0.5,
    "spelling_deviation_rate": 0.5,
    "lowercase_i_rate": 0.3,
    "cap_anomaly_rate": 0.3,
}
FW_WEIGHT = 0.3  # weight of the function-word cosine similarity

# Voice-density features. LLM drafts fail in the "too clean / too neutral"
# direction, so anything from the writer's mean up to mean + BAND_HIGH sigma
# earns full credit. Beyond that the score falls off again: stuffing a draft
# with markers reads as caricature, and an uncapped one-sided metric is
# trivially gamed (Goodhart). Remove a feature from this set to make it plain
# two-sided.
ONE_SIDED = {
    "discourse_marker_rate", "pct_para_initial_connective",
    "pct_sent_start_so_also_and", "comma_per_sentence", "comma_splice_proxy",
    "first_person_rate", "i_think_rate", "hedge_rate", "intensifier_rate",
    "signature_ngram_rate",
}
BAND_HIGH = 2.0

# Quirks (slips, lowercase "i", stray capitals) earn full credit within
# QUIRK_BAND x the writer's own rate: too few reads clean, too many reads like
# a parody of the writer.
QUIRKS = {"spelling_deviation_rate", "lowercase_i_rate", "cap_anomaly_rate"}
QUIRK_BAND = (0.5, 1.5)

# how forgiving the per-feature Gaussian is, measured in std-devs
TOLERANCE = 1.6

# AI tells, subtracted from the overall score. Only the part ABOVE the
# writer's own rate (mean + max(2*std, slack)) counts, so a writer who really
# uses a word or an em dash is never penalised for it.
#   feature: (slack per 1000 words, points per unit over, cap in points)
PENALTIES = {
    "ai_tell_rate": (1.0, 4.0, 15.0),
    "em_dash_rate": (1.0, 2.0, 10.0),
    "neg_parallelism_rate": (3.0, 2.0, 6.0),
    "nominalization_rate": (10.0, 0.3, 6.0),
}
PENALTY_CAP = 25.0

# direction-aware note templates: (low_message, high_message)
NOTES = {
    "mean_sentence_len": (
        "Sentences too short (avg {d:.0f} vs the writer's ~{m:.0f} words) — merge some the way they chain clauses.",
        "Sentences too long (avg {d:.0f} vs the writer's ~{m:.0f} words) — split a few to match their rhythm.",
    ),
    "std_sentence_len": (
        "Sentence lengths too uniform (spread {d:.0f} vs ~{m:.0f}) — mix short and long the way the writer does.",
        "",
    ),
    "pct_long_sentences": (
        "Too few long (30+ word) sentences ({d:.0f}% vs ~{m:.0f}%) — let one or two run on.",
        "Too many 30+ word sentences ({d:.0f}% vs ~{m:.0f}%) — split one.",
    ),
    "mean_paragraph_sentences": (
        "Paragraphs too short ({d:.1f} vs ~{m:.1f} sentences) — merge some.",
        "Paragraphs too long ({d:.1f} vs ~{m:.1f} sentences) — split one.",
    ),
    "mattr": (
        "Vocabulary too repetitive (MATTR {d:.2f} vs ~{m:.2f}) — vary a few words.",
        "Vocabulary too varied for the writer (MATTR {d:.2f} vs ~{m:.2f}) — LLM text is lexically richer than people; reuse their plain words.",
    ),
    "discourse_marker_rate": (
        "Too few connectives/discourse markers ({d:.0f} vs ~{m:.0f}/1000 words) — reuse the ones in STYLE.md.",
        "Too many connectives ({d:.0f} vs ~{m:.0f}/1000) — ease off the signposting; stuffing them reads as parody.",
    ),
    "pct_para_initial_connective": (
        "Only {d:.0f}% of paragraphs open with a connective vs the writer's ~{m:.0f}% — match how they start paragraphs.",
        "Nearly every paragraph opens with a connective ({d:.0f}% vs ~{m:.0f}%) — vary a few openers.",
    ),
    "pct_sent_start_so_also_and": (
        "Few sentences start with So/Also/And ({d:.0f}% vs ~{m:.0f}%) — the writer often opens that way.",
        "Too many sentences start with So/Also/And ({d:.0f}% vs ~{m:.0f}%) — vary them.",
    ),
    "comma_splice_proxy": (
        "Sentences too tidy ({d:.0f}% long multi-comma sentences vs ~{m:.0f}%) — let clauses run together like the writer does.",
        "Too many long comma-chained sentences ({d:.0f}% vs ~{m:.0f}%) — split one or two.",
    ),
    "comma_per_sentence": (
        "Few commas per sentence ({d:.1f} vs ~{m:.1f}) — the writer's sentences usually carry more.",
        "Too many commas per sentence ({d:.1f} vs ~{m:.1f}).",
    ),
    "first_person_rate": (
        "Not personal enough ({d:.0f} vs ~{m:.0f} first-person words/1000) — more 'I', 'we', 'my'.",
        "Over-personal ({d:.0f} vs ~{m:.0f} first-person words/1000) — drop a few I/my.",
    ),
    "i_think_rate": (
        "Add first-person opinion framing ('I think…', 'I would…') — now {d:.0f} vs ~{m:.0f}/1000.",
        "Too many 'I think/I would' ({d:.0f} vs ~{m:.0f}/1000) — cut some; stuffing them reads as parody.",
    ),
    "hedge_rate": (
        "Add hedging ({d:.0f} vs ~{m:.0f}/1000) — probably, maybe, I think, kind of.",
        "Too much hedging ({d:.0f} vs ~{m:.0f}/1000) — cut some maybe/probably/I think.",
    ),
    "intensifier_rate": (
        "Add intensifiers ({d:.0f} vs ~{m:.0f}/1000) — really, very, so, totally.",
        "Too many intensifiers ({d:.0f} vs ~{m:.0f}/1000) — cut some really/very/so.",
    ),
    "signature_ngram_rate": (
        "Missing the writer's signature phrases ({d:.0f} vs ~{m:.0f}/1000)",
        "Signature phrases overused ({d:.0f} vs ~{m:.0f}/1000) — keep them natural, not stuffed.",
    ),
    "spelling_deviation_rate": (
        "Text reads too clean ({d:.1f} vs ~{m:.1f} spelling deviations/1000) — the writer's small slips are part of the voice.",
        "Too many spelling slips ({d:.1f} vs ~{m:.1f}/1000) — keep only one or two.",
    ),
    "lowercase_i_rate": (
        "No lowercase 'i' ({d:.1f} vs ~{m:.1f}/1000) — the writer occasionally writes 'i'.",
        "Too many lowercase 'i' ({d:.1f} vs ~{m:.1f}/1000) — keep it occasional.",
    ),
    "cap_anomaly_rate": (
        "No stray capitals ({d:.1f} vs ~{m:.1f}/1000) — the writer sometimes Capitalises an ordinary word mid-sentence.",
        "Too many stray Capitals ({d:.1f} vs ~{m:.1f}/1000) — keep it occasional.",
    ),
    "contraction_rate": (
        "Too few contractions ({d:.0f} vs ~{m:.0f}/1000) — the writer contracts more (it's, don't, can't).",
        "Too many contractions ({d:.0f} vs ~{m:.0f}/1000) — the writer tends to write things out (it is, do not).",
    ),
    "mean_word_len": (
        "",
        "Vocabulary too heavy (avg word {d:.1f} chars vs ~{m:.1f}) — use the writer's plainer words.",
    ),
}

PENALTY_NOTES = {
    "ai_tell_rate": "AI-tell vocabulary ({d:.1f} vs the writer's ~{m:.1f}/1000) — replace with the writer's plain words.",
    "em_dash_rate": "Em dashes ({d:.1f} vs the writer's ~{m:.1f}/1000) — use commas or full stops the way the writer does.",
    "neg_parallelism_rate": "'Not only X but Y' / 'it's not X, it's Y' constructions ({d:.1f} vs ~{m:.1f}/1000) — a known LLM habit; say it plainly.",
    "nominalization_rate": "Noun-heavy phrasing ({d:.0f} vs ~{m:.0f} -tion/-ment/-ness words per 1000) — use verbs the way the writer does.",
}


def load_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            sys.exit("PDF input needs pymupdf (pip install pymupdf) — or pass .md/.txt")
        parts = []
        with fitz.open(path) as doc:
            for page in doc:
                parts.append(page.get_text("text"))
        return "\n".join(parts)
    if suf == ".docx":
        try:
            import docx
        except ImportError:
            sys.exit("DOCX input needs python-docx (pip install python-docx) — or pass .md/.txt")
        d = docx.Document(str(path))
        return "\n\n".join(p.text for p in d.paragraphs)
    return path.read_text(encoding="utf-8", errors="replace")


def fw_cosine(draft: dict, profile_feats: dict) -> float:
    keys = [k for k in draft if k.startswith("fw_")]
    a = [draft[k] for k in keys]
    b = [profile_feats[k]["mean"] for k in keys]
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def gaussian(z: float) -> float:
    return math.exp(-0.5 * (z / TOLERANCE) ** 2)


def feature_score(feat: str, d: float, mean: float, sigma: float) -> tuple[float, float]:
    """(score in 0..1, signed z of the deviation that cost points)."""
    if feat in QUIRKS:
        lo, hi = QUIRK_BAND[0] * mean, QUIRK_BAND[1] * mean
        if lo <= d <= hi:
            return 1.0, 0.0
        z = (d - (lo if d < lo else hi)) / sigma
        return gaussian(z), z
    z = (d - mean) / sigma
    if feat in ONE_SIDED and z >= 0:
        return (1.0 if z <= BAND_HIGH else gaussian(z - BAND_HIGH)), z
    return gaussian(z), z


# ---------------------------------------------------------------------------
# point the notes at the sentences that cause them
# ---------------------------------------------------------------------------


def _snip(s: str, n: int = 90) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _most(sentences: list[str], key, k: int = 2) -> list[str]:
    ranked = sorted(sentences, key=key, reverse=True)
    return [s for s in ranked[:k] if key(s) > 0]


def _avg_word_len(s: str) -> float:
    ws = stylometry.words(s)
    return sum(map(len, ws)) / len(ws) if ws else 0.0


def locate(feat: str, high: bool, text: str, sig: list[str]) -> list[str]:
    text = stylometry._normalize(text)
    sents = stylometry.split_sentences(text)

    def hits(phrases):
        return lambda s: stylometry._count_phrases(s.lower(), phrases)

    def regex(rx):
        return lambda s: len(rx.findall(s.lower()))

    if feat == "mean_sentence_len":
        return sorted(sents, key=lambda s: len(stylometry.words(s)), reverse=high)[:2]
    if feat == "mean_word_len" and high:
        return _most(sents, _avg_word_len)
    if feat == "pct_para_initial_connective" and not high:
        return [p for p in stylometry.split_paragraphs(text)
                if not stylometry._starts_with_marker(p, stylometry.DISCOURSE_MARKERS)][:2]
    if feat == "ai_tell_rate":
        return _most(sents, regex(stylometry._AI_TELL_RE))
    if feat == "em_dash_rate":
        return _most(sents, lambda s: len(stylometry._DASH_RE.findall(s)))
    if feat == "neg_parallelism_rate":
        return _most(sents, regex(stylometry._NEG_PARALLEL_RE))
    if feat == "nominalization_rate":
        return _most(sents, regex(stylometry._NOMINAL_RE))
    if not high:
        return []  # "add more X" notes have no sentence to point at
    overdone = {
        "discourse_marker_rate": stylometry.DISCOURSE_MARKERS,
        "hedge_rate": stylometry.HEDGES,
        "intensifier_rate": stylometry.INTENSIFIERS,
        "signature_ngram_rate": sig,
        "i_think_rate": ["i think", "i would"],
        "first_person_rate": ["i", "me", "my", "mine", "we", "our", "us"],
    }
    if feat == "pct_sent_start_so_also_and":
        return [s for s in sents if stylometry._starts_with_marker(s, ["so", "also", "and"])][:2]
    if feat in overdone:
        return _most(sents, hits(overdone[feat]))
    if feat == "contraction_rate":
        return _most(sents, regex(re.compile(r"\b\w+'(?:t|s|re|ve|ll|d|m)\b")))
    if feat == "lowercase_i_rate":
        return _most(sents, lambda s: len(re.findall(r"(?<![A-Za-z.])i(?![A-Za-z']|\.e\.)", s)))
    if feat == "cap_anomaly_rate":
        vocab = {w for w in stylometry.words(text) if w.islower()}
        return _most(sents, lambda s: len(stylometry._cap_anomalies([s], vocab)))
    return []


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def score(draft_text: str, profile: dict, target: float | None = None) -> dict:
    pf = profile["features"]
    sig = profile.get("signature_ngrams", [])
    df = stylometry.features(draft_text, sig)
    if target is None:
        target = profile.get("calibration", {}).get("target", DEFAULT_TARGET)

    warnings: list[str] = []
    skip: set[str] = set()
    missing = [f for f in list(WEIGHTS) + list(PENALTIES) if f not in pf]
    if missing:
        skip |= set(missing)
        warnings.append("profile.json predates this scorer (missing "
                        + ", ".join(missing) + ") — rebuild it with analyze.py.")
    profile_spell = profile.get(
        "spellchecker", pf.get("spelling_deviation_rate", {}).get("mean", 0) > 0)
    if not (profile_spell and stylometry.spellchecker_available()):
        # without the same spellchecker on both sides the feature is 0 for
        # every draft and would always read as "too clean"
        skip.add("spelling_deviation_rate")
        if profile_spell:
            warnings.append("pyspellchecker isn't installed here but the profile was built "
                            "with it — spelling feature skipped (pip install pyspellchecker).")

    active = {f: w for f, w in WEIGHTS.items() if f not in skip}
    weight_total = sum(active.values()) + FW_WEIGHT
    feat_report = {}
    weighted_sum = 0.0
    impacts = []  # (points lost, feature, message, sentences)

    for feat, w in active.items():
        mean = pf[feat]["mean"]
        std = pf[feat]["std"]
        # clamp sigma into [0.15*|mean|, 0.6*|mean|] so high-variance features
        # still discriminate, with a tiny absolute floor for safety.
        floor = max(0.15 * abs(mean), 1e-6)
        cap = max(0.6 * abs(mean), floor)
        sigma = min(max(std, floor), cap)
        d = df[feat]
        fscore, z = feature_score(feat, d, mean, sigma)
        weighted_sum += w * fscore
        feat_report[feat] = {
            "draft": round(d, 2),
            "target_mean": round(mean, 2),
            "target_range": [round(pf[feat]["min"], 2), round(pf[feat]["max"], 2)],
            "z": round(z, 2),
            "score": round(fscore, 3),
        }
        if fscore < 0.75:
            low_msg, high_msg = NOTES.get(feat, ("", ""))
            msg = low_msg if z < 0 else high_msg
            if msg:
                msg = msg.format(d=d, m=mean)
                if feat == "signature_ngram_rate" and sig and z < 0:
                    msg += " — e.g. " + ", ".join(f"'{g}'" for g in sig[:4])
                points = 100.0 * w * (1 - fscore) / weight_total
                impacts.append((points, feat, msg, locate(feat, z > 0, draft_text, sig)))

    # function-word vector cosine (rescaled — raw cosine sits near 0.85 for
    # almost any English text, so stretch the useful range)
    fwc = fw_cosine(df, pf)
    fw_score = max(0.0, min(1.0, (fwc - 0.5) / 0.4))
    weighted_sum += FW_WEIGHT * fw_score
    feat_report["function_word_cosine"] = {"draft": round(fwc, 3), "score": round(fw_score, 3)}
    if fwc < 0.85:
        impacts.append((100.0 * FW_WEIGHT * (1 - fw_score) / weight_total, "function_word_cosine",
                        "Overall function-word mix drifts from the writer's baseline — reread a sample and echo its connectors.",
                        []))
    similarity = 100.0 * weighted_sum / weight_total

    # AI-tell penalty, only above the writer's own rate
    penalty = 0.0
    for feat, (slack, per_unit, cap) in PENALTIES.items():
        if feat in skip:
            continue
        mean, std = pf[feat]["mean"], pf[feat]["std"]
        allowed = mean + max(2 * std, slack)
        pts = min(cap, per_unit * max(0.0, df[feat] - allowed))
        feat_report[feat] = {
            "draft": round(df[feat], 2),
            "target_mean": round(mean, 2),
            "allowed_up_to": round(allowed, 2),
            "penalty": round(pts, 1),
        }
        if pts > 0:
            penalty += pts
            msg = PENALTY_NOTES[feat].format(d=df[feat], m=mean)
            if feat == "ai_tell_rate":
                found = sorted(set(stylometry.ai_tell_hits(draft_text)))
                msg += " Found: " + ", ".join(f"'{w}'" for w in found)
            impacts.append((pts, feat, msg, locate(feat, True, draft_text, sig)))
    penalty = min(PENALTY_CAP, penalty)

    overall = round(max(0.0, similarity - penalty), 1)
    band = "close" if overall >= target else "medium" if overall >= target - 20 else "far"
    impacts.sort(key=lambda t: t[0], reverse=True)
    details = [
        {"feature": f, "points": round(p, 1), "message": m, "look_at": [_snip(s) for s in where]}
        for p, f, m, where in impacts
    ]
    notes = [
        d["message"] + (" Look at: " + " | ".join(f'"{s}"' for s in d["look_at"]) if d["look_at"] else "")
        for d in details
    ]

    return {
        "overall": overall,
        "similarity": round(similarity, 1),
        "ai_penalty": round(penalty, 1),
        "band": band,
        "target": target,
        "pass": overall >= target,
        "n_words": len(stylometry.words(draft_text)),
        "notes": notes,
        "note_details": details,
        "warnings": warnings,
        "features": feat_report,
    }


def print_report(result: dict) -> None:
    status = "PASS" if result["pass"] else "needs work"
    print(f"\nResemblance: {result['overall']}/100  ({result['band']}, target {result['target']:.0f}) — {status}")
    print(f"Style similarity {result['similarity']}, AI-tell penalty -{result['ai_penalty']}  |  "
          f"Words: {result['n_words']}\n")
    for w in result["warnings"]:
        print(f"  ! {w}")
    if result["warnings"]:
        print()
    if result["notes"]:
        print("What to change (most impactful first):")
        for i, d in enumerate(result["note_details"], 1):
            print(f"  {i}. [-{d['points']:.1f}] {d['message']}")
            for s in d["look_at"]:
                print(f"       → \"{s}\"")
    else:
        print("No notable deviations — reads like the writer.")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("draft", type=Path)
    ap.add_argument("--profile", type=Path, default=default_profile())
    ap.add_argument("--target", type=float, default=None,
                    help="pass threshold (default: calibrated value in profile.json, else 80)")
    ap.add_argument("--json", action="store_true", help="emit JSON (for the agent loop)")
    args = ap.parse_args()

    if not args.profile.exists():
        sys.exit(f"profile not found: {args.profile} (run tools/analyze.py first)")
    if not args.draft.exists():
        sys.exit(f"draft not found: {args.draft}")

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    result = score(load_text(args.draft), profile, args.target)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
