"""Contiguous sentence excerpts with reversible offsets to extracted source."""
import re
from text_pipeline import compact,restore_terms

# Greek/Cyrillic letters, currency and trademark signs, backslashes: OCR
# misreads of Hangul strokes, never legitimate inside Korean prose here.
FOREIGN=re.compile(r'[À-ɏͰ-ϿЀ-ӿ￠-￦¢©«®»™\\]')
def noise(text):
    c=compact(text)
    return len(re.findall(r'[가-힣][A-Za-z%&@]{1,3}[가-힣]|[가-힣][0-9][}\-]|[가-힣][0-9]{3,}|[가-힣][λ}]|[0-9]π|[a-zA-Z]\)\x27|[-~]{4,}',c))+len(FOREIGN.findall(c))+int(bool(re.match(r'^[;:，]',c)))

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
    display=restore_terms(display)
    spans=[];start=0
    for m in re.finditer(SENTENCE_END,display):
        spans.append((start,m.end(),True));start=m.end()
    # Text after the last sentence ending was cut by a page or block boundary.
    if start<len(display):spans.append((start,len(display),False))
    if not spans:return []
    raw_offsets=[i for i,ch in enumerate(raw) if not ch.isspace()]
    offsets=[0]
    for ch in display:offsets.append(offsets[-1]+int(not ch.isspace()))
    if offsets[-1]!=len(raw_offsets):return [(raw,display)]
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
            if len(compact(text))<65:continue
            lo=offsets[start];hi=offsets[end]
            if hi<=lo:continue
            excerpt=raw[raw_offsets[lo]:raw_offsets[hi-1]+1]
            result.append((excerpt,text))
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
