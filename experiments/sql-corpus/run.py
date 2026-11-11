"""SQL acceptance corpus runner (README: rules, pins, what is not measured).

  python -I run.py --reference "DSN" --engine "DSN" [--cases DIR] [--repeat N] [--json FILE]

Both DSNs are libpq key/value strings for the PostgreSQL wire protocol. Every case in cases/ runs once on the reference
(PostgreSQL 18) and once on the engine under test (ArcadeDB's PostgreSQL wire server), through psycopg 3.
One line per case: `PASS|FAIL|ERROR case client text`, then one VERDICT line. Exit code 0 only when every case passes.

  PASS   the engine's result equals the reference result (complete multiset; in order only when the case has ORDER BY),
         or, for a case with `expect-error`, the engine failed with exactly that SQLSTATE.
  FAIL   the engine returned a different result, or an error (its SQLSTATE and message are in the text). Never hidden.
  ERROR  the corpus could not judge the case: the reference itself failed, or the case file is wrong.
"""
import argparse
import collections
import datetime
import decimal
import json
import os
import re
import statistics
import sys
import time

import psycopg

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = re.compile(r"--\s*([a-z-]+):\s*(.*)$")
CLIENT = "psycopg"


def load_cases(directory):
    cases = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".sql"):
            continue
        meta, body = {}, []
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                if not body and line.startswith("--"):
                    m = HEADER.match(line)
                    if m:
                        meta.setdefault(m.group(1), []).append(m.group(2).strip())
                    continue
                body.append(line)
        sql = "\n".join(body).strip().rstrip(";").strip()
        case = {"name": name[:-4], "sql": sql, "meta": meta}
        for key in ("purpose", "tables"):
            if not meta.get(key):
                case["error"] = f"missing header `-- {key}:`"
        if not sql:
            case["error"] = "empty statement"
        case["params"] = json.loads(meta["params"][0]) if "params" in meta else None
        case["mode"] = meta.get("mode", ["rows"])[0]
        case["write"] = meta.get("write", ["no"])[0] == "yes"
        case["types"] = meta.get("types", ["no"])[0] == "yes"
        case["expect_error"] = meta.get("expect-error", [None])[0]
        case["cleanup"] = meta.get("cleanup", [])
        case["ordered"] = bool(re.search(r"\border\s+by\b", sql, re.I))
        cases.append(case)
    return cases


def canon(v):
    """One hashable form per value. Numbers compare by value across int, float and numeric, so a wrong column TYPE is
    reported by the `types: yes` check, not by a value mismatch; bool, NULL, and text never equal a number."""
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float, decimal.Decimal)):
        if v != v or v in (float("inf"), float("-inf")):
            return ("special", repr(v))
        return ("num", decimal.Decimal(repr(v)) if isinstance(v, float) else decimal.Decimal(v))
    if isinstance(v, (bytes, bytearray, memoryview)):
        return ("bytes", bytes(v).hex())
    if isinstance(v, (datetime.date, datetime.time)):
        return ("text", v.isoformat())
    return ("text", str(v))


def run_statement(conn, case, sql):
    """One execution. Returns the outcome dict; the wall time covers execute plus fetch, as a client sees it."""
    params = case["params"]
    if params:
        sql = re.sub(r"\$(\d+)", "%s", sql)  # psycopg sends these as $n server-side parameters (extended protocol)
    t0 = time.perf_counter()
    try:
        with conn.cursor() as cur:
            if case["mode"] == "copy-out":
                with cur.copy(sql) as cp:
                    data = b"".join(bytes(chunk) for chunk in cp)
                rows = [tuple(line.split("\t")) for line in data.decode().splitlines()]
                out = {"rows": rows, "types": None, "names": None, "rowcount": len(rows)}
            else:
                cur.execute(sql, params)
                if cur.description is None:
                    out = {"rows": [], "types": None, "names": None, "rowcount": cur.rowcount}
                else:
                    out = {"rows": [tuple(r) for r in cur.fetchall()], "types": [c.type_code for c in cur.description],
                           "names": [c.name for c in cur.description], "rowcount": cur.rowcount}
        out.update(ok=True, ms=(time.perf_counter() - t0) * 1000)
        return out
    except psycopg.Error as e:
        return {"ok": False, "sqlstate": e.sqlstate, "message": " ".join(str(e).split()),
                "ms": (time.perf_counter() - t0) * 1000}
    except Exception as e:  # a protocol-level surprise (bad bytes, closed socket): still a recorded failure
        return {"ok": False, "sqlstate": None, "message": f"{type(e).__name__}: {' '.join(str(e).split())}",
                "ms": (time.perf_counter() - t0) * 1000}


