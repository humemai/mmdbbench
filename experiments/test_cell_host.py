#!/usr/bin/env python3
"""The host name of a cell's server stays inside one DNS label, and the lean client says so when a name does not (humemai/mmdbbench#166).

Run with `python -m pytest test_cell_host.py -q -rs` from this directory.

THE FAILURE. In the rehearsal of the 26.11.1 pin the lean twin of the time-series restart cell, `restart_arcadedb_ts_native_server_restart_clientlean_ts100_r1`,
stopped after 20 s with `UnicodeError: encoding with 'idna' codec failed` (`label too long`) from `conn.connect()` in `lean_http._connect`. The runner names the
server container `srv-<run id>` and gives that name to the client as `BENCH_SERVER_HOST`. That name was 65 characters, and a DNS label is at most 63, so
`http.client` refused it before it opened a socket. The same limit hit the PostgreSQL-wire twin of the fp32 sparse search at small size (64 characters) in
the same rehearsal. `runner.cell_host` now returns the old name when it fits and `srv-<head>-<8 hex of sha256(run id)>` when it does not, and
`lean_http` refuses a host with a label over 63 characters with a `ConnectionError` that names the host.
"""
import hashlib
import http.client
import inspect
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lean_http as LH  # noqa: E402
import runner as RN  # noqa: E402

FAILED_ID = "restart_arcadedb_ts_native_server_restart_clientlean_ts100_r1"      # the cell of #166, 65 characters as `srv-<id>`
SIBLING_ID = "restart_arcadedb_ts_native_server_restart_ts100_r1"                # its sibling, 54 characters, which ran


# ----------------------------------------------------------------------------- the name

def test_the_name_of_the_cell_that_failed_was_65_characters_and_is_now_63_or_fewer():
    assert len("srv-" + FAILED_ID) == 65                        # the name the rehearsal used, one label of 65 characters
    host = RN.cell_host("srv", FAILED_ID)
    assert len(host) <= RN.DNS_LABEL_MAX == 63
    assert LH.host_problem(host) is None
    # pinned: a change of the function renames the containers of every rerun cell, so it is a deliberate edit of this line
    assert host == "srv-restart_arcadedb_ts_native_server_restart_clientle-a32be936"


def test_the_hash_is_of_the_whole_run_id_and_the_name_is_the_same_every_time():
    digest = hashlib.sha256(FAILED_ID.encode()).hexdigest()[:8]
    assert RN.cell_host("srv", FAILED_ID).endswith("-" + digest)
    assert RN.cell_host("srv", FAILED_ID) == RN.cell_host("srv", FAILED_ID)


def test_a_name_that_fits_is_returned_unchanged():
    assert RN.cell_host("srv", SIBLING_ID) == "srv-" + SIBLING_ID
    at_limit = "x" * (RN.DNS_LABEL_MAX - len("srv-"))
    assert RN.cell_host("srv", at_limit) == "srv-" + at_limit        # exactly 63 characters is a valid label
    assert RN.cell_host("srv", at_limit + "x") != "srv-" + at_limit + "x"
    assert len(RN.cell_host("srv", at_limit + "x")) <= RN.DNS_LABEL_MAX


def test_two_run_ids_cut_to_the_same_head_get_different_names():
    a, b = "x" * 80 + "_r1", "x" * 80 + "_r2"
    assert RN.cell_host("srv", a) != RN.cell_host("srv", b)
    assert len(RN.cell_host("srv", a)) <= RN.DNS_LABEL_MAX and len(RN.cell_host("srv", b)) <= RN.DNS_LABEL_MAX


def test_a_sidecar_name_keeps_its_dashes_and_fits_too():
    rid = ("l3d_milvus_dense_int8_search_clientlean_deep10m_r1_dstrict" * 2).replace("_", "-")     # far over, and already dashed as the runner passes it
    host = RN.cell_host("minio", rid)
    assert len(host) <= RN.DNS_LABEL_MAX and "_" not in host and host.startswith("minio-")


def test_a_prefix_that_leaves_no_room_is_refused():
    with pytest.raises(ValueError, match="no room"):
        RN.cell_host("p" * 60, "anything")


def _scheduled_cells():
    """(run_id, backend has a server) of every cell the stage generator schedules, with the lean and PostgreSQL-wire twins build_jobs adds, at reps 1 to 3."""
    import make_2611_stages as M
    out = {}
    for spec in M.ALL_STAGES:
        for c in M.stage_cells(spec):
            for job in RN.build_jobs([c.lane], [], scale=c.scale):
                if job["backend"] != c.backend or job["workload"] != c.workload:
                    continue
                dsuf = "" if c.cls == "relaxed" else f"_d{c.cls}"
                for rep in (1, 2, 3):
                    rid = f"{job['run_id']}_{c.scale}_r{rep}{dsuf}"
                    out[rid] = RN.BACKENDS[c.backend]
    return out


