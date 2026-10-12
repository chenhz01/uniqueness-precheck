#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uniqueness-precheck — pre-import duplicate-key scanner.

Scans a CSV (with header) or JSONL file against a declared unique key and
produces a conflict sample list BEFORE the database rejects the whole batch.

Rules:
  duplicate-key      (error)   key tuple appears on 2+ rows
  null-key           (error)   a key component is missing/None
  empty-key          (error)   the whole key is empty or whitespace
  whitespace-collision (warning) keys differ only by surrounding whitespace
  case-collision     (warning) keys differ only by ASCII case

Exit codes: 0 clean-or-warnings, 1 conflicts found, 2 input/config failure.
Pure stdlib. Python 3.8+.
"""
import argparse
import csv
import io
import json
import sys

__version__ = "0.1.1"

MAX_SAMPLES_DEFAULT = 5


def load_rows(text):
    """Auto-detect CSV vs JSONL; return (rows, source, errors).

    rows are dicts. errors is a list of {line, message}.
    """
    text = text.lstrip("\ufeff")
    stripped = text.lstrip()
    if not stripped:
        return [], "empty", []
    if stripped.startswith("{") or stripped.startswith("["):
        rows, errs = [], []
        for ln, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:
                errs.append({"line": ln, "message": "invalid JSONL: %s" % e})
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                errs.append({"line": ln, "message": "JSONL line is not an object"})
        return rows, "jsonl", errs
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for i, row in enumerate(reader):
        rows.append(dict(row))
    return rows, "csv", []


def _component(row, col):
    v = row.get(col)
    if v is None:
        return None
    return str(v)


def scan(rows, key_cols, max_samples=MAX_SAMPLES_DEFAULT):
    """Scan rows against key_cols; return report dict."""
    findings = []

    def add(rule, severity, row_no, msg):
        findings.append({"rule": rule, "severity": severity,
                         "row": row_no, "message": msg})

    groups = {}          # exact key tuple -> [row_no]
    stripped_index = {}  # stripped key -> {key variant: first row}
    case_index = {}      # lower key -> {key variant: first row}
    dup_groups = 0
    for i, row in enumerate(rows, 1):  # row numbers are 1-based, data rows
        parts = [_component(row, c) for c in key_cols]
        if any(p is None for p in parts):
            add("null-key", "error", i,
                "key %s missing component (row %d)" % (key_cols, i))
            continue
        if all(p.strip() == "" for p in parts):
            add("empty-key", "error", i, "entire key is empty (row %d)" % i)
            continue
        kt = tuple(parts)
        groups.setdefault(kt, []).append(i)
        sk = tuple(p.strip() for p in parts)
        stripped_index.setdefault(sk, {})[kt] = i
        ck = tuple(p.lower() for p in parts)
        case_index.setdefault(ck, {})[kt] = i
    for kt, rowsn in groups.items():
        if len(rowsn) > 1:
            dup_groups += 1
            add("duplicate-key", "error", rowsn[0],
                "key %s appears %d time(s): rows %s (showing first %d)"
                % (list(kt), len(rowsn), rowsn[:max_samples],
                   min(len(rowsn), max_samples)))
    for sk, variants in stripped_index.items():
        if len(variants) > 1:
            add("whitespace-collision", "warning", min(variants.values()),
                "keys differ only by whitespace: %s"
                % [list(v) for v in variants])
    for ck, variants in case_index.items():
        if len(variants) > 1:
            add("case-collision", "warning", min(variants.values()),
                "keys differ only by case: %s" % [list(v) for v in variants])
    errors = [f for f in findings if f["severity"] == "error"]
    findings.sort(key=lambda f: (f["row"], f["rule"]))
    return {"rows": len(rows), "key": key_cols,
            "unique_keys": sum(1 for v in groups.values() if len(v) == 1),
            "duplicate_groups": dup_groups,
            "errors": len(errors),
            "warnings": len(findings) - len(errors),
            "findings": findings}


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="uniqueness-precheck",
        description="Pre-import duplicate-key scanner for CSV/JSONL batches "
                    "with conflict sample list.")
    p.add_argument("file", help="CSV (with header) or JSONL file "
                                "('-' for stdin)")
    p.add_argument("--key", required=True,
                   help="comma-separated key column names")
    p.add_argument("--max-samples", type=int, default=MAX_SAMPLES_DEFAULT,
                   help="max example rows shown per duplicate group")
    p.add_argument("--json", action="store_true")
    p.add_argument("--version", action="version",
                   version="%(prog)s " + __version__)
    args = p.parse_args(argv)
    key_cols = [c.strip() for c in args.key.split(",") if c.strip()]
    if not key_cols:
        print("error: --key must name at least one column", file=sys.stderr)
        return 2
    try:
        if args.file == "-":
            text = sys.stdin.read()
        else:
            with open(args.file, "r", encoding="utf-8-sig", newline="") as f:
                text = f.read()
    except OSError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print("error: cannot read %s: %s" % (args.file, e), file=sys.stderr)
        return 2
    rows, source, parse_errors = load_rows(text)
    if source != "empty":
        missing = [c for c in key_cols
                   if rows and all(c not in r for r in rows[:50])]
        if rows and missing:
            if args.json:
                print(json.dumps({"error": "key column(s) not found: %s"
                                            % missing}))
            else:
                print("error: key column(s) not found in input: %s" % missing,
                      file=sys.stderr)
            return 2
    result = scan(rows, key_cols, max_samples=args.max_samples)
    result["source"] = source
    result["parse_errors"] = parse_errors
    for pe in parse_errors:
        result["findings"].append({"rule": "parse-error", "severity": "error",
                                   "row": pe["line"], "message": pe["message"]})
    has_errors = result["errors"] > 0 or bool(parse_errors)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for f in result["findings"]:
            print("%-20s %-7s row %s: %s"
                  % (f["rule"], f["severity"], f["row"], f["message"]))
        print("source=%s rows=%d unique_keys=%d duplicate_groups=%d "
              "%d error(s), %d warning(s)"
              % (source, result["rows"], result["unique_keys"],
                 result["duplicate_groups"], result["errors"],
                 result["warnings"]))
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
