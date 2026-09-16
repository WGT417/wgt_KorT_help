"""Rank explanatory passages, not pages that merely contain query words."""
import math,re,itertools
from collections import Counter
from text_pipeline import compact,VERSION,restore_terms,correct_display
from passage_text import best_window,clean_blocks,noise,align,suspect_segments

def table_rows(raw,display):
    """Rows and cells of a small-print table or bullet list, spacing-corrected."""
    rows=[]
    for line in align(raw,display).split('\n'):
        cells=[re.sub(r'^[•·]\s*','',c).strip() for c in line.split('\t')]
        cells=[c for c in cells if c]
        if cells:rows.append(cells)
    return rows

def layout_source(db,page_id):
    rows=db.execute('SELECT ordinal,raw,display,kind FROM passages WHERE page_id=? ORDER BY ordinal',(page_id,)).fetchall()
    kept=[r for r in rows if r['kind']!='margin']
    # `blocks`: clean sentences only, used as evidence and for citation checks.
    # `reading`: everything on the page for the reader, doubtful sentences flagged,
    # known OCR word damage corrected for display only.
    blocks=[];reading=[]
    for i,r in enumerate(kept):
        if r['kind']=='body':
            blocks.extend({'text':text,'kind':'body','ordinal':r['ordinal']} for text in clean_blocks(r['raw'],r['display']))
            segments=[];fixed=0
            for seg in suspect_segments(r['display']):
                text,n=correct_display(seg['text']);fixed+=n
                segments.append({'text':text,'suspect':seg['suspect']})
            if segments:reading.append({'kind':'body','ordinal':r['ordinal'],'text':' '.join(x['text'] for x in segments),'segments':segments,'corrections':fixed})
        elif r['kind']=='table':
            cells=table_rows(r['raw'],r['display'])
            if sum(len(c) for row in cells for c in row)>=30:
                text=restore_terms(r['display'])
                blocks.append({'kind':'table','rows':cells,'text':text,'raw':r['raw'],'ordinal':r['ordinal']})
                fixed_rows=[[correct_display(c)[0] for c in row] for row in cells]
                reading.append({'kind':'table','rows':fixed_rows,'text':correct_display(text)[0],'raw':r['raw'],'ordinal':r['ordinal']})
        elif r['kind']=='note' and len(re.findall(r'[가-힣]',r['display']))>=40 and not noise(r['display']):
            blocks.append({'kind':'note','text':restore_terms(r['display'])})
            reading.append({'kind':'note','text':correct_display(restore_terms(r['display']))[0]})
        elif r['kind']=='exercise':reading.append({'kind':'exercise','text':correct_display(restore_terms(r['display']))[0]})
    # Short "[표 8-4] ..." lines are table captions; pair them with tables in page order.
    captions=[restore_terms(r['display']).strip('[]〔〕lI| ') for r in kept if r['kind'] in {'note','fragment'} and len(r['display'])<70 and re.match(r'\W*표\s*\d',r['display'].strip())]
    for group in (blocks,reading):
        tables=[b for b in group if b['kind']=='table']
        if captions and len(captions)==len(tables):
            for caption,block in zip(captions,tables):block['caption']=caption
    return '\n\n'.join(r['raw'] for r in kept),blocks,reading

# Ranking with the BGE-M3 index: cosine similarity x100 plus a share of the
# lexical score, so passages naming the concept stay ahead while passages that
# explain it in other words can still be found. Values were tuned with
# scripts/eval_retrieval.py on 137 concepts asked by name and by paraphrase.
LEXICAL_WEIGHT=.45
DENSE_CANDIDATES=60
# Similarity a passage found only by meaning needs; higher when no passage has
# the question's words, where unrelated questions otherwise still get answers.
DENSE_FLOOR=.55
DENSE_FLOOR_ALONE=.58
CORE_MARGIN=8
WIDE_MARGIN=15

