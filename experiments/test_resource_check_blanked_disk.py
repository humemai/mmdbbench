"""resource_check.PRE_DISK and a disk reading the freeze blanked on purpose (humemai/mmdbbench#65).

The freeze blanks every field with "disk" in its name on a row whose `server_disk_settled` is False (PAGE-SPEC 4a rule 3), which includes
`server_pre_disk`, the text of the command run before the reading. The check reads the frozen rows, so it must not flag a pre-disk step it
can no longer see. Synthetic rows; light. Run with pytest, or as plain functions from this directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resource_check as RC  # noqa: E402

ENGINES = ("duckdb", "sqlite", "chroma", "redis")


def _row(backend, **kw):
    r = {"lane": "l3d", "scale": "deep10m", "workload": "search", "durability_class": "relaxed", "backend": backend, "instrument": "2026-11",
         "rc": 0, "rep": 1, "disk_data_mb": 100.0, "peak_anon_mib_sum": 1000.0, "peak_shmem_mib_sum": 0.0, "peak_owned_mib_sum": 1000.0}
    r.update(kw)
    return r


def _kinds(rows):
    flags, not_checked = RC.check(rows)
    return [(f.kind, f.backend) for f in flags], not_checked


def test_a_pre_disk_step_the_freeze_blanked_with_an_unsettled_reading_is_not_a_finding():
    rows = [_row(b) for b in ENGINES[:3]]
    rows.append(_row("redis", server_pre_disk=None, server_disk_settled=False, disk_data_mb=None, disk_mb_sum=None))
    flags, not_checked = _kinds(rows)
    assert flags == []
    assert any("blanked" in k and v == 1 for k, v in not_checked.items()), dict(not_checked)


def test_a_settled_row_whose_pre_disk_step_did_not_return_zero_is_still_flagged():
    rows = [_row(b) for b in ENGINES[:3]]
    rows.append(_row("redis", server_pre_disk="redis-cli SAVE: rc=1 ERR", server_disk_settled=True))
    assert _kinds(rows)[0] == [("PRE_DISK", "redis")]


def test_an_unsettled_row_that_still_carries_a_reading_is_still_flagged():
    rows = [_row(b) for b in ENGINES[:3]]
    rows.append(_row("redis", server_pre_disk="redis-cli SAVE: rc=1 ERR", server_disk_settled=False))
    assert _kinds(rows)[0] == [("PRE_DISK", "redis")]


def test_a_healthy_pre_disk_step_is_not_counted_as_blanked():
    rows = [_row(b) for b in ENGINES[:3]]
    rows.append(_row("redis", server_pre_disk="redis-cli SAVE: rc=0 OK", server_disk_settled=True))
    flags, not_checked = _kinds(rows)
    assert flags == [] and not any("blanked" in k for k in not_checked)
