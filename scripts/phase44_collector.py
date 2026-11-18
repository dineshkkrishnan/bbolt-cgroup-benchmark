#!/usr/bin/env python3
"""Phase 4.3: real Collector persistent queue, not a synthetic bbolt opener."""
import argparse
import gzip
import http.server
import json
import os
from pathlib import Path
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.request

IMAGE = os.environ.get("PHASE44_IMAGE", "otel/opentelemetry-collector-contrib:0.140.0")
ROOT = Path(os.environ.get("PHASE44_ROOT", "scratch/phase44")).resolve()
CONFIG = Path("phase4/collector44.yaml").resolve()
RESULTS = Path("results/phase44").resolve()
RECORDS = int(os.environ.get("PHASE44_RECORDS", "200000"))
BATCH = int(os.environ.get("PHASE44_BATCH", "100"))
state = {"accept": False, "accepted_requests": 0, "rejected_requests": 0, "delivered_records": 0, "delivered_ids": set(), "duplicate_records": 0}
lock = threading.Lock()

class Sink(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size)
        if self.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
        with lock:
            accept = state["accept"]
            key = "accepted_requests" if accept else "rejected_requests"
            state[key] += 1
            if accept:
                payload = json.loads(raw)
                for resource in payload.get("resourceLogs", []):
                    for scope in resource.get("scopeLogs", []):
                        for record in scope.get("logRecords", []):
                            body = record.get("body", {}).get("stringValue", "")
                            prefix = body.split("-", 2)[:2]
                            if len(prefix) != 2 or prefix[0] != "phase44":
                                raise ValueError("Unexpected downstream log record")
                            index = int(prefix[1])
                            state["delivered_records"] += 1
                            if index in state["delivered_ids"]:
                                state["duplicate_records"] += 1
                            state["delivered_ids"].add(index)
        self.send_response(200 if accept else 503)
        self.end_headers()
        self.wfile.write(b"{}")
    def log_message(self, *args):
        return

def cmd(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, text=True, capture_output=True, **kwargs)

def get(url, payload=None, timeout=2):
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"} if payload else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, TimeoutError):
        return None

def wait_health(timeout=90):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if get("http://127.0.0.1:13133/") == 200:
            return time.monotonic() - start
        time.sleep(0.1)
    details = cmd("docker", "logs", "phase44-collector", check=False)
    status = cmd("docker", "inspect", "-f", "{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}", "phase44-collector", check=False)
    raise RuntimeError("Collector did not become healthy: " + status.stdout + "\\n" + details.stdout[-5000:] + details.stderr[-5000:])

def run_collector(name, directory, memory_mib):
    for folder in [directory, *[x for x in directory.rglob("*") if x.is_dir()]]:
        folder.chmod(0o777)
    for file in directory.rglob("*"):
        if file.is_file():
            file.chmod(0o666)
    cmd("docker", "rm", "-f", name, check=False)
    return cmd("docker", "run", "-d", "--name", name, "--network", "host",
        "--memory", f"{memory_mib}m", "--memory-swap", f"{memory_mib}m",
        "-v", f"{CONFIG}:/etc/otelcol-contrib/config.yaml:ro",
        "-v", f"{directory}:/var/lib/otelcol/queue",
        IMAGE, "--config=/etc/otelcol-contrib/config.yaml").stdout.strip()

def stop_collector(name):
    cmd("docker", "stop", "-t", "15", name, check=False)
    cmd("docker", "rm", "-f", name, check=False)

def allow_snapshot_copy(path):
    """Fix container-owned queue files without changing database contents."""
    cmd("docker", "run", "--rm", "--network", "none", "--user", "0:0",
        "-v", f"{path}:/data:rw", "--entrypoint", "/bin/chmod",
        "ubuntu:24.04", "-R", "a+rwX", "/data")

