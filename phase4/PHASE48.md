# Phase 4.8 — freelist reconstruction isolation (Linux)

This is a focused follow-up to [OpenTelemetry issue #52868](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/52868).

Use the same *source database* for both arms. Copy it into two independent files, then run the preparation command on each copy: one retains the unsynced freelist, and the other commits a saved freelist. This controls for the original key/value workload, but **does not guarantee identical file sizes or layouts after the final transaction**. Record both file sizes and compare them.

Build with bbolt v1.4.3 (the version used in the earlier experiment):

```sh
cd phase4
go mod init phase48probe # only in a clean temporary directory
go get go.etcd.io/bbolt@v1.4.3
go build -o phase48-probe phase48_probe.go
```

For an existing closed database, from the repository root:

```sh
cp source.db /tmp/unsynced.db
cp source.db /tmp/synced.db
phase4/phase48-probe --db /tmp/unsynced.db --prepare
phase4/phase48-probe --db /tmp/synced.db --prepare --sync-freelist
stat -c '%n %s' /tmp/{unsynced,synced}.db
phase4/phase48-probe --db /tmp/unsynced.db
phase4/phase48-probe --db /tmp/synced.db
```

For valid repeats, **re-copy each prepared source before every timed run**. Randomize run order. Run each probe in a fresh process and capture JSON. To test cache sensitivity, separately report warm and advisory-cold conditions; `POSIX_FADV_DONTNEED` is not guaranteed to evict cached pages. Do not equate minor faults with disk reads. Use Linux cgroup v2 `memory.stat`, `memory.events`, and `io.stat` around each run if available.

Interpretation: the comparison isolates the effect of persisting the freelist for a given workload more directly than comparing unrelated real and synthetic databases. It does not reproduce network-attached storage or demonstrate production Collector startup latency. The preparation step uses a final transaction and is **not** a proposed production change.

AI disclosure: This experimental probe and documentation were prepared with LLM assistance and require review and benchmark validation before publishing results.
