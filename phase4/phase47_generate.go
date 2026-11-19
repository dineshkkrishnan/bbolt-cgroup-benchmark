package main
import (
 "flag"
 "fmt"
 "os"
 bolt "go.etcd.io/bbolt"
)
func main(){
 path:=flag.String("db","","database path")
 count:=flag.Int("keys",120000,"number of keys")
 valueBytes:=flag.Int("value-bytes",3000,"bytes per value")
 flag.Parse()
 if *path=="" {panic("missing --db")}
 os.Remove(*path)
 db,err:=bolt.Open(*path,0600,&bolt.Options{NoFreelistSync:true})
 if err!=nil {panic(err)}
 defer db.Close()
 value:=make([]byte,*valueBytes)
 for i:=0;i<len(value);i++ {value[i]=byte(i%251)}
 const batch=1000
 for start:=0;start<*count;start+=batch {
  end:=start+batch;if end>*count {end=*count}
  if err:=db.Update(func(tx *bolt.Tx)error{
   b,e:=tx.CreateBucketIfNotExists([]byte("synthetic"));if e!=nil{return e}
   for i:=start;i<end;i++{
    key:=[]byte(fmt.Sprintf("key-%012d",i))
    if e=b.Put(key,value);e!=nil{return e}
   }
   return nil
  });err!=nil{panic(err)}
 }
 // Delete alternating keys to generate nontrivial free-page state.
 for start:=0;start<*count;start+=batch {
  end:=start+batch;if end>*count {end=*count}
  if err:=db.Update(func(tx *bolt.Tx)error{
   b:=tx.Bucket([]byte("synthetic"))
   for i:=start;i<end;i+=2{
    if e:=b.Delete([]byte(fmt.Sprintf("key-%012d",i)));e!=nil{return e}
   }
   return nil
  });err!=nil{panic(err)}
 }
 fmt.Printf("synthetic database generated: keys=%d value_bytes=%d\n",*count,*valueBytes)
}
