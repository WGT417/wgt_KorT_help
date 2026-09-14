"""Full-corpus invariants plus multi-topic retrieval review artifact."""
import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from text_pipeline import compact,VERSION
QUERIES=[
 ('문식성','능동적으로 읽기에 대해 알려줘'),('문식성','비판적 읽기'),('문식성','추론적 읽기'),('문식성','심미적 독서'),('문식성','독서 과정'),('문식성','배경지식'),('문식성','읽기 전략'),('문식성','작문의 과정에 대해 알려줘'),('문식성','내용 생성하기'),('문식성','고쳐쓰기'),('문식성','화법의 협력 원리'),('문식성','토론과 토의'),
 ('문법','어미의 종류에 대해 설명해줘'),('문법','선어말어미'),('문법','종결어미'),('문법','전성어미'),('문법','피동과 사동의 차이는 무엇인가'),('문법','형태소'),('문법','음운 변동'),('문법','음절'),('문법','보조용언'),('문법','중세 국어'),('문법','높임법'),
 ('문학','자유간접화법'),('문학','서술자'),('문학','시적 화자'),('문학','은유'),('문학','반어'),('문학','운율'),('문학','소설의 시점'),('문학','초점화'),('문학','고전 소설'),('문학','시조'),('문학','가사'),('문학','문학교육')]
def main():
 report={'version':VERSION,'books':[],'queries':[]}
 with core.connect() as db:
  for b in db.execute("SELECT * FROM books WHERE category!='참고자료' ORDER BY category,title"):
   pages=db.execute('SELECT p.id,p.pdf_page,t.version FROM pages p LEFT JOIN text_build t ON t.page_id=p.id WHERE p.book_id=?',(b['id'],)).fetchall()
   rows=db.execute('SELECT x.* FROM passages x JOIN pages p ON p.id=x.page_id WHERE p.book_id=?',(b['id'],)).fetchall()
   kinds={};bad=[];noisy=[]
   for r in rows:
    kinds[r['kind']]=kinds.get(r['kind'],0)+1
    if compact(r['raw'])!=compact(r['display']):bad.append(r['id'])
    import re
    if len(re.findall(r'[가-힣][A-Za-z%&@][가-힣]',r['raw']))>=3:noisy.append(r['id'])
   report['books'].append({'title':b['title'],'pages':b['pages'],'audited_pages':len(pages),'not_rebuilt':[p['pdf_page'] for p in pages if p['version']!=VERSION],'passages':len(rows),'kinds':kinds,'glyph_mismatch':bad,'ocr_review_passages':noisy})
 for category,q in QUERIES:
  start=time.perf_counter();rows=core.search_pages(q,category)
  report['queries'].append({'query':q,'category':category,'seconds':round(time.perf_counter()-start,3),'results':[{'title':r['title'],'page':r['pdf_page'],'kind':r['kind'],'score':r['score'],'text':r['display_excerpt']} for r in rows]})
  print(q,round(time.perf_counter()-start,2),[(r['title'],r['pdf_page']) for r in rows[:2]],flush=True)
  (core.DATA/'full-text-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 path=core.DATA/'full-text-audit.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Pages',sum(b['audited_pages'] for b in report['books']),'Not rebuilt',sum(len(b['not_rebuilt']) for b in report['books']),'Glyph mismatches',sum(len(b['glyph_mismatch']) for b in report['books']),flush=True)
 for q in report['queries']:print(q['query'],[(r['title'],r['page']) for r in q['results'][:2]],flush=True)
if __name__=='__main__':main()
