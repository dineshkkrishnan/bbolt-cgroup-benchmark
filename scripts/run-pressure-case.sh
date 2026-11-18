#!/usr/bin/env bash
# AI-assisted cgroup-v2 experiment wrapper. Runs entirely inside a Docker container.
set -euo pipefail
: "${CASE_ID:?}" "${MEMORY_BYTES:?}" "${DB_FILE:?}" "${ITEMS:?}" "${MODE:?}" "${PRESSURE_PERCENT:?}"
[[ "$MODE" == "startup" || "$MODE" == "read" ]] || { echo "Invalid MODE" >&2; exit 2; }
[[ "$PRESSURE_PERCENT" == "0" || "$PRESSURE_PERCENT" == "60" ]] || { echo "Invalid pressure percentage" >&2; exit 2; }
cg=/sys/fs/cgroup
[[ -f "$cg/cgroup.controllers" ]] || { echo "cgroup v2 required" >&2; exit 2; }
actual="$(cat "$cg/memory.max")"
[[ "$actual" == "$MEMORY_BYTES" ]] || { echo "FAIL: memory.max=$actual expected=$MEMORY_BYTES" >&2; exit 2; }
mkdir -p /out
prefix="/out/$CASE_ID"
printf 'memory.max=%s\nmode=%s\npressure_percent=%s\n' "$actual" "$MODE" "$PRESSURE_PERCENT" > "${prefix}.meta"
cat "$cg/memory.current" > "${prefix}.memory.current.before"
cat "$cg/memory.stat" > "${prefix}.memory.stat.before"
cat "$cg/memory.events" > "${prefix}.memory.events.before"
cat "$cg/io.stat" > "${prefix}.io.stat.before"
if [[ "$PRESSURE_PERCENT" != "0" ]]; then
  /bench/bbolt-pressure -percent "$PRESSURE_PERCENT" -ready /tmp/pressure.ready > "${prefix}.pressure.log" 2>&1 &
  pressure_pid=$!
  trap 'kill "$pressure_pid" 2>/dev/null || true; wait "$pressure_pid" 2>/dev/null || true' EXIT
  for i in {1..100}; do
    [[ -f /tmp/pressure.ready ]] && break
    kill -0 "$pressure_pid" 2>/dev/null || { cat "${prefix}.pressure.log" >&2; exit 1; }
    sleep 0.1
  done
  [[ -f /tmp/pressure.ready ]] || { echo "Pressure helper did not become ready" >&2; exit 1; }
  current="$(cat "$cg/memory.current")"
  min_current=$((MEMORY_BYTES * 50 / 100))
  [[ "$current" -ge "$min_current" ]] || { echo "FAIL: pressure not resident: current=$current min=$min_current" >&2; exit 1; }
  printf 'pressure_ready=true\nresident_memory_current=%s\n' "$current" >> "${prefix}.meta"
else
  echo 'pressure_ready=false' >> "${prefix}.meta"
fi
cat "$cg/memory.current" > "${prefix}.memory.current.prework"
cat "$cg/memory.stat" > "${prefix}.memory.stat.prework"
cat "$cg/memory.events" > "${prefix}.memory.events.prework"
cat "$cg/io.stat" > "${prefix}.io.stat.prework"
if [[ "$MODE" == "startup" ]]; then
  # Read-write bbolt.Open exercises freelist reconstruction, unlike read-only bbolt.Open.
  /bench/bbolt-fill -mode open -db "/bench/$DB_FILE" -items "$ITEMS" -sync-freelist=false -fsync=true > "${prefix}.json"
else
  /bench/bbolt-read -mode read -db "/bench/$DB_FILE" -items "$ITEMS" -passes 2 -pattern "${PATTERN:?}" -expected-memory-bytes "$MEMORY_BYTES" > "${prefix}.json"
fi
cat "$cg/memory.current" > "${prefix}.memory.current.after"
cat "$cg/memory.peak" > "${prefix}.memory.peak"
cat "$cg/memory.stat" > "${prefix}.memory.stat.after"
cat "$cg/memory.events" > "${prefix}.memory.events.after"
cat "$cg/io.stat" > "${prefix}.io.stat.after"
echo "Finished $CASE_ID: memory.peak=$(cat "$cg/memory.peak")"
