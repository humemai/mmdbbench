#!/usr/bin/env bash
# Study of the pilot of humemai/mmdbbench#164 (permuted neighbours on the mini's compare lanes). The Humem Worker starts it as `bash ./run_ab.sh` with OUT=<label>
# and HUMEM_HOST_LANE, HUMEM_HOST_CPUS, HUMEM_HOST_CELL_CLASS in the environment; it pins the unit to the lane's cores. pilot_run.py reads order.json (and any
# order-*-t1.json) in this folder, finds the claim by OUT, and runs the units of its stage. It writes ./$OUT/rows.jsonl and, at the end, ./$OUT/analysis.txt.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export PATH="$HOME/.local/bin:$PATH"
: "${OUT:?OUT is not set}"
case "$OUT" in "" | . | .. | */*) echo "OUT must be a plain label" >&2; exit 2 ;; esac
if [ -f "$HERE/SHA256SUMS" ]; then
    (cd "$HERE" && sha256sum --quiet -c SHA256SUMS) || { echo "the study folder differs from SHA256SUMS: a partial copy or an edit" >&2; exit 2; }
fi
uv run --no-project --python 3.12 python -I "$HERE/pilot_run.py"
