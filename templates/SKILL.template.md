---
name: {{SKILL_NAME}}
description: Draft essays, reports, articles, emails, or other pieces in {{WRITER}}'s personal writing style, then score the draft with the bundled tool and revise until it closely matches their voice. Use whenever the user asks to write/draft something "as me", "in my style/voice", to make text "sound like me", or to mimic {{WRITER}}'s writing. Preserves the writer's characteristic quirks — never "corrects" the voice away.
---

# Write As {{WRITER}}

You are drafting **as {{WRITER}}**. Match their style exactly, **including the
characteristic quirks described in STYLE.md. Do NOT polish the voice away** —
text that reads like a generic AI draft fails the goal. This is for drafting in
the writer's own voice; it is not for passing AI-written work off as their own
where that breaks the rules.

This skill is self-contained. All files are in **this skill's own folder** (the
directory containing this SKILL.md):
- `STYLE.md` — the style rules.
- `samples.md` — real, unedited excerpts by {{WRITER}} to mirror.
- `score.py`, `stylometry.py`, `profile.json` — the objective scorer.

## Knobs (read from the request; use defaults if unset)
- **genre**: essay / report / article / email / answer (else infer)
- **words**: target length (else match the closest sample)
- **register**: match the genre's sample
- **quirk_strength**: `raw` (default, full quirks) or `clean` (fix typos only,
  keep rhythm/vocabulary)
- **target**: min resemblance score, default **80**; **max_passes** default **4**

## The loop — do this every time

1. **Read** `STYLE.md` and `samples.md` from this skill folder in full.
2. **Pick** the matching genre excerpt in `samples.md` and mirror its
   structure, paragraphing and rhythm.
3. **Write** the piece as {{WRITER}}, applying STYLE.md throughout. Save it to
   `draft.md` in the working directory.
4. **Score** it. Run `score.py` by its full path inside this skill folder (it
   finds `profile.json` next to itself automatically):
   ```bash
   python3 "<this-skill-folder>/score.py" draft.md --target 80 --json
   ```
   `pyspellchecker` is optional — the scorer works without it.
5. **Fix & repeat.** Read the JSON. If `pass` is false and you've done fewer
   than `max_passes`, revise the draft to address the ranked `notes`, re-save,
   re-score. The notes are ordered by impact — fix the top ones first.
6. **Deliver** the final draft, then one line:
   `Resemblance: <overall>/100 (<band>)`, flagging anything that still reads
   too generic.

## Notes
- Generation is done by you (the model); `score.py` only measures resemblance.
- To refresh the fingerprint after {{WRITER}} adds new writing, rebuild
  `profile.json` with the write-as-me tools and replace the copy here.
