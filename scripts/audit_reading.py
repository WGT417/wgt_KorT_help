"""Full-corpus survey of what the reader is actually shown.

A card puts two things on the screen: the excerpt (the window the lexical search
picks, or the indexed chunk a semantic match returns) and the tables printed
beside it on the same page. This walks every passage in the 26 books, builds both
exactly as passage_search.layout_source does, and counts what still carries
visible scan damage.

Writes data/reading-audit.json (per book counts, dropped-table reasons, samples).
Nothing in the database is modified.
"""
import sys,re,json,time,argparse,random
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from text_pipeline import VERSION,compact,restore_terms,correct_display,tidy_display,strange_ratio,corpus_words,read_citations
from passage_text import chunks,noise,ocr_damage
from passage_search import table_rows,readable_table,PRINTED,INDEX_ENTRY

def table_verdict(rows):
    """Why readable_table turned a table down, for the report."""
    cells=[c for row in rows for c in row]
    if not cells:return 'empty'
    text=' '.join(cells);body=re.sub(r'\s','',text)
    if len(body)<30:return '너무 짧음'
    if len(re.findall(r'[가-힣]',body))<len(body)*.45:return '한글 아님'
    if sum(1 for ch in body if not ('가'<=ch<='힣' or ch.isalnum() or '一'<=ch<='鿿' or ch in PRINTED))>len(body)*.04:return '기호 덩어리'
    if sum(bool(re.fullmatch(r'[\d\s,.·\-~]+',c)) or bool(INDEX_ENTRY.search(c)) for c in cells)>len(cells)*.3:return '찾아보기·쪽번호'
    if sum(len(re.findall(r'[가-힣]',c))<=1 for c in cells)>len(cells)*.4:return '낱글자 칸'
    if max(len(r) for r in rows)>1 and sum(len(r)==1 for r in rows)>len(rows)*.4:return '칸이 흐트러짐'
    known=corpus_words()
    if known and any(len(w)>=7 and w not in known for w in re.findall(r'[가-힣]{2,}',text)):return '붙어 버린 긴 낱말'
    if strange_ratio(text)>.25 and len(re.findall(r'[가-힣]{2,}',text))>=8:return '없는 낱말'
    return 'keep'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--samples',type=int,default=6);args=parser.parse_args()
    start=time.time();random.seed(0)
    if not corpus_words():print('data/corpus-words.json 없음 - scripts/audit_glyphs.py 를 먼저 실행하세요',flush=True)
    with core.connect() as db:
        rows=db.execute("""SELECT x.id,x.kind,x.raw,x.display,b.title,b.category,p.pdf_page
          FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id
          WHERE b.category!='참고자료' AND x.version=? ORDER BY b.category,b.title,p.pdf_page,x.ordinal""",(VERSION,)).fetchall()
    books=defaultdict(lambda:{'passages':0,'excerpts':0,'damaged':0,'corrected':0,'citations':0,'tables':0,'tables_shown':0})
    reasons=Counter();kinds_seen=Counter();damaged_samples=defaultdict(list);dropped_samples=defaultdict(list);kept_samples=[]
    def keep_sample(bucket,item,seen):
        """One sample per bucket per book, so the report is not all one book."""
        if len(bucket)<args.samples and item['title'] not in {s['title'] for s in bucket}:bucket.append(item)
    for r in rows:
        b=books[r['title']];b['category']=r['category'];b['passages']+=1
        if r['kind'] not in {'body','table','note'}:continue
        if r['kind']=='table':
            cells=[[correct_display(c)[0] for c in row] for row in table_rows(r['raw'],r['display'])]
            b['tables']+=1
            verdict=table_verdict(cells);reasons[verdict]+=1
            sample={'title':r['title'],'page':r['pdf_page'],'rows':cells[:4]}
            if verdict=='keep':
                b['tables_shown']+=1;keep_sample(kept_samples,sample,None)
            else:keep_sample(dropped_samples[verdict],sample,None)
            continue
        for excerpt,text in chunks(r['raw'],r['display']):
            shown,marks=tidy_display(excerpt,restore_terms(text))
            b['citations']+=read_citations(shown)[1]
            shown,fixed=correct_display(shown)
            b['excerpts']+=1;b['corrected']+=fixed
            kinds=sorted(set(ocr_damage(shown)+(['noise'] if noise(shown) else [])))
            if kinds:
                b['damaged']+=1;kinds_seen.update(kinds)
                for kind in kinds:keep_sample(damaged_samples[kind],{'title':r['title'],'page':r['pdf_page'],'kinds':kinds,'text':shown[:240]},None)
    report={'generated':time.strftime('%Y-%m-%d %H:%M'),'version':VERSION,'seconds':round(time.time()-start),
            'books':[{'title':t,**v} for t,v in sorted(books.items(),key=lambda kv:(kv[1]['category'],kv[0]))],
            'table_verdicts':dict(reasons.most_common()),'damage_kinds':dict(kinds_seen.most_common()),
            'samples':{'damaged_excerpts':{k:v for k,v in damaged_samples.items()},'tables_shown':kept_samples,'tables_dropped':{k:v for k,v in dropped_samples.items()}}}
    (core.DATA/'reading-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    total=lambda k:sum(b[k] for b in report['books'])
    print(f"\n{'책':34s} {'발췌':>6s} {'깨짐':>6s} {'교정':>6s} {'자모':>6s} {'표':>5s} {'표표시':>6s}")
    for b in report['books']:
        print(f"{b['title'][:33]:34s} {b['excerpts']:6d} {b['damaged']:6d} {b['corrected']:6d} {b['citations']:6d} {b['tables']:5d} {b['tables_shown']:6d}")
    print(f"{'합계':34s} {total('excerpts'):6d} {total('damaged'):6d} {total('corrected'):6d} {total('citations'):6d} {total('tables'):5d} {total('tables_shown'):6d}")
    print('\n발췌 깨짐 유형:',dict(kinds_seen.most_common()))
    print('표 판정:',dict(reasons.most_common()))
    print(f"({report['seconds']}s) data/reading-audit.json")

if __name__=='__main__':main()
