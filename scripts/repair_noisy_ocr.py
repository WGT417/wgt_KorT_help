"""Re-OCR pages whose embedded text layer is unreadable, keeping whichever version reads better.

The embedded OCR of some scanned pages is damaged (e.g. '릎어보1', '휠-동') while
still containing enough letters to pass the sparse-page check. A Korean language
model score per character identifies those pages. Tesseract at 300 dpi is run on
them and adopted only when its score is clearly higher. Pages that stay unreadable
either way are marked quality='review' so search demotes them and the UI warns.
Original extraction is never modified; OCR results are saved separately.
"""
import sys, os, json, re, time, argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['OMP_THREAD_LIMIT']='1'
from core import *

THRESHOLD=-3.05   # below this per-character score the page is worth re-OCR
REVIEW=-3.4       # below this even after OCR the page is flagged for manual review
MARGIN=0.12       # OCR must beat the embedded text by this much to be adopted
METHOD='tesseract-kor-eng-300dpi'

def remark():
    """Recompute quality flags from stored scores without running OCR again.

    Prose pages score around -2.6; ordinary clean prose can reach -3.1, so the
    review flag uses the stricter REVIEW threshold. Tables, poems, phonetic
    symbols and front matter fall below it and are demoted in search.
    """
    with connect() as db:
        init_quality(db)
        rows=db.execute('SELECT q.page_id,q.score,q.ocr_score,p.quality FROM page_quality q JOIN pages p ON p.id=q.page_id WHERE q.ocr_score IS NOT NULL').fetchall()
        changed=0
        for r in rows:
            best=max(x for x in [r['score'],r['ocr_score']] if x is not None)
            new='review' if best<REVIEW else 'extracted'
            if new!=r['quality']:
                db.execute('UPDATE pages SET quality=? WHERE id=?',(new,r['page_id']));changed+=1
        counts=dict(db.execute('SELECT quality,COUNT(*) FROM pages GROUP BY quality').fetchall())
    print(f'remarked {changed} pages; quality counts {counts}')

def init_quality(db):
    db.execute('CREATE TABLE IF NOT EXISTS page_quality(page_id INTEGER PRIMARY KEY,method TEXT,score REAL,ocr_score REAL,adopted INTEGER,checked_at REAL)')

def scorer():
    from kiwipiepy import Kiwi
    kiwi=Kiwi(num_workers=4)
    def score(text):
        t=re.sub(r'\s+',' ',text).strip()
        if len(t)<50:return None
        result=kiwi.analyze(t,top_n=1)[0]
        return result[1]/len(t)
    def score_many(texts):
        prepared=[re.sub(r'\s+',' ',t).strip() for t in texts]
        out=[]
        for t,result in zip(prepared,kiwi.analyze(prepared,top_n=1)):
            out.append(result[0][1]/len(t) if len(t)>=50 else None)
        return out
    return score,score_many

