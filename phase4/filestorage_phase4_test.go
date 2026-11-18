// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// Phase 4 diagnostic: injected into upstream filestorage package by the workflow.
// This tests the actual newClient/Get path, not a simulated API.
package filestorage

import (
 "context"
 "encoding/binary"
 "encoding/json"
 "fmt"
 "os"
 "strconv"
 "testing"
 "time"

 "go.etcd.io/bbolt"
 "go.uber.org/zap"
)

func TestPhase4FileStorageRecovery(t *testing.T) {
 if os.Getenv("PHASE4_ENABLED")!="1" { t.Skip("opt-in integration diagnostic") }
 dir:=os.Getenv("PHASE4_DIR")
 if dir=="" { t.Fatal("PHASE4_DIR required") }
 if err:=os.MkdirAll(dir,0700);err!=nil { t.Fatal(err) }
 path:=dir+"/collector.db"
 persist:=os.Getenv("PHASE4_PERSIST")=="true"
 count:=200000
 if s:=os.Getenv("PHASE4_ITEMS");s!="" { n,e:=strconv.Atoi(s);if e!=nil||n<=0 {t.Fatal("invalid items")};count=n }
 // Populate the real filestorage default bucket using the same bbolt options,
 // varying only the on-disk freelist persistence in the seed stage.
 opts:=bboltOptions(&Config{FSync:true,Timeout:30*time.Second})
 opts.NoFreelistSync=!persist
 db,err:=bbolt.Open(path,0600,&opts);if err!=nil {t.Fatal(err)}
 value:=make([]byte,1700)
 for i:=range value {value[i]=byte(i%251)}
 for start:=0;start<count;start+=1000 {
  end:=start+1000;if end>count {end=count}
  err=db.Update(func(tx *bbolt.Tx)error{
   bucket,e:=tx.CreateBucketIfNotExists(defaultBucket);if e!=nil{return e}
   for j:=start;j<end;j++ {var k [8]byte;binary.BigEndian.PutUint64(k[:],uint64(j));if e=bucket.Put(k[:],value);e!=nil{return e}}
   return nil
  });if err!=nil {t.Fatal(err)}
 }
 if err=db.Close();err!=nil {t.Fatal(err)}
 info,err:=os.Stat(path);if err!=nil {t.Fatal(err)}
 // Actual filestorage newClient always uses NoFreelistSync=true.
 cfg:=&Config{FSync:true,Timeout:30*time.Second,Compaction:&CompactionConfig{}}
 start:=time.Now()
 client,err:=newClient(zap.NewNop(),path,cfg)
 openDuration:=time.Since(start)
 if err!=nil {t.Fatal(err)}
 ctx:=context.Background()
 readStart:=time.Now()
 for j:=0;j<count;j+=20 {
  var k [8]byte;binary.BigEndian.PutUint64(k[:],uint64(j))
  v,e:=client.Get(ctx,string(k[:]));if e!=nil {t.Fatal(e)}
  if len(v)!=len(value) {t.Fatalf("key %d unexpected len %d",j,len(v))}
 }
 readDuration:=time.Since(readStart)
 if err=client.Close(ctx);err!=nil {t.Fatal(err)}
 out:=map[string]any{"case":os.Getenv("PHASE4_CASE"),"persisted_freelist_seed":persist,"items":count,"db_bytes":info.Size(),"newClient_open_ms":float64(openDuration.Microseconds())/1000,"client_sampled_get_ms":float64(readDuration.Microseconds())/1000,"actual_filestorage_client":true}
 b,_:=json.Marshal(out);fmt.Println("PHASE4_RESULT "+string(b))
}
