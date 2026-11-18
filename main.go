// Microbenchmark for OpenTelemetry issue #52868. AI-assisted initial scaffold.
package main

import (
 "encoding/binary"
 "encoding/json"
 "flag"
 "fmt"
 "os"
 "runtime"
 "syscall"
 "time"
 bolt "go.etcd.io/bbolt"
)
func usage() (int64,int64) { var r syscall.Rusage; if err:=syscall.Getrusage(syscall.RUSAGE_SELF,&r);err!=nil {panic(err)};return r.Minflt,r.Majflt }
func main(){
 mode:=flag.String("mode","fill","fill or open");path:=flag.String("db","/tmp/bench.db","database path");n:=flag.Int("items",100000,"item count");size:=flag.Int("value-bytes",1700,"bytes per value");syncFreelist:=flag.Bool("sync-freelist",false,"persist freelist per transaction");fsync:=flag.Bool("fsync",true,"enable fsync");flag.Parse()
 opts:=&bolt.Options{Timeout:10*time.Second,NoFreelistSync:!*syncFreelist,NoSync:!*fsync,FreelistType:bolt.FreelistMapType}
 a,b:=usage();start:=time.Now();db,err:=bolt.Open(*path,0600,opts);if err!=nil{panic(err)};elapsed:=time.Since(start);c,d:=usage()
 if *mode=="fill" {value:=make([]byte,*size);for i:=range value{value[i]=byte(i%251)};for offset:=0;offset<*n;offset+=1000 {end:=offset+1000;if end>*n{end=*n};if err:=db.Update(func(tx *bolt.Tx)error{bucket,e:=tx.CreateBucketIfNotExists([]byte("items"));if e!=nil{return e};for j:=offset;j<end;j++{var key [8]byte;binary.BigEndian.PutUint64(key[:],uint64(j));if e=bucket.Put(key[:],value);e!=nil{return e}};return nil});err!=nil{panic(err)}} } else if *mode!="open" {panic("invalid mode")}
 if err:=db.Close();err!=nil{panic(err)};info,err:=os.Stat(*path);if err!=nil{panic(err)}
 out:=map[string]any{"mode":*mode,"db_bytes":info.Size(),"open_ms":float64(elapsed.Microseconds())/1000,"open_minor_faults":c-a,"open_major_faults":d-b,"items_requested":*n,"value_bytes":*size,"sync_freelist":*syncFreelist,"fsync":*fsync,"go":runtime.Version()};enc:=json.NewEncoder(os.Stdout);enc.SetIndent("","  ");if err:=enc.Encode(out);err!=nil{panic(err)};fmt.Fprintln(os.Stderr,"Note: faults cover bolt.Open only; compare independent runs and cgroup counters externally")
}