def queue_bytes(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

def advise_cold(path):
    supported = hasattr(os, "POSIX_FADV_DONTNEED")
    if not supported:
        return False
    for file in path.rglob("*"):
        if file.is_file():
            with file.open("rb") as f:
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    return True

def emit():
    accepted = 0
    for start in range(0, RECORDS, BATCH):
        end = min(start+BATCH, RECORDS)
        records = [{"timeUnixNano": str(1700000000000000000+i),
            "body": {"stringValue": f"phase44-{i}-" + "x"*1700}}
            for i in range(start,end)]
        body = {"resourceLogs":[{"scopeLogs":[{"logRecords":records}]}]}
        status = get("http://127.0.0.1:4318/v1/logs", json.dumps(body).encode(), timeout=20)
        if status != 200:
            raise RuntimeError(f"OTLP ingestion failed at batch {start}: HTTP {status}")
        accepted += len(records)
        if accepted % 20000 == 0:
            print(f"Queued {accepted}/{RECORDS} records", flush=True)
    return accepted

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 19090), Sink)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    name = "phase44-collector"
    report = {"image":IMAGE, "records_sent":RECORDS, "runs":[], "limitations":[
        "Health endpoint readiness is not equivalent to queue fully recovered",
        "Mock counts exporter HTTP requests, not individual log records",
        "Host file cache and container startup overhead are uncontrolled",
        "This is a small real-queue pilot; the seeded freelist state may differ from issue #52868"
    ]}
    try:
        seed = ROOT/"seed"
        seed.mkdir(exist_ok=True)
        run_collector(name, seed, 1024)
        wait_health()
        report["records_ingested"] = emit()
        time.sleep(3)
        stop_collector(name)
        allow_snapshot_copy(seed)
        report["seed_queue_bytes"] = queue_bytes(seed)
        print("Queue snapshot bytes:", report["seed_queue_bytes"], flush=True)
        report["rejected_export_requests"] = state["rejected_requests"]
        if report["seed_queue_bytes"] == 0:
            raise RuntimeError("No persisted queue database created")
        # Restore identical queue state before each restart. Run warm then advisory-cold,
        # alternating memory limit. Recovery delivery is deliberately blocked while timing.
        for memory, cache in [(1024,"warm"),(256,"cold"),(256,"warm"),(1024,"cold")]:
            print(f"Starting recovery: memory={memory}MiB cache={cache}", flush=True)
            directory = ROOT/f"recovery-{memory}-{cache}"
            if directory.exists():
                shutil.rmtree(directory)
            shutil.copytree(seed, directory)
            if cache == "warm":
                for file in directory.rglob("*"):
                    if file.is_file():
                        with file.open("rb") as f:
                            while f.read(1024*1024):
                                pass
                advised = False
            else:
                advised = advise_cold(directory)
            start = time.monotonic()
            try:
                run_collector(name, directory, memory)
                health_s = wait_health()
                time.sleep(3)
                inspection = cmd("docker", "inspect", "--format",
                    "{{.State.Status}} oom={{.State.OOMKilled}} pid={{.State.Pid}}", name,
                    check=False)
                cg = cmd("docker", "exec", name, "/otelcol-contrib", "--version", check=False)
                inspection.stdout += "\\ncollector_version: " + cg.stdout + cg.stderr
                logs = cmd("docker", "logs", name, check=False)
                (RESULTS/f"{memory}-{cache}.logs").write_text(logs.stdout+"\n"+logs.stderr)
                (RESULTS/f"{memory}-{cache}.cgroup.txt").write_text(inspection.stdout+"\n"+inspection.stderr)
                report["runs"].append({"memory_mib":memory,"cache_protocol":cache,
                    "advisory_eviction_requested":advised,"time_to_health_s":health_s,
                    "wall_to_health_s":time.monotonic()-start-3,
                    "queue_bytes":queue_bytes(directory),
                    "container_running":cmd("docker","inspect","-f","{{.State.Running}}",name).stdout.strip()})
            except Exception as exc:
                report["runs"].append({"memory_mib":memory,"cache_protocol":cache,"error":str(exc)})
                raise
            finally:
                diagnostics = cmd("docker", "logs", name, check=False)
                (RESULTS/f"{memory}-{cache}.logs").write_text(diagnostics.stdout+"\n"+diagnostics.stderr)
                stop_collector(name)
        # One separate delivery check, from the original seed.
        recovery = ROOT/"delivery"
        if recovery.exists():
            shutil.rmtree(recovery)
        shutil.copytree(seed,recovery)
        with lock:
            state["accept"] = True
        run_collector(name,recovery,1024)
        wait_health()
        start = time.monotonic()
        while time.monotonic()-start < 180:
            with lock:
                if len(state["delivered_ids"]) >= RECORDS:
                    break
            time.sleep(0.5)
        with lock:
            report["accepted_export_requests_after_restart"] = state["accepted_requests"]
            report["delivered_unique_records"] = len(state["delivered_ids"])
            report["delivered_total_records"] = state["delivered_records"]
            report["duplicate_records"] = state["duplicate_records"]
            report["missing_records"] = RECORDS - len(state["delivered_ids"])
        if report["missing_records"] != 0:
            raise RuntimeError("Queue drain incomplete: %d missing records" % report["missing_records"])
        print(json.dumps(report,indent=2))
    finally:
        stop_collector(name)
        server.shutdown()
        (RESULTS/"phase44-summary.json").write_text(json.dumps(report,indent=2)+"\n")

if __name__ == "__main__":
    main()
