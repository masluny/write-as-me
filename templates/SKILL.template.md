---
name: {{SKILL_NAME}}
description: Drafts text in {{WRITER}}'s personal writing style and checks it against their real stylometric fingerprint. Use when asked to write anything "as me", "in my voice/style", or to sound like {{WRITER}}.
compatibility: Requires python3 3.9+ (standard library only); pyspellchecker optional.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/score.py *)
---

# Write As {{WRITER}}

You are drafting **as {{WRITER}}**. Match their style exactly, **including the
characteristic quirks described in the style guide. Do NOT polish the voice
away**, and don't overdo it either: a caricature fails just like a generic AI
draft. This is for drafting in the writer's own voice; it is not for passing
AI-written work off as their own where that breaks the rules.

Everything is in this skill's folder, `${CLAUDE_SKILL_DIR}` (the directory
containing this SKILL.md; paths below are relative to it):
- `references/STYLE.md`: the style rules.
- `references/samples.md`: real, unedited writing by {{WRITER}}, by genre.
- `scripts/score.py`: the scorer (finds `assets/profile.json` itself).

## Knobs (read from the request; use defaults if unset)
- **genre**: essay / report / article / email / answer (else infer)
- **words**: target length (else match the closest sample)
- **quirk_strength**: `raw` (default, full quirks) or `clean` (fix typos only,
  keep rhythm/vocabulary)
- **target**: pass score. Default: the value calibrated for this writer,
  which score.py applies by itself. Pass `--target` only if asked.
- **max_passes**: default **4**

## Before writing

Use the user's own material: facts, events, names, opinions. Never invent
personal details. If something essential is missing, ask; otherwise keep it
general. Invented specifics are the fastest giveaway.

## The loop

1. **Read** `references/STYLE.md` and `references/samples.md` in full.
2. **Mirror** the samples of the same genre (structure, paragraphing,
   rhythm). Pick by genre, not by topic.
3. **Write** the piece as {{WRITER}} and save it to `draft.md` in the working
   directory.
4. **Score** it:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/score.py draft.md --json
   ```
5. **Fix** the ranked `note_details`, biggest `points` first. Each note's
   `look_at` quotes the sentences causing it, so edit those. An *overdone*
   note matters as much as a *missing* one: never stuff markers, phrases or
   quirks to raise the score. If `ai_penalty` > 0, first remove the listed
   AI-tell words and em dashes.
6. **Keep the best.** Whenever a pass beats your best score, copy it to
   `draft.best.md`. Stop when `pass` is true, after `max_passes`, or when two
   passes in a row don't beat the best (or one drops by more than 3 points).
   More passes after a plateau usually make the text worse.
7. **Deliver** the best version, then one line:
   `Resemblance: <overall>/100 (<band>)`. Mention any scorer `warnings`
   and anything that still reads generic.

## Notes
- Generation is done by you (the model); `score.py` only measures resemblance.
- To refresh the fingerprint after {{WRITER}} adds new writing, rebuild
  `profile.json` with the write-as-me tools (`analyze.py`, then
  `eval.py --write-calibration`) and replace `assets/profile.json`.
