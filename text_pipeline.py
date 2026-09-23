"""Layout-aware, reversible local reading text. Never rewrite source glyphs."""
import re,statistics,hashlib,json
from pathlib import Path
# Resolved once: resolve() costs about 1.5ms on Windows, and correct_display
# looked up two of these files on every call (5s for the 6,600 index labels).
DATA_DIR=Path(__file__).resolve().parent/'data'
VERSION='layout-spacing-v3'
TERMS='''형태소 이형태 형태론 통사론 음운론 의미론 화용론 통사 음운 음소 변이음 음절 어절 단일어 합성어 파생어 어근 접사 접두사 접미사 선어말어미 어말어미 종결어미 연결어미 전성어미 명사형 관형사형 부사형 관형사절 명사절 부사절 인용절 서술절 안긴문장 안은문장 홑문장 겹문장 이어진문장 피동사 사동사 피동문 사동문 피동 사동 주동 능동 높임법 주체높임 객체높임 상대높임 시제 서법 동작상 본용언 보조용언 의존명사 서술격조사 보조사 격조사 주격조사 목적격조사 관형격조사 부사격조사
독서교육 작문교육 문학교육 국어교육 과정중심 결과중심 내용생성 내용조직 고쳐쓰기 계획하기 표현하기 초인지 배경지식 의미구성 자기점검 자기조절 독해력 문식성 상향식 하향식 상호작용 심미적 비판적 창의적 능동적 자기주도적 사고구술법 소리내어읽기 브레인스토밍 협동학습 반응중심 문제해결 교수학습
서술자 초점화 서술시점 내적독백 자유간접화법 자유간접문체 서정시 서사시 자유시 정형시 시적화자 시적자아 운율 내재율 외형률 음수율 음보율 상징 은유 직유 환유 제유 공감각 객관적상관물 감정이입 낯설게하기 반어 역설 비극 희극 고전소설 현대소설 고전시가 향가 고려가요 경기체가 시조 가사 판소리'''.split()
def restore_terms(text):
    for term in sorted(TERMS,key=len,reverse=True):
        # Only change spacing, including syllables split across OCR lines.
        text=re.sub(r'\s*'.join(map(re.escape,term)),term,text)
    for term in ['독서 교육','작문 교육','문학 교육','국어 교육','과정 중심','결과 중심','내용 생성','내용 조직','배경 지식','의미 구성','자기 점검','자기 조절','시적 화자','시적 자아','객관적 상관물','반응 중심','문제 해결','교수 학습']:
        text=text.replace(term.replace(' ',''),term)
    text=re.sub(r'(어미|형태소|음운|음절|독서|작문)(와|과)(?=[가-힣])',r'\1\2 ',text)
    text=re.sub(r'(하기도|해야|이해할|수행할|확인할|설명할)(?=한다|하는|한다는|된다)',r'\1 ',text)
    # OCR splits item numbers such as "(1 )" and "( 2)"; only whitespace changes.
    text=re.sub(r'\(\s*(\d{1,2})\s*\)',r'(\1)',text)
    return text
def compact(text):return re.sub(r'\s+','',text).lower()

# Superscript footnote references come out of the text layer as a stray syllable
# or number glued to a sentence end (한다.쩌 (122)의, 있다46 남의, 구분한다 12
# 단모음은), to a clause (나타나며70 격 조사) or to a heading
# (관형사절을안은문장39). A comma after an ending is often read as 1 (있고1
# 그것이). A glued syllable that really starts a sentence stays, and so does a
# number that counts something (있다.1 연에서, 2 학년과, 9품사).
SENTENCE_INITIAL=set('즉이그저또곧더왜꼭늘잘참좀못안한두세네첫새각몇약총단및전후본위표시예나너내제둘셋넷김박최와과는은를을가의로에고도만라자아오어음응다')
# Words a number counts ("2 학년", "10 년", "3 인칭"): the number is not a footnote mark.
COUNTED=re.compile(r'(?:부터|까지|내지|또는|및|이상|이하|미만|이내|년대|세기|번째|차시|개국|년|월|일|시|분|초|개|명|사람|권|쪽|면|장|절|항|조|편|부|차|회|번|등급|단계|가지|종류|음절|음보|자|글자|행|연|대|세|학년|학기|인칭|모음|자음|품사|퍼센트|배|점|마리|곳|줄|칸|단원|과|원)(?:이|가|은|는|을|를|의|에|에서|과|와|도|만|로|으로|부터|까지|씩|째|간|쯤|이나|나|이다|이며|이고|처럼|같이|만큼|에서는|에는|으로는|로는|에서도|에도|이라는|라는|이란)?')
# A footnote number, sometimes read with l or I for 1 (l7 is 17).
NUMBER=r'\d{1,2}(?![\dlI])|[lI]\d(?!\d)|\d[lI](?![\dlI])'

