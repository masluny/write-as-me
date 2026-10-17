#!/usr/bin/env python3
"""Package your analyzed style into ready-to-install agent skills.

    python3 tools/make_skill.py --name write-as-alex --writer "Alex"

Produces, under dist/<name>/:
  skill/<name>/          -> Agent Skills folder: ~/.claude/skills/ (Claude Code)
                            or ~/.agents/skills/ (Codex, Copilot, Cursor, ...)
  <name>-skill.zip       -> upload in claude.ai / the Claude app (Customize > Skills)
  plugin/<name>/ + .zip  -> upload in the Claude app (Customize > Plugins)
  AGENTS.md              -> fallback snippet for agents without skills support

Prerequisites: run tools/corpus_ingest.py and tools/analyze.py first (and
ideally tools/eval.py --write-calibration), and author STYLE.md at the repo
root (see templates/STYLE_PROMPT.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
BUILD_DIR = ROOT / "build"
TEMPLATES = ROOT / "templates"

EXCERPT_CHARS = 2000
DESCRIPTION_SOFT_LIMIT = 200   # claude.ai custom-skill form
DESCRIPTION_HARD_LIMIT = 1024  # Agent Skills specification


def fill(template: str, name: str, writer: str, version: str = "") -> str:
    return (
        template.replace("{{SKILL_NAME}}", name)
        .replace("{{WRITER}}", writer)
        .replace("{{DIR}}", name)
        .replace("{{VERSION}}", version)
    )


def check_name(name: str) -> None:
    """Agent Skills spec: 1-64 chars, lowercase letters/digits/single hyphens."""
    if not (1 <= len(name) <= 64 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)):
        sys.exit(f"invalid --name {name!r}: use 1-64 lowercase letters, digits and "
                 "single hyphens (e.g. write-as-alex)")
    if re.search(r"(?:^|-)(?:claude|anthropic)(?:-|$)", name):
        sys.exit(f"invalid --name {name!r}: 'claude' and 'anthropic' are reserved words")


def build_version() -> str:
    """A new version on every build: a pinned plugin version keeps installed
    copies on the old cached build until the string changes."""
    now = dt.datetime.now()
    return f"1.{now:%Y%m%d}.{now.hour * 3600 + now.minute * 60 + now.second}"


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


def write_skill_folder(dst: Path, skill_md: str, style: Path,
                       profile: Path, samples_md: str) -> None:
    """Agent Skills layout: SKILL.md + references/ + scripts/ + assets/."""
    for sub in ("references", "scripts", "assets"):
        (dst / sub).mkdir(parents=True, exist_ok=True)
    (dst / "SKILL.md").write_text(skill_md, encoding="utf-8")
    shutil.copy2(style, dst / "references" / "STYLE.md")
    (dst / "references" / "samples.md").write_text(samples_md, encoding="utf-8")
    shutil.copy2(profile, dst / "assets" / "profile.json")
    shutil.copy2(TOOLS_DIR / "score.py", dst / "scripts" / "score.py")
    shutil.copy2(TOOLS_DIR / "stylometry.py", dst / "scripts" / "stylometry.py")


def zip_dir(src: Path, zip_path: Path) -> None:
    """Zip a folder so the folder itself is the archive's top level."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if "__pycache__" in p.parts or p.name == ".DS_Store":
                continue
            zf.write(p, p.relative_to(src.parent))


