"""The page's statement of itself: which ArcadeDB release its rows are, and what the 26.12.1 rerun does to them (mmdbbench#173).

`page_status.json` is the one place that says it. The exporter (export_web.main) and the restate step (restate_web_page.py) read it and write
the payload's `status` field, which the MMDBBench page renders at the top of its results: a stamp line (instrument, engine release, the date the
data was generated) and the status sentences. The sentences are built here from the fields, so changing the page on a rerun day is a change of one
line of the JSON (`rerun_state`, then `small_release` when the 26.12.1 small rows have landed) and no change of code.

What the file says about the rows is checked against the rows: the releases of the ArcadeDB rows of each size class in the payload must be the ones
`small_release` and `large_release` name (`problems`, run by the exporter, the restate step and page_check). A status that claims 26.12.1 over rows
of 26.11.1, or the other way, is refused, so the one-line change cannot get ahead of the landing or fall behind it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS_FILE = HERE / "page_status.json"
STATES = ("scheduled", "running", "landed")
FIELDS = ("instrument", "instrument_month", "small_release", "large_release", "final_release", "release_date", "rerun_start",
          "rerun_state", "large_run_year", "large_run_host")
_RELEASE = re.compile(r"^\d{2}\.\d{1,2}\.\d+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load(path: Path | str | None = None) -> dict:
    """The status file, validated: every field there and no other, releases and dates in their shapes, a state that agrees with the releases."""
    path = Path(path) if path else STATUS_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    extra, missing = sorted(set(data) - set(FIELDS)), [f for f in FIELDS if not data.get(f)]
    if extra or missing:
        raise SystemExit(f"{path.name}: unknown field(s) {extra}, missing field(s) {missing}; the fields are {', '.join(FIELDS)}")
    for f in ("small_release", "large_release", "final_release"):
        if not _RELEASE.match(data[f]):
            raise SystemExit(f"{path.name}: {f} {data[f]!r} is not a release such as 26.12.1")
    for f in ("release_date", "rerun_start"):
        if not _DATE.match(data[f]):
            raise SystemExit(f"{path.name}: {f} {data[f]!r} is not a date such as 2026-12-02")
    if data["rerun_state"] not in STATES:
        raise SystemExit(f"{path.name}: rerun_state {data['rerun_state']!r} is not one of {', '.join(STATES)}")
    landed = data["small_release"] == data["final_release"]
    if landed != (data["rerun_state"] == "landed"):
        raise SystemExit(f"{path.name}: rerun_state {data['rerun_state']!r} and small_release {data['small_release']!r} disagree: the state is "
                         f"'landed' exactly when the small rows are the final release {data['final_release']}")
    return data


def _rows_sentence(s: dict) -> str:
    if s["small_release"] == s["large_release"]:
        return f"These rows are ArcadeDB {s['small_release']} (the {s['instrument_month']} instrument)."
    return (f"The small rows are ArcadeDB {s['small_release']} and the large rows are ArcadeDB {s['large_release']} "
            f"(the {s['instrument_month']} instrument).")


def _rerun_sentence(s: dict) -> str:
    final, start, rel = s["final_release"], s["rerun_start"], s["release_date"]
    if s["rerun_state"] == "scheduled":
        return (f"The final numbers are the {final} rerun at the small size of every lane: it starts on {start}, after the release on {rel}, "
                f"and the rows of the ArcadeDB arms update then.")
    if s["rerun_state"] == "running":
        return (f"The final numbers are the {final} rerun at the small size of every lane: it started on {start}, after the release on {rel}, "
                f"and the rows of the ArcadeDB arms update as each lane lands.")
    return f"The small rows are the final numbers: the {final} rerun at the small size of every lane, started on {start}, after the release on {rel}."


def block(s: dict, generated_on: str) -> dict:
    """The payload's `status` field: the stamp line, and the status sentences in the order a reader needs them."""
    if s["small_release"] == s["large_release"]:
        engine = f"ArcadeDB {s['small_release']}"
    else:
        engine = f"ArcadeDB {s['small_release']} (small) and {s['large_release']} (large)"
    return {
        "stamp": f"Instrument {s['instrument']} · {engine} · generated {generated_on}",
        "lines": [
            f"{_rows_sentence(s)} {_rerun_sentence(s)} The large sizes keep their {s['large_release']} rows until {s['large_run_year']}.",
            "Each table lists the engine version of every build behind its rows, and says which ArcadeDB release its small rows and its large rows are.",
        ],
        "small_release": s["small_release"],
        "large_release": s["large_release"],
        "rerun_state": s["rerun_state"],
    }


def releases_by_class(payload: dict) -> dict:
    """size class -> the ArcadeDB releases of the rows of that class in the payload (a version_name reads "arcadedb 26.11.1 · a3a5d1245")."""
    out: dict = {}
    for t in payload.get("tables") or []:
        for e in t.get("entries") or []:
            m = re.search(r"\d+\.\d+\.\d+", str(e.get("version_name") or ""))
            if e.get("is_arcadedb") and m and e.get("size_class") in ("small", "large"):
                out.setdefault(e["size_class"], set()).add(m.group(0))
    return out


def problems(payload: dict, s: dict | None = None) -> list[str]:
    """Why the payload's status block is not the one the status file and the rows give; empty when it is."""
    s = s or load()
    found = []
    have = releases_by_class(payload)
    for cls, key in (("small", "small_release"), ("large", "large_release")):
        if have.get(cls) and have[cls] != {s[key]}:
            found.append(f"{STATUS_FILE.name} says the {cls} rows are ArcadeDB {s[key]}, and the payload's {cls} rows are ArcadeDB "
                         f"{', '.join(sorted(have[cls]))}")
    got = payload.get("status")
    if not isinstance(got, dict):
        return found + ["the payload has no status block"]
    day = str(got.get("stamp", "")).rsplit(" generated ", 1)[-1]
    if got != block(s, day):
        found.append(f"the payload's status block is not the one {STATUS_FILE.name} gives (stamp {got.get('stamp')!r})")
    return found
