"""Embed passage chunks with BGE-M3 into data/vectors/bge-m3.sqlite3.

Resumable: vectors are keyed by the digest of the chunk text, so an interrupted
run continues where it stopped and a passage rebuild re-embeds only changed
chunks. Library text never leaves this computer.

  python scripts/build_vectors.py                      # Intel GPU via OpenVINO when installed
  python scripts/build_vectors.py --engine onnxruntime # CPU
  python scripts/build_vectors.py --limit 500          # trial run
"""
import sys,argparse,hashlib,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import numpy as np
import vector_search as vs
from passage_text import chunks
from text_pipeline import VERSION

# Fixed sequence lengths keep GPU kernels compiled once per shape.
BUCKETS=(48,96,160,256,384,512)

def collect(db):
    rows=db.execute('''SELECT x.id,x.page_id,x.raw,x.display,p.book_id,b.category
      FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id
      WHERE x.version=? AND x.kind IN ('body','note') AND b.category!='참고자료'
      ORDER BY p.book_id,p.pdf_page,x.ordinal''',(VERSION,))
    return [(pid,page,book,category,excerpt,text,hashlib.sha256(text.encode('utf-8')).hexdigest())
        for pid,page,raw,display,book,category in rows for excerpt,text in chunks(raw,display)]

class OpenVINO:
    def __init__(self,path,device):
        import openvino as ov
        runtime=ov.Core()
        runtime.set_property({'CACHE_DIR':str(core.ROOT/'tmp'/'openvino-cache')})
        self.model=runtime.compile_model(str(path),device)
        self.request=self.model.create_infer_request()
        self.names={i.get_any_name() for i in self.model.inputs}
        self.fixed=device=='GPU';self.label=f'openvino-{device.lower()}'
    def __call__(self,ids,mask):
        feed={'input_ids':ids,'attention_mask':mask}
        if 'token_type_ids' in self.names:feed['token_type_ids']=np.zeros_like(ids)
        return self.request.infer(feed)[self.model.outputs[0]]

class OnnxRuntime:
    fixed=False;label='onnxruntime-cpu'
    def __init__(self,path):
        self.session=vs.open_session(path);self.names={i.name for i in self.session.get_inputs()}
    def __call__(self,ids,mask):
        feed={'input_ids':ids,'attention_mask':mask}
        if 'token_type_ids' in self.names:feed['token_type_ids']=np.zeros_like(ids)
        return self.session.run(None,feed)[0]

def engine(name,path):
    if name in {'auto','openvino'}:
        try:
            import openvino as ov
            device='GPU' if 'GPU' in ov.Core().available_devices else 'CPU'
            if name=='openvino' or device=='GPU':return OpenVINO(path,device)
        except ImportError:
            if name=='openvino':sys.exit('openvino가 설치되어 있지 않습니다: python -m pip install openvino')
    return OnnxRuntime(path)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',choices=['auto','openvino','onnxruntime'],default='auto')
    parser.add_argument('--tokens',type=int,default=4096,help='padded tokens per batch')
    parser.add_argument('--limit',type=int,default=0,help='embed at most this many new chunks')
    args=parser.parse_args()
    path=vs.model_path(build=True)
    if not path or not path.exists():sys.exit('BGE-M3 모델이 없습니다: python scripts/download_bge_m3.py --full')
    with core.connect() as db:items=collect(db)
    index=vs.connect_index()
    with index:
        index.execute('DELETE FROM chunks')
        index.executemany('INSERT INTO chunks(passage_id,page_id,book_id,category,excerpt,text,digest) VALUES(?,?,?,?,?,?,?)',[i[:7] for i in items])
        index.execute("INSERT OR REPLACE INTO meta VALUES('text_version',?)",(VERSION,))
        index.execute("INSERT OR REPLACE INTO meta VALUES('model',?)",(f'BAAI/bge-m3 {path.name}',))
    done={d for (d,) in index.execute('SELECT digest FROM vectors')}
    todo=list({i[6]:i[5] for i in items if i[6] not in done}.items())
    if args.limit:todo=todo[:args.limit]
    print(f'청크 {len(items):,}개, 새로 임베딩할 청크 {len(todo):,}개 ({path.name})',flush=True)
    if not todo:return prune(index)
    run=engine(args.engine,path);print('엔진:',run.label,flush=True)
    tok=vs.tokenizer();tok.no_padding()
    lengths=[len(e.ids) for e in tok.encode_batch([t for _,t in todo])]
    tok.enable_padding(pad_id=1,pad_token='<pad>')
    groups={}
    for (digest,text),n in sorted(zip(todo,lengths),key=lambda x:x[1]):
        groups.setdefault(next(b for b in BUCKETS if n<=b or b==BUCKETS[-1]),[]).append((digest,text))
    start=time.perf_counter();count=0
    for bucket,group in groups.items():
        size=max(1,args.tokens//bucket)
        for b in range(0,len(group),size):
            batch=group[b:b+size];texts=[t for _,t in batch]
            if run.fixed and len(texts)<size:texts+=['']*(size-len(texts))
            ids,mask=vs.encode_batch(texts,vs.MAX_TOKENS,pad_to=bucket if run.fixed else None)
            vectors=vs.normalize(run(ids,mask))[:len(batch)]
            with index:index.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?)',[(d,v.astype(np.float16).tobytes()) for (d,_),v in zip(batch,vectors)])
            count+=len(batch);rate=count/(time.perf_counter()-start)
            print(f'  {count:,}/{len(todo):,}  {rate:.1f}개/초  남은 시간 {(len(todo)-count)/rate/60:.0f}분  (길이 {bucket})',flush=True)
    prune(index)

def prune(index):
    with index:
        removed=index.execute('DELETE FROM vectors WHERE digest NOT IN (SELECT digest FROM chunks)').rowcount
        missing=index.execute('SELECT COUNT(*) FROM chunks WHERE digest NOT IN (SELECT digest FROM vectors)').fetchone()[0]
    # Rewritten chunk rows leave free pages, and this file is synced to the bucket.
    # VACUUM also applies the page size set in connect_index to an older file.
    index.execute('VACUUM')
    print(f'완료. 쓰지 않는 벡터 {removed:,}개 삭제, 임베딩 안 된 청크 {missing:,}개',flush=True)
    index.close()

if __name__=='__main__':main()
