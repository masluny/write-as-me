#!/usr/bin/env python3
"""Ingest your writing samples (PDF / DOCX / TXT / MD) into build/corpus.jsonl.

Text is extracted *verbatim* — nothing is corrected or cleaned up, because the
quirks in your writing are exactly the fingerprint we want to capture.

Put your samples in ./samples (see samples/README.md) and run:

    python3 tools/corpus_ingest.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
DEFAULT_CORPUS = ROOT / "samples"
BUILD_DIR = ROOT / "build"

# filename keyword -> genre label (checked in order). Name your files with one
# of these keywords (e.g. email_to_landlord.txt, uni_essay_2024.pdf) so drafts
# can be matched to the right kind of sample.
GENRE_KEYWORDS = [
    ("email", "email"),
    ("letter", "email"),
    ("essay", "essay"),
    ("report", "report"),
    ("article", "article"),
    ("blog", "article"),
    ("answer", "answer"),
    ("writing", "writing"),
]


def infer_genre(name: str) -> str:
    low = name.lower()
    for kw, genre in GENRE_KEYWORDS:
        if kw in low:
            return genre
    return "other"


def extract_pdf(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("PDF input needs pymupdf:  pip install pymupdf")
    parts = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def extract_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        sys.exit("DOCX input needs python-docx:  pip install python-docx")
    d = docx.Document(str(path))
    return "\n\n".join(p.text for p in d.paragraphs)


def extract_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".txt": extract_text_file,
    ".md": extract_text_file,
}


def clean(text: str) -> str:
    """Normalise whitespace only — content stays byte-for-byte otherwise."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse big gaps to one blank line
    return text.strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text))


def ingest(corpus_dir: Path) -> list[dict]:
    docs: list[dict] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.name.startswith(".") or path.suffix.lower() not in EXTRACTORS:
            continue
        try:
            raw = EXTRACTORS[path.suffix.lower()](path)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"  ! skipped {path.name}: {e}", file=sys.stderr)
            continue
        text = clean(raw)
        n = word_count(text)
        if n < 20:
            print(
                f"  ! skipped {path.name}: only {n} words (likely image-only PDF)",
                file=sys.stderr,
            )
            continue
        # a file's mtime says when it was copied, not written — only trust a
        # year in the filename (e.g. uni_essay_2024.pdf)
        m = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", path.stem)
        year = int(m.group(0)) if m else None
        docs.append(
            {
                "path": str(path),
                "name": path.name,
                "genre": infer_genre(path.name),
                "year": year,
                "weight": 1.0,
                "n_words": n,
                "n_chars": len(text),
                "text": text,
            }
        )
    return docs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS,
                    help="folder with your writing samples (default: ./samples)")
    ap.add_argument("--out", type=Path, default=BUILD_DIR / "corpus.jsonl")
    args = ap.parse_args()

    if not args.corpus.exists():
        sys.exit(f"corpus dir not found: {args.corpus}")

    docs = ingest(args.corpus)
    if not docs:
        sys.exit(
            "no documents ingested — put .txt/.md/.pdf/.docx samples in "
            f"{args.corpus} (see samples/README.md)"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    total = sum(d["n_words"] for d in docs)
    print(f"Ingested {len(docs)} documents ({total} words) -> {args.out}")
    for d in docs:
        print(f"  {d['name']:<36} {d['genre']:<8} {d['year'] or '-':<4}  {d['n_words']:>5}w")
    if len(docs) < 6:
        print("\n  Tip: 8+ samples across a few genres gives a much sharper fingerprint.")


if __name__ == "__main__":
    main()