def test_every_server_name_of_every_scheduled_cell_is_one_valid_label_and_distinct():
    cells = _scheduled_cells()
    assert len(cells) > 500                                         # the whole 26.11 schedule, not a corner of it
    hosts = {}
    cut = []
    for rid, be in cells.items():
        if not be.get("server_image"):
            continue
        host = RN.cell_host("srv", rid)
        assert len(host) <= RN.DNS_LABEL_MAX, (rid, host)
        assert LH.host_problem(host) is None, (rid, host)
        assert host not in hosts, (rid, hosts.get(host))             # two cells never share a container name
        hosts[host] = rid
        if host != "srv-" + rid:
            cut.append(rid)
        else:
            assert len(host) <= RN.DNS_LABEL_MAX                     # a name that fit before is the one it always was
        for s in be.get("sidecars", []):
            sc = RN.cell_host(s["name"], rid.replace("_", "-"))
            assert len(sc) <= RN.DNS_LABEL_MAX and "_" not in sc, (rid, sc)
    assert cut, "no scheduled cell needed a shorter name: this test no longer covers the case it was written for"
    assert all(len("srv-" + r) > RN.DNS_LABEL_MAX for r in cut)     # only names that did not fit were changed


def test_run_cell_gives_the_container_and_the_client_the_same_cut_name_and_records_it():
    src = inspect.getsource(RN.run_cell)
    assert 'server_host = cell_host("srv", run_id)' in src
    assert '"--name", server_host,' in src                           # the container is named what the client is told
    assert 'f"BENCH_SERVER_HOST={server_host}"' in src
    assert 'row["server_host"] = server_host' in src                 # the row maps the container back to its cell
    assert 'srv-{run_id}' not in src                                 # no second, uncut spelling of the name
    assert 'cell_host(_s["name"]' in src                             # the sidecars go through the same function


def test_the_restart_lane_reads_the_container_name_from_the_host_it_was_given():
    # l6_restart stops and starts `docker_api` containers by HOST, so the name the runner gave the container and the client must be one string
    text = (HERE / "l6_restart.py").read_text()
    assert re.search(r"^HOST = os\.environ\.get\(\"BENCH_SERVER_HOST\"", text, re.M)
    assert re.search(r"^\s+srv = HOST\b", text, re.M)


# ----------------------------------------------------------------------------- the client

def test_the_two_modules_state_the_same_limit():
    assert LH.DNS_LABEL_MAX == RN.DNS_LABEL_MAX == 63


@pytest.mark.parametrize("host,ok", [
    ("srv-" + "a" * 59, True),                    # 63: valid
    ("srv-" + "a" * 60, False),                   # 64: the first invalid length
    ("srv-" + FAILED_ID, False),                  # the name of #166
    ("a" * 63 + "." + "b" * 63, True),            # the limit is per label
    ("a" * 64 + ".example", False),
    ("host..example", False),                     # an empty label
    (".example", False),
    ("example.", True),                           # a trailing dot is the root, not an empty label
    ("localhost", True),
    ("127.0.0.1", True),
    ("::1", True),
    ("a." * 130 + "b", False),                    # over 253 characters in all
    ("", False),
    (None, False),
])
def test_host_problem(host, ok):
    assert (LH.host_problem(host) is None) is ok


def test_connect_refuses_a_label_over_63_with_a_connection_error_that_names_it():
    host = "srv-" + FAILED_ID
    with pytest.raises(LH.ConnectionError, match=r"label of 65 characters.*limit of 63") as ei:
        LH.LeanSession()._connect("http", host, 2480, 1)
    assert host in str(ei.value)
    assert isinstance(ei.value, OSError)                              # the lanes catch OSError and Exception, not UnicodeError


def test_a_request_to_a_long_name_raises_a_connection_error_not_a_unicode_error():
    host = "srv-" + FAILED_ID
    with LH.LeanSession() as s:
        with pytest.raises(LH.ConnectionError, match="cannot connect to srv-restart.*label of 65 characters"):
            s.get(f"http://{host}:2480/api/v1/server", timeout=1)
        with pytest.raises(LH.ConnectionError):
            s.post(f"http://{host}:2480/api/v1/command/bench", json={"language": "sql", "command": "select 1"}, timeout=1)


def test_a_label_of_exactly_63_characters_reaches_http_client(monkeypatch):
    seen = []

    def connect(self):
        seen.append(self.host)
        raise OSError("stub: no network in this test")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", connect)
    host = "srv-" + "a" * 59
    assert len(host) == 63
    with pytest.raises(OSError, match="stub"):
        LH.LeanSession()._connect("http", host, 2480, 1)
    assert seen == [host]                                             # the guard let it through


def test_any_other_unicode_error_from_the_connect_is_also_a_connection_error(monkeypatch):
    def boom(self, scheme, host, port, timeout):
        raise UnicodeError("encoding with 'idna' codec failed")

    monkeypatch.setattr(LH.LeanSession, "_connect", boom)
    with pytest.raises(LH.ConnectionError, match="cannot connect to example:80"):
        LH.LeanSession().get("http://example:80/x", timeout=1)
