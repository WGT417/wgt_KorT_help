"""Does search find the pages each concept entry was written from?

Gold pages are the verified `sources` of concepts/*.json; a result on the page
or next to it (±1) counts. Each concept is asked twice: by its name ('term')
and by a paraphrase that avoids the name ('paraphrase', eval_queries.json).
Gold lists are what one reader cited, not every relevant page, so compare modes
against each other rather than reading the numbers as absolute precision.

  python scripts/eval_retrieval.py                          # lexical, dense, hybrid
  python scripts/eval_retrieval.py --modes hybrid --sample 40
"""
import sys,json,time,re,argparse,random,statistics
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import vector_search as vs
from concepts import all_concepts

def questions(styles,sample):
    paraphrase=json.loads((Path(__file__).parent/'eval_queries.json').read_text(encoding='utf-8'))['paraphrase']
    items=[]
    for c in all_concepts():
        gold={(s['book'],int(s['pdf_page'])) for s in c.get('sources',[]) if s.get('status')=='verified'}
        if not gold:continue
        name=re.sub(r'\(.*?\)','',c['label'].split(':')[0]).strip()
        if len(name)>20:name=c.get('aliases',[name])[0]
        if 'term' in styles:items.append({'id':c['id'],'style':'term','query':name,'category':c['area'],'gold':gold})
        if 'paraphrase' in styles and c['id'] in paraphrase:items.append({'id':c['id'],'style':'paraphrase','query':paraphrase[c['id']],'category':c['area'],'gold':gold})
    if sample:
        random.seed(11);ids=sorted({i['id'] for i in items});keep=set(random.sample(ids,min(sample,len(ids))))
        items=[i for i in items if i['id'] in keep]
    return items

def dense(query,category,limit=8):
    hits=vs.nearest(vs.embed([query])[0],category,k=80);pages=[]
    for h in hits:
        if h['page_id'] not in pages:pages.append(h['page_id'])
    with core.connect() as db:
        rows={r['id']:r for r in db.execute('SELECT p.id,p.pdf_page,b.title FROM pages p JOIN books b ON b.id=p.book_id WHERE p.id IN (%s)'%','.join('?'*len(pages[:limit])),pages[:limit])} if pages else {}
    return [{'title':rows[p]['title'],'pdf_page':rows[p]['pdf_page'],'match':'dense'} for p in pages[:limit]]

def run(mode,item):
    if mode=='dense':return dense(item['query'],item['category'])
    if mode=='lexical':
        with patch.object(vs,'ready',return_value=False):return core.search_pages(item['query'],item['category'])
    return core.search_pages(item['query'],item['category'])

def score(results,gold):
    near=lambda r:any(r['title']==b and abs(r['pdf_page']-p)<=1 for b,p in gold)
    ranks=[i for i,r in enumerate(results) if near(r)]
    return {'hit1':bool(ranks and ranks[0]<1),'hit3':bool(ranks and ranks[0]<3),'hit8':bool(ranks),
        'rr':1/(ranks[0]+1) if ranks else 0.0,'precision':len(ranks)/len(results) if results else 0.0,'empty':not results,'count':len(results)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--modes',default='lexical,dense,hybrid')
    parser.add_argument('--styles',default='term,paraphrase')
    parser.add_argument('--sample',type=int,default=0,help='concepts to sample')
    parser.add_argument('--out',default=str(core.DATA/'retrieval-eval.json'))
    args=parser.parse_args()
    modes=args.modes.split(',');items=questions(args.styles.split(','),args.sample)
    if any(m!='lexical' for m in modes) and not vs.ready():sys.exit('벡터 색인이 준비되지 않았습니다: python scripts/build_vectors.py')
    report={'modes':modes,'questions':len(items),'summary':{},'details':[]}
    if modes!=['lexical']:vs.embed(['준비'])
    for mode in modes:
        for style in args.styles.split(','):
            rows=[];seconds=[]
            for item in [i for i in items if i['style']==style]:
                start=time.perf_counter();results=run(mode,item);seconds.append(time.perf_counter()-start)
                s=score(results,item['gold']);rows.append(s)
                report['details'].append({'mode':mode,'style':style,'id':item['id'],'query':item['query'],**{k:v for k,v in s.items()},
                    'results':[[r['title'],r['pdf_page'],r.get('match','')] for r in results]})
            if not rows:continue
            summary={k:round(statistics.mean(float(r[k]) for r in rows),3) for k in ['hit1','hit3','hit8','rr','precision','empty','count']}
            summary.update(n=len(rows),seconds=round(statistics.mean(seconds),2))
            report['summary'][f'{mode}/{style}']=summary
            print(f"{mode:8s} {style:10s} n={len(rows):3d}  hit@1 {summary['hit1']:.2f}  hit@3 {summary['hit3']:.2f}  hit@8 {summary['hit8']:.2f}  MRR {summary['rr']:.2f}  정밀도 {summary['precision']:.2f}  빈결과 {summary['empty']:.2f}  결과수 {summary['count']:.1f}  {summary['seconds']:.2f}초",flush=True)
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')

if __name__=='__main__':main()