class Engine:
    def __init__(self, name, dsn):
        self.name, self.dsn, self.conn = name, dsn, None

    def connect(self):
        t0 = time.perf_counter()
        try:
            self.conn = psycopg.connect(self.dsn, autocommit=True, connect_timeout=15)
            return {"ok": True, "ms": (time.perf_counter() - t0) * 1000}
        except Exception as e:
            self.conn = None
            return {"ok": False, "sqlstate": getattr(e, "sqlstate", None), "message": " ".join(str(e).split()),
                    "ms": (time.perf_counter() - t0) * 1000}

    def alive(self):
        if self.conn is None or self.conn.closed or self.conn.broken:
            return self.connect()["ok"]
        return True

    def run(self, case, sql, repeat=1):
        """First execution decides the verdict; the extra executions only feed the timing (read-only cases only)."""
        if not self.alive():
            return {"ok": False, "sqlstate": None, "message": "no connection", "ms": 0.0, "ms_all": []}
        first = run_statement(self.conn, case, sql)
        times = [first["ms"]]
        if first["ok"] and repeat > 1 and not case["write"] and not case["expect_error"]:
            for _ in range(repeat - 1):
                again = run_statement(self.conn, case, sql)
                if not again["ok"]:
                    break
                times.append(again["ms"])
        first["ms_all"] = times
        return first

    def cleanup(self, case):
        errors = []
        for stmt in case["cleanup"]:
            if self.alive():
                res = run_statement(self.conn, {**case, "params": None, "mode": "rows"}, stmt)
                if not res["ok"]:
                    errors.append(f"{self.name} cleanup failed: SQLSTATE {res['sqlstate']} {res['message'][:120]}")
        return errors


def compare(ref, got, case):
    """(True, '') when equal, else (False, first difference)."""
    if case["mode"] != "copy-out" and ref["types"] is None and got["types"] is None:
        if ref["rowcount"] != got["rowcount"]:
            return False, f"row count {got['rowcount']}, reference {ref['rowcount']}"
        return True, ""
    if (ref["types"] is None) != (got["types"] is None):
        return False, "one side returned a result set, the other did not"
    if ref["rows"] and got["rows"] and len(ref["rows"][0]) != len(got["rows"][0]):
        return False, f"{len(got['rows'][0])} columns, reference {len(ref['rows'][0])}"
    if case["types"] and ref["types"] != got["types"]:
        return False, f"column type OIDs {got['types']}, reference {ref['types']}"
    a = [tuple(canon(v) for v in row) for row in ref["rows"]]
    b = [tuple(canon(v) for v in row) for row in got["rows"]]
    if case["ordered"]:
        if a == b:
            return True, ""
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return False, f"first difference at row {i}: {got['rows'][i]!r}, reference {ref['rows'][i]!r}"
        return False, f"{len(b)} rows, reference {len(a)}"
    ca, cb = collections.Counter(a), collections.Counter(b)
    if ca == cb:
        return True, ""
    missing, extra = ca - cb, cb - ca
    parts = [f"{len(b)} rows, reference {len(a)}"]
    if missing:
        parts.append(f"{sum(missing.values())} reference row(s) missing, e.g. {next(iter(missing))[0:3]}")
    if extra:
        parts.append(f"{sum(extra.values())} extra row(s), e.g. {next(iter(extra))[0:3]}")
    return False, "; ".join(parts)


