#!/usr/bin/env python3
"""Package your analyzed style into ready-to-install agent skills.

    python3 tools/make_skill.py --name write-as-alex --writer "Alex"

Produces, under dist/<name>/:
  skill/<name>/          -> drop into ~/.claude/skills/  (Claude Code)
  plugin/<name>/ + .zip  -> upload in the Claude desktop app (plugin layout)
  AGENTS.md              -> snippet for OpenAI Codex (project AGENTS.md)

Prerequisites: run tools/corpus_ingest.py and tools/analyze.py first, and
author STYLE.md at the repo root (see templates/STYLE_PROMPT.md).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
BUILD_DIR = ROOT / "build"
TEMPLATES = ROOT / "templates"

EXCERPT_CHARS = 2000


def fill(template: str, name: str, writer: str) -> str:
    return (
        template.replace("{{SKILL_NAME}}", name)
        .replace("{{WRITER}}", writer)
        .replace("{{DIR}}", name)
    )


def build_samples_md(corpus_path: Path, writer: str) -> str:
    """One real excerpt per genre, straight from the ingested corpus."""
    by_genre: dict[str, dict] = {}
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            by_genre.setdefault(d["genre"], d)  # first doc per genre
    parts = [
        f"# samples.md — real writing by {writer} (style anchors)\n",
        "Mirror the structure, rhythm and quirks of these. They are genuine, unedited.\n",
    ]
    for genre, d in sorted(by_genre.items()):
        text = d["text"].strip()
        if len(text) > EXCERPT_CHARS:
            text = text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " […]"
        parts.append(f"\n## {genre} ({d['name']})\n\n{text}\n")
    return "\n".join(parts)


def write_skill_folder(dst: Path, name: str, writer: str, style: Path,
                       profile: Path, samples_md: str) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    skill_md = fill((TEMPLATES / "SKILL.template.md").read_text(encoding="utf-8"),
                    name, writer)
    (dst / "SKILL.md").write_text(skill_md, encoding="utf-8")
    shutil.copy2(style, dst / "STYLE.md")
    (dst / "samples.md").write_text(samples_md, encoding="utf-8")
    shutil.copy2(profile, dst / "profile.json")
    shutil.copy2(TOOLS_DIR / "score.py", dst / "score.py")
    shutil.copy2(TOOLS_DIR / "stylometry.py", dst / "stylometry.py")


def zip_dir(src: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if "__pycache__" in p.parts or p.name == ".DS_Store":
                continue
            zf.write(p, p.relative_to(src.parent))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="write-as-me", help="skill name (kebab-case)")
    ap.add_argument("--writer", default="the writer", help="writer's name as shown in prompts")
    ap.add_argument("--style", type=Path, default=ROOT / "STYLE.md")
    ap.add_argument("--profile", type=Path, default=BUILD_DIR / "profile.json")
    ap.add_argument("--corpus", type=Path, default=BUILD_DIR / "corpus.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    args = ap.parse_args()

    if not args.profile.exists() or not args.corpus.exists():
        sys.exit("missing build artifacts — run tools/corpus_ingest.py then tools/analyze.py first")
    if not args.style.exists():
        sys.exit(
            f"STYLE.md not found at {args.style} — have your AI author it from your "
            "samples using templates/STYLE_PROMPT.md, then re-run"
        )

    out_root = args.out / args.name
    if out_root.exists():
        shutil.rmtree(out_root)
    samples_md = build_samples_md(args.corpus, args.writer)

    # 1) Claude Code personal skill
    skill_dir = out_root / "skill" / args.name
    write_skill_folder(skill_dir, args.name, args.writer, args.style,
                       args.profile, samples_md)

    # 2) Claude desktop-app plugin (skills nested under skills/, manifest at root)
    plugin_root = out_root / "plugin" / args.name
    write_skill_folder(plugin_root / "skills" / args.name, args.name, args.writer,
                       args.style, args.profile, samples_md)
    manifest_dir = plugin_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = fill((TEMPLATES / "plugin.json.template").read_text(encoding="utf-8"),
                    args.name, args.writer)
    (manifest_dir / "plugin.json").write_text(manifest, encoding="utf-8")
    zip_dir(plugin_root, out_root / f"{args.name}-plugin.zip")

    # 3) Codex AGENTS.md snippet
    agents = fill((TEMPLATES / "AGENTS.template.md").read_text(encoding="utf-8"),
                  args.name, args.writer)
    (out_root / "AGENTS.md").write_text(agents, encoding="utf-8")

    print(f"Built -> {out_root}\n")
    print("Install options:")
    print(f"  Claude Code : cp -r {skill_dir} ~/.claude/skills/")
    print(f"  Claude app  : upload {out_root / (args.name + '-plugin.zip')} (Settings -> Capabilities)")
    print(f"  Codex       : merge {out_root / 'AGENTS.md'} into your project's AGENTS.md")
    print(f"                and keep the {args.name}/ skill folder in the project.")


if __name__ == "__main__":
    main()