def hybrid(db,query,category,book_id,lexical,admissible,penalty):
    """Lexical candidates with their semantic similarity, plus passages found
    only by meaning. Each row carries `match`: 'lexical' or 'semantic'."""
    import vector_search as vs
    q=vs.embed([query],max_tokens=256)[0]
    top=lexical[:40]
    similarity=vs.passage_similarity(q,{r['passage_id'] for r in top})
    # Tables and other windows the index does not cover are compared directly.
    missing=[r for r in top if r['passage_id'] not in similarity][:8]
    if missing:similarity.update({r['passage_id']:float(v@q) for r,v in zip(missing,vs.embed([r['display'] for r in missing]))})
    ranked={}
    for r in top:
        s=similarity.get(r['passage_id'],0.0)
        r.update(lexical_score=r['score'],semantic_score=s,match='lexical',score=s*100+r['score']*LEXICAL_WEIGHT)
        ranked[r['passage_id']]=r
    floor=DENSE_FLOOR if top else DENSE_FLOOR_ALONE
    hits=[h for h in vs.nearest(q,category,book_id,k=DENSE_CANDIDATES) if h['semantic']>=floor and h['passage_id'] not in ranked]
    if hits:
        rows={r['passage_id']:dict(r) for r in db.execute('''SELECT x.id AS passage_id,x.page_id,x.ordinal,x.kind,x.raw,x.display,
          p.book_id,p.pdf_page,p.printed_page,p.number_status,p.method,p.quality,b.title,b.category
          FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id WHERE x.id IN (%s)'''%','.join('?'*len(hits)),[h['passage_id'] for h in hits])}
        for h in hits:
            r=rows.get(h['passage_id'])
            # Skip chunks of passages rebuilt after the index was made.
            if r is None or h['passage_id'] in ranked or h['excerpt'] not in r['raw']:continue
            r['raw'],r['display']=h['excerpt'],h['text'];c=compact(h['text']);r['compact']=c
            if not admissible(r,c):continue
            r.update(lexical_score=0.0,semantic_score=h['semantic'],match='semantic',score=h['semantic']*100-penalty(r,c))
            ranked[h['passage_id']]=r
    return sorted(ranked.values(),key=lambda r:(-r['score'],r['page_id'],r['ordinal']))

