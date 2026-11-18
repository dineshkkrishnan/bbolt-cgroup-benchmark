#!/usr/bin/env python3
"""Phase 4.3: real Collector persistent queue, not a synthetic bbolt opener."""
import argparse
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

IMAGE = os.environ.get("PHASE43_IMAGE", "otel/opentelemetry-collector-contrib:0.140.0")
ROOT = Path(os.environ.get("PHASE43_ROOT", "scratch/phase43")).resolve()
CONFIG = Path("phase4/collector43.yaml").resolve()
RESULTS = Path("results/phase43").resolve()
RECORDS = int(os.environ.get("PHASE43_RECORDS", "5000"))
state = {"accept": False, "accepted_requests": 0, "rejected_requests": 0}
lock = threading.Lock()

class Sink(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        with lock:
            accept = state["accept"]
            key = "accepted_requests" if accept else "rejected_requests"
            state[key] += 1
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
    raise RuntimeError("Collector did not become healthy")

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
    for i in range(RECORDS):
        body = {"resourceLogs":[{"scopeLogs":[{"logRecords":[{
            "timeUnixNano":str(1700000000000000000+i),
            "body":{"stringValue":f"phase43-{i}-" + "x"*1500}
        }]}]}]}
        status = get("http://127.0.0.1:4318/v1/logs", json.dumps(body).encode(), timeout=10)
        if status != 200:
            raise RuntimeError(f"OTLP ingestion failed at record {i}: HTTP {status}")
        accepted += 1
    return accepted

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 19090), Sink)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    name = "phase43-collector"
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
        report["seed_queue_bytes"] = queue_bytes(seed)
        report["rejected_export_requests"] = state["rejected_requests"]
        if report["seed_queue_bytes"] == 0:
            raise RuntimeError("No persisted queue database created")
        # Restore identical queue state before each restart. Run warm then advisory-cold,
        # alternating memory limit. Recovery delivery is deliberately blocked while timing.
        for memory, cache in [(1024,"warm"),(256,"cold"),(256,"warm"),(1024,"cold")]:
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
            run_collector(name, directory, memory)
            try:
                health_s = wait_health()
                time.sleep(3)
                inspection = cmd("docker", "exec", name, "sh", "-c",
                    "cat /sys/fs/cgroup/memory.stat; echo EVENTS; cat /sys/fs/cgroup/memory.events; echo IO; cat /sys/fs/cgroup/io.stat",
                    check=False)
                logs = cmd("docker", "logs", name, check=False)
                (RESULTS/f"{memory}-{cache}.logs").write_text(logs.stdout+"\n"+logs.stderr)
                (RESULTS/f"{memory}-{cache}.cgroup.txt").write_text(inspection.stdout+"\n"+inspection.stderr)
                report["runs"].append({"memory_mib":memory,"cache_protocol":cache,
                    "advisory_eviction_requested":advised,"time_to_health_s":health_s,
                    "wall_to_health_s":time.monotonic()-start-3,
                    "queue_bytes":queue_bytes(directory),
                    "container_running":cmd("docker","inspect","-f","{{.State.Running}}",name).stdout.strip()})
            finally:
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
        while time.monotonic()-start < 45:
            with lock:
                if state["accepted_requests"] > 0:
                    break
            time.sleep(0.5)
        with lock:
            report["accepted_export_requests_after_restart"] = state["accepted_requests"]
        if report["accepted_export_requests_after_restart"] == 0:
            raise RuntimeError("No queued exports reached downstream after restart")
        print(json.dumps(report,indent=2))
    finally:
        stop_collector(name)
        server.shutdown()
        (RESULTS/"phase43-summary.json").write_text(json.dumps(report,indent=2)+"\n")

if __name__ == "__main__":
    main()
