// Phase 4.1: actual upstream filestorage client, separate seed and recovery.
package filestorage

import (
 "context"
 "encoding/binary"
 "encoding/json"
 "fmt"
 "os"
 "strconv"
 "strings"
 "testing"
 "time"

 "go.etcd.io/bbolt"
 "go.uber.org/zap"
)

func phase41Read(path string) string {
 b,e:=os.ReadFile(path);if e!=nil{return "ERROR: "+e.Error()}
 return strings.TrimSpace(string(b))
}
func phase41Counters(path string) map[string]int64 {
 result:=map[string]int64{}
 for _,line:=range strings.Split(phase41Read(path),"\n") {
  f:=strings.Fields(line)
  if len(f)==2 { if n,e:=strconv.ParseInt(f[1],10,64);e==nil {result[f[0]]=n} }
 }
 return result
}
func phase41Delta(a,b map[string]int64)map[string]int64{
 out:=map[string]int64{}
 for k,v:=range b {out[k]=v-a[k]}
 return out
}
func TestPhase41SeedOrRecover(t *testing.T) {
 mode:=os.Getenv("PHASE41_MODE")
 if mode=="" {t.Skip("opt-in")}
 path:=os.Getenv("PHASE41_DB")
 if path=="" {t.Fatal("PHASE41_DB missing")}
 n:=200000
 if x:=os.Getenv("PHASE41_ITEMS");x!="" {v,e:=strconv.Atoi(x);if e!=nil||v<1 {t.Fatal("invalid items")};n=v}
 persist:=os.Getenv("PHASE41_PERSIST")=="true"
 if mode=="seed" {
  opts:=bboltOptions(&Config{FSync:true,Timeout:30*time.Second})
  opts.NoFreelistSync=!persist
  db,e:=bbolt.Open(path,0600,&opts);if e!=nil{t.Fatal(e)}
  value:=make([]byte,1700);for i:=range value{value[i]=byte(i%251)}
  for start:=0;start<n;start+=1000{
   end:=start+1000;if end>n{end=n}
   e=db.Update(func(tx *bbolt.Tx)error{
    bucket,err:=tx.CreateBucketIfNotExists(defaultBucket);if err!=nil{return err}
    for j:=start;j<end;j++{
     var key [8]byte;binary.BigEndian.PutUint64(key[:],uint64(j))
     if err=bucket.Put(key[:],value);err!=nil{return err}
    };return nil
   });if e!=nil{t.Fatal(e)}
  }
  if e=db.Close();e!=nil{t.Fatal(e)}
  info,e:=os.Stat(path);if e!=nil{t.Fatal(e)}
  fmt.Printf("PHASE41_SEED %s\n",mustPhase41JSON(map[string]any{"persist":persist,"db_bytes":info.Size(),"items":n}))
  return
 }
 if mode!="recover"{t.Fatalf("invalid mode %q",mode)}
 // Capture the cgroup counters immediately around the actual newClient call.
 beforeStat:=phase41Counters("/sys/fs/cgroup/memory.stat")
 beforeEvents:=phase41Counters("/sys/fs/cgroup/memory.events")
 beforeIO:=phase41Read("/sys/fs/cgroup/io.stat")
 beforeMem:=phase41Read("/sys/fs/cgroup/memory.current")
 start:=time.Now()
 client,e:=newClient(zap.NewNop(),path,&Config{FSync:true,Timeout:30*time.Second,Compaction:&CompactionConfig{}})
 elapsed:=time.Since(start)
 afterStat:=phase41Counters("/sys/fs/cgroup/memory.stat")
 afterEvents:=phase41Counters("/sys/fs/cgroup/memory.events")
 afterIO:=phase41Read("/sys/fs/cgroup/io.stat")
 afterMem:=phase41Read("/sys/fs/cgroup/memory.current")
 if e!=nil{t.Fatal(e)}
 ctx:=context.Background()
 for _,j:=range []int{0,n/2,n-1}{
  var key [8]byte;binary.BigEndian.PutUint64(key[:],uint64(j))
  v,err:=client.Get(ctx,string(key[:]));if err!=nil{t.Fatal(err)}
  if len(v)!=1700{t.Fatalf("unexpected value length for key %d: %d",j,len(v))}
 }
 if e=client.Close(ctx);e!=nil{t.Fatal(e)}
 fmt.Printf("PHASE41_RESULT %s\n",mustPhase41JSON(map[string]any{
  "case":os.Getenv("PHASE41_CASE"),"persisted_seed":persist,"open_ms":float64(elapsed.Microseconds())/1000,
  "memory_stat_delta_during_open":phase41Delta(beforeStat,afterStat),
  "memory_events_delta_during_open":phase41Delta(beforeEvents,afterEvents),
  "io_before_open":beforeIO,"io_after_open":afterIO,
  "memory_current_before_open":beforeMem,"memory_current_after_open":afterMem,
  "verified_keys":3,
 }))
}
func mustPhase41JSON(v any)string{b,e:=json.Marshal(v);if e!=nil{panic(e)};return string(b)}