# Two books point from the running text to a boxed exercise or an addendum
# printed elsewhere ("한다. 적용4", "있다.[덧붙임 1]."). Like a footnote number the
# mark belongs to the page, not to the sentence. The number and the brackets
# come out of the text layer damaged ("[덧붙임 8J.", "[덧붙임 1이." for 10],
# "적용1 0" for 적용10), so only the label itself is matched exactly.
CALLOUT_NUMBER=r'\d{1,2}(?:[ \t]*[,，][ \t]*\d{1,2})?(?:[ \t]+\d(?!\d)|[ \t]*[가-힣](?![가-힣]))?'
CALLOUT_CLOSE=r'[ \t]*[\])}J1l]{0,2}[ \t]*'
# A mark the sentence reads through stays: "[덧붙임 2]에서 언급한", "제13장 [덧붙임
# 5]를 보라", "[덧붙임 11] 에서". A mark closed by a period ends the sentence
# before it, so "[덧붙임 4]. 이 밖에도" is a mark and 이 there is a word.
CALLOUT_END=r'(?:[.。](?=[ \n，,]|$)|(?=[ \n，,]|$)(?![ \t]*(?:에서|에|을|를|의|이|가|은|는|으로|로|과|와|도|만|까지|부터)(?![가-힣])))'
ADDENDUM=re.compile(r'[\[({f][ \t]*(?:덧붙임|덧붙엄)\s*'+CALLOUT_NUMBER+CALLOUT_CLOSE+CALLOUT_END)
APPLY=re.compile(r'(?:(?<=[다요자라])|(?<=[.。])|(?<=[，,])|(?<=\d)|(?<=[\])}】])|(?<=\n)|(?<=\A))'
                 r'[ \t]*(적용[ \t]*'+CALLOUT_NUMBER+CALLOUT_CLOSE+CALLOUT_END+r')')
def callout_marks(raw):
    """(start, end) of every cross-reference mark standing between sentences."""
    return [m.span() for m in ADDENDUM.finditer(raw)]+[m.span(1) for m in APPLY.finditer(raw)]

def note_marks(raw):
    """(start, end, replacement) for the footnote marks, cross-reference marks
    and the sentence punctuation the marks took with them, in `raw`."""
    marks={span:'' for span in callout_marks(raw)}
    for m in re.finditer(r'(?<=[다요][.!?。])([가-힣]|\d{1,2})(?=[ \t]+(\S))',raw):
        mark,after=m.group(1),m.group(2)
        if mark in SENTENCE_INITIAL or (mark.isdigit() and after!='('):continue
        marks[m.span(1)]=''
    # The superscript took the period with it ("이끌어질 수도 있다46 남의 말이나",
    # "구분한다 12 단모음은", "것이다 15) 이런"), so the mark is read back as one.
    for m in re.finditer(r'(?<=[가-힣]다)[ \t]*('+NUMBER+r'|\d{1,2}\))(?=[ \t\n]+([가-힣]+))',raw):
        if not COUNTED.fullmatch(m.group(2)):marks[m.span(1)]='.'
    # Glued to a comma and read with l or I: "성립하지 않으며，l7 보조 용언은". A plain
    # number there is as often a list item ("，2 생활 속에서，3 더 찾아 읽기").
    for m in re.finditer(r'(?<=[，,])([lI]\d(?!\d)|\d[lI](?![\dlI]))(?=[ \t\n]+([가-힣]+))',raw):
        if not COUNTED.fullmatch(m.group(2)):marks[m.span(1)]=''
    # Glued to an ending or particle: a comma read as 1, otherwise a footnote mark.
    for m in re.finditer(r'(?<=[가-힣][고로도데서만며면를을에는은와과써여해지요])('+NUMBER+r')(?=[ \t\n]+([가-힣]+))',raw):
        if COUNTED.fullmatch(m.group(2)) or re.match(r'차(?:교육과정|개정|시)',m.group(2)):continue
        marks.setdefault(m.span(1),'，' if m.group(1)=='1' and raw[m.start()-1] in '고로며면서데요' else '')
    for m in re.finditer(r'^[ \t]*\d+(?:\.\d+)+\.?[ \t]*\S[^\n]*?[가-힣](\d{1,2})[ \t]*$',raw,re.M):marks[m.span(1)]=''
    return [(a,b,r) for (a,b),r in sorted(marks.items())]

def glyph_gaps(text):
    """The non-space characters of `text`, the whitespace before each, and what trails."""
    glyphs=[];gaps=[];gap=''
    for ch in text:
        if ch.isspace():gap+=ch
        else:glyphs.append(ch);gaps.append(gap);gap=''
    return ''.join(glyphs),gaps,gap

def term_starts(text,gaps,raw_gaps,keys,longest,every=False):
    """(position, term) for the longest term in `keys` beginning at each word
    start, or for every such term, longest first, with `every`."""
    for p,ch in enumerate(text):
        if not '가'<=ch<='힣' or not (p==0 or gaps[p] or raw_gaps[p] or not '가'<=text[p-1]<='힣'):continue
        for n in range(min(longest,len(text)-p),1,-1):
            if text[p:p+n] in keys:
                yield p,text[p:p+n]
                if not every:break

_joined={'stamp':None,'keys':frozenset(),'longest':0,'misread':{}}
def _term_lists():
    path=DATA_DIR/'term-index.json'
    stamp=path.stat().st_mtime_ns if path.exists() else None
    if stamp!=_joined['stamp']:
        data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        keys=frozenset(data.get('joined',[]))
        _joined.update(stamp=stamp,keys=keys,longest=max(map(len,keys),default=0),misread=data.get('misread',{}))
    return _joined
def joined_terms():
    """Index terms the books write without a space (scripts/build_term_index.py counts it)."""
    lists=_term_lists();return lists['keys'],lists['longest']
def misread_terms():
    """Terms the OCR misread by one syllable: 통작성 -> 동작성, 흩문장 -> 홑문장
    (scripts/build_term_index.misreadings)."""
    return _term_lists()['misread']

