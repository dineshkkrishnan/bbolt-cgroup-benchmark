// AI-assisted diagnostic for OpenTelemetry Collector Contrib issue #52868.
// This is a synthetic read workload, not a reproduction of Collector queue behavior.
package main

import (
 "encoding/binary"
 "encoding/json"
 "flag"
 "fmt"
 "math/rand"
 "os"
 "runtime"
 "strconv"
 "strings"
 "syscall"
 "time"

 bolt "go.etcd.io/bbolt"
)

func readFile(path string) string {
 b, err := os.ReadFile(path)
 if err != nil { return "unavailable: " + err.Error() }
 return strings.TrimSpace(string(b))
}
func counters() (int64, int64) {
 var r syscall.Rusage
 if err := syscall.Getrusage(syscall.RUSAGE_SELF, &r); err != nil { panic(err) }
 return r.Minflt, r.Majflt
}
func must(err error) { if err != nil { panic(err) } }
func main() {
 path := flag.String("db", "/bench/queue.db", "existing bbolt database")
 mode := flag.String("mode", "read", "read or startup")
 items := flag.Int("items", 50000, "number of sequential numeric keys")
 pattern := flag.String("pattern", "random", "sequential or random")
 passes := flag.Int("passes", 2, "number of full read passes")
 expectedMax := flag.Int64("expected-memory-bytes", 0, "required cgroup memory.max, in bytes")
 flag.Parse()
 if *items <= 0 || *passes <= 0 { panic("items and passes must be positive") }
 if *mode != "read" && *mode != "startup" { panic("mode must be read or startup") }
 if *pattern != "random" && *pattern != "sequential" { panic("invalid pattern") }
 max := readFile("/sys/fs/cgroup/memory.max")
 if *expectedMax > 0 && max != strconv.FormatInt(*expectedMax, 10) {
  panic(fmt.Sprintf("cgroup memory limit mismatch: got %q, expected %d", max, *expectedMax))
 }
 beforeEvents := readFile("/sys/fs/cgroup/memory.events")
 beforeStat := readFile("/sys/fs/cgroup/memory.stat")
 beforeIO := readFile("/sys/fs/cgroup/io.stat")
 beforeCurrent := readFile("/sys/fs/cgroup/memory.current")
 min0, maj0 := counters()
 start := time.Now()
 db, err := bolt.Open(*path, 0600, &bolt.Options{ReadOnly:true, Timeout:10*time.Second, NoFreelistSync:true})
 must(err)
 openMs := float64(time.Since(start).Microseconds()) / 1000
 min1, maj1 := counters()
 order := make([]int, 0)
 if *mode == "read" { order = make([]int, *items) }
 for i := range order { order[i] = i }
 if *pattern == "random" { rand.New(rand.NewSource(52868)).Shuffle(len(order), func(i,j int){ order[i],order[j]=order[j],order[i] }) }
 readStart := time.Now()
 var checksum uint64
 for pass:=0; *mode == "read" && pass<*passes; pass++ {
  must(db.View(func(tx *bolt.Tx) error {
   bucket := tx.Bucket([]byte("items"))
   if bucket == nil { return fmt.Errorf("items bucket missing") }
   for _, id := range order {
    var key [8]byte
    binary.BigEndian.PutUint64(key[:], uint64(id))
    val := bucket.Get(key[:])
    if val == nil { return fmt.Errorf("missing key %d", id) }
    // Touch a byte from each 4 KiB page of each value, plus its final byte.
    for i:=0; i<len(val); i+=4096 { checksum += uint64(val[i]) }
    checksum += uint64(val[len(val)-1])
   }
   return nil
  }))
 }
 readMs := float64(time.Since(readStart).Microseconds()) / 1000
 min2, maj2 := counters()
 must(db.Close())
 out := map[string]any{
  "go":runtime.Version(), "db":*path, "items":*items, "passes":*passes, "mode":*mode,
  "pattern":*pattern, "checksum":checksum, "open_ms":openMs, "read_ms":readMs,
  "open_minor_faults":min1-min0, "open_major_faults":maj1-maj0,
  "read_minor_faults":min2-min1, "read_major_faults":maj2-maj1,
  "cgroup_memory_max":max, "memory_current_before":beforeCurrent,
  "memory_current_after":readFile("/sys/fs/cgroup/memory.current"),
  "memory_peak":readFile("/sys/fs/cgroup/memory.peak"),
  "memory_events_before":beforeEvents, "memory_events_after":readFile("/sys/fs/cgroup/memory.events"),
  "memory_stat_before":beforeStat, "memory_stat_after":readFile("/sys/fs/cgroup/memory.stat"),
  "io_stat_before":beforeIO, "io_stat_after":readFile("/sys/fs/cgroup/io.stat"),
 }
 enc:=json.NewEncoder(os.Stdout); enc.SetIndent("", "  "); must(enc.Encode(out))
}
