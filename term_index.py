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
# The literature books close a defining sentence without writing "…이다". Korean
# drops 이 after a vowel-final noun, so 장르이다 is printed 장르다 ("서사시는 …
# 서술시의 대표적 장르다"); a sentence that states what a form is made of ends in
# 로 이루어진다 ("판소리 사설은 아니리와 창의 결합으로 이루어진다"), and one that
# places a term in a category in 에 해당한다. All twelve places in the 문학 books
# were read. 로 분류·구분된다 was tried and dropped: listing the subtypes is not
# defining the term, which test_definitions_outrank_mentions already settled on
# "관형사절은 동격 관형사절과 관계 관형사절로 분류된다". The text this is matched
# against has its spaces removed, hence 에해당한다.
CATEGORY_END=r'(?:갈래|장르|양식|형식|문체|명칭|용어|개념|유형|부류|작품군|노래|시가|산문|운문)다|에해당한다|(?:으)?로이루어진다'
# What a "X란 ..." sentence must end with to define X rather than just talk about it.
DEFINING_END=r'(?:이다|'+CATEGORY_END+r'|말한다|뜻한다|의미한다|가리킨다|일[컫걷]는다|이른다|지칭한다|칭한다|정의된다|정의한다|규정된다|(?:라|이라|볼|말할|정의할)수있다|(?:뜻하|의미하|가리키|말하|이르)기도한다)[.。]?$'
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
            score=9 if re.search(DEFINING_VERB+r'[.。]?$',end) and not re.search(r'(?:다|라|자|냐)고말한다[.。]?$',end) else 7 if re.search(r'(?:이다|'+CATEGORY_END+r')[.。]?$',end) and not re.search(NOT_DEFINING_END,end) else 5
        else:score=1
        best=max(best,score)
    return best

def _load():
    stamp=PATH.stat().st_mtime_ns if PATH.exists() else None
    with _lock:
        if _cache['stamp']==stamp:return _cache['terms']
        terms=json.loads(PATH.read_text(encoding='utf-8')).get('terms',{}) if PATH.exists() else {}
        _cache.update(stamp=stamp,terms=terms);return terms

