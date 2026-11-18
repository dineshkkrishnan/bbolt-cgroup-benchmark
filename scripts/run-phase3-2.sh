#!/usr/bin/env bash
# Phase 3.2: generate and repeatedly read a DB inside one 256 MiB cgroup.
# AI-assisted experimental scaffold. No claim of thrashing without counter evidence.
set -euo pipefail
cg=/sys/fs/cgroup
expected=$((256*1024*1024))
[[ -f "$cg/cgroup.controllers" ]] || { echo 'cgroup v2 required' >&2; exit 2; }
[[ "$(cat "$cg/memory.max")" == "$expected" ]] || { echo 'incorrect memory.max' >&2; exit 2; }
mkdir -p /out /work
cat "$cg/memory.max" > /out/memory.max
cat "$cg/memory.stat" > /out/initial.memory.stat
cat "$cg/memory.events" > /out/initial.memory.events
cat "$cg/io.stat" > /out/initial.io.stat
# Write from within this cgroup so its page cache is charged to this cgroup.
# A regular bind-mounted disk directory is used (not tmpfs).
/bench/bbolt-fill -mode fill -db /work/queue.db -items 200000 -value-bytes 1700 -sync-freelist=false -fsync=true > /out/fill.json
stat -c '%s' /work/queue.db > /out/database.bytes
size="$(cat /out/database.bytes)"
[[ "$size" -gt "$expected" ]] || { echo "database too small: $size" >&2; exit 2; }
cat "$cg/memory.stat" > /out/postfill.memory.stat
cat "$cg/memory.events" > /out/postfill.memory.events
cat "$cg/io.stat" > /out/postfill.io.stat
for repeat in 1 2 3 4; do
  for pattern in random sequential; do
    id="$pattern-r$repeat"
    cat "$cg/memory.stat" > "/out/$id.before.memory.stat"
    cat "$cg/memory.events" > "/out/$id.before.memory.events"
    cat "$cg/io.stat" > "/out/$id.before.io.stat"
    /bench/bbolt-read -mode read -db /work/queue.db -items 200000 -passes 3 -pattern "$pattern" -expected-memory-bytes "$expected" > "/out/$id.json"
    cat "$cg/memory.stat" > "/out/$id.after.memory.stat"
    cat "$cg/memory.events" > "/out/$id.after.memory.events"
    cat "$cg/io.stat" > "/out/$id.after.io.stat"
    cat "$cg/memory.current" > "/out/$id.memory.current"
    echo "completed $id"
  done
done
cat "$cg/memory.peak" > /out/memory.peak
cat "$cg/memory.stat" > /out/final.memory.stat
cat "$cg/memory.events" > /out/final.memory.events
cat "$cg/io.stat" > /out/final.io.stat
python3 /bench/summarize.py /out
