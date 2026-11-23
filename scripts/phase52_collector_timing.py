#!/usr/bin/env python3
"""Phase 5.2: distinguish Docker overhead from process-start-to-health on real queues."""
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
from datetime import datetime, timezone
import math

spec=importlib.util.spec_from_file_location("phase44","scripts/phase44_collector.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT=Path("scratch/phase52").resolve()
m.RESULTS=Path("results/phase52").resolve()
m.RECORDS=int(os.environ.get("PHASE52_RECORDS","200000"))
REPEATS=int(os.environ.get("PHASE52_REPEATS","20"))
MEMORY=int(os.environ.get("PHASE52_MEMORY_MIB","1024"))
assert 1<=REPEATS<=20 and 1000<=m.RECORDS<=500000
assert MEMORY>=256
PROBE=Path("phase4/phase48-probe").resolve()
NAME="phase52-collector"

def command(*args):
    return subprocess.run([str(x) for x in args],check=True,capture_output=True,text=True).stdout

def inspect(path):
    import ast
    import struct
    source=ast.parse(Path("scripts/phase48_run.py").read_text())
    functions=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=="meta_info"]
    ns={"struct":struct,"os":os}
    exec(compile(ast.Module(body=functions,type_ignores=[]),"<meta>","exec"),ns)
    return {**json.loads(command(PROBE,"--db",path,"--inspect")) ,**ns["meta_info"](path)}

def percentile(values, q):
    values=sorted(values)
    pos=(len(values)-1)*q
    lo=math.floor(pos)
    hi=math.ceil(pos)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)

def poll_health(timeout=120):
    start=time.monotonic()
    while time.monotonic()-start<timeout:
        if m.get("http://127.0.0.1:13133/")==200:
            return time.monotonic()
        time.sleep(0.02)
    raise RuntimeError("Collector health endpoint not ready")

def started_at(name):
    value=m.cmd("docker","inspect","-f","{{.State.StartedAt}}",name).stdout.strip()
    return datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()