# An author cited as 박진호(1998) keeps the source spacing the spacing model split (박진 호).
SURNAMES='김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구나민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부'
# A lone syllable before a term-looking run is usually a word of its own:
# 이 형태 is "this form", not 이형태.
STANDALONE=SENTENCE_INITIAL|set('것수등때데뿐바중앞뒤속밑곳적줄채듯양만번개명권쪽장절말글책뜻법')
# The spacing model is given a paragraph with its line breaks closed up, so it
# re-spaces text the page had already spaced, and where one glyph defeats it
# ("꽁기" for 공기) it runs a whole clause together: "…은 조음 과정에서 꽁기의" came
# back as "…은조음과정에서꽁기의". A space printed inside a line is the book's own
# typography and is put back, unless the two words it separates are a form the
# books themselves print as one ("보석처 럼", "소설이 다" — those spaces are the
# scan's, not the page's). A single syllable on either side is left to the model,
# because that is the shape a scan's stray space makes, except inside a run the
# model has plainly derailed on.
RESPACE_RUN=8
def respace(text,gaps,raw_gaps,keys=(),longest=0):
    """Glyph positions where the page printed a space and the spacing model
    closed it up. A position inside a term the books write as one word is left
    closed, so 부사격 조사 stays 부사격조사; a form the books themselves mostly
    print as two words (할수, 두개의) is not such a word and comes back spaced."""
    known=one_word_forms()
    if not known:return set()
    # A line break is where the page ran out of room, not a word boundary, so a
    # token that ends at one is half a word ("불리기도 하 / 며") and the word on
    # either side is read across the break.
    bounds=[0]+[i for i in range(1,len(text)) if re.search(r'[ \t]',raw_gaps[i])]+[len(text)]
    token={q:(a,b) for a,b in zip(bounds,bounds[1:]) for q in range(a,b)}
    out=set()
    for i in range(1,len(text)):
        if gaps[i] or '\n' in raw_gaps[i] or not re.search(r'[ \t]',raw_gaps[i]):continue
        if not ('가'<=text[i-1]<='힣' and '가'<=text[i]<='힣'):continue
        start=token[i-1][0];end=token[i][1]
        left=re.sub(r'[^가-힣]','',text[start:i]);right=re.sub(r'[^가-힣]','',text[i:end])
        if left+right in known:continue
        if len(left)<=1 or len(right)<=1:
            a=i
            while a and not gaps[a]:a-=1
            b=i
            while b<len(text)-1 and not gaps[b+1]:b+=1
            if sum('가'<=c<='힣' for c in text[a:b+1])<RESPACE_RUN:continue
        out.add(i)
    if out and keys:
        trial=list(gaps)
        for q in out:trial[q]=' '
        for p,term in term_starts(text,trial,raw_gaps,keys,longest):out-=set(range(p+1,p+len(term)))
    return out

_guard={}
def respace_terms(keys,longest):
    """The term list that protects a join, cached: the index terms plus TERMS."""
    if _guard.get('keys') is not keys:
        _guard.update(keys=keys,guard=keys|frozenset(TERMS),longest=max(longest,max(map(len,TERMS))))
    return _guard['guard'],_guard['longest']

def respaced(raw,display):
    """`display` with the spaces the page printed on the line put back."""
    if not raw or not display or compact(raw)!=compact(display):return display
    text,gaps,trailing=glyph_gaps(display)
    raw_gaps=glyph_gaps(raw)[1]
    keys,longest=respace_terms(*joined_terms())
    split=respace(text,gaps,raw_gaps,keys,longest)
    if not split:return display
    for q in split:gaps[q]=' '
    return ''.join(gaps[g]+ch for g,ch in enumerate(text))+trailing

def tidy_display(raw,display,terms=None,misread=None):
    """Reading text for the screen. Footnote marks and the books' own
    cross-reference marks are dropped and the punctuation they took with them is
    read back; a term the books write as one word is rejoined where the spacing
    model split it and the source had no space (관 계절로 -> 관계절로, 동 격 ->
    동격); example numbers the OCR split are closed up ((1 23 가) -> (123가)).
    Returns (text, marks handled, plus terms the OCR misread and that are shown
    corrected: 통작성 -> 동작성, 흩문장 -> 홑문장). Excerpts, evidence and
    citations keep the source glyphs. `terms` is (keys, longest) and `misread`
    the corrections while the term index itself is being built."""
    if not raw or not display or compact(raw)!=compact(display):return display,0
    text,gaps,trailing=glyph_gaps(display)
    raw_at=[i for i,ch in enumerate(raw) if not ch.isspace()]
    raw_gaps=glyph_gaps(raw)[1]
    at={pos:g for g,pos in enumerate(raw_at)}
    spans=note_marks(raw)
    marks={at[i]:(r if i==a else '') for a,b,r in spans for i in range(a,b) if i in at}
    keys,longest=terms or joined_terms()
    misread=misread_terms() if misread is None else misread
    # The page's own spaces first: a word the model ran together is not a word
    # the corrections below can recognise ("…에서꽁기의" only becomes 꽁기의 here).
    for q in respace(text,gaps,raw_gaps,*respace_terms(keys,longest)):gaps[q]=' '
    joined=set();done=0;fixed=0
    if misread:
        chars=list(text);sizes=sorted({len(k) for k in misread},reverse=True)
        for p,ch in enumerate(text):
            # A word start on screen counts too, because the source often lost
            # the space altogether ("이루어진문장을흩문장이라고한다").
            if not '가'<=ch<='힣' or (p and not raw_gaps[p] and not gaps[p] and '가'<=text[p-1]<='힣'):continue
            for n in sizes:
                if p+n>len(text):continue
                right=misread.get(text[p:p+n])
                # Only a word the source wrote as one run: 부가가치는 제조업 is not
                # 가치논제. A line break inside it still leaves one word (흩\n문장).
                if right and not any(re.search(r'[ \t]',raw_gaps[q]) for q in range(p+1,p+n)):
                    chars[p:p+n]=right;joined.update(q for q in range(p+1,p+n) if gaps[q]);fixed+=1;break
        text=''.join(chars)
    for m in re.finditer(r'(?<![가-힣])['+SURNAMES+r'][가-힣]{1,3}(?=\(\s*[12\d])',raw):
        g=at.get(m.end()-1)
        if g is None:continue
        start=at[m.start()]
        if all(not raw_gaps[q] for q in range(start+1,g+1)):joined.update(q for q in range(start+1,g+1) if gaps[q])
    for p,term in term_starts(text,gaps,raw_gaps,keys,longest) if keys else ():
        # Only a run that starts a word on screen: 학문 태 준 is not 문태준 to rejoin.
        if p<done or (p and not gaps[p] and '가'<=text[p-1]<='힣'):continue
        end=p+len(term);inner=[q for q in range(p+1,end) if gaps[q]]
        if not inner:done=end;continue
        # The source itself spaced it, or the first syllable is a word of its own.
        if any(re.search(r'[ \t]',raw_gaps[q]) for q in inner) or (gaps[p+1] and text[p] in STANDALONE):continue
        # Two-syllable terms only when split into two lone syllables (동 격).
        if len(term)==2 and end<len(text) and not gaps[end] and '가'<=text[end]<='힣':continue
        joined.update(inner);done=end
    out=[gaps[0]] if gaps else [];pending=''
    for g,ch in enumerate(text):
        gap='' if g in joined else gaps[g]
        if g in marks:
            # Punctuation read back sits on the word before it: "있고， 그것이", "있다. 남의".
            if marks[g]:out.append(marks[g]);pending=''
            else:pending=pending or gap
            continue
        # The space before a dropped mark still separates the words around it.
        if len(out)>1:out.append(gap or pending)
        out.append(ch);pending=''
    shown=''.join(out)+trailing
    shown=re.sub(r'\((\s*\d(?:\s*\d){1,3})\s*([가나다라마바사아자차카타파하]?[\'′]?)\s*\)',lambda m:'('+re.sub(r'\s','',m.group(1))+m.group(2)+')',shown)
    return shown,len(spans)+fixed

