"""The qualification probes (docs/qualification.md, issue #260): four small programs that give one figure each, so that the same lane can be measured alone and beside other lanes.

    python -m controlplane.worker.lanes.probes PROBE --cpus LIST [--seconds S] [--dir DIR] [--barrier] [--buffer-mib N] [--size-mib N]

    cpu    a fixed integer and floating point kernel on a working set that fits the L2 cache (nothing but registers and the interpreter's own small objects). Value: operations per second.
    membw  a streaming copy between two buffers that are each several times the size of the L3 cache (4 times, from `sys/devices/system/cpu/cpuN/cache`, 256 MiB when it cannot be read).
           Value: megabytes (10^6 bytes) copied per second, the bytes of one buffer per pass.
    io     write, fsync, drop the cache and read back of a file of a fixed size (`--size-mib`, 64 by default) in the directory `--dir`, again and again. Value: megabytes written plus megabytes
           read back, per second.
    ab     a small paired A/B of two deterministic kernels in the style of tools/ab.py of the benchmark notes: arm A is the cpu kernel, arm B is the same kernel plus a walk over a 16 MiB table (larger
           than the L2 cache, so a neighbour that shares the L3 cache moves arm B more than arm A). The rounds alternate the arm order (A B, then B A), round 0 is a warm-up and is dropped.
           Value: the median over the rounds of the time of arm B over the time of arm A (about 1.5 on an idle lane; a ratio above 1 means B is slower).

The probes are time boxed: they run their fixed chunk of work again and again for `--seconds` (the plan's `duration_s` by default: 60, 60, 90 and 120) and report the rate over the time they really
used, so every lane in a run works over the same wall-clock window. They read no network, write only below `--dir` (the cpu, membw and ab probes write nothing), take no random input and print exactly one
JSON line to standard output: `probe`, `value`, `unit`, `elapsed_s`, `seconds`, `work`, `cpus_allowed`, `nice`, `partial`. Everything else goes to standard error. The program pins itself to `--cpus`
with the kernel's affinity call, reads `Cpus_allowed_list` back from `/proc/self/status` and stops with exit 3 when the list is not the one asked for; the launcher (`qualify_run.py`) pins the process
before it starts, so even the imports run on the lane's cores.

`--barrier` is the launcher's way to start the lanes of one run at the same instant: after its setup (the buffers, the file) the probe writes `ready` to standard error and waits for one line on standard
input, and times from that line on. SIGTERM (and SIGINT) end the work at the next chunk: the probe prints the line it has, with `partial` true, and exits 0. Exit codes: 0 a result, 2 an option does
not fit, 3 the pin did not hold, 4 the setup or the go line failed, 5 no work was done.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import sys
import time
from pathlib import Path

PROBES = ("cpu", "membw", "io", "ab")
DEFAULT_SECONDS = {"cpu": 60, "membw": 60, "io": 90, "ab": 120}  # the plan's duration_s (a test keeps them equal)
UNITS = {"cpu": "ops/s", "membw": "MB/s", "io": "MB/s", "ab": "ratio"}
MB = 1_000_000
MIB = 1024 * 1024
OPS_PER_STEP = 13  # operations of one step of the kernel as written: 8 integer (3 xor, 3 shift, 2 and), 1 integer and, 4 floating point (2 add, 1 multiply, 1 divide)
CPU_CHUNK_STEPS = 20_000  # about 4 ms: the time and the stop flag are looked at between chunks
AB_STEPS = 60_000  # arm A of one round, about 12 ms; arm B is the same steps plus the table walk
AB_MIN_ROUNDS = 3  # measured rounds that a result needs (round 0 comes on top)
AB_TABLE_BYTES = 16 * MIB
L3_FACTOR = 4  # the buffers of membw are this many times the L3 cache
MEMBW_UNKNOWN_L3_MIB = 256
MEMBW_BUFFER_MIB = (64, 1024)  # the clamp of the default buffer size
IO_CHUNK = MIB
IO_DEFAULT_SIZE_MIB = 64
MASK = (1 << 64) - 1
STOP = False


class ProbeError(Exception):
    """The probe cannot run as asked; `code` is the exit code."""

    def __init__(self, message: str, code: int = 4):
        super().__init__(message)
        self.code = code


def _on_term(signum, frame) -> None:  # noqa: ARG001
    global STOP
    STOP = True


def allowed_cpus() -> str:
    """`Cpus_allowed_list` of this process, read from /proc (the read-back: what the kernel really allows, never what was asked)."""
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("Cpus_allowed_list"):
            return line.split(":", 1)[1].strip()
    raise ProbeError("Cpus_allowed_list is not in /proc/self/status", 3)


def parse_cpus(text: str) -> tuple[int, ...]:
    out: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ValueError("an empty entry")
        low, _, high = part.partition("-")
        first, last = int(low), int(high or low)
        if first < 0 or last < first:
            raise ValueError(f"{part!r} is not a core range")
        out.update(range(first, last + 1))
    return tuple(sorted(out))


def format_cpus(cpus) -> str:
    items = sorted(cpus)
    parts, i = [], 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1] == items[j] + 1:
            j += 1
        parts.append(str(items[i]) if i == j else f"{items[i]}-{items[j]}")
        i = j + 1
    return ",".join(parts)


def pin(cpus_text: str) -> str:
    """Pin this process to `cpus_text` and return the list read back from /proc; ProbeError(3) when it is not the list that was asked for."""
    try:
        wanted = parse_cpus(cpus_text)
    except ValueError as exc:
        raise ProbeError(f"--cpus: {exc}", 2) from exc
    try:
        os.sched_setaffinity(0, wanted)
    except OSError as exc:
        raise ProbeError(f"cannot pin to {cpus_text}: {exc.strerror or exc}", 3) from exc
    got = allowed_cpus()
    if parse_cpus(got) != wanted:
        raise ProbeError(f"pinned to {cpus_text} but Cpus_allowed_list says {got}", 3)
    return got


# ---- the kernels --------------------------------------------------------------------------------------------------------------------------------------------


def kernel(steps: int, x: int = 88172645463325252, f: float = 1.0) -> tuple[int, float]:
    """`steps` steps of the integer (xorshift) and floating point kernel. Deterministic: the same arguments give the same state, on every host."""
    for _ in range(steps):
        x ^= (x << 13) & MASK
        x ^= x >> 7
        x ^= (x << 17) & MASK
        f = f * 1.0000001 + 0.5 / (1.0 + (x & 1023))
    return x, f


def table_walk(table: bytearray, steps: int, idx: int = 12345) -> int:
    """`steps` reads at positions of a linear congruential walk over `table` (a power of two in size): the same positions on every host."""
    mask = len(table) - 1
    acc = 0
    for _ in range(steps):
        idx = (idx * 1103515245 + 12345) & mask
        acc += table[idx]
    return acc


def run_cpu(seconds: float, **_) -> dict:
    steps, state, began = 0, (88172645463325252, 1.0), time.perf_counter()
    end = began + seconds
    while not STOP:
        state = kernel(CPU_CHUNK_STEPS, *state)
        steps += CPU_CHUNK_STEPS
        if time.perf_counter() >= end:
            break
    elapsed = time.perf_counter() - began
    if steps == 0:
        raise ProbeError("no chunk of work finished", 5)
    return {"value": steps * OPS_PER_STEP / elapsed, "elapsed_s": elapsed, "work": {"steps": steps, "ops_per_step": OPS_PER_STEP, "chunk_steps": CPU_CHUNK_STEPS}}


def l3_mib(cpu: int) -> float | None:
    """The size of the L3 cache of `cpu` in MiB from sysfs, or None."""
    base = Path(f"/sys/devices/system/cpu/cpu{cpu}/cache")
    try:
        for entry in sorted(base.glob("index*")):
            if (entry / "level").read_text().strip() == "3":
                text = (entry / "size").read_text().strip().upper()
                return float(text[:-1]) / 1024 if text.endswith("K") else float(text[:-1]) if text.endswith("M") else float(text) / MIB
    except (OSError, ValueError):
        return None
    return None


def membw_buffer_mib(cpus: tuple[int, ...], override: int | None) -> int:
    if override is not None:
        return override
    size = l3_mib(cpus[0]) if cpus else None
    mib = MEMBW_UNKNOWN_L3_MIB if size is None else size * L3_FACTOR
    return int(min(max(mib, MEMBW_BUFFER_MIB[0]), MEMBW_BUFFER_MIB[1]))


def setup_membw(cpus: tuple[int, ...], buffer_mib: int | None = None, **_) -> dict:
    mib = membw_buffer_mib(cpus, buffer_mib)
    size = mib * MIB
    src, dst = bytearray(size), bytearray(size)
    pattern = bytes(range(256)) * (MIB // 256)
    for offset in range(0, size, MIB):  # touch every page of both buffers now, so the timed loop pays for no page fault
        src[offset : offset + MIB] = pattern
        dst[offset : offset + MIB] = pattern
    return {"src": memoryview(src), "dst": memoryview(dst), "mib": mib}


def run_membw(seconds: float, state: dict, **_) -> dict:
    src, dst, mib = state["src"], state["dst"], state["mib"]
    passes, began = 0, time.perf_counter()
    end = began + seconds
    while not STOP:
        dst[:] = src  # one pass: a memmove of the whole buffer, read once and written once
        src, dst = dst, src  # the direction alternates, so no pass copies what the cache just held
        passes += 1
        if time.perf_counter() >= end:
            break
    elapsed = time.perf_counter() - began
    if passes == 0:
        raise ProbeError("no pass finished", 5)
    return {"value": passes * mib * MIB / MB / elapsed, "elapsed_s": elapsed, "work": {"buffer_mib": mib, "passes": passes, "bytes_copied": passes * mib * MIB}}


def setup_io(directory: str | None = None, size_mib: int | None = None, **_) -> dict:
    if not directory:
        raise ProbeError("the io probe needs --dir", 2)
    folder = Path(directory)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProbeError(f"cannot use --dir {directory}: {exc.strerror or exc}") from exc
    return {"path": folder / f"qprobe-io-{os.getpid()}.bin", "size": (size_mib or IO_DEFAULT_SIZE_MIB) * MIB}


def run_io(seconds: float, state: dict, **_) -> dict:
    path, size = state["path"], state["size"]
    chunk = bytes((i * 7 + 3) & 255 for i in range(256)) * (IO_CHUNK // 256)
    view = memoryview(chunk)
    written = read = cycles = 0
    began = time.perf_counter()
    end = began + seconds
    try:
        while not STOP:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                for _ in range(size // IO_CHUNK):
                    written += os.write(fd, chunk)
                    if STOP:
                        break
                os.fsync(fd)
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)  # the written pages are clean after the fsync: drop them, so the read comes from the disk
            finally:
                os.close(fd)
            if STOP:
                break
            fd = os.open(path, os.O_RDONLY)
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                while True:
                    block = os.read(fd, IO_CHUNK)
                    if not block:
                        break
                    if block != view[: len(block)]:
                        raise ProbeError("the file read back differs from what was written", 4)
                    read += len(block)
            finally:
                os.close(fd)
            cycles += 1
            if time.perf_counter() >= end:
                break
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    elapsed = time.perf_counter() - began
    if read == 0:
        raise ProbeError("no write, fsync and read back cycle finished", 5)
    return {"value": (written + read) / MB / elapsed, "elapsed_s": elapsed, "work": {"file_mib": size // MIB, "cycles": cycles, "bytes_written": written, "bytes_read": read}}


def setup_ab(**_) -> dict:
    table = bytearray(AB_TABLE_BYTES)
    for offset in range(0, AB_TABLE_BYTES, MIB):
        table[offset : offset + MIB] = bytes((offset // MIB + i) & 255 for i in range(256)) * (MIB // 256)
    return {"table": table}


def arm(name: str, table: bytearray) -> float:
    began = time.perf_counter()
    kernel(AB_STEPS)
    if name == "B":
        table_walk(table, AB_STEPS)
    return time.perf_counter() - began


def run_ab(seconds: float, state: dict, **_) -> dict:
    table = state["table"]
    ratios: list[float] = []
    began = time.perf_counter()
    end = began + seconds
    k = 0
    while not STOP:
        order = ("A", "B") if k % 2 == 0 else ("B", "A")  # alternate the arm order, as the harness interleaves A B A B
        times = {name: arm(name, table) for name in order}
        if k > 0:  # round 0 is the warm-up
            ratios.append(times["B"] / times["A"])
        k += 1
        if time.perf_counter() >= end and len(ratios) >= AB_MIN_ROUNDS:
            break
    elapsed = time.perf_counter() - began
    if not ratios:
        raise ProbeError("no measured round finished", 5)
    return {
        "value": statistics.median(ratios),
        "elapsed_s": elapsed,
        "work": {"rounds": len(ratios), "steps_per_arm": AB_STEPS, "table_mib": AB_TABLE_BYTES // MIB, "ratio_min": min(ratios), "ratio_max": max(ratios)},
    }


SETUP = {"cpu": lambda **kw: {}, "membw": setup_membw, "io": setup_io, "ab": setup_ab}
RUN = {"cpu": run_cpu, "membw": run_membw, "io": run_io, "ab": run_ab}


def wait_for_go() -> None:
    """The start barrier: `ready` on standard error, then one line on standard input."""
    print("ready", file=sys.stderr, flush=True)
    line = sys.stdin.readline()
    if line.strip() != "go":
        raise ProbeError("no go line on standard input (the launcher is gone)", 4)


def run_probe(name: str, cpus: str, seconds: float | None = None, directory: str | None = None, barrier: bool = False, buffer_mib: int | None = None, size_mib: int | None = None) -> dict:
    """Pin, set up, wait for the go line when asked, run and return the result dictionary (the line that is printed). ProbeError for anything that stops the probe."""
    if name not in PROBES:
        raise ProbeError(f"unknown probe {name!r}; one of {', '.join(PROBES)}", 2)
    seconds = float(DEFAULT_SECONDS[name] if seconds is None else seconds)
    if not seconds > 0:
        raise ProbeError("--seconds must be above 0", 2)
    allowed = pin(cpus)
    state = SETUP[name](cpus=parse_cpus(cpus), buffer_mib=buffer_mib, directory=directory, size_mib=size_mib)
    if barrier:
        wait_for_go()
    started = time.time()
    result = RUN[name](seconds, state=state)
    return {
        "probe": name,
        "value": result["value"],
        "unit": UNITS[name],
        "elapsed_s": round(result["elapsed_s"], 4),
        "seconds": seconds,
        "work": result["work"],
        "cpus_allowed": allowed,
        "nice": os.nice(0),
        "partial": STOP,
        "t_start": round(started, 3),
        "t_end": round(time.time(), 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m controlplane.worker.lanes.probes", description=__doc__.split("\n\n")[0])
    parser.add_argument("probe", choices=PROBES)
    parser.add_argument("--cpus", required=True, help="the lane's cores, such as 6,8 (the probe pins itself to them and reads the list back)")
    parser.add_argument("--seconds", type=float, default=None, help="the time box in seconds (default: the plan's duration_s of the probe)")
    parser.add_argument("--dir", default=None, help="the directory the io probe writes its scratch file in (the only place a probe writes)")
    parser.add_argument("--barrier", action="store_true", help="write `ready` to standard error after the setup and wait for a `go` line on standard input")
    parser.add_argument("--buffer-mib", type=int, default=None, help="membw: the size of each of the two buffers (default 4 times the L3 cache)")
    parser.add_argument("--size-mib", type=int, default=None, help=f"io: the size of the file (default {IO_DEFAULT_SIZE_MIB})")
    args = parser.parse_args(argv)
    global STOP
    STOP = False
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    try:
        result = run_probe(args.probe, args.cpus, args.seconds, args.dir, args.barrier, args.buffer_mib, args.size_mib)
    except ProbeError as exc:
        print(f"probe {args.probe}: {exc}", file=sys.stderr, flush=True)
        return exc.code
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
