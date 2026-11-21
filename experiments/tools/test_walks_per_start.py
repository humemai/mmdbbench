"""walks_per_start: the closed-form walk count equals a brute-force enumeration of three-relationship paths, and the sample comparison drops
discarded reads."""
import itertools
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import walks_per_start as W  # noqa: E402


def _write_corpus(d, ids, pairs):
    d.mkdir(parents=True, exist_ok=True)
    (d / "person_0_0.csv").write_text("id|firstName\n" + "".join(f"{i}|n{i}\n" for i in ids))
    (d / "person_knows_person_0_0.csv").write_text("Person.id|Person.id|creationDate\n" + "".join(f"{a}|{b}|0\n" for a, b in pairs))


def _brute(ids, pairs):
    """Every p-m1-m2-x over three DISTINCT friendships, in either direction, counted one path at a time."""
    edge = lambda a, b: frozenset((a, b))  # noqa: E731
    nbr = {i: set() for i in ids}
    for a, b in pairs:
        nbr[a].add(b)
        nbr[b].add(a)
    out = {}
    for p in ids:
        n = 0
        for m1 in nbr[p]:
            for m2 in nbr[m1]:
                for x in nbr[m2]:
                    if len({edge(p, m1), edge(m1, m2), edge(m2, x)}) == 3:
                        n += 1
        out[p] = n
    return out


def test_closed_form_matches_brute_force(tmp_path):
    rng = random.Random(5)
    ids = list(range(100, 140))
    pairs = {(a, b) for a, b in itertools.combinations(ids, 2) if rng.random() < 0.12}
    # a pair listed twice (both directions) and a loop must count once, and not at all
    rows = sorted(pairs) + [(b, a) for a, b in sorted(pairs)[:5]] + [(ids[0], ids[0])]
    _write_corpus(tmp_path, ids, rows)
    got_ids, adj = W.load_graph(W.find_dynamic(tmp_path))
    assert got_ids == ids
    expected = _brute(ids, pairs)
    assert sum(expected.values()) > 0
    assert W.walks_per_person(got_ids, adj) == expected


def test_data_root_layout(tmp_path):
    dyn = tmp_path / "sf1" / "social_network-sf1-X" / "dynamic"
    _write_corpus(dyn, [1, 2, 3], [(1, 2), (2, 3)])
    assert W.find_dynamic(tmp_path, "sf1") == dyn
    assert W.find_dynamic(dyn) == dyn


def test_compare_skips_discarded_and_other_ops(tmp_path):
    f = tmp_path / "samples.jsonl"
    recs = [{"header": 1, "n_persons_ingested": 3, "n_edges_ingested": 2}]
    for pos, (pid, lat) in enumerate([(1, 1.0), (2, 2.0), (3, 3.0)]):
        recs.append({"op": "hop3f", "pass": 1, "discarded": False, "start_id": pid, "latency_ms": lat, "position": pos})
    recs.append({"op": "hop3f", "pass": 1, "discarded": True, "start_id": 1, "latency_ms": 999.0})
    recs.append({"op": "hop2", "pass": 1, "discarded": False, "start_id": 1, "latency_ms": 999.0})
    f.write_text("".join(json.dumps(r) + "\n" for r in recs))
    head, smp = W.read_samples(f)
    assert head["n_persons_ingested"] == 3 and len(smp) == 3
    c = W.compare(smp, {1: 10, 2: 20, 3: 30})
    assert c["n"] == 3 and abs(c["spearman"] - 1.0) < 1e-12 and abs(c["us_per_walk_median"] - 100.0) < 1e-9
