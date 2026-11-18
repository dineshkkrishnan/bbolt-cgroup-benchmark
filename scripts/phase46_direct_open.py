#!/usr/bin/env python3
"""Phase 4.6: direct bbolt.Open on independent copies of real Collector queue DB."""
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import threading
import time

spec=importlib.util.spec_from_file_location("phase44","scripts/phase44_collector.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT=Path("scratch/phase46").resolve()
m.RESULTS=Path("results/phase46").resolve()
m.RECORDS=int(os.environ.get("PHASE46_RECORDS","200000"))
REPEATS=int(os.environ.get("PHASE46_REPEATS","5"))
BINARY=Path("phase4/phase46-open").resolve()
NAME="phase44-collector"

def command(*args,check=True):
    return subprocess.run(args,text=True,capture_output=True,check=check)

def main():
    m.RESULTS.mkdir(parents=True,exist_ok=True)
    m.ROOT.mkdir(parents=True,exist_ok=True)
    server=m.http.server.ThreadingHTTPServer(("127.0.0.1",19090),m.Sink)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    report={"records_requested":m.RECORDS,"repeats":REPEATS,"runs":[],
        "limitations":["This probe measures bbolt.Open on a copy, not the Collector process",
        "NoFreelistSync=true is matched to the Collector database metadata; other Collector options may differ",
        "Advisory POSIX_FADV_DONTNEED does not guarantee a cold cache",
        "Docker process startup overhead is excluded from the internal Go open_ms timer",
        "Cgroup memory limit includes process memory but page cache accounting may differ from Collector"]}
    try:
        seed=m.ROOT/"seed"
        if seed.exists(): shutil.rmtree(seed)
        seed.mkdir(parents=True)
        m.run_collector(NAME,seed,1024)
        m.wait_health()
        report["records_ingested"]=m.emit()
        time.sleep(3)
        m.stop_collector(NAME)
        m.allow_snapshot_copy(seed)
        files=[p for p in seed.rglob("*") if p.is_file() and p.stat().st_size>=8192]
        if len(files)!=1: raise RuntimeError("Expected exactly one queue DB; found "+repr([str(p) for p in files]))
        db=files[0]
        report["database_file"]=str(db.relative_to(seed))
        report["database_bytes"]=db.stat().st_size
        conditions=[(1024,"warm"),(1024,"cold"),(256,"warm"),(256,"cold")]
        for repeat in range(REPEATS):
            order=conditions[:]
            random.Random(4600+repeat).shuffle(order)
            for memory,cache in order:
                key=f"r{repeat+1}-{memory}-{cache}"
                directory=m.ROOT/key
                directory.mkdir()
                target=directory/"queue.db"
                shutil.copyfile(db,target)
                target.chmod(0o666)
                if cache=="warm":
                    with target.open("rb") as f:
                        while f.read(1024*1024): pass
                    advised=False
                else:
                    advised=m.advise_cold(directory)
                container="phase46-"+key
                command("docker","rm","-f",container,check=False)
                run=command("docker","run","--name",container,
                    "--network","none","--memory",f"{memory}m",
                    "--memory-swap",f"{memory}m",
                    "-v",f"{directory}:/data:rw",
                    "-v",f"{BINARY}:/probe:ro",
                    "--entrypoint","/probe","ubuntu:24.04","--db","/data/queue.db",
                    "--timeout","90s",check=False)
                inspect=command("docker","inspect","-f",
                    "{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Status}}",
                    container,check=False)
                record={"repeat":repeat+1,"memory_mib":memory,"cache":cache,
                    "advisory_eviction_requested":advised,"container_state":inspect.stdout.strip(),
                    "returncode":run.returncode,"stderr":run.stderr[-4000:]}
                try: record["probe"]=json.loads(run.stdout)
                except json.JSONDecodeError: record["stdout"]=run.stdout[-4000:]
                report["runs"].append(record)
                (m.RESULTS/"phase46-summary.json").write_text(json.dumps(report,indent=2))
                print(key,record.get("probe",{}).get("open_ms"),record["container_state"],flush=True)
                command("docker","rm","-f",container,check=False)
                if run.returncode!=0: raise RuntimeError(key+": "+str(record))
        report["summary"]=[]
        for memory,cache in conditions:
            values=[r["probe"]["open_ms"] for r in report["runs"] if r["memory_mib"]==memory and r["cache"]==cache]
            report["summary"].append({"memory_mib":memory,"cache":cache,"n":len(values),
                "median_open_ms":statistics.median(values),"min_open_ms":min(values),"max_open_ms":max(values)})
    finally:
        m.stop_collector(NAME)
        server.shutdown()
        (m.RESULTS/"phase46-summary.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report["summary"],indent=2))
if __name__=="__main__": main()
