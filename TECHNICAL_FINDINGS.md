# Technical findings: bbolt freelist persistence and Collector recovery

Related: [collector-contrib #52868](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/52868). November 25, 2026.

## Scope
Independent validation of the existing clean-shutdown freelist persistence idea, not a new storage architecture proposal. Matched database snapshots were prepared with and without a persisted freelist using an empty transaction with freelist sync and fsync enabled for the persisted arm. Logical hashes, key counts and metadata were checked. The Collector itself was unmodified; this does not test an integrated shutdown implementation.

## Method and results
Linux GitHub Actions, direct bbolt v1.4.3 probe, Collector Contrib v0.140.0, synthetic OTLP workload, warm and advisory-cold cache conditions. Collector recovery used 200,000 records and a 1024 MiB container limit. The downstream mock returned 503 during seeding and accepted records during recovery.

| Phase / median metric | Unsynced warm | Persisted warm | Unsynced advisory-cold | Persisted advisory-cold |
|---|---:|---:|---:|---:|
| 4.9 synthetic bbolt open (80 trials) | 3.040 ms | 0.281 ms | 249.504 ms | 1.569 ms |
| 5.0 real queue direct open (20 trials) | 15.339 ms | 0.208 ms | 202.090 ms | 0.642 ms |
| 5.2 approximate process-to-health (80 trials) | 125.84 ms | 125.03 ms | 350.73 ms | 146.69 ms |
| 5.3 first observed export (20 trials) | 123.47 ms | 105.43 ms | 324.43 ms | 130.34 ms |
| 5.3 last observed export | 4.319 s | 4.333 s | 9.276 s | 9.218 s |

Phase 5.1 (20 exploratory restarts) exposed Docker overhead and health polling confounders; Phase 5.2 separated approximate process timing from CLI timing. Phase 5.0 median advisory-cold minor/major faults were 1339/1998 without persisted freelist versus 59/4 with it. Phase 5.3 recovered all 200,000 expected IDs in each trial, with zero observed missing, unexpected or duplicate IDs during the observation window.

## Interpretation
Persisted freelist snapshots reduced direct opening latency and advisory-cold time to first observed export (~194 ms, 2.49x). Complete delivery time was similar. These results independently support the recovery-initiation mechanism, not a production-wide speedup or a solution to crash recovery or mmap churn.

## Limitations
Advisory eviction is not guaranteed cold cache; local runner storage does not reproduce the reported network volume. Single runner per phase; five trials per condition in Phase 5.3. Docker/host clock timing is approximate; last observed export is not an internal queue-depth measurement. Logical ID checks do not establish exactly-once guarantees. The persisted snapshot preparation changes transaction metadata and may change free-page accounting. Versions differ from the issue's v0.165.0/v1.5.0. No integrated shutdown cost, crash consistency, corruption/recreate behavior, or steady-state write overhead validation. Earlier cgroup experiments did not demonstrate substantial additional slowdown from reducing memory from 1 GiB to 256 MiB.

## Reproduction
[Consolidated evidence](BENCHMARK_EVIDENCE.md). Runs: [4.9](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45121571002), [5.0](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45123451490), [5.1](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45124184131), [5.2](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45384231469), [5.3](https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45549160949). Raw artifacts have finite retention.

Disclosure: benchmark implementation, analysis and report were prepared with LLM assistance.
