"""Dense passage retrieval with BGE-M3. Local model; no network on the query path.

The index (data/vectors/bge-m3.sqlite3) holds one row per chunk, a clean run
of sentences cut by passage_text.chunks, with its source excerpt and a float16
CLS vector. scripts/build_vectors.py writes it; this module only reads it.
"""
import os,sqlite3,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MODEL_DIR=ROOT/'data'/'models'/'bge-m3'
INDEX=ROOT/'data'/'vectors'/'bge-m3.sqlite3'
# Queries use the int8 model everywhere (same results on this computer and on
# Cloud Run; measured no loss against full precision). The full-precision model
# only builds the index, and the int8 one builds it when that is all there is.
QUERY_MODEL='model_quantized.onnx'
BUILD_MODELS=('model.onnx',QUERY_MODEL)
MAX_TOKENS=512
DIM=1024
_lock=threading.RLock()
_state={'session':None,'tokenizer':None,'index':None,'stamp':None}

def model_path(build=False):
    override=os.environ.get('BGE_M3_MODEL')
    if override:return MODEL_DIR/override
    if not build:return MODEL_DIR/QUERY_MODEL
    return next((MODEL_DIR/f for f in BUILD_MODELS if (MODEL_DIR/f).exists()),None)

def ready():
    from text_pipeline import VERSION
    path=model_path()
    if not path.exists() or not (MODEL_DIR/'tokenizer.json').exists() or not INDEX.exists():return False
    index=load()
    return index is not None and index['version']==VERSION and len(index['ids'])>0

def tokenizer(max_tokens=MAX_TOKENS):
    from tokenizers import Tokenizer
    with _lock:
        if _state['tokenizer'] is None:
            tok=Tokenizer.from_file(str(MODEL_DIR/'tokenizer.json'))
            tok.enable_padding(pad_id=1,pad_token='<pad>')
            _state['tokenizer']=tok
        tok=_state['tokenizer'];tok.enable_truncation(max_length=max_tokens)
        return tok

def open_session(path):
    import onnxruntime as ort
    opts=ort.SessionOptions();opts.intra_op_num_threads=int(os.environ.get('BGE_M3_THREADS',min(8,os.cpu_count() or 1)))
    # The arena keeps the largest batch's buffers for the life of the server.
    opts.enable_cpu_mem_arena=False
    return ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])

def session():
    with _lock:
        if _state['session'] is None:_state['session']=open_session(model_path())
        return _state['session']

def encode_batch(texts,max_tokens=MAX_TOKENS,pad_to=None):
    """Token ids and attention mask; `pad_to` fixes the length for shape-cached devices."""
    import numpy as np
    tok=tokenizer(max_tokens)
    if pad_to:tok.enable_padding(pad_id=1,pad_token='<pad>',length=pad_to)
    try:enc=tok.encode_batch(texts)
    finally:
        if pad_to:tok.enable_padding(pad_id=1,pad_token='<pad>')
    return np.array([e.ids for e in enc],dtype=np.int64),np.array([e.attention_mask for e in enc],dtype=np.int64)

def normalize(hidden):
    """BGE-M3 dense vector: the first token's hidden state, unit length."""
    import numpy as np
    cls=hidden[:,0].astype(np.float32)
    return cls/(np.linalg.norm(cls,axis=1,keepdims=True)+1e-12)

def embed(texts,max_tokens=MAX_TOKENS):
    import numpy as np
    s=session();names={i.name for i in s.get_inputs()};out=[]
    with _lock:
        for start in range(0,len(texts),8):
            ids,mask=encode_batch(texts[start:start+8],max_tokens)
            feed={'input_ids':ids,'attention_mask':mask}
            if 'token_type_ids' in names:feed['token_type_ids']=np.zeros_like(ids)
            out.append(normalize(s.run(None,feed)[0]))
    return np.concatenate(out) if out else np.zeros((0,DIM),dtype=np.float32)

