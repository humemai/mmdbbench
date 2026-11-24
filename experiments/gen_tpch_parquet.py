#!/usr/bin/env python3
"""One-time prep for the l1tpc lane: the TPC-H `lineitem` and `part` tables as parquet, from DuckDB's own `tpch` extension.

The lane (`l1_tpc.py`) reads `$BENCH_TPC_DATA/sf<SF>_lineitem.parquet` and `sf<SF>_part.parquet`. The data is generated, not
downloaded: `CALL dbgen(sf=N)` is deterministic, and the tables are written in key order so that the parquet order does not
depend on the number of threads. The script prints the row counts and two column sums; a reproduction compares them with the
numbers in docs/reproduce.md before it trusts the data (the file bytes depend on the DuckDB version, the rows do not).

Usage (from experiments/, `uv` only):
  export BENCH_TPC_DATA=$HOME/bench-data/tpch
  uv run --no-project --with duckdb==1.5.6 python gen_tpch_parquet.py --sf 1

DuckDB installs its `tpch` extension from extensions.duckdb.org on the first call, so the machine needs network access once.
`--sf 1` is the `tpch1` scale of the lane; `--sf 10` is its large size and takes about 15 GB of memory and 10 GB of disk.
"""
import argparse
import os
import sys

import duckdb


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sf", type=int, default=1, help="TPC-H scale factor (1 or 10)")
    ap.add_argument("--out", default=os.environ.get("BENCH_TPC_DATA") or os.path.join(os.path.expanduser("~"), "bench-data", "tpch"),
                    help="output directory (default: $BENCH_TPC_DATA, else ~/bench-data/tpch)")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    cx = duckdb.connect(":memory:")
    cx.execute("INSTALL tpch")
    cx.execute("LOAD tpch")
    cx.execute(f"CALL dbgen(sf={args.sf})")
    for table, key in (("lineitem", "l_orderkey, l_linenumber"), ("part", "p_partkey")):
        path = os.path.join(args.out, f"sf{args.sf}_{table}.parquet")
        cx.execute(f"COPY (SELECT * FROM {table} ORDER BY {key}) TO '{path}' (FORMAT parquet)")
        n = cx.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        print(f"{path}: {n} rows, {os.path.getsize(path)} bytes")
    li = cx.execute("SELECT count(*), sum(l_quantity), sum(l_extendedprice) FROM lineitem").fetchone()
    pa = cx.execute("SELECT count(*), sum(p_retailprice) FROM part").fetchone()
    print(f"lineitem: count={li[0]} sum(l_quantity)={li[1]} sum(l_extendedprice)={li[2]}")
    print(f"part: count={pa[0]} sum(p_retailprice)={pa[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
