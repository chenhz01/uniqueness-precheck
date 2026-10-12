# Changelog

## v0.1.1 — 2026-10-13
- Round-2 fix found by self-audit: a JSONL file whose first line is an array (`[1,2]`) was silently parsed as CSV; the auto-detector now routes `[`-prefixed input through the JSONL branch and reports "not an object" parse errors.
- Self-test re-run: `python self_test.py` → `SUMMARY: PASS 65/65` (was 64/65 at first draft).

## v0.1.0 — 2026-10-13
- Initial implementation: CSV/JSONL auto-detection (BOM/CRLF tolerant), `--key` composite key spec, five rules (duplicate-key with capped row samples / null-key / empty-key / whitespace-collision / case-collision), conflict sample list, CLI (file/stdin, `--max-samples`, `--json`, exit 0/1/2 contract).
- Self-test suite (functional / error / extreme-edge tiers), 65 cases at first draft.
