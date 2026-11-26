#!/usr/bin/env python3
"""Restate the published payload from the exporter's own statements, where the rows it needs are not at hand (humemai/mmdbbench#173, #124, #132).

    uv run python restate_web_page.py [--site <humem.ai checkout>] [--status-only]

WHY THIS EXISTS. The page is the payload `results/web_benchmarks.json` as the last landing wrote it. Since that landing the exporter learned to say
things the page should already say: the size class of every row (#132), the full-network label of Graph OLAP and its caption (#125), the precision and
deployment of a cell with no result (#125), one statement per absent cell (#125), the dash legend (#125), and now the status block and stamp (#173,
page_status.json). A full export needs the bench host's row log and overlay directories, which are on the mini only, so none of this reaches the page
until the 26.12.1 landing. This script applies exactly those statements to the payload as it is, with the exporter's own functions, and touches no number:
no row is added, removed or changed, and no cell is computed. Each step is a label, a legend, a class word or a sentence.

It is a stopgap with an end: the next full export (the 26.12.1 landing) writes all of it from the rows, and the payload loses its `restated` field.
Until then `restated` says what was applied, and where. A payload that already carries the classes and no `restated` field was written by the exporter
and gets only its status block refreshed (what `--status-only` does on any payload), which is also all that the update on a rerun day needs: change
`page_status.json`, run this with `--status-only`, publish.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped; no table is built here
import export_web as EW  # noqa: E402
import page_status as PS  # noqa: E402
from publish_instrument import results_dir  # noqa: E402

# The sentences the size classification writes (export_web._classify_sizes); a restated payload loses and regains them, so the pass can run twice.
OWNED_PREFIXES = ("Every table measured on a dataset has a small size and a large size", "Beside its small and its large size, this table has",
                  "Engine version of the ArcadeDB rows:", EW.VERSIONS_NOTE, EW.COVERAGE_VERSIONS_NOTE)
OWNED_LARGE = re.compile(r"^Large size \(.+\): (not run yet\.|no rows yet, planned for )")
OLD_LEGEND_TAIL = "A dash is an operation the engine cannot express, never a slow one."


def _owned(sentence: str) -> bool:
    return sentence.startswith(OWNED_PREFIXES) or bool(OWNED_LARGE.match(sentence))


def _table_sentences(payload):
    yield from payload.get("conditions") or []
    for t in payload["tables"]:
        yield from t.get("conditions") or []


def _strip_sizes(payload, changes):
    """Take the size classification off, so it is written again from what the payload says now (idempotence)."""
    payload["conditions"] = [c for c in payload.get("conditions") or [] if not _owned(c)]
    for t in payload["tables"]:
        t["conditions"] = [c for c in t.get("conditions") or [] if not _owned(c)]
        t.pop("sizes", None)
        for e in t.get("entries") or []:
            if "size_corpus" in e:
                e["scale_label"] = e.pop("size_corpus")
                e.pop("size_class", None)


def _no_result_rows(payload, changes):
    """A row that stands for a cell with no result takes its precision from the arm and its deployment from the topology, never from its name."""
    for t in payload["tables"]:
        for e in t.get("entries") or []:
            key = e.get("backend_key")
            if not e.get("outcome") or not key:
                continue
            if t["id"] == "l3d" and e.get("precision") is None and key in EW.DENSE_PRECISION:
                e["precision"] = EW.DENSE_PRECISION[key]
                changes.append(f"{t['id']}: {e['backend']} at {e.get('scale_label')} has precision {e['precision']}")
            if key in EW.BACKENDS and e.get("deployment") != EW.deployment_of(key):
                changes.append(f"{t['id']}: {e['backend']} at {e.get('scale_label')} reads {EW.deployment_of(key)}, not {e.get('deployment')}")
                e["deployment"] = EW.deployment_of(key)


def _relabel(node, old, new):
    """Every string of the payload that carries the old size label carries the new one (the notes name a size by its label)."""
    if isinstance(node, str):
        return node.replace(old, new)
    if isinstance(node, list):
        return [_relabel(x, old, new) for x in node]
    if isinstance(node, dict):
        return {k: _relabel(v, old, new) for k, v in node.items()}
    return node


def _graph_olap_labels(payload, changes):
    """The full-network size says what it holds, and the caption names the size the table has."""
    new = EW.scale_label("l2", "sf1full")
    spec = next(v["l2olap"] for v in vars(EW).values() if isinstance(v, dict) and isinstance(v.get("l2olap"), dict) and "dataset" in v["l2olap"])
    for t in payload["tables"]:
        if t["id"] != "l2olap":
            continue
        old = {e["scale_label"] for e in t["entries"] if e.get("scale") == "sf1full" and e.get("scale_label") not in (None, new)}
        if t.get("dataset") != spec["dataset"]:
            changes.append(f"l2olap: the caption reads {spec['dataset']!r}, not {t.get('dataset')!r}")
            t["dataset"] = spec["dataset"]
        for label in sorted(old, key=len, reverse=True):
            changes.append(f"l2olap: the size reads {new!r}, not {label!r}")
            return _relabel(payload, label, new)
    return payload


def _legend(payload, changes):
    """The dash legend names all three of its meanings (export_web._mark_legend)."""
    tail = EW._mark_legend({"lost"})[0]
    tail = tail[tail.index("A dash means"):]
    registry = {r["text"]: r for r in payload.get("condition_provenance", {}).get("generated", [])}
    for t in payload["tables"]:
        for i, c in enumerate(t.get("conditions") or []):
            if c.startswith("In the cells: ") and c.endswith(OLD_LEGEND_TAIL):
                new = c[: -len(OLD_LEGEND_TAIL)] + tail
                t["conditions"][i] = EW._gen(new, *(registry.get(c, {}).get("values") or []))
                changes.append(f"{t['id']}: the legend names every meaning of a dash")


def _not_measured(payload, changes):
    """An arm with a statement for a size (failed, censored, out of memory) was attempted there: it is not also "not measured" (export_web._declare_missing_builds)."""
    for t in payload["tables"]:
        absences, said = t.get("declared_absences") or [], [a for a in t.get("declared_absences") or [] if a["kind"] != "not measured"]
        sizes = {str(e.get("scale_label")) for e in t.get("entries") or [] if e.get("scale_label")}
        keep, touched = [], False
        for a in absences:
            m = re.fullmatch(r"(.+) was not measured at (.+)\.", a["why"]) if a["kind"] == "not measured" else None
            if not m:
                keep.append(a)
                continue
            named = [z for z in sorted(sizes) if z in m.group(2)]
            left = [z for z in named if not any(s["backend"] == a["backend"] and z in s["why"] for s in said)]
            if left == named:
                keep.append(a)
                continue
            touched = True
            changes.append(f"{t['id']}: {a['backend']} was attempted at {', '.join(z for z in named if z not in left)}, so it is not also not measured there")
            if left:
                keep.append({**a, "why": f"{a['backend']} was not measured at {EW._join_and(left)}."})
        if not touched:
            continue
        t["declared_absences"] = keep
        t["conditions"] = [c for c in t["conditions"] if not re.match(r"^The (native|JVM) build was not measured for .*, so those rows are absent\.$", c)]
        for b, name in EW._AI.BUILD_NAMES.items():
            parts, vals = [], []
            for a in keep:
                m = re.fullmatch(r"(.+) was not measured at (.+)\.", a["why"]) if a["kind"] == "not measured" else None
                if m and a["backend"].endswith(f"{name})"):
                    parts.append(f"{a['backend']} at {m.group(2)}")
                    vals += [a["backend"], *[z for z in sorted(sizes) if z in m.group(2)]]
            if parts:
                t["conditions"].append(EW._gen(f"The {name} was not measured for {EW._join_and(parts)}, so those rows are absent.", *vals))


def _registry(payload):
    """The generated-sentence registry holds the sentences the page carries, with the strings they inserted."""
    texts = set(_table_sentences(payload))
    keep = [r for r in payload.get("condition_provenance", {}).get("generated", []) if r["text"] in texts]
    for r in EW._GENERATED:
        if r["text"] in texts and r not in keep:
            keep.append(r)
    payload["condition_provenance"] = {"generated": keep}


def restate(payload, generated_on=None, status_only=False):
    """The payload with the exporter's statements applied, and the list of what changed. Rows and cells are never touched."""
    payload, changes = copy.deepcopy(payload), []
    exported = any(t.get("sizes") for t in payload["tables"]) and "restated" not in payload
    if not (status_only or exported):
        _strip_sizes(payload, changes)
        _no_result_rows(payload, changes)
        payload = _graph_olap_labels(payload, changes) or payload
        _legend(payload, changes)
        _not_measured(payload, changes)
        EW._classify_sizes(payload)
        _registry(payload)
        day = generated_on or datetime.date.today().isoformat()
        payload["restated"] = {"on": day, "by": "experiments/restate_web_page.py",
                               "changes": (payload.get("restated") or {}).get("changes", 0) + len(changes),
                               "note": "the exporter's statements applied to the payload of the last landing; no row or cell changed; the next full export replaces this"}
    EW._stamp_status(payload, generated_on)
    payload = EW._strip_internal_refs(payload)
    EW._refuse_internal_refs(payload)
    return payload, changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", help="humem.ai checkout: copy the payload to src/data/dbbench-benchmarks.json and check the copy")
    ap.add_argument("--status-only", action="store_true", help="refresh the status block and the stamp only")
    ap.add_argument("--date", help="the generation date (default: today)")
    args = ap.parse_args()
    path = results_dir() / "web_benchmarks.json"
    before = json.loads(path.read_text(encoding="utf-8"))
    after, changes = restate(before, args.date, args.status_only)
    path.write_text(json.dumps(after, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {path}: {len(changes)} statement(s) applied")
    for c in changes:
        print(f"  {c}")
    problems = PS.problems(after)
    if problems:
        print("REFUSING:", "; ".join(problems), file=sys.stderr)
        return 1
    import refresh_web_page as RW
    RW._rewrite_page_spec_inventory(path)
    if args.site:
        RW.sync_payload(path, Path(args.site).resolve() / RW.PAGE_DATA)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
