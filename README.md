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


## Phase 3.2: focused oversized-database reclaim pilot

Run [Phase 3.2 GitHub Actions](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/workflows/phase3-2-reclaim.yml) manually on `main`. Download artifact `bbolt-phase3-2-reclaim-results`.

This *new, separate workflow* does not modify Phase 3.1. It creates a 200,000-record, 1700-byte/value bbolt file **inside** a Docker container capped at 256 MiB (swap also capped at 256 MiB), verifies the database file is larger than `memory.max`, and performs four random and four sequential read runs (three passes each). Creating the database in the container is intended to charge its page cache to the tested cgroup; it is still a host bind mount, not a controlled cold-cache environment.

The workflow saves `memory.stat`, `memory.events`, `io.stat`, `memory.current`, and `memory.peak` snapshots, per-run JSON measurements, and `assessment.json`. The assessment requires **positive deltas** in `pgscan`, `pgsteal`, and `workingset_refault_file` between the end of database population and the end of reads before labeling the pilot qualified for follow-up. The workflow **does not fail solely because pressure was inconclusive**; it reports `qualified_for_followup: false`. An OOM or a missing result is a genuine failure.

**Limitations:** This experiment establishes whether the container exhibits reclaim and refaults, not whether bbolt itself causes pathological thrashing. It lacks an independent control, cold-cache isolation, randomized order, and production Collector queue semantics. No conclusion about OpenTelemetry issue #52868 should be posted without analyzing the raw counters and performing follow-up controls.


## Phase 3.3: paired 256 MiB versus 1 GiB comparison

Run the [Phase 3.3 comparison workflow](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/workflows/phase3-3-comparison.yml) manually on `main`. Artifact: `bbolt-phase3-3-comparison-results`.

The workflow executes four independent Docker containers in ABBA order (256, 1024, 1024, 256 MiB), with swap capped at the same limit. Each container generates its own 200K-record bbolt database within its cgroup, then runs two random and two sequential read tests (three full passes each). Pattern order alternates within each container. It collects raw per-run `memory.stat`, `memory.events`, and `io.stat` snapshots and produces `comparison.json` with median read durations and 256/1024 ratios.

**Interpretation:** This is a synthetic memory-limit comparison, not a causal freelist benchmark. The 1 GiB condition may fit the ~400 MiB database, while 256 MiB cannot; compare reclaim/refault and disk-read deltas alongside latency. Container creation and host cache are not isolated across tests, so ABBA order only partially mitigates order effects. Do not claim statistical significance from two containers per limit, and do not post a production Collector performance claim from this pilot alone.


## Phase 4: actual upstream `file_storage` client integration pilot

Manually run [Phase 4 workflow](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/workflows/phase4-filestorage.yml) on `main`. Download `bbolt-phase4-filestorage-results`.

Unlike Phases 1–3, this compiles an opt-in test **inside the upstream OpenTelemetry Collector Contrib `extension/storage/filestorage` package** from a pinned-in-results upstream Git checkout. The test calls the package's real `newClient` (which invokes read-write `bbolt.Open` and creates the default bucket) and `client.Get`. The seed database uses the actual default bucket, a 200K-item dataset, and the same bbolt configuration, varying only whether the seed persists the freelist. The real `newClient` always uses `NoFreelistSync=true`, matching upstream source.

Four independent 256/1024 MiB Docker runs cover both seed freelist modes. Each run collects cgroup `memory.stat`, `memory.events`, `io.stat`, peak memory, database size, measured `newClient` startup time, and sampled `Get` duration. Results include the upstream Git SHA.

**Scope and limitations:** This exercises the real extension client code, but **not** the Collector service or persistent queue, nor a realistic churned freelist. Seeding is a synthetic, append-only workload. There is only one run per cell; no causal/statistical conclusion is warranted. Seed generation is inside the constrained container and may be slow or fail at 256 MiB. Compilation happens outside the cgroup to avoid conflating Go compiler memory with the runtime. The workflow is opt-in and not yet validated on a runner. Do not publish a maintainer performance claim until the workflow runs and raw data are reviewed.


## Phase 4.1: validate upstream client startup (opt-in)

[Run Phase 4.1 workflow](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/workflows/phase4-1-validation.yml) on `main`. Artifact: `bbolt-phase4-1-validation-results`.

This follow-up separates database creation from recovery. It builds the actual upstream `filestorage` package integration test, seeds two 200K-record databases **outside** constrained containers (with/without freelist persistence), then copies each seed into a fresh work directory for each recovery-only container. Five repetitions per combination of 256 MiB / 1 GiB and persisted / non-persisted seed yield 20 independent recovery processes. The test measures `newClient` latency and cgroup `memory.stat`, `memory.events`, `io.stat`, and `memory.current` immediately around `newClient`, before three sample `Get` calls. The workflow records seed checksums, upstream commit, per-run logs, and a summary with medians.

**Important caveats:** Repeated host-side file copies can warm the shared runner's page cache. The copies are not a controlled cold-cache protocol, and the sample count does not establish production causality. The test is not a full Collector queue startup; its synthetic append-only seed does not reproduce real freelist churn. Treat latency ratios as exploratory until cache effects are controlled. No upstream issue comment is posted automatically.
