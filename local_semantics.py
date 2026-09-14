"""Offline multilingual sentence similarity; no network code on query path."""
from pathlib import Path
import threading,hashlib,sqlite3
MODEL_DIR=Path(__file__).resolve().parent/'data'/'models'/'multilingual-e5-small'
_model=None;_tokenizer=None;_lock=threading.RLock();_cache={}
CACHE_VERSION='e5-small-qint8-256-v1'
def ready():return (MODEL_DIR/'model.onnx').exists() and (MODEL_DIR/'tokenizer.json').exists()
def embed(texts):
    global _model,_tokenizer
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer
    with _lock:
        if _model is None:
            opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
            _model=ort.InferenceSession(str(MODEL_DIR/'model.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
            _tokenizer=Tokenizer.from_file(str(MODEL_DIR/'tokenizer.json'))
            _tokenizer.enable_truncation(max_length=256);_tokenizer.enable_padding(pad_id=1,pad_token='<pad>')
        result=[]
        for start in range(0,len(texts),12):
            enc=_tokenizer.encode_batch(texts[start:start+12]);ids=np.array([x.ids for x in enc],dtype=np.int64);mask=np.array([x.attention_mask for x in enc],dtype=np.int64)
            inputs={'input_ids':ids,'attention_mask':mask}
            if any(x.name=='token_type_ids' for x in _model.get_inputs()):inputs['token_type_ids']=np.zeros_like(ids)
            output=_model.run(None,inputs)[0]
            vec=(output*mask[:,:,None]).sum(axis=1)/mask.sum(axis=1)[:,None] if output.ndim==3 else output
            vec=vec/(np.linalg.norm(vec,axis=1,keepdims=True)+1e-12);result.extend(vec)
        return np.array(result)
def rerank(query,rows):
    if not ready():return rows
    import numpy as np
    with _lock:
        cache_db=sqlite3.connect(MODEL_DIR/'embeddings.sqlite3',timeout=30)
        cache_db.execute('CREATE TABLE IF NOT EXISTS embeddings(key TEXT PRIMARY KEY,vector BLOB)')
        missing=[];keys=[]
        for r in rows:
            key=hashlib.sha256((CACHE_VERSION+r['display']).encode()).hexdigest();keys.append(key)
            if key not in _cache:
                saved=cache_db.execute('SELECT vector FROM embeddings WHERE key=?',(key,)).fetchone()
                if saved:_cache[key]=np.frombuffer(saved[0],dtype=np.float32)
                else:missing.append((key,r['display']))
        if missing:
            vectors=embed(['passage: '+s for _,s in missing])
            for (key,_),v in zip(missing,vectors):
                _cache[key]=v.astype(np.float32)
                cache_db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?)',(key,_cache[key].tobytes()))
            cache_db.commit()
        cache_db.close()
        q=embed(['query: '+query])[0]
        for r,key in zip(rows,keys):
            semantic=float(np.dot(q,_cache[key]));r['lexical_score']=r['score'];r['semantic_score']=semantic
            r['score']=semantic*100+r['score']*.35
        if len(_cache)>6000:_cache.clear()
    return sorted(rows,key=lambda r:-r['score'])
