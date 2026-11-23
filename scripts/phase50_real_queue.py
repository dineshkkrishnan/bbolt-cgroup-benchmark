#!/usr/bin/env python3
"""Phase 5: validate freelist effect using an actual Collector file_storage queue.
Direct bbolt.Open timing only; not end-to-end Collector startup.
"""
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

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

m=load("phase44","scripts/phase44_collector.py")
p=load("phase48","scripts/phase48_run.py") if False else None
m.ROOT=Path("scratch/phase50").resolve()
m.RESULTS=Path("results/phase50").resolve()
m.RECORDS=int(os.environ.get("PHASE50_RECORDS","200000"))
REPEATS=int(os.environ.get("PHASE50_REPEATS","5"))
assert 1<=REPEATS<=20
assert 1000<=m.RECORDS<=500000
PROBE=Path("phase4/phase48-probe").resolve()
NAME="phase50-collector"

def command(*args):
    return subprocess.run([str(x) for x in args],check=True,capture_output=True,text=True).stdout

def inspect(path):
    # Metadata reader from Phase 4.9, loaded without executing its benchmark.
    import ast
    import types
    source=Path("scripts/phase48_run.py").read_text()
    tree=ast.parse(source)
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="meta_info"]
    ns={"struct":__import__("struct"),"os":os}
    exec(compile(ast.Module(body=selected,type_ignores=[]),"<meta_info>","exec"),ns)
    logical=json.loads(command(PROBE,"--db",path,"--inspect"))
    return {**logical,**ns["meta_info"](path)}

def main():
    m.ROOT.mkdir(parents=True,exist_ok=True)
    m.RESULTS.mkdir(parents=True,exist_ok=True)
    report={"records_requested":m.RECORDS,"repeats":REPEATS,"records":[],
      "limitations":["Measures direct bbolt.Open on real Collector queue database, not Collector startup",
        "Synced copy requires an additional preparation transaction; internal layout may differ",
        "Advisory eviction does not guarantee a cold cache",
        "No network-attached storage or controlled cgroup memory pressure"]}
    server=m.http.server.ThreadingHTTPServer(("127.0.0.1",19090),m.Sink)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        seed=m.ROOT/"seed"
        if seed.exists(): shutil.rmtree(seed)
        seed.mkdir()
        m.run_collector(NAME,seed,1024)
        m.wait_health()
        report["records_ingested"]=m.emit()
        time.sleep(3)
        m.stop_collector(NAME)
        m.allow_snapshot_copy(seed)
        dbs=[f for f in seed.rglob("*") if f.is_file() and f.stat().st_size>=8192]
        if len(dbs)!=1: raise RuntimeError(f"expected one Collector bbolt DB, got {dbs}")
        db=dbs[0]
        sources={}
        for arm in ("unsynced","synced"):
            dest=m.ROOT/(arm+".db")
            shutil.copyfile(db,dest)
            args=[PROBE,"--db",dest,"--prepare"]
            if arm=="synced": args.append("--sync-freelist")
            command(*args)
            sources[arm]=dest
        validation={arm:inspect(path) for arm,path in sources.items()}
        report["validation"]=validation
        if validation["unsynced"]["freelist_persisted"] or not validation["synced"]["freelist_persisted"]:
            raise AssertionError("freelist state not as expected")
        for field in ("keys","content_sha256","page_size"):
            if validation["unsynced"][field]!=validation["synced"][field]:
                raise AssertionError("queue logical mismatch: "+field)
        (m.RESULTS/"validation.json").write_text(json.dumps(validation,indent=2))
        print("VALIDATION",json.dumps(validation),flush=True)
        conditions=[(a,c) for a in sources for c in ("warm","advisory-cold")]
        for rep in range(1,REPEATS+1):
            order=conditions[:]
            random.Random(5000+rep).shuffle(order)
            for arm,cache in order:
                trial=m.ROOT/f"trial-{rep}-{arm}-{cache}.db"
                shutil.copyfile(sources[arm],trial)
                if cache=="warm":
                    with trial.open("rb") as f:
                        while f.read(1024*1024): pass
                else:
                    import ctypes
                    libc=ctypes.CDLL(None)
                    with trial.open("rb",buffering=0) as f:
                        rc=libc.posix_fadvise(f.fileno(),ctypes.c_longlong(0),ctypes.c_longlong(0),4)
                    if rc: raise OSError(rc,"posix_fadvise failed")
                result=json.loads(command(PROBE,"--db",trial))
                result.update({"arm":arm,"cache":cache,"repeat":rep,
                    "prepared_bytes":sources[arm].stat().st_size})
                report["records"].append(result)
                print("TRIAL",json.dumps(result),flush=True)
                trial.unlink()
        report["summary"]=[]
        for arm,cache in conditions:
            subset=[r for r in report["records"] if r["arm"]==arm and r["cache"]==cache]
            report["summary"].append({"arm":arm,"cache":cache,"n":len(subset),
              **{f"median_{k}":statistics.median(r[k] for r in subset)
                 for k in ("open_ms","minor_faults","major_faults")}})
        print("SUMMARY",json.dumps(report["summary"],indent=2),flush=True)
    finally:
        m.stop_collector(NAME)
        server.shutdown()
        (m.RESULTS/"report.json").write_text(json.dumps(report,indent=2)+"\n")

if __name__=="__main__":
    main()
