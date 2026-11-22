#!/usr/bin/env python3
"""Repeat controlled freelist-open trials. Advisory-cold is not guaranteed cold."""
import ctypes
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import struct
import subprocess

ROOT=Path("results/phase48")
ROOT.mkdir(parents=True,exist_ok=True)
BIN=Path("phase4/phase48-probe").resolve()
GEN=Path("phase4/phase48-generate").resolve()
REPEATS=int(os.environ.get("PHASE48_REPEATS","20"))
KEYS=int(os.environ.get("PHASE48_KEYS","20000"))
assert 1 <= REPEATS <= 40
assert 1000 <= KEYS <= 200000
def run(*args):
    return subprocess.run([str(x) for x in args],check=True,capture_output=True,text=True).stdout
def meta_info(path):
    # bbolt page header: 16 bytes; meta: magic, version, pageSize, flags,
    # root bucket (16 bytes), freelist, pgid, txid, checksum (FNV-1a 64).
    with open(path,"rb") as f:
        first=f.read(4096)
        if len(first)<96: raise ValueError("truncated bbolt database")
        pagesize=struct.unpack_from("<I",first,24)[0]
        if pagesize<1024 or pagesize>65536 or pagesize&(pagesize-1):
            raise ValueError("invalid bbolt page size")
        f.seek(0)
        pages=[f.read(pagesize) for _ in range(2)]
    candidates=[]
    for index,p in enumerate(pages):
        magic,version,ps=struct.unpack_from("<III",p,16)
        if magic!=0xED0CDAED or version!=2 or ps!=pagesize:
            raise ValueError(f"invalid bbolt meta page {index}")
        expected=struct.unpack_from("<Q",p,72)[0]
        value=14695981039346656037
        for byte in p[16:72]:
            value=((value^byte)*1099511628211)&0xFFFFFFFFFFFFFFFF
        if value!=expected: continue
        freelist,pgid,txid=struct.unpack_from("<QQQ",p,48)
        candidates.append({"meta_page":index,"freelist_pgid":freelist,
                           "high_water_pgid":pgid,"txid":txid,
                           "page_size":pagesize,"freelist_persisted":freelist!=0xFFFFFFFFFFFFFFFF})
    if not candidates: raise ValueError("no valid bbolt metadata pages")
    return max(candidates,key=lambda x:x["txid"])

def inspect(path):
    logical=json.loads(run(BIN,"--db",path,"--inspect"))
    return {**logical,**meta_info(path)}

seed=ROOT/"seed.db"
run(GEN,"--db",seed,"--keys",KEYS,"--value-bytes","1024")
sources={}
for arm in ("unsynced","synced"):
    dest=ROOT/(arm+"-prepared.db")
    shutil.copyfile(seed,dest)
    args=[BIN,"--db",dest,"--prepare"]
    if arm=="synced": args.append("--sync-freelist")
    run(*args)
    sources[arm]=dest
validation={arm:inspect(path) for arm,path in sources.items()}
if validation["unsynced"]["freelist_persisted"]:
    raise AssertionError("unsynced database unexpectedly has a persisted freelist")
if not validation["synced"]["freelist_persisted"]:
    raise AssertionError("synced database does not have a persisted freelist")
for field in ("keys","content_sha256","page_size"):
    if validation["unsynced"][field]!=validation["synced"][field]:
        raise AssertionError(f"logical database mismatch in {field}")
(ROOT/"validation.json").write_text(json.dumps(validation,indent=2)+"\\n")
print("VALIDATION",json.dumps(validation,indent=2),flush=True)
libc=ctypes.CDLL(None,use_errno=True)
POSIX_FADV_DONTNEED=4
def cache_mode(path,mode):
    with open(path,"rb",buffering=0) as f:
        if mode=="warm":
            while f.read(1024*1024): pass
            return "read-through"
        ret=libc.posix_fadvise(f.fileno(),ctypes.c_longlong(0),ctypes.c_longlong(0),POSIX_FADV_DONTNEED)
        if ret: raise OSError(ret,os.strerror(ret))
        return "advisory-fadvise"
records=[]
conditions=[(a,c) for a in sources for c in ("warm","advisory-cold")]
for repeat in range(1,REPEATS+1):
    order=conditions[:]
    random.Random(4800+repeat).shuffle(order)
    for arm,cache in order:
        copy=ROOT/f"trial-{repeat}-{arm}-{cache}.db"
        shutil.copyfile(sources[arm],copy)
        hint=cache_mode(copy,cache)
        result=json.loads(run(BIN,"--db",copy))
        result.update({"repeat":repeat,"arm":arm,"cache":cache,"cache_preparation":hint,
                       "prepared_bytes":sources[arm].stat().st_size,
                       "trial_bytes":copy.stat().st_size})
        records.append(result)
        print(json.dumps(result),flush=True)
        copy.unlink()
summary=[]
for arm,cache in conditions:
    subset=[r for r in records if r["arm"]==arm and r["cache"]==cache]
    summary.append({"arm":arm,"cache":cache,"n":len(subset),
       **{f"median_{key}":statistics.median(r[key] for r in subset)
          for key in ("open_ms","minor_faults","major_faults")},
       "prepared_bytes":sources[arm].stat().st_size})
report={"repeats":REPEATS,"keys":KEYS,"bbolt_version":"1.4.3",
 "limitations":["Advisory eviction does not guarantee cold page cache",
 "Prepared copies can differ in size and layout",
 "Synthetic database, not production Collector startup",
 "Minor faults are not equivalent to storage reads",
 "No cgroup limits or I/O counters in this phase"],
 "summary":summary,"records":records,"validation":validation}
(ROOT/"report.json").write_text(json.dumps(report,indent=2)+"\n")
print("SUMMARY",json.dumps(summary,indent=2),flush=True)
