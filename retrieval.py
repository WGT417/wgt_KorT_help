"""Local, passage-first retrieval. Source text is never rewritten."""
import math
import re
from collections import Counter

STOP = set('무엇 어떻게 무엇인가 무엇인가요 알려줘 알려주세요 설명 설명해 설명해줘 찾아줘 찾아주세요 대해 대한 관해 관한 좀 해줘 주세요 차이 차이는 비교 예시 인가 인가요 것인가 것일까 있나요 읽는'.split())
INTENT = {'종류','분류','체계','정의','개념','특징','특성','기능','의미','예','예시'}
# Domain equivalents, not generated answers. Keep this small and inspectable.
ALIASES = [('작문', '쓰기', '글쓰기'), ('독서', '읽기'), ('퇴고', '고쳐쓰기', '수정하기'), ('내용생성', '내용창안'), ('내용조직', '내용구성'), ('자유간접화법','자유간접문체'),
    # School-grammar names beside the names the 개론서 use.
    ('관형절','관형사절'), ('관계관형절','관계관형사절','관계절'), ('동격관형절','동격관형사절','보문절'), ('재귀대명사','재귀칭'), ('안은문장','내포문'), ('안긴문장','내포절'), ('이어진문장','접속문'), ('홑문장','단문'), ('겹문장','복문'), ('음절의끝소리규칙','평파열음화','음절말평파열음화'), ('된소리되기','경음화'), ('거센소리되기','격음화','유기음화')]

def compound_keys():
    """Compact spellings that count as one term: alias groups plus every term in the books' indexes."""
    keys=set(t for group in ALIASES for t in group)
    try:
        from term_index import _load
        keys.update(_load().keys())
    except Exception:pass
    return keys

# Only unambiguous particles; never mutilate lexical endings such as 피동, 쓰기, 시가, 화자, 의미 or 소설가.
PARTICLE_RE=re.compile(r'(에대해서|에관해서|에서는|인가요|인가|에게|에서|으로|이란|이랑|에는|에도|은|는|을|를|의|과|와|에)$')
def strip_particle(token):return PARTICLE_RE.sub('',token) if len(token)>2 else token

def terms(query):
    result=[]
    for token in re.findall(r'[가-힣A-Za-z0-9]+',query.lower()):
        if token in STOP: continue
        token=strip_particle(token)
        if len(token)>=2 and token not in STOP: result.append(token)
    return list(dict.fromkeys(result))[:12]

def groups_for(query):
    ts=terms(query)
    if any(t not in INTENT for t in ts):ts=[t for t in ts if t not in INTENT]
    # Preserve compound concepts while allowing OCR whitespace variation.
    for left,right in [('내용','생성'),('내용','조직'),('내용','창안'),('내용','구성')]:
        for i in range(len(ts)-1):
            if ts[i]==left and ts[i+1].startswith(right):
                ts[i:i+2]=[left+right];break
    # Adjacent words that together form an alias-listed term (관계 + 관형절) stay
    # one term so its equivalents (관계 관형사절, 관계절) count. Only the explicit
    # alias list merges: merging every indexed compound narrowed multiword
    # questions such as 심미적 독서 and 작문의 과정.
    known={t for group in ALIASES for t in group};i=0
    while i<len(ts)-1:
        joined=ts[i]+ts[i+1]
        if joined in known:ts[i:i+2]=[joined]
        else:i+=1
    groups=[next((a for a in ALIASES if t in a), (t,)) for t in ts]
    # A term this OCR never spells right (홑문장 comes out 흩문장, 흘문장) is not on
    # any page under its own name, so the damaged spellings are searched too.
    # The reading text still shows the term corrected (text_pipeline.tidy_display).
    damaged=damaged_spellings()
    return [tuple(dict.fromkeys((*g,*(w for t in g for w in damaged.get(t,()))))) for g in groups]

def damaged_spellings():
    """Corrected term -> the spellings the OCR left on the page."""
    from text_pipeline import misread_terms
    by_term={}
    for wrong,right in misread_terms().items():by_term.setdefault(right,[]).append(wrong)
    return by_term

def compact_with_offsets(text):
    chars=[]; offsets=[]
    for i,ch in enumerate(text):
        if not ch.isspace(): chars.append(ch.lower());offsets.append(i)
    return ''.join(chars), offsets

def retrieve(db,query,category,book_id,limit):
    from passage_search import search
    from text_pipeline import init_passages
    init_passages(db)
    return search(db,query,category,book_id,limit,groups_for(query))
