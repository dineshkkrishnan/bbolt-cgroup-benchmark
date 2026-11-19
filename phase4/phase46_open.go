package main

import (
 "encoding/json"
 "flag"
 "fmt"
 "os"
 "runtime"
 "time"
 bolt "go.etcd.io/bbolt"
)
func main() {
 path := flag.String("db", "", "path to copied real Collector bbolt database")
 timeout := flag.Duration("timeout", 90*time.Second, "open timeout")
 flag.Parse()
 if *path == "" { fmt.Fprintln(os.Stderr,"--db required"); os.Exit(2) }
 info, err := os.Stat(*path)
 if err != nil { panic(err) }
 start := time.Now()
 db, err := bolt.Open(*path, 0600, &bolt.Options{Timeout:*timeout, NoFreelistSync:true})
 elapsed := time.Since(start)
 result := map[string]interface{}{
  "path":*path,"database_bytes":info.Size(),"open_ns":elapsed.Nanoseconds(),
  "open_ms":float64(elapsed.Nanoseconds())/1e6,"go_version":runtime.Version(),
  "no_freelist_sync":true,"readonly":false,
 }
 if err != nil {
  result["error"]=err.Error()
 } else {
  stats := db.Stats()
  result["freelist_free_pages"]=stats.FreePageN
  result["freelist_pending_pages"]=stats.PendingPageN
  result["freelist_inuse_bytes"]=stats.FreelistInuse
  if closeErr:=db.Close(); closeErr!=nil {result["close_error"]=closeErr.Error()}
 }
 encoder:=json.NewEncoder(os.Stdout)
 encoder.SetIndent("","  ")
 encoder.Encode(result)
 if err != nil { os.Exit(1) }
}
