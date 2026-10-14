# Loop notes — the agent's working memory

READ THIS FIRST every run. This file is NOT a log — run history lives in the
dashboard (`loop_run_events`). Write here ONLY when you found and fixed a real
bug. `notes_lint.py` enforces the rules (dedupe, 50-line cap, format) — the rules
below are not optional.

Notes format (ONE line per finding, newest first, no pipe characters inside a field):

`[YYYY-MM-DD] <region> | <area: tab/module/parser> | <symptom signature: how to detect> | <root cause> | <file/fix location> | <one-line lesson for the next run>`

Rules:
- A clean run (covered / no_data / bad_login) writes NOTHING here.
- Same portal + same symptom again → the lint bumps an `xN` counter instead of
  adding a line.
- Hard cap 50 lines; the lint moves the oldest overflow to LOOP_NOTES_ARCHIVE.md.
- Never put patient names or NIKs here — the lint strips them.

## Notes

## Known-empty
(one line per puskesmas: `[YYYY-MM-DD] <region> | <date range checked> | <why>`)
(none yet)
