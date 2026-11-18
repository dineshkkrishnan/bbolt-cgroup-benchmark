#!/usr/bin/env bash
# Phase 3.3: isolated cgroup runs; no cross-container database reuse.
set -euo pipefail
: "${CASE_ID:?}" "${MEMORY_MIB:?}"
[[ "$MEMORY_MIB" == 256 || "$MEMORY_MIB" == 1024 ]] || exit 2
cg=/sys/fs/cgroup
expected=$((MEMORY_MIB*1024*1024))
[[ -f "$cg/cgroup.controllers" ]] || { echo 'cgroup v2 required' >&2; exit 2; }
[[ "$(cat "$cg/memory.max")" == "$expected" ]] || { echo 'memory.max mismatch' >&2; exit 2; }
out="/out/$CASE_ID"
mkdir -p "$out" /work
echo "$expected" > "$out/memory.max"
cat "$cg/memory.stat" > "$out/initial.memory.stat"
cat "$cg/io.stat" > "$out/initial.io.stat"
cat "$cg/memory.events" > "$out/initial.memory.events"
# Populate under the same limit as the reads, on a bind-mounted filesystem.
/bench/bbolt-fill -mode fill -db /work/queue.db -items 200000 -value-bytes 1700 -sync-freelist=false -fsync=true > "$out/fill.json"
stat -c '%s' /work/queue.db > "$out/database.bytes"
cat "$cg/memory.stat" > "$out/postfill.memory.stat"
cat "$cg/io.stat" > "$out/postfill.io.stat"
cat "$cg/memory.events" > "$out/postfill.memory.events"
for round in 1 2; do
  # Alternate order across rounds to expose order-dependent cache warming.
  if [[ "$round" == 1 ]]; then patterns=(random sequential); else patterns=(sequential random); fi
  for pattern in "${patterns[@]}"; do
    id="$pattern-r$round"
    cat "$cg/memory.stat" > "$out/$id.before.memory.stat"
    cat "$cg/io.stat" > "$out/$id.before.io.stat"
    cat "$cg/memory.events" > "$out/$id.before.memory.events"
    /bench/bbolt-read -mode read -db /work/queue.db -items 200000 -passes 3 -pattern "$pattern" -expected-memory-bytes "$expected" > "$out/$id.json"
    cat "$cg/memory.stat" > "$out/$id.after.memory.stat"
    cat "$cg/io.stat" > "$out/$id.after.io.stat"
    cat "$cg/memory.events" > "$out/$id.after.memory.events"
  done
done
cat "$cg/memory.peak" > "$out/memory.peak"
cat "$cg/memory.stat" > "$out/final.memory.stat"
cat "$cg/io.stat" > "$out/final.io.stat"
cat "$cg/memory.events" > "$out/final.memory.events"
