# bbolt cgroup-memory microbenchmark (initial scaffold)

For https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/52868

**Status:** scaffold only; no benchmark results yet. AI-assisted initial implementation; independently review before publishing.

## Requirements
Linux, Go >=1.23, network access to download bbolt v1.5.0, and Docker/Podman for cgroup-controlled runs. Use a disposable scratch directory. Benchmark creates potentially multi-GB files.

## Build
```sh
go mod tidy
go build -o bboltbench .
```

## Populate separate database files (outside constrained container)
```sh
mkdir -p scratch
./bboltbench -mode fill -db scratch/no-freelist.db -items 100000 -value-bytes 1700 -sync-freelist=false
./bboltbench -mode fill -db scratch/synced-freelist.db -items 100000 -value-bytes 1700 -sync-freelist=true
```

## Measure constrained opens
For Linux Docker, run each open as a new process. Use absolute `$PWD` paths and adjust memory limits. Use `--memory-swap` equal to `--memory` to avoid swap masking pressure.
```sh
for mem in 256m 512m 1g; do
  for db in no-freelist synced-freelist; do
    docker run --rm --memory "$mem" --memory-swap "$mem" \
      -v "$PWD/scratch:/bench:rw" -v "$PWD/bboltbench:/bboltbench:ro" \
      --entrypoint /bboltbench debian:bookworm-slim \
      -mode open -db "/bench/$db.db" -sync-freelist=false
  done
done
```

The `-sync-freelist` option for `open` should remain false to match `file_storage`; a persisted freelist in the file is still used by bbolt. Do not concurrently open the same database for writing.

## Important controls
- Collect `memory.current`, `memory.stat`, `memory.events`, `io.stat` from the **container cgroup** during each run. For short opens, sample frequently or wrap with an external cgroup-aware collector.
- `open_minor_faults` and `open_major_faults` are **process** deltas around `bolt.Open`; these are not the same as cgroup-wide counters.
- Warm/cold cache comparisons need a controlled cache protocol (e.g. dedicated test VM, not indiscriminate cache dropping on shared systems). Randomize test order and repeat >=5 times.
- Opening a DB with a large resident backlog is not equivalent to draining it. A second benchmark must exercise random and sequential `Get` workloads under pressure.
- The `fill` mode writes a synthetic dataset, not a faithful Collector persistent-queue workload. The benchmark is diagnostic, not proof of production performance.
- `NoSync` is deliberately configurable. For durability experiments, distinguish process kill from host power loss.

## Next implementation tasks
1. Add a subprocess workload mode for sequential/random Get and repeated reads.
2. Add an outer Linux cgroup sampler with timestamps and CSV output.
3. Run a size matrix (100k, 300k, 1m items) and memory matrix (256 MiB, 512 MiB, 1 GiB).
4. Compare against a real `file_storage` workload and proposed implementation when available.
