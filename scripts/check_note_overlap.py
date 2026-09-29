"""How much of each term card's 풀이 is copied word for word from its own cited pages.

A character counts as copied when it sits inside a run of 20 or more characters
(spaces removed) that also appears on one of the pages the note cites. The
2026-09-29 round rewrote the 672 cards whose explanation was 60% or more copied
down to 0-19%, reading each page and writing in our own words; new rewrites
should stay under 20%. This only measures; it never edits the notes.

    python scripts/check_note_overlap.py                 # distribution + cards at 60%+
    python scripts/check_note_overlap.py --min 0.3       # list every card at 30%+
    python scripts/check_note_overlap.py --label 음보    # show the copied runs of one card
"""
import sys,json,re,argparse,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTES=ROOT/'data'/'term-notes.json'
RUN=20

def compact(t):return re.sub(r'\s+','',t or '')

class Pages:
    def __init__(self):self.db=sqlite3.connect(ROOT/'data'/'library.sqlite3');self.cache={}
    def text(self,pid):
        if pid not in self.cache:
            r=self.db.execute('select text from pages where id=?',(pid,)).fetchone();self.cache[pid]=compact(r[0]) if r else ''
        return self.cache[pid]
    def source(self,note):
        ids=dict.fromkeys(c.get('page_id') for c in note.get('citations',[]) if c.get('page_id'))
        return ''.join(self.text(p) for p in ids)

def copied(text,source):
    """Return (length, copied mask) of text against source, both space-free."""
    t=compact(text);mask=[False]*len(t)
    if len(t)<RUN or not source:return t,mask
    for i in range(len(t)-RUN+1):
        if t[i:i+RUN] in source:
            for j in range(i,i+RUN):mask[j]=True
    return t,mask

def share(text,source):
    t,mask=copied(text,source);return sum(mask)/len(t) if t else 0.0

def runs(text,source):
    t,mask=copied(text,source);out=[];i=0
    while i<len(t):
        if mask[i]:
            j=i
            while j<len(t) and mask[j]:j+=1
            out.append(t[i:j]);i=j
        else:i+=1
    return out

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--min',type=float,default=0.6,help='list cards whose explanation is at least this share copied')
    ap.add_argument('--label',help='show the copied runs of this one card')
    a=ap.parse_args()
    notes=json.loads(NOTES.read_text(encoding='utf-8'))['notes'];pages=Pages()
    if a.label:
        n=notes.get(a.label) or sys.exit(f'{a.label}: 풀이가 없습니다')
        src=pages.source(n)
        for part,text in [('정의',n['definition'])]+[('해설',x) for x in n['explanation']]:
            print(f'{part} {share(text,src):.0%}',runs(text,src) or '')
        return
    rows=[]
    for label,n in notes.items():
        src=pages.source(n)
        if not src:continue
        rows.append((share(' '.join(n['explanation']),src),share(n['definition'],src),label))
    bands=[(0.6,None),(0.3,0.6),(0.2,0.3),(0,0.2)]
    print(f'풀이 {len(rows)}장 (근거 쪽이 있는 것)')
    for lo,hi in bands:
        n=sum(lo<=r[0] and (hi is None or r[0]<hi) for r in rows)
        print(f'  해설 {lo:.0%} 이상'+(f' {hi:.0%} 미만' if hi else '')+f': {n}장')
    print(f'  정의 40% 이상: {sum(r[1]>=0.4 for r in rows)}장')
    hits=sorted((r for r in rows if r[0]>=a.min),reverse=True)
    for e,d,label in hits:print(f'{e:4.0%} {d:4.0%}  {label}')

if __name__=='__main__':main()
