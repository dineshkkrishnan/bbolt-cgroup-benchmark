# Benchmark evidence index (verified GitHub Actions runs)

The GitHub Actions artifacts are temporary. This tracked summary preserves key results, but **not** the raw trial logs. Download artifacts before expiry if raw data is required for external review.

| Phase | Run | Evidence | Median observations |
| --- | --- | --- | --- |
| 4.9 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45121571002 | 80 synthetic bbolt trials; freelist metadata and logical SHA-256 validated | Warm unsynced 3.040 ms vs synced 0.281 ms; advisory-cold 249.504 ms vs 1.569 ms |
| 5.0 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45123451490 | 20 direct bbolt.Open trials on real Collector-generated queue | Warm unsynced 15.339 ms vs synced 0.208 ms; advisory-cold 202.090 ms vs 0.642 ms |
| 5.1 | https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45124184131 | 20 full Collector restarts; queue logical SHA-256 validated | Warm unsynced 1.415 s vs synced 1.402 s; advisory-cold 0.385 s vs 0.187 s |

All three runs completed on 2026-11-23. Phase 5.1 has high variance, Docker CLI overhead, and polling effects; it does **not** establish a statistically reliable production Collector startup benefit. Advisory eviction is not guaranteed to clear page cache. None of these runs proves end-to-end queue recovery or delivery performance.

Artifacts (subject to retention):
- Phase 4.9: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45121571002/artifacts/14793633231
- Phase 5.0: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45123451490/artifacts/14795051133
- Phase 5.1: https://github.com/dineshkkrishnan/bbolt-cgroup-benchmark/actions/runs/45124184131/artifacts/14794569382

Phase 5.2 increases repeats to 20 per arm/cache (80 total) and captures Docker CLI time separately from approximate Collector process-to-health latency. Its artifact retention is set to 90 days; GitHub repository policies may impose a shorter maximum. No automated commit of raw results is configured.
