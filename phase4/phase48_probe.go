//go:build linux
package main

import (
 "encoding/json"
 "flag"
 "fmt"
 "os"
 "runtime"
 "syscall"
 "time"
 bolt "go.etcd.io/bbolt"
)
func usage() (syscall.Rusage,error) { var r syscall.Rusage; err:=syscall.Getrusage(syscall.RUSAGE_SELF,&r); return r,err }
func main() {
 path:=flag.String("db","","database file to open")
 syncFreelist:=flag.Bool("sync-freelist",false,"persist freelist via a final empty transaction (preparation only)")
 prepare:=flag.Bool("prepare",false,"prepare a freelist-synced copy before timing")
 flag.Parse()
 if *path=="" {fmt.Fprintln(os.Stderr,"--db required");os.Exit(2)}
 opts:=&bolt.Options{Timeout:90*time.Second,NoSync:true,NoFreelistSync:true,FreelistType:bolt.FreelistMapType}
 if *prepare {
  db,err:=bolt.Open(*path,0600,opts);if err!=nil{panic(err)}
  if *syncFreelist {
   db.NoFreelistSync=false
   db.NoSync=false
   if err:=db.Update(func(*bolt.Tx)error{return nil});err!=nil{panic(err)}
  }
  if err:=db.Close();err!=nil{panic(err)}
  return
 }
 before,err:=usage();if err!=nil{panic(err)}
 start:=time.Now()
 db,err:=bolt.Open(*path,0600,opts)
 elapsed:=time.Since(start)
 after,e:=usage();if e!=nil{panic(e)}
 out:=map[string]interface{}{
  "open_ms":float64(elapsed.Nanoseconds())/1e6,
  "minor_faults":after.Minflt-before.Minflt,
  "major_faults":after.Majflt-before.Majflt,
  "go_version":runtime.Version(),
  "no_freelist_sync":true,"no_sync":true,"freelist_type":"map",
 }
 if err!=nil {out["error"]=err.Error()} else {
  st:=db.Stats()
  out["free_pages"]=st.FreePageN
  out["pending_pages"]=st.PendingPageN
  if e:=db.Close();e!=nil {out["close_error"]=e.Error()}
 }
 if e:=json.NewEncoder(os.Stdout).Encode(out);e!=nil{panic(e)}
 if err!=nil{os.Exit(1)}
}
