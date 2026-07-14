# write-as-me

Turn your own writing into an AI **skill** that drafts new text in *your*
voice — with an objective stylometric scorer that grades every draft and a
write → score → revise loop your agent runs until the text actually reads like
you. Works with **Claude Code**, the **Claude desktop app** (plugin), and
**OpenAI Codex** (AGENTS.md).

No fine-tuning, no API keys, no cloud: your samples never leave your machine.
The LLM you already use (Claude / Codex) does the writing; a small pure-Python
scorer does the measuring.

## How it works

```
samples/            your real writing (.txt/.md/.pdf/.docx) — gitignored
   │ corpus_ingest.py
   ▼
build/corpus.jsonl  verbatim text + genre tags
   │ analyze.py
   ▼
build/profile.json  your fingerprint: 60+ stylometric features (means ± std)
                    + auto-derived signature phrases
   │ make_skill.py         (+ STYLE.md, authored by your AI from your samples)
   ▼
dist/<name>/        ready-to-install skill for Claude Code / Claude app / Codex
```

At drafting time the skill makes your agent: read `STYLE.md` → mirror the
closest real sample → write `draft.md` → run `score.py` (0–100 + ranked,
actionable notes like *"sentences too uniform"*, *"missing your signature
phrases"*) → revise → repeat until it passes (default target 80, max 4 passes).

## Quickstart

```bash
git clone <this repo> && cd write-as-me
pip install pymupdf python-docx pyspellchecker   # all optional: pdf, docx, spelling-quirk feature

# 1. add your writing
cp ~/my_old_essays/* samples/        # 8+ pieces; name files with genre keywords
                                     # (email/essay/report/article/blog/answer)

# 2. build your fingerprint
python3 tools/corpus_ingest.py
python3 tools/analyze.py

# 3. have your AI write your style guide
#    open your agent (Claude Code, Codex…) in this folder and give it the
#    prompt in templates/STYLE_PROMPT.md  ->  it authors ./STYLE.md

# 4. package the skill
python3 tools/make_skill.py --name write-as-alex --writer "Alex"
```

`make_skill.py` prints the install lines for each target:

- **Claude Code**: `cp -r dist/<name>/skill/<name> ~/.claude/skills/` — then just
  ask Claude to *"write X as me"* in a new session.
- **Claude desktop app**: upload `dist/<name>/<name>-plugin.zip` in
  Settings → Capabilities (plugin layout with `.claude-plugin/plugin.json`).
- **Codex**: merge `dist/<name>/AGENTS.md` into your project's `AGENTS.md` and
  keep the skill folder in the project.

No samples handy? Kick the tires with the bundled fake writer:

```bash
python3 tools/corpus_ingest.py --corpus examples/demo_samples
python3 tools/analyze.py
```

## Why a scorer instead of "just prompt it"?

LLMs drift toward polished, neutral prose — the opposite of a personal voice.
The scorer makes the loop objective:

- **60+ features**: sentence-length distribution, discourse markers, paragraph
  openers, comma-splice density, first-person/hedge/intensifier rates,
  contractions, function-word cosine, spelling deviations, capitalisation
  anomalies, and **signature phrases auto-derived from your corpus**.
- **One-sided "voice density" scoring**: LLM drafts fail in the *too clean*
  direction, so quirk-density features only penalise undershooting (tunable —
  see `ONE_SIDED` in `tools/score.py`).
- **Ranked notes**: every failed feature becomes a concrete instruction the
  agent can act on in the next pass.

Sanity-check your own fingerprint with leave-one-out: hold one real sample
out (`analyze.py --exclude <name>`), score it against the rest — it should
score high while generic AI text scores low.

## Repo layout

| path | what |
|------|------|
| `tools/corpus_ingest.py` | samples → `build/corpus.jsonl` |
| `tools/analyze.py` | corpus → `build/profile.json` (+ signature phrases) |
| `tools/score.py` | grade a draft against the profile (report or `--json`) |
| `tools/stylometry.py` | shared feature extractor |
| `tools/make_skill.py` | package skill + plugin zip + AGENTS.md into `dist/` |
| `templates/` | SKILL / AGENTS / plugin manifest templates + STYLE prompt |
| `samples/` | your writing (gitignored) |
| `examples/demo_samples/` | a fake writer to test the pipeline |

Your personal artifacts — `samples/*`, `build/`, `dist/`, `STYLE.md` — are all
gitignored, so a fork stays safe to push.

## Fair use

This is a tool for drafting in **your own** voice: first drafts, emails,
routine reports, beating blank-page paralysis. Don't use it to submit
AI-written work where that's not allowed (courses, exams, publications), and
don't clone anyone's voice but your own without their consent.

## License

MIT — see [LICENSE](LICENSE).
