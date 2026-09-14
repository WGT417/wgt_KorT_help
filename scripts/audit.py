from pathlib import Path
import sys, json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.runtime'))
import pymupdf
rows=[]
for path in sorted((ROOT/'개론서 파일').rglob('*.pdf')):
    with pymupdf.open(path) as doc:
        indices=sorted(set([0,min(15,len(doc)-1),len(doc)//2]))
        samples=[{'pdf_page':i+1,'chars':len(doc[i].get_text()),'sample':doc[i].get_text()[:180]} for i in indices]
        rows.append({'title':path.stem,'category':path.parent.name,'pages':len(doc),'samples':samples})
(ROOT/'data'/'audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
for r in rows: print(r['category'],r['title'],r['pages'],[s['chars'] for s in r['samples']])
