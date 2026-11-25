# Benchmark evidence index (verified GitHub Actions runs)

The GitHub Actions artifacts are temporary. This tracked summary preserves key results, but **not** the raw trial logs. Download artifacts before expiry if raw data is required for external review.

| Phase | Run | Evidence | Median observations |
| --- | --- | --- | --- |
| 4.9 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45121571002 | 80 synthetic bbolt trials; freelist metadata and logical SHA-256 validated | Warm unsynced 3.040 ms vs synced 0.281 ms; advisory-cold 249.504 ms vs 1.569 ms |
| 5.0 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45123451490 | 20 direct bbolt.Open trials on real Collector-generated queue | Warm unsynced 15.339 ms vs synced 0.208 ms; advisory-cold 202.090 ms vs 0.642 ms |
| 5.1 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45124184131 | 20 full Collector restarts; queue logical SHA-256 validated | Warm unsynced 1.415 s vs synced 1.402 s; advisory-cold 0.385 s vs 0.187 s |

| 5.2 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45384231469 | 80 full Collector restarts, 20 trials per arm/cache; matched logical SHA-256 | Approximate process-to-health warm unsynced 125.84 ms vs synced 125.03 ms; advisory-cold unsynced 350.73 ms vs synced 146.69 ms |

Phase 5.2 checks: all 80 trials and all workflow steps passed on 2026-11-24. Collector queue DB file size 357,523,456 bytes; 2,001 logical bbolt entries in both arms; SHA-256 `6d34e76ea7ea388db691848f69d91cba8f4bd6d7d04a2981363c05c6da1665eb`. Collector process-to-health median/95th percentile, seconds: unsynced warm 0.125841/0.131677; synced warm 0.125033/0.130880; unsynced advisory-cold 0.350734/0.353977; synced advisory-cold 0.146693/0.150463. Process start timestamp comes from Docker and health timestamp from host clock, so measurement is approximate. Host cache eviction is advisory; health readiness is not full queue recovery. All conditions use the same runner and 1024 MiB container limit. More independent runs and queue recovery instrumentation are needed before upstream production-performance claims.

Phase 5.2 artifact: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45384231469/artifacts/14915836551 (expires 2027-02-22).

Phases 4.9 through 5.1 completed on 2026-11-23. Phase 5.1 has high variance, Docker CLI overhead, and polling effects; it does **not** establish a statistically reliable production Collector startup benefit. Advisory eviction is not guaranteed to clear page cache. None of these runs proves end-to-end queue recovery or delivery performance.

Artifacts (subject to retention):
- Phase 4.9: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45121571002/artifacts/14793633231
- Phase 5.0: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45123451490/artifacts/14795051133
- Phase 5.1: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45124184131/artifacts/14794569382

Phase 5.2 increases repeats to 20 per arm/cache (80 total) and captures Docker CLI time separately from approximate Collector process-to-health latency. Its artifact retention is set to 90 days; GitHub repository policies may impose a shorter maximum. No automated commit of raw results is configured.


## Phase 5.3 — persistent queue recovery (2026-11-25)

Run: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45549160949

Artifact: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45549160949/artifacts/14992039203 (GitHub reports expiry 2027-02-23).

Collector `otel/opentelemetry-collector-contrib:0.140.0`; 200,000 OTLP log records per trial; five repetitions per arm/cache; 1024 MiB container. All 20 trials succeeded with exactly 200,000 unique record IDs, **zero missing, zero unexpected, zero duplicates**. Both freelist variants had 2,001 logical bbolt keys and identical SHA-256 `a445357b3fbf0a915a01f40040601ddbed6b1c6ac58e59316655e7876baa458b`; file size 357,167,104 bytes. Unsynced freelist metadata sentinel vs synced persisted freelist confirmed.

| Cache | Unsynced median first observed export | Synced median first observed export | Unsynced median last observed export | Synced median last observed export |
| --- | ---: | ---: | ---: | ---: |
| Warm | 123.468 ms | 105.427 ms | 4.319 s | 4.333 s |
| Advisory-cold | 324.426 ms | 130.341 ms | 9.276 s | 9.218 s |

**Interpretation:** Under advisory-cold conditions, persisted freelist reduced time to first observed export by about 194 ms (2.49× faster). The time to deliver all 200,000 unique IDs was similar between variants; thus no substantial overall drain-throughput improvement was demonstrated. The sink's `last_delivery_epoch` is updated after handling HTTP requests, not from an internal Collector queue-depth metric; therefore 'last observed export' is a proxy for drain completion. Timestamp differences use Docker container start and host wall clock; cache eviction is advisory, not guaranteed. One runner and five repetitions per condition are not sufficient to generalize production effect. The benchmark uses an error-returning sink during seeding, then an accepting mock sink during recovery. The validation is of an instrumented synthetic workload using a real Collector and persistent queue, not production reliability.

