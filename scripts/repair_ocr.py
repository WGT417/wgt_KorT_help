"""Resume-safe local OCR for pages whose embedded extraction contains little text."""
import sys, os, json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['OMP_THREAD_LIMIT']='1'
from core import *

def process(row):
    try:
        with pymupdf.open(ROOT/row['path']) as doc:
            page=doc[row['pdf_page']-1]
            tp=page.get_textpage_ocr(language='kor+eng',dpi=250,full=True,tessdata=str(DATA/'tessdata'))
            text=page.get_text(textpage=tp,sort=True)
        return row,text,None
    except Exception as e:return row,'',type(e).__name__

if __name__=='__main__':
    init_db()
    with connect() as db:
        rows=[dict(r) for r in db.execute("SELECT p.*,b.path FROM pages p JOIN books b ON p.book_id=b.id WHERE p.quality='sparse' AND p.method='embedded'")]
        db.execute("INSERT OR REPLACE INTO state VALUES('ocr',?)",(json.dumps({'total':len(rows),'done':0,'status':'running'}),))
    print('Sparse pages:',len(rows),flush=True)
    failures=[]
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(process,r) for r in rows]
        for done,future in enumerate(as_completed(futures),1):
            row,txt,error=future.result()
            if error:failures.append({'page_id':row['id'],'error':error})
            else:
                record={'text':txt,'method':'tesseract-kor-eng-250dpi','pdf_page':row['pdf_page'],'book_id':row['book_id']}
                (DATA/'text'/row['book_id']/f"{row['pdf_page']:04}.ocr.json").write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
                with connect() as db:
                    current=db.execute('SELECT * FROM pages WHERE id=?',(row['id'],)).fetchone()
                    if current['method']=='embedded':
                        db.execute("INSERT INTO search(search,rowid,text,compact) VALUES('delete',?,?,?)",(row['id'],row['text'],normalized(row['text'])))
                        db.execute('UPDATE pages SET text=?,compact=?,method=?,quality=? WHERE id=?',(txt,normalized(txt),record['method'],quality(txt),row['id']))
                        db.execute('INSERT INTO search(rowid,text,compact) VALUES(?,?,?)',(row['id'],txt,normalized(txt)))
            if done%20==0 or done==len(rows):
                with connect() as db:db.execute("INSERT OR REPLACE INTO state VALUES('ocr',?)",(json.dumps({'total':len(rows),'done':done,'failed':len(failures),'status':'complete' if done==len(rows) else 'running'}),))
                print(f'OCR {done}/{len(rows)}; errors={len(failures)}',flush=True)
    (DATA/'ocr-repair-report.json').write_text(json.dumps({'total':len(rows),'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
