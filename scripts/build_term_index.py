"""Build a term dictionary from the books' own back-of-book indexes (찾아보기).

Every index entry "term  page, page" is parsed, mapped to PDF pages through
the book's verified page offset, and kept only when the term actually occurs
on the referenced page (±1). Entries are merged across books by spelling
(spaces ignored), and for each book page the sentence that defines or
explains the term is pulled from the reading text, if the page has one. The
index terms the books write as one word are listed for display spacing.

Result: data/term-index.json. No AI is involved; the books decide what a
term is and where it is explained.
"""
import sys,re,json,time,argparse
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from text_pipeline import compact,restore_terms,tidy_display,glyph_gaps,term_starts,SENTENCE_INITIAL,VERSION
from passage_text import SENTENCE_END,noise,ocr_damage
from term_index import definition_score,DEFINITION

# Page-number groups such as "31", "54, 76", "296-298". The text between two
# groups is the next entry's term. Linear scan, no backtracking.
NUMBERS=re.compile(r"(?<![\d가-힣A-Za-z])\d{1,3}(?:\s*[-–~,，]\s*\d{1,3})*(?![\d가-힣A-Za-z])")
MIN_VALID_PER_PAGE=8

def page_digits(text):
    """Page numbers the OCR read with look-alike letters or a stray mark:
    Z73 -> 273, 47l -> 471, '151 -> 151. Only a run holding a real digit changes."""
    fix=str.maketrans('ZzlIOo','221100')
    return re.sub(r"(?<![A-Za-z가-힣\d])['‘’*]?([\dZzlIOo]{1,3})(?![A-Za-z가-힣\d])",lambda m:m.group(1).translate(fix) if re.search(r'\d',m.group(1)) else m.group(0),text)

def entries(text):
    """Yield (term, [pages]) from one index page."""
    text=page_digits(text);last=0
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

EXAMPLE=re.compile(r'^\(?\s*[\d\s]{1,6}[′]?\s*\)?\s*[가-하]\s*\.|^[가-하]\s*\.\s')
FRAGMENT=re.compile(r'(?:의|을|를|은|는|에|에서|으로|로|와|과|도|만|하여|하고|하며|되어|되며|이며|이고|으며|며|고|서|는데|지만|다|요)\s')
HEADING=re.compile(r'^\s*(?:\d+(?:\s*\.\s*\d+)*\s*\.|제\s*\d+\s*[장절편부])\s*\S')

def page_sentences(db,page_id,joined):
    """Reading sentences of a page's body text and side notes: footnote marks
    dropped, a numbered heading line cut off, example lines and sentences with
    visible OCR damage skipped."""
    result=[]
    for r in db.execute("SELECT kind,raw,display FROM passages WHERE page_id=? AND kind IN ('body','note') AND version=? ORDER BY ordinal",(page_id,VERSION)):
        raw,display=r['raw'],restore_terms(r['display'])
        lines=raw.split('\n',1)
        if len(lines)==2 and HEADING.match(lines[0]) and len(lines[0])<60 and not re.search(r'[다요][.!?。]',lines[0]):
            cut=len(compact(lines[0]));seen=0
            for i,ch in enumerate(display):
                if seen==cut:display=display[i:];break
                seen+=not ch.isspace()
            raw=lines[1]
        text,_=tidy_display(raw,display,joined)
        start=0;previous=None
        for m in list(re.finditer(SENTENCE_END,text))+[None]:
            end=m.end() if m else len(text)
            sentence=text[start:end].strip();start=end
            # Text after the last sentence end was cut by the page unless it ends in 다.
            cut=m is None and not re.search(r'[가-힣]다$',sentence)
            # A sentence opening with a particle or a connective ending lost its start ("하여 ‘단어구름’이라고 부른다.").
            cut=cut or bool(FRAGMENT.match(sentence))
            if cut or len(compact(sentence))<10 or len(sentence)>400 or noise(sentence) or EXAMPLE.match(sentence):
                previous=None;continue
            # A side note opens with its reference mark: "엉 ‘관형사절’은 ...".
            if r['kind']=='note' and re.match(r'[가-힣$]\s+[‘“]',sentence) and sentence[0] not in SENTENCE_INITIAL:sentence=sentence[1:].lstrip()
            # ...or with its note number: "16 이런 변이음을 조건 변이음이라고 한다".
            if r['kind']=='note':sentence=re.sub(r'^\d{1,3}\s*\)?\s+(?=[가-힣‘“(])','',sentence)
            result.append((r['kind'],sentence,previous));previous=sentence
    return result