# The scan turns a closing bracket into a look-alike: 「봄봄J, 〈광장), 《사슴}.
CLOSING={'「':'」','〈':'〉','<':'〉','《':'》','『':'』'}
# Index headings whose jamo the scan read as Latin letters, each checked against
# its page. The same letter stands for different jamo, so no rule can do this:
# 한국어표준문법 102 lists "'H'불규칙, 'E'불규칙, 'λ'불규칙" (ㅂ ㄷ ㅅ), while
# 한국어문법총론 1 68 writes "'己'의 비음화" (ㄹ).
LABEL_FIXES={
    'E ’불규칙':'ㄷ 불규칙','E ’ 불규칙 활용':'ㄷ 불규칙 활용','E ’불규칙 동사':'ㄷ 불규칙 동사',
    'E ’의 비음화':'ㄹ의 비음화',
    'L ’첨가':'ㄴ 첨가',            # 국어음운론 강의 205: "4.1. L- 첨가"
    'L 다':'-ㄴ다','L 다’체':'-ㄴ다체',  # 한국현대소설의 이해 316: "'-L 다'체의 종결형"
    'l 상합자':'ㅣ 상합자',          # 국어사 개론 39: 一字中聲之與ㅣ相合者
    'OJ 수사':'양수사',              # 한국어표준문법 251: 양수사(量數詞)와 서수사
    # A name the index also carries with its hanja: one card, the plain spelling.
    '김동인金東仁':'김동인','김만중金萬重':'김만중','김소행金紹行':'김소행','박인량朴寅亮':'박인량',
    '서거정徐居正':'서거정','서유영徐有英':'서유영','성임成任':'성임','수산水山':'수산',
    '신재효申在孝':'신재효','야담野談':'야담','원호元昊':'원호','이인로李仁老':'이인로',
    '박지원朴빠源':'박지원','구우많佑':'구우','가전假따':'가전','비장悲밤':'비장',
    # One syllable the scan read as its look-alike (scripts/audit_glyphs.PAIRS).
    '대둥합성어':'대등합성어','겸손볍':'겸손법','문볍용어':'문법용어','시용역':'사용역',
    '상정 부사':'상징 부사','상정부사':'상징 부사','지음체계':'자음 체계','김기립':'김기림','한자어 병사':'한자어 명사',
    '일인칭 관찰자시접':'일인칭 관찰자 시점','국힌 문체':'국한문체','대웅적 진술':'대응적 진술',
    # A jamo the books quote, left as a letter or a look-alike syllable.
    'λ ’ 불규칙':'ㅅ 불규칙','λ ’불규칙 형용사':'ㅅ 불규칙 형용사','人-불규칙 어간':'ㅅ 불규칙 어간',
    '님’ 불규칙 동사':'ㅂ 불규칙 동사','동’불규칙 형용사':'ㅎ 불규칙 형용사','동-불규칙 어간':'ㅎ 불규칙 어간',
    '송-구개음화':'ㅎ 구개음화','근’ 탈락 규칙':'ㄹ 탈락 규칙','(느) L':'(느)ㄴ',
    # A quotation mark or a bracket the scan lost, and the heading it left behind.
    '「국문관계론(國文關係論) J':'「국문관계론」','「산남(山男) J':'「산남」','「삼대(三代) J':'「삼대」',
    '「야한기(夜寒記) J':'「야한기」','「을화(ζ火) J':'「을화」','「지맥(地版) J':'「지맥」','〈방(房))':'〈방〉',
    '상호 융화{Ineinander)':'상호 융화','다매체 언어(M띠ti-meclia)':'다매체 언어','인정 기술 A 定記述':'인정 기술',
    ', 김기림':'김기림',', 매체 언어':'매체 언어',', 자아( the ego)':'자아',', 최인호':'최인호',', 환상성':'환상성',
    '거라’ 불규칙':'거라 불규칙','너라’불규칙':'너라 불규칙','러’ 불규칙 동사':'러 불규칙 동사',
    '러’ 불규칙 형용사':'러 불규칙 형용사','르’ 불규칙 활용':'르 불규칙 활용','르’ 불규칙 형용사':'르 불규칙 형용사',
    '여’ 불규칙 동사':'여 불규칙 동사','여’ 불규칙 형용사':'여 불규칙 형용사','오’ 불규칙 동사':'오 불규칙 동사',
    '우’ 불규칙 동사':'우 불규칙 동사','불규칙형용사,':'불규칙 형용사','기’ 명사절':'기 명사절',
    # 고전시가작품론 indexes a 시조 by its opening line, and the scan is an OCR layer
    # (the pages' font is HiddenHorzOCR) made by an engine that does not know 옛한글:
    # ᄒᆞᆫ came out 흔, ᄆᆞᆰ다 붉다, 막ᄃᆡ 막덕/막믹. The reading is settled by the page's
    # own 지은이·출전 and the poem printed under it.
    '흔손에막덕잡고':'한 손에 막대 잡고',        # 우탁, 청구영언(육당본) 232쪽
    '개를여라븐이나기르되':'개를 여라믄이나 기르되',  # 사설시조, 청구영언(진본) 351쪽
    '창내고자창을내고자':'창 내고자 창을 내고자',   # 사설시조, 청구영언(진본) 342쪽
    '나모도바히돌도':'나모도 바히돌도',          # 사설시조, 청구영언(진본) 358쪽
    '가마귀 검다 창고':'가마귀 검다 하고',        # 이직, 청구영언(진본) 261쪽
    '북천이 붉다커늘':'북천이 맑다커늘',          # 임제, 해동가요(주씨본) 306쪽
    '어이 얼어 잘이':'어이 얼어 자리',           # 한우, 같은 쪽
    '서검을못일우고':'서검을 못 일우고',          # 김천택, 해동가요(주씨본) 333쪽
    '대장부공성신퇴항야':'대장부 공성신퇴하야',     # 이정보, 367쪽
    '동통':'동동',                            # 고려가요 動動, 140쪽("아으 動動다리")
    '가마귀검다창고':'가마귀 검다 하고',
    # 고소설: 전(傳)의 끝 글자를 젠으로, 쇠를 죄로 읽은 제목들.
    '「설공찬젠」':'「설공찬전」','「유충렬젠」':'「유충렬전」','「오륜전젠」':'「오륜전전」','「임씨젠」':'「임씨전」',
    '변강죄전':'변강쇠전','콩쥐팔쥐전':'콩쥐팥쥐전','문장풍류삼대목':'문장풍류삼대록',
    '향냥':'향낭','아니라':'아니리',            # 판소리의 아니리(白)
    '권섭뺨燮':'권섭','김매순金週淳':'김매순','나카라이 도스이半井挑水':'나카라이 도스이',
}
# The books' own index headings, and what the scan left of them: a card for
# "찾아보기" is the index itself, not a term. 답1·답2·장)·도록하·을 것이다 are
# scraps a heading line broke into. (시조 첫 구는 지우지 않는다: 제목 없는
# 고시조를 고전시가작품론 찾아보기가 첫 구로 싣는다 — 흔손에막덕잡고 등.)
JUNK={'찾아보기','색인','인영색인','잦m보기','증에}보기','찾아5ê기','칭i버{보기',
      '잦아보기-서지','찢아보기 서지','찾아보기-서지','잦아보기-전문용어','찢아보기-전문용어','찾아보기-전문용어',
      '답1','답2','장)','도록하','을 것이다','뱃글','뱃째','통사 구성의 어휘화 단어',
      '찾。}보기','찾아보기-인영','찢아보기-인명','찾아보기 •'}