def split_heading(raw,display):
    """A heading line the layout joined to the paragraph below it ("7 보조용언의
    의미 기능", "4.3.3.2. 관형사절을안은문장"): short, no sentence end, ending in
    a noun, and followed by full lines. Returns (heading, body raw, body display);
    heading is '' when there is none. Glyphs are unchanged."""
    lines=raw.split('\n')
    if len(lines)<2 or compact(raw)!=compact(display):return '',raw,display
    first=lines[0].strip();size=len(compact(first));rest=max(len(compact(l)) for l in lines[1:])
    number=re.match(r'\s*(?:\d+(?:\.\d+)*\.?|\(\d+\)|\d+\)|[①-⑳]|[가-하]\.)\s*([가-힣]*)',first)
    numbered=bool(number) and not COUNTED.fullmatch(number.group(1) or '-')
    if not 2<=size<=(32 if numbered else 24) or rest<18 or size>=rest*(.8 if numbered else .5):return '',raw,display
    # Not a heading: a sentence end, a clause ending (끝나고), a particle at either
    # end (면 참조, 은， 앞서), an unclosed bracket, a trailing number or a quote.
    if re.search(r'[다요][.!?。]|다$|[，,;:]$|\d$|[“”"]',first) or first.count('(')!=first.count(')'):return '',raw,display
    if re.search(r'[가-힣](?:고|며|서|면|는데|지만|어서|아서)\s',first) or re.match(r'[가-힣][\s，,]',first):return '',raw,display
    # A line cut mid-phrase ends in a particle or a one-syllable word ("감상한 후 그 것").
    if not numbered and re.search(r'[가-힣][고며서면는은을를이가에의와과도만로]$|\s[가-힣]$',first):return '',raw,display
    # A subject or topic inside the line makes it the start of a sentence: "(325가)는 접미사".
    if not numbered and re.search(r'(?:[가-힣]{2}|[)〉」』’])(?:는|은|이|가)\s',first):return '',raw,display
    seen=0
    for i,ch in enumerate(display):
        if seen==size:return display[:i].strip(),raw[len(lines[0])+1:],display[i:].lstrip()
        seen+=not ch.isspace()
    return '',raw,display

_corrections={'stamp':None,'words':{}}
def corrections():
    """Display-only OCR corrections accepted by scripts/audit_glyphs.py (whole words, same length)."""
    path=DATA_DIR/'ocr-corrections.json'
    stamp=path.stat().st_mtime_ns if path.exists() else None
    if stamp!=_corrections['stamp']:
        words=json.loads(path.read_text(encoding='utf-8')).get('words',{}) if path.exists() else {}
        _corrections.update(stamp=stamp,words={w:v['to'] for w,v in words.items() if len(v['to'])==len(w)})
    return _corrections['words']

_printed={'stamp':None,'words':frozenset(),'latin':frozenset(),'solid':frozenset(),'often_split':frozenset()}
def _printed_lists():
    """What the pages themselves print as one word, read off the extracted text
    rather than off the spacing model's output (scripts/audit_glyphs.py counts it)."""
    path=DATA_DIR/'source-words.json'
    stamp=path.stat().st_mtime_ns if path.exists() else None
    if stamp!=_printed['stamp']:
        data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        _printed.update(stamp=stamp,words=frozenset(data.get('words',())),latin=frozenset(data.get('latin',())),
                        solid=frozenset(data.get('solid',())),often_split=frozenset(data.get('often_split',())))
        _printed['one_word']=_printed['words']-_printed['often_split']
    return _printed
def source_words():
    """Korean word forms the books print as one word within a line."""
    return _printed_lists()['words']
def solid_words():
    """Of those, the forms the books hardly ever print as two words (3% or less):
    각각 483:0, 그것을 567:0, but not 할수 61:2,051."""
    return _printed_lists()['solid']
