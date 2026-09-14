"""Validate the pre-written concept entries in concepts/*.json.

Checks shape, minimum content, unique ids and aliases, that every linked
concept exists, and that every cited book page exists in the library.
Exit code 1 on any error so it can run in the test suite.
"""
import sys,json,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core

REQUIRED=['id','label','parent','aliases','summary','sources','review']
MIN_EXPLANATION=400   # characters without spaces across the body (sections or explanation paragraphs)
ITEM_KEYS={'label','text','sub','examples','refs'}

def compact(t):return re.sub(r'\s+','',t)

def check_items(items,where,n_sources,errors,depth=0):
    """Validate the nested items of a document-style section; return their text."""
    text=''
    if not isinstance(items,list) or not items:errors.append(f'{where}: 항목이 비었음');return text
    for item in items:
        if isinstance(item,str):text+=item;continue
        if not isinstance(item,dict) or set(item)-ITEM_KEYS:errors.append(f'{where}: 항목 키는 {sorted(ITEM_KEYS)}만 가능');continue
        if not (item.get('label') or item.get('text')):errors.append(f'{where}: 항목에 label이나 text가 없음')
        text+=item.get('label','')+item.get('text','')+''.join(item.get('examples',[]))
        for i in item.get('refs',[]):
            if not isinstance(i,int) or not 0<=i<n_sources:errors.append(f'{where}: refs {i}가 sources 범위를 벗어남')
        if item.get('sub'):
            if depth>=2:errors.append(f'{where}: 항목은 두 단계까지만 중첩')
            text+=check_items(item['sub'],where,n_sources,errors,depth+1)
    return text

def body_text(c,where,errors):
    """Either document-style sections (schema 2) or explanation paragraphs (schema 1)."""
    sections=c.get('sections');paragraphs=c.get('explanation')
    if sections:
        if not isinstance(sections,list) or len(sections)<3:errors.append(f'{where}: sections가 3개보다 적음');return ''
        text=''
        for s in sections:
            if not isinstance(s,dict) or not s.get('heading'):errors.append(f'{where}: section에 heading이 없음');continue
            text+=s['heading']+s.get('intro','')+check_items(s.get('items'),f'{where} [{s["heading"]}]',len(c['sources']),errors)
        return text
    if paragraphs:
        if len(paragraphs)<3:errors.append(f'{where}: explanation이 3문단보다 짧음')
        return ''.join(paragraphs)
    errors.append(f'{where}: sections나 explanation이 없음');return ''

def main():
    errors=[];warnings=[];entries=[];alias_owner={}
    for path in sorted((core.ROOT/'concepts').glob('*.json')):
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('area') not in {'문식성','문법','문학'}:errors.append(f'{path.name}: area가 문식성·문법·문학 중 하나가 아님')
        for c in data.get('concepts',[]):
            c['_file']=path.name;entries.append(c)
    ids={c['id'] for c in entries}
    if len(ids)!=len(entries):errors.append('개념 id 중복')
    with core.connect() as db:
        titles={r['title']:r['id'] for r in db.execute('SELECT id,title FROM books')}
        for c in entries:
            where=f"{c['_file']} {c.get('id','?')}"
            for key in REQUIRED:
                if key not in c:errors.append(f'{where}: {key} 없음')
            if any(k not in c for k in REQUIRED):continue
            if len(compact(c['summary']))<40:errors.append(f'{where}: summary가 짧음')
            if len(compact(body_text(c,where,errors)))<MIN_EXPLANATION:errors.append(f'{where}: 본문이 공백 제외 {MIN_EXPLANATION}자보다 짧음')
            # Legacy fields are no longer shown on the card; only their shape is checked when present.
            for ex in c.get('examples',[])+c.get('counter_examples',[]):
                if not all(ex.get(k,'').strip() for k in ('case','verdict','why','source')):errors.append(f'{where}: 예·반례의 사례·판정·이유·출처가 비었음')
            for linked in c.get('confused_with',[]):
                if linked not in ids:errors.append(f'{where}: 없는 confused_with {linked}')
            for alias in [c['label']]+c['aliases']:
                key=compact(alias).lower()
                # Shared aliases are allowed (the matcher shows both); report them so authors can tighten.
                if key in alias_owner and alias_owner[key]!=c['id']:warnings.append(f'{where}: 별칭 "{alias}"이 {alias_owner[key]}와 겹침')
                alias_owner.setdefault(key,c['id'])
            if not c['sources']:errors.append(f'{where}: 개론서 근거가 없음')
            for s in c['sources']:
                book=titles.get(s.get('book'))
                if not book:errors.append(f'{where}: 서재에 없는 책 {s.get("book")}');continue
                row=db.execute('SELECT id FROM pages WHERE book_id=? AND pdf_page=?',(book,int(s.get('pdf_page',0)))).fetchone()
                if not row:errors.append(f'{where}: {s["book"]} 자료 {s.get("pdf_page")}페이지가 없음')
                if s.get('status') not in {'verified','candidate'}:errors.append(f'{where}: 근거 status는 verified 또는 candidate여야 함')
            if c['review'].get('status') not in {'draft','reviewed'}:errors.append(f'{where}: review.status는 draft 또는 reviewed여야 함')
    for w in warnings:print(' (참고)',w)
    if errors:
        print('개념 사전 검사 실패');[print(' -',e) for e in errors];sys.exit(1)
    by_area={}
    for c in entries:by_area[c['_file']]=by_area.get(c['_file'],0)+1
    print(f'개념 {len(entries)}개 · 검수 완료 {sum(c["review"].get("status")=="reviewed" for c in entries)}개 · 파일별 {by_area}')
    print(f'근거 쪽 {sum(len(c["sources"]) for c in entries)}곳 · 대조 완료 {sum(s.get("status")=="verified" for c in entries for s in c["sources"])}곳')

if __name__=='__main__':main()