def judge(case, ref, got):
    if case["expect_error"]:
        want = case["expect_error"]
        if got["ok"]:
            return "FAIL", f"expected SQLSTATE {want}, the statement succeeded"
        if got["sqlstate"] == want:
            return "PASS", f"failed with SQLSTATE {want} as required: {got['message'][:150]}"
        return "FAIL", f"expected SQLSTATE {want}, got {got['sqlstate']}: {got['message'][:180]}"
    if not ref["ok"]:
        return "ERROR", f"the reference failed, SQLSTATE {ref['sqlstate']}: {ref['message'][:200]}"
    if not got["ok"]:
        return "FAIL", f"SQLSTATE {got['sqlstate']}: {got['message'][:240]}"
    same, diff = compare(ref, got, case)
    if same:
        if got["types"] is None and case["mode"] != "copy-out":
            return "PASS", f"row count {got['rowcount']} equal"
        return "PASS", f"{len(got['rows'])} rows equal" + (" in order" if case["ordered"] else " as a multiset")
    return "FAIL", diff[:300]


def timing_text(ref, got):
    def fmt(res):
        times = res.get("ms_all") or [res["ms"]]
        return f"{statistics.median(times):.2f} ms p50 of {len(times)}" if len(times) > 1 else f"{times[0]:.2f} ms"
    return f"[postgres {fmt(ref)}; arcadedb {fmt(got)}]"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True, help="libpq DSN of PostgreSQL 18")
    ap.add_argument("--engine", required=True, help="libpq DSN of ArcadeDB's PostgreSQL wire server")
    ap.add_argument("--cases", default=os.path.join(HERE, "cases"))
    ap.add_argument("--repeat", type=int, default=5, help="executions per read-only statement for the timing (>= 1)")
    ap.add_argument("--json", help="write one JSON object per case to this file")
    args = ap.parse_args()

    cases = load_cases(args.cases)
    if not cases:
        sys.exit(f"no cases found in {args.cases}")
    ref, eng = Engine("postgres", args.reference), Engine("arcadedb", args.engine)
    print(f"# client {CLIENT} {psycopg.__version__} (libpq {psycopg.pq.version()}), repeat {args.repeat}, "
          f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC")
    records, tally = [], collections.Counter()

    cref, ceng = ref.connect(), eng.connect()
    for e, c in ((ref, cref), (eng, ceng)):
        version = e.conn.info.parameter_status("server_version") if c["ok"] else None
        print(f"# {e.name} server_version {version}")
    if not cref["ok"]:
        print(f"ERROR connect {CLIENT} the reference refused the connection: {cref['message'][:200]}")
        sys.exit(2)
    connect_verdict = "PASS" if ceng["ok"] else "FAIL"
    print(f"{connect_verdict} connect {CLIENT} " + (f"[postgres {cref['ms']:.2f} ms; arcadedb {ceng['ms']:.2f} ms]"
          if ceng["ok"] else f"SQLSTATE {ceng['sqlstate']}: {ceng['message'][:240]}"))

    for case in cases:
        if "error" in case:
            verdict, text, r, g = "ERROR", f"case file: {case['error']}", None, None
        else:
            r = ref.run(case, case["sql"], args.repeat)
            g = eng.run(case, case["sql"], args.repeat)
            verdict, text = judge(case, r, g)
            if r["ok"] and g["ok"]:
                text += " " + timing_text(r, g)
            for note in ref.cleanup(case) + eng.cleanup(case):
                text += f" ({note})"
        tally[verdict] += 1
        print(f"{verdict} {case['name']} {CLIENT} {text}")
        records.append({"case": case["name"], "client": CLIENT, "verdict": verdict, "text": text,
                        "sql": case["sql"], "ordered": case["ordered"],
                        "postgres": r, "arcadedb": g})
        sys.stdout.flush()

    client_verdict = "PASS" if connect_verdict == "PASS" and tally["PASS"] == len(cases) else "FAIL"
    print(f"VERDICT {CLIENT} {client_verdict} connect={connect_verdict} cases={len(cases)} PASS={tally['PASS']} "
          f"FAIL={tally['FAIL']} ERROR={tally['ERROR']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, default=str) + "\n")
    sys.exit(0 if client_verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