def defining_quote(sentences,key,longer):
    """The page's sentence that best defines the term, and its score (see
    term_index.definition_score); no sentence unless it defines the term.
    Sentences that only talk about the term were right about one time in five
    when read through, so the card lists those pages as buttons instead. Side
    notes carry more OCR damage, so only a note that names the term outright
    (X라고 부른다) counts."""
    best=(0,None)
    for kind,sentence,previous in sentences:
        score=definition_score(sentence,key,longer)
        if score and kind=='note':score-=3
        if score>best[0]:
            # "이를 관형사절이라 한다." needs the sentence it points back to.
            if previous and re.match(r'(?:이를|이것을|이러한|이런|이와\s*같은|이처럼|이\s*같은|그것을|그러한)\s',sentence) and len(previous)+len(sentence)<320:sentence=previous+' '+sentence
            best=(score,sentence)
    return (best[1] if best[0]>=DEFINITION else None),best[0]

NAMED=re.compile(r'(?:\([^)]{0,40}\))?(?:이란|란(?!무엇|어떤)|이라고|라고|이라|라(?=도|는|를|하|한|부|불|일|칭|명|정|이|말)|으로도?(?=불리|불린|부르|부른|일컫|칭하|칭한|명명)|로도?(?=불리|불린|부르|부른|일컫|칭하|칭한|명명))')
SUBJECT=re.compile(r'(?:\([^)]{0,40}\))?(?:은|는|이란|란|이라는것은|라는것은|이라함은|라함은|의개념은|의정의는)')
def defined_keys(sentence,keys,longest):
    """Index terms a sentence may define: the term before 이란/라고 한다/로 불린
    다, or the term that opens it. definition_score decides."""
    c=re.sub(r'[\s‘’“”\'"「」『』〈〉<>《》·\-]','',sentence).lower();found=set()
    for m in NAMED.finditer(c):
        n=next((n for n in range(min(longest,m.start()),1,-1) if c[m.start()-n:m.start()] in keys),0)
        if n:found.add(c[m.start()-n:m.start()])
    for i in range(min(13,len(c))):
        n=next((n for n in range(min(longest,len(c)-i),1,-1) if c[i:i+n] in keys and SUBJECT.match(c,i+n)),0)
        if n:found.add(c[i:i+n])
    return found

def library_definitions(db,terms,cache,joined,longer):
    """Pages anywhere in the library that define an indexed term, best page per
    book. A book's index can point to where a term is used rather than where it
    is explained, and a term one book indexes is often defined in another. Read
    through, the plainest shapes (X란 ...이다, X라고 부른다, X는 ...을 말한다)
    held up away from the index pages; X는 ...이다 and two-syllable terms such as
    과정 or 방법 did not, so those count only on the pages the index names."""
    keys={k for k in terms if len(k)>=3 and re.search(r'[가-힣]',k)};longest=max(map(len,keys))
    pages=db.execute("SELECT p.id,p.pdf_page,b.title,b.category FROM pages p JOIN books b ON b.id=p.book_id WHERE b.category!='참고자료' ORDER BY b.title,p.pdf_page").fetchall()
    best={}
    for p in pages:
        if p['id'] not in cache:cache[p['id']]=page_sentences(db,p['id'],joined)
        for kind,sentence,previous in cache[p['id']]:
            for key in defined_keys(sentence,keys,longest):
                score=definition_score(sentence,key,longer(key))-3*(kind=='note')
                if score<9 or ocr_damage(sentence):continue
                if previous and re.match(r'(?:이를|이것을|이러한|이런|이와\s*같은|이처럼|이\s*같은|그것을|그러한)\s',sentence) and len(previous)+len(sentence)<320:sentence=previous+' '+sentence
                slot=(key,p['title'])
                if slot not in best or score>best[slot]['score']:best[slot]={'book':p['title'],'category':p['category'],'pdf_page':p['pdf_page'],'page_id':p['id'],'quote':sentence,'score':score,'indexed':False}
    return best