def main():
    m.ROOT.mkdir(parents=True,exist_ok=True)
    m.RESULTS.mkdir(parents=True,exist_ok=True)
    report={"records_requested":m.RECORDS,"repeats":REPEATS,"memory_mib":MEMORY,
        "collector_image":m.IMAGE,"runs":[],
        "limitations":["Health readiness is not equivalent to fully drained queue",
          "Docker CLI overhead reported separately; process-to-health uses host UTC and Docker StartedAt clocks",
          "Advisory eviction does not guarantee a cold cache",
          "Single GitHub-hosted runner, no controlled network storage",
          "Freelist preparation changes transaction metadata and may change free-page accounting"]}
    server=m.http.server.ThreadingHTTPServer(("127.0.0.1",19090),m.Sink)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        seed=m.ROOT/"seed"
        if seed.exists(): shutil.rmtree(seed)
        seed.mkdir()
        m.run_collector(NAME,seed,MEMORY)
        m.wait_health()
        report["records_ingested"]=m.emit()
        time.sleep(3)
        m.stop_collector(NAME)
        m.allow_snapshot_copy(seed)
        dbs=[p for p in seed.rglob("*") if p.is_file() and p.stat().st_size>=8192]
        if len(dbs)!=1: raise RuntimeError(f"expected exactly one Collector queue DB: {dbs}")
        relative=dbs[0].relative_to(seed)
        sources={}
        for arm in ("unsynced","synced"):
            directory=m.ROOT/("prepared-"+arm)
            if directory.exists(): shutil.rmtree(directory)
            shutil.copytree(seed,directory)
            target=directory/relative
            args=[PROBE,"--db",target,"--prepare"]
            if arm=="synced": args.append("--sync-freelist")
            command(*args)
            sources[arm]=directory
        validation={arm:inspect(directory/relative) for arm,directory in sources.items()}
        report["validation"]=validation
        if validation["unsynced"]["freelist_persisted"] or not validation["synced"]["freelist_persisted"]:
            raise AssertionError("incorrect freelist persistence states")
        for field in ("keys","content_sha256","page_size"):
            if validation["unsynced"][field]!=validation["synced"][field]:
                raise AssertionError("queue database mismatch: "+field)
        (m.RESULTS/"validation.json").write_text(json.dumps(validation,indent=2)+"\n")
        print("VALIDATION",json.dumps(validation),flush=True)
        conditions=[(arm,cache) for arm in sources for cache in ("warm","advisory-cold")]
        for rep in range(1,REPEATS+1):
            order=conditions[:]
            random.Random(5100+rep).shuffle(order)
            for arm,cache in order:
                key=f"r{rep}-{arm}-{cache}"
                directory=m.ROOT/key
                if directory.exists(): shutil.rmtree(directory)
                shutil.copytree(sources[arm],directory)
                if cache=="warm":
                    for p in directory.rglob("*"):
                        if p.is_file():
                            with p.open("rb") as f:
                                while f.read(1024*1024): pass
                    advised=False
                else:
                    advised=m.advise_cold(directory)
                    if not advised: raise RuntimeError("POSIX_FADV_DONTNEED unsupported")
                record={"repeat":rep,"arm":arm,"cache":cache,"memory_mib":MEMORY,
                        "advisory_eviction_requested":advised}
                started=time.monotonic()
                try:
                    m.run_collector(NAME,directory,MEMORY)
                    docker_return=time.monotonic()
                    record["docker_cli_s"]=docker_return-started
                    record["docker_started_at_epoch_s"]=started_at(NAME)
                    health_mono=poll_health(timeout=120)
                    health_epoch=time.time()
                    record["wall_to_health_s"]=health_mono-started
                    record["health_after_docker_cli_s"]=health_mono-docker_return
                    # Host wall clock is compared with Docker's process StartedAt timestamp.
                    # Record the cross-clock value separately rather than assuming exact precision.
                    record["process_to_health_approx_s"]=health_epoch-record["docker_started_at_epoch_s"]
                    if record["process_to_health_approx_s"]<0:
                        raise RuntimeError("inconsistent host and Docker start clocks")
                    status=m.cmd("docker","inspect","-f","{{.State.Running}} {{.State.OOMKilled}}",NAME)
                    record["container_state"]=status.stdout.strip()
                    if record["container_state"]!="true false":
                        raise RuntimeError("Collector unhealthy container state: "+record["container_state"])
                except Exception as exc:
                    record["error"]=str(exc)
                finally:
                    logs=m.cmd("docker","logs",NAME,check=False)
                    (m.RESULTS/(key+".logs")).write_text(logs.stdout+"\n"+logs.stderr)
                    m.stop_collector(NAME)
                    report["runs"].append(record)
                    (m.RESULTS/"report.json").write_text(json.dumps(report,indent=2)+"\n")
                    print("TRIAL",json.dumps(record),flush=True)
                if "error" in record: raise RuntimeError(f"{key}: {record['error']}")
        report["summary"]=[]
        for arm,cache in conditions:
            subset=[r["wall_to_health_s"] for r in report["runs"] if r["arm"]==arm and r["cache"]==cache]
            report["summary"].append({"arm":arm,"cache":cache,"n":len(subset),
                **{metric:{"median":statistics.median([r[metric] for r in report["runs"] if r["arm"]==arm and r["cache"]==cache]),
                           "p95":percentile([r[metric] for r in report["runs"] if r["arm"]==arm and r["cache"]==cache],.95),
                           "min":min(r[metric] for r in report["runs"] if r["arm"]==arm and r["cache"]==cache),
                           "max":max(r[metric] for r in report["runs"] if r["arm"]==arm and r["cache"]==cache)}
                   for metric in ("wall_to_health_s","docker_cli_s","process_to_health_approx_s")}})
        print("SUMMARY",json.dumps(report["summary"],indent=2),flush=True)
    finally:
        m.stop_collector(NAME)
        server.shutdown()
        (m.RESULTS/"report.json").write_text(json.dumps(report,indent=2)+"\n")

if __name__=="__main__": main()
