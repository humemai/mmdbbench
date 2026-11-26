#!/usr/bin/env bash
# build_cell_study.sh LEG DEST: the study folder of a cell leg of the pilot of mmdbbench#164 (C0, L5 or L6), as DEST/pilot164-<leg in lower case>.
# It holds the files of study/, the leg's order as order.json, and a frozen copy of experiments/ at the harness commit that study/cell.json names
# (repo/experiments, from `git archive`, never from the working tree). SHA256SUMS covers every file; run_ab.sh checks it before every claim.
# The folder is new or the script stops: a study folder is never edited in place. Run it from any checkout that has the harness commit.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LEG="${1:?usage: build_cell_study.sh LEG DEST}"
DEST="${2:?usage: build_cell_study.sh LEG DEST}"
case "$LEG" in C0 | L5 | L6) ;; *) echo "LEG is C0, L5 or L6" >&2; exit 2 ;; esac
dir="$DEST/pilot164-${LEG,,}"
[ ! -e "$dir" ] || { echo "$dir exists" >&2; exit 2; }
commit="$(sed -n 's/^ *"harness_commit": *"\([0-9a-f]\{40\}\)",*$/\1/p' "$HERE/study/cell.json")"
[ -n "$commit" ] || { echo "study/cell.json names no harness commit" >&2; exit 2; }
top="$(git -C "$HERE" rev-parse --show-toplevel)"
git -C "$top" cat-file -e "$commit^{commit}" || { echo "the harness commit $commit is not in this clone" >&2; exit 2; }
mkdir -p "$dir/repo"
cp "$HERE/study/pilot_run.py" "$HERE/study/probes.py" "$HERE/study/run_ab.sh" "$HERE/study/cell_run.py" "$HERE/study/cell.json" "$dir/"
cp "$HERE/orders/order-$LEG.json" "$dir/order.json"
git -C "$top" archive "$commit" experiments | tar -x -C "$dir/repo"
mkdir -p "$dir/repo/experiments/results"
(cd "$dir" && find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum >SHA256SUMS)
echo "$dir"
echo "harness $commit"
(cd "$dir" && sha256sum SHA256SUMS order.json cell_run.py pilot_run.py cell.json)
