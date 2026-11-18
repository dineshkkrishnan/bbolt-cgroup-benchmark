#!/usr/bin/env python3
"""Phase 4.5: repeated real-Collector restart timings and bbolt metadata inspection.
Health readiness is a proxy, NOT a direct bbolt.Open() measurement.
"""
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import struct
import time
import statistics

spec = importlib.util.spec_from_file_location("phase44", "scripts/phase44_collector.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT = Path("scratch/phase45").resolve()
m.RESULTS = Path("results/phase45").resolve()
m.CONFIG = Path("phase4/collector44.yaml").resolve()
m.RECORDS = int(os.environ.get("PHASE45_RECORDS", "200000"))
REPEATS = int(os.environ.get("PHASE45_REPEATS", "5"))
NAME = "phase44-collector"

def meta(path):
    result = []
    for file in sorted(path.rglob("*")):
        if not file.is_file() or file.stat().st_size < 8192:
            continue
        with file.open("rb") as stream:
            header = stream.read(8192)
        pages = []
        for offset in (0, 4096):
            page_id, flags, count, overflow = struct.unpack_from("<QHHI", header, offset)
            magic, version, page_size, meta_flags = struct.unpack_from("<IIII", header, offset+16)
            if magic != 0xED0CDAED:
                continue
            root, sequence, freelist, pgid, txid = struct.unpack_from("<QQQQQ", header, offset+32)
            pages.append({"page_id":page_id,"page_flags":flags,"magic":hex(magic),
                "version":version,"page_size":page_size,"meta_flags":meta_flags,
                "freelist_page_id":freelist,"high_water_page_id":pgid,"transaction_id":txid})
        if pages:
            result.append({"file":str(file.relative_to(path)),"size_bytes":file.stat().st_size,"meta_pages":pages,
                "note":"freelist_page_id=18446744073709551615 indicates no persisted freelist page"})
    return result

def cgstats(name):
    inspect = m.cmd("docker","inspect","-f","{{.State.Pid}}",name,check=False)
    if inspect.returncode or not inspect.stdout.strip().isdigit():
        return {"error":inspect.stderr.strip()}
    pid = int(inspect.stdout.strip())
    if pid <= 0:
        return {"error":"container not running"}
    cgfile = Path(f"/proc/{pid}/cgroup")
    if not cgfile.exists():
        return {"error":"container cgroup path inaccessible"}
    entries = cgfile.read_text().splitlines()
    rel = next((line.split("::",1)[1] for line in entries if "::" in line),None)
    if rel is None:
        return {"error":"requires cgroup v2"}
    root = Path("/sys/fs/cgroup")
    path = root / rel.lstrip("/")
    data = {"cgroup_path":str(path)}
    for filename in ("memory.stat","memory.events","memory.current","io.stat"):
        f = path / filename
        if f.exists():
            data[filename] = f.read_text()
        else:
            data[filename] = "unavailable"
    return data

def main():
    m.RESULTS.mkdir(parents=True,exist_ok=True)
    m.ROOT.mkdir(parents=True,exist_ok=True)
    import threading
    server = m.http.server.ThreadingHTTPServer(("127.0.0.1",19090),m.Sink)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    report = {"records":m.RECORDS,"repeats":REPEATS,"runs":[],
        "limitations":["Health readiness is not a direct bbolt.Open duration",
        "Advisory cache eviction is not guaranteed",
        "Copying database snapshots may warm host cache",
        "Cgroup counters are sampled after readiness, not at exact Open boundaries"]}
    try:
        seed = m.ROOT/"seed"
        if seed.exists(): shutil.rmtree(seed)
        seed.mkdir()
        m.run_collector(NAME,seed,1024)
        m.wait_health()
        report["ingested"] = m.emit()
        time.sleep(3)
        m.stop_collector(NAME)
        m.allow_snapshot_copy(seed)
        report["seed_bytes"] = m.queue_bytes(seed)
        report["bbolt_metadata"] = meta(seed)
        (m.RESULTS/"bbolt-metadata.json").write_text(json.dumps(report["bbolt_metadata"],indent=2))
        if not report["bbolt_metadata"]:
            raise RuntimeError("No valid bbolt metadata found; cannot characterize freelist")
        conditions = [(1024,"warm"),(1024,"cold"),(256,"warm"),(256,"cold")]
        for repetition in range(REPEATS):
            order = conditions[:]
            random.Random(4500+repetition).shuffle(order)
            for memory,cache in order:
                key=f"r{repetition+1}-{memory}-{cache}"
                directory=m.ROOT/key
                shutil.copytree(seed,directory)
                if cache=="warm":
                    for file in directory.rglob("*"):
                        if file.is_file():
                            with file.open("rb") as stream:
                                while stream.read(1024*1024): pass
                    advised=False
                else:
                    advised=m.advise_cold(directory)
                started=time.monotonic()
                record={"repeat":repetition+1,"memory_mib":memory,"cache":cache,
                    "advisory_eviction_requested":advised}
                try:
                    m.run_collector(NAME,directory,memory)
                    record["health_ready_s"]=m.wait_health(timeout=120)
                    record["total_start_to_health_s"]=time.monotonic()-started
                    record["cgroup_after_health"]=cgstats(NAME)
                    record["queue_bytes"]=m.queue_bytes(directory)
                except Exception as exc:
                    record["error"]=str(exc)
                finally:
                    logs=m.cmd("docker","logs",NAME,check=False)
                    (m.RESULTS/(key+".logs")).write_text(logs.stdout+"\n"+logs.stderr)
                    m.stop_collector(NAME)
                    report["runs"].append(record)
                    (m.RESULTS/"phase45-summary.json").write_text(json.dumps(report,indent=2))
                    print(key,record.get("total_start_to_health_s"),record.get("error","ok"),flush=True)
                if "error" in record:
                    raise RuntimeError(f"{key}: {record['error']}")
        report["summary"]=[]
        for memory,cache in conditions:
            values=[r["total_start_to_health_s"] for r in report["runs"] if r["memory_mib"]==memory and r["cache"]==cache]
            report["summary"].append({"memory_mib":memory,"cache":cache,"median_s":statistics.median(values),
                "min_s":min(values),"max_s":max(values),"n":len(values)})
    finally:
        m.stop_collector(NAME)
        server.shutdown()
        (m.RESULTS/"phase45-summary.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report["summary"],indent=2))
if __name__=="__main__":
    main()
