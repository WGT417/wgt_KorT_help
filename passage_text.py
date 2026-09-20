"""Contiguous sentence excerpts with reversible offsets to extracted source."""
import re
from text_pipeline import compact,restore_terms,correct_display

# Greek/Cyrillic letters, currency and trademark signs, backslashes: OCR
# misreads of Hangul strokes, never legitimate inside Korean prose here.
FOREIGN=re.compile(r'[À-ɏͰ-ϿЀ-ӿ￠-￦¢©«®»™\\]')
# Three more shapes the scan leaves behind, all read off the compacted text:
# Hangul pulled into a Latin gloss ("텍스트(m뻐", "(C이 e & Hall"), a colon
# standing in for a stroke ("pre:final", "a:J(l- stltuent"), and a run of carets
# or tildes where a syllable used to be ("^~용하기도"). Example numbers the scan
# read with l for 1 ("(l다)는") and the syllable types of 음운론 ("(V형, VC형")
# are spelled the same way and stay.
GLOSS=r'\((?![li][가-힣])[a-z]{1,3}(?![형류군급계열])[가-힣]|[a-z]:[a-z0-9]|[~^]{2,}'
# A gloss set in the Latin alphabet with a Hangul syllable standing where letters
# should be: "기능 문법(gr 없 lmar)", "intellectu 외 seriousness", "텍스 틴 monomc
# 벼 상대되는". Read off the spaced text, because compacting closes the gap that
# gives it away. A particle between two Latin words is an ordinary sentence
# ("Chomsky 의 Syntactic Structures"), so particles do not count.
PARTICLE=r'의|은|는|이|가|을|를|과|와|도|에|로|나|만|및|즉|등'
def lone(size):return r'(?!(?:'+PARTICLE+r')(?![가-힣]))(?<![가-힣])[가-힣]{1,'+str(size)+r'}(?![가-힣])'
# Latin on both sides is damage on its own; Hangul on both sides needs the
# stranded run to be a single syllable, or a real sentence would match.
STRANDED=re.compile(r'[A-Za-z]{2,}[ \t]+'+lone(2)+r'[ \t]+[A-Za-z]{2,}'
                    r'|'+lone(1)+r'[ \t]+[A-Za-z]{3,}[ \t]+'+lone(1))
def noise(text):
    c=compact(text)
    return len(re.findall(r'[가-힣][A-Za-z%&@]{1,3}[가-힣]|[가-힣][0-9][}\-]|[가-힣][0-9]{3,}|[가-힣][λ}]|[0-9]π|[a-zA-Z]\)\x27|[-~]{4,}|'+GLOSS,c))+len(FOREIGN.findall(c))+len(STRANDED.findall(text))+int(bool(re.match(r'^[;:，]',c)))

# A Hanja gloss followed by a Korean particle or ending is how these books are
# printed (話者는, 軍律에, 素材를); it is not damage. Damage is a Hangul syllable
# standing where another Hanja belongs (模뼈 for 模倣, 共짧 for 共謀).
HANJA_TAIL=r'(?:의|이|가|을|를|은|는|에|와|과|도|만|로|으|라|하|한|들|인|시|형|적|론|설|편|권|장|절|기|서|부|년|대|체|류|어|음|자|문|학|법|성|화|식|제)'
BROKEN_GLOSS=re.compile(r'[一-鿿](?!'+HANJA_TAIL+r'(?![가-힣]))[가-힣]')
# A bullet or a note mark opening a line is the page's own typography, not a
# stray glyph: the circled numerals ①②③ all come out of this scan as @.
MARKER=re.compile(r'^[@*%·•]\s')
def ocr_damage(text):
    """Kinds of OCR damage still visible in a reading sentence that noise()
    lets through: jamo read as Latin letters (‘ L ’이 ‘ E ’로), a stray digit
    between words, a stray symbol, a long run with no spaces, Hangul standing
    inside a Hanja gloss (설면(좀面))."""
    kinds=[]
    plain=re.sub(r'\([^)]*[A-Za-z]{2,}[^)]*\)','',text)
    # A single letter in quotes is deliberate notation — a jamo the scan could
    # not read, or a placeholder the book itself uses (명사 ‘A’와 ‘B’, ‘C’는 자음).
    plain=re.sub(r'[‘\'"“]\s*[A-Za-z]\s*[’\'"”]','',plain)
    if re.search(r'(?<![A-Za-z\-/])[A-Z](?![A-Za-z])',plain):kinds.append('letter')
    from text_pipeline import COUNTED
    if any(not COUNTED.fullmatch(m.group(1)) for m in re.finditer(r'[가-힣]\s\d{1,2}\s([가-힣]+)',plain)):kinds.append('digit')
    if (re.search(r'^[%$#@&*|]',text) and not MARKER.match(text)) or re.search(r'[가-힣][%&@|][가-힣]',text):kinds.append('symbol')
    if re.search(r'[가-힣]{18,}',text):kinds.append('unspaced')
    if BROKEN_GLOSS.search(text):kinds.append('hanja')
    return kinds

def shown_damage(text):
    """ocr_damage as the reader meets it, after the display corrections: a
    sentence whose jamo citations were read back ("‘-(으)ㄴ’, ‘-는’") is no longer
    damaged, and can stand as a definition."""
    return ocr_damage(correct_display(text)[0])

