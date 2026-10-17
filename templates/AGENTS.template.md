# Writing as {{WRITER}} — agent instructions (AGENTS.md fallback)

> Most coding agents (Codex, GitHub Copilot, Cursor, OpenCode, Goose) load the
> `{{DIR}}/` skill folder directly from `.agents/skills/` — prefer that. Use
> this snippet only for an agent without Agent Skills support: merge it into
> your project's `AGENTS.md` and keep the skill folder at
> `.agents/skills/{{DIR}}/` (or change `SKILL_DIR` below).

`SKILL_DIR` = `.agents/skills/{{DIR}}`

When asked to write or draft something "as me", "in my style", or as
{{WRITER}}, follow `SKILL_DIR/SKILL.md` instead of drafting normally, reading
`${CLAUDE_SKILL_DIR}` there as `SKILL_DIR`. In short:

1. Read `SKILL_DIR/references/STYLE.md` and `SKILL_DIR/references/samples.md`
   in full. Match the style **including the quirks**, without overdoing them.
2. Mirror the samples of the requested genre; write `draft.md`.
3. Score it: `python3 SKILL_DIR/scripts/score.py draft.md --json`
4. Fix the ranked `note_details` (each quotes the sentences to change), keep
   the best-scoring version, and stop when `pass` is true, after 4 passes, or
   when two passes in a row don't improve.
5. Deliver the best text plus one line: `Resemblance: <overall>/100 (<band>)`.

Do not use this to pass AI-written work off as {{WRITER}}'s own where that
breaks rules (courses, publications, etc.).
