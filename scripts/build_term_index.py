"""Build a term dictionary from the books' own back-of-book indexes (찾아보기).

Every index entry "term  page, page" is parsed, mapped to PDF pages through
the book's verified page offset, and kept only when the term actually occurs
on the referenced page (±1). Entries are merged across books by spelling
(spaces ignored), and for each book page a defining sentence containing the
term is pulled from the clean reading text (source glyphs unchanged).

Result: data/term-index.json. No AI is involved; the books decide what a
term is and where it is explained.
"""
import sys,re,json,time,argparse
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from text_pipeline import compact,restore_terms,VERSION
from passage_text import windows

# Page-number groups such as "31", "54, 76", "296-298". The text between two
# groups is the next entry's term. Linear scan, no backtracking.
NUMBERS=re.compile(r"(?<![\d가-힣A-Za-z])\d{1,3}(?:\s*[-–~,，]\s*\d{1,3})*(?![\d가-힣A-Za-z])")
MIN_VALID_PER_PAGE=8

def entries(text):
    """Yield (term, [pages]) from one index page."""
    last=0
    for m in NUMBERS.finditer(text):
        raw=text[last:m.start()];last=m.end()
        # The term is the last line-ish chunk before the numbers.
        raw=re.split(r'[\n]',raw)[-1]
        term=clean_term(re.sub(r'[.:\"…ㅡ_~]+',' ',raw))
        nums=[int(n) for n in re.findall(r'\d{1,3}',m.group())]
        if term and nums:yield term,nums

def clean_term(term):
    term=term.strip(' .:’‘"\'-ㅡ_~·')
    term=re.sub(r'\s+',' ',term)
    term=re.sub(r'^[\-\s]+|[\-\s]+$','',term)
    return term

def key_of(term):
    return re.sub(r'[\s\-‘’\'"·]','',term).lower()

def defining_quote(db,page_id,term):
    """Shortest clean window naming the term, preferring definitional wording."""
    k=key_of(term);best=None
    for r in db.execute("SELECT raw,display FROM passages WHERE page_id=? AND kind='body' AND version=? ORDER BY ordinal",(page_id,VERSION)):
        for _,text in windows(r['raw'],r['display']):
            c=key_of(text)
            if k not in c:continue
            first=re.split(r'[.!?。]\s',text,maxsplit=1)[0]
            named=k in key_of(first)
            defines=bool(re.search(r'(?:이란|란|라고|이라고|이라|라)\s*(?:한다|불리|부르|일컫|하는|함|말한다)|(?:은|는)\s*[^.]{0,60}(?:을|를)\s*(?:말한다|가리킨다|이른다|뜻한다)|(?:이다|것이다)[.]',text))
            score=named*4+defines*3-min(len(text),600)/300
            if best is None or score>best[0]:best=(score,text)
    return restore_terms(best[1]) if best else None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--category',default='');args=parser.parse_args()
    start=time.time();terms=defaultdict(lambda:{'label':Counter(),'sources':[]});report=[]
    with core.connect() as db:
        books=db.execute("SELECT id,title,category,pages FROM books WHERE category!='참고자료'"+(" AND category=?" if args.category else '')+" ORDER BY category,title",(args.category,) if args.category else ()).fetchall()
        for b in books:
            rows=db.execute("SELECT id,pdf_page,printed_page,text FROM pages WHERE book_id=? ORDER BY pdf_page",(b['id'],)).fetchall()
            texts={r['pdf_page']:r['text'] for r in rows};ids={r['pdf_page']:r['id'] for r in rows}
            keyed={p:key_of(t) for p,t in texts.items()}
            offs=Counter(r['pdf_page']-r['printed_page'] for r in rows if r['printed_page'])
            if offs:off=offs.most_common(1)[0][0]
            else:
                # No verified printed numbers: pick the PDF-minus-printed offset under which
                # the most index entries land on a page that actually contains the term.
                candidates=[(term,n) for r in rows if r['pdf_page']>=b['pages']*0.6 for term,nums in entries(r['text']) for n in nums[:2] if 2<=len(key_of(term))<=12 and re.search(r'[가-힣]',term)]
                best=max(range(0,41),key=lambda o:sum(key_of(t) in keyed.get(n+o,'') for t,n in candidates[:1500]),default=None)
                score=sum(key_of(t) in keyed.get(n+best,'') for t,n in candidates[:1500]) if best is not None else 0
                if not candidates or score<MIN_VALID_PER_PAGE*2:report.append({'book':b['title'],'note':'쪽수 대응 없음'});print(f"{b['title']}: 쪽수 대응을 찾지 못함",flush=True);continue
                off=best;print(f"{b['title']}: 쪽수 대응 추정 +{off} (일치 {score})",flush=True)
            index_pages=0;kept=0;seen=set()
            for r in rows:
                if r['pdf_page']<b['pages']*0.6:continue
                t=r['text']
                if len(re.findall(r'\(?(?:19|20)\d\d\)?',t))>=6:continue   # bibliography
                found=[]
                for term,nums in entries(t):
                    if len(key_of(term))<2 or len(term)>24 or not re.search(r'[가-힣]',term):continue
                    if re.fullmatch(r'[가-힣]',key_of(term)):continue
                    for n in nums[:4]:
                        pdf=n+off
                        if pdf not in texts:continue
                        hit=next((pdf+d for d in (0,1,-1) if key_of(term) in keyed.get(pdf+d,'')),None)
                        if hit:found.append((term,hit))
                if len(found)<MIN_VALID_PER_PAGE:continue
                index_pages+=1
                for term,pdf in found:
                    if (key_of(term),pdf) in seen:continue
                    seen.add((key_of(term),pdf));kept+=1
                    entry=terms[key_of(term)];entry['label'][term]+=1
                    entry['sources'].append({'book':b['title'],'category':b['category'],'pdf_page':pdf,'page_id':ids[pdf]})
            report.append({'book':b['title'],'index_pages':index_pages,'entries':kept})
            print(f"{b['title']}: index pages {index_pages}, validated entries {kept}",flush=True)
        # Defining sentences.
        n=0
        for key,entry in terms.items():
            label=entry['label'].most_common(1)[0][0]
            for s in entry['sources']:
                s['quote']=defining_quote(db,s['page_id'],label)
                row=db.execute('SELECT printed_page FROM pages WHERE id=?',(s['page_id'],)).fetchone()
                s['printed_page']=row['printed_page'];n+=1
            if n%2000<len(entry['sources']):print('quotes',n,flush=True)
    out={'generated':time.strftime('%Y-%m-%d %H:%M'),'text_version':VERSION,'books':report,
         'terms':{key:{'label':e['label'].most_common(1)[0][0],'variants':sorted(e['label']),'sources':sorted(e['sources'],key=lambda s:(s['book'],s['pdf_page']))} for key,e in sorted(terms.items())}}
    (core.DATA/'term-index.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
    quoted=sum(1 for e in out['terms'].values() for s in e['sources'] if s['quote'])
    print(f"terms {len(out['terms'])}, sources {sum(len(e['sources']) for e in out['terms'].values())}, with defining sentence {quoted} ({round(time.time()-start)}s)")

if __name__=='__main__':main()
