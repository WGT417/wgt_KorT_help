"""Layout-aware, reversible local reading text. Never rewrite source glyphs."""
import re,statistics,hashlib,json
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

_corrections={'stamp':None,'words':{}}
def corrections():
    """Display-only OCR corrections accepted by scripts/audit_glyphs.py (whole words, same length)."""
    from pathlib import Path
    path=Path(__file__).resolve().parent/'data'/'ocr-corrections.json'
    stamp=path.stat().st_mtime_ns if path.exists() else None
    if stamp!=_corrections['stamp']:
        words=json.loads(path.read_text(encoding='utf-8')).get('words',{}) if path.exists() else {}
        _corrections.update(stamp=stamp,words={w:v['to'] for w,v in words.items() if len(v['to'])==len(w)})
    return _corrections['words']

def correct_display(text):
    """Replace known OCR-damaged words for reading. Returns (text, number of replacements).
    Source text, excerpts and citations are never changed; only what is shown."""
    words=corrections()
    if not words or not text:return text,0
    count=0
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
