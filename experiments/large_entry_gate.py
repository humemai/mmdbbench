"""A large dense entry keeps the metric keys the page already printed for it (humemai/mmdbbench#146).

Until the full benchmark of the large sizes, the large rows of the page keep the numbers of the release that measured them (26.11.1) while the small
rows move to a new release. The overlay of the large dense rows is read from a directory named by a pin (`dense_mp5_<pin>`), and it supplies the
columns the lane rows cannot: `warm p50 ms` and `warm p99 ms`. When that directory is not found the table does not fail: the large entries are
rebuilt from the lane rows, one fewer arm and no warm columns, and nothing says so (the landing rehearsal of 2026-11-23 found it).

`refuse_lost_large_keys` is the gate. It compares the payload about to be written with the one on disk (the page as last published): a large
entry of the dense table that had an overlay key and no longer has it, or that is gone, refuses the write. The sentence names the table, the entry
and the keys. It reads the size class from `size_classes.row_size_class` (no second classifier), imports the standard library and `size_classes`
only, and takes plain dictionaries, so it needs neither the exporter nor an overlay to be tested.
"""
from __future__ import annotations

import size_classes as _SC

LANE = TABLE = "l3d"
# What the dense multipass overlay supplies, in the order of export_web._dense_overlay_entries (test_large_overlay_by_release holds the two equal).
# Peak memory and disk come from the campaign cell of the same arm, not from the overlay, and are not held here.
OVERLAY_KEYS = ("cold p50 ms", "cold p99 ms", "warm p50 ms", "warm p99 ms", "recall@10",
                "ingest+index total s", "ingest s", "index s", "ingest+index vectors/s")


def _identity(e, sid):
    """What an entry is, apart from the words it is labelled with (a rename of a label must not read as a lost entry): the runner's backend key,
    the build, the precision and the size id."""
    return (str(e.get("backend_key") or e.get("backend")), str(e.get("build") or ""), str(e.get("precision") or ""), sid)


def _large_entries(payload, table=TABLE):
    """{identity: [entries]} for the large-class entries of one table, or None when the payload has no such table."""
    for t in (payload or {}).get("tables") or []:
        if t.get("id") != table:
            continue
        out = {}
        for e in t.get("entries") or []:
            sid = str(e.get("size_id") or e.get("scale"))
            if _SC.row_size_class({"lane": LANE, "scale": sid}) == "large":
                out.setdefault(_identity(e, sid), []).append(e)
        return out
    return None


def lost_large_keys(previous, current, table=TABLE, keys=OVERLAY_KEYS):
    """One sentence per large entry of `table` that had some of `keys` in `previous` and has fewer in `current`, or is gone.

    Only a table that both payloads carry is compared: a scoped landing that leaves the dense table out, and a first export with no earlier
    payload, have nothing to lose. An entry with none of the keys before (a comparator the overlay does not hold) has nothing to keep."""
    was, now = _large_entries(previous, table), _large_entries(current, table)
    if was is None or now is None:
        return []
    problems = []
    for ident, old in sorted(was.items()):
        had = [k for k in keys if any(k in (e.get("metrics") or {}) for e in old)]
        if not had:
            continue
        kept = {k for e in now.get(ident, []) for k in (e.get("metrics") or {})}
        lost = [k for k in had if k not in kept]
        if lost:
            label, sid = old[0].get("backend"), ident[-1]
            problems.append(f"table {table!r}, entry {label!r} at size {sid!r}: " + ("the entry is gone, it had " if ident not in now else "it lost ")
                            + ", ".join(lost))
    return problems


def refuse_lost_large_keys(previous, current, table=TABLE, keys=OVERLAY_KEYS):
    """Refuse the write (SystemExit) when `lost_large_keys` finds anything; return None otherwise."""
    problems = lost_large_keys(previous, current, table, keys)
    if problems:
        raise SystemExit(
            f"REFUSING to write the payload: {len(problems)} large entr{'y' if len(problems) == 1 else 'ies'} of the page lost metric keys the "
            "published payload has.\n  " + "\n  ".join(problems) + "\n"
            "  The large rows keep the numbers of the release that measured them until the full benchmark of the large sizes. Their overlay is "
            "read at the pin of the large class: set BENCH_LARGE_ENGINE_COMMIT to the commit of that release and check that "
            "results/dense_mp5_<that pin> is there (size_classes.pin_of_size_class, humemai/mmdbbench#146).")
