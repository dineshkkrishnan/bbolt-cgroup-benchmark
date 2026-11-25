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