def search(db,query,category,book_id,limit,groups):
    if not groups or limit<=0:return []
    where=["b.category!='참고자료'",'x.version=?'];args=[VERSION]
    if category!='전체':where.append('b.category=?');args.append(category)
    if book_id:where.append('b.id=?');args.append(book_id)
    rows=[dict(r) for r in db.execute('''SELECT x.id AS passage_id,x.page_id,x.ordinal,x.kind,x.raw,x.display,x.compact,
      p.book_id,p.pdf_page,p.printed_page,p.number_status,p.method,p.quality,b.title,b.category
      FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id WHERE '''+' AND '.join(where),args)]
    if not rows:return []
    # Keep rare explicit multiword concepts together (e.g. 심미적 독서).
    nq=compact(query);focus=[]
    for a,b in zip(groups,groups[1:]):
        phrase=a[0]+b[0]
        n=sum(phrase in r['compact'] for r in rows)
        if len(a[0])>=2 and phrase in nq and 0<n<max(3,len(rows)*.02):focus.append((n,phrase))
    if focus:groups=[(min(focus)[1],)]
    exact_groups=groups
    groups=[tuple(dict.fromkeys((*g,*(a[:-1] for a in g if a.endswith('적') and len(a)>2)))) for g in groups]
    weights=[math.log(2+len(rows)/(1+sum(any(t in r['compact'] for t in g) for r in rows))) for g in groups]
    catalog_request=bool(re.search(r'교과서|교육과정|출판사|목록|서지|참고문헌',query))
    exercise_request=bool(re.search(r'학습\s*활동|연습\s*문제|탐구\s*활동|과제|문항',query))
    # Small-print tables that lay out the concept's steps or types.
    tables={}
    for r in rows:
        if r['kind']=='table' and all(any(t in r['compact'] for t in g) for g in groups):tables.setdefault(r['page_id'],[]).append(r['raw'])
    families=[('읽기','독서'),('쓰기','작문'),('말하기','화법'),('듣기','화법')]
    domain=next((f for f in families if any(t in query for t in f)),None)
    requested_domains=[f for f in families if any(t in query for t in f)]
    phrases=['(?:의)?'.join(map(re.escape,parts)) for parts in itertools.product(*groups)] if len(groups)<=3 else []
    scored=[]
    for r in rows:
        c=r['compact'];kind=r['kind']
        # Specialized books in another communication domain are supplemental,
        # not primary evidence for a single-domain question.
        if domain and len(requested_domains)==1:
            other_titles=[t for f in families if f!=domain for t in f]
            if any(r['title'].startswith(t) for t in other_titles):continue
        if kind in {'margin','fragment','index'}:continue
        if kind=='exercise' and not exercise_request:continue
        if kind=='table' and '표' not in query:continue
        bullets=len(re.findall(r'[·•]',r['raw']))
        if bullets>=8 and len(re.findall(r'다[.!?。]',r['raw']))<bullets/2:continue
        if kind=='catalog' and not catalog_request:continue
        if not all(any(t in c for t in g) for g in groups):continue
        # Reject a catalog even when its publisher list straddles paragraph cuts.
        if not catalog_request and len(re.findall(r'교과서|출판사|천재교육|비상|지학사|신사고',c))>=3:continue
        window=best_window(r['raw'],r['display'],groups)
        if not window:continue
        r['raw'],r['display']=window;c=compact(r['display']);r['compact']=c
        explanatory=len(re.findall(r'한다|된다|이다|있다|없다|뜻하|의미하|가리키|말한다|이라|해야|통해|때문|과정|전략|구분|나뉘|예를',c))
        if len(c)<65 or not re.search(r'[가-힣]다(?=[.!?。]|$|\s|[（(])',r['display']):continue
        score=sum(w*(1+math.log1p(min(6,sum(c.count(t) for t in g)))) for w,g in zip(weights,groups))
        score/= .8+.2*len(c)/400
        score+=min(8,explanatory)*.7
        if not all(any(t in c for t in g) for g in exact_groups):score*=.6
        if len(groups)>1 and any(re.search(p+r'(?:은|는|이란|란)',c[:220]) for p in phrases):score+=18
        if '과정' in query and re.search(r'단계|구분|나누|나뉘|과정은',c):score+=12
        if '과정' in query:score+=min(5,len(re.findall(r'[가-힣]{2,8}하기',c)))*4
        if re.search(r'종류|분류|체계',query) and re.search(r'나누|나뉘|분류|대별|구분',c):score+=10
        # A topic sentence defining the requested concept beats a mention in
        # a discussion of a different concept.
        for g in groups:
            if any(re.search(r'(?<![가-힣])'+r'\s*'.join(map(re.escape,t))+r'\s*(?:은|는|란|이란|의\s*(?:종류|분류|개념))',r['display'][:180]) for t in g):score+=8
        if re.search(r'가리킨다|일컫는다|뜻한다|의미한다|규정될수있다|정의할수있다',c):score+=6
        # "X(reflexive pronoun)로 불리는", "X라고 한다": the passage names the concept.
        for g in groups:
            if any(re.search(re.escape(t)+r'(?:\([^)]{0,40}\))?(?:으로|로|이라고|라고|이라|라)(?:도)?(?:불리|부르|일컫|한다|칭한)',c[:400]) for t in g):score+=8;break
        if not catalog_request and len(re.findall(r'성취기준|교육과정|교과서|단원',c))>=2:continue
        if not catalog_request and re.search(r'교과서|성취기준|이책지은이|용어를쓰|이책에서는',c):score*=.65
        for a,b in zip(groups,groups[1:]):
            if any(re.search(re.escape(x)+r'(?:의|인|으로|적인|적으로)?'+re.escape(y),c) for x in a for y in b):score+=5
        if domain:
            in_domain=sum(c.count(t) for t in domain)
            other=max((sum(c.count(t) for t in f) for f in families if f!=domain),default=0)
            if other>in_domain*1.5:score*=.35
            if any(t in r['title'] for t in domain):score*=1.25
        if kind=='table':score*=.5
        if kind=='note':score*=.75
        if r['page_id'] in tables:score+=6
        # Pages whose letters are unreliable even after OCR repair stay visible
        # but do not outrank clean explanations.
        if r['quality']=='review':score*=.5
        if '국어사' in r['title'] and not re.search(r'중세|고대|근대|역사|국어사|변천|옛',query):score*=.6
        # Surface noisy OCR as a limitation rather than promoting symbol soup.
        noisy=len(re.findall(r'[가-힣][A-Za-z%&@][가-힣]|[A-Za-z][가-힣][A-Za-z]',c))
        if noisy>max(4,len(c)*.012):score*=.35
        r['score']=score;scored.append(r)
    scored.sort(key=lambda r:(-r['score'],r['page_id'],r['ordinal']))
    def admissible(r,c):
        """The lexical loop's filters that do not depend on query words."""
        if domain and len(requested_domains)==1 and any(r['title'].startswith(t) for f in families if f!=domain for t in f):return False
        bullets=len(re.findall(r'[·•]',r['raw']))
        if bullets>=8 and len(re.findall(r'다[.!?。]',r['raw']))<bullets/2:return False
        if not catalog_request and (len(re.findall(r'교과서|출판사|천재교육|비상|지학사|신사고',c))>=3 or len(re.findall(r'성취기준|교육과정|교과서|단원',c))>=2):return False
        return True
    def penalty(r,c):
        """Points off a passage found by meaning, mirroring the lexical demotions."""
        points=0
        if not catalog_request and re.search(r'교과서|성취기준|이책지은이|용어를쓰|이책에서는',c):points+=4
        if domain and max((sum(c.count(t) for t in f) for f in families if f!=domain),default=0)>sum(c.count(t) for t in domain)*1.5:points+=8
        if r['kind']=='note':points+=2
        if r['quality']=='review':points+=8
        if '국어사' in r['title'] and not re.search(r'중세|고대|근대|역사|국어사|변천|옛',query):points+=4
        return points
    import vector_search
    semantic=dense=vector_search.ready()
    if dense:scored=hybrid(db,query,category,book_id,scored,admissible,penalty)
    elif scored:
        from local_semantics import ready,rerank
        semantic=ready()
        if semantic:scored=rerank(query,scored[:40])
    if not scored:return []
    # Lexical candidates contain all query terms inside one clean excerpt, so the
    # floor only drops clearly weaker matches. Semantic scores sit within a narrow
    # band, so a tighter floor would hide most passages that mention the concept.
    best=scored[0]['score']
    floor=best-(WIDE_MARGIN if dense else 25) if semantic else best*.45
    lexical_found=any(r.get('match','lexical')=='lexical' for r in scored)
    candidates=[];seen=set()
    for r in scored:
        if r['score']<floor or r['page_id'] in seen:continue
        # A passage without the question's words joins exact matches only when it is nearly as strong as the best.
        if r.get('match')=='semantic' and lexical_found and r['score']<best-CORE_MARGIN:continue
        seen.add(r['page_id']);candidates.append(r)
    # A concept is often developed in another book at a lower lexical score:
    # secure each book's best passage first, then fill with the rest by score.
    first={}
    for r in candidates:first.setdefault(r['book_id'],r)
    picked=list(first.values())[:limit];chosen={r['page_id'] for r in picked}
    for r in candidates:
        if len(picked)>=limit:break
        if r['page_id'] not in chosen:picked.append(r);chosen.add(r['page_id'])
    picked.sort(key=lambda r:-r['score'])
    selected=[]
    for r in picked:
        text,blocks,reading=layout_source(db,r['page_id'])
        result={k:r[k] for k in ['book_id','pdf_page','printed_page','number_status','method','quality','title','category']}
        # Tables that name the concept, or that directly follow the matched paragraph.
        structured=[{'rows':b['rows'],'text':b['text'],'caption':b.get('caption','')} for b in reading if b['kind']=='table' and (b['raw'] in tables.get(r['page_id'],[]) or r['ordinal']<b['ordinal']<=r['ordinal']+3 or any(t in compact(b.get('caption','')) for g in groups for t in g))]
        shown,fixed=correct_display(restore_terms(r['display']))
        result.update(id=r['page_id'],source_id=f"S{r['page_id']}",text=text,evidence_text='\n\n'.join(b['text'] for b in blocks if b['kind'] in {'body','table','note'}),excerpt=r['raw'],display_excerpt=shown,corrections=fixed,passage_id=r['passage_id'],text_version=VERSION,score=round(r['score'],3),matched=[g[0] for g in groups],kind=r['kind'],structured=structured,match=r.get('match','lexical'),semantic_score=round(r['semantic_score'],4) if 'semantic_score' in r else None)
        selected.append(result)
    return selected
