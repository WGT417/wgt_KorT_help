"""Terms from the books' own back-of-book indexes, shown without AI.

data/term-index.json is produced by scripts/build_term_index.py. A question
that names an indexed term gets a card listing, for every book that indexes
it, the page and the defining sentence from that page.
"""
import json,re,threading
from core import DATA,connect
from concepts import query_terms,compact

_lock=threading.Lock()
_cache={'stamp':None,'terms':{}}
PATH=DATA/'term-index.json'

def key_of(term):return re.sub(r'[\s\-‘’\'"·]','',term).lower()

def _load():
    stamp=PATH.stat().st_mtime_ns if PATH.exists() else None
    with _lock:
        if _cache['stamp']==stamp:return _cache['terms']
        terms=json.loads(PATH.read_text(encoding='utf-8')).get('terms',{}) if PATH.exists() else {}
        _cache.update(stamp=stamp,terms=terms);return terms

def match_terms(query,category='전체',limit=3):
    """Exact term matches only: a word of the question (particles stripped),
    or two or three adjacent words joined, must equal an indexed term."""
    terms=_load()
    if not terms:return []
    from retrieval import ALIASES
    wanted=[key_of(t) for t in query_terms(query)]+[key_of(query)]
    hits=[]
    for k in dict.fromkeys(wanted):
        # 관형절 and 관형사절 are one card: the school-grammar name and the books' name.
        group=next((g for g in ALIASES if k in g),(k,))
        found=[(g,terms[g]) for g in group if g in terms]
        if not found:continue
        sources=[dict(s,term=e['label']) for g,e in found for s in e['sources'] if category=='전체' or s['category']==category]
        if not sources:continue
        entry={'label':' · '.join(dict.fromkeys(e['label'] for g,e in found)),'variants':sorted({v for g,e in found for v in e['variants']})}
        hits.append((len(k),len({s['book'] for s in sources}),k,entry,sources))
    hits.sort(key=lambda h:(-h[0],-h[1]))
    # '음절의 끝소리 규칙' answers the question; its parts 음절 and 규칙 do not.
    keys=[h[2] for h in hits]
    hits=[h for h in hits if not any(h[2]!=k and h[2] in k for k in keys)]
    result=[]
    with connect() as db:
        for _,_,k,entry,sources in hits[:limit]:
            resolved=[]
            for s in sources:
                row=db.execute('SELECT id,printed_page,number_status,quality FROM pages WHERE id=?',(s['page_id'],)).fetchone()
                item={'book':s['book'],'title':s['book'],'category':s['category'],'pdf_page':s['pdf_page'],'quote':s.get('quote'),'term':s.get('term',entry['label']),'id':row['id'] if row else None,'printed_page':row['printed_page'] if row else None,'quality':row['quality'] if row else None}
                resolved.append(item)
            result.append({'key':k,'label':entry['label'],'variants':entry['variants'],'sources':resolved})
    return result