def process(rows):
    """OCR a batch of pages from one book with a single open of the PDF."""
    results=[]
    try:
        with pymupdf.open(ROOT/rows[0]['path']) as doc:
            for row in rows:
                try:
                    text,lines=ocr_page(doc[row['pdf_page']-1],dpi=300)
                    results.append((row,text,lines,None))
                except Exception as e:results.append((row,'',[],type(e).__name__))
    except Exception as e:
        results=[(row,'',[],type(e).__name__) for row in rows]
    return results

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--book',default='')
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--remark',action='store_true',help='recompute quality flags from stored scores only')
    args=parser.parse_args()
    init_db()
    if args.remark:return remark()
    score,score_many=scorer()
    start=time.time()
    with connect() as db:
        init_quality(db)
        where="b.category!='참고자료' AND p.method='embedded' AND p.quality!='sparse'"
        params=[]
        if args.book:where+=' AND b.title LIKE ?';params.append(args.book+'%')
        rows=[dict(r) for r in db.execute(f'SELECT p.id,p.book_id,p.pdf_page,p.text,p.method,p.quality,b.path,b.title FROM pages p JOIN books b ON b.id=p.book_id WHERE {where}',params)]
        known={r['page_id']:r['score'] for r in db.execute('SELECT page_id,score FROM page_quality WHERE method=?',('embedded',))}
    todo=[r for r in rows if r['id'] not in known]
    print(f'Pages: {len(rows)}, scoring {len(todo)}',flush=True)
    for i in range(0,len(todo),200):
        chunk=todo[i:i+200]
        scores=score_many([r['text'] for r in chunk])
        with connect() as db:
            db.executemany('INSERT OR REPLACE INTO page_quality(page_id,method,score,checked_at) VALUES(?,?,?,?)',[(r['id'],'embedded',s,time.time()) for r,s in zip(chunk,scores)])
        for r,s in zip(chunk,scores):known[r['id']]=s
        if (i//200)%10==0:print(f'scored {min(i+200,len(todo))}/{len(todo)} {round(time.time()-start)}s',flush=True)
    candidates=[r for r in rows if known.get(r['id']) is not None and known[r['id']]<THRESHOLD]
    with connect() as db:
        done={r['page_id'] for r in db.execute('SELECT page_id FROM page_quality WHERE ocr_score IS NOT NULL')}
    candidates=[r for r in candidates if r['id'] not in done]
    if args.limit:candidates=candidates[:args.limit]
    print(f'Damaged pages to re-OCR: {len(candidates)}',flush=True)
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO state VALUES('ocr',?)",(json.dumps({'total':len(candidates),'done':0,'status':'running','kind':'noisy'}),))
    adopted=0;failures=[];reviewed=0
    batches=[];by_book={}
    for r in candidates:by_book.setdefault(r['book_id'],[]).append(r)
    for rows_of_book in by_book.values():
        for i in range(0,len(rows_of_book),12):batches.append(rows_of_book[i:i+12])
    n=0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(process,batch) for batch in batches]
        for future in as_completed(futures):
          for row,txt,lines,error in future.result():
            n+=1
            if error:failures.append({'page_id':row['id'],'error':error});continue
            embedded=known[row['id']];ocr=score(txt)
            use_ocr=ocr is not None and ocr>embedded+MARGIN
            best=max(x for x in [embedded,ocr] if x is not None)
            record={'text':txt,'lines':lines,'method':METHOD,'pdf_page':row['pdf_page'],'book_id':row['book_id'],'embedded_score':round(embedded,4),'ocr_score':round(ocr,4) if ocr is not None else None,'adopted':use_ocr}
            (DATA/'text'/row['book_id']/f"{row['pdf_page']:04}.ocr.json").write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
            new_quality='review' if best<REVIEW else 'extracted'
            with connect() as db:
                current=db.execute('SELECT text,method FROM pages WHERE id=?',(row['id'],)).fetchone()
                if use_ocr and current['method']=='embedded':
                    db.execute("INSERT INTO search(search,rowid,text,compact) VALUES('delete',?,?,?)",(row['id'],current['text'],normalized(current['text'])))
                    db.execute('UPDATE pages SET text=?,compact=?,method=?,quality=? WHERE id=?',(txt,normalized(txt),METHOD,new_quality,row['id']))
                    db.execute('INSERT INTO search(rowid,text,compact) VALUES(?,?,?)',(row['id'],txt,normalized(txt)))
                    adopted+=1
                else:db.execute('UPDATE pages SET quality=? WHERE id=?',(new_quality,row['id']))
                db.execute('UPDATE page_quality SET ocr_score=?,adopted=?,checked_at=? WHERE page_id=?',(ocr,int(use_ocr),time.time(),row['id']))
            reviewed+=new_quality=='review'
            if n%20==0 or n==len(candidates):
                with connect() as db:db.execute("INSERT OR REPLACE INTO state VALUES('ocr',?)",(json.dumps({'total':len(candidates),'done':n,'failed':len(failures),'status':'complete' if n==len(candidates) else 'running','kind':'noisy'}),))
                print(f'OCR {n}/{len(candidates)} adopted={adopted} review={reviewed} errors={len(failures)} {round(time.time()-start)}s',flush=True)
    report={'threshold':THRESHOLD,'margin':MARGIN,'pages_scored':len(rows),'damaged':len(candidates),'adopted_ocr':adopted,'still_review':reviewed,'failures':failures,'seconds':round(time.time()-start)}
    (DATA/'noisy-ocr-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('COMPLETE',json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