JUNK_KEYS={key_of(x) for x in JUNK}

def display_label(label):
    """An index heading as the page shows it: known misreadings fixed and a work
    title's bracket closed (93 〈…) and 94 「…J among the 문학 books' headings;
    r등신불J is 「등신불」 with both brackets misread)."""
    if label in LABEL_FIXES:return LABEL_FIXES[label]
    label=correct_display(label)[0].strip()
    label=re.sub(r'^r\s*([^\sA-Za-z][^「」]*?)\s*J$',r'「\1」',label)
    m=re.fullmatch(r'([「〈<《『])([^「」〈〉<>《》『』()]+?)\s*[)〉>}JjＪ」》』]?',label)
    if m:label=('〈' if m[1]=='<' else m[1])+m[2].strip()+CLOSING[m[1]]
    # The table is looked up again: a heading may only match once its brackets and
    # its misread syllables are mended (「설공찬젠 → 「설공찬젠」 → 「설공찬전」).
    return LABEL_FIXES.get(label,label)

CHO='ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
def sort_key(label):
    """가나다 order as a Korean glossary has it: Hangul first, with a lone jamo
    (ㄴ 첨가) at the head of its consonant, then Latin, then numbers and the rest."""
    s=re.sub(r'^[^가-힣ㄱ-ㅎA-Za-z0-9]+','',label).lower();ch=s[:1]
    if '가'<=ch<='힣':rank,cho=0,(ord(ch)-0xAC00)//588
    elif ch and ch in CHO:rank,cho=0,CHO.index(ch)
    elif ch.isascii() and ch.isalpha():rank,cho=1,0
    else:rank,cho=2,0
    return (rank,cho,s,label)

def _group(k):
    """관형절 and 관형사절 are one card: the school-grammar name and the books' name."""
    from retrieval import ALIASES
    terms=_load()
    group=next((g for g in ALIASES if k in g),(k,))
    return [(g,terms[g]) for g in group if g in terms]

def _found(k):
    """Every indexed spelling that reads k once its label is fixed: L ’첨가 in
    국어음운론 강의 and ㄴ 첨가 in the other books are one term."""
    with _catalog_lock:keys=_build_catalog()['keys'].get(k,(k,))
    found={}
    for key in (k,*keys):
        for g,e in _group(key):found.setdefault(g,e)
    return list(found.items())