def connect_index(path=INDEX):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30)
    # A 1024-dim float16 vector (2KB) overflows a 4KB page into a second page.
    db.execute('PRAGMA page_size=16384')
    db.executescript('''CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,passage_id INTEGER,page_id INTEGER,
        book_id TEXT,category TEXT,excerpt TEXT,text TEXT,digest TEXT);
      CREATE INDEX IF NOT EXISTS chunk_digest ON chunks(digest);
      CREATE INDEX IF NOT EXISTS chunk_passage ON chunks(passage_id);
      CREATE TABLE IF NOT EXISTS vectors(digest TEXT PRIMARY KEY,vector BLOB);
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);''')
    return db

def load():
    """Every embedded chunk as one float32 matrix, reloaded when the file changes."""
    import numpy as np
    if not INDEX.exists():return None
    stat=INDEX.stat();stamp=(stat.st_mtime_ns,stat.st_size)
    with _lock:
        if _state['stamp']==stamp:return _state['index']
        db=connect_index()
        try:
            meta=dict(db.execute('SELECT key,value FROM meta'))
            join='FROM chunks c JOIN vectors v ON v.digest=c.digest'
            n=db.execute('SELECT COUNT(*) '+join).fetchone()[0]
            # Filled row by row: holding every blob at once costs several times the matrix.
            matrix=np.empty((n,DIM),dtype=np.float32);columns=np.empty((n,3),dtype=np.int64)
            book_names=[];books=np.empty(n,dtype=np.int32);category_names=[];categories=np.empty(n,dtype=np.int16)
            for i,(cid,passage,page,book,category,vector) in enumerate(db.execute('SELECT c.id,c.passage_id,c.page_id,c.book_id,c.category,v.vector '+join+' ORDER BY c.id')):
                matrix[i]=np.frombuffer(vector,dtype=np.float16);columns[i]=(cid,passage,page)
                if book not in book_names:book_names.append(book)
                if category not in category_names:category_names.append(category)
                books[i]=book_names.index(book);categories[i]=category_names.index(category)
        finally:db.close()
        index={'version':meta.get('text_version'),'model':meta.get('model'),'matrix':matrix,
            'ids':columns[:,0].copy(),'passages':columns[:,1].copy(),'pages':columns[:,2].copy(),
            'book_names':book_names,'books':books,'category_names':category_names,'categories':categories}
        _state.update(index=index,stamp=stamp)
        return index

def nearest(query_vector,category='전체',book_id='',k=60):
    """Top chunks by cosine similarity: dicts with chunk, passage and page ids."""
    import numpy as np
    index=load()
    if index is None or not len(index['ids']):return []
    scores=index['matrix']@query_vector
    allowed=np.ones(len(scores),dtype=bool)
    if category!='전체':
        allowed&=index['categories']==(index['category_names'].index(category) if category in index['category_names'] else -1)
    if book_id:allowed&=index['books']==(index['book_names'].index(book_id) if book_id in index['book_names'] else -1)
    scores=np.where(allowed,scores,-2.0)
    k=min(k,int(allowed.sum()))
    if k<=0:return []
    top=np.argpartition(-scores,k-1)[:k];top=top[np.argsort(-scores[top])]
    db=connect_index()
    try:
        text={r[0]:(r[1],r[2]) for r in db.execute('SELECT id,excerpt,text FROM chunks WHERE id IN (%s)'%','.join('?'*len(top)),[int(index['ids'][i]) for i in top])}
    finally:db.close()
    return [{'chunk_id':int(index['ids'][i]),'passage_id':int(index['passages'][i]),'page_id':int(index['pages'][i]),
        'excerpt':text[int(index['ids'][i])][0],'text':text[int(index['ids'][i])][1],'semantic':float(scores[i])} for i in top]

def passage_similarity(query_vector,passage_ids):
    """Best chunk similarity for each requested passage that has chunks."""
    index=load()
    if index is None or not passage_ids:return {}
    import numpy as np
    wanted=np.isin(index['passages'],list(passage_ids))
    result={}
    for p,s in zip(index['passages'][wanted],index['matrix'][wanted]@query_vector):
        result[int(p)]=max(result.get(int(p),-1.0),float(s))
    return result