def often_split_words():
    """Forms the books print as two words more often than as one (할수, 두개의):
    a joined reading of one of these is the scan having lost the page's space."""
    return _printed_lists()['often_split']
def one_word_forms():
    """The printed words minus those (할수, 두개의, 예를들어): what may stand
    joined on screen where the page itself printed a space."""
    return _printed_lists()['one_word']
def latin_words():
    """Latin word forms the books print inside their Korean prose."""
    return _printed_lists()['latin']

_vocabulary={'stamp':None,'words':frozenset()}
def corpus_words():
    """Word forms the 26 books repeat (scripts/audit_glyphs.py counts them)."""
    path=DATA_DIR/'corpus-words.json'
    stamp=path.stat().st_mtime_ns if path.exists() else None
    if stamp!=_vocabulary['stamp']:
        words=json.loads(path.read_text(encoding='utf-8')).get('words',()) if path.exists() else ()
        _vocabulary.update(stamp=stamp,words=frozenset(words))
    return _vocabulary['words']

def strange_ratio(text):
    """Share of the Korean words in `text` that no book in the library repeats.
    A word the scan invented (인해돼스트기반입기, 복합g씩텍스트읽기) appears once and
    nowhere else, so a high share means the reader is being shown letters rather
    than words. Prose that merely names rare concepts stays low, because the
    books repeat their own terms. 0.0 when the vocabulary has not been built."""
    known=corpus_words()
    if not known:return 0.0
    words=re.findall(r'[가-힣]{2,}',text)
    return sum(w not in known for w in words)/len(words) if words else 0.0

# The OCR layer uses full-width punctuation; in the page font "본용언， 본용언과"
# looks like a space before the comma.
PLAIN=str.maketrans({'，':',','：':':','；':';','（':'(','）':')','．':'.','？':'?','！':'!','～':'~'})

# The grammar books cite a jamo by printing it in quotes, and this scan reads the
# glyph as something else. The books' own sentences settle each reading: "‘E’의
# 비음화는 ‘E’이 ‘L’으로 바뀌는 현상" and "‘근’의 비음화를 가리키는 다른 용어" are both
# ㄹ; "‘T’는 입술을 둥글게 오므리며" is ㅜ; "국어의 마찰음에는 ‘人 송’이 있다" is ㅅ and
# ㅎ; "‘님, 표, 배, 口’이 양순음에 속한" is ㅂ ㅍ ㅃ ㅁ. ㅐ is left alone: it comes out
# as H, but so does ㅂ ("‘H’이라는 음소는 음절의 초성에 놓일 때"), and nothing in the
# line says which. A letter followed by more letters is a word, not a jamo, so the
# French title ‘L’enfer, c'est les autres’ stays as it is.
JAMO={'E':'ㄹ','L':'ㄴ','T':'ㅜ','근':'ㄹ','己':'ㄹ','口':'ㅁ','人':'ㅅ','λ':'ㅅ','。':'ㅇ','「':'ㄱ','亡':'ㄷ','닝':'ㅂ'}
# These stand for a jamo as well, but they are also words of their own (만해의
# ‘님’, 시경의 ‘송’, ‘눈’과 ‘매화 향기’), so they are read as jamo only where the
# sentence is talking about sounds and letters ("‘괴, 귀’는 이중 모음으로 발음할
# 수 있다", "국어의 후음에는 ‘송’이 존재한다").
JAMO_WORD={'님':'ㅂ','표':'ㅍ','송':'ㅎ','동':'ㅎ','승':'ㅎ','종':'ㅎ','괴':'ㅚ','귀':'ㅟ'}
# A jamo's own NAME says which particle follows it, so the particle says which
# jamo the glyph stands for. Vowel names are open syllables (애, 우, 의) and take
# 가/를/는/와/로; consonant names are closed (비읍, 디귿) and take 이/을/은/과/으로 —
# 리을 alone takes 로 like a vowel. Three glyphs are read two ways and the particle
# settles them: ‘H’ is ㅐ in "‘H’와 ‘ㅔ’를 구분하지 못하고" but ㅂ in "‘H’이 ‘ㄴ’
# 앞에서 ‘ㅁ’으로 바뀌는"; ‘E’ is ㄹ in "‘E’로 바뀐다" but ㄷ in "평파열음화에 의해
# ‘E’으로"; ‘기’ is ㄱ in "‘기’은 ‘ㄴ’ 앞에 올 수 없다" but the ending -기 in "‘기’가
# 쓰이면". Where the particle does not settle it, the glyph is left as it is.
PARTICLE={'으로':'consonant','로':'rieul','가':'vowel','를':'vowel','는':'vowel','와':'vowel',
          '이':'closed','을':'closed','은':'closed','과':'closed'}
