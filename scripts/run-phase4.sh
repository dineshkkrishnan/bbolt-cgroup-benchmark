#!/usr/bin/env bash
set -euo pipefail
: "${PHASE4_CASE:?}" "${PHASE4_PERSIST:?}" "${PHASE4_MEMORY_MIB:?}"
cg=/sys/fs/cgroup
expected=$((PHASE4_MEMORY_MIB*1024*1024))
[[ "$(cat "$cg/memory.max")" == "$expected" ]] || exit 2
mkdir -p "/out/$PHASE4_CASE" /work
out="/out/$PHASE4_CASE"
cat "$cg/memory.stat" > "$out/before.memory.stat"
cat "$cg/io.stat" > "$out/before.io.stat"
cat "$cg/memory.events" > "$out/before.memory.events"
PHASE4_ENABLED=1 PHASE4_DIR=/work PHASE4_ITEMS=200000 \
  /bench/filestorage-phase4.test -test.run '^TestPhase4FileStorageRecovery$' -test.v -test.timeout 25m > "$out/test.log" 2>&1
cat "$cg/memory.stat" > "$out/after.memory.stat"
cat "$cg/io.stat" > "$out/after.io.stat"
cat "$cg/memory.events" > "$out/after.memory.events"
cat "$cg/memory.peak" > "$out/memory.peak"
stat -c '%s' /work/collector.db > "$out/db.bytes"
cat "$out/test.log"
