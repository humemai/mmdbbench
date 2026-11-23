"""The native build's overlay files that the frozen rows of a table call for (humemai/mmdbbench#160).

Since 26.11.1 one release is measured on two ArcadeDB builds (`arm_identity`), and the multipass overlays hold one file per build: the JVM build's
`mp_<arm>_b<k>.json` and `sp_<arm>_<tier>.json`, and the native build's `mp_<arm>_native_b<k>.json` and `sp_<arm>_native_<tier>.json` (a served arm's
file also carries its client, `overlay_merge`: a reader asks for the plain name). A table entry takes its warm columns from the overlay file, so a native
row whose overlay file is missing prints without them, or leaves the page, and every gate stays green: the rehearsal of the 26.12.1 landing on
2026-11-23 lost the warm columns of 9 of 22 `l3s` entries and 2 of 27 `l3d` entries that way.

THE RULE, ONE FOR THE SPARSE AND THE DENSE OVERLAY. When the frozen rows hold a NATIVE row of an overlay arm at a size (`lane`, `tier`), the overlay of that
size must hold the arm's native files; a missing one refuses with the file named. Absent is not partial: an arm with no native row at that size owes no
native file, so a freeze of old rows, a lane with no native chain and a table with no rows are untouched. The arm is the unit (an in-process or a served
ArcadeDB arm, `arm_identity.built`): an arm the native chain did not run owes nothing. It is the existing all-or-nothing of
`make_paper_tables._refuse_partial_native` read the other way round: that one refuses an overlay that holds SOME native files and not all, this one also
refuses the overlay that holds NONE when the rows say the native build was measured.

No import of the exporter: `export_web` (the sparse table and the dense one) and `land_stage` (the check before the merge) both call this module."""
import os

import arm_identity as _AI
import overlay_merge as _OM


def _rows_at(rows, lane, tier):
    return [r for r in rows if r.get("lane") == lane and str(r.get("scale")) == str(tier)]


def holds_rows(rows, lane, tier):
    """True when the rows hold at least one row of `lane` at `tier` (the size of the table the overlay feeds)."""
    return bool(_rows_at(rows, lane, tier))


def native_backends(rows, lane, tier):
    """The backend keys of the in-process and served ArcadeDB arms that have a native-build row of `lane` at `tier` among `rows`."""
    return {str(r.get("backend")) for r in _rows_at(rows, lane, tier) if _AI.built(r) and _AI.build_of(r) == "native"}


def owed_native(rows, lane, tier, arms, names):
    """The plain names of the native overlay files the rows call for. `arms` is [(arm token, backend key of its rows)]; `names(token)` gives the plain
    file names of one arm's native files at this size (the dense overlay: one per build, the sparse one: one per tier). An arm whose backend has no native
    row at (`lane`, `tier`) owes none."""
    held = native_backends(rows, lane, tier)
    out = []
    for token, backend in arms:
        if backend in held:
            out += list(names(token))
    return out


def missing(root, names):
    """The names among `names` that `root` holds no file for (a served arm's file named for its client counts: `overlay_merge.pick`)."""
    return [n for n in names if not os.path.isfile(_OM.pick(root, n))]


def refuse_missing_native(root, owed, lane, tier, label):
    """Refuse, naming the files, when the native files `owed` (`owed_native`) are not all in `root`. A `root` that is not a directory is the lane not having
    run at its pin and is the caller's business (`export_web._pinned_dir`: absent is not partial); this reads a directory that is there."""
    gone = missing(root, owed)
    if gone:
        raise SystemExit(f"{label}: the frozen rows hold native-build ArcadeDB rows of {lane} at {tier}, and {len(gone)} of {len(owed)} native overlay files "
                         f"are missing ({', '.join(gone[:4])}{' ...' if len(gone) > 4 else ''}); no fallback: a native entry without its overlay prints "
                         f"without its warm columns, or leaves the page. Copy the native chain's files into {label}, or re-run the arm "
                         f"(humemai/mmdbbench#160)")
