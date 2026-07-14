# Put your writing samples here

Drop **your own past writing** into this folder — `.txt`, `.md`, `.pdf` or
`.docx`. This is what the toolkit learns your voice from.

Guidelines:
- **8+ pieces works well**, more is better. A few hundred words each is plenty.
- **Cover the genres you'll want drafted** (emails, essays, reports, posts…).
- **Name files with a genre keyword** so they get tagged correctly:
  `email`, `letter`, `essay`, `report`, `article`, `blog`, `answer`
  (e.g. `email_to_landlord.txt`, `uni_essay_2024.pdf`).
- **Use unedited originals** — your quirks are the fingerprint. Don't clean
  them up first.

Privacy: this folder is **gitignored** (everything except this README), so
your writing never gets committed or pushed. Same for `build/`, `dist/` and
your generated `STYLE.md`.

No samples yet? Try the toolkit with the fake writer in `examples/demo_samples/`:

```
python3 tools/corpus_ingest.py --corpus examples/demo_samples
python3 tools/analyze.py
```