PARTICLE_AFTER=re.compile(r'\s*(으로|로|가|를|는|와|이|을|은|과)(?![가-힣])')
# ‘E’ with 이/을/은/과, or with no particle at all, fits 리을 and 디귿 alike. A broad
# cue list (파열음, 사이시옷, 대표음…) was tried over all 156 such places and read the
# sonorant list "‘ㄴ, E, ㅁ, ㅇ’" and 맞춤법 제8항's 받침 list as ㄷ, so the commoner
# ㄹ stays the default. Two narrow cues do hold, each checked place by place:
# - ‘E’ 불규칙 is ㄷ 불규칙 — the books' own examples are 묻다(問)·물으니, 걷다·깨닫다·
#   싣다, [묻따]/[무르내] (15 of 17 places). ㄹ-final stems drop their ㄹ by rule, so
#   ‘E’ 불규칙 is ㄹ only where the passage treats that drop as irregular, and it
#   then names the stems or the drop: "‘놀다’… ‘E’ 탈락이 일어났기 때문에 ‘E’ 불규칙
#   활용으로 다루기도 한다" (한국어표준문법 105), "‘길다’류를 ‘E’ 불규칙" (277).
# - "‘E’이 ‘E’로 바뀌며" cannot name one sound turning into itself: all three places
#   are 묻다→물어 and 걷다→걸어, ㄷ becoming ㄹ.
IRREGULAR=re.compile(r'\s*불\s*규\s*칙')
RIEUL_STEMS=re.compile(r"[‘'\"]\s*E\s*[’'\"]\s*탈락|놀다|길다|알다|살다|울다|날다|멀다|만들다")
BECOMES_RIEUL=re.compile(r"\s*이\s*[‘'\"]\s*E\s*[’'\"]\s*로")
def two_way(key,after,window):
    """The reading the particle settles; None to leave the glyph as it is."""
    m=PARTICLE_AFTER.match(after);kind=PARTICLE[m.group(1)] if m else None
    if key=='H':return 'ㅐ' if kind in {'vowel','rieul'} else 'ㅂ' if kind in {'consonant','closed'} else None
    if key=='기':return 'ㄱ' if kind in {'consonant','closed'} else None
    if kind=='consonant' or BECOMES_RIEUL.match(after):return 'ㄷ'
    if IRREGULAR.match(after):return 'ㄹ' if RIEUL_STEMS.search(window) else 'ㄷ'
    return 'ㄹ'
TWO_WAY={'H','E','기'}
JAMO_CUE=re.compile(r'음소|음운|변이\s?음|자음|모음|된소리|비음|유음|경음|평음|격음|마찰음|파열음|파찰음|후\s?음|순\s?음|치조|연구개|경구개|초성|중성|종성|받침|조음|구개음|음절|자모|글자|훈민정음|해례|발음|불청|불\s?탁|상형|가획')
# The vowels the phonology books cite come out as a digit, a hyphen and a brace:
# "‘1’ 모음 역행 동화", "양순음 뒤에 오는 ‘-’", "단 모음 ‘}’". All three are also
# what this scan leaves where ㄱ stood inside a consonant list, and there the rest
# of the list says so — "‘1, C, 동’의 구개음화" is ㄱㄷㅎ, 평파열음화의 "‘님, C, -,’"
# is ㅂㄷㄱ. So they are read as vowels only where no other item of the same
# quotation is a consonant, and only where the line is about sounds.
VOWEL_GLYPH={'1':'ㅣ','-':'ㅡ','}':'ㅏ'}
CONSONANT_JAMO=set('ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ')
def consonant_list(items):
    """Whether a quoted list names a consonant beside the doubtful glyphs."""
    return any(JAMO.get(k,'') in CONSONANT_JAMO or JAMO_WORD.get(k,'') in CONSONANT_JAMO
               or any(c in CONSONANT_JAMO for c in k) for k in items if k not in VOWEL_GLYPH)
OPEN_QUOTE='‘“\'"'
CLOSE_QUOTE='’”\'"'
QUOTED=re.compile('(['+OPEN_QUOTE+'])([^'+OPEN_QUOTE+CLOSE_QUOTE+r'\n]{0,40}?)(['+CLOSE_QUOTE+'])')
# Only a comma list is split into items. Splitting on spaces as well would read
# the ‘천만 근’ of a poem and the ‘ E rinnerung’ of a bibliography as jamo.
CITED_SPLIT=re.compile(r'[，,、]')

# "‘-(으)ㄴ’" comes back as "느(의L ’" and "‘-(으)ㄹ’" as "까으)2 ’": the opening quote
# and the hyphen were read as one syllable, the closing paren was swallowed by the
# vowel ("(으)" left as "(의"), and the jamo itself became a letter or a digit.
CITED_JAMO={'L':'ㄴ','2':'ㄹ','근':'ㄹ','己':'ㄹ','E':'ㄹ','口':'ㅁ','디':'ㅁ','0':'ㅁ','人':'ㅅ','λ':'ㅅ'}
MEDIAL=re.compile(r'([(（]\s*)[으의](\s*[)）]?\s*)(['+''.join(CITED_JAMO)+r'])(?![A-Za-z0-9])')
OPENERS='느노니나내냐가거까카키개ι←'
CITED_OPEN=re.compile(r'(?<![(（])(['+OPENERS+r'])\s*[(（]?\s*([으어])\s*[)）]')
# ‘-는’ read as ‘눈’, which is a word of its own, so the sentence has to be naming endings.
CITED_WORD={'눈':'-는'}
CITED_CUE=re.compile(r'어미|관형사형|선어말')
CITED_WORD_QUOTE=re.compile('(['+OPEN_QUOTE+r'])\s*('+'|'.join(CITED_WORD)+r')\s*(['+CLOSE_QUOTE+'])')

# A cited ending keeps the glyph inside it: ‘- L 다’ is ‘-ㄴ다’, ‘-(으)口’ is ‘-(으)ㅁ’.
# The hyphen or the paren is what says it is a citation; ‘천만 근’ has neither, and a
# run of three syllables makes it a phrase rather than a form.
CITED_FORM=re.compile(r'[-—~/()（）\s가-힣ㄱ-ㅣ'+''.join(JAMO)+r']{1,14}')

