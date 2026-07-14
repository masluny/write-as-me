#!/usr/bin/env python3
"""Score how closely a draft matches the writer's style fingerprint.

    python3 tools/score.py draft.md --target 80          # readable report
    python3 tools/score.py draft.md --json               # machine-readable

Output: overall 0-100, band, pass/fail, per-feature detail, and ranked
actionable notes telling the writing agent exactly what to change.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import stylometry

SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_DIR = SCRIPT_DIR.parent / "build"


def default_profile() -> Path:
    """profile.json lives in build/ in the repo layout, or next to this
    script in a flat skill bundle."""
    for cand in (BUILD_DIR / "profile.json", SCRIPT_DIR / "profile.json"):
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

# Voice-density features are scored ONE-SIDED: at or above the writer's mean
# earns full credit, only *less* is penalised. Rationale: LLM drafts fail in
# the "too clean / too neutral" direction, so under-shooting these is the
# failure mode worth catching. If your writer is unusually restrained (e.g.
# never uses intensifiers) the low mean already handles it; but if you find
# drafts overdoing a marker, remove that feature from this set to make it
# two-sided again.
ONE_SIDED = {
    "discourse_marker_rate", "pct_para_initial_connective",
    "pct_sent_start_so_also_and", "comma_per_sentence", "comma_splice_proxy",
    "first_person_rate", "i_think_rate", "hedge_rate", "intensifier_rate",
    "signature_ngram_rate", "spelling_deviation_rate", "lowercase_i_rate",
    "cap_anomaly_rate",
}

# how forgiving the per-feature Gaussian is, measured in std-devs
TOLERANCE = 1.6

# direction-aware note templates: (low_message, high_message)
NOTES = {
    "mean_sentence_len": (
        "Sentences too short (avg {d:.0f} vs the writer's ~{m:.0f} words) — merge some the way they chain clauses.",
        "Sentences too long (avg {d:.0f} vs the writer's ~{m:.0f} words) — split a few to match their rhythm.",
    ),
    "std_sentence_len": (
        "Sentence lengths too uniform (spread {d:.0f} vs ~{m:.0f}) — humans mix short and long; vary it.",
        "",
    ),
    "discourse_marker_rate": (
        "Too few connectives/discourse markers ({d:.0f} vs ~{m:.0f}/1000 words) — reuse the ones in STYLE.md.",
        "Too many connectives ({d:.0f} vs ~{m:.0f}/1000) — ease off the signposting a little.",
    ),
    "pct_para_initial_connective": (
        "Only {d:.0f}% of paragraphs open with a connective vs the writer's ~{m:.0f}% — match how they start paragraphs.",
        "",
    ),
    "comma_splice_proxy": (
        "Sentences too tidy ({d:.0f}% long multi-comma sentences vs ~{m:.0f}%) — let clauses run together like the writer does.",
        "",
    ),
    "comma_per_sentence": (
        "Few commas per sentence ({d:.1f} vs ~{m:.1f}) — the writer's sentences usually carry more.",
        "",
    ),
    "first_person_rate": (
        "Not personal enough ({d:.0f} vs ~{m:.0f} first-person words/1000) — more 'I', 'we', 'my'.",
        "",
    ),
    "i_think_rate": (
        "Add first-person opinion framing ('I think…', 'I would…') — now {d:.0f} vs ~{m:.0f}/1000.",
        "",
    ),
    "hedge_rate": (
        "Add hedging ({d:.0f} vs ~{m:.0f}/1000) — probably, maybe, I think, kind of.",
        "",
    ),
    "intensifier_rate": (
        "Add intensifiers ({d:.0f} vs ~{m:.0f}/1000) — really, very, so, totally.",
        "",
    ),
    "signature_ngram_rate": (
        "Missing the writer's signature phrases ({d:.0f} vs ~{m:.0f}/1000)",
        "",
    ),
    "spelling_deviation_rate": (
        "Text reads too clean ({d:.1f} vs ~{m:.1f} spelling deviations/1000) — the writer's small slips are part of the voice.",
        "",
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


def score(draft_text: str, profile: dict, target: float) -> dict:
    pf = profile["features"]
    sig = profile.get("signature_ngrams", [])
    df = stylometry.features(draft_text, sig)

    feat_report = {}
    weighted_sum = 0.0
    weight_total = 0.0
    impacts = []  # (impact, feature, message)

    for feat, w in WEIGHTS.items():
        mean = pf[feat]["mean"]
        std = pf[feat]["std"]
        # clamp sigma into [0.15*|mean|, 0.6*|mean|] so high-variance features
        # still discriminate, with a tiny absolute floor for safety.
        floor = max(0.15 * abs(mean), 1e-6)
        cap = max(0.6 * abs(mean), floor)
        sigma = min(max(std, floor), cap)
        d = df[feat]
        z = (d - mean) / sigma
        # one-sided features: at or above the mean is fully "the writer"
        fscore = 1.0 if (feat in ONE_SIDED and d >= mean) else gaussian(z)
        weighted_sum += w * fscore
        weight_total += w
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
                if feat == "signature_ngram_rate" and sig:
                    msg += " — e.g. " + ", ".join(f"'{g}'" for g in sig[:4])
                impacts.append((w * (1 - fscore), feat, msg))

    # function-word vector cosine (rescaled — raw cosine sits near 0.85 for
    # almost any English text, so stretch the useful range)
    fwc = fw_cosine(df, pf)
    fw_score = max(0.0, min(1.0, (fwc - 0.5) / 0.4))
    weighted_sum += FW_WEIGHT * fw_score
    weight_total += FW_WEIGHT
    feat_report["function_word_cosine"] = {"draft": round(fwc, 3), "score": round(fw_score, 3)}
    if fwc < 0.85:
        impacts.append((FW_WEIGHT * (1 - fw_score), "function_word_cosine",
                        "Overall function-word mix drifts from the writer's baseline — reread a sample and echo its connectors."))

    overall = round(100.0 * weighted_sum / weight_total, 1)
    band = "close" if overall >= 80 else "medium" if overall >= 60 else "far"
    impacts.sort(reverse=True)
    notes = [m for _, _, m in impacts]

    return {
        "overall": overall,
        "band": band,
        "target": target,
        "pass": overall >= target,
        "n_words": len(stylometry.words(draft_text)),
        "notes": notes,
        "features": feat_report,
    }


def print_report(result: dict) -> None:
    status = "PASS" if result["pass"] else "needs work"
    print(f"\nResemblance: {result['overall']}/100  ({result['band']}, target {result['target']:.0f}) — {status}")
    print(f"Words: {result['n_words']}\n")
    if result["notes"]:
        print("What to change (most impactful first):")
        for i, n in enumerate(result["notes"], 1):
            print(f"  {i}. {n}")
    else:
        print("No notable deviations — reads like the writer.")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("draft", type=Path)
    ap.add_argument("--profile", type=Path, default=default_profile())
    ap.add_argument("--target", type=float, default=80.0)
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
