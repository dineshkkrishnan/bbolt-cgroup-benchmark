#!/usr/bin/env bash
set -euo pipefail
: "${PHASE41_CASE:?}" "${PHASE41_MEMORY_MIB:?}" "${PHASE41_PERSIST:?}"
cg=/sys/fs/cgroup
expected=$((PHASE41_MEMORY_MIB*1024*1024))
[[ "$(cat "$cg/memory.max")" == "$expected" ]] || { echo 'memory.max mismatch' >&2; exit 2; }
mkdir -p "/out/$PHASE41_CASE"
out="/out/$PHASE41_CASE"
printf 'memory_max=%s\n' "$expected" > "$out/meta"
stat -c 'database_bytes=%s' /work/collector.db >> "$out/meta"
sha256sum /work/collector.db > "$out/db.sha256"
cat "$cg/memory.stat" > "$out/pretest.memory.stat"
cat "$cg/io.stat" > "$out/pretest.io.stat"
cat "$cg/memory.events" > "$out/pretest.memory.events"
PHASE41_MODE=recover PHASE41_DB=/work/collector.db \
  /bench/filestorage-phase41.test -test.run '^TestPhase41SeedOrRecover$' -test.v -test.timeout 10m > "$out/test.log" 2>&1
cat "$cg/memory.stat" > "$out/posttest.memory.stat"
cat "$cg/io.stat" > "$out/posttest.io.stat"
cat "$cg/memory.events" > "$out/posttest.memory.events"
cat "$cg/memory.peak" > "$out/memory.peak"
cat "$out/test.log"
