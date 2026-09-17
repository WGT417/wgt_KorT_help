"""Terms from the books' own back-of-book indexes, shown without AI.

data/term-index.json is produced by scripts/build_term_index.py. A question
that names an indexed term gets a card listing the sentences that define it,
from the pages the books' indexes name and, where a book's index pages do not
define it, from elsewhere in that book or another, then the remaining index
pages as buttons.
"""
import json,re,threading
from core import DATA,connect
from concepts import query_terms,compact
from text_pipeline import correct_display

_lock=threading.Lock()
_cache={'stamp':None,'terms':{}}
PATH=DATA/'term-index.json'

def key_of(term):return re.sub(r'[\s\-‘’\'"·]','',term).lower()

# 일컫는다 is often read 일걷는다.
DEFINING_VERB=r'(?:말한다|가리킨다|뜻한다|의미한다|이른다|일[컫걷]는다|지칭한다|(?:으로|로|라고|이라고)정의된다|정의한다|정의할수있다|규정된다|규정할수있다)'
# What a "X란 ..." sentence must end with to define X rather than just talk about it.
DEFINING_END=r'(?:이다|말한다|뜻한다|의미한다|가리킨다|일[컫걷]는다|이른다|지칭한다|칭한다|정의된다|정의한다|규정된다|(?:라|이라|볼|말할|정의할)수있다|(?:뜻하|의미하|가리키|말하|이르)기도한다)[.。]?$'
# "X라고 한다/부른다" names X; "X라고 부르는 현상" only mentions the name.
NAMING=r'(?:이라고|라고|이라|라)(?:도|는|를)?(?:한다(?!면|고)|하며|하고|하는데|하였다|했다|하기도(?!하지만)|부른다|부르며|부르고|부르는데|부르기도(?!하지만)|부르고자|불러(?!야)|불린다|불리며|불리고|불리기도(?!하지만)|일[컫걷]는다|일컬으며|일[컫걷]고|칭한다|칭하며|칭하고|명명한다|명명하였다|명명했다|정의한다|정의하며|이른다|말한다)'
# Words that may open a defining sentence before the term; anything else
# ("가장 긴 드라마는", "단어 형성 규칙은") makes the term part of a larger phrase.
OPENER=r'(?:\(?\d{1,3}\)|\d+(?:\.\d+)*\.?|[가-하]\.|[①-⑳])?(?:.{0,30}(?:첫|두|세|네|다섯|여섯)번째|즉|곧|따라서|그러므로|그래서|일반적으로|흔히|대체로|보통|먼저|우선|첫째|둘째|셋째|넷째|다섯째|한편|또한|또|반면|반면에|이에비해|이와달리|여기서|여기에서|이때|그런데|그러나|하지만|결국|요컨대|다시말해|말하자면|원래|본래|전통적으로|적용\d)?[，,]?'
# Predicates that close a statement about X, not a definition of it.
NOT_DEFINING_END=r'(?:일반적이다|중요한부분이다|부분이다|것들이다|일이다|다른것이다|때문이다|사실이다|물론이다|마찬가지이다|셈이다|뿐이다|탓이다|까닭이다|있는것이다|없는것이다|야하는것이다|[을할될볼]것이다)[.。]?$'
# The word before a named term must end in a particle, an ending or an
# adverb: "이것을 음소 분석이라고 부른다" names 음소 분석, not 분석.
NAMED_AFTER=set('을를은는이가에로서고며면게도만과와께야지니여해어아듯히리')
DEFINITION=7
def definition_score(sentence,key,longer=()):
    """How plainly `sentence` defines the term `key` (compact spelling):
    10 names it (X란 ...이다, ...을 X라고 부른다), 9 X는 ...을 말한다,
    8 X로 불린다, 7 X는 ...이다, 5 a sentence about X, 2 X inside a
    longer indexed term (동격 관형사절이란 defines 동격 관형사절), 1 a
    mention, 0 absent. The term must start a word: 에서 in 과정에서는 is
    not the particle's entry, and X란 or X는 opening a sentence counts only
    after a plain connective (일반적으로, 즉, 첫째) or the heading repeating X."""
    chars=[];at=[]
    for i,ch in enumerate(sentence):
        if not re.match(r'[\s‘’“”\'"「」『』〈〉<>《》·\-]',ch):chars.append(ch.lower());at.append(i)
    c=''.join(chars)
    # "... 숨겨진 의미이다(오주영, 1997)." ends where the citation starts.
    end=re.sub(r'(?:\([^()]{0,60}\)[.。]?)+$','',c)
    spans=[(m.start(),m.start()+len(l)) for l in longer for m in re.finditer(re.escape(l),c)]
    best=0
    for m in re.finditer(re.escape(key),c):
        i,j=m.span()
        if i and re.match(r'[가-힣A-Za-z0-9]',sentence[at[i]-1]):best=max(best,1);continue
        if any(a<=i and j<=b for a,b in spans):best=max(best,2);continue
        head=c[:i];tail=re.sub(r'^\([^)]{0,40}\)','',c[j:])
        before=sentence[:at[i]].rstrip()
        modified=bool(before) and '가'<=before[-1]<='힣' and before[-1] not in NAMED_AFTER or before.endswith(')') and re.search(r'[가-힣]\s*\([^)]*\)$',before)
        opens=bool(re.fullmatch(OPENER,head) or re.fullmatch(OPENER+re.escape(key)+r'(?:\([^)]{0,40}\))?',head))
        if modified and re.match(r'(?:\([^)]{0,40}\))?(?:이란|란|이라|라|으로|로)',tail):score=1
        # "... 이때 발생하는 것이 ‘대화 함축’이다."
        elif head.endswith('것이') and re.fullmatch(r'(?:\([^)]{0,40}\))?이?다[.。]?',re.sub(r'(?:\([^()]{0,60}\)[.。]?)+$','',tail)):score=9
        elif re.match(r'(?:이란|란)(?!무엇|어떤|말)',tail):score=10 if re.search(DEFINING_END,end) and not re.search(r'[그이저]런것이다[.。]?$',end) else 5
        elif re.match(NAMING,tail):score=10
        elif re.match(r'(?:으로|로)도?(?:불린다|불리며|불리고|불리기도|부른다|부르며|부르기도|일컫는다|칭한다|칭하며|명명한다|명명된다|명명되며|명명되기도)',tail):score=8
        elif opens and re.match(r'(?:은|는|이라는것은|라는것은|이라함은|라함은|의개념은|의정의는)',tail):
            score=9 if re.search(DEFINING_VERB+r'[.。]?$',end) and not re.search(r'(?:다|라|자|냐)고말한다[.。]?$',end) else 7 if re.search(r'이다[.。]?$',end) and not re.search(NOT_DEFINING_END,end) else 5
        else:score=1
        best=max(best,score)
    return best

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
            # 관형절 and 관형사절 both index 265쪽: one row per page, keeping the better sentence.
            pages={}
            for s in sources:
                seen=pages.get((s['book'],s['pdf_page']))
                if seen is None or (s.get('score') or 0)>(seen.get('score') or 0):pages[(s['book'],s['pdf_page'])]=s
            resolved=[]
            for s in pages.values():
                row=db.execute('SELECT id,printed_page,number_status,quality FROM pages WHERE id=?',(s['page_id'],)).fetchone()
                quote=correct_display(s['quote'])[0] if s.get('quote') else None
                more=correct_display(s['more'])[0] if quote and s.get('more') else ''
                item={'book':s['book'],'title':s['book'],'category':s['category'],'pdf_page':s['pdf_page'],'quote':quote,'more':more,'definition':(s.get('score') or 0)>=DEFINITION,'indexed':s.get('indexed',True),'ocr':bool(s.get('ocr')),'term':s.get('term',entry['label']),'id':row['id'] if row else None,'printed_page':row['printed_page'] if row else None,'quality':row['quality'] if row else None}
                resolved.append(item)
            # Definitions from the index pages first, then those found elsewhere in the
            # books, readable ones before those with OCR damage; pages without one last.
            resolved.sort(key=lambda s:(not s['quote'],not s['indexed'],s['ocr'],s['book'],s['pdf_page']))
            result.append({'key':k,'label':entry['label'],'variants':entry['variants'],'sources':resolved})
    return result
