# bbolt cgroup-memory microbenchmark

For https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/52868

**Status:** Initial Ubuntu startup benchmark completed on 2026-11-18. These are warm/unspecified-cache startup measurements, not a cgroup pressure or queue-drain test. AI-assisted initial implementation; review code and methodology independently before publishing findings.

Initial run: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/44242485254

Median `bolt.Open` time (three repetitions, Go 1.25.0, bbolt 1.5.0, `fsync=true`):

| Records | Database size (approx.) | `NoFreelistSync=true` | Persisted freelist |
| --- | ---: | ---: | ---: |
| 10,000 | 35.5 MB | 1.733 ms | 0.097 ms |
| 50,000 | 110 MB | 9.987 ms | 0.087 ms |

Major faults were zero in all runs. These results are not evidence of I/O thrashing under cgroup memory limits.

## Requirements
Linux, Go >=1.25, network access to download bbolt v1.5.0. Docker/Podman or a delegated Linux cgroup is needed only for cgroup-controlled runs; preliminary startup tests run on GitHub Actions without Docker. Use a disposable scratch directory. Benchmark creates potentially multi-GB files.

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

## Phase 3.1: controlled-pressure pilot
Run [the opt-in workflow](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/workflows/cgroup-read-benchmark.yml) using **Actions → bbolt cgroup pressure pilot (Phase 3.1) → Run workflow → main**. Download the `bbolt-phase3-1-pressure-results` artifact.

- The workflow builds three static Linux executables: `bbolt-fill`, `bbolt-read`, and `bbolt-pressure`.
- It populates 100K/300K-record databases on the host, then runs separate startup-only and sequential/random-read container processes with 256/512/1024 MiB `memory.max`, with 0% (control) or 60% (resident anonymous allocation) pressure, twice per configuration.
- The wrapper verifies the exact cgroup v2 `memory.max` and, for pressured cases, verifies `memory.current` reaches at least 50% of that limit before starting work. This validates the *allocation*, not necessarily active reclaim.
- For each container, inspect `.memory.stat.prework` vs `.memory.stat.after` (`pgscan`, `pgsteal`, `workingset_refault_file`), `.memory.events.prework` vs `.memory.events.after` (`high`, `max`, `oom`), `.io.stat.prework` vs `.io.stat.after` (`rbytes`, `rios`), and `.memory.peak`. The `.json` file reports process timing/faults; `.meta` reports limit and pressure state.
- Startup uses read-write `bolt.Open` (`bbolt-fill -mode open`), which can reconstruct an unsynced freelist. Read tests use read-only `bolt.Open`, so **do not** compare their open times as if they measured identical startup paths.
- Shared-runner host page cache is uncontrolled; pressure may not cause reclaim. **Do not claim thrashing unless reclaim/refault and I/O counters support it.** These are synthetic tests, not a faithful Collector persistent queue workload.
- Runs are sequential and only twice repeated; this is a pilot. A more rigorous follow-up needs randomized order, more repetitions, controlled cache state, and actual Collector `file_storage` workload.

## Remaining work
1. Verify the new GitHub Actions run and inspect all per-container memory limits and counter deltas.
2. Improve the pressure model if `pgscan`/`workingset_refault_file` remain zero.
3. Compare against a real `file_storage` queue workload and the proposed implementation.
