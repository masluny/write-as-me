# STYLE_PROMPT.md — have your AI author your STYLE.md

After running `corpus_ingest.py` + `analyze.py`, give your coding agent
(Claude Code, Codex, etc.) this prompt — it reads your samples and writes the
style guide the skill will follow. Review the result; you know your voice best.

---

Read every writing sample in `samples/` (or the extracted text in
`build/corpus.jsonl`) and the quantitative fingerprint in `build/profile.json`
(note the auto-derived `signature_ngrams`). Then write `STYLE.md` at the repo
root describing how I write, so an AI can draft new text indistinguishable in
style from mine.

Treat my quirks as **features to preserve, not errors to fix** — unusual
grammar, punctuation habits, spelling slips, capitalisation, filler phrases:
document them so they can be reproduced at a natural density.

Structure STYLE.md as:

1. **The non-negotiables** — the 5–8 habits that must appear in every piece.
2. **Structure by genre** — how I open, develop and close each genre found in
   the samples (essay / report / article / email / answer …), with my actual
   phrases quoted as anchors.
3. **Sentences & rhythm** — typical length, how I chain clauses, punctuation
   habits, paragraph size.
4. **Voice & stance** — person, hedging, intensity, tone, how much opinion.
5. **Vocabulary** — words and phrases I actually use (quote them), and fancy
   synonyms to avoid.
6. **Quirks to preserve** — my fingerprint: each quirk with 1–2 real quoted
   examples and a note on how often to use it (sprinkle, don't overdo).
7. **Anti-patterns** — what would give away an AI draft of "me" (generic
   AI vocabulary, uniform sentence lengths, zero quirks, em-dash habits …).
8. **Quick self-check** — a checklist a draft must pass.

Quote real fragments from my samples throughout — concrete anchors beat
abstract descriptions. Keep it under ~120 lines so it fits comfortably in a
prompt.
