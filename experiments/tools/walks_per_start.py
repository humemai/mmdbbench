"""Walks per start for the l2 graph reads, from the corpus files alone, and how the per-start latencies of a cell relate to it.

A hop3f read starts at one person and follows three KNOWS relationships, each used at most once per match, in either direction. The
work of such a read grows with the number of those three-relationship paths that start at the person, and in the LDBC graph that number
differs by orders of magnitude between persons. This script counts them for every person from the two corpus CSV files, without any
engine, so the count is an independent yardstick for the latency of each start.

    uv run python walks_per_start.py --data "$BENCH_GRAPH_DATA"                       # the distribution over all persons
    uv run python walks_per_start.py --data "$BENCH_GRAPH_DATA" --samples samples.jsonl   # and the per-start latencies against it

`--data` is the directory that holds `sf1/` (the value of BENCH_GRAPH_DATA), or a `dynamic/` directory itself. `--samples` is the file the
cell writes when BENCH_GRAPH_SAMPLES_OUT is set (see PROTOCOL.md, "Per-start samples"). Standard library only.
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path


def find_dynamic(data, scale="sf1"):
    """The `dynamic/` directory: `data` itself, or `data/<scale>/social_network-*/dynamic` (the layout the cell reads)."""
    d = Path(data)
    if (d / "person_0_0.csv").exists():
        return d
    hits = sorted(d.glob(f"{scale}/social_network-*/dynamic"))
    if not hits:
        sys.exit(f"walks_per_start: no {scale}/social_network-*/dynamic directory under {d}")
    return hits[0]


def load_graph(dynamic):
    """(person ids in file order, adjacency of the undirected friendship graph with one edge per pair)."""
    dynamic = Path(dynamic)
    with open(dynamic / "person_0_0.csv", newline="", encoding="utf-8") as f:
        rows = csv.reader(f, delimiter="|")
        header = next(rows)
        ix = header.index("id")
        ids = [int(r[ix]) for r in rows]
    pairs = set()
    with open(dynamic / "person_knows_person_0_0.csv", newline="", encoding="utf-8") as f:
        rows = csv.reader(f, delimiter="|")
        next(rows)
        for r in rows:
            a, b = int(r[0]), int(r[1])
            if a != b:
                pairs.add((min(a, b), max(a, b)))
    adj = {}
    for a, b in pairs:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    return ids, adj


def walks_per_person(ids, adj):
    """For each person p: the number of paths p-m1-m2-x over three distinct friendships.

    With no repeated friendship, m2 is not p and x is not m1, and then the last step has deg(m2) - 1 choices; the sum is taken
    through a per-person total so the whole graph costs one pass over the edges.
    """
    deg = {p: len(n) for p, n in adj.items()}
    s = {m: sum(deg[x] - 1 for x in adj[m]) for m in adj}
    out = {}
    for p in ids:
        n = adj.get(p, ())
        out[p] = sum(s[m] - (deg[p] - 1) for m in n)
    return out


def _pct(v, f):
    v = sorted(v)
    return v[min(len(v) - 1, int(f * len(v)))]


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = _rank(x), _rank(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


def read_samples(path, op="hop3f"):
    """(header record, the timed (not discarded) records of `op`)."""
    recs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return recs[0], [r for r in recs[1:] if r.get("op") == op and not r.get("discarded")]


def compare(samples, walks):
    """Spearman rank correlation of latency with walks over `samples`, and microseconds per walk (median, p5, p95)."""
    lat = [r["latency_ms"] for r in samples]
    w = [walks[r["start_id"]] for r in samples]
    per = [1000 * latency / n for latency, n in zip(lat, w) if n]
    return {"n": len(samples), "spearman": spearman(lat, w) if len(set(lat)) > 1 and len(set(w)) > 1 else None,
            "us_per_walk_median": statistics.median(per) if per else None,
            "us_per_walk_p5": _pct(per, 0.05) if per else None, "us_per_walk_p95": _pct(per, 0.95) if per else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", required=True, help="BENCH_GRAPH_DATA (the directory holding sf1/) or a dynamic/ directory")
    ap.add_argument("--scale", default="sf1")
    ap.add_argument("--samples", help="the BENCH_GRAPH_SAMPLES_OUT file of a cell")
    a = ap.parse_args(argv)
    ids, adj = load_graph(find_dynamic(a.data, a.scale))
    walks = walks_per_person(ids, adj)
    friendships = sum(len(n) for n in adj.values()) // 2
    w = list(walks.values())
    print(f"corpus: {len(ids)} persons, {friendships} friendships")
    print(f"3-hop walks per person: p50 {_pct(w, .5)}  p95 {_pct(w, .95)}  p99 {_pct(w, .99)}  max {max(w)}")
    if a.samples:
        head, smp = read_samples(a.samples)
        print(f"samples: {head.get('n_persons_ingested', '?')} persons and {head.get('n_edges_ingested', '?')} edges ingested by the cell, "
              f"{len(smp)} timed hop3f reads")
        lat = sorted(r["latency_ms"] for r in smp)
        sw = sorted(walks[r["start_id"]] for r in smp)
        print(f"latency ms: p50 {_pct(lat, .5):.1f}  p95 {_pct(lat, .95):.1f}  p99 {_pct(lat, .99):.1f}")
        print(f"walks per timed start: p50 {_pct(sw, .5)}  p95 {_pct(sw, .95)}  p99 {_pct(sw, .99)}")
        c = compare(smp, walks)
        print(f"Spearman(latency, walks) = {c['spearman']:.3f}; microseconds per walk: median {c['us_per_walk_median']:.2f}, "
              f"p5 {c['us_per_walk_p5']:.2f}, p95 {c['us_per_walk_p95']:.2f}")


if __name__ == "__main__":
    main()
