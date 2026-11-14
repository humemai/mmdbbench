#!/usr/bin/env bash
# rep_state_audit.sh: which cells of the paper pins have fewer than N ok reps? Read-only, small output.
# Run on the bench host: ssh <host> bash -s < experiments/tools/rep_state_audit.sh        (a different N: ssh <host> 'N=5 bash -s' < experiments/tools/rep_state_audit.sh)
# Environment, all optional: N (default 3), REP_STATE_DIR (default $HOME, where the rep-state-*.tsv files are), ARCADEDB_PIN (default a3a5d1245) and COMPARATOR_PIN (default e85469273).
# Why: "n=3 done" was said from a count of OK cells and never listed the cells with no ok rep (the native-server deep10m dense cells).
# A cell is `lane/scale/backend/op` in column 1, the rep number in column 2, `ok` or `fail` in column 3 of rep-state-*.tsv.
# For the ArcadeDB pin the rep-state files of one arm are read TOGETHER (main + pgwire + strict): the main file's fail lines of the
# PostgreSQL-wire twins are redone as ok in the -pgwire file, so a per-file count would flag them wrongly.
set -u
N=${N:-3}
ARCADEDB_PIN=${ARCADEDB_PIN:-a3a5d1245}
COMPARATOR_PIN=${COMPARATOR_PIN:-e85469273}
cd "${REP_STATE_DIR:-$HOME}" || exit 1
audit() {  # label files...
  label=$1; shift
  echo "== $label (cells with fewer than $N ok reps)"
  awk -F'\t' -v n="$N" '{k=$1; r=$2; seen[k]=1; if($3=="ok") okr[k SUBSEP r]=1; else failr[k SUBSEP r]=1}
    END{t=0; for(c in seen){t++; o=0; f=0; for(r=1;r<=9;r++){ if((c SUBSEP r) in okr) o++; else if((c SUBSEP r) in failr) f++ } if(o<n) printf "  ok=%d failreps=%d  %s\n", o, f, c} print "  cells in the union:", t}' "$@" | sort
}
for arm in jvm native; do
  files="rep-state-2026-11-$ARCADEDB_PIN-$arm.tsv rep-state-2026-11-$ARCADEDB_PIN-$arm-pgwire.tsv"
  [ "$arm" = native ] && files="$files rep-state-2026-11-$ARCADEDB_PIN-native-strict.tsv"
  audit "ArcadeDB $arm, pin $ARCADEDB_PIN" $files
done
# the three PG+AGE cells rerun at n=3 are ok reps in the -comprerun file; without it they print as ok=0 and the audit calls them missing
audit "comparators and the original pin, $COMPARATOR_PIN" rep-state-2026-11-$COMPARATOR_PIN.tsv rep-state-2026-11-$COMPARATOR_PIN-comprerun.tsv
echo "note: a post2 file (rep-state-2026-11-$ARCADEDB_PIN-post2.tsv) is in progress while the post2 rerun runs; read it when its driver has finished."
