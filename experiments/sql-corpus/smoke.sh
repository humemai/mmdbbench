#!/usr/bin/env bash
# One command: start PostgreSQL 18 and ArcadeDB in containers, load the shared dataset into both, run the corpus once,
# write the output to results/, and remove only the containers this script started (by name, even on failure).
#   bash smoke.sh                       defaults below; every default can be overridden by an environment variable
#   REPEAT=20 OUT=/some/dir bash smoke.sh
# Exit code: 0 only when every case passes, 1 when the run is complete but a case fails, 2 or 3 when the setup failed.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PG_IMAGE=${PG_IMAGE:-postgres:18.6}
ADB_IMAGE=${ADB_IMAGE:-arcadedata/arcadedb:26.11.1}
PSYCOPG=${PSYCOPG:-3.3.8}
CPUSET=${CPUSET:-12-15}
MEM=${MEM:-2g}
ADB_HEAP=${ADB_HEAP:-1g}
REPEAT=${REPEAT:-5}
OUT=${OUT:-$HERE/results}
WAIT=${WAIT:-120}

ID=sqlcorpus-$$
PG_NAME=$ID-postgres
ADB_NAME=$ID-arcadedb
PW=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
started=()
cleanup() {
  for name in "${started[@]}"; do docker rm -f "$name" >/dev/null 2>&1 || true; done
}
trap cleanup EXIT
mkdir -p "$OUT"

wait_for() {
  local what=$1 deadline=$((SECONDS + WAIT))
  shift
  until "$@" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then echo "timeout after ${WAIT}s waiting for $what" >&2; exit 3; fi
    sleep 1
  done
}
host_port() { docker port "$1" "$2/tcp" | head -n 1 | sed 's/.*://'; }
py() { uv run --no-project --with "psycopg[binary]==$PSYCOPG" python -I "$@"; }

started+=("$PG_NAME")
docker run -d --name "$PG_NAME" --cpuset-cpus "$CPUSET" -m "$MEM" -p 127.0.0.1::5432 \
  -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=corpus "$PG_IMAGE" >/dev/null
started+=("$ADB_NAME")
docker run -d --name "$ADB_NAME" --cpuset-cpus "$CPUSET" -m "$MEM" -p 127.0.0.1::5432 -p 127.0.0.1::2480 \
  -e JAVA_OPTS="-Xmx$ADB_HEAP -Darcadedb.server.rootPassword=$PW -Darcadedb.server.defaultDatabases=corpus[root] -Darcadedb.server.plugins=Postgres:com.arcadedb.postgres.PostgresProtocolPlugin" \
  "$ADB_IMAGE" >/dev/null

PG_PORT=$(host_port "$PG_NAME" 5432)
ADB_PG_PORT=$(host_port "$ADB_NAME" 5432)
ADB_HTTP_PORT=$(host_port "$ADB_NAME" 2480)
wait_for "PostgreSQL" docker exec "$PG_NAME" psql -h 127.0.0.1 -U postgres -d corpus -tAc 'SELECT 1'
wait_for "ArcadeDB HTTP" curl -sf -o /dev/null "http://127.0.0.1:$ADB_HTTP_PORT/api/v1/ready"

PG_DSN="host=127.0.0.1 port=$PG_PORT user=postgres password=$PW dbname=corpus sslmode=disable"
ADB_DSN="host=127.0.0.1 port=$ADB_PG_PORT user=root password=$PW dbname=corpus sslmode=disable"

py "$HERE/setup.py" postgres "$PG_DSN"
py "$HERE/setup.py" arcadedb "http://127.0.0.1:$ADB_HTTP_PORT" "$PW"

{
  echo "# images: $PG_IMAGE $(docker image inspect --format '{{index .RepoDigests 0}}' "$PG_IMAGE" 2>/dev/null || echo 'no repo digest')"
  echo "# images: $ADB_IMAGE $(docker image inspect --format '{{index .RepoDigests 0}}' "$ADB_IMAGE" 2>/dev/null || echo 'no repo digest')"
  echo "# limits: cores $CPUSET and $MEM per container, both containers on the same cores, ArcadeDB heap -Xmx$ADB_HEAP"
  echo "# host: $(grep -m 1 'model name' /proc/cpuinfo | sed 's/.*: //'), kernel $(uname -r), $(docker version --format 'docker {{.Server.Version}}')"
  echo "# arcadedb engine: $(curl -s -u "root:$PW" "http://127.0.0.1:$ADB_HTTP_PORT/api/v1/server" | grep -o '"version":"[^"]*"' | head -n 1)"
  echo "# arcadedb wire plugin: $(docker logs "$ADB_NAME" 2>&1 | grep -i -m 1 'postgres' | cut -c 1-200)"
} > "$OUT/first-run.txt"

set +e
py "$HERE/run.py" --reference "$PG_DSN" --engine "$ADB_DSN" --cases "${CASES:-$HERE/cases}" --repeat "$REPEAT" \
  --json "$OUT/first-run.jsonl" \
  >> "$OUT/first-run.txt" 2>&1
rc=$?
set -e
cat "$OUT/first-run.txt"
exit "$rc"
