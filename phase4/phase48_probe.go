//go:build linux
package main

import (
 "encoding/json"
 "crypto/sha256"
 "encoding/hex"
 "encoding/binary"
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
 inspect:=flag.Bool("inspect",false,"inspect logical contents and metadata without timing")
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
 if *inspect {
  db,err:=bolt.Open(*path,0600,&bolt.Options{Timeout:90*time.Second,ReadOnly:true,FreelistType:bolt.FreelistMapType});if err!=nil{panic(err)}
  defer db.Close()
  h:=sha256.New()
  var keys uint64
  err=db.View(func(tx *bolt.Tx)error{
   return tx.ForEach(func(name []byte,b *bolt.Bucket)error{
    if err:=binary.Write(h,binary.LittleEndian,uint64(len(name)));err!=nil{return err}
    if _,err:=h.Write(name);err!=nil{return err}
    return b.ForEach(func(k,v []byte)error{
     if v==nil{return fmt.Errorf("nested bucket unsupported: %s",k)}
     for _,item:=range [][]byte{k,v} {
      if err:=binary.Write(h,binary.LittleEndian,uint64(len(item)));err!=nil{return err}
      if _,err:=h.Write(item);err!=nil{return err}
     }
     keys++
     return nil
    })
   })
  });if err!=nil{panic(err)}
  stat,err:=os.Stat(*path);if err!=nil{panic(err)}
  out:=map[string]interface{}{"keys":keys,"content_sha256":hex.EncodeToString(h.Sum(nil)),"file_bytes":stat.Size()}
  if err:=json.NewEncoder(os.Stdout).Encode(out);err!=nil{panic(err)}
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
