"""Print an entry's current text, its source pages, and the best extra pages for its terms.
usage: pages_for.py <entry-id> [--extra N] [--max-chars N] [--terms a,b,c] [--books t1,t2] [--pages BOOK:P1,P2 ...]
"""
import sys,json,glob,re,argparse
import os;ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..'));sys.path.insert(0,ROOT)
import core
ap=argparse.ArgumentParser();ap.add_argument('id');ap.add_argument('--extra',type=int,default=6);ap.add_argument('--max-chars',type=int,default=2600)
ap.add_argument('--terms',default='');ap.add_argument('--books',default='');ap.add_argument('--pages',nargs='*',default=[]);ap.add_argument('--no-sources',action='store_true');ap.add_argument('--brief',action='store_true')
a=ap.parse_args()
def compact(t):return re.sub(r'\s+','',t or '').lower()
def clean(t):
    t=re.sub(r'[ \t]+\n','\n',t);t=re.sub(r'\n{3,}','\n\n',t);return t.strip()
entry=None;area=None
for f in sorted(glob.glob(os.path.join(ROOT,'concepts','*.json'))):
    d=json.load(open(f,encoding='utf-8'))
    for c in d['concepts']:
        if c['id']==a.id:entry=c;area=d['area']
if not entry and not a.pages:sys.exit('no entry '+a.id)
if entry and not a.brief:
    print('### ENTRY',entry['id'],'|',entry['label'],'|',entry.get('parent'),'| area',area)
    print('aliases:',entry.get('aliases'));print('summary:',entry.get('summary'))
    for p in entry.get('explanation',[]):print('-',p)
    print('sources:',[(s['book'],s['pdf_page'],s.get('status')) for s in entry.get('sources',[])])
terms=[t for t in a.terms.split(',') if t] or ([entry['label']]+list(entry.get('aliases',[])) if entry else [])
terms=[compact(t) for t in terms if len(compact(t))>=2 and re.search(r'[가-힣]',t)]
seen=set()
def show(row,tag):
    key=(row['title'],row['pdf_page'])
    if key in seen:return
    seen.add(key);t=clean(row['text'])
    if len(t)>a.max_chars:t=t[:a.max_chars]+' …[잘림]'
    print(f"\n## [{tag}] {row['title']} 자료{row['pdf_page']} 책{row['printed_page']}({row['number_status']}) q={row['quality']}\n{t}")
with core.connect() as db:
    for spec in a.pages:
        book,pages=spec.split(':');
        for p in pages.split(','):
            r=db.execute('SELECT b.title,p.pdf_page,p.printed_page,p.number_status,p.quality,p.text FROM pages p JOIN books b ON b.id=p.book_id WHERE b.title=? AND p.pdf_page=?',(book,int(p))).fetchone()
            if r:show(r,'요청')
    if entry and not a.no_sources:
        for s in entry.get('sources',[]):
            r=db.execute('SELECT b.title,p.pdf_page,p.printed_page,p.number_status,p.quality,p.text FROM pages p JOIN books b ON b.id=p.book_id WHERE b.title=? AND p.pdf_page=?',(s['book'],int(s['pdf_page']))).fetchone()
            if r:show(r,'근거 '+s.get('status',''))
    if a.extra>0 and terms:
        books=[b for b in a.books.split(',') if b]
        q='SELECT b.title,p.pdf_page,p.printed_page,p.number_status,p.quality,p.compact,p.text FROM pages p JOIN books b ON b.id=p.book_id WHERE b.category=?'
        args=[area or '문법']
        if books:q+=' AND b.title IN (%s)'%','.join('?'*len(books));args+=books
        scored=[]
        for r in db.execute(q,args):
            c=r['compact'] or ''
            if len(c)<300:continue
            score=0
            for t in terms:
                n=c.count(t)
                if n:score+=n*(len(t)**1.5)
            if score:scored.append((score*(0.6 if r['quality']=='review' else 1),r))
        scored.sort(key=lambda x:-x[0])
        for score,r in scored[:a.extra+len(seen)]:
            if len(seen)>=a.extra+(0 if a.no_sources else len(entry.get('sources',[]) if entry else [])):break
            show(r,f'추가 {score:.0f}')
