"""Audit and rebuild all library pages with local layout and Korean spacing."""
import sys,json,time,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from text_pipeline import *
from kiwipiepy import Kiwi

def main():
    kiwi=Kiwi(num_workers=2);start=time.time();report=[]
    with core.connect() as db:
        init_passages(db)
        books=[dict(b) for b in db.execute("SELECT * FROM books WHERE category!='참고자료' ORDER BY category,title")]
    for b in books:
        counts={};changed=0;processed=0
        with core.connect() as db:
            pages={r['pdf_page']:dict(r) for r in db.execute('SELECT * FROM pages WHERE book_id=?',(b['id'],))}
            done={r['page_id']:r['digest'] for r in db.execute('SELECT * FROM text_build WHERE version=?',(VERSION,))}
        with core.pymupdf.open(core.ROOT/b['path']) as doc:
            for number,page in enumerate(doc,1):
                r=pages.get(number)
                if not r:continue
                digest=hashlib.sha256((r['text']+r['method']).encode()).hexdigest()
                if done.get(r['id'])==digest:continue
                with core.connect() as db:
                    prior={p['raw']:p['display'] for p in db.execute('SELECT raw,display FROM passages WHERE page_id=?',(r['id'],))}
                ocr_lines=None
                if r['method']!='embedded':
                    ocr_file=core.DATA/'text'/b['id']/f'{number:04}.ocr.json'
                    if ocr_file.exists():ocr_lines=json.loads(ocr_file.read_text(encoding='utf-8')).get('lines')
                parts=layout_passages(page,ocr_lines) if ocr_lines else layout_passages(page) if r['method']=='embedded' else []
                # OCR-only pages without line geometry retain OCR provenance as one block.
                if not parts and r['text'].strip():parts=[{'raw':r['text'],'kind':classify(r['text']),'bbox':[0,0,page.rect.width,page.rect.height]}]
                # Batch spacing within each page in Kiwi's worker pool.
                source=[re.sub(r'\s+',' ',p['raw']).strip() for p in parts]
                missing=[i for i,p in enumerate(parts) if p['raw'] not in prior]
                repaired=iter(kiwi.space([source[i] for i in missing],reset_whitespace=True)) if missing else iter([])
                spaced=[prior[p['raw']] if p['raw'] in prior else next(repaired) for p in parts]
                for p,s,display in zip(parts,source,spaced):
                    p['display']=display if compact(display)==compact(s) else s
                    changed+=p['display']!=s;counts[p['kind']]=counts.get(p['kind'],0)+1
                with core.connect() as db:
                    db.execute('DELETE FROM passages WHERE page_id=?',(r['id'],))
                    db.executemany('INSERT INTO passages(page_id,ordinal,kind,raw,display,compact,bbox,version) VALUES(?,?,?,?,?,?,?,?)',[(r['id'],i,p['kind'],p['raw'],p['display'],compact(p['raw']),json.dumps(p['bbox']),VERSION) for i,p in enumerate(parts)])
                    db.execute('INSERT OR REPLACE INTO text_build VALUES(?,?,?)',(r['id'],digest,VERSION))
                processed+=1
                if processed%100==0:print(b['title'],number,'/',len(doc),flush=True)
        report.append({'book':b['title'],'pages_rebuilt':processed,'passage_kinds':counts,'spacing_changed':changed})
        print('DONE',b['title'],processed,counts,flush=True)
        (core.DATA/'passage-build-report.json').write_text(json.dumps({'version':VERSION,'seconds':round(time.time()-start),'books':report},ensure_ascii=False,indent=2),encoding='utf-8')
    print('COMPLETE',round(time.time()-start),flush=True)
if __name__=='__main__':main()