def _entry(found):
    return {'label':' · '.join(dict.fromkeys(display_label(e['label']) for g,e in found)),'variants':sorted({v for g,e in found for v in e['variants']})}

def match_terms(query,category='전체',limit=3):
    """Exact term matches only: a word of the question (particles stripped),
    or two or three adjacent words joined, must equal an indexed term."""
    if not _load():return []
    wanted=[key_of(t) for t in query_terms(query)]+[key_of(query)]
    hits=[]
    for k in dict.fromkeys(wanted):
        found=_found(k)
        if not found:continue
        sources=[dict(s,term=e['label']) for g,e in found for s in e['sources'] if category=='전체' or s['category']==category]
        if not sources:continue
        hits.append((len(k),len({s['book'] for s in sources}),k,_entry(found),sources))
    hits.sort(key=lambda h:(-h[0],-h[1]))
    # '음절의 끝소리 규칙' answers the question; its parts 음절 and 규칙 do not.
    keys=[h[2] for h in hits]
    hits=[h for h in hits if not any(h[2]!=k and h[2] in k for k in keys)]
    return _cards(hits[:limit])

def card(label):
    """The card for one term picked from the catalog: that term exactly, never a
    part of it, from every area."""
    k=key_of(label);found=_found(k)
    if not found:return []
    sources=[dict(s,term=e['label']) for g,e in found for s in e['sources']]
    entry=_entry(found);written=notes().get(k)
    if written and key_of(written['label'])==k:entry['label']=written['label']
    return _cards([(len(k),0,k,entry,sources)])

def _cards(hits):
    result=[]
    with connect() as db:
        for _,_,k,entry,sources in hits:
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
                item={'book':s['book'],'title':s['book'],'category':s['category'],'pdf_page':s['pdf_page'],'quote':quote,'more':more,'definition':(s.get('score') or 0)>=DEFINITION,'indexed':s.get('indexed',True),'ocr':bool(s.get('ocr')),'term':s.get('term',entry['label']),'id':row['id'] if row else None,'printed_page':row['printed_page'] if row else None,'number_status':row['number_status'] if row else None,'quality':row['quality'] if row else None}
                resolved.append(item)
            # Definitions from the index pages first, then those found elsewhere in the
            # books, readable ones before those with OCR damage; pages without one last.
            resolved.sort(key=lambda s:(not s['quote'],not s['indexed'],s['ocr'],s['book'],s['pdf_page']))
            result.append({'key':k,'label':entry['label'],'variants':entry['variants'],'sources':resolved})
    return result

AREA_BIT={'문식성':1,'문법':2,'문학':4}
DEFINED,CONCEPT,NOTE=1,2,4

NOTES=DATA/'term-notes.json'
_notes={'stamp':None,'by_key':{},'model':None}
def notes():
    """The 풀이 scripts/write_term_notes.py wrote ahead of time from the books'
    paragraphs, by term key. Nothing here calls a model."""
    stamp=NOTES.stat().st_mtime_ns if NOTES.exists() else None
    with _lock:
        if _notes['stamp']!=stamp:
            data=json.loads(NOTES.read_text(encoding='utf-8')) if NOTES.exists() else {}
            # Keyed by the label as the page shows it, so a note written before a
            # label was fixed still finds its card (국힌 문체 → 국한문체). The file's
            # key and the note's own label can be spelled differently ('국힌문체' vs
            # '국힌 문체'), and only the spaced one is corrected, so both are filed.
            by_key={}
            for label,n in data.get('notes',{}).items():
                for name in (label,n.get('label') or label):
                    by_key.setdefault(key_of(display_label(name)),n)
            _notes.update(stamp=stamp,model=data.get('model'),by_key=by_key)
        return _notes['by_key']

