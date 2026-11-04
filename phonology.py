"""Which sound change a question's example shows, read off the spelling and the
pronunciation the question gives: '국물'이 [궁물]로 → 비음화, '솜이불'을 [솜니불]로 →
ㄴ 첨가. The question never names the change, so search had nothing to go on: the
2026-11-04 evidence eval found 0% and 8% of their pages. The names lead the 해설 to
the books' pages on them (concept entries, 찾아보기, search) and reach the model as
candidates it checks against the books; they are never the answer by themselves.

The syllables are compared jamo by jamo at each boundary, the way the standard
pronunciation rules are stated. Only what the comparison shows is named, so an
example the rules here do not cover gives no name rather than a wrong one."""
import re

ONSETS='ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
NUCLEI='ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
CODAS=['','ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ','ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
CLUSTERS={'ㄳ':'ㄱㅅ','ㄵ':'ㄴㅈ','ㄶ':'ㄴㅎ','ㄺ':'ㄹㄱ','ㄻ':'ㄹㅁ','ㄼ':'ㄹㅂ','ㄽ':'ㄹㅅ','ㄾ':'ㄹㅌ','ㄿ':'ㄹㅍ','ㅀ':'ㄹㅎ','ㅄ':'ㅂㅅ'}
# The sound a final consonant has before a pause or a consonant (음절의 끝소리 규칙).
PLAIN={'ㄱ':'ㄱ','ㄲ':'ㄱ','ㅋ':'ㄱ','ㄷ':'ㄷ','ㅅ':'ㄷ','ㅆ':'ㄷ','ㅈ':'ㄷ','ㅊ':'ㄷ','ㅌ':'ㄷ','ㅎ':'ㄷ','ㅂ':'ㅂ','ㅍ':'ㅂ'}
NASAL={'ㄱ':'ㅇ','ㄷ':'ㄴ','ㅂ':'ㅁ'}
TENSE={'ㄱ':'ㄲ','ㄷ':'ㄸ','ㅂ':'ㅃ','ㅅ':'ㅆ','ㅈ':'ㅉ'}
ASPIRATE={'ㄱ':'ㅋ','ㄷ':'ㅌ','ㅂ':'ㅍ','ㅈ':'ㅊ'}
SONORANT=set('ㄴㄹㅁㅇ')
# ㄴ is added before ㅣ and the j-diphthongs (솜이불 [솜니불], 물약 [물략]).
J_VOWELS=set('ㅣㅑㅕㅛㅠㅒㅖ')
# 피어 [피여], 되어 [되여]: a glide after these vowels.
GLIDE={('ㅓ','ㅕ'),('ㅗ','ㅛ'),('ㅏ','ㅑ')}

def jamo(syllable):
    n=ord(syllable)-0xAC00
    return ONSETS[n//588],NUCLEI[n%588//28],CODAS[n%28]

def parts(coda):
    return CLUSTERS.get(coda,coda)

def changes(spelling,pronunciation):
    """The sound changes that turn the spelling into the pronunciation, in the
    order they show up; [] when the two do not line up syllable for syllable or
    nothing here explains them."""
    s=re.sub(r'\s','',spelling);p=re.sub(r'\s','',pronunciation)
    if not s or len(s)!=len(p) or not re.fullmatch(r'[가-힣]+',s+p) or s==p:return []
    S=[jamo(c) for c in s];P=[jamo(c) for c in p]
    # The same word read aloud: it starts the same and keeps its vowels (a glide aside).
    if S[0][0]!=P[0][0] or any(a[1]!=b[1] and (a[1],b[1]) not in GLIDE for a,b in zip(S,P)):return []
    found=[]
    def add(*names):
        for name in names:
            if name not in found:found.append(name)
    for i,((so,sn,sc),(po,pn,pc)) in enumerate(zip(S,P)):
        if i and sn!=pn and so=='ㅇ' and po=='ㅇ' and not S[i-1][2] and S[i-1][1] in 'ㅣㅚㅟㅐㅔ':add('반모음 첨가')
        last=i==len(S)-1
        no,nn,_=S[i+1] if not last else ('','','')
        np=P[i+1][0] if not last else ''
        coda_done=False
        if not last and sc:
            if no in 'ㅇㅎ' and nn=='ㅣ' and sc in ('ㄷ','ㅌ','ㄾ') and np in 'ㅈㅊ':
                add('구개음화')
                if no=='ㅎ':add('거센소리되기')
                coda_done=True
            elif no=='ㅇ' and nn in J_VOWELS and np in 'ㄴㄹ':
                add('ㄴ 첨가')
                if np=='ㄹ':add('유음화')
            elif no=='ㅇ' and parts(sc)[-1]=='ㅎ':
                if np in 'ㅇㄴㄹ':add('ㅎ 탈락')
                coda_done=True
            elif no=='ㅇ':
                coda_done=True  # 연음: the final consonant moves on, nothing changes
            elif parts(sc)[-1]=='ㅎ' and no in ASPIRATE and np==ASPIRATE[no]:
                add('거센소리되기');coda_done=True
            elif no=='ㅎ' and PLAIN.get(parts(sc)[-1]) in ASPIRATE and np==ASPIRATE[PLAIN[parts(sc)[-1]]]:
                add('거센소리되기');coda_done=True
            if no in TENSE and np==TENSE[no]:add('된소리되기')
            if no=='ㄹ' and np=='ㄴ':add('비음화')
            if no=='ㄴ' and np=='ㄹ' and parts(sc)[0]=='ㄹ':add('유음화')
        if coda_done or sc==pc:continue
        if sc=='ㄴ' and pc=='ㄹ' and np=='ㄹ':add('유음화');continue
        if pc in ('ㅇ','ㄴ','ㅁ') and sc not in SONORANT and np in ('ㄴ','ㅁ'):
            # 읽는 [잉는]: the cluster first loses a consonant; 부엌문 [부엉문]: ㅋ first becomes ㄱ.
            add('비음화')
            if sc in CLUSTERS:add('자음군 단순화')
            elif PLAIN.get(sc)!=sc:add('음절의 끝소리 규칙')
            continue
        if sc in CLUSTERS and (pc in parts(sc) or pc in {PLAIN.get(x) for x in parts(sc)}):add('자음군 단순화');continue
        if PLAIN.get(sc) and PLAIN[sc]!=sc and pc==PLAIN[sc]:add('음절의 끝소리 규칙')
    return found

PRONOUNCED=re.compile(r'\[\s*([가-힣][가-힣\s]*)\]|/([가-힣][가-힣\s]*)/')
QUOTED_BEFORE=re.compile(r"[‘'\"“]([가-힣][가-힣\s]*)[’'\"”]\s*(?:[가-힣]{1,2})?\s*(?:→|->|⇒|=>|:)?\s*$")
WORD_BEFORE=re.compile(r'([가-힣]+)\s*(?:→|->|⇒|=>|:)?\s*$')
# '국물'을 '궁물'로 발음, 국물 → 궁물
SPOKEN_AS=re.compile(r"[‘'\"“]?([가-힣]+)[’'\"”]?\s*(?:을|를)\s*[‘'\"“]([가-힣]+)[’'\"”]\s*(?:으로|로)\s*(?:발음|소리)")
ARROW=re.compile(r'([가-힣]+)\s*(?:→|->|⇒|=>)\s*([가-힣]+)')
PARTICLE=re.compile(r'(?:이|가|을|를|은|는|의|도|에|와|과|로|으로)$')

def pairs(query):
    """(spelling, pronunciation) for each example the question gives with its
    pronunciation: '국물'이 [궁물]로, 국물[궁물], '국물'을 '궁물'로 발음, 국물 → 궁물."""
    out=[]
    for m in PRONOUNCED.finditer(query):
        said=m[1] or m[2];before=query[:m.start()]
        word=QUOTED_BEFORE.search(before) or WORD_BEFORE.search(before)
        if not word:continue
        written=re.sub(r'\s','',word[1])
        # 국물이 [궁물]: the particle is not part of the word.
        if len(written)!=len(re.sub(r'\s','',said)) and PARTICLE.search(written):written=PARTICLE.sub('',written)
        out.append((written,said))
    out+=[(m[1],m[2]) for m in SPOKEN_AS.finditer(query)]+[(m[1],m[2]) for m in ARROW.finditer(query)]
    return list(dict.fromkeys((a,re.sub(r'\s','',b)) for a,b in out))

def sound_changes(query):
    """[{'spelling','pronunciation','changes'}] for the examples whose change is named."""
    return [{'spelling':s,'pronunciation':p,'changes':names} for s,p in pairs(query) for names in [changes(s,p)] if names]

def change_names(query):
    return list(dict.fromkeys(n for item in sound_changes(query) for n in item['changes']))
