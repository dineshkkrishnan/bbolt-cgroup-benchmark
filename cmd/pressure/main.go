// AI-assisted synthetic anonymous-memory pressure helper for cgroup v2 experiments.
package main

import (
 "flag"
 "fmt"
 "os"
 "runtime"
 "strconv"
 "strings"
 "time"
)

var held [][]byte

func main() {
 pct := flag.Int("percent", 60, "percent of memory.max to hold as resident anonymous memory (0 disables)")
 ready := flag.String("ready", "/tmp/pressure.ready", "ready signal file")
 flag.Parse()
 if *pct < 0 || *pct > 75 { panic("percent must be 0..75") }
 raw, err := os.ReadFile("/sys/fs/cgroup/memory.max")
 if err != nil { panic(err) }
 max, err := strconv.ParseInt(strings.TrimSpace(string(raw)), 10, 64)
 if err != nil || max <= 0 { panic("requires a finite cgroup v2 memory.max") }
 target := max * int64(*pct) / 100
 var allocated int64
 for allocated < target {
  size := int64(1024*1024)
  if target-allocated < size { size = target-allocated }
  b := make([]byte, int(size))
  for i:=0; i<len(b); i+=4096 { b[i] = byte(i/4096) }
  held = append(held,b)
  allocated += size
 }
 runtime.KeepAlive(held)
 fmt.Printf("pressure target=%d bytes percent=%d memory.max=%d\n", allocated, *pct, max)
 if err:=os.WriteFile(*ready, []byte(fmt.Sprintf("%d\n",allocated)),0600); err!=nil { panic(err) }
 for { runtime.KeepAlive(held); time.Sleep(time.Second) }
}
