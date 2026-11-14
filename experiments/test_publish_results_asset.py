"""publish_results_asset.py builds the release asset of a landing: the raw rows, the frozen table, the page payload and a manifest (humemai/mmdbbench#75, refs #52).

The raw rows archive is a release of this repository tagged bench-2026-11-<landing day> (DECISIONS #331). The tool must put the raw rows file in the bundle, name its sha256
in the manifest, point the reader at the real page, and refuse to build a bundle whose rows hold an email address, a token, a secret assignment, a tailnet name or a home
directory (the benchmark containers' own /home/arcadedb and docker bridge addresses are not private). Light: a temporary results directory, no network, nothing published.
Run with pytest, or as plain functions from this directory.
"""
import hashlib
import json
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import publish_results_asset as M  # noqa: E402

CLEAN = [{"lane": "l2", "backend": "arcadedb_graph_embedded", "instrument": "2026-11", "bench_host": "mini", "rep": 1,
          "server_cmd": "docker run -p 0.0.0.0:2480:2480 --user arcadedb -v /home/arcadedb/databases:/data arcadedata/arcadedb@sha256:2a84", "ip": "172.20.0.2"},
         {"lane": "l1tpc", "backend": "postgres", "instrument": "2026-11", "bench_host": "laptop", "rep": 2}]


def stage(rows, tmp=None):
    d = Path(tmp or tempfile.mkdtemp(prefix="asset-"))
    (d / "web_benchmarks.json").write_text(json.dumps({"instrument": M.PUBLISH_INSTRUMENT, "arcadedb_engines": ["arcadedb 26.11.1"], "arcadedb_commits": ["a3a5d1245"],
                                                       "tables": [{"id": "l2"}]}))
    (d / "runs_paper.csv").write_text("instrument,lane\n2026-11,l2\n")
    (d / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def build(d, *extra):
    old = (M.RESULTS, sys.argv)
    try:
        M.RESULTS = d
        sys.argv = ["publish_results_asset.py", "--tag", "bench-2026-11-14", "--out", str(d / "out"), *extra]
        return M.main()
    finally:
        M.RESULTS, sys.argv = old


def test_the_bundle_holds_the_raw_rows_and_the_manifest_names_their_hash():
    d = stage(CLEAN)
    assert build(d) == 0
    with tarfile.open(d / "out" / "benchmark-results-bench-2026-11-14.tar.gz") as tar:
        assert sorted(tar.getnames()) == ["results_manifest.json", "runs.jsonl", "runs_paper.csv", "web_benchmarks.json"]
    man = json.loads((d / "out" / "results_manifest.json").read_text())
    assert man["files"]["runs.jsonl"]["sha256"] == hashlib.sha256((d / "runs.jsonl").read_bytes()).hexdigest()
    assert man["rows_in_raw_rows"] == 2 and man["raw_rows_instruments"] == {"2026-11": 2}


def test_the_manifest_points_at_the_real_page():
    d = stage(CLEAN)
    assert build(d) == 0
    how = json.loads((d / "out" / "results_manifest.json").read_text())["how_to_check"]
    assert "https://humem.ai/research/mmdbbench" in how and "research/dbbench" not in how


def test_rows_with_private_content_are_refused_and_no_bundle_is_written():
    for bad in ({"note": "contact tae898@example.org"}, {"path": "/home/tk/repos/x"}, {"path": "/Users/someone/x"}, {"tok": "ghp_" + "a" * 36},
                {"cfg": "password = 'hunter22'"}, {"host": "box.tailabc123.ts.net"}, {"ip": "100.101.102.103"}):
        d = stage(CLEAN + [dict(CLEAN[1], **bad)])
        assert build(d) == 1, bad
        assert not (d / "out").exists(), bad


def test_the_private_scan_names_what_it_found_and_lets_the_containers_own_names_through():
    assert M.private_findings(stage(CLEAN) / "runs.jsonl") == {}
    found = M.private_findings(stage(CLEAN + [dict(CLEAN[1], note="a@b.org and /home/tk/x")]) / "runs.jsonl")
    assert found == {"email address": 1, "home directory": 1}, found


def test_the_dry_run_prints_the_exact_release_commands_and_publishes_nothing():
    cmds = M.release_commands("bench-2026-11-14", Path("/x/bundle.tar.gz"), Path("/x/notes.md"))
    assert cmds[0][:4] == ["gh", "release", "create", "bench-2026-11-14"] and "--repo" in cmds[0] and "humemai/mmdbbench" in cmds[0]
    assert "--notes-file" in cmds[0] and "/x/notes.md" in cmds[0] and cmds[0][-1] == "/x/bundle.tar.gz"


def test_the_manifest_counts_csv_rows_not_lines():
    """A frozen cell may hold a newline (the declared reason of an engine does): the manifest said 2781 rows for a table of 621."""
    d = stage(CLEAN)
    (d / "runs_paper.csv").write_text('instrument,why\n2026-11,"first line\nsecond line\nthird"\n2026-11,plain\n')
    assert build(d) == 0
    assert json.loads((d / "out" / "results_manifest.json").read_text())["rows_in_frozen_csv"] == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
