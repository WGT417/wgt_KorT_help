"""Full-corpus survey of OCR glyph damage in the reading text.

Two kinds of damage are measured over every body/table/note passage:

1. Foreign symbols inside Korean prose (Greek letters for ㅅ/ㅇ, currency
   signs, ©, backslashes...). Counted per character and per book.
2. Hangul look-alike confusions (히↔하, 지↔자, 볍↔법, 괴↔과 ...). For every
   word containing a suspect syllable the corrected word is scored with the
   Kiwi language model. A correction is recorded only when the corrected
   word reads clearly better AND the corrected word itself occurs in the
   corpus at least MIN_TARGET times AND it occurs more often than the
   damaged form. Whole-word, same-length rules only, so citation offsets
   stay aligned with the source text.

Writes data/glyph-audit.json (statistics, samples) and
data/ocr-corrections.json (the accepted display-only rules).
Source text in the database is never modified.
"""
import sys,re,json,time,unicodedata,argparse
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from kiwipiepy import Kiwi

# OCR shape confusions observed in this library: damaged syllable -> intended syllable.
PAIRS={'히':'하','지':'자','볍':'법','괴':'과','영':'명','렉':'텍','럭':'텍','시':'사','둥':'등','디':'다','슴':'습','힐':'활','휠':'활','넘':'념','엽':'업','딴':'발','뭇':'뜻','갓':'것','깃':'것','밍':'명','정':'징','익':'악','볼':'불','섬':'심','겅':'경','펀':'된','히':'하','굽':'급','긍':'등','힌':'한','헤':'해','뎌':'더','츠':'초','치':'차','띠':'따','틀':'들','니':'나','샤':'서','졍':'정','딘':'단','딜':'달','텀':'럼','낱':'날'}
MIN_GAIN=4.0      # language-model score gain required for the corrected word
MIN_TARGET=3      # corrected word must already occur this often in the corpus
# Damaged-looking forms that are real words in these books; never rewritten.
LEGITIMATE={'기지','치를','치가','치게','한지를','지음과','시이','기치를','여지는','헤는','감지','시전','시정이','지연의','투영한','상정이다','상정과','치원','교시는','시용','시용하는','지기','아디','학습지','필지','시장','시제','지시','지도','지수','지위','시각','시기','시대','시절','시점','시집','시행','시험','정도','정의','정서','정보','정리','정상','치료','치우','영향','영역','영상','영화','섬유','섬세','틀어','틀린','틀에','틀을','틀이','낱자','낱말','니라고','시상','시선','시조','시어','시가','시인','시적','정치','정신','정체','정확','정당','영어','영역','영상'}
def accept(word,fixed,count,target,gain):
    if word in LEGITIMATE or any(word.startswith(x) for x in LEGITIMATE if len(x)>=2 and word!=x and len(word)-len(x)<=2):return False
    ratio=target/max(1,count)
    return (ratio>=4 and gain>=6) or (ratio>=15 and gain>=4)
FOREIGN=re.compile(r'[Ͱ-ϿЀ-ӿ￠-￦¢©«®»™\\]')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=0);args=parser.parse_args()
    start=time.time();kiwi=Kiwi(num_workers=4)
    with core.connect() as db:
        rows=db.execute("SELECT x.display,x.kind,b.title,p.pdf_page FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id WHERE x.kind IN ('body','table','note') AND b.category!='참고자료'").fetchall()
    if args.limit:rows=rows[:args.limit]
    foreign=Counter();foreign_book=defaultdict(Counter);foreign_ctx=defaultdict(list);sentences_with_foreign=0
    words=Counter()
    for r in rows:
        t=r['display']
        hit=False
        for m in FOREIGN.finditer(t):
            ch=m.group();foreign[ch]+=1;foreign_book[r['title']][ch]+=1;hit=True
            if len(foreign_ctx[ch])<4:foreign_ctx[ch].append(f"{r['title']} p{r['pdf_page']}: {t[max(0,m.start()-18):m.end()+18]}".replace('\n',' '))
        sentences_with_foreign+=hit
        for w in re.findall(r'[가-힣]{2,}',t):words[w]+=1
    print(f'passages {len(rows)}; foreign symbols {sum(foreign.values())} in {sentences_with_foreign} passages; distinct words {len(words)} ({round(time.time()-start)}s)',flush=True)
    # Candidate corrections: words containing a suspect syllable.
    candidates={}
    suspects=[w for w in words if any(s in w for s in PAIRS)]
    print('suspect word forms',len(suspects),flush=True)
    def score(word):
        return kiwi.analyze(word,top_n=1)[0][1]
    checked=0
    for w in suspects:
        options=set()
        for s,rep in PAIRS.items():
            if s not in w:continue
            for i in [m.start() for m in re.finditer(re.escape(s),w)]:
                fixed=w[:i]+rep+w[i+1:]
                if fixed!=w and words.get(fixed,0)>=MIN_TARGET and words[fixed]>words[w]:options.add(fixed)
        if not options:continue
        base=score(w);checked+=1
        best=None
        for fixed in options:
            gain=score(fixed)-base
            if gain>=MIN_GAIN and (best is None or gain>best[1]):best=(fixed,gain)
        if best and accept(w,best[0],words[w],words[best[0]],best[1]):candidates[w]={'to':best[0],'count':words[w],'target_count':words[best[0]],'gain':round(best[1],2)}
        if checked%2000==0:print('scored',checked,'accepted',len(candidates),flush=True)
    accepted=dict(sorted(candidates.items(),key=lambda kv:-kv[1]['count']))
    core.DATA.mkdir(exist_ok=True)
    audit={'generated':time.strftime('%Y-%m-%d %H:%M'),'passages':len(rows),'foreign_symbols':{'total':sum(foreign.values()),'passages':sentences_with_foreign,'by_char':[{'char':c,'code':f'U+{ord(c):04X}','name':unicodedata.name(c,'?'),'count':n,'samples':foreign_ctx[c]} for c,n in foreign.most_common()],'by_book':{k:sum(v.values()) for k,v in sorted(foreign_book.items(),key=lambda x:-sum(x[1].values()))}},
           'corrections':{'rule':f'같은 길이의 어절 전체 치환. 교정형이 말뭉치에 {MIN_TARGET}회 이상 나타나고 원형의 4배 이상 잦으며 Kiwi 점수가 6 이상 오르거나(또는 15배 이상·4 이상), 실제 단어 목록(LEGITIMATE)에 없을 때만 채택. 화면 표시에만 적용하고 원문·인용은 바꾸지 않음','checked_words':checked,'accepted':len(accepted),'occurrences':sum(v['count'] for v in accepted.values())}}
    (core.DATA/'glyph-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=1),encoding='utf-8')
    (core.DATA/'ocr-corrections.json').write_text(json.dumps({'generated':audit['generated'],'rule':audit['corrections']['rule'],'words':accepted},ensure_ascii=False,indent=1),encoding='utf-8')
    print('accepted corrections',len(accepted),'covering',audit['corrections']['occurrences'],'occurrences',f'({round(time.time()-start)}s)')
    for w,v in list(accepted.items())[:40]:print(f"  {w} -> {v['to']}  x{v['count']} (target x{v['target_count']}, gain {v['gain']})")

if __name__=='__main__':main()
