# Manual document-upload smoke fixtures

These tiny files contain synthetic facts only. They are prepared for the owner
to upload one at a time after the intended Frankfurt Render commit is verified.
Do not upload them during local packaging or use production data.

| File | Expected extracted fact |
| --- | --- |
| evidenceai_smoke.pdf | The Atlas rehearsal vault stores 73 amber markers. |
| evidenceai_smoke.docx | The Lumen survey cabinet stores 28 violet seals. |
| evidenceai_smoke.md | The Cedar Gate archive contains 19 copper tags. |

For each file: authenticate at /library, upload it, search the exact fact on
/, verify the returned source quote, replace it with a new unique fact, verify
the replacement, then delete the managed upload. Record the upload ID and
confirm that the managed-upload table is empty afterward. Never use existing
corpus records for destructive checks.
