#!/usr/bin/env python3
"""Measure how well the scorer separates the writer from impostors.

    python3 tools/eval.py                               # report
    python3 tools/eval.py --impostors my_ai_drafts/     # add more impostors
    python3 tools/eval.py --by-genre                    # cross-genre check
    python3 tools/eval.py --write-calibration           # store the pass target

Genuine scores are leave-one-out: each of the writer's documents is scored
against a profile rebuilt WITHOUT it. Impostors (examples/impostors/ plus any
--impostors folders) are scored against the full profile. The skill's own
drafts are the most realistic impostors — save a few and pass their folder.
A "stuffed" copy of every impostor, padded with the writer's markers and
signature phrases, checks that the score can't be gamed.

Reports ROC-AUC with a bootstrap 95% CI, the equal-error rate, pass rates at
the target, and the threshold that best separates the two groups (which
--write-calibration stores in profile.json as score.py's default target).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import statistics
import sys
from pathlib import Path

import analyze
import score
import stylometry

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
BUILD_DIR = ROOT / "build"
DEFAULT_IMPOSTORS = ROOT / "examples" / "impostors"
TEXT_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


def read_dir(path: Path) -> list[tuple[str, str]]:
    return [(p.name, score.load_text(p)) for p in sorted(path.iterdir())
            if p.suffix.lower() in TEXT_SUFFIXES and not p.name.startswith(".")]


def stuff(text: str, profile: dict) -> str:
    """Pad every paragraph with the writer's markers — a crude gaming attack
    that leaves the content and structure of the text untouched."""
    sig = ", ".join(profile.get("signature_ngrams", [])[:4])
    tail = f" I think it is really very important, for example, and also maybe {sig}, so yes."
    return "\n\n".join("So, I think that for sure, " + p[0].lower() + p[1:] + tail
                       for p in stylometry.split_paragraphs(text))


def genuine_scores(docs: list[dict], by_genre: bool) -> list[tuple[str, str, float]]:
    out = []
    for held in docs:
        if by_genre:
            rest = [d for d in docs if d["genre"] != held["genre"]]
        else:
            rest = [d for d in docs if d is not held]
        if not rest:
            continue
        prof = analyze.build_profile(rest)
        out.append((held["name"], held["genre"], score.score(held["text"], prof)["overall"]))
    return out


def auc(pos: list[float], neg: list[float]) -> float:
    """P(genuine scores higher than impostor) — Mann-Whitney U / (n1*n2)."""
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def auc_ci(pos, neg, n_boot=2000, seed=1234) -> tuple[float, float]:
    if not pos or not neg:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    vals = sorted(
        auc([rng.choice(pos) for _ in pos], [rng.choice(neg) for _ in neg])
        for _ in range(n_boot)
    )
    return vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot) - 1]


def thresholds(pos, neg):
    """Candidate pass thresholds: midpoints between neighbouring scores."""
    s = sorted(set(pos + neg))
    return [s[0] - 0.1] + [(a + b) / 2 for a, b in zip(s, s[1:])] + [s[-1] + 0.1]


def rates(t, pos, neg):
    frr = sum(p < t for p in pos) / len(pos)   # genuine that fail
    far = sum(n >= t for n in neg) / len(neg)  # impostors that pass
    return frr, far


def eer(pos, neg) -> tuple[float, float]:
    best = min(thresholds(pos, neg), key=lambda t: abs(rates(t, pos, neg)[0] - rates(t, pos, neg)[1]))
    frr, far = rates(best, pos, neg)
    return (frr + far) / 2, best


def best_threshold(pos, neg) -> float:
    """Youden's J: maximise genuine pass rate minus impostor pass rate. Ties go
    to the stricter threshold — in the drafting loop a failing genuine-sounding
    draft just gets another pass, while a passing AI-sounding one ships."""
    return max(thresholds(pos, neg),
               key=lambda t: ((1 - rates(t, pos, neg)[0]) - rates(t, pos, neg)[1], t))


def summary(xs):
    return {"n": len(xs), "min": round(min(xs), 1), "median": round(statistics.median(xs), 1),
            "max": round(max(xs), 1)} if xs else {"n": 0}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path, default=BUILD_DIR / "corpus.jsonl")
    ap.add_argument("--impostors", type=Path, action="append", default=[],
                    help="extra folder of impostor texts (repeatable)")
    ap.add_argument("--no-default-impostors", action="store_true",
                    help=f"don't include {DEFAULT_IMPOSTORS.relative_to(ROOT)}")
    ap.add_argument("--target", type=float, default=score.DEFAULT_TARGET)
    ap.add_argument("--by-genre", action="store_true",
                    help="also score each genre against a profile built from the OTHER genres")
    ap.add_argument("--write-calibration", nargs="?", type=Path, const=BUILD_DIR / "profile.json",
                    default=None, metavar="PROFILE",
                    help="store the best threshold as the default target in this profile.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.corpus.exists():
        sys.exit(f"corpus not found: {args.corpus} (run tools/corpus_ingest.py first)")
    docs = analyze.load_corpus(args.corpus)
    if len(docs) < 3:
        sys.exit("need at least 3 documents for a leave-one-out evaluation")
    dirs = ([] if args.no_default_impostors else [DEFAULT_IMPOSTORS]) + args.impostors
    impostors = [item for d in dirs for item in read_dir(d)]
    if not impostors:
        sys.exit("no impostor texts found — pass --impostors <folder>")

    full = analyze.build_profile(docs)
    gen = genuine_scores(docs, by_genre=False)
    imp = [(n, score.score(t, full)["overall"]) for n, t in impostors]
    stf = [(n, score.score(stuff(t, full), full)["overall"]) for n, t in impostors]
    g = [s for _, _, s in gen]
    i = [s for _, s in imp]
    st = [s for _, s in stf]
    neg = i + st

    lo, hi = auc_ci(g, i)
    e, e_t = eer(g, neg)
    best = best_threshold(g, neg)
    frr_b, far_b = rates(best, g, neg)
    report = {
        "n_docs": len(docs),
        "total_words": sum(d["n_words"] for d in docs),
        "target": args.target,
        "genuine_loo": summary(g),
        "impostors": summary(i),
        "stuffed_impostors": summary(st),
        "pass_at_target": {
            "genuine": sum(x >= args.target for x in g),
            "impostors": sum(x >= args.target for x in i),
            "stuffed": sum(x >= args.target for x in st),
        },
        "auc_vs_impostors": round(auc(g, i), 3),
        "auc_vs_impostors_ci95": [round(lo, 3), round(hi, 3)],
        "auc_vs_stuffed": round(auc(g, st), 3),
        "eer": round(e, 3),
        "best_threshold": round(best, 1),
        "best_threshold_genuine_pass": round(1 - frr_b, 3),
        "best_threshold_impostor_pass": round(far_b, 3),
        "genuine": [{"name": n, "genre": gr, "score": s} for n, gr, s in gen],
        "impostor_scores": [{"name": n, "score": s} for n, s in imp],
        "stuffed_scores": [{"name": n, "score": s} for n, s in stf],
    }
    if args.by_genre:
        cg = genuine_scores(docs, by_genre=True)
        report["cross_genre"] = {
            "genuine": summary([s for _, _, s in cg]),
            "auc_vs_impostors": round(auc([s for _, _, s in cg], i), 3),
            "scores": [{"name": n, "genre": gr, "score": s} for n, gr, s in cg],
        }

    if args.write_calibration:
        prof_path = args.write_calibration
        if not prof_path.exists():
            sys.exit(f"profile not found: {prof_path} (run tools/analyze.py first)")
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
        prof["calibration"] = {
            "target": round(min(90.0, max(50.0, best)), 1),
            "auc": report["auc_vs_impostors"],
            "eer": report["eer"],
            "n_genuine": len(g),
            "n_impostors": len(neg),
            "date": dt.date.today().isoformat(),
        }
        prof_path.write_text(json.dumps(prof, indent=2), encoding="utf-8")
        report["calibration_written"] = str(prof_path)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    def line(label, xs, key):
        s = summary(xs)
        return (f"  {label:<30} min {s['min']:5.1f}  median {s['median']:5.1f}  max {s['max']:5.1f}"
                f"   pass@{args.target:.0f}: {report['pass_at_target'][key]}/{len(xs)}")

    print(f"\nWriter: {len(docs)} docs, {report['total_words']} words  |  "
          f"impostors: {len(i)} (+{len(st)} stuffed)\n")
    print(line("genuine (leave-one-out)", g, "genuine"))
    print(line("impostors", i, "impostors"))
    print(line("stuffed impostors (gaming)", st, "stuffed"))
    print(f"\n  AUC genuine vs impostors: {report['auc_vs_impostors']:.2f}  (95% CI {lo:.2f}–{hi:.2f})")
    print(f"  AUC genuine vs stuffed:   {report['auc_vs_stuffed']:.2f}")
    print(f"  Equal-error rate:         {e:.0%}  (at {e_t:.1f})")
    print(f"  Best threshold:           {best:.1f}  -> genuine pass {1 - frr_b:.0%}, impostors pass {far_b:.0%}")
    if args.by_genre:
        cg = report["cross_genre"]
        print(f"\n  Cross-genre genuine: median {cg['genuine']['median']}, "
              f"min {cg['genuine']['min']}  |  AUC vs impostors {cg['auc_vs_impostors']:.2f}")
    print("\n  Lowest genuine:   " + ", ".join(f"{n} {s:.0f}" for n, _, s in sorted(gen, key=lambda x: x[2])[:3]))
    print("  Highest impostor: " + ", ".join(f"{n} {s:.0f}" for n, s in sorted(imp + stf, key=lambda x: -x[1])[:3]))
    if len(g) < 30:
        print(f"\n  Note: with {len(g)} genuine docs these numbers are rough "
              "(AUC CI half-width ~±0.1) — more writing samples tighten them.")
    if args.write_calibration:
        print(f"\n  Calibration written -> {report['calibration_written']} "
              f"(target {min(90.0, max(50.0, best)):.1f})")
    print()


if __name__ == "__main__":
    main()
