// Phase 4.2 diagnostic: advisory cold versus prewarmed file cache.
package filestorage

import (
 "context"
 "encoding/binary"
 "encoding/json"
 "fmt"
 "io"
 "os"
 "strconv"
 "strings"
 "syscall"
 "testing"
 "time"

 "golang.org/x/sys/unix"
 "go.uber.org/zap"
)

func p42Read(path string) string { b,e:=os.ReadFile(path);if e!=nil{return "unavailable: "+e.Error()};return strings.TrimSpace(string(b)) }
func p42Stats(path string)map[string]int64 {
 out:=map[string]int64{}
 for _,line:=range strings.Split(p42Read(path),"\n"){f:=strings.Fields(line);if len(f)==2{if n,e:=strconv.ParseInt(f[1],10,64);e==nil{out[f[0]]=n}}}
 return out
}
func p42Diff(a,b map[string]int64)map[string]int64 {o:=map[string]int64{};for k,v:=range b{o[k]=v-a[k]};return o}
func p42IO(path string)map[string]uint64{
 out:=map[string]uint64{}
 for _,line:=range strings.Split(p42Read(path),"\n"){
  fields:=strings.Fields(line);if len(fields)<2{continue}
  for _,part:=range fields[1:] {kv:=strings.SplitN(part,"=",2);if len(kv)==2{if n,e:=strconv.ParseUint(kv[1],10,64);e==nil{out[fields[0]+":"+kv[0]]=n}}}
 }
 return out
}
func p42IODiff(a,b map[string]uint64)map[string]uint64{o:=map[string]uint64{};for k,v:=range b{if v>=a[k]{o[k]=v-a[k]}};return o}
func p42Faults()(int64,int64){var r syscall.Rusage;if e:=syscall.Getrusage(syscall.RUSAGE_SELF,&r);e!=nil{panic(e)};return r.Minflt,r.Majflt}
func TestPhase42CacheControlledOpen(t *testing.T){
 mode:=os.Getenv("PHASE42_CACHE")
 if mode==""{t.Skip("opt-in")}
 if mode!="warm"&&mode!="cold"{t.Fatal("cache mode must be warm or cold")}
 path:=os.Getenv("PHASE42_DB");if path==""{t.Fatal("PHASE42_DB required")}
 f,e:=os.Open(path);if e!=nil{t.Fatal(e)}
 info,e:=f.Stat();if e!=nil{t.Fatal(e)}
 // Cold is an advisory request, not a guaranteed eviction. No global drop_caches.
 if mode=="cold"{
  if e=unix.Fadvise(int(f.Fd()),0,0,unix.FADV_DONTNEED);e!=nil{t.Fatal(e)}
 }else{
  if _,e=io.Copy(io.Discard,f);e!=nil{t.Fatal(e)}
 }
 if e=f.Close();e!=nil{t.Fatal(e)}
 beforeStat:=p42Stats("/sys/fs/cgroup/memory.stat")
 beforeEvents:=p42Stats("/sys/fs/cgroup/memory.events")
 beforeIO:=p42IO("/sys/fs/cgroup/io.stat")
 minor0,major0:=p42Faults()
 start:=time.Now()
 client,e:=newClient(zap.NewNop(),path,&Config{FSync:true,Timeout:30*time.Second,Compaction:&CompactionConfig{}})
 elapsed:=time.Since(start)
 minor1,major1:=p42Faults()
 afterIO:=p42IO("/sys/fs/cgroup/io.stat")
 afterStat:=p42Stats("/sys/fs/cgroup/memory.stat")
 afterEvents:=p42Stats("/sys/fs/cgroup/memory.events")
 if e!=nil{t.Fatal(e)}
 // Verify representative records after measurement.
 for _,j:=range []int{0,100000,199999}{
  var key [8]byte;binary.BigEndian.PutUint64(key[:],uint64(j))
  val,err:=client.Get(context.Background(),string(key[:]));if err!=nil{t.Fatal(err)}
  if len(val)!=1700{t.Fatalf("invalid value for %d: %d",j,len(val))}
 }
 if e=client.Close(context.Background());e!=nil{t.Fatal(e)}
 result:=map[string]any{
  "case":os.Getenv("PHASE42_CASE"),"cache_protocol":mode,"persisted_seed":os.Getenv("PHASE42_PERSIST")=="true",
  "db_bytes":info.Size(),"open_ms":float64(elapsed.Microseconds())/1000,
  "open_minor_faults":minor1-minor0,"open_major_faults":major1-major0,
  "memory_stat_delta":p42Diff(beforeStat,afterStat),"memory_events_delta":p42Diff(beforeEvents,afterEvents),
  "io_stat_delta_by_device":p42IODiff(beforeIO,afterIO),
  "cold_cache_verified":false,"cold_cache_note":"FADV_DONTNEED is advisory; inspect major faults and per-device read deltas",
 }
 b,e:=json.Marshal(result);if e!=nil{t.Fatal(e)}
 fmt.Printf("PHASE42_RESULT %s\n",string(b))
}
