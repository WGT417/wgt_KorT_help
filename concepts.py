"""Pre-written concept entries shown without calling any AI at query time.

Entries live in concepts/<area>.json and are authored or reviewed in advance.
Each entry carries the book pages it rests on; the app resolves those pages
to the library so the reader can open the source text. Matching is term
based and deliberately narrow: a concept is shown only when the question
names it, never guessed.
"""
import json,re,threading
from pathlib import Path
from core import ROOT,connect

CONCEPT_DIR=ROOT/'concepts'
_lock=threading.Lock()
_cache={'stamp':None,'entries':[]}
# Terms too generic to identify a concept on their own.
TOO_COMMON={'문법','문학','독서','작문','화법','읽기','쓰기','말하기','듣기','시','소설','문장','단어','의미','표현','과정','전략','교육','수업','개념','학습','활동','유형','기능','모형','이론','텍스트','독자','필자','작품','화자','언어','국어','교수'}

def compact(text):return re.sub(r'\s+','',text or '').lower()

def section_items(items):
    """Flatten the nested items of a document-style section into plain strings."""
    out=[]
    for item in items or []:
        if isinstance(item,str):out.append(item);continue
        out+=[item.get('label',''),item.get('text','')]+list(item.get('examples',[]))+section_items(item.get('sub',[]))
    return out

def entry_text(entry):
    """All prose of an entry: summary, document sections, and legacy paragraphs."""
    parts=[entry.get('summary','')]+list(entry.get('explanation',[]))
    for s in entry.get('sections',[]):parts+=[s.get('heading',''),s.get('intro','')]+section_items(s.get('items',[]))
    return ' '.join(p for p in parts if p)

def _load():
    files=sorted(CONCEPT_DIR.glob('*.json')) if CONCEPT_DIR.exists() else []
    stamp=tuple((f.name,f.stat().st_mtime_ns) for f in files)
    with _lock:
        if _cache['stamp']==stamp:return _cache['entries']
        entries=[]
        for f in files:
            data=json.loads(f.read_text(encoding='utf-8'))
            for entry in data.get('concepts',[]):
                entry=dict(entry);entry['area']=data.get('area',f.stem)
                terms=[entry.get('label','')]+list(entry.get('aliases',[]))
                entry['_terms']=[t for t in dict.fromkeys(compact(t) for t in terms) if len(t)>=2 and t not in {compact(x) for x in TOO_COMMON}]
                entries.append(entry)
        _cache.update(stamp=stamp,entries=entries)
        return entries

def all_concepts():return _load()

# 이 and 가 are not in retrieval.PARTICLE_RE, and must not be: stripping them
# would eat the last syllable of 소설가, 미닫이, 해돋이, 어린이 — words the books
# use as examples. But a question does end in them ("조음점이 뭐야", "연어가 뭐죠"),
# so the stripped form is offered as one more candidate rather than replacing the
# word. A candidate matters only if it equals a concept's name, and 미닫/해돋/어린
# are nobody's name.
SUBJECT=re.compile(r'(?<=[가-힣][가-힣])[이가]$')
def query_terms(query):
    """Whole words of the question plus adjacent pairs and triples, so '재귀 대명사'
    and '재귀대명사' both yield 재귀대명사. A particle is stripped only from the
    last word of a phrase: '대등적으로 이어진 문장과' must still yield
    대등적으로이어진문장, where 으로 is part of the name, not a particle."""
    from retrieval import terms,strip_particle
    raw=[compact(t) for t in re.findall(r'[가-힣A-Za-z0-9]+',query.lower())]
    out=[]
    for n in (3,2,1):
        for i in range(len(raw)-n+1):
            words=raw[i:i+n];head=''.join(words[:-1])
            out+=[head+words[-1],head+strip_particle(words[-1]),head+SUBJECT.sub('',words[-1])]
    words=[compact(t) for t in terms(query)]
    out+=[a+b+c for a,b,c in zip(words,words[1:],words[2:])]+[a+b for a,b in zip(words,words[1:])]+words
    return [t for t in dict.fromkeys(out) if len(t)>=2]

def match_concepts(query,category='전체',limit=3):
    """Exact: a term of the question IS one of the entry's names. Related: an
    entry name is only part of a longer term (대명사 inside 재귀대명사); such an
    entry is offered as background, never as the answer, and only if its own
    text mentions the name."""
    q=compact(query);qterms=query_terms(query);hits=[]
    for entry in _load():
        if category!='전체' and entry['area']!=category:continue
        names=entry['_terms']
        exact=[t for t in names if t in qterms or t==q]
        if exact:hits.append(('exact',max(len(t) for t in exact),entry));continue
        partial=[t for t in names if any(t in qt and t!=qt for qt in qterms) or (t in q and not qterms)]
        if partial:
            body=compact(entry_text(entry))
            # A concept whose text never uses the matched word cannot explain it.
            if any(t in body for t in partial):hits.append(('related',max(len(t) for t in partial),entry))
    # '재귀 대명사' names one concept; the word 대명사 inside it must not also
    # promote the broader 대명사 entry to an answer.
    exact_terms=[t for kind,_,e in hits if kind=='exact' for t in e['_terms'] if t in qterms or t==q]
    longest=max(exact_terms,key=len,default='')
    hits=[('related' if kind=='exact' and all(t!=longest and t in longest for t in e['_terms'] if t in qterms or t==q) and longest else kind,n,e) for kind,n,e in hits]
    hits.sort(key=lambda h:(h[0]!='exact',-h[1],h[2]['id']))
    seen=set();result=[]
    for kind,_,entry in hits:
        if entry['id'] in seen:continue
        seen.add(entry['id']);item=public(entry);item['match']=kind
        matched=[t for t in entry['_terms'] if t in qterms or t==q] or [t for t in entry['_terms'] if t in q]
        item['matched_term']=max(matched,key=len) if matched else ''
        # '재귀 대명사(재귀칭)' is named by the question 재귀대명사; 안은문장 is not named by 관형절.
        item['by_label']=bool(item['matched_term']) and item['matched_term'] in compact(entry.get('label',''))
        result.append(item)
        if len(result)>=limit:break
    return result

def public(entry):
    out={k:v for k,v in entry.items() if not k.startswith('_')}
    out['sources']=resolve_sources(entry.get('sources',[]))
    return out

def resolve_sources(sources):
    """Attach library page ids and printed page numbers to authored book references."""
    if not sources:return []
    resolved=[]
    with connect() as db:
        for s in sources:
            row=None
            if s.get('book') and s.get('pdf_page'):
                row=db.execute('SELECT p.id,p.printed_page,p.number_status,p.quality,b.title FROM pages p JOIN books b ON b.id=p.book_id WHERE b.title=? AND p.pdf_page=?',(s['book'],int(s['pdf_page']))).fetchone()
            item=dict(s)
            if row:item.update(id=row['id'],title=row['title'],printed_page=row['printed_page'],number_status=row['number_status'],quality=row['quality'])
            else:item.update(id=None,title=s.get('book'))
            resolved.append(item)
    return resolved