def read_citations(text):
    """The jamo and the endings the grammar books cite, read back for the screen.
    Returns (text, citations read). Nothing outside a citation is touched."""
    count=0
    def medial(m):
        """"-(의L ’" and "-(으)2 ’" are both -(으)ㄹ/ㄴ: the paren the vowel swallowed returns."""
        nonlocal count;count+=1
        tail=m.group(2) if ')' in m.group(2) or '）' in m.group(2) else ')'+m.group(2)
        return m.group(1)+'으'+tail+CITED_JAMO[m.group(3)]
    text=MEDIAL.sub(medial,text)
    def opener(m):
        """Only where the citation closes: "선어말 어미가 으)시-’를" is "선어말 어미 ‘-(으)시-’를"."""
        nonlocal count
        tail=text[m.end():m.end()+14]
        if '’' not in tail and "'" not in tail:return m.group(0)
        count+=1
        space=' ' if m.start() and not text[m.start()-1].isspace() else ''
        return space+'‘-('+m.group(2)+')'
    text=CITED_OPEN.sub(opener,text)
    def word(m):
        nonlocal count
        if not CITED_CUE.search(text[max(0,m.start()-70):m.end()+70]):return m.group(0)
        count+=1;return m.group(1)+CITED_WORD[m.group(2)]+m.group(3)
    text=CITED_WORD_QUOTE.sub(word,text)
    def quoted(m):
        """Each item of "‘님, 표, 배, 口’" on its own; a run of letters is a word."""
        nonlocal count
        body=m.group(2);items=[i.strip() for i in CITED_SPLIT.split(body)];hit=0;out=[]
        sounds=None
        for key in items:
            if key in VOWEL_GLYPH:
                if sounds is None:
                    sounds=not consonant_list(items) and bool(JAMO_CUE.search(text[max(0,m.start()-100):m.end()+100]))
                out.append(VOWEL_GLYPH[key] if sounds else key);hit+=sounds
            elif key in TWO_WAY:
                read=two_way(key,text[m.end():],text[max(0,m.start()-110):m.end()+80])
                out.append(read or key);hit+=bool(read)
            elif key in JAMO:out.append(JAMO[key]);hit+=1
            elif key in JAMO_WORD and JAMO_CUE.search(text[max(0,m.start()-100):m.end()+100]):out.append(JAMO_WORD[key]);hit+=1
            else:out.append(key)
        out=', '.join(out)
        if not hit and CITED_FORM.fullmatch(body) and re.search(r'[-—(（]',body) and not re.search(r'[가-힣]{3,}',body):
            hit=sum(ch in JAMO for ch in body);out=''.join(JAMO.get(ch,ch) for ch in body)
        if not hit:return m.group(0)
        if re.fullmatch(r'\s*[A-Za-z]\s*',body) and (re.match(r'[A-Za-z]',text[m.end():m.end()+1] or ' ') or re.search(r'[A-Za-z]$',text[:m.start()])):return m.group(0)
        count+=hit
        return m.group(1)+out+m.group(3)
    text=QUOTED.sub(quoted,text)
    # The space the source left between the jamo and the closing quote ("‘-(으)ㄴ ’").
    return re.sub(r'([ㄱ-ㅣ])[ \t]+(['+CLOSE_QUOTE+'])',r'\1\2',text),count

# A stray space inside the Latin glosses these books set beside their terms:
# "자음(子音， co nsonant)", "이 형태(異形態， a llomorph)", "음운적 단어(phonologic
# al word)". The library's own spelling of the word says where the space does not
# belong; two words that are both spelled that way elsewhere are left alone, so
# "in formation" and "an other" stay as they are.
LATIN_RUN=re.compile(r'(?<![A-Za-z])[A-Za-z]+(?:[ ][A-Za-z]+)+(?![A-Za-z])')
def join_latin(text):
    """Latin words the scan broke with a space, put back. Returns (text, joins).
    A word can be broken more than once ("se ntenc e", "read i ng"), so up to
    four pieces in a row are joined, longest first, and every piece after the
    first has to be lower case."""
    known=latin_words()
    if not known or not re.search(r'[A-Za-z] [a-z]',text):return text,0
    count=0
    def fuse(m):
        nonlocal count
        parts=m.group().split(' ');out=[];i=0
        while i<len(parts):
            for n in range(min(4,len(parts)-i),1,-1):
                group=parts[i:i+n];whole=''.join(group)
                if (all(p[:1].islower() for p in group[1:]) and len(whole)>=4
                        and whole.lower() in known and not all(p.lower() in known for p in group)):
                    out.append(whole);count+=1;i+=n;break
            else:out.append(parts[i]);i+=1
        return ' '.join(out)
    return LATIN_RUN.sub(fuse,text),count

def correct_display(text):
    """Replace known OCR-damaged words for reading. Returns (text, number of replacements).
    Source text, excerpts and citations are never changed; only what is shown."""
    if not text:return text,0
    text=re.sub(r'(?<=[가-힣’”)]),(?=\S)',', ',re.sub(r'\s+([,:;)?!])',r'\1',text.translate(PLAIN)))
    text,jamo=read_citations(text)
    text,latin=join_latin(text);jamo+=latin
    words=corrections()
    if not words:return text,jamo
    count=jamo
    def swap(m):
        nonlocal count
        fixed=words.get(m.group())
        if fixed is None:return m.group()
        count+=1;return fixed
    return re.sub(r'[가-힣]{2,}',swap,text),count

# Chapter exercises quote concepts as tasks or true/false statements. They are
# not explanations and must not be promoted as evidence.
EXERCISE=r'(?:하|보|쓰|고르|구분|논의|정리|계획|말해|답하|찾아|비교|설명|제시|서술|토의|발표|작성|분석|평가)(?:해)?\s*보?시오|참\(t\)|거짓\(f\)|다음물음에답|다음진술|아래용어|^학습활동|^탐구활동|^연습문제|생각해볼문제|토의해봅시다|생각해봅시다'
def exercise_heading(text):
    return bool(re.fullmatch(r'\W*(?:학습|탐구|연습|심화|적용)\s*(?:활동|문제|과제)\W*',text.strip()))

