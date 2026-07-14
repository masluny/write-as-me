# Writing as {{WRITER}} — agent instructions (Codex / AGENTS.md)

> Merge this into your project's `AGENTS.md` (Codex reads it automatically),
> and keep the generated `{{DIR}}/` skill folder in the project root.

When asked to write or draft something "as me", "in my style", or as
{{WRITER}}, follow this procedure instead of drafting normally:

1. Read `{{DIR}}/STYLE.md` and `{{DIR}}/samples.md` in full. Match the style
   exactly, **including the characteristic quirks — do not polish the voice
   away**.
2. Pick the sample excerpt closest to the requested genre and mirror its
   structure, paragraphing and rhythm.
3. Write the draft and save it to `draft.md`.
4. Score it:
   ```bash
   python3 {{DIR}}/score.py draft.md --target 80 --json
   ```
5. If `pass` is false (and fewer than 4 passes so far): revise the draft to
   address the ranked `notes` in the JSON, re-save, re-score.
6. Deliver the final text plus one line: `Resemblance: <overall>/100 (<band>)`.

Do not use this to pass AI-written work off as {{WRITER}}'s own where that
breaks rules (courses, publications, etc.).
