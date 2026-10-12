# -*- coding: utf-8 -*-
"""self_test for uniqueness-precheck — v2 template, four defenses:
1) SystemExit/Exception capture  2) Unicode-safe matching
3) fixtures written with newline=""  4) last line: SUMMARY: PASS n/n
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uniqueness_precheck as mod  # noqa: E402

main = mod.main


def run_cli(argv):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            code = main(argv) or 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # noqa: BLE001
        code = 1
        buf_err.write(repr(e))
    return code, buf_out.getvalue(), buf_err.getvalue()


FIX = tempfile.mkdtemp(prefix="uq_selftest_")


def wfile(name, content):
    path = os.path.join(FIX, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


def jrow(**kw):
    return json.dumps(kw)


def rules(text):
    rows, _src, _errs = mod.load_rows(text)
    return [f["rule"] for f in mod.scan(rows, ["id"])["findings"]]


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


CLEAN_JSONL = "\n".join([jrow(id="a", v=1), jrow(id="b", v=2), jrow(id="c", v=3)])
CLEAN_CSV = "id,v\na,1\nb,2\nc,3\n"
DUP_JSONL = "\n".join([jrow(id="a"), jrow(id="b"), jrow(id="a")])


# ---------- [A] functional ----------
@case("clean JSONL passes")
def t01():
    rows, src, errs = mod.load_rows(CLEAN_JSONL)
    r = mod.scan(rows, ["id"])
    assert r["errors"] == 0 and r["unique_keys"] == 3 and src == "jsonl", r


@case("clean CSV passes")
def t02():
    rows, src, _ = mod.load_rows(CLEAN_CSV)
    r = mod.scan(rows, ["id"])
    assert r["errors"] == 0 and r["unique_keys"] == 3 and src == "csv", r


@case("duplicate-key fires")
def t03():
    assert "duplicate-key" in rules(DUP_JSONL)


@case("duplicate group count correct")
def t04():
    rows, _, _ = mod.load_rows(DUP_JSONL)
    r = mod.scan(rows, ["id"])
    assert r["duplicate_groups"] == 1 and r["rows"] == 3, r


@case("triple duplicate reported once as one group")
def t05():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="x")] * 3))
    r = mod.scan(rows, ["id"])
    assert r["duplicate_groups"] == 1
    assert len([f for f in r["findings"]
                if f["rule"] == "duplicate-key"]) == 1


@case("null-key fires for missing field")
def t06():
    assert "null-key" in rules(jrow(name="no id here"))


@case("null-key fires for JSON null")
def t07():
    assert "null-key" in rules(jrow(id=None))


@case("empty-key fires for whitespace key")
def t08():
    assert "empty-key" in rules(jrow(id="   "))


@case("empty-key not fired for '0'")
def t09():
    rows, _, _ = mod.load_rows(jrow(id="0"))
    r = mod.scan(rows, ["id"])
    assert r["errors"] == 0, r


@case("whitespace-collision warning fires")
def t10():
    r = rules("\n".join([jrow(id="abc"), jrow(id="abc ")]))
    assert "whitespace-collision" in r and "duplicate-key" not in r, r


@case("case-collision warning fires")
def t11():
    r = rules("\n".join([jrow(id="abc"), jrow(id="ABC")]))
    assert "case-collision" in r and "duplicate-key" not in r, r


@case("exact duplicate also implies case group but no warning spam")
def t12():
    r = rules("\n".join([jrow(id="abc"), jrow(id="abc")]))
    assert "case-collision" not in r and "duplicate-key" in r, r


@case("composite key via scan()")
def t13():
    rows = [{"a": "1", "b": "2"}, {"a": "1", "b": "3"}, {"a": "1", "b": "2"}]
    r = mod.scan(rows, ["a", "b"])
    assert r["duplicate_groups"] == 1 and r["unique_keys"] == 1, r


@case("composite key different tuples are distinct")
def t14():
    rows = [{"a": "1", "b": "2"}, {"a": "1", "b": "3"}]
    assert mod.scan(rows, ["a", "b"])["errors"] == 0


@case("sample list capped by max_samples")
def t15():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="k")] * 10))
    r = mod.scan(rows, ["id"], max_samples=3)
    f = [f for f in r["findings"] if f["rule"] == "duplicate-key"][0]
    assert "rows [1, 2, 3]" in f["message"], f


@case("csv quoted commas in values handled")
def t16():
    rows, src, _ = mod.load_rows('id,v\n"x,y",1\n"z",2\n')
    assert src == "csv" and mod.scan(rows, ["id"])["errors"] == 0


@case("csv duplicate with commas in keys")
def t17():
    rows, _, _ = mod.load_rows('id\n"a,b"\n"a,b"\n')
    r = mod.scan(rows, ["id"])
    assert r["duplicate_groups"] == 1, r


@case("json parse error collected")
def t18():
    rows, _, errs = mod.load_rows('{"id":"a"}\nNOTJSON\n')
    assert len(errs) == 1 and rows, errs


@case("jsonl non-object line collected as error")
def t19():
    _, _, errs = mod.load_rows('[1,2]\n')
    assert len(errs) == 1, errs


@case("empty string source detected")
def t20():
    rows, src, _ = mod.load_rows("")
    assert src == "empty" and rows == []


@case("report totals consistent")
def t21():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="a"), jrow(id="a"),
                                          jrow(id="b")]))
    r = mod.scan(rows, ["id"])
    assert r["rows"] == 3 and r["unique_keys"] == 1 and r["duplicate_groups"] == 1


# ---------- [A] CLI ----------
@case("CLI clean exits 0")
def t22():
    path = wfile("ok.jsonl", CLEAN_JSONL)
    code, out, _ = run_cli([path, "--key", "id"])
    assert code == 0 and "0 error(s)" in out, out


@case("CLI duplicate exits 1")
def t23():
    path = wfile("dup.jsonl", DUP_JSONL)
    code, out, _ = run_cli([path, "--key", "id"])
    assert code == 1 and "duplicate-key" in out, out


@case("CLI csv input works")
def t24():
    path = wfile("ok.csv", CLEAN_CSV)
    code, out, _ = run_cli([path, "--key", "id"])
    assert code == 0 and "source=csv" in out, out


@case("CLI --json parseable")
def t25():
    path = wfile("d2.jsonl", DUP_JSONL)
    code, out, _ = run_cli([path, "--key", "id", "--json"])
    data = json.loads(out)
    assert code == 1 and data["duplicate_groups"] == 1


@case("CLI stdin works")
def t26():
    buf = io.StringIO(CLEAN_JSONL)
    old = sys.stdin
    sys.stdin = buf
    try:
        code, out, _ = run_cli(["-", "--key", "id"])
    finally:
        sys.stdin = old
    assert code == 0 and "unique_keys=3" in out, out


@case("CLI --max-samples respected")
def t27():
    path = wfile("many.jsonl", "\n".join([jrow(id="k")] * 7))
    code, out, _ = run_cli([path, "--key", "id", "--max-samples", "2"])
    assert code == 1 and "rows [1, 2]" in out, out


@case("warning-only exits 0")
def t28():
    path = wfile("w.jsonl", "\n".join([jrow(id="a"), jrow(id="A")]))
    code, _, _ = run_cli([path, "--key", "id"])
    assert code == 0


@case("parse error in JSONL exits 1")
def t29():
    path = wfile("bad.jsonl", '{"id":"a"}\nOOPS\n')
    code, out, _ = run_cli([path, "--key", "id"])
    assert code == 1 and "parse-error" in out, out


# ---------- [B] error paths ----------
@case("missing file exits 2")
def t30():
    code, _, err = run_cli([os.path.join(FIX, "nope.jsonl"), "--key", "id"])
    assert code == 2 and "cannot read" in err, err


@case("missing file --json prints json error")
def t31():
    code, out, _ = run_cli([os.path.join(FIX, "nope.jsonl"), "--key", "id",
                            "--json"])
    assert code == 2 and "error" in json.loads(out)


@case("missing key column exits 2")
def t32():
    path = wfile("nk.jsonl", jrow(foo="1"))
    code, _, err = run_cli([path, "--key", "id"])
    assert code == 2 and "not found" in err, err


@case("missing --key exits 2 via argparse")
def t33():
    path = wfile("any.jsonl", CLEAN_JSONL)
    code, _, _ = run_cli([path])
    assert code == 2


@case("empty --key value exits 2")
def t34():
    code, _, err = run_cli(["-", "--key", ","])
    assert code == 2 and "at least one" in err


@case("directory as input exits 2")
def t35():
    assert run_cli([FIX, "--key", "id"])[0] == 2


@case("no positional file exits 2")
def t36():
    try:
        main(["--key", "id"])
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code == 2


@case("--help exits 0")
def t37():
    code, out, _ = run_cli(["--help"])
    assert code == 0 and "usage" in out.lower()


@case("--version exits 0")
def t38():
    code, out, _ = run_cli(["--version"])
    assert code == 0 and "0.1.1" in out


@case("unknown flag exits 2")
def t39():
    assert run_cli(["--bogus"])[0] == 2


@case("findings always have four keys")
def t40():
    rows, _, _ = mod.load_rows(DUP_JSONL)
    for f in mod.scan(rows, ["id"])["findings"]:
        assert set(f) == {"rule", "severity", "row", "message"}


# ---------- [C] extreme edge ----------
@case("empty input: zero rows zero findings")
def t41():
    rows, src, _ = mod.load_rows("")
    r = mod.scan(rows, ["id"])
    assert r["rows"] == 0 and r["findings"] == []


@case("whitespace-only input")
def t42():
    rows, src, _ = mod.load_rows("   \n\n")
    assert src == "empty"


@case("single row passes")
def t43():
    rows, _, _ = mod.load_rows(jrow(id="solo"))
    assert mod.scan(rows, ["id"])["errors"] == 0


@case("unicode keys")
def t44():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="订单-1"), jrow(id="订单-2")]))
    assert mod.scan(rows, ["id"])["errors"] == 0


@case("unicode duplicates detected")
def t45():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="订单"), jrow(id="订单")]))
    assert mod.scan(rows, ["id"])["duplicate_groups"] == 1


@case("unicode case-collision uses lower()")
def t46():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="Ärger"), jrow(id="ärger")]))
    assert "case-collision" in [f["rule"] for f in mod.scan(rows, ["id"])["findings"]]


@case("CRLF JSONL tolerated")
def t47():
    rows, _, _ = mod.load_rows(jrow(id="a") + "\r\n" + jrow(id="b") + "\r\n")
    assert len(rows) == 2


@case("CRLF CSV tolerated")
def t48():
    rows, _, _ = mod.load_rows("id,v\r\na,1\r\nb,2\r\n")
    assert len(rows) == 2 and mod.scan(rows, ["id"])["errors"] == 0


@case("BOM prefix tolerated")
def t49():
    rows, _, _ = mod.load_rows("\ufeff" + CLEAN_JSONL)
    assert mod.scan(rows, ["id"])["errors"] == 0


@case("very long key value (50k chars)")
def t50():
    rows, _, _ = mod.load_rows(jrow(id="x" * 50000))
    assert mod.scan(rows, ["id"])["errors"] == 0


@case("100k rows performance path")
def t51():
    rows = [{"id": "id-%d" % i, "v": i} for i in range(100000)]
    r = mod.scan(rows, ["id"])
    assert r["unique_keys"] == 100000 and r["errors"] == 0


@case("all rows identical (1000 dups, capped samples)")
def t52():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="same")] * 1000))
    r = mod.scan(rows, ["id"], max_samples=5)
    assert r["duplicate_groups"] == 1 and r["unique_keys"] == 0


@case("key value that looks like number stays string")
def t53():
    rows, _, _ = mod.load_rows('{"id": 1}\n{"id": "1"}\n')
    r = mod.scan(rows, ["id"])
    assert r["duplicate_groups"] == 1, r


@case("whitespace-collision with multiple variants")
def t54():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="a"), jrow(id="a "),
                                          jrow(id=" a")]))
    ws = [f for f in mod.scan(rows, ["id"])["findings"]
          if f["rule"] == "whitespace-collision"]
    assert len(ws) == 1, ws


@case("extra columns ignored")
def t55():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="a", extra=1, x=2),
                                          jrow(id="b", other="z")]))
    assert mod.scan(rows, ["id"])["errors"] == 0


@case("duplicate across far-apart rows")
def t56():
    rows, _, _ = mod.load_rows("\n".join(
        [jrow(id="first")] + [jrow(id="m%d" % i) for i in range(500)] +
        [jrow(id="first")]))
    r = mod.scan(rows, ["id"])
    assert r["duplicate_groups"] == 1, r


@case("emoji key values")
def t57():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="🎉1"), jrow(id="🎉2")]))
    assert mod.scan(rows, ["id"])["errors"] == 0


@case("repeated runs deterministic")
def t58():
    rows, _, _ = mod.load_rows(DUP_JSONL)
    assert mod.scan(rows, ["id"]) == mod.scan(rows, ["id"])


@case("csv with ragged rows tolerated")
def t59():
    rows, _, _ = mod.load_rows("id,v\na,1,extra\nb,2\n")
    r = mod.scan(rows, ["id"])
    assert r["rows"] == 2, r


@case("mixed null and dup errors counted separately")
def t60():
    rows, _, _ = mod.load_rows("\n".join([jrow(id="a"), jrow(id="a"),
                                          jrow(name="noid")]))
    r = mod.scan(rows, ["id"])
    assert r["errors"] == 2, r


@case("full pipeline contract")
def t61():
    path = wfile("c61.jsonl", DUP_JSONL)
    code, out, _ = run_cli([path, "--key", "id"])
    assert code == 1 and "duplicate_groups=1" in out and "rows [1, 3]" in out, out


@case("summary line format stable")
def t62():
    path = wfile("c62.jsonl", CLEAN_JSONL)
    code, out, _ = run_cli([path, "--key", "id"])
    assert "source=jsonl rows=3 unique_keys=3 duplicate_groups=0 0 error(s), 0 warning(s)" in out, out


@case("empty CSV body with only header")
def t63():
    rows, _, _ = mod.load_rows("id,v\n")
    r = mod.scan(rows, ["id"])
    assert r["rows"] == 0 and r["findings"] == []


@case("tab-separated values not supported but safe")
def t64():
    rows, src, _ = mod.load_rows("id\tv\na\t1\n")
    # treated as csv with one weird column name; must not crash
    assert src == "csv"


@case("key column present but empty header name")
def t65():
    rows, _, _ = mod.load_rows(",v\na,1\n")
    rows2 = [{"": "a", "v": "1"}]
    assert mod.scan(rows2, [""])["unique_keys"] == 1


class ToolTests(unittest.TestCase):
    pass


def _name(i, n):
    return "test_%03d_%s" % (i, re.sub(r"\W+", "_", n))


for _i, (_n, _fn) in enumerate(CASES):
    setattr(ToolTests, _name(_i, _n), lambda self, _f=_fn: _f())


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
    total, fails = r.testsRun, len(r.failures) + len(r.errors)
    for t, _ in r.failures + r.errors:
        print("FAIL:", t.id().split(".")[-1])
    print("SUMMARY: PASS %d/%d" % (total - fails, total))
    sys.exit(0 if fails == 0 else 1)
