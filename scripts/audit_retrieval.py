"""Audit every indexed page and record reproducible search probes."""
import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
queries=[('작문의 과정에 대해 알려줘','문식성'),('쓰기 과정','문식성'),('내용 생성하기','문식성'),('내용 조직하기','문식성'),('고쳐쓰기','문식성'),('읽기의 목적에서 심미적 독서는 문학 작품을 읽는 것인가?','문식성'),('피동과 사동의 차이는 무엇인가?','문법'),('음운 변동','문법'),('형태소','문법'),('중세 국어','문법'),('자유간접화법','문학'),('서술자','문학'),('은유','문학'),('시적 화자','문학')]
report={'books':[],'probes':[]}
with core.connect() as db:
    for b in db.execute("SELECT * FROM books WHERE category!='참고자료' ORDER BY category,title"):
        rows=db.execute('SELECT * FROM pages WHERE book_id=? ORDER BY pdf_page',(b['id'],)).fetchall()
        report['books'].append({'title':b['title'],'expected':b['pages'],'indexed':len(rows),'missing':sorted(set(range(1,b['pages']+1))-{r['pdf_page'] for r in rows}),'empty':[r['pdf_page'] for r in rows if not r['text'].strip()],'sparse':[r['pdf_page'] for r in rows if core.quality(r['text'])=='sparse'],'compact_mismatch':[r['pdf_page'] for r in rows if r['compact']!=core.normalized(r['text'])],'unverified_numbers':sum(r['printed_page'] is None for r in rows)})
for q,c in queries:
    start=time.perf_counter();rows=core.search_pages(q,c)
    report['probes'].append({'query':q,'terms':core.query_terms(q),'seconds':round(time.perf_counter()-start,3),'results':[{'title':r['title'],'page':r['pdf_page'],'score':r['score'],'excerpt':r['excerpt']} for r in rows]})
out=core.DATA/'retrieval-audit.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
for b in report['books']:print(b['title'],b['indexed'],'missing',len(b['missing']),'empty',len(b['empty']),'sparse',len(b['sparse']),'compact mismatch',len(b['compact_mismatch']))
for p in report['probes']:print(p['query'],p['seconds'],[(r['title'],r['page']) for r in p['results'][:3]])