def classify(text):
    c=compact(text)
    if re.search(r'차례|찾아보기|참고문헌',c[:40]):return 'index'
    if exercise_heading(text) or re.search(EXERCISE,c):return 'exercise'
    # Catalogs enumerate publishers/volumes rather than explain a concept.
    if len(re.findall(r'교과서|천재교육|천재교과서|지학사|비상교과서|신사고|동아출판',c))>=3:return 'catalog'
    if sum(ch.isdigit() for ch in c)>max(30,len(c)*.22):return 'table'
    if len(re.findall(r'[가-힣A-Za-z]',c))<20:return 'fragment'
    return 'body'

def page_lines(page,textpage=None):
    """Line records with geometry; from the embedded layer or a supplied OCR textpage."""
    lines=[]
    layout=page.get_text('dict',textpage=textpage) if textpage is not None else page.get_text('dict')
    for block in layout['blocks']:
        if block.get('type')!=0:continue
        for line in block['lines']:
            spans=line['spans'];text=''.join(s['text'] for s in spans).strip()
            if not text:continue
            x0,y0,x1,y1=line['bbox']
            lines.append({'text':text,'box':[x0,y0,x1,y1],'size':statistics.median(s['size'] for s in spans)})
    return lines

def layout_passages(page,lines=None):
    width,height=page.rect.width,page.rect.height
    lines=[dict(l) for l in lines] if lines is not None else page_lines(page)
    if not lines:return []
    wide=[l for l in lines if l['box'][2]-l['box'][0]>width*.48 and height*.07<l['box'][1]<height*.9]
    left=statistics.median(l['box'][0] for l in wide) if wide else width*.1
    size=statistics.median(l['size'] for l in wide) if wide else statistics.median(l['size'] for l in lines)
    lanes={'body':[],'note':[],'margin':[]}
    for l in lines:
        x0,y0,x1,y1=l['box']
        lane='body'
        if (y1<height*.06 or y0>height*.93) and len(l['text'])<130:lane='margin'
        elif left>width*.21 and x1<left-3:lane='note'
        elif l['size']<size*.77:lane='note'
        lanes[lane].append(l)
    result=[]
    for lane,items in lanes.items():
        items.sort(key=lambda l:(round(l['box'][1]/3),l['box'][0]))
        # Coalesce text spans on the same baseline; table cells stay separated.
        rows=[]
        for l in items:
            if rows and abs(l['box'][1]-rows[-1]['box'][1])<max(3,l['size']*.4):
                r=rows[-1];gap=l['box'][0]-r['box'][2]
                r['parts'].append(l)
                r['box']=[min(r['box'][0],l['box'][0]),min(r['box'][1],l['box'][1]),max(r['box'][2],l['box'][2]),max(r['box'][3],l['box'][3])]
            else:rows.append({**l,'cells':1,'parts':[l]})
        for r in rows:
            parts=sorted(r['parts'],key=lambda l:l['box'][0])
            r['text']=parts[0]['text'];r['cells']=1
            for prev,part in zip(parts,parts[1:]):
                separated=part['box'][0]-prev['box'][2]>size*1.8
                r['text']+=('\t' if separated else ' ')+part['text']
                r['cells']+=int(separated)
        buf=[];chars=0
        def flush():
            nonlocal buf,chars
            if not buf:return
            raw='\n'.join(r['text'] for r in buf)
            kind=classify(raw) if lane=='body' else lane
            if sum(r['cells']>=3 for r in buf)>=2:kind='table'
            # A small-print list of steps or cells is a table, not a side note.
            if lane=='note' and (raw.count('•')+raw.count('\t'))>=3:kind='table'
            result.append({'raw':raw,'kind':kind,'bbox':[min(r['box'][0] for r in buf),min(r['box'][1] for r in buf),max(r['box'][2] for r in buf),max(r['box'][3] for r in buf)]})
            buf=[];chars=0
        for r in rows:
            if buf:
                previous=buf[-1]
                gap=r['box'][1]-previous['box'][3]
                indent=r['box'][0]-left
                # Paragraph breaks, larger headings, and table boundaries.
                boundary=gap>size*1.25 or (indent>size*.8 and re.search(r'[다요][.!?。]?\s*$',previous['text'])) or ((r['cells']>=3)!=(previous['cells']>=3)) or chars>800
                if boundary:flush()
            buf.append(r);chars+=len(r['text'])
        flush()
    result.sort(key=lambda p:(p['kind']=='margin',p['kind']=='note',p['bbox'][1],p['bbox'][0]))
    # Everything below an exercise heading on the page belongs to the exercises.
    exercise_top=min((p['bbox'][1] for p in result if p['kind'] in {'body','fragment','exercise'} and exercise_heading(p['raw'])),default=None)
    if exercise_top is not None:
        for p in result:
            if p['kind'] in {'body','fragment','catalog'} and p['bbox'][1]>=exercise_top:p['kind']='exercise'
    return result

def readable(text,kiwi):
    # Korean language model changes whitespace only. Reject any glyph change.
    source=re.sub(r'\s+',' ',text).strip()
    corrected=kiwi.space(source,reset_whitespace=True)
    return restore_terms(corrected) if compact(corrected)==compact(source) else source

def init_passages(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS passages(
      id INTEGER PRIMARY KEY,page_id INTEGER,ordinal INTEGER,kind TEXT,raw TEXT,
      display TEXT,compact TEXT,bbox TEXT,version TEXT,UNIQUE(page_id,ordinal));
      CREATE INDEX IF NOT EXISTS passage_page ON passages(page_id);
      CREATE TABLE IF NOT EXISTS text_build(page_id INTEGER PRIMARY KEY,digest TEXT,version TEXT);
    ''')
