# uniqueness-precheck

uniqueness-precheck scans a CSV or JSONL batch against your declared unique key *before* the database import, so one duplicate no longer aborts a 100k-row load. It reports duplicate groups with row-number samples, null/empty keys, and near-miss collisions (whitespace, case). Pure stdlib, offline. Confidence: High (≥80%) for all five rules, per the 65-case suite.

## Problem

The default way to learn your batch has duplicate keys is ` IntegrityError: duplicate key value violates unique constraint` — after the import has already failed, possibly mid-transaction, on row 87,341 of a file nobody wants to open. Nulls in key columns, `"abc "` vs `"abc"`, and `ABC` vs `abc` each fail differently on different databases. A five-second preflight turns a failed import into a fixable work order.

## How it works

1. **Input** — auto-detected CSV (with header) or JSONL; BOM and CRLF tolerated.
2. **Key spec** — `--key col1,col2` names one or more columns; composite keys are tuples.
3. **Rules** —
   - **duplicate-key** (error): the key tuple appears on 2+ rows; each group reports occurrence count and the first N row numbers (`--max-samples`, default 5).
   - **null-key** (error): a key component is missing or JSON `null`.
   - **empty-key** (error): the whole key is empty or whitespace-only.
   - **whitespace-collision** (warning): keys equal after stripping — one of them is probably a typo.
   - **case-collision** (warning): keys equal case-insensitively but distinct — flagged, not merged, because case-sensitivity is a schema decision.
4. **Exit contract** — 0 clean or warnings, 1 any conflict, 2 input/config failure (missing file, missing key column). `--json` for CI.

## Quickstart (~2 min)

```bash
# step 1: precheck a JSONL batch (~0.6 s for 100k rows)
python uniqueness_precheck.py batch.jsonl --key user_id
# step 2: composite key
python uniqueness_precheck.py batch.csv --key tenant_id,sku
# step 3: CI mode
python uniqueness_precheck.py batch.jsonl --key id --json
# full suite (~1 s)
python self_test.py   # SUMMARY: PASS 65/65 [Measured]
```

Library use: `scan(rows, ["id"], max_samples=5)` → dict with `rows`, `unique_keys`, `duplicate_groups`, `findings`.

## Why not X? (as of 2026-10-13)

**No direct equivalent found as of 2026-10-13** — no standalone stdlib-only pre-import key scanner with conflict sample lists was located in the searched space. Nearest adjacent options:

- **The database itself** — authoritative but last: it rejects the *whole batch* at import time, reports one offending row at a time, and offers no whitespace/case near-miss analysis.
- **pandas `duplicated()`** — two lines of code but requires the pandas stack, produces no per-group sample list, and silently treats `1` and `"1"` per its own dtype coercion rules.
- **csvlint / csvkit (csvvalid)** — CSV *syntax* validators; they check quoting and dialect, not business keys.
- **ETL frameworks (Airbyte/dbt tests)** — full pipelines with unique-tests, but they need infrastructure and run post-landing; this tool is the zero-setup gate you run on the file before it ships.

## Performance

All numbers [Measured] on this machine (Windows, Python 3.x, single run):

| Input | Time | Command |
|---|---|---|
| 100,000 JSONL rows, single key, clean | 0.597 s | see repro below |
| 65-case self-test suite | 0.84 s | `python self_test.py` |

Repro:

```bash
python -c "import time,uniqueness_precheck as m; rows=[{'id':'id-%d'%i} for i in range(100000)]; t0=time.perf_counter(); r=m.scan(rows,['id']); print('%.3f s'%(time.perf_counter()-t0), r['unique_keys'],'unique keys')"
```

## Minimal Fallback (PLAN B)

No Python: `sort batch.csv | uniq -d -f0` on the key column catches exact duplicates; `awk -F, 'NR>1 && $1=="" {print NR}' batch.csv` lists null keys. You lose composite keys, whitespace/case collision warnings, JSONL support, and the exit-code contract.

## Design Trade-offs

Priority order: **actionable-conflict-report > zero-false-merges > zero-dependency > speed**. Near-miss collisions (whitespace/case) are warnings, never errors: whether `ABC` and `abc` are the same customer is a business decision the tool refuses to make for you. Numbers and strings are distinct keys (`1` ≠ `"1"`) because that is exactly what most databases will decide. The sample list is capped (`--max-samples`) so a 1000-row duplicate group reports a pointer, not a wall of text. Unquoted ragged CSV rows are tolerated rather than rejected — the goal is key analysis, not dialect policing.

## Limits & Second-order Effects

- Key components are compared as strings; a schema that distinguishes `"01"` from `"1"` must normalize before scanning.
- Unicode case-collision uses `str.lower()` — full Unicode case-folding (ß/SS) is approximate.
- Very large duplicate groups produce one finding per group, not per row; join back with the reported row numbers for the full list.
- Second-order: teams may start "fixing" whitespace-collisions by stripping keys at ingest, which silently merges records that were intentionally distinct (`" room 1"` vs `"room 1"`) — treat the warning as a prompt to define a canonical key, not as license to mutate data.
- The scan sees only the file: rows already in the target table are out of scope unless you export and concatenate them.

## FAQ

**Q: Does it connect to the database?**
No — it scans the file. Zero credentials, zero network.

**Q: CSV with quoted commas inside key values?**
Handled — parsing uses the stdlib csv module with proper quote handling.

**Q: Why is case-collision a warning, not an error?**
Some schemas are case-sensitive by design (SKU codes); flagging it as an error would flood those users.

**Q: When NOT to use this tool?**
For streams where duplicates are legal (event logs keyed by timestamp+uuid is fine — but then use a real unique key), for files >memory-size (it loads rows in memory; ~100MB JSONL is comfortable, 10GB is not), or when your ETL already runs dbt unique tests post-load.

**Q: Does it modify the input file?**
Never — read-only.

## [Core Assumptions]

1. Batches arrive as whole files (CSV/JSONL) that fit in memory, keyed by one or more declared columns.
2. Duplicate detection is exact-tuple on string-normalized values; near-miss variants deserve human review, not auto-merge.
3. The pre-import stage is the cheapest place to catch conflicts — earlier than the database, earlier than the analyst.
4. Row numbers (1-based, data rows) are the useful join key back to the original file.

Confidence: High (≥80%) for the five rules (65-case suite); Medium (60–79%) for the memory-fit claim above ~100MB inputs — bounded by observation, not stress-tested. Data as of 2026-10-13.

---

Part of the [zhengming-toolbox](https://github.com/chenhz01/zhengming-toolbox) — 105 purpose-built AI-engineering tools across neglected niches.

Related tools: [primary-key-guard](https://github.com/chenhz01/primary-key-guard) · [slow-query-pattern-ledger](https://github.com/chenhz01/slow-query-pattern-ledger) · [baseline-drift-ledger](https://github.com/chenhz01/baseline-drift-ledger)
