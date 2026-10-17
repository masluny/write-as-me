# write-as-me

Turn your own writing into an AI **skill** that drafts new text in *your*
voice — with an objective stylometric scorer that grades every draft and a
write → score → revise loop your agent runs until the text actually reads like
you. Works with **Claude Code**, **claude.ai / the Claude app** (skill or
plugin upload), and any agent that reads Agent Skills — **OpenAI Codex**,
GitHub Copilot, Cursor, OpenCode, Goose — with an AGENTS.md fallback.

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
   │ eval.py --write-calibration   (your writing vs AI impostors -> pass target)
   │ make_skill.py         (+ STYLE.md, authored by your AI from your samples)
   ▼
dist/<name>/        ready-to-install skill for Claude Code / Claude app / Codex …
```

At drafting time the skill makes your agent: read `STYLE.md` → mirror real
samples of the same genre → write `draft.md` → run `score.py` (0–100 + ranked,
actionable notes like *"sentences too uniform"* or *"AI-tell vocabulary:
'pivotal'"*, each quoting the sentences to change) → revise → keep the best
pass → stop when it passes or stops improving (max 4 passes).

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

# 3. check it separates you from AI text, and calibrate the pass target
python3 tools/eval.py --write-calibration

# 4. have your AI write your style guide
#    open your agent (Claude Code, Codex…) in this folder and give it the
#    prompt in templates/STYLE_PROMPT.md  ->  it authors ./STYLE.md

# 5. package the skill
python3 tools/make_skill.py --name write-as-alex --writer "Alex"
```

`make_skill.py` prints the install lines for each target. Install **one**
copy per agent: several "write as me" skills compete for the same requests.

- **Claude Code**: `cp -r dist/<name>/skill/<name> ~/.claude/skills/` — then just
  ask Claude to *"write X as me"* in a new session.
- **Codex, GitHub Copilot, Cursor, OpenCode, Goose**: the same folder works
  there too: `cp -r dist/<name>/skill/<name> ~/.agents/skills/` (or
  `.agents/skills/` inside one project).
- **claude.ai / Claude app**: upload `dist/<name>/<name>-skill.zip` in
  **Customize → Skills**, or `dist/<name>/<name>-plugin.zip` in
  **Customize → Plugins → Add → Upload plugin**.
- **Agents without skills support**: merge `dist/<name>/AGENTS.md` into the
  project's `AGENTS.md` and keep the skill folder at `.agents/skills/<name>/`.

The packages contain excerpts of your real writing and your style guide —
share them only with people you'd show that writing to.

No samples handy? Kick the tires with the bundled fake writer:

```bash
python3 tools/corpus_ingest.py --corpus examples/demo_samples --out build/demo.jsonl
python3 tools/analyze.py --corpus build/demo.jsonl --out build/demo_profile.json
python3 tools/eval.py --corpus build/demo.jsonl
```

## Why a scorer instead of "just prompt it"?

LLMs drift toward polished, neutral prose — the opposite of a personal voice.
The scorer makes the loop objective:

- **60+ features**: sentence-length distribution, discourse markers, paragraph
  openers, comma-splice density, first-person/hedge/intensifier rates,
  contractions, function-word cosine, spelling deviations, capitalisation
  anomalies, and **signature phrases auto-derived from your corpus**.
- **Capped "voice density" scoring**: LLM drafts fail in the *too clean*
  direction, so voice markers earn full credit from your average up to
  mean + 2σ — but past that the score drops again, because stuffing a draft
  with your phrases reads as caricature (see `ONE_SIDED` / `BAND_HIGH` in
  `tools/score.py`). Quirks (slips, lowercase "i", stray Capitals) are scored
  within 0.5×–1.5× your own rate.
- **AI-tell penalty**: words LLMs over-use (*delve, pivotal, underscore,
  showcase…*), em dashes, "not only X but Y" and noun-heavy phrasing are
  subtracted — but only the part above **your own** rate, so nothing you
  genuinely write is penalised. Low "burstiness" or plain vocabulary is
  deliberately *not* penalised: those checks misfire on non-native writers.
- **Ranked, located notes**: every failed feature becomes a concrete
  instruction with the points it costs and the sentences to change.

## Does it actually tell you apart from AI?

`tools/eval.py` measures it. Each of your documents is scored against a
profile built *without* it (leave-one-out) and compared with AI-written
impostors (`examples/impostors/`, plus any folder you pass with
`--impostors` — the skill's own drafts are the most realistic test), and with
"stuffed" copies of them padded with your markers to check the score can't be
gamed. It reports ROC-AUC (with a bootstrap CI), the equal-error rate and the
threshold that best separates the two; `--write-calibration` stores that
threshold as `score.py`'s default target. `--by-genre` scores each genre
against a profile built from the other genres.

On the author's own 12-document corpus, moving from v1 to v2 of the scorer
changed:

| | v1 | v2 |
|---|---|---|
| AUC, you vs AI impostors | 0.93 | 0.99 |
| AUC, you vs marker-stuffed AI text | 0.26 | 1.00 |
| stuffed AI texts passing | 6 / 6 | 0 / 6 |
| equal-error rate | 46% | 8% |

With a dozen documents these numbers are rough; more samples tighten them.

## Repo layout

| path | what |
|------|------|
| `tools/corpus_ingest.py` | samples → `build/corpus.jsonl` |
| `tools/analyze.py` | corpus → `build/profile.json` (+ signature phrases) |
| `tools/score.py` | grade a draft against the profile (report or `--json`) |
| `tools/eval.py` | your writing vs AI impostors: AUC, EER, calibrated target |
| `tools/stylometry.py` | shared feature extractor |
| `tools/make_skill.py` | package skill folder + zips + AGENTS.md into `dist/` |
| `templates/` | SKILL / AGENTS / plugin manifest templates + STYLE prompt |
| `samples/` | your writing (gitignored) |
| `examples/demo_samples/` | a fake writer to test the pipeline |
| `examples/impostors/` | AI-written texts the evaluation tests against |

Your personal artifacts — `samples/*`, `build/`, `dist/`, `STYLE.md` — are all
gitignored, so a fork stays safe to push.

## Fair use

This is a tool for drafting in **your own** voice: first drafts, emails,
routine reports, beating blank-page paralysis. Don't use it to submit
AI-written work where that's not allowed (courses, exams, publications), and
don't clone anyone's voice but your own without their consent.

## License

MIT — see [LICENSE](LICENSE).