def validate_plugin(plugin_root: Path) -> None:
    claude = shutil.which("claude")
    if not claude:
        return
    try:
        out = subprocess.run([claude, "plugin", "validate", str(plugin_root)],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  (claude plugin validate skipped: {e})")
        return
    lines = (out.stdout + out.stderr).strip().splitlines()
    print("claude plugin validate:", *(f"  {ln}" for ln in lines[-6:]), sep="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="write-as-me", help="skill name (kebab-case)")
    ap.add_argument("--writer", default="the writer", help="writer's name as shown in prompts")
    ap.add_argument("--style", type=Path, default=ROOT / "STYLE.md")
    ap.add_argument("--profile", type=Path, default=BUILD_DIR / "profile.json")
    ap.add_argument("--corpus", type=Path, default=BUILD_DIR / "corpus.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    ap.add_argument("--version", default=None, help="plugin version (default: a new one per build)")
    args = ap.parse_args()

    check_name(args.name)
    if not args.profile.exists() or not args.corpus.exists():
        sys.exit("missing build artifacts — run tools/corpus_ingest.py then tools/analyze.py first")
    if not args.style.exists():
        sys.exit(
            f"STYLE.md not found at {args.style} — have your AI author it from your "
            "samples using templates/STYLE_PROMPT.md, then re-run"
        )

    skill_md = fill((TEMPLATES / "SKILL.template.md").read_text(encoding="utf-8"),
                    args.name, args.writer)
    desc = re.search(r"^description: (.*)$", skill_md, re.M).group(1)
    if len(desc) > DESCRIPTION_HARD_LIMIT:
        sys.exit(f"SKILL.md description is {len(desc)} chars (max {DESCRIPTION_HARD_LIMIT})")
    if len(desc) > DESCRIPTION_SOFT_LIMIT:
        print(f"  ! description is {len(desc)} chars; claude.ai's skill form allows "
              f"{DESCRIPTION_SOFT_LIMIT} — shorten --writer or the template")
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    if "calibration" not in profile:
        print("  ! profile has no calibrated target (score.py will use 80) — "
              "run tools/eval.py --write-calibration first")

    out_root = args.out / args.name
    if out_root.exists():
        shutil.rmtree(out_root)
    samples_md = build_samples_md(args.corpus, args.writer)
    version = args.version or build_version()

    # 1) Agent Skills folder (Claude Code, Codex, Copilot, Cursor, OpenCode, Goose)
    #    + the same folder zipped for claude.ai / the Claude app
    skill_dir = out_root / "skill" / args.name
    write_skill_folder(skill_dir, skill_md, args.style, args.profile, samples_md)
    zip_dir(skill_dir, out_root / f"{args.name}-skill.zip")

    # 2) Claude plugin (skills nested under skills/, manifest at root)
    plugin_root = out_root / "plugin" / args.name
    write_skill_folder(plugin_root / "skills" / args.name, skill_md,
                       args.style, args.profile, samples_md)
    manifest_dir = plugin_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = fill((TEMPLATES / "plugin.json.template").read_text(encoding="utf-8"),
                    args.name, args.writer, version)
    (manifest_dir / "plugin.json").write_text(manifest, encoding="utf-8")
    zip_dir(plugin_root, out_root / f"{args.name}-plugin.zip")

    # 3) AGENTS.md fallback for agents without skills support
    agents = fill((TEMPLATES / "AGENTS.template.md").read_text(encoding="utf-8"),
                  args.name, args.writer)
    (out_root / "AGENTS.md").write_text(agents, encoding="utf-8")

    print(f"Built -> {out_root}  (plugin version {version})\n")
    validate_plugin(plugin_root)
    print("\nInstall options:")
    print(f"  Claude Code        : cp -r {skill_dir} ~/.claude/skills/")
    print(f"  Codex / Copilot /  : cp -r {skill_dir} ~/.agents/skills/")
    print("  Cursor / OpenCode /    (or .agents/skills/ inside one project)")
    print("  Goose")
    print(f"  Claude app/claude.ai: upload {out_root / (args.name + '-skill.zip')} in Customize > Skills,")
    print(f"                       or {out_root / (args.name + '-plugin.zip')} in Customize > Plugins > Add > Upload plugin")
    print(f"  Other agents       : merge {out_root / 'AGENTS.md'} into the project's AGENTS.md")
    print("\nPrivacy: these packages contain excerpts of your real writing (samples.md)")
    print("and your style guide — share them only with people you'd show that writing to.")
    print("Install ONE copy per agent: several 'write as me' skills compete for the same requests.")


if __name__ == "__main__":
    main()