def suspect_segments(display):
    """Split reading text into sentences, marking those with visible OCR damage.
    Nothing is removed: the reader sees the whole paragraph with doubtful
    sentences flagged instead of silently missing."""
    display=restore_terms(display)
    segments=[];start=0
    for m in re.finditer(SENTENCE_END,display):
        segments.append(display[start:m.end()]);start=m.end()
    if start<len(display):segments.append(display[start:])
    out=[]
    for s in segments:
        if not s.strip():continue
        flag=bool(noise(s))
        if out and out[-1]['suspect']==flag:out[-1]['text']+=s
        else:out.append({'text':s,'suspect':flag})
    for o in out:o['text']=o['text'].strip()
    return out

def clean_blocks(raw,display):
    selected=[];used=[]
    for excerpt,text in sorted(windows(raw,display),key=lambda w:-len(w[0])):
        start=raw.find(excerpt);end=start+len(excerpt)
        if any(start<b and end>a for a,b in used):continue
        used.append((start,end));selected.append((start,text))
    return [text for _,text in sorted(selected)]

SENTENCE_END=r'[다요][.!?。](?:[”’\x27"])?(?=\s|$)|다(?=\s)(?!\s+[A-Za-z])'
def align(raw,display):
    """Display spacing laid over the source line and cell breaks. Glyphs unchanged."""
    if compact(raw)!=compact(display):return raw
    raw_gaps=[];gap=''
    for ch in raw:
        if ch.isspace():gap+=ch
        else:raw_gaps.append(gap);gap=''
    out=[];i=0;pending=''
    for ch in display:
        if ch.isspace():pending+=ch;continue
        source_gap=raw_gaps[i]
        if i:out.append('\n' if '\n' in source_gap else '\t' if '\t' in source_gap else ' ' if pending else '')
        out.append(ch);pending='';i+=1
    return ''.join(out)

def windows(raw,display):
    """Do not repair uncertain letters or splice noncontiguous sentences."""
    return [(excerpt,text) for _,_,excerpt,text in sentence_runs(raw,display)]

def chunks(raw,display,target=320,limit=640,minimum=40):
    """Non-overlapping runs of clean sentences for dense retrieval, cut left to
    right near `target` characters so each sentence is indexed once. Every run
    is a window: a contiguous source excerpt that never ends mid-sentence.
    Short definitions count, and a block ending in 다 without a period is a
    finished sentence rather than one cut by the page."""
    runs=sentence_runs(raw,display,minimum=minimum,closing=True)
    if runs and runs[0][0] is None:
        text=restore_terms(display)
        return [(raw,text)] if not noise(text) and len(compact(text))>=minimum and len(text)<=limit else []
    by_start={}
    for i,j,excerpt,text in runs:by_start.setdefault(i,[]).append((j,excerpt,text))
    result=[];after=0
    for i in sorted(by_start):
        if i<after:continue
        options=[o for o in by_start[i] if len(o[2])<=limit] or by_start[i][:1]
        pick=next((o for o in options if len(o[2])>=target),options[-1])
        # A short tail that cannot stand as its own run joins this one.
        if not any(s>pick[0] for s in by_start):pick=options[-1]
        result.append((pick[1],pick[2]));after=pick[0]+1
    return result

def sentence_runs(raw,display,minimum=65,closing=False):
    """(first sentence, last sentence, source excerpt, display text) for every
    run of up to six clean sentences. (None, None, raw, display) when spacing
    correction cannot be mapped back to the source glyphs."""
    display=restore_terms(display)
    spans=[];start=0
    for m in re.finditer(SENTENCE_END,display):
        spans.append((start,m.end(),True));start=m.end()
    # Text after the last sentence ending was cut by a page or block boundary.
    if start<len(display):spans.append((start,len(display),bool(closing and re.search(r'[가-힣]다\s*$',display[start:]))))
    if not spans:return []
    raw_offsets=[i for i,ch in enumerate(raw) if not ch.isspace()]
    offsets=[0]
    for ch in display:offsets.append(offsets[-1]+int(not ch.isspace()))
    if offsets[-1]!=len(raw_offsets):return [(None,None,raw,display)]
    result=[]
    for i,(start,end,complete) in enumerate(spans):
        # A sentence containing visible OCR damage is retained in full source,
        # but cannot be promoted as a clean explanation excerpt.
        if noise(display[start:end]) or end-start>600:continue
        for j in range(i,min(i+6,len(spans))):
            end=spans[j][1]
            # An excerpt never ends mid-sentence.
            if not spans[j][2]:break
            text=display[start:end].strip()
            if noise(display[spans[j][0]:end]) or end-spans[j][0]>600:break
            if len(text)>900:break
            if len(compact(text))<minimum:continue
            lo=offsets[start];hi=offsets[end]
            if hi<=lo:continue
            excerpt=raw[raw_offsets[lo]:raw_offsets[hi-1]+1]
            result.append((i,j,excerpt,text))
    return result

def best_window(raw,display,groups):
    candidates=[]
    for excerpt,text in windows(raw,display):
        c=compact(text)
        if not all(any(t in c for t in g) for g in groups):continue
        matches=sum(min(3,sum(c.count(t) for t in g)) for g in groups)
        complete=bool(re.search(r'[다요][.!?。][”’\x27"]?$',text))
        start_clean=not bool(re.match(r'^[;:，\W]|^(?:다[.!]|고만|으로\s)',text))
        # Show the paragraph that develops the concept, not the two shortest
        # sentences that mention it. Windows are already free of damaged text.
        first=compact(re.split(SENTENCE_END,text,maxsplit=1)[0])
        topical=any(any(t in first for t in g) for g in groups)
        score=matches*4+complete*4+start_clean*4+topical*3+min(len(text),700)/140
        if len(text)>700:score-=(len(text)-700)/150
        candidates.append((score,excerpt,text))
    if not candidates:return None
    _,excerpt,text=max(candidates,key=lambda x:x[0])
    return excerpt,text