def spacing(db,keys):
    """Terms the books write as one word. For every word start in the reading
    text, each term found there counts as spaced when the source put a
    space inside it, and as joined when the source glyphs run together."""
    longest=max(map(len,keys),default=0);spaced=Counter();joined=Counter()
    for r in db.execute("SELECT x.raw,x.display FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id WHERE x.version=? AND x.kind IN ('body','note','table','exercise') AND b.category!='참고자료'",(VERSION,)):
        if compact(r['raw'])!=compact(r['display']):continue
        text,gaps,_=glyph_gaps(r['display']);raw_gaps=glyph_gaps(r['raw'])[1]
        # 동격 inside 동격 관형사절 counts for 동격 too.
        for p,term in term_starts(text,gaps,raw_gaps,keys,longest,every=True):
            inner=raw_gaps[p+1:p+len(term)]
            if any(re.search(r'[ \t]',g) for g in inner):spaced[term]+=1
            elif not any(inner):joined[term]+=1
    # 관형사절 is never spaced in the books; 문학교육 is spaced 8% of the time and 안은문장 78%.
    return sorted(k for k in keys if joined[k]>=3 and spaced[k]<=.03*(spaced[k]+joined[k]))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--category',default='');args=parser.parse_args()
    start=time.time();terms=defaultdict(lambda:{'label':Counter(),'sources':[]});report=[]
    # Some index pages' numbers are garbled in the text layer (우리말문법론: "감탄법 쟁6")
    # and no longer parse. An entry an earlier build validated stays while its
    # term is still on that page.
    path=core.DATA/'term-index.json';before=defaultdict(list)
    if path.exists():
        for key,e in json.loads(path.read_text(encoding='utf-8')).get('terms',{}).items():
            for s in e['sources']:
                if s.get('indexed',True):before[s['book']].append((key,e['label'],s['pdf_page']))
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
            carried=0
            for key,label,pdf in before.get(b['title'],[]):
                if (key,pdf) in seen or pdf not in ids or key not in keyed[pdf]:continue
                seen.add((key,pdf));carried+=1
                entry=terms[key];entry['label'][label]+=1
                entry['sources'].append({'book':b['title'],'category':b['category'],'pdf_page':pdf,'page_id':ids[pdf]})
            report.append({'book':b['title'],'index_pages':index_pages,'entries':kept+carried,'carried':carried})
            print(f"{b['title']}: index pages {index_pages}, validated entries {kept}, kept from the previous build {carried}",flush=True)
        # The first two syllables of a term count as well: 동격 of 동격절 and 동격 관형사절.
        hangul=[k for k in terms if re.fullmatch(r'[가-힣]{2,14}',k)]
        joined=spacing(db,set(hangul)|{k[:2] for k in hangul})
        print('joined spellings',len(joined),flush=True)
        joined_terms=(frozenset(joined),max(map(len,joined),default=0))
        # Defining sentences. A longer indexed term containing this one
        # (동격 관형사절 for 관형사절) is not a definition of this one.
        by_length=sorted(terms,key=len);n=0;cache={};longer_of={}
        def longer(key):
            if key not in longer_of:longer_of[key]=[k for k in by_length if len(k)>len(key) and key in k]
            return longer_of[key]
        for key,entry in terms.items():
            for s in entry['sources']:
                if s['page_id'] not in cache:cache[s['page_id']]=page_sentences(db,s['page_id'],joined_terms)
                s['quote'],s['score']=defining_quote(cache[s['page_id']],key,longer(key))
                if s['quote']:s['ocr']=ocr_damage(s['quote'])
                n+=1
            if n%2000<len(entry['sources']):print('quotes',n,flush=True)
        # Definitions away from the index pages, for books with no definition row yet.
        added=0
        for (key,book),s in library_definitions(db,terms,cache,joined_terms,longer).items():
            entry=terms[key]
            if any(x['book']==book and (x['score']>=DEFINITION or abs(x['pdf_page']-s['pdf_page'])<=1) for x in entry['sources']):continue
            entry['sources'].append(s);added+=1
        print('definitions found away from the index pages',added,flush=True)
        for entry in terms.values():
            for s in entry['sources']:
                s['printed_page']=db.execute('SELECT printed_page FROM pages WHERE id=?',(s['page_id'],)).fetchone()['printed_page']
    out={'generated':time.strftime('%Y-%m-%d %H:%M'),'text_version':VERSION,'books':report,'joined':joined,
         'terms':{key:{'label':e['label'].most_common(1)[0][0],'variants':sorted(e['label']),'sources':sorted(e['sources'],key=lambda s:(s['book'],s['pdf_page']))} for key,e in sorted(terms.items())}}
    (core.DATA/'term-index.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
    quoted=sum(1 for e in out['terms'].values() for s in e['sources'] if s['quote'])
    away=sum(1 for e in out['terms'].values() for s in e['sources'] if not s.get('indexed',True))
    damaged=sum(1 for e in out['terms'].values() for s in e['sources'] if s.get('ocr'))
    with_def=sum(1 for e in out['terms'].values() if any(s['quote'] for s in e['sources']))
    print(f"terms {len(out['terms'])} ({with_def} with a definition), index pages {sum(len(e['sources']) for e in out['terms'].values())-away}, defining sentences {quoted} ({away} away from the index pages, {damaged} with visible OCR damage) ({round(time.time()-start)}s)")

if __name__=='__main__':main()
