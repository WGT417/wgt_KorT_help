"""Write the term list and every card of it as static files under dist/terms/.

The public site used to ask Cloud Run for both. The service sleeps when idle
(min_instances 0), so the first visit after a quiet spell waited 5–16s for the
list and 4–10s more for the first card while the search model loaded; once warm
a card took 3–18ms on the server and ~0.24s end to end, nearly all of it the
hop from the Hosting edge to Cloud Run. A card depends only on the concept
entries, the term index, the 풀이 and the library, so it can be written ahead
and served from the Hosting CDN like app.js.

    dist/terms/index.json          the same body as GET /api/terms
    dist/terms/c/<name>.json       GET /api/terms/card?q=<label> as a visitor the admin
                                   has not let in gets it (server.closed_view): anyone
                                   can fetch these files, and the books are sold, so
                                   they carry no sentence of a book. A let-in account's
                                   page asks the server for the card with its quotes.

<name> is the first 16 hex digits of SHA-1 over the label as the list gives
it; the page computes the same name (dist/app.js termFile). A card the files
do not have — the list is older or newer than the files, or this script was
never run — is asked of the server as before, so a missing build only costs
speed. The folder is replaced whole, so no card of an old build lingers.

Run it after changing concepts/*.json, data/term-index.json,
data/term-notes.json or the library, then deploy hosting
(scripts/cloud.py hosting does both).

    python scripts/build_term_cards.py
"""
import sys,json,time,hashlib,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import ROOT

OUT=ROOT/'dist'/'terms'

def file_name(label):return hashlib.sha1(label.encode('utf-8')).hexdigest()[:16]

def dump(data):return json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()

def main():
    from server import term_card,catalog_body,closed_view
    started=time.monotonic()
    body=catalog_body();items=json.loads(body['plain'])['items']
    # Written outside dist/ first, so a build stopped halfway is never deployed.
    temporary=ROOT/'tmp'/'terms-build'
    shutil.rmtree(temporary,ignore_errors=True);(temporary/'c').mkdir(parents=True)
    (temporary/'index.json').write_bytes(body['plain'])
    written=0;empty=[];sizes=[];names={}
    for i,(label,*_) in enumerate(items,1):
        name=file_name(label)
        if name in names:sys.exit(f'파일 이름이 겹칩니다: {names[name]!r} / {label!r}')
        names[name]=label
        card=term_card(label)
        if card is None:empty.append(label);continue
        data=dump(closed_view(card));(temporary/'c'/(name+'.json')).write_bytes(data)
        written+=1;sizes.append(len(data))
        if i%500==0:print(f'{i:,} / {len(items):,}',flush=True)
    shutil.rmtree(OUT,ignore_errors=True);shutil.move(temporary,OUT)
    print(f'목록 {len(items):,}장 · 카드 파일 {written:,}개 · 비어 있어 서버에 맡긴 카드 {len(empty)}장'
          f' · 합계 {sum(sizes)/2**20:.1f}MB (평균 {sum(sizes)/max(written,1)/1024:.1f}KB, 최대 {max(sizes,default=0)/1024:.0f}KB)'
          f' · {time.monotonic()-started:.0f}초')
    if empty:print('비어 있는 카드:',', '.join(empty[:20])+(' …' if len(empty)>20 else ''))

if __name__=='__main__':main()