def note(label):
    """A card's 풀이 with each citation resolved to the library page it quotes.
    The 풀이 keeps the index heading it was written from, which may be the
    damaged one (송-구개음화, 변강죄전, ‘, 매체 언어’), so the card's own fixed
    name is what the screen shows."""
    n=notes().get(key_of(label))
    if not n:return None
    cites=[]
    with connect() as db:
        for c in n['citations']:
            row=db.execute('SELECT p.id,p.printed_page,p.pdf_page,p.number_status,b.title FROM pages p JOIN books b ON b.id=p.book_id WHERE p.id=?',(c['page_id'],)).fetchone()
            if row:cites.append(dict(row)|{'book':row['title'],'quote':correct_display(c['quote'])[0]})
    if not cites:return None
    return {k:n[k] for k in ('label','definition','explanation','examples','basis')}|{'label':display_label(label),'citations':cites,'model':_notes['model']}
_catalog={'stamp':None,'items':[],'keys':{}}
# Fixing 6,600 labels takes most of a second, so the server builds the list once
# at start (server.warm_catalog) and a request arriving meanwhile waits for that
# build instead of starting its own.
_catalog_lock=threading.Lock()
def catalog():
    """Every term of the books' indexes and every written concept, for the page
    that lays them out as cards: [label, area bits, books, flags], in 가나다
    order, one card per label as fixed (display_label), so 양수사 and OJ 수사
    are one card.

    Headings stood in for the index of 고전산문교육론 and 한국문학강의 (see
    build_term_index.heading_terms). They serve questions well enough, but as a
    list they read "할 수도 없었다", "저 13 장", "꼼꼼히 읽기: …", so a term only
    those headings give is left out of the catalog."""
    with _catalog_lock:return _build_catalog()['items']

def _build_catalog():
    from concepts import all_concepts
    terms=_load();concepts=all_concepts();written=notes()
    stamp=(_cache['stamp'],id(concepts),_notes['stamp'])
    if _catalog['stamp']==stamp:return _catalog
    data=json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {}
    from_headings={b['book'] for b in data.get('books',[]) if b.get('from_headings')}
    named={key_of(t) for c in concepts for t in c['_terms']}
    groups={}
    for k,e in terms.items():
        if {s['book'] for s in e['sources']}<=from_headings or key_of(e['label']) in JUNK_KEYS:continue
        label=display_label(e['label'])
        groups.setdefault(key_of(label),[label,[]])[1].append(k)
    items=[];renamed={}
    for shown,(label,keys) in groups.items():
        sources=[s for k in keys for s in terms[k]['sources']]
        flags=(DEFINED if any(s.get('quote') for s in sources) else 0)|(CONCEPT if named&{shown,*keys} else 0)|(NOTE if shown in written else 0)
        # The 풀이 spells the term with its spaces put back (두 자리 서 술어 → 두 자리 서술어).
        # That rename can change the key the card is looked up by (국힌 문체 → 국한문체),
        # and the group is still filed under the old one, so the card came back empty.
        # Remember the new key too.
        if shown in written and key_of(written[shown]['label'])==shown:
            label=display_label(written[shown]['label'])
            if key_of(label)!=shown:renamed.setdefault(key_of(label),keys or [shown])
        items.append([label,sum(AREA_BIT.get(c,0) for c in {s['category'] for s in sources}),len({s['book'] for s in sources}),flags])
    # A concept named by no index heading ("국어의 통시적 변화") is still a card.
    for c in concepts:
        k=key_of(c['label'])
        if k in groups:continue
        items.append([c['label'],AREA_BIT.get(c['area'],0),len({s.get('book') for s in c.get('sources',[]) if s.get('book')}),CONCEPT]);groups[k]=[c['label'],[]]
    items.sort(key=lambda i:sort_key(i[0]))
    lookup={shown:keys for shown,(label,keys) in groups.items() if keys!=[shown]}
    for k,v in renamed.items():lookup.setdefault(k,v)
    _catalog.update(stamp=stamp,items=items,keys=lookup)
    return _catalog
